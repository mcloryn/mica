import logging
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from mica.core.types import ErrorCode
from mica.vision.camera import Camera
from mica.vision.detector import (
    ModelMissing,
    UltralyticsDetector,
    model_path,
    tracks_from_result,
)
from mica.vision.presence import (
    BoxHeightSignal,
    PresenceState,
    PresenceTracker,
    ShoulderWidthSignal,
)
from mica.vision.types import CameraStatus, PersonArrived, PersonLeft, PersonTrack

# data uji (bukan ambang): frame 100 px, syarat tinggi 0,4, dwell 2 s, leave 3 s, 10 fps
FRAME_H = 100
FRAME = (FRAME_H, 100)
DWELL, LEAVE, RATIO = 2.0, 3.0, 0.4
STEP = 0.1


def person(track_id, height=60.0, conf=0.9):
    return PersonTrack(track_id, (10.0, 100.0 - height, 50.0, 100.0), conf)


def tracker():
    return PresenceTracker(dwell_s=DWELL, leave_s=LEAVE, min_signal=RATIO, signal=BoxHeightSignal())


class Clip:
    """Jalankan urutan (durasi, tracks) dengan langkah STEP; kumpulkan event dan waktunya."""

    def __init__(self, presence):
        self.presence = presence
        self.now = 0.0
        self.events = []

    def play(self, seconds, tracks):
        for _ in range(round(seconds / STEP)):
            for e in self.presence.update(tracks, FRAME, self.now):
                self.events.append(e)
            self.now = round(self.now + STEP, 6)
        return self

    def kinds(self):
        return [type(e).__name__ for e in self.events]


# --- PresenceTracker ---------------------------------------------------------------------


def test_passing_by_shorter_than_dwell_no_event():
    clip = Clip(tracker()).play(1.5, [person(1)]).play(5, [])
    assert clip.events == [] and clip.presence.state == PresenceState.IDLE


def test_standing_dwell_gives_exactly_one_arrival():
    clip = Clip(tracker()).play(10, [person(1)])
    assert clip.kinds() == ["PersonArrived"]
    arrived = clip.events[0]
    assert arrived.track_id == 1 and arrived.t == pytest.approx(DWELL)
    assert arrived.color is None
    assert clip.presence.state == PresenceState.ENGAGED


def test_candidate_resets_when_target_changes_before_dwell():
    clip = Clip(tracker()).play(1.5, [person(1)]).play(1.5, [person(2)])
    assert clip.events == []  # track 2 baru 1,5 s
    clip.play(1, [person(2)])
    assert clip.kinds() == ["PersonArrived"] and clip.events[0].track_id == 2


def test_id_switch_while_standing_no_second_greeting(caplog):
    caplog.set_level(logging.DEBUG, logger="mica.vision.presence")
    clip = Clip(tracker()).play(3, [person(1)]).play(5, [person(7)]).play(5, [person(9)])
    assert clip.kinds() == ["PersonArrived"]
    assert clip.presence.track_id == 9 and clip.presence.id_switches == 2
    assert "ID switch 1 -> 7" in caplog.text


def test_short_occlusion_no_event():
    clip = Clip(tracker()).play(3, [person(1)]).play(LEAVE - 0.5, []).play(5, [person(1)])
    assert clip.kinds() == ["PersonArrived"]


def test_leave_then_return_gives_new_arrival():
    clip = Clip(tracker()).play(3, [person(1)]).play(LEAVE + 1, [])
    assert clip.kinds() == ["PersonArrived", "PersonLeft"]
    left = clip.events[1]
    arrived_t = clip.events[0].t
    assert isinstance(left, PersonLeft) and left.track_id == 1
    last_seen = 3 - STEP  # frame terakhir dengan orang
    assert left.t - last_seen == pytest.approx(LEAVE, abs=STEP + 1e-9)
    assert left.duration_s == pytest.approx(left.t - arrived_t)
    assert clip.presence.state == PresenceState.IDLE
    clip.play(DWELL + 0.5, [person(4)])
    assert clip.kinds() == ["PersonArrived", "PersonLeft", "PersonArrived"]
    assert clip.events[2].track_id == 4


