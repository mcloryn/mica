"""M-12 eval stt (E-05): manifest, metrik, transkripsi palsu, Recall@5, Groq palsu, kiosk.

Tanpa mikrofon, model, atau jaringan: VAD dan STT palsu dari tests/fakes.py. Angka di sini data
uji, bukan ambang.
"""

import csv
import json
import wave
from pathlib import Path

import numpy as np
import pytest
from tests.fakes import FakeStt, fake_prob

import mica.eval.__main__ as cli
from mica.audio.stt import GROQ_STT_URL, FasterWhisperStt, GroqWhisperStt, Transcript
from mica.audio.vad import CHUNK_SAMPLES, SpeechSegmenter
from mica.eval import stt as e05

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
KIOSK_YAML = ROOT / "config" / "kiosk.yaml"
TRIAL = ["--vad-threshold", "0.5", "--min-silence-ms", "160", "--max-utterance-s", "10"]


def _segmenter():
    return SpeechSegmenter(0.5, 160, 10.0, prob=fake_prob())  # 160 ms = 5 potongan


def _pcm(*parts):
    out = []
    for kind, n in parts:
        out.append(np.full(n * CHUNK_SAMPLES, 1000 if kind == "bicara" else 0, dtype=np.int16))
    return np.concatenate(out)


def _wav(path, pcm, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.asarray(pcm, dtype=np.int16).tobytes())


def _manifest(folder, rows):
    path = folder / "manifest.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


ROWS = [
    {"id": "q1", "file": "q1.wav", "jenis": "pertanyaan", "referensi": "biaya kuliah berapa",
     "qid": "d001", "penutur": "P01", "persetujuan": True},
    {"id": "d1", "file": "d1.wav", "jenis": "diam", "penutur": "P01", "persetujuan": True},
    {"id": "b1", "file": "b1.wav", "jenis": "bising", "penutur": "P02", "persetujuan": True},
]  # fmt: skip


def _item(kind="pertanyaan", reference="biaya kuliah berapa", qid=None):
    return e05.SpeechItem("x", Path("x.wav"), kind, reference, qid, "P01")


# --- manifest ---------------------------------------------------------------------------


def test_manifest_valid(tmp_path):
    items = e05.load_manifest(_manifest(tmp_path, ROWS))
    assert [i.kind for i in items] == ["pertanyaan", "diam", "bising"]
    assert items[0].file == tmp_path / "q1.wav" and items[0].qid == "d001"
    assert items[1].reference is None and items[1].qid is None


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"persetujuan": False}, "persetujuan bukan true"),
        ({"persetujuan": "ya"}, "persetujuan bukan true"),
        ({"persetujuan": None}, "persetujuan bukan true"),
        ({"jenis": "lain"}, "jenis"),
        ({"referensi": ""}, "referensi wajib"),
        ({"penutur": ""}, "penutur wajib"),
    ],
)
def test_manifest_rejects(tmp_path, change, message):
    with pytest.raises(e05.ManifestError, match=message):
        e05.load_manifest(_manifest(tmp_path, [{**ROWS[0], **change}, ROWS[1]]))


def test_manifest_without_consent_rejects_whole_file(tmp_path):
    rows = [ROWS[0], {**ROWS[1], "persetujuan": False}]
    with pytest.raises(e05.ManifestError, match="d1: persetujuan"):
        e05.load_manifest(_manifest(tmp_path, rows))


def test_manifest_duplicate_id(tmp_path):
    with pytest.raises(e05.ManifestError, match="id ganda"):
        e05.load_manifest(_manifest(tmp_path, [ROWS[1], ROWS[1]]))


def test_example_manifest_in_repo_is_valid():
    items = e05.load_manifest(ROOT / "data" / "eval" / "speech" / "contoh" / "manifest.jsonl")
    assert {i.kind for i in items} == {"pertanyaan", "diam", "bising"}


def test_read_wav_requires_16k_mono(tmp_path):
    _wav(tmp_path / "a.wav", np.zeros(100), rate=16000)
    assert len(e05.read_wav(tmp_path / "a.wav")) == 100
    _wav(tmp_path / "b.wav", np.zeros(100), rate=44100)
    with pytest.raises(e05.ManifestError, match="16 kHz"):
        e05.read_wav(tmp_path / "b.wav")


# --- metrik -------------------------------------------------------------------------------


def test_question_metrics_and_time_to_text():
    pcm = _pcm(("diam", 3), ("bicara", 10))  # berakhir tanpa diam: ekor ditambahkan
    r = e05.evaluate_item(_item(), pcm, _segmenter(), FakeStt(["biaya kuliah berapa"]), None)
    assert r.hypothesis == "biaya kuliah berapa" and r.wer == 0 and r.cer == 0
    assert r.n_utterances == 1 and r.false_transcript is None
    assert r.vad_end_s == pytest.approx(5 * CHUNK_SAMPLES / 16000)  # = min_silence 160 ms
    assert r.time_to_text_s == pytest.approx(r.vad_end_s + r.stt_s)


