"""mica.core.startup (Langkah 40): tahap start-up dibuffer lalu ditulis, satu jam monotonic,
pembungkus bus pasif, dan hanya nama tahap + waktu (tanpa gambar/audio/teks)."""

import json
import os
import time

from mica.audio.messages import AudioStatus
from mica.core import startup
from mica.vision.types import CameraStatus

KEYS = {"ts", "run", "pid", "proc", "stage", "t"}


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_mark_without_begin_writes_nothing(tmp_path):
    before = time.monotonic()
    t = startup.mark("main_start")
    assert t >= before and not startup.active()
    assert list(tmp_path.iterdir()) == []


def test_buffer_flushed_on_init_and_env_for_children(tmp_path, monkeypatch):
    monkeypatch.setattr(startup, "DEFAULT_PATH_OVERRIDE", None)
    startup.begin()
    startup.mark("main_start")
    path = startup.init(tmp_path / "logs")
    startup.mark("run_start")
    assert path.parent == tmp_path / "logs" and path.name.startswith("startup-")
    assert os.environ[startup.ENV_FILE] == str(path) and os.environ[startup.ENV_RUN]
    rows = _rows(path)
    assert [r["stage"] for r in rows] == ["main_start", "run_start"]
    assert all(set(r) == KEYS for r in rows)  # tanpa gambar, audio, atau teks pengunjung
    assert len({r["run"] for r in rows}) == 1 and rows[0]["t"] <= rows[1]["t"]


def test_child_process_writes_to_same_file(tmp_path):
    path = tmp_path / "startup.jsonl"
    os.environ[startup.ENV_FILE] = str(path)  # seperti proses anak spawn
    os.environ[startup.ENV_RUN] = "r1"
    startup.set_process("vision")
    startup.mark("proc_start")
    startup.timed_import("json")
    rows = _rows(path)
    assert [(r["proc"], r["stage"]) for r in rows] == [
        ("vision", "proc_start"), ("vision", "import_json_start"), ("vision", "import_json_done")
    ]  # fmt: skip
    assert {r["run"] for r in rows} == {"r1"}


class _Bus:
    names = ("vision", "audio")

    def __init__(self, batches):
        self.batches = list(batches)
        self.sent = []

    def poll(self):
        return self.batches.pop(0) if self.batches else []

    def send(self, target, msg):
        self.sent.append((target, msg))


def test_startup_bus_is_passive_and_marks_ready(tmp_path):
    path = tmp_path / "startup.jsonl"
    os.environ[startup.ENV_FILE] = str(path)
    cam_down = CameraStatus(ok=False, message="belum")
    cam = CameraStatus(ok=True, message="kamera 0 terbuka")
    audio = AudioStatus(mic_ok=True, speaker_ok=True, ready=True, message="siap")
    inner = _Bus([[cam_down], [cam], [audio, cam]])
    bus = startup.StartupBus(inner)
    bus.note_pipeline_ready()
    assert bus.poll() == [cam_down]  # pesan diteruskan apa adanya
    assert bus.poll() == [cam]
    bus.send("vision", "x")  # atribut lain diteruskan ke bus asli
    assert inner.sent == [("vision", "x")]
    assert bus.poll() == [audio, cam]
    assert bus.all_ready_at is None  # UI belum digambar
    bus.note_ui_rendered()
    stages = [r["stage"] for r in _rows(path)]
    assert stages == ["camera_ready", "audio_ready", "all_ready"]
    bus.poll()
    assert [r["stage"] for r in _rows(path)].count("all_ready") == 1


def test_fake_bus_without_camera_does_not_wait_for_camera(tmp_path):
    from mica.ui.devfakes import FakeWorkerBus

    os.environ[startup.ENV_FILE] = str(tmp_path / "startup.jsonl")
    bus = startup.StartupBus(FakeWorkerBus())
    assert bus.waiting == {"audio"}
    bus.note_pipeline_ready()
    bus.note_ui_rendered()
    bus.poll()  # AudioStatus(ready=True) palsu
    assert bus.all_ready_at is not None


def test_startup_log_dir_gets_only_stage_lines(tmp_path, monkeypatch):
    # N-08: pencatatan tahap hanya menulis satu file teks nama tahap + waktu, tanpa gambar/audio
    monkeypatch.setattr(startup, "DEFAULT_PATH_OVERRIDE", None)
    startup.begin()
    startup.mark("main_start")
    path = startup.init(tmp_path)
    for stage in ("camera_first_frame", "mic_open_done", "all_ready"):
        startup.mark(stage)
    assert [p.name for p in tmp_path.iterdir()] == [path.name]
    assert path.suffix == ".jsonl"
    assert all(set(r) == KEYS for r in _rows(path))
