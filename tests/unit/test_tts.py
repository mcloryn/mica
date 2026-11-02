"""M-08 TTS: PiperTts (loader palsu), VoiceMissing, CLI fetch-voice dan say."""

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from tests.fakes import FakeTts

import mica.audio.__main__ as cli
from mica.audio.tts import AudioClip, PiperTts, VoiceMissing, voice_path
from mica.config import ConfigError, load_settings
from mica.core.types import ErrorCode

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
PROD_YAML = ROOT / "config" / "prod.yaml"


@dataclass
class FakeChunk:
    audio_int16_bytes: bytes
    sample_rate: int = 22050


class FakeVoice:
    def __init__(self):
        self.calls = []

    def synthesize(self, text, syn_config=None):
        self.calls.append((text, syn_config))
        for _sentence in text.split(". "):
            yield FakeChunk(np.ones(2205, dtype=np.int16).tobytes())


def _voice_files(tmp_path):
    onnx = tmp_path / "v.onnx"
    onnx.write_bytes(b"onnx")
    Path(f"{onnx}.json").write_text("{}", encoding="utf-8")
    return onnx


def _dev_settings():
    return load_settings(DEV_YAML)


def _prod_settings():
    s = _dev_settings()
    return s.model_copy(update={"app": s.app.model_copy(update={"mode": "prod"})})


def test_audio_clip_duration():
    assert AudioClip(np.zeros(22050, dtype=np.int16), 22050, 0.1).duration_s == 1.0


def test_voice_missing_code(tmp_path):
    with pytest.raises(VoiceMissing) as err:
        PiperTts(tmp_path / "tidak-ada.onnx", loader=lambda m, c: FakeVoice())
    assert err.value.code == ErrorCode.VOICE_MISSING
    assert "fetch-voice" in str(err.value)


def test_voice_config_json_also_required(tmp_path):
    onnx = tmp_path / "v.onnx"
    onnx.write_bytes(b"onnx")
    with pytest.raises(VoiceMissing):
        PiperTts(onnx, loader=lambda m, c: FakeVoice())


def test_piper_normalizes_and_streams_per_sentence(tmp_path):
    voice = FakeVoice()
    tts = PiperTts(_voice_files(tmp_path), loader=lambda m, c: voice)
    clips = list(tts.stream("Biaya Rp14.000.000 per tahun. Buka 09.00 WIB."))
    text, syn_config = voice.calls[0]
    assert (
        text
        == "Biaya empat belas juta rupiah per tahun. Buka pukul sembilan waktu Indonesia barat."
    )
    assert syn_config is None  # length_scale null = bawaan .onnx.json suara
    assert len(clips) == 2 and clips[0].samples.dtype == np.int16
    assert tts.synthesize("Satu. Dua").duration_s == pytest.approx(0.2)


def test_piper_length_scale_passed(tmp_path):
    voice = FakeVoice()
    tts = PiperTts(_voice_files(tmp_path), length_scale=1.1, loader=lambda m, c: voice)
    tts.synthesize("Halo")
    assert voice.calls[0][1].length_scale == 1.1


def test_config_tts_voice_and_length_scale(tmp_path):
    import yaml

    for path in (DEV_YAML, PROD_YAML):
        tts = yaml.safe_load(path.read_text(encoding="utf-8"))["audio"]["tts"]
        assert {k: tts[k] for k in ("voice", "length_scale")} == {
            "voice": "id_ID-news_tts-medium", "length_scale": None}  # fmt: skip
        assert "threads" in tts  # docs/CPU-THREADS.md; nilai dev boleh hasil pilih, prod null
    assert yaml.safe_load(PROD_YAML.read_text(encoding="utf-8"))["audio"]["tts"]["threads"] is None
    assert load_settings(DEV_YAML).audio.tts.length_scale is None
    assert (
        voice_path("id_ID-news_tts-medium").as_posix() == "models/piper/id_ID-news_tts-medium.onnx"
    )


def test_length_scale_null_allowed_in_prod(tmp_path):
    from test_config import _complete_prod_raw, _write

    raw = _complete_prod_raw()
    raw["audio"]["tts"]["length_scale"] = None
    settings = load_settings(_write(tmp_path, raw))
    assert settings.app.mode == "prod" and settings.audio.tts.length_scale is None
    raw["audio"]["tts"]["length_scale"] = 0
    with pytest.raises(ConfigError):
        load_settings(_write(tmp_path, raw))


# --- fetch-voice ----------------------------------------------------------------------


def test_fetch_voice_verifies_sha256(tmp_path, monkeypatch):
    payload = {name: name.encode() for name in cli.VOICE_SHA256}
    monkeypatch.setattr(
        cli, "VOICE_SHA256", {n: hashlib.sha256(b).hexdigest() for n, b in payload.items()}
    )
    urls = []

    def download(url, dest):
        urls.append(url)
        dest.write_bytes(payload[url.rsplit("/", 1)[1]])

    assert cli.cmd_fetch_voice(_dev_settings(), tmp_path, download) == 0
    assert all(f"/resolve/{cli.HF_REVISION}/id/id_ID/news_tts/medium/" in u for u in urls)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(payload)
    urls.clear()
    cli.cmd_fetch_voice(_dev_settings(), tmp_path, download)
    assert urls == []  # sudah ada dan cocok: tidak diunduh ulang


