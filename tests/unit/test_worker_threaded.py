"""CV-3: VisionLoop(threaded=True), pratinjau tidak menunggu YOLO (pola frame terbaru)."""

import itertools
import queue
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from test_bus import TEST_VALUES, _settings
from test_vision_color import fake_table
from tests.fakes import FakeDetector, make_fake_camera

from mica.core.bus import Shutdown
from mica.vision.color import DEFAULT_COLORS_FILE
from mica.vision.worker import VisionLoop, VisionWorkerConfig

CAMERA_PERIOD_S = 1 / 30  # kamera palsu sekitar 30 fps
DETECT_S = 0.25  # YOLO lambat: jauh lebih lama dari jarak antar-frame
RUN_S = 1.5


class SlowDetector(FakeDetector):
    """FakeDetector yang tidur DETECT_S per panggilan dan mencatat frame yang dideteksi."""

    def __init__(self) -> None:
        super().__init__((0.0, 99.0))
        self.seen: list[int] = []

    def detect_and_track(self, frame):
        self.seen.append(int(frame[0, 0, 0]))
        time.sleep(DETECT_S)
        return super().detect_and_track(frame)


class NumberedCamera:
    """Kamera palsu sekitar 30 fps; piksel [0,0,0] = nomor frame (mod 256)."""

    def __init__(self) -> None:
        self.camera = make_fake_camera(0, {"camera_period_s": CAMERA_PERIOD_S})
        self.reads = 0
        self.released = False

    def read(self):
        frame, status = self.camera.read()
        if frame is not None:
            self.reads += 1
            frame[0, 0, 0] = self.reads % 256
        return frame, status

    def release(self):
        self.released = True
        self.camera.release()


def _cfg(tmp_path, fps_idle):
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    np.save(models / DEFAULT_COLORS_FILE.name, fake_table())
    s = _settings()
    s = s.model_copy(update={
        "ui": s.ui.model_copy(update={"camera_preview": "public", "preview_fps": 24.0}),
        "vision": s.vision.model_copy(update={"fps_idle": fps_idle}),
    })  # fmt: skip
    return VisionWorkerConfig.from_settings(s, TEST_VALUES, models_dir=Path(models))


def _run(tmp_path, threaded, camera=None, fps_idle=5.0, seconds=RUN_S):
    cfg = _cfg(tmp_path, fps_idle)
    inbox, outbox = queue.Queue(), queue.Queue()
    out: queue.Queue = queue.Queue(maxsize=1)
    detector = SlowDetector()
    camera = camera or NumberedCamera()
    loop = VisionLoop(cfg, inbox, outbox, camera, detector, preview_out=out, threaded=threaded)
    timer = threading.Timer(seconds, lambda: inbox.put(Shutdown()))
    timer.start()
    loop.run()
    timer.cancel()
    return loop, detector, camera, out


def test_threaded_preview_not_blocked_by_slow_detection(tmp_path):
    loop, _detector, camera, out = _run(tmp_path, threaded=True)
    # kamera tetap dibaca sekitar 30 fps walau tiap deteksi 0,25 s
    assert camera.reads >= 0.6 * RUN_S * 30
    # pratinjau mengikuti preview_fps 24 (dibatasi frame kamera), bukan laju deteksi
    assert loop.previews >= 0.6 * RUN_S * 24
    assert out.get_nowait()[:2] == b"\xff\xd8"
    # deteksi tidak lebih sering dari fps_idle dan tidak bisa lebih dari 1/DETECT_S per detik
    assert loop.detections <= RUN_S / DETECT_S + 2
    assert camera.released


def test_single_loop_preview_is_blocked_by_slow_detection(tmp_path):
    """Pembanding: loop tunggal lama ikut tertahan YOLO (alasan CV-3)."""
    loop, _detector, camera, _out = _run(tmp_path, threaded=False)
    threaded, _d, threaded_camera, _o = _run(tmp_path, threaded=True)
    assert loop.previews < 0.5 * threaded.previews
    assert camera.reads < 0.5 * threaded_camera.reads


def test_threaded_detects_latest_frame_and_drops_old(tmp_path):
    _loop, detector, _camera, _out = _run(tmp_path, threaded=True, fps_idle=100.0)
    seen = detector.seen
    assert len(seen) >= 3
    gaps = [(b - a) % 256 for a, b in itertools.pairwise(seen)]
    # selama satu deteksi (0,25 s) kamera memberi sekitar 7 frame; yang lama dibuang
    assert min(gaps) >= 2


def test_threaded_camera_error_propagates(tmp_path):
    class BrokenCamera(NumberedCamera):
        def read(self):
            if self.reads >= 3:
                raise RuntimeError("driver rusak")
            return super().read()

    camera = BrokenCamera()
    with pytest.raises(RuntimeError, match="driver rusak"):
        _run(tmp_path, threaded=True, camera=camera, seconds=5.0)
    assert camera.released


def test_threaded_reports_camera_status(tmp_path):
    loop, _detector, _camera, _out = _run(tmp_path, threaded=True, seconds=0.5)
    statuses = []
    while not loop.outbox.empty():
        statuses.append(loop.outbox.get_nowait())
    oks = [s for s in statuses if type(s).__name__ == "CameraStatus"]
    assert oks and oks[0].ok
