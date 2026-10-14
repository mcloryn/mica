"""Uji VisionPipeline dengan model YOLO asli (tanpa kamera). Dilewati jika file model belum diunduh."""

import numpy as np
import pytest

from mica.config import ROOT, SETTINGS
from mica.vision import pipeline

MODEL_FILE = ROOT / pipeline.MODEL

needs_model = pytest.mark.skipif(not MODEL_FILE.exists(),
                                 reason=f"{MODEL_FILE.name} belum ada; jalankan run_cv.py sekali supaya terunduh")


def test_calibration_values_come_from_config():
    assert pipeline.MODEL == SETTINGS["model"]
    assert pipeline.TRACK_CONF == SETTINGS["detection"]["track_conf"]
    assert pipeline.GREET_CONF == SETTINGS["detection"]["greet_conf"]
    assert pipeline.MIN_FRAMES == SETTINGS["session"]["min_frames"]
    assert pipeline.FORGET_AFTER == SETTINGS["session"]["forget_after"]


@needs_model
@pytest.mark.parametrize("mode", ["debug", "kiosk"])
def test_empty_frame_gives_no_events(mode):
    p = pipeline.VisionPipeline(str(MODEL_FILE), mode=mode)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    image, events = p.process(frame, 0.0)
    assert image.shape == frame.shape
    assert events == []