def test_fetch_voice_rejects_bad_sha256(tmp_path):
    def download(url, dest):
        dest.write_bytes(b"rusak")

    with pytest.raises(cli.AudioCliError, match="sha256"):
        cli.cmd_fetch_voice(_dev_settings(), tmp_path, download)
    assert list(tmp_path.iterdir()) == []


def test_fetch_voice_refused_in_prod(tmp_path):
    with pytest.raises(cli.AudioCliError, match="app.mode: dev"):
        cli.cmd_fetch_voice(_prod_settings(), tmp_path, lambda u, d: None)


# --- say ------------------------------------------------------------------------------


def _say(argv, tmp_path, answers=(), monkeypatch=None):
    played = []
    answers = list(answers)
    args = cli.build_parser().parse_args(["say", *argv, "--voices-dir", str(tmp_path / "v")])
    code = cli.cmd_say(
        args,
        _dev_settings(),
        tts_factory=FakeTts,
        play=lambda clip, device: played.append(clip.duration_s),
        ask=lambda prompt: answers.pop(0),
    )
    return code, played


def test_say_no_play_prints_measurements(tmp_path, capsys):
    code, played = _say(["Biaya Rp14.000.000. Buka 09.00 WIB.", "--no-play"], tmp_path)
    out = capsys.readouterr().out
    assert code == 0 and played == []
    assert "normal: Biaya empat belas juta rupiah." in out
    assert "synth_s" in out and "RTF" in out and "first_audio_s" in out


def test_say_rate_writes_only_ratings_and_run_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lines = tmp_path / "kalimat.txt"
    lines.write_text("Satu dua.\n\nRp15.000.000 per tahun.\n", encoding="utf-8")
    out = tmp_path / "results" / "pilot"
    before = set(tmp_path.rglob("*"))
    code, played = _say(
        ["--file", str(lines), "--rate", "--out", str(out)], tmp_path, answers=["x", "r", "1", "2"]
    )
    assert code == 0 and len(played) == 3  # dua baris + satu putar ulang
    created = set(tmp_path.rglob("*")) - before
    assert {p.relative_to(tmp_path).as_posix() for p in created if p.is_file()} == {
        "results/pilot/ratings.csv",
        "results/pilot/run.json",
    }
    with (out / "ratings.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == list(cli.RATING_FIELDS)
    assert [r["nilai"] for r in rows] == ["1", "2"]
    assert rows[1]["teks_normal"] == "lima belas juta rupiah per tahun."
    assert (out / "ratings.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    json.loads((out / "run.json").read_text(encoding="utf-8"))


def test_say_rate_needs_out_and_playback(tmp_path):
    with pytest.raises(cli.AudioCliError, match="--out"):
        _say(["Halo", "--rate"], tmp_path)
    with pytest.raises(cli.AudioCliError, match="pemutaran"):
        _say(["Halo", "--rate", "--no-play", "--out", str(tmp_path / "o")], tmp_path)


def test_say_refused_in_prod(tmp_path):
    args = cli.build_parser().parse_args(["say", "Halo", "--no-play"])
    with pytest.raises(cli.AudioCliError, match="app.mode: dev"):
        cli.cmd_say(args, _prod_settings(), tts_factory=FakeTts)


def test_dev_sentences_file():
    lines = (ROOT / "data" / "speech" / "tts_dev_sentences.txt").read_text(encoding="utf-8")
    lines = [line for line in lines.splitlines() if line.strip()]
    assert len(lines) == 12
    assert sum("Rp" in line for line in lines) >= 3
    assert sum("WIB" in line for line in lines) >= 2
    assert any("S1" in line and "SKS" in line for line in lines)
    assert any("T.A." in line for line in lines)


MODEL = Path("models/piper/id_ID-news_tts-medium.onnx")


@pytest.mark.slow
@pytest.mark.skipif(not (ROOT / MODEL).is_file(), reason="suara Piper belum diunduh (fetch-voice)")
def test_real_piper_voice_synthesizes():
    tts = PiperTts(ROOT / MODEL)
    clips = list(tts.stream("Halo. Biaya Rp14.000.000 per tahun."))
    assert len(clips) == 2 and all(c.sample_rate == 22050 and c.duration_s > 0.2 for c in clips)


def test_say_without_rate_writes_no_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lines = tmp_path / "kalimat.txt"
    lines.write_text("Satu dua.\nRp15.000.000 per tahun.\n", encoding="utf-8")
    before = set(tmp_path.rglob("*"))
    code, played = _say(["--file", str(lines)], tmp_path)
    assert code == 0 and len(played) == 2
    assert set(tmp_path.rglob("*")) == before
