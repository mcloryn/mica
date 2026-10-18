import os
from pathlib import Path

import numpy as np
import pytest

from mica.core.types import ErrorCode
from mica.vision.color import (
    COLOR_NAMES,
    DEFAULT_COLORS_FILE,
    ColorNamesLut,
    ColorNamesLutMean,
    ColorResult,
    ColorsMissing,
    ColorVoting,
    lut_index,
)
from mica.vision.presence import BoxHeightSignal, PresenceTracker
from mica.vision.region import BoxUpperRegion, KeypointTorsoRegion, shoulder_width_ratio
from mica.vision.types import PersonTrack

ROOT = Path(__file__).resolve().parents[2]
BIRU, MERAH, PUTIH, HITAM = (COLOR_NAMES.index(n) for n in ("biru", "merah", "putih", "hitam"))


def fake_table():
    """Tabel palsu: biru bila B tinggi, merah bila R tinggi, putih bila semua tinggi, selain itu
    hitam; satu label bernilai 1 per baris (data uji, bukan tabel van de Weijer)."""
    i = np.arange(32 * 32 * 32)
    r, g, b = i % 32 >= 16, (i // 32) % 32 >= 16, i // 1024 >= 16
    label = np.full(i.shape, HITAM)
    label[b & ~r] = BIRU
    label[r & ~b] = MERAH
    label[r & g & b] = PUTIH
    table = np.zeros((i.size, len(COLOR_NAMES)), dtype=np.float32)
    table[i, label] = 1.0
    return table


def solid(bgr, h=20, w=10):
    return np.tile(np.array(bgr, dtype=np.uint8), (h, w, 1))


@pytest.fixture
def namer():
    return ColorNamesLut(fake_table(), min_majority=0.6)


def test_lut_index_follows_im2c_layout():
    # im2c.m: 1 + floor(R/8) + 32*floor(G/8) + 32*32*floor(B/8); piksel kita BGR, 0-based
    assert lut_index(np.array([[0, 0, 8]], np.uint8)).tolist() == [1]  # R=8
    assert lut_index(np.array([[0, 8, 0]], np.uint8)).tolist() == [32]  # G=8
    assert lut_index(np.array([[8, 0, 0]], np.uint8)).tolist() == [1024]  # B=8
    assert lut_index(np.array([[255, 255, 255]], np.uint8)).tolist() == [32767]


def test_single_color_image_named(namer):
    result = namer.name(solid((255, 0, 0)))  # BGR biru murni
    assert result.label == "biru" and result.majority == 1.0 and result.pixels == 200
    assert namer.name(solid((0, 0, 255))).label == "merah"
    assert namer.name(solid((255, 255, 255))).label == "putih"


def test_half_half_with_high_min_majority_is_none(namer):
    img = np.concatenate([solid((255, 0, 0)), solid((0, 0, 255))], axis=1)
    result = namer.name(img)
    assert result.label is None and result.majority == pytest.approx(0.5)
    assert result.top in ("biru", "merah")
    assert dict(result.ranked()) == pytest.approx({"biru": 0.5, "merah": 0.5})
    assert ColorNamesLut(fake_table(), min_majority=0.5).name(img).label is not None


def test_empty_pixels(namer):
    result = namer.name(np.zeros((0, 0, 3), np.uint8))
    assert result.label is None and result.pixels == 0 and result.top is None


def test_table_shape_checked():
    with pytest.raises(ValueError):
        ColorNamesLut(np.zeros((10, 11)), 0.5)


def test_missing_table_has_error_code(tmp_path):
    with pytest.raises(ColorsMissing) as exc:
        ColorNamesLut.load(tmp_path / "w2c.npy", 0.5)
    assert exc.value.code == ErrorCode.VISION_COLORS_MISSING
    assert "fetch-colors" in str(exc.value)


def test_load_npy(tmp_path):
    path = tmp_path / "w2c.npy"
    np.save(path, fake_table())
    assert ColorNamesLut.load(path, 0.5).name(solid((255, 0, 0))).label == "biru"


# --- lut_mean (amandemen 1 E-08) -------------------------------------------------------


@pytest.mark.parametrize("bgr", [(255, 0, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)])
def test_lut_mean_single_color_equals_lut_vote(bgr):
    vote = ColorNamesLut(fake_table(), min_majority=0.6).name(solid(bgr))
    mean = ColorNamesLutMean(fake_table(), min_majority=0.6).name(solid(bgr))
    assert mean.label == vote.label and mean.majority == 1.0 and mean.pixels == 200


def test_lut_mean_two_colors_can_differ_from_vote():
    # setengah biru (B 255) + setengah merah (R 255): rata-rata BGR (128, 0, 128) jatuh di bin
    # R >= 16 dan B >= 16 tanpa G, yang di tabel uji berlabel hitam; voting = biru/merah 50:50
    img = np.concatenate([solid((255, 0, 0)), solid((0, 0, 255))], axis=1)
    vote = ColorNamesLut(fake_table(), min_majority=0.0).name(img)
    mean = ColorNamesLutMean(fake_table(), min_majority=0.9).name(img)
    assert vote.top in ("biru", "merah")
    assert mean.label == "hitam" and mean.majority == 1.0  # min_majority tidak membatasi


def test_lut_mean_empty_and_load(tmp_path):
    namer = ColorNamesLutMean(fake_table(), 0.6)
    assert namer.name(np.zeros((0, 0, 3), np.uint8)).label is None
    path = tmp_path / "w2c.npy"
    np.save(path, fake_table())
    loaded = ColorNamesLutMean.load(path, 0.5)
    assert isinstance(loaded, ColorNamesLutMean)
    assert loaded.name(solid((255, 0, 0))).label == "biru"


# --- region -----------------------------------------------------------------------------


def track(box):
    return PersonTrack(1, box, 0.9)


def test_box_upper_region_rect_and_pixels():
    frame = np.zeros((100, 100, 3), np.uint8)
    frame[30:50, 20:40] = (255, 0, 0)
    region = BoxUpperRegion(top=0.25, bottom=0.45, side=0.25)
    t = track((10.0, 10.0, 50.0, 110.0))  # box 40x100
    assert region.rect(frame.shape, t) == (20, 35, 40, 55)
    pixels = region.extract(frame, t)
    assert pixels.shape == (20, 20, 3)


def test_box_upper_region_clipped_outside_frame():
    frame = np.zeros((100, 100, 3), np.uint8)
    region = BoxUpperRegion(top=0.0, bottom=0.5, side=0.0)
    assert region.rect(frame.shape, track((-50.0, -40.0, 30.0, 60.0))) == (0, 0, 30, 10)
    assert region.rect(frame.shape, track((120.0, 0.0, 180.0, 50.0))) is None
    assert region.extract(frame, track((120.0, 0.0, 180.0, 50.0))) is None
    assert region.extract(frame, track((10.0, 150.0, 20.0, 400.0))) is None  # di bawah frame


# data uji (bukan ambang): conf minimum 0,5, dipersempit 10%, torso 1,2 x lebar bahu
KP = {"min_kp_conf": 0.5, "shrink": 0.1, "torso_aspect": 1.2}
FALLBACK = BoxUpperRegion(top=0.3, bottom=0.6, side=0.25)


def keypoints(shoulders=((60, 40), (20, 40)), hips=((55, 90), (25, 90)), conf=0.9, hip_conf=None):
    kp = np.zeros((17, 3), dtype=np.float32)
    (lsx, lsy), (rsx, rsy) = shoulders
    (lhx, lhy), (rhx, rhy) = hips
    kp[5], kp[6] = (lsx, lsy, conf), (rsx, rsy, conf)
    hc = conf if hip_conf is None else hip_conf
    kp[11], kp[12] = (lhx, lhy, hc), (rhx, rhy, hc)
    return kp


def pose_track(kp, box=(10.0, 20.0, 70.0, 150.0)):
    return PersonTrack(1, box, 0.9, kp)


def kp_region():
    return KeypointTorsoRegion(fallback=FALLBACK, **KP)


def test_keypoint_torso_from_shoulders_and_hips():
    frame = np.zeros((200, 100, 3), np.uint8)
    # bahu x 20..60, y 40; pinggul y 90 -> 40x50, dipersempit 10% per sisi -> 32x40
    rect, source = kp_region().locate(frame.shape, pose_track(keypoints()))
    assert (rect, source) == ((24, 45, 56, 85), "keypoint")
    assert kp_region().extract(frame, pose_track(keypoints())).shape == (40, 32, 3)


def test_keypoint_torso_hips_hidden_uses_shoulders_and_box():
    frame = np.zeros((200, 100, 3), np.uint8)
    track = pose_track(keypoints(hip_conf=0.1))
    rect, source = kp_region().locate(frame.shape, track)
    # bawah = 40 + 1,2 x 40 = 88 (< bawah box 150)
    assert source == "keypoint+box" and rect == (24, 45, 56, 83)
    short_box = pose_track(keypoints(hip_conf=0.1), box=(10.0, 20.0, 70.0, 60.0))
    assert kp_region().locate(frame.shape, short_box)[0][3] == 58  # dibatasi bawah box 60


def test_keypoint_torso_low_confidence_falls_back_to_box():
    frame = np.zeros((200, 100, 3), np.uint8)
    track = pose_track(keypoints(conf=0.2))
    rect, source = kp_region().locate(frame.shape, track)
    assert source == "fallback" and rect == FALLBACK.rect(frame.shape, track)


def test_keypoint_torso_without_keypoints_falls_back():
    frame = np.zeros((200, 100, 3), np.uint8)
    assert kp_region().locate(frame.shape, pose_track(None))[1] == "fallback"


def test_keypoint_torso_outside_frame_is_safe():
    frame = np.zeros((50, 50, 3), np.uint8)
    track = PersonTrack(1, (200.0, 200.0, 260.0, 330.0), 0.9, keypoints(
        shoulders=((250, 240), (210, 240)), hips=((245, 290), (215, 290))))  # fmt: skip
    assert kp_region().locate(frame.shape, track) is None
    assert kp_region().extract(frame, track) is None


def test_shoulder_width_ratio():
    track = pose_track(keypoints())
    assert shoulder_width_ratio(track, 100, 0.5) == pytest.approx(0.4)
    assert shoulder_width_ratio(pose_track(keypoints(conf=0.2)), 100, 0.5) is None
    assert shoulder_width_ratio(pose_track(None), 100, 0.5) is None


# --- voting lintas frame -----------------------------------------------------------------


def result(label_index, pixels=100):
    dist = [0.0] * len(COLOR_NAMES)
    dist[label_index] = 1.0
    return ColorResult(COLOR_NAMES[label_index], 1.0, COLOR_NAMES[label_index], tuple(dist), pixels)


def test_voting_equal_weight_per_frame():
    voting = ColorVoting(min_majority=0.6)
    voting.add(result(BIRU, pixels=10))
    voting.add(result(BIRU, pixels=10))
    voting.add(result(MERAH, pixels=1000))  # piksel banyak tidak mendominasi
    out = voting.result()
    assert out.label == "biru" and out.majority == pytest.approx(2 / 3)
    voting.add(ColorResult(None, 0.0, None, (0.0,) * 11, 0))  # frame tanpa piksel diabaikan
    assert voting.frames == 3


def person(track_id, height=60.0):
    return PersonTrack(track_id, (10.0, 100.0 - height, 50.0, 100.0), 0.9)


def run(presence, seconds, tracks, colors, now):
    events = []
    for _ in range(round(seconds / 0.1)):
        events += presence.update(tracks, (100, 100), now[0], color_of=lambda t: colors[t.track_id])
        now[0] = round(now[0] + 0.1, 6)
    return events


def test_arrival_carries_voted_color():
    presence = PresenceTracker(
        2.0, 3.0, 0.4, BoxHeightSignal(), voting=ColorVoting(min_majority=0.6)
    )
    events = run(presence, 3, [person(1)], {1: result(BIRU)}, [0.0])
    assert len(events) == 1
    assert events[0].color == "biru" and events[0].color_confidence == pytest.approx(1.0)


def test_voting_reset_when_candidate_changes():
    presence = PresenceTracker(
        2.0, 3.0, 0.4, BoxHeightSignal(), voting=ColorVoting(min_majority=0.6)
    )
    now = [0.0]
    colors = {1: result(MERAH), 2: result(BIRU)}
    assert run(presence, 1.5, [person(1)], colors, now) == []  # suara merah milik kandidat 1
    events = run(presence, 3, [person(2)], colors, now)
    assert events[0].track_id == 2 and events[0].color == "biru"
    assert events[0].color_confidence == pytest.approx(1.0)


def test_voting_reset_after_leave():
    presence = PresenceTracker(
        2.0, 3.0, 0.4, BoxHeightSignal(), voting=ColorVoting(min_majority=0.6)
    )
    now = [0.0]
    run(presence, 3, [person(1)], {1: result(MERAH)}, now)
    run(presence, 4, [], {}, now)
    events = run(presence, 3, [person(2)], {2: result(BIRU)}, now)
    assert events[0].color == "biru" and events[0].color_confidence == pytest.approx(1.0)


def test_uncertain_color_gives_none_label_with_confidence():
    presence = PresenceTracker(
        2.0, 3.0, 0.4, BoxHeightSignal(), voting=ColorVoting(min_majority=0.9)
    )
    now = [0.0]
    flip = iter([result(BIRU), result(MERAH)] * 100)
    events = []
    for _ in range(30):
        events += presence.update([person(1)], (100, 100), now[0], color_of=lambda t: next(flip))
        now[0] = round(now[0] + 0.1, 6)
    assert events[0].color is None and events[0].color_confidence == pytest.approx(0.5, abs=0.05)


def test_no_voting_keeps_color_none():
    presence = PresenceTracker(2.0, 3.0, 0.4, BoxHeightSignal())
    events = run(presence, 3, [person(1)], {1: result(BIRU)}, [0.0])
    assert events[0].color is None and events[0].color_confidence is None


def test_color_processing_writes_no_files(tmp_path, monkeypatch, namer):
    import cv2

    def forbidden(*a, **k):
        raise AssertionError("tidak boleh menulis gambar (N-08)")

    monkeypatch.setattr(cv2, "imwrite", forbidden)
    monkeypatch.chdir(tmp_path)
    frame = solid((255, 0, 0), h=100, w=100)
    region = BoxUpperRegion(0.2, 0.5, 0.2)
    presence = PresenceTracker(2.0, 3.0, 0.4, BoxHeightSignal(), voting=ColorVoting(0.6))
    for i in range(30):
        presence.update(
            [person(1)],
            (100, 100),
            i * 0.1,
            color_of=lambda t: namer.name(region.extract(frame, t)),
        )
    assert presence.state == "ENGAGED"
    assert os.listdir(tmp_path) == []


# --- tes asap tabel asli -----------------------------------------------------------------

REAL_TABLE = ROOT / DEFAULT_COLORS_FILE


@pytest.mark.slow
@pytest.mark.skipif(not REAL_TABLE.is_file(), reason="tabel warna belum diunduh (fetch-colors)")
def test_real_table_pure_colors():
    namer = ColorNamesLut.load(REAL_TABLE, min_majority=0.0)
    # (R, G, B) -> BGR untuk OpenCV
    for rgb, name in [
        ((0, 0, 255), "biru"),
        ((255, 0, 0), "merah"),
        ((255, 255, 255), "putih"),
        ((0, 0, 0), "hitam"),
    ]:
        assert namer.name(solid(rgb[::-1])).label == name, rgb


@pytest.mark.slow
@pytest.mark.skipif(not REAL_TABLE.is_file(), reason="tabel warna belum diunduh (fetch-colors)")
def test_real_table_lut_mean_differs_on_mixed_area():
    # 60 % putih + 40 % hitam: voting -> putih; rata-rata RGB (153, 153, 153) -> tabel: abu-abu
    img = np.concatenate([solid((255, 255, 255), w=6), solid((0, 0, 0), w=4)], axis=1)
    assert ColorNamesLut.load(REAL_TABLE, 0.0).name(img).label == "putih"
    assert ColorNamesLutMean.load(REAL_TABLE, 0.0).name(img).label == "abu-abu"
