"""Kunci thread CPU (docs/CPU-THREADS.md): audio.tts.threads -> onnxruntime Piper, vision.threads ->
torch.set_num_threads. null = bawaan pustaka, perilaku tidak berubah."""

from pathlib import Path

from test_audio_worker import VALUES
from test_audio_worker import _settings as audio_settings
from test_bus import TEST_VALUES, _settings

from mica.audio import tts as tts_module
from mica.audio import worker as audio_worker
from mica.audio.tts import PiperTts, session_options
from mica.audio.worker import AudioWorkerConfig
from mica.vision.detector import apply_torch_threads
from mica.vision.worker import VisionWorkerConfig

ROOT = Path(__file__).resolve().parents[2]


def _with(settings, section, key, value):
    part = getattr(settings, section)
    if section == "audio":
        tts = part.tts.model_copy(update={key: value})
        part = part.model_copy(update={"tts": tts})
    else:
        part = part.model_copy(update={key: value})
    return settings.model_copy(update={section: part})


def test_config_defaults_null():
    s = audio_settings()
    assert s.audio.tts.threads is None and s.vision.threads is None


def test_session_options_null_keeps_onnxruntime_defaults():
    import onnxruntime

    default = onnxruntime.SessionOptions()
    opts = session_options(None)
    assert opts.intra_op_num_threads == default.intra_op_num_threads == 0
    assert opts.inter_op_num_threads == default.inter_op_num_threads
    set_ = session_options(2)
    assert set_.intra_op_num_threads == 2 and set_.inter_op_num_threads == 1


def _voice(tmp_path):
    voice = tmp_path / "v.onnx"
    voice.write_bytes(b"x")
    Path(f"{voice}.json").write_text("{}", encoding="utf-8")
    return voice


def test_piper_loader_gets_threads_only_when_set(tmp_path):
    calls = []
    voice = _voice(tmp_path)
    PiperTts(voice, loader=lambda *a: calls.append(a))
    PiperTts(voice, loader=lambda *a: calls.append(a), threads=3)
    assert len(calls[0]) == 2  # null: pemanggilan lama, PiperVoice.load bawaan
    assert calls[1][2] == 3


def test_audio_worker_passes_tts_threads(monkeypatch):
    cfg = AudioWorkerConfig.from_settings(_with(audio_settings(), "audio", "threads", 4), VALUES)
    assert cfg.tts_threads == 4
    assert AudioWorkerConfig.from_settings(audio_settings(), VALUES).tts_threads is None
    made = {}

    class Fake:
        def __init__(self, path, length_scale, threads=None):
            made["threads"] = threads

    monkeypatch.setattr(tts_module, "PiperTts", Fake)
    audio_worker._make_tts(cfg)
    assert made["threads"] == 4


class FakeTorch:
    def __init__(self) -> None:
        self.n = 14
        self.calls: list[int] = []

    def set_num_threads(self, n):
        self.calls.append(n)
        self.n = n

    def get_num_threads(self):
        return self.n


def test_torch_threads_applied_only_when_set():
    torch = FakeTorch()
    assert apply_torch_threads(None, torch) == 14 and torch.calls == []
    assert apply_torch_threads(2, torch) == 2 and torch.calls == [2]


def test_vision_config_carries_threads(tmp_path):
    base = VisionWorkerConfig.from_settings(_settings(), TEST_VALUES, models_dir=tmp_path)
    assert base.threads is None
    s = _with(_settings(), "vision", "threads", 3)
    assert VisionWorkerConfig.from_settings(s, TEST_VALUES, models_dir=tmp_path).threads == 3