def test_wrong_transcript_wer_and_cer():
    pcm = _pcm(("bicara", 10), ("diam", 6))
    r = e05.evaluate_item(_item(), pcm, _segmenter(), FakeStt(["biaya kulia"]), None)
    assert r.wer == pytest.approx(2 / 3)  # satu substitusi + satu penghapusan
    assert 0 < r.cer < r.wer


def test_false_transcript_on_silence_and_noise():
    # "terima kasih" palsu dari bunyi pendek pada rekaman diam
    pcm = _pcm(("diam", 5), ("bicara", 10), ("diam", 6))
    r = e05.evaluate_item(_item("diam", None), pcm, _segmenter(), FakeStt(["terima kasih"]), None)
    assert r.false_transcript == 1 and r.wer is None
    quiet = e05.evaluate_item(_item("bising", None), _pcm(("diam", 20)), _segmenter(),
                              FakeStt(["x"]), None)  # fmt: skip
    assert quiet.false_transcript == 0 and quiet.n_utterances == 0 and quiet.time_to_text_s is None


def test_min_speech_filter_counts_and_skips_stt():
    stt = FakeStt(["terima kasih"])
    pcm = _pcm(("bicara", 3), ("diam", 6))  # 96 ms
    r = e05.evaluate_item(_item("diam", None), pcm, _segmenter(), stt, 100)
    assert r.filtered_by == ("min_speech",) and r.false_transcript == 0 and stt.calls == 0


def test_no_speech_filter_counted():
    class NoSpeechStt:
        def transcribe(self, pcm):
            return Transcript("", False, 0.2, len(pcm) / 16000, filtered_by="no_speech")

    r = e05.evaluate_item(_item("bising", None), _pcm(("bicara", 10), ("diam", 6)),
                          _segmenter(), NoSpeechStt(), None)  # fmt: skip
    assert r.filtered_by == ("no_speech",) and r.false_transcript == 0


def test_false_rate_in_summary():
    results = [
        e05.ItemResult(_item("diam", None), "terima kasih", 3.0, 1, 0.5, 0.2, (), 1),
        e05.ItemResult(_item("diam", None), "", 3.0, 0, None, None, (), 0),
        e05.ItemResult(_item("bising", None), "", 3.0, 1, None, None, ("no_speech",), 0),
        e05.ItemResult(_item("bising", None), "halo", 3.0, 1, 0.4, 0.2, (), 1),
    ]
    s = e05.summarize("cfg", True, results)
    assert s.n_noise == 4 and s.n_false == 2 and s.false_rate == 0.5
    assert s.wer_total is None and s.n_questions == 0


def test_recall5_with_fake_retriever():
    def search(text):
        return ["c1", "c2"] if "biaya" in text else ["c9"]

    results = [
        e05.ItemResult(_item(qid="d001"), "biaya kuliah", 2.0, 1, 0.5, 0.2, ()),  # hit/hit
        e05.ItemResult(_item(qid="d002"), "bia kuli", 2.0, 1, 0.5, 0.2, ()),  # miss/hit
        e05.ItemResult(_item(qid="d003"), "", 2.0, 0, None, None, ()),  # transkripsi kosong
        e05.ItemResult(_item(qid=None), "biaya", 2.0, 1, 0.5, 0.2, ()),  # tanpa qid
    ]
    e05.add_retrieval(results, search, {"d001": ["c2"], "d002": ["c1"], "d003": ["c1"]})
    assert [r.hit5_hyp for r in results] == [True, False, False, None]
    assert [r.hit5_ref for r in results] == [True, True, True, None]
    s = e05.summarize("cfg", True, results)
    assert s.n_retrieval == 3 and s.recall5_hyp == pytest.approx(1 / 3) and s.recall5_ref == 1.0


