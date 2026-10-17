"""M-13 + M-08: proses suara di proses anak (spawn) dengan mikrofon, STT, TTS, speaker palsu.

Tanpa perangkat dan tanpa model. Factory palsu ada di tests/fakes.py.
"""

import json
import logging
import multiprocessing as mp
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import mica.audio.__main__ as cli
from mica.audio.messages import AudioStatus, ListenControl, Speak, SpeechDone, Transcript
from mica.audio.worker import AudioWorkerConfig
from mica.config import load_settings
from mica.core.bus import Bus, start_workers
from mica.core.types import ErrorCode

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
START_TIMEOUT_S = 60.0  # spawn + impor di Windows
VALUES = {"vad.threshold": 0.5, "vad.min_silence_ms": 160, "max_utterance_s": 10.0}  # data uji
FAKES = {
    "mic_factory": "tests.fakes:make_fake_audio_mic",
    "stt_factory": "tests.fakes:make_fake_stt",
    "tts_factory": "tests.fakes:make_fake_tts",
    "player_factory": "tests.fakes:make_fake_player",
    "prob_factory": "tests.fakes:make_fake_prob",
}
SPEECH = [["diam", 3], ["bicara", 8], ["diam", 6]]
AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".pcm", ".raw"}


@pytest.fixture
def workdir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # proses anak mewarisi cwd: file apa pun yang ditulis ada di sini
    return tmp_path


def _cfg(**options):
    return AudioWorkerConfig.from_settings(load_settings(DEV_YAML), VALUES, **FAKES,
                                           factory_options=options)  # fmt: skip


def _collect(bus: Bus, until, timeout_s=START_TIMEOUT_S):
    got = []
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        got.extend(bus.poll())
        if until(got):
            return got
        time.sleep(0.05)
    raise AssertionError(f"batas waktu; pesan: {got}")


def _ready(msgs):
    return any(isinstance(m, AudioStatus) and m.ready for m in msgs)


def _audio_files(root):
    return [p for p in Path(root).rglob("*") if p.suffix.lower() in AUDIO_SUFFIXES]


def test_audio_worker_listens_and_speaks_over_bus(workdir):
    bus = start_workers(load_settings(DEV_YAML), audio=_cfg(mic_pattern=SPEECH,
                                                            texts=["biaya kuliah"]))  # fmt: skip
    try:
        assert bus.names == ("audio",)
        _collect(bus, _ready)
        bus.send("audio", ListenControl("auto", "s1"))
        msgs = _collect(bus, lambda ms: any(isinstance(m, Transcript) for m in ms))
        bus.send("audio", Speak("s1", "Kamu bertanya: biaya kuliah.", "u1"))
        msgs += _collect(bus, lambda ms: any(isinstance(m, SpeechDone) for m in ms))
    finally:
        bus.stop()
    (t,) = [m for m in msgs if isinstance(m, Transcript)]
    assert t.session_id == "s1" and t.ok and t.text == "biaya kuliah"
    assert [m.utterance_id for m in msgs if isinstance(m, SpeechDone)] == ["u1"]
    assert mp.active_children() == [] and _audio_files(workdir) == []


def test_killed_audio_worker_restarts_once_then_dead(workdir, caplog):
    caplog.set_level(logging.WARNING, logger="mica.core.bus")
    bus = start_workers(load_settings(DEV_YAML), audio=_cfg())
    try:
        _collect(bus, _ready)
        first = bus.processes["audio"]
        old_queue = bus.to_audio
        first.kill()
        msgs = _collect(bus, lambda ms: bus.restarts["audio"] == 1 and _ready(ms))
        assert bus.processes["audio"].pid != first.pid and bus.to_audio is not old_queue
        down = [m for m in msgs if isinstance(m, AudioStatus) and not m.ready]
        assert down and ErrorCode.WORKER_RESTART in down[0].message
        assert msgs.index(down[0]) < max(i for i, m in enumerate(msgs) if _ready([m]))
        assert ErrorCode.WORKER_RESTART in caplog.text

        bus.processes["audio"].kill()
        msgs = _collect(bus, lambda ms: "audio" in bus.dead, timeout_s=10)
        dead = [m for m in msgs if isinstance(m, AudioStatus) and not m.ready]
        assert dead and ErrorCode.WORKER_DEAD in dead[-1].message
        assert not dead[-1].mic_ok and not dead[-1].speaker_ok
        assert ErrorCode.WORKER_DEAD in caplog.text
        assert bus.poll() == [] and bus.restarts["audio"] == 1
        bus.send("audio", Speak("s1", "Halo.", "u1"))  # dibuang tanpa error
    finally:
        bus.stop()
    assert mp.active_children() == []


