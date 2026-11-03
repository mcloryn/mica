"""PROD-8: persiapan data suara publik E-05 (docs/AMANDEMEN-2026-11-03b.md B).

Arsip Common Voice sintetis: struktur cv-corpus-<versi>/<locale>/{validated.tsv, clips/*.mp3}
dan kolom validated.tsv mengikuti dokumentasi dataset Common Voice; MP3 dibuat di tes dengan
PyAV (libmp3lame). Tidak ada file dataset asli yang dibuka.
"""

import io
import json
import tarfile
import wave
from pathlib import Path

import numpy as np
import pytest

import mica.eval.__main__ as cli
from mica.eval import public_speech as ps
from mica.eval.stt import load_manifest

CV_COLUMNS = ("client_id", "path", "sentence_id", "sentence", "sentence_domain", "up_votes",
              "down_votes", "age", "gender", "accents", "variant", "locale", "segment")  # fmt: skip
ROOT_DIR = "cv-corpus-27.0-2026-09-12/id"


def mp3_bytes(seconds=0.3, rate=48000, freq=440.0):
    import av

    buf = io.BytesIO()
    with av.open(buf, "w", format="mp3") as c:
        s = c.add_stream("libmp3lame", rate=rate)
        s.layout = "mono"
        t = np.arange(int(seconds * rate)) / rate
        data = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
        n = s.codec_context.frame_size or 1152
        for i in range(0, len(data), n):
            frame = av.AudioFrame.from_ndarray(data[None, i : i + n].copy(), format="fltp",
                                               layout="mono")  # fmt: skip
            frame.rate = rate
            for p in s.encode(frame):
                c.mux(p)
        for p in s.encode(None):
            c.mux(p)
    return buf.getvalue()


def _add(tar, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


# penutur a punya 3 klip, b 2, c-e 1; satu baris tanpa kalimat dibuang
ROWS = [
    ("spk-a", "common_voice_id_1.mp3", "Selamat pagi semua."),
    ("spk-a", "common_voice_id_2.mp3", "Kampus dibuka jam tujuh."),
    ("spk-a", "common_voice_id_3.mp3", "Terima kasih."),
    ("spk-b", "common_voice_id_4.mp3", "Saya ingin mendaftar."),
    ("spk-b", "common_voice_id_5.mp3", "Berapa biayanya?"),
    ("spk-c", "common_voice_id_6.mp3", 'Dia berkata "halo".'),
    ("spk-d", "common_voice_id_7.mp3", "Hujan turun deras."),
    ("spk-e", "common_voice_id_8.mp3", "Buku itu merah."),
    ("spk-f", "common_voice_id_9.mp3", ""),
]


def make_archive(path, rows=ROWS, tsv_name="validated.tsv", extra_clip=True):
    lines = ["\t".join(CV_COLUMNS)]
    for spk, clip, sentence in rows:
        values = {"client_id": spk, "path": clip, "sentence": sentence, "locale": "id"}
        lines.append("\t".join(values.get(c, "") for c in CV_COLUMNS))
    with tarfile.open(path, "w:gz") as tar:
        for _spk, clip, _s in rows:  # klip sebelum TSV: pembaca harus dua lintasan
            _add(tar, f"{ROOT_DIR}/clips/{clip}", mp3_bytes())
        if extra_clip:
            _add(tar, f"{ROOT_DIR}/clips/common_voice_id_99.mp3", mp3_bytes())
        _add(tar, f"{ROOT_DIR}/{tsv_name}", ("\n".join(lines) + "\n").encode("utf-8"))
        _add(tar, f"{ROOT_DIR}/invalidated.tsv", b"client_id\tpath\tsentence\n")
    return path


def test_decode_mp3_to_16k_mono_int16():
    pcm = ps.decode_to_16k(mp3_bytes(seconds=0.5))
    assert pcm.dtype == np.int16 and abs(len(pcm) / 16000 - 0.5) < 0.06
    assert np.abs(pcm).max() > 5000


def test_select_one_clip_per_speaker_deterministic():
    clips = [ps.CvClip(p, s, t) for s, p, t in ROWS if t]
    a = ps.select_clips(clips, 3, 20261103)
    assert a == ps.select_clips(clips, 3, 20261103)
    assert len(a) == 3 and len({c.speaker for c in a}) == 3
    everyone = ps.select_clips(clips, 300, 20261103)  # penutur kurang: ambil semua
    assert sorted(c.speaker for c in everyone) == ["spk-a", "spk-b", "spk-c", "spk-d", "spk-e"]


def test_prep_commonvoice_writes_wav_manifest_and_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path / "repo")
    archive = make_archive(tmp_path / "cv.tar.gz")
    out = tmp_path / "publik"
    ids = tmp_path / "repo" / "clip_ids.txt"
    info = ps.prep_commonvoice(archive, out, 4, 20261103, ids, progress=lambda s: None)
    assert info["n_selected"] == 4 and info["n_speakers"] == 5 and info["n_validated_clips"] == 8
    rows = [
        json.loads(line) for line in (out / "commonvoice.jsonl").read_text("utf-8").splitlines()
    ]
    assert len(rows) == 4 and all(r["status"] == "ucapan" and r["jenis"] == "pertanyaan"
                                  for r in rows)  # fmt: skip
    assert [r["penutur"] for r in rows] == ["CV001", "CV002", "CV003", "CV004"]
    text = (out / "commonvoice.jsonl").read_text("utf-8") + (out / "commonvoice.json").read_text(
        "utf-8"
    )
    assert "spk-" not in text  # client_id tidak pernah ditulis
    assert ids.read_text("utf-8").split() == [r["id"] for r in rows]
    with wave.open(str(out / rows[0]["file"]), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
    # manifest bisa dibaca eval stt (format SDD 6.3)
    items = load_manifest(out / "commonvoice.jsonl")
    assert len(items) == 4 and items[0].kind == "pertanyaan" and items[0].reference


def test_prep_commonvoice_refuses_out_inside_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path)
    with pytest.raises(ps.PublicDataError, match="di luar repo"):
        ps.prep_commonvoice(make_archive(tmp_path / "cv.tar.gz"), tmp_path / "out", 2, 1, None)


