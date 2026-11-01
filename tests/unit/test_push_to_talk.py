"""Push-to-talk (Langkah 42; audio.input_mode push_to_talk): tekan-tahan-lepas mengirim, batal
membuang, tanpa ucapan tidak memanggil STT, batas max_utterance_s, barge-in menghentikan TTS
tanpa merekam audio TTS, mikrofon tidak merekam saat tombol tidak ditahan, tanpa audio ke disk.
Mikrofon/STT/TTS/speaker palsu; tidak ada perangkat atau model."""

import os
import time
from pathlib import Path

import numpy as np
from test_audio_worker import VALUES, Harness, _cfg, _has
from tests.fakes import FakePlayer, FakeStt, fake_prob

from mica.audio.messages import (
    ListenControl,
    ReleaseTalk,
    Speak,
    SpeechDone,
    StopSpeaking,
    Transcript,
)
from mica.audio.vad import CHUNK_SAMPLES, push_to_talk_utterance
from mica.config import load_settings
from mica.core import texts
from mica.core.session import TalkCancelled, TalkPressed, TalkReleased, VisitState
from mica.eval.stt import SpeechItem, evaluate_item
from mica.ui.viewmodel import ViewModel
from mica.webui import state
from mica.webui.server import STATIC_DIR

ROOT = Path(__file__).resolve().parents[2]
SPEECH = np.full(CHUNK_SAMPLES, 1000, dtype=np.int16)
SILENCE = np.zeros(CHUNK_SAMPLES, dtype=np.int16)


class StreamMic:
    """Mikrofon palsu yang terus mengalir seperti perangkat asli: potongan hanya terbaca saat
    tidak di-pause (MicStream membuang audio saat pause); reads menghitung potongan terbaca."""

    def __init__(self, chunk=SPEECH, log=None) -> None:
        self.chunk = chunk
        self.paused = True
        self.reads = 0
        self.log = log if log is not None else []
        self.input_rate, self.resampled, self.closed = 16000, False, False

    def read_chunk(self, timeout_s=1.0):
        time.sleep(0.002)
        if self.paused:
            return None
        self.reads += 1
        return self.chunk

    def pause(self) -> None:
        self.paused = True
        self.log.append("mic pause")

    def resume(self) -> None:
        self.paused = False
        self.log.append("mic resume")

    def close(self) -> None:
        self.closed = True


def _wait(cond, timeout_s=5.0):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


# --- proses suara ---------------------------------------------------------------------------


def test_press_hold_release_sends_one_transcript():
    mic = StreamMic()
    with Harness(mic=mic, stt=FakeStt(["biaya kuliah berapa"])) as h:
        h.send(ListenControl("hold", "s1"))
        assert _wait(lambda: mic.reads >= 10)
        h.send(ReleaseTalk("s1"))
        (t,) = h.collect(_has(Transcript)) and h.of(Transcript)
        assert t.ok and t.text == "biaya kuliah berapa" and t.session_id == "s1"
        assert not t.cut_by_max and t.filtered_by is None
        assert t.vad_s is not None and t.vad_s >= 0 and t.ended_t is not None
        assert h.stt.calls == 1
        assert _wait(lambda: mic.paused)  # selesai: mikrofon dijeda lagi


def test_cancel_drops_recording_without_stt():
    mic = StreamMic()
    with Harness(mic=mic, stt=FakeStt(["tidak boleh"])) as h:
        h.send(ListenControl("hold", "s1"))
        assert _wait(lambda: mic.reads >= 5)
        h.send(ListenControl("off", "s1"))  # TalkCancelled -> ListenControl(off)
        assert _wait(lambda: mic.paused)
        h.send(ReleaseTalk("s1"))  # lepas setelah batal: diabaikan
        time.sleep(0.3)
        h.collect(lambda ms: True, timeout_s=0.1)
        assert h.of(Transcript) == [] and h.stt.calls == 0


def test_recording_without_speech_does_not_call_stt():
    mic = StreamMic(chunk=SILENCE)
    with Harness(mic=mic, stt=FakeStt(["tidak boleh"])) as h:
        h.send(ListenControl("hold", "s1"))
        assert _wait(lambda: mic.reads >= 10)
        h.send(ReleaseTalk("s1"))
        (t,) = h.collect(_has(Transcript)) and h.of(Transcript)
        assert not t.ok and t.text == "" and t.filtered_by == "no_voice"
        assert h.stt.calls == 0


