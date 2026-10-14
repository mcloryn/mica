"""Uji unit bagian Computer Vision (tanpa kamera dan tanpa YOLO). Jalankan: python -m pytest"""

import numpy as np
import pytest

from mica.vision import body
from mica.vision.color import REFERENCE_RGB, read_color, to_lab
from mica.vision.session import SessionManager


def solid_image(rgb, size=20):
    """Gambar BGR satu warna, dibuat dari nilai RGB."""
    r, g, b = rgb
    return np.full((size, size, 3), (b, g, r), dtype=np.uint8)


# ---------- color.py ----------

@pytest.mark.parametrize("name, rgb", list(REFERENCE_RGB.items()))
def test_reference_color_reads_as_itself(name, rgb):
    color, _, distance = read_color(solid_image(rgb))
    assert color == name
    assert distance < 1e-3


def test_to_lab_gives_true_range():
    white = to_lab(solid_image((255, 255, 255)))[0, 0]
    black = to_lab(solid_image((0, 0, 0)))[0, 0]
    assert white[0] == pytest.approx(100, abs=0.1)
    assert black[0] == pytest.approx(0, abs=0.1)
    assert abs(white[1]) < 0.5 and abs(white[2]) < 0.5


def test_median_ignores_small_shadow():
    patch = solid_image((255, 255, 255))
    patch[:2] = 0  # 10% baris paling atas jadi hitam
    assert read_color(patch)[0] == "putih"


# ---------- body.py ----------

def shirt_region(keypoints, height, width):
    """shirt_region dengan nilai tetap, supaya uji tidak berubah saat config/mica.yaml dikalibrasi."""
    return body.shirt_region(keypoints, height, width, min_conf=0.5, shrink=0.15, min_size=4)


def person_keypoints(shoulder_conf=0.9, hip_conf=0.9):
    """17 titik tubuh palsu: bahu di (100,100) dan (200,100), pinggul di (110,300) dan (190,300)."""
    keypoints = np.zeros((17, 3))
    keypoints[5] = (200, 100, shoulder_conf)
    keypoints[6] = (100, 100, shoulder_conf)
    keypoints[11] = (190, 300, hip_conf)
    keypoints[12] = (110, 300, hip_conf)
    return keypoints


def test_region_from_shoulders_to_hips_then_shrunk():
    # Lebar 100 dan tinggi 200, disusutkan 15%: x 115..185, y 130..270.
    assert shirt_region(person_keypoints(), 480, 640) == (115, 130, 185, 270)


def test_without_hips_uses_bottom_of_frame():
    _, y1, _, y2 = shirt_region(person_keypoints(hip_conf=0.1), 480, 640)
    # Tinggi 100..480 = 380, disusutkan 15% (57): y 157..423.
    assert (y1, y2) == (157, 423)


def test_hidden_shoulders_give_none():
    assert shirt_region(person_keypoints(shoulder_conf=0.2), 480, 640) is None


def test_too_small_region_gives_none():
    keypoints = person_keypoints()
    keypoints[5, 0] = 102  # bahu hampir berimpit, misalnya orang menyamping
    assert shirt_region(keypoints, 480, 640) is None


# ---------- session.py ----------

def test_new_person_only_once():
    session = SessionManager()
    assert session.see(1, 0.0) is True
    assert session.see(1, 0.1) is False


def test_color_decided_by_majority_vote():
    session = SessionManager(min_frames=10)
    session.see(1, 0.0)
    results = [session.add_vote(1, c) for c in ["putih"] * 7 + ["abu-abu"] * 3]
    assert results[:9] == [None] * 9
    assert results[9] == ("putih", 7, 10)


def test_greeting_only_once_per_person():
    session = SessionManager(min_frames=2)
    session.see(1, 0.0)
    session.add_vote(1, "biru")
    assert session.add_vote(1, "biru") is not None
    assert session.add_vote(1, "biru") is None
    assert session.needs_color(1) is False


def test_label_shows_progress_then_color():
    session = SessionManager(min_frames=2)
    session.see(1, 0.0)
    assert session.label(1) == "membaca... 0/2"
    session.add_vote(1, "hitam")
    session.add_vote(1, "hitam")
    assert session.label(1) == "hitam"


def test_person_gone_too_long_is_removed():
    session = SessionManager(forget_after=30.0)
    session.see(1, 0.0)
    session.see(2, 25.0)
    assert session.remove_stale(31.0) == [1]
    assert list(session.people) == [2]