def test_prep_commonvoice_needs_validated_tsv(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path / "repo")
    archive = make_archive(tmp_path / "cv.tar.gz", tsv_name="train.tsv")
    with pytest.raises(ps.PublicDataError, match="validated.tsv"):
        ps.prep_commonvoice(archive, tmp_path / "out", 2, 1, None)


def test_prep_commonvoice_refuses_non_empty_out(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path / "repo")
    (tmp_path / "out" / "commonvoice").mkdir(parents=True)
    (tmp_path / "out" / "commonvoice" / "x.wav").write_bytes(b"")
    with pytest.raises(ps.PublicDataError, match="sudah berisi"):
        ps.prep_commonvoice(make_archive(tmp_path / "cv.tar.gz"), tmp_path / "out", 2, 1, None)


def test_cli_prep_commonvoice(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path / "repo")
    archive = make_archive(tmp_path / "cv.tar.gz")
    code = cli.main(["prep-commonvoice", "--archive", str(archive), "--out",
                     str(tmp_path / "out"), "--n", "300", "--ids-out",
                     str(tmp_path / "ids.txt")])  # fmt: skip
    assert code == 0
    assert "5 klip dari 5 penutur" in capsys.readouterr().out
    assert len(Path(tmp_path / "ids.txt").read_text("utf-8").split()) == 5


# --- MUSAN (hf_hub di-mock, tanpa internet) -----------------------------------------------

HF_FILES = (
    [f"noise/free-sound/noise-free-sound-{i:04d}.wav" for i in range(12)]
    + [f"noise/sound-bible/noise-sound-bible-{i:04d}.wav" for i in range(3)]
    + ["noise/free-sound/LICENSE", "noise/sound-bible/LICENSE", "noise/free-sound/ANNOTATIONS",
       "noise/README", "music/fma/music-fma-0000.wav", "speech/librivox/speech-0000.wav",
       "README.md"]
)  # fmt: skip


