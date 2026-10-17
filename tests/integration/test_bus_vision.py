"""M-13 + M-07: vision worker di proses anak (spawn) dengan kamera dan detektor palsu.

Tanpa kamera dan tanpa model. Factory palsu ada di tests/fakes.py.
"""

import json
import logging
import multiprocessing as mp
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from mica.config import load_settings
from mica.core.bus import Bus, SetVisionRate, start_workers
from mica.core.types import ErrorCode
from mica.vision.color import DEFAULT_COLORS_FILE
from mica.vision.types import CameraStatus, PersonArrived, PersonLeft
from mica.vision.worker import VisionWorkerConfig

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
sys.path.insert(0, str(ROOT / "tests" / "unit"))
from test_bus import TEST_VALUES
from test_vision_color import fake_table

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".avi", ".mp4", ".wav"}
START_TIMEOUT_S = 60.0  # spawn + impor di Windows


@pytest.fixture
def workdir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # proses anak mewarisi cwd: file apa pun yang ditulis ada di sini
    models = tmp_path / "models"
    models.mkdir()
    np.save(models / DEFAULT_COLORS_FILE.name, fake_table())
    return tmp_path


def _cfg(workdir, status_interval_s=10.0, **options):
    return VisionWorkerConfig.from_settings(
        load_settings(DEV_YAML),
        TEST_VALUES,
        models_dir=workdir / "models",
        status_interval_s=status_interval_s,
        camera_factory="tests.fakes:make_fake_camera",
        detector_factory="tests.fakes:make_fake_detector",
        factory_options=options,
    )


def _collect(bus: Bus, until, timeout_s=START_TIMEOUT_S):
    """Poll setiap 50 ms sampai until(pesan) benar; kembalikan semua pesan."""
    got = []
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        batch = bus.poll()
        got.extend(batch)
        if until(got):
            return got
        time.sleep(0.05)
    raise AssertionError(f"batas waktu; pesan: {got}")


def _image_files(root):
    return [p for p in Path(root).rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES]


def _ok(msgs):
    return any(isinstance(m, CameraStatus) and m.ok for m in msgs)


def test_arrived_once_then_left(workdir):
    bus = start_workers(load_settings(DEV_YAML), _cfg(workdir, present_s=[0.0, 1.5]))
    try:
        msgs = _collect(bus, lambda ms: any(isinstance(m, PersonLeft) for m in ms))
        time.sleep(0.5)  # tidak ada PersonArrived kedua
        msgs += bus.poll()
    finally:
        bus.stop()
    arrived = [m for m in msgs if isinstance(m, PersonArrived)]
    left = [m for m in msgs if isinstance(m, PersonLeft)]
    assert len(arrived) == 1 and len(left) == 1
    assert arrived[0].track_id == 1 and arrived[0].color == "merah"
    assert left[0].duration_s > 0
    assert _ok(msgs)
    assert _image_files(workdir) == []


def test_set_vision_rate_changes_rate(workdir):
    bus = start_workers(load_settings(DEV_YAML), _cfg(workdir, status_interval_s=0.5))
    try:

        def rates(ms):
            return [m.fps for m in ms if isinstance(m, CameraStatus) and m.fps is not None]

        idle = _collect(bus, lambda ms: len(rates(ms)) >= 3)
        bus.send("vision", SetVisionRate(20.0))
        busy = _collect(bus, lambda ms: len(rates(ms)) >= 3, timeout_s=10)
    finally:
        bus.stop()
    assert rates(idle)[-1] < 8  # fps_idle = 5
    assert rates(busy)[-1] > 12