def test_small_far_box_ignored():
    clip = Clip(tracker()).play(10, [person(1, height=30)])  # rasio 0,3 < 0,4
    assert clip.events == [] and clip.presence.state == PresenceState.IDLE


def test_two_people_one_greeting_for_tallest():
    clip = Clip(tracker()).play(10, [person(1, height=45), person(2, height=80)])
    assert clip.kinds() == ["PersonArrived"] and clip.events[0].track_id == 2


def test_engaged_single_other_box_kept_as_target():
    # Langkah 51: ID target hilang tapi hanya ada satu orang di frame -> dianggap target yang
    # sama (belum ada pencocokan IoU), walau kecil; dua orang lain -> tidak ada yang dipilih
    clip = Clip(tracker()).play(3, [person(1)]).play(LEAVE + 0.5, [person(5, height=20)])
    assert clip.kinds() == ["PersonArrived"]
    two = Clip(tracker()).play(3, [person(1)])
    two.play(LEAVE + 0.5, [person(5, height=20), person(6, height=20)])
    assert two.kinds() == ["PersonArrived", "PersonLeft"]


def test_presence_has_no_default_values():
    with pytest.raises(TypeError):
        PresenceTracker()  # type: ignore[call-arg]


# --- detector -------------------------------------------------------------------------


class FakeBoxes:
    def __init__(self, xyxy, conf, ids):
        self.xyxy = np.array(xyxy, dtype=np.float32).reshape(-1, 4)
        self.conf = np.array(conf, dtype=np.float32)
        self.id = None if ids is None else np.array(ids, dtype=np.float32)

    @property
    def is_track(self):
        return self.id is not None

    def __len__(self):
        return len(self.conf)


class FakeKeypoints:
    def __init__(self, n):
        self.data = np.ones((n, 17, 3), dtype=np.float32)


def fake_result(xyxy, conf, ids, keypoints=False):
    return types.SimpleNamespace(
        boxes=FakeBoxes(xyxy, conf, ids),
        keypoints=FakeKeypoints(len(conf)) if keypoints else None,
    )


def test_tracks_from_result_converts():
    result = fake_result([[1, 2, 3, 4], [5, 6, 7, 18]], [0.9, 0.5], [3, 8])
    tracks = tracks_from_result(result)
    assert [t.track_id for t in tracks] == [3, 8]
    assert tracks[1].box_xyxy == (5.0, 6.0, 7.0, 18.0) and tracks[1].height == 12.0
    assert tracks[0].conf == pytest.approx(0.9) and tracks[0].keypoints is None
    assert all(isinstance(v, float) for v in tracks[0].box_xyxy)


def test_tracks_from_result_skips_boxes_without_id():
    assert tracks_from_result(fake_result([[1, 2, 3, 4]], [0.9], None)) == []
    assert tracks_from_result(fake_result([], [], None)) == []


def test_tracks_from_result_pose_keypoints():
    tracks = tracks_from_result(fake_result([[1, 2, 3, 4]], [0.9], [1], keypoints=True))
    assert tracks[0].keypoints.shape == (17, 3)


class FakeModel:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def track(self, frame, **kwargs):
        self.calls.append(kwargs)
        return self.results


@pytest.fixture
def fake_ultralytics(monkeypatch):
    updates = []
    module = types.ModuleType("ultralytics")
    module.settings = types.SimpleNamespace(update=lambda d: updates.append(d))

    def no_yolo(path):
        raise AssertionError("YOLO asli tidak boleh dimuat di tes ini")

    module.YOLO = no_yolo
    monkeypatch.setitem(sys.modules, "ultralytics", module)
    return updates