def test_run_eval_writes_csv_without_audio_and_scrubs(tmp_path):
    items = [_item(), _item("diam", None)]
    items[1] = e05.SpeechItem("d1", Path("d1.wav"), "diam", None, None, "P01")
    audio = {"x": _pcm(("bicara", 10), ("diam", 6)), "d1": _pcm(("diam", 20))}
    cand = e05.SttCandidate("palsu", True, FakeStt(["nomor saya 081234567890"]), {"b": "palsu"})
    summaries = e05.run_eval(items, audio, [cand], _segmenter, None, tmp_path / "run",
                             {"note": "uji"}, progress=lambda s: None)  # fmt: skip
    run = tmp_path / "run"
    assert sorted(p.name for p in run.rglob("*")) == ["palsu", "per_item.csv", "run.json",
                                                      "summary.csv"]  # fmt: skip
    rows = list(csv.DictReader((run / "palsu" / "per_item.csv").open(encoding="utf-8-sig")))
    assert "081234567890" not in rows[0]["hipotesis_norm"]
    info = json.loads((run / "palsu" / "run.json").read_text(encoding="utf-8"))
    assert info["note"] == "uji" and info["stt"] == {"b": "palsu"}
    # nomor dibaca per digit oleh normalize_for_wer: banyak sisipan, WER > 1
    assert summaries[0].n_questions == 1 and summaries[0].wer_total > 1


def test_run_eval_loads_retriever_only_after_all_stt(tmp_path):
    order = []

    class LoggingStt(FakeStt):
        def transcribe(self, pcm16k):
            order.append("stt")
            return super().transcribe(pcm16k)

    def retrieval():
        order.append("retriever")
        return (lambda text: ["c1"]), {"d001": ["c1"]}

    items = [_item(qid="d001"), e05.SpeechItem("y", Path("y.wav"), "pertanyaan", "biaya", "d001",
                                               "P02")]  # fmt: skip
    audio = {i.id: _pcm(("bicara", 10), ("diam", 6)) for i in items}
    cands = [e05.SttCandidate(f"k{n}", True, LoggingStt(["biaya"] * 2), {}) for n in (1, 2)]
    summaries = e05.run_eval(items, audio, cands, _segmenter, None, tmp_path / "run", {},
                             retrieval=retrieval, progress=lambda s: None,
                             loaded_modules=list,
                             late_info=lambda: {"environment": {"x": 1}})  # fmt: skip
    assert order == ["stt"] * 4 + ["retriever"]
    assert all(s.recall5_hyp == 1.0 for s in summaries)
    info = json.loads((tmp_path / "run" / "k1" / "run.json").read_text(encoding="utf-8"))
    assert info["timing"]["retriever_loaded_during_stt"] is False
    assert info["timing"]["heavy_modules_loaded_after_stt"] == []
    assert info["environment"] == {"x": 1}


def test_format_table_follows_rule_and_picks_no_winner():
    s = e05.Summary("a", True, 1, 2, 0.2, 0.1, 1.0, 3.5, 1, 0.5, 1, 1.0, 1.0, 1)
    table = e05.format_table([s])
    assert e05.E05_RULE in table and "tidak dipilih otomatis" in table
    assert "| tidak |" in table  # p95 3,5 s > 3 s


# --- backend --------------------------------------------------------------------------------


class FakeSegment:
    def __init__(self, text):
        self.text, self.no_speech_prob, self.avg_logprob = text, 0.1, -0.2


def test_faster_whisper_hotwords_forwarded(tmp_path):
    from mica.audio.stt import MODEL_FILES

    for name in MODEL_FILES:
        (tmp_path / name).write_bytes(b"x")
    calls = []

    class Model:
        def transcribe(self, audio, **kwargs):
            calls.append(kwargs)
            return iter([FakeSegment("halo")]), None

    stt = FasterWhisperStt(tmp_path, loader=lambda *a: Model(), hotwords="PMB, SKS")
    stt.transcribe(np.zeros(1600, dtype=np.int16))
    assert calls[0]["hotwords"] == "PMB, SKS"
    FasterWhisperStt(tmp_path, loader=lambda *a: Model()).transcribe(np.zeros(16, dtype=np.int16))
    assert "hotwords" not in calls[1]


def test_groq_whisper_with_fake_http():
    sent = []

    def post(url, headers, data, files):
        sent.append((url, headers, data, files))
        return {"text": " Biaya kuliah berapa? ",
                "segments": [{"no_speech_prob": 0.1, "avg_logprob": -0.3}]}  # fmt: skip

    stt = GroqWhisperStt("kunci-rahasia", "whisper-large-v3-turbo", 0.6, post=post)
    t = stt.transcribe(np.zeros(16000, dtype=np.int16))
    assert t.ok and t.text == "Biaya kuliah berapa?" and t.audio_s == 1.0
    url, headers, data, files = sent[0]
    assert url == GROQ_STT_URL == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert headers == {"Authorization": "Bearer kunci-rahasia"}
    assert data == {"model": "whisper-large-v3-turbo", "language": "id",
                    "response_format": "verbose_json", "temperature": "0"}  # fmt: skip
    _name, wav, mime = files["file"]
    assert wav[:4] == b"RIFF" and mime == "audio/wav"
    assert "kunci-rahasia" not in repr(stt)


