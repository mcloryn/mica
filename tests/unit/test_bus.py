"""M-13 pesan bus dan VisionWorkerConfig (tanpa proses anak)."""

import pickle
from pathlib import Path

import pytest

from mica.config import load_settings
from mica.core.bus import Message, SetVisionRate, Shutdown
from mica.vision.types import CameraStatus, PersonArrived, PersonLeft
from mica.vision.worker import VisionWorkerConfig, WorkerConfigError, required_keys

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
# data uji (bukan ambang)
TEST_VALUES = {
    "presence_signal": "box_height",
    "dwell_s": 0.3,
    "leave_s": 0.3,
    "min_box_height_ratio": 0.3,
    "color.min_majority": 0.5,
    "box_upper.top": 0.2,
    "box_upper.bottom": 0.5,
    "box_upper.side": 0.2,
    "keypoint_torso.min_kp_conf": 0.5,
    "keypoint_torso.shrink": 0.1,
    "keypoint_torso.torso_aspect": 1.2,
}


def _settings(mode="dev"):
    settings = load_settings(DEV_YAML)
    return settings.model_copy(update={"app": settings.app.model_copy(update={"mode": mode})})


@pytest.mark.parametrize(
    "msg",
    [
        PersonArrived(3, (1.0, 2.0, 3.0, 4.0), 10.5, "merah", 0.8),
        PersonLeft(3, 20.0, 9.5),
        CameraStatus(ok=True, message="kamera 0 terbuka", fps=4.9),
        SetVisionRate(2.0),
        Shutdown(),
    ],
)
def test_messages_pickle_roundtrip(msg: Message):
    assert pickle.loads(pickle.dumps(msg)) == msg


def test_null_values_rejected_with_key_names():
    with pytest.raises(WorkerConfigError) as err:
        VisionWorkerConfig.from_settings(_settings(), {"presence_signal": "shoulder_width"})
    text = str(err.value)
    assert "vision.dwell_s" in text and "vision.min_shoulder_ratio" in text
    assert "vision.color.min_majority" in text


def test_overrides_fill_null_values_and_pickle():
    cfg = VisionWorkerConfig.from_settings(_settings(), TEST_VALUES)
    assert cfg.presence_signal == "box_height"
    assert set(cfg.values) == set(required_keys(_settings().vision, "box_height"))
    assert pickle.loads(pickle.dumps(cfg)) == cfg


def test_fake_factory_rejected_in_prod():
    with pytest.raises(WorkerConfigError, match="app.mode: dev"):
        VisionWorkerConfig.from_settings(
            _settings("prod"), TEST_VALUES, camera_factory="tests.fakes:make_fake_camera"
        )
    cfg = VisionWorkerConfig.from_settings(
        _settings(), TEST_VALUES, camera_factory="tests.fakes:make_fake_camera"
    )
    forged = VisionWorkerConfig(**{**cfg.__dict__, "mode": "prod"})
    with pytest.raises(WorkerConfigError, match="app.mode: dev"):
        forged.validate()


def test_start_workers_rejects_mode_mismatch(tmp_path):
    from mica.core.bus import start_workers

    cfg = VisionWorkerConfig.from_settings(
        _settings(), TEST_VALUES, detector_factory="tests.fakes:make_fake_detector"
    )
    with pytest.raises(WorkerConfigError):
        start_workers(_settings("prod"), cfg)


def _record_sigint(out):
    import signal

    out.append(signal.getsignal(signal.SIGINT))


def test_worker_main_ignores_ctrl_c_then_runs_target():
    # RF-2: pekerja mengabaikan Ctrl+C; berhenti lewat Shutdown dari Bus.stop()
    import signal

    from mica.core.bus import _worker_main

    before = signal.getsignal(signal.SIGINT)
    seen: list = []
    try:
        _worker_main(_record_sigint, seen)
    finally:
        signal.signal(signal.SIGINT, before)
    assert seen == [signal.SIG_IGN]


def test_worker_processes_start_through_worker_main(monkeypatch):
    from mica.core import bus as bus_mod

    started = []

    class FakeProcess:
        def __init__(self, target, args, name, daemon):
            started.append((target, args[0], name, daemon))
            self.pid = 1

        def start(self):
            pass

    class FakeCtx:
        Process = FakeProcess

    b = bus_mod.Bus.__new__(bus_mod.Bus)
    b.__dict__.update(
        ctx=FakeCtx(),
        processes={},
        started_at={},
        vision_cfg=None,
        to_vision=None,
        to_main=None,
        preview=None,
        measure=None,
        tts_busy=None,
    )
    b._start_process("vision")
    assert started == [(bus_mod._worker_main, bus_mod.run_vision_worker, "mica-vision", True)]