def test_detector_calls_track_with_bytetrack_and_disables_sync(tmp_path, fake_ultralytics):
    weights = tmp_path / "yolo26n.pt"
    weights.write_bytes(b"x")
    model = FakeModel([fake_result([[0, 0, 10, 50]], [0.8], [1])])
    det = UltralyticsDetector(weights, "bytetrack.yaml", 0.1, 640, model_factory=lambda p: model)
    tracks = det.detect_and_track(np.zeros((100, 100, 3), dtype=np.uint8))
    assert fake_ultralytics == [{"sync": False}]
    assert [t.track_id for t in tracks] == [1]
    kwargs = model.calls[0]
    assert kwargs["tracker"] == "bytetrack.yaml" and kwargs["persist"] is True
    assert kwargs["classes"] == [0] and kwargs["save"] is False and kwargs["verbose"] is False
    assert kwargs["conf"] == 0.1 and kwargs["imgsz"] == 640 and kwargs["device"] == "cpu"


def test_detector_missing_model_raises_without_download(tmp_path, fake_ultralytics):
    with pytest.raises(ModelMissing) as exc:
        UltralyticsDetector(tmp_path / "yolo26n.pt", "bytetrack.yaml", None, None)
    assert exc.value.code == ErrorCode.VISION_MODEL_MISSING
    assert "VISION_MODEL_MISSING" in str(exc.value)
    assert fake_ultralytics == []  # gagal sebelum Ultralytics disentuh
    assert list(tmp_path.iterdir()) == []


def test_model_path():
    assert model_path("yolo26n").as_posix() == "models/yolo26n.pt"
    assert model_path("yolo26n-pose", Path("m")).as_posix() == "m/yolo26n-pose.pt"


# --- kamera ----------------------------------------------------------------------------


class FakeCapture:
    def __init__(self, frames, opened=True):
        self.frames = list(frames)
        self.opened = opened
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        if not self.frames:
            return False, None
        return True, self.frames.pop(0)

    def release(self):
        self.released = True


class Opener:
    def __init__(self, captures):
        self.captures = list(captures)
        self.calls = 0

    def __call__(self, source):
        self.calls += 1
        return self.captures.pop(0) if self.captures else FakeCapture([], opened=False)


def test_camera_reports_failure_and_reopens_after_interval():
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    now = [0.0]
    opener = Opener([FakeCapture([frame]), FakeCapture([], opened=False), FakeCapture([frame])])
    cam = Camera(0, open_capture=opener, clock=lambda: now[0], reopen_interval_s=2.0)

    got, status = cam.read()
    assert got is frame and status == CameraStatus(True, "kamera 0 terbuka")
    got, status = cam.read()  # putus
    assert got is None and status is not None and status.ok is False
    got, status = cam.read()  # belum lewat jeda: tidak membuka ulang, status tidak diulang
    assert got is None and status is None and opener.calls == 1
    now[0] = 2.0
    got, status = cam.read()  # dibuka ulang, gagal
    assert got is None and status is None and opener.calls == 2
    now[0] = 4.0
    got, status = cam.read()
    assert got is frame and status.ok is True and opener.calls == 3


def test_camera_open_failure_is_status_not_crash():
    cam = Camera(5, open_capture=Opener([]), clock=lambda: 0.0)
    got, status = cam.read()
    assert got is None and status.ok is False and "5" in status.message


# --- tipe ------------------------------------------------------------------------------


def test_event_types():
    arrived = PersonArrived(1, (0.0, 0.0, 1.0, 1.0), 2.0)
    assert arrived.color is None and arrived.color_confidence is None
    assert PersonLeft(1, 5.0, 3.0).duration_s == 3.0
    assert person(1, height=50).height_ratio(FRAME_H) == 0.5
    assert person(1).height_ratio(0) == 0.0


def test_open_cv2_uses_dshow_for_webcam_on_windows(monkeypatch):
    import cv2

    from mica.vision import camera as camera_module

    calls = []
    monkeypatch.setattr(cv2, "VideoCapture", lambda *args: calls.append(args))
    monkeypatch.setattr(camera_module.sys, "platform", "win32")
    camera_module._open_cv2(0)
    camera_module._open_cv2("video.mp4")
    assert calls == [(0, cv2.CAP_DSHOW), ("video.mp4",)]


# --- sinyal lebar bahu ------------------------------------------------------------------

KP_CONF = 0.5  # data uji