def test_groq_no_speech_filter_and_unknown_model():
    def post(url, headers, data, files):
        return {"text": "terima kasih", "segments": [{"no_speech_prob": 0.9, "avg_logprob": -1}]}

    t = GroqWhisperStt("k", "whisper-large-v3", 0.6, post=post).transcribe(np.zeros(160))
    assert (t.ok, t.text, t.filtered_by) == (False, "", "no_speech")
    with pytest.raises(ValueError, match="tidak dikenal"):
        GroqWhisperStt("k", "whisper-x", None)


# --- CLI ------------------------------------------------------------------------------------


def test_eval_stt_refused_in_kiosk(tmp_path, capsys):
    manifest = _manifest(tmp_path, [ROWS[1]])
    code = cli.main(["stt", "--config", str(KIOSK_YAML), "--dataset", str(manifest), *TRIAL])
    assert code == 2
    err = capsys.readouterr().err
    assert "app.mode: dev" in err or "mode kiosk" in err


def test_eval_stt_refused_in_kiosk_even_when_complete(tmp_path, monkeypatch):
    from mica.config import load_settings

    settings = load_settings(DEV_YAML)
    kiosk = settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "kiosk"})})
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: kiosk)
    args = cli.build_parser().parse_args(["stt", "--config", "x", "--dataset", "y", *TRIAL])
    with pytest.raises(cli.SttEvalError, match="app.mode: dev"):
        cli.cmd_stt(args)


def _groq_settings(model, key="kunci-palsu"):
    from pydantic import SecretStr

    from mica.config import load_settings

    s = load_settings(DEV_YAML)
    stt = s.audio.stt.model_copy(update={"groq_model": model})
    audio = s.audio.model_copy(update={"stt": stt})
    keys = s.api_keys.model_copy(update={"groq": SecretStr(key) if key else None})
    return s.model_copy(update={"audio": audio, "api_keys": keys})


def _groq_args(*extra):
    return cli.build_parser().parse_args(["stt", "--config", "x", "--dataset", "y",
                                          "--backend", "groq", *extra, *TRIAL])  # fmt: skip


def test_eval_stt_groq_model_from_config_or_flag():
    (cand,) = cli.stt_candidates(_groq_args(), _groq_settings("whisper-large-v3-turbo"), None)
    assert cand.stt.model == "whisper-large-v3-turbo" and not cand.local
    assert cand.info["model_source"] == "audio.stt.groq_model"
    (cand,) = cli.stt_candidates(_groq_args("--groq-model", "whisper-large-v3"),
                                 _groq_settings("whisper-large-v3-turbo"), None)  # fmt: skip
    assert cand.stt.model == "whisper-large-v3" and cand.info["model_source"] == "--groq-model"
    assert "kunci-palsu" not in json.dumps(cand.info)


def test_eval_stt_groq_needs_model_and_key():
    with pytest.raises(cli.SttEvalError, match="audio.stt.groq_model"):
        cli.stt_candidates(_groq_args(), _groq_settings(None), None)
    with pytest.raises(cli.SttEvalError, match="GROQ_API_KEY"):
        cli.stt_candidates(_groq_args(), _groq_settings("whisper-large-v3", key=None), None)


def test_eval_stt_end_to_end_with_fakes(tmp_path, capsys):
    for row, pcm in zip(ROWS, (_pcm(("bicara", 10), ("diam", 6)), _pcm(("diam", 20)),
                               _pcm(("bicara", 2), ("diam", 6))), strict=True):  # fmt: skip
        _wav(tmp_path / row["file"], pcm)
    manifest = _manifest(tmp_path, ROWS)

    def candidates(args, settings, no_speech):
        return [e05.SttCandidate("palsu", True, FakeStt(["biaya kuliah berapa"]), {})]

    args = cli.build_parser().parse_args([
        "stt", "--config", str(DEV_YAML), "--dataset", str(manifest), "--out",
        str(tmp_path / "out"), "--run-name", "r1", "--min-speech-ms", "100", *TRIAL])  # fmt: skip
    code = cli.cmd_stt(args, candidates, lambda a, s, i: (lambda t: ["c1"], {"d001": ["c1"]}),
                       prob_factory=fake_prob)  # fmt: skip
    assert code == 0
    out = capsys.readouterr().out
    assert "nilai coba" in out and "tidak dipilih otomatis" in out
    summary = next(iter(csv.DictReader((tmp_path / "out" / "r1" / "summary.csv").open(
        encoding="utf-8-sig"))))  # fmt: skip
    assert summary["wer_total"] == "0.0000" and summary["laju_transkripsi_palsu"] == "0.0000"
    assert summary["recall5_transkripsi"] == "1.0000"
    assert not list((tmp_path / "out").rglob("*.wav"))