def test_max_utterance_reached_sends_automatically():
    mic = StreamMic()
    with Harness(cfg=_cfg(max_utterance_s=0.2), mic=mic, stt=FakeStt(["jalur masuk"])) as h:
        h.send(ListenControl("hold", "s1"))  # tombol tidak pernah dilepas
        (t,) = h.collect(_has(Transcript)) and h.of(Transcript)
        assert t.ok and t.cut_by_max and t.audio_s <= 0.2 + CHUNK_SAMPLES / 16000
        assert _wait(lambda: mic.paused)
        reads = mic.reads
        time.sleep(0.2)
        assert mic.reads == reads  # tidak merekam lagi setelah dikirim


def test_mic_not_recording_unless_held():
    mic = StreamMic()
    with Harness(mic=mic, stt=FakeStt(["a"])) as h:
        h.send(ListenControl("off", "s1"))  # push-to-talk tidak pernah mengirim "auto"
        time.sleep(0.2)
        assert mic.reads == 0 and mic.paused
        h.send(ListenControl("hold", "s1"))
        assert _wait(lambda: mic.reads > 0)
        h.send(ReleaseTalk("s1"))
        h.collect(_has(Transcript))
        assert _wait(lambda: mic.paused)
        reads = mic.reads
        time.sleep(0.2)
        assert mic.reads == reads


class StopLoggingPlayer(FakePlayer):
    def __init__(self, log) -> None:
        super().__init__(speed=1.0)  # durasi clip nyata: sedang bicara
        self.log = log

    def start(self, clip) -> None:
        super().start(clip)
        self.log.append("play")

    def stop(self) -> None:
        super().stop()
        self.log.append("player stop")


def test_barge_in_stops_tts_and_records_no_tts_audio():
    log: list[str] = []
    mic = StreamMic(log=log)
    player = StopLoggingPlayer(log)
    with Harness(mic=mic, player=player, stt=FakeStt(["biaya"])) as h:
        h.send(Speak("s1", "Jawaban panjang. " * 20, "u1"))
        assert _wait(lambda: "play" in log)
        # TalkPressed saat SPEAKING -> StopSpeaking lalu ListenControl(hold) (Session P03)
        h.send(StopSpeaking("s1"))
        h.send(ListenControl("hold", "s1"))
        (done,) = h.collect(_has(SpeechDone)) and h.of(SpeechDone)
        assert done.interrupted
        assert _wait(lambda: mic.reads >= 5)
        h.send(ReleaseTalk("s1"))
        h.collect(_has(Transcript))
        # mikrofon baru dibuka setelah suara MICA dihentikan: tidak ada audio TTS terekam
        assert log.index("mic resume") > log.index("player stop")
        assert log.index("mic resume") > max(i for i, e in enumerate(log) if e == "play")


def test_no_audio_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mic = StreamMic()
    with Harness(mic=mic, stt=FakeStt(["a"])) as h:
        h.send(ListenControl("hold", "s1"))
        assert _wait(lambda: mic.reads >= 5)
        h.send(ReleaseTalk("s1"))
        h.collect(_has(Transcript))
    assert os.listdir(tmp_path) == []


# --- VAD hanya cek ucapan dan pangkas ---------------------------------------------------------


def test_push_to_talk_utterance_trims_and_detects():
    pcm = np.concatenate([SILENCE] * 5 + [SPEECH] * 4 + [SILENCE] * 6)
    utt = push_to_talk_utterance(pcm, fake_prob(), VALUES["vad.threshold"])
    assert utt is not None and not utt.cut_by_max
    pad = int(0.03 * 16000)
    assert len(utt.pcm16k) == 4 * CHUNK_SAMPLES + 2 * pad  # hening awal/akhir dipangkas
    assert utt.speech_s == 4 * CHUNK_SAMPLES / 16000
    silent = np.concatenate([SILENCE] * 10)
    assert push_to_talk_utterance(silent, fake_prob(), 0.5) is None