SCRIPT = """
import json, sys, time
from mica.config import load_settings
from mica.core.bus import start_workers
from mica.audio.messages import AudioStatus
from mica.audio.worker import AudioWorkerConfig
from mica.vision.types import CameraStatus
from mica.vision.worker import VisionWorkerConfig
settings = load_settings(sys.argv[1])
fakes = json.loads(sys.argv[2])
audio = AudioWorkerConfig.from_settings(settings, json.loads(sys.argv[3]), **fakes)
vision = VisionWorkerConfig.from_settings(settings, json.loads(sys.argv[4]), models_dir="models",
    camera_factory="tests.fakes:make_fake_camera", detector_factory="tests.fakes:make_fake_detector")
bus = start_workers(settings, vision, audio)
end = time.monotonic() + 60
cam = ready = False
while time.monotonic() < end and not (cam and ready):
    for m in bus.poll():
        cam = cam or (isinstance(m, CameraStatus) and m.ok)
        ready = ready or (isinstance(m, AudioStatus) and m.ready)
    time.sleep(0.05)
bus.stop()
heavy = ["torch", "ctranslate2", "onnxruntime", "faster_whisper", "piper", "ultralytics"]
print(json.dumps({"names": list(bus.names), "camera": cam, "audio": ready,
                  "heavy": [m for m in heavy if m in sys.modules]}))
"""


def test_main_process_loads_no_heavy_modules_with_both_workers(workdir):
    sys.path.insert(0, str(ROOT / "tests" / "unit"))
    import numpy as np
    from test_bus import TEST_VALUES
    from test_vision_color import fake_table

    from mica.vision.color import DEFAULT_COLORS_FILE

    (workdir / "models").mkdir()
    np.save(workdir / "models" / DEFAULT_COLORS_FILE.name, fake_table())
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")])}
    argv = [str(DEV_YAML), json.dumps(FAKES), json.dumps(VALUES), json.dumps(TEST_VALUES)]
    result = subprocess.run([sys.executable, "-c", SCRIPT, *argv], check=False, cwd=workdir,
                            env=env, capture_output=True, text=True, timeout=180)  # fmt: skip
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out == {"names": ["vision", "audio"], "camera": True, "audio": True, "heavy": []}


DEMO_VAD = ["--vad-threshold", "0.5", "--min-silence-ms", "160", "--max-utterance-s", "10"]


def _demo(argv, **options):
    args = cli.build_parser().parse_args(["bus-demo", "--config", str(DEV_YAML), *DEMO_VAD, *argv])
    return cli.cmd_bus_demo(args, load_settings(DEV_YAML),
                            factories={**FAKES, "factory_options": options})  # fmt: skip


def test_bus_demo_one_turn(workdir, capsys):
    pattern = [["bicara", 3], ["diam", 6], *SPEECH]  # 96 ms tersaring, lalu pertanyaan
    assert _demo(["--turns", "1", "--min-speech-ms", "100"], mic_pattern=pattern,
                 texts=["jalur masuk apa saja"]) == 0  # fmt: skip
    out = capsys.readouterr().out
    assert "-> Speak(u1, sapaan)" in out and "-> ListenControl(auto)" in out
    assert "[tersaring: min_speech]" in out and "teks: jalur masuk apa saja" in out
    assert "-> Speak(u2, gema)" in out and "pertanyaan dijawab 1" in out
    assert '>>> GILIRAN KAMU: ucapkan pertanyaan 1 dari 1, misalnya: "' in out
    assert ">>> SELESAI" in out
    assert "tersaring: min_speech 1 | no_speech 0" in out
    assert "modul berat di proses utama: tidak ada" in out
    assert "proses anak tersisa: tidak ada" in out and _audio_files(workdir) == []


def test_bus_demo_stop_after_interrupts(workdir, capsys):
    assert _demo(["--turns", "1", "--stop-after", "0.5"], play_speed=1.0) == 0
    out = capsys.readouterr().out
    assert "-> Speak(u1, panjang)" in out and "-> StopSpeaking" in out
    assert "StopSpeaking: interrupted=True" in out
    assert ">>> DIAM SAJA" in out and "GILIRAN KAMU" not in out