def _wav_bytes(seconds, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        t = np.arange(int(seconds * rate)) / rate
        w.writeframes((3000 * np.sin(2 * np.pi * 300 * t)).astype(np.int16).tobytes())
    return buf.getvalue()


class FakeHub:
    def __init__(self):
        self.downloaded = []

    def list_files(self, repo, revision):
        assert (repo, revision) == (ps.MUSAN_REPO, ps.MUSAN_REVISION)
        return list(HF_FILES)

    def download(self, repo, revision, filename, local_dir):
        self.downloaded.append(filename)
        path = Path(local_dir) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if filename.endswith("LICENSE"):
            path.write_text(f"lisensi {filename}", encoding="utf-8")
        else:  # sound-bible pendek (4 s, 44,1 kHz); free-sound 12 s 16 kHz
            short = "sound-bible" in filename
            path.write_bytes(_wav_bytes(4 if short else 12, 44100 if short else 16000))
        return path


def test_select_musan_only_noise_wav_and_deterministic():
    a = ps.select_musan(HF_FILES, 5, 20261103)
    assert a == ps.select_musan(HF_FILES, 5, 20261103)
    assert len(set(a)) == 5 and all(f.startswith("noise/") and f.endswith(".wav") for f in a)
    assert len(ps.select_musan(HF_FILES, 100, 20261103)) == 15  # kurang dari n: semua


def test_prep_musan_downloads_only_selected_and_cuts(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path / "repo")
    hub = FakeHub()
    out = tmp_path / "publik"
    info = ps.prep_musan(out, 5, 20261103, 10.0, list_files=hub.list_files,
                         download=hub.download, progress=lambda s: None)  # fmt: skip
    wavs = [f for f in hub.downloaded if f.endswith(".wav")]
    assert wavs == ps.select_musan(HF_FILES, 5, 20261103)  # hanya file terpilih yang diunduh
    assert sorted(f for f in hub.downloaded if f.endswith("LICENSE")) == [
        "noise/free-sound/LICENSE", "noise/sound-bible/LICENSE"]  # fmt: skip
    assert (out / "musan" / "LICENSE-free-sound").read_text("utf-8").startswith("lisensi")
    assert not (out / "musan-raw").exists()  # unduhan mentah dihapus
    rows = [json.loads(x) for x in (out / "musan.jsonl").read_text("utf-8").splitlines()]
    assert all(r["jenis"] == "bising" and r["status"] == "bukan ucapan" for r in rows)
    for r in rows:
        with wave.open(str(out / r["file"]), "rb") as w:
            assert w.getframerate() == 16000 and w.getnchannels() == 1
            expected = 4.0 if "sound-bible" in r["asal"] else 10.0
            assert abs(w.getnframes() / 16000 - expected) < 0.05
    assert info["n_noise_wav"] == 15 and info["revision"] == ps.MUSAN_REVISION
    assert set(info["shorter_than_clip_s"]) == {
        r["asal"] for r in rows if "sound-bible" in r["asal"]
    }


def test_prep_musan_requires_locked_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path / "repo")
    with pytest.raises(ps.PublicDataError, match="hash commit"):
        ps.prep_musan(tmp_path / "out", 5, 1, 10.0, revision="main")


# --- diam dan manifest gabungan -----------------------------------------------------------


def test_prep_silence_with_fake_recorder(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path / "repo")
    calls = []

    def record(seconds, device):
        calls.append((seconds, device))
        return np.zeros(int(seconds * 16000), dtype=np.int16)

    out = tmp_path / "publik"
    ps.prep_silence(out, 3, 2.0, device=1, record=record, progress=lambda s: None)
    assert calls == [(2.0, 1)] * 3
    rows = [json.loads(x) for x in (out / "silence.jsonl").read_text("utf-8").splitlines()]
    assert [r["id"] for r in rows] == ["diam-01", "diam-02", "diam-03"]
    assert all(r["jenis"] == "diam" and r["status"] == "bukan ucapan" for r in rows)


def test_prep_manifest_merges_sources_for_eval_stt(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path / "repo")
    out = tmp_path / "publik"
    ps.prep_commonvoice(make_archive(tmp_path / "cv.tar.gz"), out, 2, 1, None,
                        progress=lambda s: None)  # fmt: skip
    with pytest.raises(ps.PublicDataError, match="belum ada"):
        ps.prep_manifest(out)
    hub = FakeHub()
    ps.prep_musan(out, 2, 1, 10.0, list_files=hub.list_files, download=hub.download,
                  progress=lambda s: None)  # fmt: skip
    ps.prep_silence(out, 2, 1.0, record=lambda s, d: np.zeros(16000, np.int16),
                    progress=lambda s: None)  # fmt: skip
    counts = ps.prep_manifest(out)
    assert counts == {"pertanyaan": 2, "bising": 2, "diam": 2}
    items = load_manifest(out / "manifest.jsonl")
    assert {i.kind for i in items} == {"pertanyaan", "bising", "diam"}


def test_cli_prep_silence_refused_in_prod(tmp_path, capsys):
    prod = Path(__file__).resolve().parents[2] / "config" / "prod.yaml"
    code = cli.main(["prep-silence", "--config", str(prod), "--out", str(tmp_path / "o")])
    assert code == 2 and "mode prod" in capsys.readouterr().err


def test_cli_prep_silence_refused_in_prod_even_when_complete(tmp_path, monkeypatch):
    from mica.config import load_settings

    dev = Path(__file__).resolve().parents[2] / "config" / "dev.yaml"
    s = load_settings(dev)
    prod = s.model_copy(update={"app": s.app.model_copy(update={"mode": "prod"})})
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: prod)
    args = cli.build_parser().parse_args(["prep-silence", "--config", "x", "--out",
                                          str(tmp_path / "o")])  # fmt: skip
    with pytest.raises(cli.SttEvalError, match="app.mode: dev"):
        cli.cmd_prep_silence(args)
