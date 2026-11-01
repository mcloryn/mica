"""M-07 vision worker: jendela pratinjau (dev saja) di dalam proses kamera."""

import queue
from pathlib import Path

import cv2
import numpy as np
import pytest
from test_bus import TEST_VALUES, _settings
from test_vision_color import fake_table
from tests.fakes import FakeDetector, make_fake_camera

from mica.core.bus import Shutdown
from mica.vision.color import DEFAULT_COLORS_FILE
from mica.vision.worker import VisionLoop, VisionWorkerConfig, WorkerConfigError


class CountingCamera:
    """Kamera palsu yang mengirim Shutdown ke worker setelah n frame."""

    def __init__(self, inbox, n):
        self.camera = make_fake_camera(0, {"camera_period_s": 0.0})
        self.inbox, self.n, self.reads = inbox, n, 0

    def read(self):
        self.reads += 1
        if self.reads == self.n:
            self.inbox.put(Shutdown())
        return self.camera.read()

    def release(self):
        self.camera.release()


def _run(tmp_path, preview, n=20, countdown_s=0.0):
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    np.save(models / DEFAULT_COLORS_FILE.name, fake_table())
    cfg = VisionWorkerConfig.from_settings(
        _settings(),
        TEST_VALUES,
        models_dir=Path(models),
        preview=preview,
        prompts=((0.0, "Duduk dekat laptop"),),
        countdown_s=countdown_s,
    )
    inbox, outbox = queue.Queue(), queue.Queue()
    camera = CountingCamera(inbox, n)
    loop = VisionLoop(cfg, inbox, outbox, camera, FakeDetector((0.0, 99.0)))
    loop.run()
    return loop, camera


def test_no_imshow_without_preview(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("imshow tanpa --preview")

    monkeypatch.setattr(cv2, "imshow", forbidden)
    loop, camera = _run(tmp_path, preview=False)
    assert camera.reads == 20 and loop.detections > 0


def test_preview_q_closes_window_but_worker_keeps_running(tmp_path, monkeypatch):
    shown, destroyed = [], []
    monkeypatch.setattr(cv2, "imshow", lambda name, frame: shown.append(frame.shape))
    monkeypatch.setattr(cv2, "waitKey", lambda ms: ord("q") if len(shown) == 3 else -1)
    monkeypatch.setattr(cv2, "destroyWindow", lambda name: destroyed.append(name))
    loop, camera = _run(tmp_path, preview=True)
    assert len(shown) == 3 and len(destroyed) == 1
    assert not loop.preview_on and camera.reads == 20  # loop jalan terus setelah q


def test_preview_countdown_before_detection(tmp_path, monkeypatch):
    monkeypatch.setattr(cv2, "imshow", lambda name, frame: None)
    monkeypatch.setattr(cv2, "waitKey", lambda ms: -1)
    loop, _camera = _run(tmp_path, preview=True, countdown_s=60.0)
    assert loop.detections == 0  # masih hitung mundur: tanpa deteksi


def test_preview_rejected_in_prod():
    with pytest.raises(WorkerConfigError, match="app.mode: dev"):
        VisionWorkerConfig.from_settings(_settings("prod"), TEST_VALUES, preview=True)
    cfg = VisionWorkerConfig.from_settings(_settings(), TEST_VALUES, preview=True)
    forged = VisionWorkerConfig(**{**cfg.__dict__, "mode": "prod"})
    with pytest.raises(WorkerConfigError, match="app.mode: dev"):
        forged.validate()