def test_eval_stt_push_to_talk_silence_skips_stt():
    item = SpeechItem("d1", Path("x.wav"), "diam", None, None, "P01")
    stt = FakeStt(["palsu"])
    from mica.audio.vad import SpeechSegmenter

    seg = SpeechSegmenter(0.5, 500, 15.0, fake_prob())
    r = evaluate_item(item, np.concatenate([SILENCE] * 20), seg, stt, 250, "push_to_talk")
    assert stt.calls == 0 and r.false_transcript == 0 and r.filtered_by == ("no_voice",)
    q = SpeechItem("q1", Path("x.wav"), "pertanyaan", "biaya", None, "P01")
    pcm = np.concatenate([SILENCE] * 3 + [SPEECH] * 20 + [SILENCE] * 3)
    r = evaluate_item(q, pcm, seg, FakeStt(["biaya"]), 250, "push_to_talk")
    assert r.n_utterances == 1 and r.hypothesis == "biaya" and r.vad_end_s is not None


# --- M-09, UI web, config -----------------------------------------------------------------


def test_config_input_mode_push_to_talk_default():
    for name in ("dev", "prod"):
        text = (ROOT / "config" / f"{name}.yaml").read_text(encoding="utf-8")
        assert "  input_mode: push_to_talk" in text
    assert load_settings(ROOT / "config" / "dev.yaml").audio.input_mode == "push_to_talk"


def test_session_hold_release_cancel_messages():
    from mica.core.session import Session

    s = Session(5.0, None, None, None, None, input_mode="push_to_talk")
    actions = s.handle(TalkPressed(), 0.0)
    assert s.state == VisitState.LISTENING
    assert actions[0] == ListenControl("hold", s.session_id)
    assert actions[-1].message == texts.TALK_HOLD
    actions = s.handle(TalkReleased(), 1.0)
    assert actions[0] == ReleaseTalk(s.session_id) and s.state == VisitState.LISTENING
    s.handle(Transcript(s.session_id, "", False, 0.0, 1.0, False, "no_voice"), 1.2)
    assert s.state == VisitState.READY and s.view.message == texts.NOT_HEARD_HOLD
    s.handle(TalkPressed(), 2.0)
    actions = s.handle(TalkCancelled(), 2.1)
    assert actions[0] == ListenControl("off", s.session_id) and s.view.message == "Dibatalkan"
    assert s.state == VisitState.READY
    # push-to-talk: "auto" tidak pernah dikirim (mikrofon hanya saat ditahan)
    assert s._listen("auto") == ListenControl("off", s.session_id)


def test_web_events_status_and_config():
    vm = ViewModel()
    ui = load_settings(ROOT / "config" / "dev.yaml").ui
    assert isinstance(state.event_from_message({"type": "talk_press"}, vm, ui), TalkPressed)
    assert isinstance(state.event_from_message({"type": "talk_release"}, vm, ui), TalkReleased)
    assert isinstance(state.event_from_message({"type": "talk_cancel"}, vm, ui), TalkCancelled)
    vm.mic_ok = False
    assert state.event_from_message({"type": "talk_press"}, vm, ui) is None
    vm = ViewModel(status=VisitState.LISTENING, status_message=texts.TALK_HOLD)
    assert state.view_json(vm)["status_line"] == "Mendengarkan... lepas tombol untuk mengirim"
    vm = ViewModel(status=VisitState.READY, status_message=texts.TALK_CANCELLED)
    assert state.view_json(vm)["status_line"] == "Dibatalkan"
    vm = ViewModel(status=VisitState.READY, status_message=texts.NOT_HEARD_HOLD)
    assert state.view_json(vm)["status_line"] == (
        "Suara tidak terdengar, coba lagi sambil menahan tombol"
    )
    assert state.config_json(ui, True, input_mode="push_to_talk")["input_mode"] == "push_to_talk"


def test_js_uses_pointer_events_and_space():
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for needle in ('"pointerdown"', '"pointerup"', '"pointercancel"', "setPointerCapture",
                   '"talk_press"', '"talk_release"', '"talk_cancel"', 'e.code !== "Space"',
                   "typingTarget(document.activeElement)", "insideTalk(e)"):  # fmt: skip
        assert needle in js, needle


def test_controller_routes_release_to_audio():
    from mica.core.controller import AppController
    from mica.core.session import Session

    class Bus:
        names = ("vision", "audio")

        def __init__(self):
            self.sent = []

        def poll(self):
            return []

        def send(self, target, msg):
            self.sent.append((target, msg))

    bus = Bus()
    s = Session(5.0, None, None, None, None, input_mode="push_to_talk")
    c = AppController(bus, s, object(), lambda item: None)
    c.submit(TalkPressed())
    c.submit(TalkReleased())
    assert [type(m).__name__ for t, m in bus.sent if t == "audio"] == ["ListenControl",
                                                                       "ReleaseTalk"]  # fmt: skip