def test_killed_worker_restarts_once_then_dead(workdir, caplog):
    caplog.set_level(logging.WARNING, logger="mica.core.bus")
    bus = start_workers(load_settings(DEV_YAML), _cfg(workdir))
    try:
        _collect(bus, _ok)
        first = bus.processes["vision"]
        first.kill()
        _collect(bus, lambda ms: bus.restarts["vision"] == 1 and _ok(ms))
        assert bus.processes["vision"].pid != first.pid
        assert ErrorCode.WORKER_RESTART in caplog.text

        bus.processes["vision"].kill()
        msgs = _collect(bus, lambda ms: "vision" in bus.dead, timeout_s=10)
        dead = [m for m in msgs if isinstance(m, CameraStatus) and not m.ok]
        assert dead and ErrorCode.WORKER_DEAD in dead[-1].message
        assert ErrorCode.WORKER_DEAD in caplog.text
        # bus tetap bisa di-poll dan tidak memulai ulang lagi
        assert bus.poll() == [] and bus.restarts["vision"] == 1
        bus.send("vision", SetVisionRate(2.0))  # dibuang tanpa error
    finally:
        bus.stop()


def test_stop_leaves_no_orphans(workdir):
    bus = start_workers(load_settings(DEV_YAML), _cfg(workdir))
    _collect(bus, _ok)
    bus.stop()
    assert all(not p.is_alive() for p in bus.processes.values())
    assert mp.active_children() == []


SCRIPT = """
import json, sys, time
from mica.config import load_settings
from mica.core.bus import start_workers
from mica.vision.types import CameraStatus
from mica.vision.worker import VisionWorkerConfig
values = json.loads(sys.argv[2])
settings = load_settings(sys.argv[1])
cfg = VisionWorkerConfig.from_settings(settings, values, models_dir="models",
    camera_factory="tests.fakes:make_fake_camera", detector_factory="tests.fakes:make_fake_detector",
    factory_options={"present_s": [0, 1]})
bus = start_workers(settings, cfg)
end = time.monotonic() + 60
ok = False
while time.monotonic() < end and not ok:
    ok = any(isinstance(m, CameraStatus) and m.ok for m in bus.poll())
    time.sleep(0.05)
time.sleep(1.5)
bus.poll()
bus.stop()
print(json.dumps({"ok": ok, "torch": "torch" in sys.modules,
                  "ultralytics": "ultralytics" in sys.modules}))
"""


def test_main_process_does_not_import_torch_and_writes_no_images(workdir):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")])}
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(DEV_YAML), json.dumps(TEST_VALUES)],
        check=False,
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out == {"ok": True, "torch": False, "ultralytics": False}
    assert _image_files(workdir) == []


BUS_DEMO_ARGS = ["--presence-signal", "box_height", "--dwell-s", "0.3", "--leave-s", "0.3",
                 "--min-ratio", "0.3", "--fps-busy", "2", "--min-majority", "0.5",
                 "--box-top", "0.2", "--box-bottom", "0.5", "--box-side", "0.2", "--kp-conf", "0.5",
                 "--kp-shrink", "0.1", "--torso-aspect", "1.2"]  # fmt: skip


def test_bus_demo_requires_trial_values(capsys):
    import mica.vision.__main__ as cli

    assert cli.main(["bus-demo", "--config", str(DEV_YAML), "--seconds", "1"]) == 2
    assert "argumen kurang" in capsys.readouterr().err


def test_bus_demo_prints_bus_messages(workdir, capsys):
    import mica.vision.__main__ as cli

    argv = ["bus-demo", "--config", str(DEV_YAML), "--models-dir", "models", "--seconds", "6"]
    args = cli.build_parser().parse_args([*argv, *BUS_DEMO_ARGS])
    code = cli.cmd_bus_demo(
        args,
        load_settings(DEV_YAML),
        camera_factory="tests.fakes:make_fake_camera",
        detector_factory="tests.fakes:make_fake_detector",
        factory_options={"present_s": [0.0, 1.0]},
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "nilai coba" in out
    assert out.count("PersonArrived track=1 warna=merah") == 1
    assert "PersonLeft track=1" in out and "SetVisionRate(2.0)" in out
    assert "torch di proses utama: tidak" in out and "proses anak tersisa: tidak ada" in out
    assert _image_files(workdir) == []