def shouldered(track_id, width=30.0, conf=0.9, height=60.0):
    """Orang dengan bahu selebar `width` px di frame 100 px."""
    kp = np.zeros((17, 3), dtype=np.float32)
    kp[5], kp[6] = (50 + width / 2, 50, conf), (50 - width / 2, 50, conf)
    return PersonTrack(track_id, (20.0, 100.0 - height, 80.0, 100.0), 0.9, kp)


def shoulder_tracker():
    # data uji: ambang lebar bahu 0,22 dari lebar frame
    return PresenceTracker(DWELL, LEAVE, 0.22, ShoulderWidthSignal(KP_CONF))


def test_shoulder_width_separates_sitting_from_standing_back():
    # box hampir setinggi frame di kedua kondisi; yang beda lebar bahu (0,30 vs 0,16)
    # Langkah 51: lebar bahu hanya syarat MEMULAI sesi; selama sesi box target cukup
    near, far = shouldered(1, width=30, height=99), shouldered(1, width=16, height=99)
    assert Clip(shoulder_tracker()).play(3, [far]).events == []  # jauh: tidak disapa
    assert Clip(shoulder_tracker()).play(3, [near]).kinds() == ["PersonArrived"]
    box_clip = Clip(tracker()).play(3, [far])
    assert box_clip.kinds() == ["PersonArrived"]  # tinggi box tidak memisahkan
    kept = Clip(shoulder_tracker()).play(3, [near]).play(LEAVE + 1, [far])
    assert kept.kinds() == ["PersonArrived"]  # menyamping/menunduk saat sesi: tetap ada


def test_shoulder_unsure_briefly_does_not_trigger_leave():
    clip = Clip(shoulder_tracker()).play(3, [shouldered(1)])
    clip.play(LEAVE - 0.5, [shouldered(1, conf=0.1)])  # keypoint goyah < leave_s, box masih ada
    clip.play(1, [shouldered(1)])
    clip.play(LEAVE - 0.5, [shouldered(1, conf=0.1)])  # goyah lagi: batas dihitung ulang
    clip.play(1, [shouldered(1)])
    assert clip.kinds() == ["PersonArrived"]
    assert clip.presence.state == PresenceState.ENGAGED


def test_box_without_confident_shoulders_keeps_session_then_leaves_when_box_gone():
    # Langkah 51: keypoint bahu hilang (menunduk ke keyboard) tapi box target masih ada ->
    # tidak pergi. Trade-off: box tertinggal (mis. kursi) kini menahan sesi; pengamannya
    # session.idle_reset_s (TBD). Box hilang selama leave_s -> PersonLeft.
    clip = Clip(shoulder_tracker()).play(3, [shouldered(1)])
    clip.play(3 * LEAVE, [shouldered(1, conf=0.1)])
    assert clip.kinds() == ["PersonArrived"]
    gone_at = clip.now
    clip.play(LEAVE + 1, [])
    assert clip.kinds() == ["PersonArrived", "PersonLeft"]
    assert clip.events[1].t - gone_at == pytest.approx(LEAVE, abs=2 * STEP)
    clip.play(5, [shouldered(1, conf=0.1)])
    assert clip.kinds() == ["PersonArrived", "PersonLeft"]  # tanpa bahu yakin: tidak disapa


def test_shoulder_unsure_and_box_gone_leaves():
    clip = Clip(shoulder_tracker()).play(3, [shouldered(1)]).play(0.5, [shouldered(1, conf=0.1)])
    clip.play(LEAVE + 1, [])
    assert clip.kinds() == ["PersonArrived", "PersonLeft"]


def test_new_candidate_without_confident_shoulders_not_greeted():
    clip = Clip(shoulder_tracker()).play(10, [shouldered(1, conf=0.1)])
    assert clip.events == [] and clip.presence.state == PresenceState.IDLE


def test_shoulder_target_is_widest():
    clip = Clip(shoulder_tracker()).play(3, [shouldered(1, width=25), shouldered(2, width=40)])
    assert clip.events[0].track_id == 2
