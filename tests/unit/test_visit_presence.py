"""Langkah 51: akhir sesi (box target, ketikan, MICA sibuk), jeda YOLO saat Piper menyusun suara,
dan pemanasan Piper saat startup."""

import queue
import threading
from dataclasses import replace

import numpy as np
from test_audio_worker import VALUES, Harness, _has
from test_audio_worker import _settings as audio_settings
from test_bus import TEST_VALUES, _settings
from test_preview_meter import StepClock
from test_session import V, arrived, drive, make, of
from test_vision_color import fake_table
from test_worker_preview import CountingCamera
from tests.fakes import FakeDetector, FakeTts

from mica.audio.messages import AudioStatus, Speak, SpeechDone
from mica.audio.worker import WARMUP_TEXT, AudioWorkerConfig, run_audio_worker
from mica.core.bus import SetVisionRate, Shutdown
from mica.core.session import Tick, Typing
from mica.vision.color import DEFAULT_COLORS_FILE
from mica.vision.types import PersonLeft
from mica.vision.worker import VisionLoop, VisionWorkerConfig
from mica.webui.state import event_from_message

LEAVE = 3.0  # data uji, bukan ambang


def _reset(actions) -> bool:
    return bool(of(actions, SetVisionRate)) and any(
        type(a).__name__ == "ClearScreen" for a in actions
    )


# --- sesi -------------------------------------------------------------------------------


def test_person_left_while_typing_holds_session_until_idle_for_leave_s():
    s = drive(V.READY, make(leave_s=LEAVE))
    s.handle(Typing(), 5.0)
    assert not _reset(s.handle(PersonLeft(1, 5.5, 4.0), 5.5))  # masih mengetik
    s.handle(Typing(), 6.0)
    assert not _reset(s.handle(Tick(8.9), 8.9))  # < leave_s sejak ketikan terakhir
    assert s.state == V.READY
    assert _reset(s.handle(Tick(9.1), 9.1)) and s.state == V.IDLE


def test_person_left_while_mica_busy_holds_until_done_plus_leave_s():
    s = drive(V.SPEAKING, make(leave_s=LEAVE))
    assert not _reset(s.handle(PersonLeft(1, 5.0, 4.0), 5.0))
    s.handle(Tick(20.0), 20.0)  # masih bicara: tidak berakhir walau lama
    assert s.state == V.SPEAKING
    s.handle(SpeechDone(s.session_id, s.answer_uid, 0.3), 21.0)
    assert not _reset(s.handle(Tick(23.0), 23.0))
    assert _reset(s.handle(Tick(24.1), 24.1))


def test_person_really_gone_ends_session():
    s = drive(V.READY, make(leave_s=LEAVE))
    assert _reset(s.handle(PersonLeft(1, 10.0, 9.0), 10.0))  # tidak mengetik, tidak sibuk


def test_person_back_cancels_held_end_without_second_greeting():
    s = drive(V.READY, make(leave_s=LEAVE))
    s.handle(Typing(), 5.0)
    s.handle(PersonLeft(1, 5.5, 4.0), 5.5)
    assert not of(s.handle(arrived(), 6.0), Speak)  # tanpa sapaan kedua
    assert not _reset(s.handle(Tick(30.0), 30.0)) and s.state == V.READY


def test_leave_s_null_keeps_old_behaviour():
    s = drive(V.READY, make())
    s.handle(Typing(), 5.0)
    assert _reset(s.handle(PersonLeft(1, 5.5, 4.0), 5.5))


def test_typing_message_has_no_text():
    assert isinstance(event_from_message({"type": "typing", "text": "rahasia"}, None, None), Typing)
    assert Typing.__dataclass_fields__ == {}


# --- vision: jeda YOLO saat TTS -----------------------------------------------------------


class CountingDetector(FakeDetector):
    def __init__(self, *a) -> None:
        super().__init__(*a)
        self.calls = 0

    def detect_and_track(self, frame):
        self.calls += 1
        return super().detect_and_track(frame)


def _loop(tmp_path, busy, pause=True, n=60):
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    np.save(models / DEFAULT_COLORS_FILE.name, fake_table())
    cfg = replace(VisionWorkerConfig.from_settings(_settings(), TEST_VALUES, models_dir=models),
                  camera_preview="public", preview_fps=10.0, preview_pixel_block=16,
                  pause_during_tts=pause)  # fmt: skip
    inbox = queue.Queue()
    det = CountingDetector((0.0, 99.0))
    loop = VisionLoop(cfg, inbox, queue.Queue(), CountingCamera(inbox, n), det,
                      clock=StepClock(), preview_out=queue.Queue(1), tts_busy=busy)  # fmt: skip
    return loop, det


def test_yolo_skipped_while_tts_synthesizes_but_preview_still_sent(tmp_path):
    busy = threading.Event()
    busy.set()
    loop, det = _loop(tmp_path, busy)
    loop.run()
    assert det.calls == 0 and loop.skipped > 0 and loop.previews > 0


def test_yolo_runs_when_tts_idle_or_pause_off(tmp_path):
    loop, det = _loop(tmp_path, threading.Event())
    loop.run()
    assert det.calls > 0 and loop.skipped == 0
    busy = threading.Event()
    busy.set()
    loop, det = _loop(tmp_path, busy, pause=False)
    loop.run()
    assert det.calls > 0  # vision.pause_during_tts false: perilaku lama


def test_leave_timer_frozen_during_pause(tmp_path):
    busy = threading.Event()
    loop, _ = _loop(tmp_path, busy)
    p = loop.presence
    p.state, p.last_seen, p.last_measured = p.state.ENGAGED, 10.0, {1: 10.0}
    busy.set()
    assert loop._tts_pause(11.0)
    busy.clear()
    assert not loop._tts_pause(15.0)  # jeda 4 s
    assert p.last_seen == 14.0 and p.last_measured == {1: 14.0}


# --- suara: sinyal busy dan pemanasan ----------------------------------------------------


def test_tts_busy_set_only_while_synthesizing():
    from tests.unit.test_audio_worker import _cfg

    busy = threading.Event()
    seen: list[bool] = []

    class SpyTts(FakeTts):
        def stream(self, text):
            for clip in super().stream(text):
                seen.append(busy.is_set())  # saat clip disintesis
                yield clip

    with Harness(cfg=_cfg(), tts_busy=busy) as h:
        h.loop.tts = SpyTts()
        h.send(Speak("s1", "Satu dua. Tiga empat.", "u1"))
        h.collect(_has(SpeechDone))
    assert seen == [True, True] and not busy.is_set()


def test_piper_warm_up_once_at_startup_before_ready(monkeypatch):
    from tests import fakes

    tts = FakeTts()
    monkeypatch.setattr(fakes, "make_fake_tts", lambda cfg, options: tts)
    from tests.unit.test_audio_worker import FAKES

    cfg = AudioWorkerConfig.from_settings(audio_settings(), VALUES, **FAKES)
    inbox, outbox = queue.Queue(), queue.Queue()
    worker = threading.Thread(target=run_audio_worker, args=(cfg, inbox, outbox), daemon=True)
    worker.start()
    status = outbox.get(timeout=10)
    assert isinstance(status, AudioStatus) and status.ready
    assert tts.calls == [WARMUP_TEXT]  # sekali, sebelum status siap; tidak diputar
    inbox.put(Shutdown())
    worker.join(10)
    assert not worker.is_alive() and tts.calls == [WARMUP_TEXT]
