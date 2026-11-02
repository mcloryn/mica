"""CV-4: fungsi murni scripts/cv_resize_bench.py (tanpa COCO; pyvips dilewati bila tak ada)."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import cv_resize_bench as rb


def test_cases_have_integer_factors():
    assert rb.factor("A") == 2 and rb.factor("B") == 3


@pytest.mark.parametrize("shape", [(480, 640, 3), (427, 640, 3), (640, 480, 3), (100, 900, 3)])
@pytest.mark.parametrize("size", [(640, 480), (1920, 1080)])
def test_center_crop_resize_shape(shape, size):
    img = np.random.default_rng(0).integers(0, 255, shape, dtype=np.uint8)
    out = rb.center_crop_resize(img, size)
    assert out.shape == (size[1], size[0], 3) and out.flags["C_CONTIGUOUS"]


def test_resize_cv2_matches_livepreview_width():
    out = rb.resize_cv2(np.zeros((480, 640, 3), np.uint8), 320)
    assert out.shape == (240, 320, 3)


def test_resize_cv2_is_box_average_at_integer_factor():
    img = np.arange(16, dtype=np.uint8).reshape(4, 4, 1).repeat(3, axis=2) * 10
    out = rb.resize_cv2(np.ascontiguousarray(img), 2)
    assert out[0, 0, 0] == round((0 + 10 + 40 + 50) / 4)


def test_summarize_and_diff_and_decide():
    s = rb.summarize([1.0, 2.0, 3.0, 4.0])
    assert s["median"] == 2.5 and s["n"] == 4 and 3.8 <= s["p95"] <= 4.0
    a = np.zeros((2, 2, 3), np.uint8)
    assert rb.mean_abs_diff(a, a + 2) == 2.0
    with pytest.raises(ValueError):
        rb.mean_abs_diff(a, np.zeros((3, 2, 3), np.uint8))
    assert rb.decide(2.0, 1.0)["propose_pyvips"] is True  # tepat 1 ms -> diusulkan
    assert rb.decide(2.0, 1.5)["propose_pyvips"] is False
    assert rb.decide(1.0, 2.0)["propose_pyvips"] is False


def test_vips_matches_cv2_box_average():
    pytest.importorskip("pyvips")
    img = np.random.default_rng(1).integers(0, 255, (480, 640, 3), dtype=np.uint8)
    a, b = rb.resize_cv2(img, 320), rb.resize_vips(img, 2)
    assert a.shape == b.shape == (240, 320, 3)
    assert rb.mean_abs_diff(a, b) <= 1.0
