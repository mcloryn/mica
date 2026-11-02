"""M-08 audio worker (AudioLoop di satu proses), pesan bus suara, Player, dan logika bus-demo.

Mikrofon, STT, TTS, dan speaker palsu dari tests/fakes.py; tidak ada perangkat atau model.
"""

import pickle
import queue
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from tests.fakes import FakeMic, FakePlayer, FakeStt, FakeTts, fake_prob

import mica.audio.__main__ as cli
from mica.audio.messages import (
    AudioStatus,
    ListenControl,
    Speak,
    SpeechDone,
    SpeechStarted,
    StopSpeaking,
    Transcript,
)
from mica.audio.player import SounddevicePlayer, SpeakerUnavailable
from mica.audio.tts import AudioClip
from mica.audio.worker import (
    AudioLoop,
    AudioWorkerConfig,
    AudioWorkerConfigError,
    run_audio_worker,
)
from mica.config import load_settings
from mica.core.bus import Shutdown
from mica.core.types import ErrorCode

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
# data uji, bukan ambang: 160 ms = 5 potongan diam mengakhiri ucapan
VALUES = {"vad.threshold": 0.5, "vad.min_silence_ms": 160, "max_utterance_s": 10.0}
FAKES = {
    "mic_factory": "tests.fakes:make_fake_audio_mic",
    "stt_factory": "tests.fakes:make_fake_stt",
    "tts_factory": "tests.fakes:make_fake_tts",
    "player_factory": "tests.fakes:make_fake_player",
    "prob_factory": "tests.fakes:make_fake_prob",
}
SPEECH = [("diam", 3), ("bicara", 8), ("diam", 6)]
TIMEOUT_S = 10.0


def _settings(mode="dev"):
    s = load_settings(DEV_YAML)
    return s.model_copy(update={"app": s.app.model_copy(update={"mode": mode})})


def _cfg(**overrides):
    return AudioWorkerConfig.from_settings(_settings(), {**VALUES, **overrides}, **FAKES)


class GatedMic(FakeMic):
    """FakeMic yang baru memberi audio setelah gate.set(); log dibagi dengan player."""

    def __init__(self, pattern, log=None) -> None:
        super().__init__(pattern)
        self.gate = threading.Event()
        self.log = log if log is not None else []

    def read_chunk(self, timeout_s=1.0):
        if not self.gate.is_set():
            time.sleep(0.005)
            return None
        return super().read_chunk(timeout_s)

    def pause(self) -> None:
        super().pause()
        self.log.append("mic pause")

    def resume(self) -> None:
        super().resume()
        self.log.append("mic resume")


class LoggingPlayer(FakePlayer):
    def __init__(self, log, speed=0.0) -> None:
        super().__init__(speed)
        self.log = log

    def start(self, clip) -> None:
        super().start(clip)
        self.log.append("play")


class Harness:
    def __init__(self, cfg=None, stt=None, mic="default", player="default", **kw) -> None:
        self.inbox: queue.Queue = queue.Queue()
        self.outbox: queue.Queue = queue.Queue()
        self.got: list = []
        self.stt = stt or FakeStt()
        self.mic = GatedMic([]) if mic == "default" else mic
        self.player = FakePlayer() if player == "default" else player
        self.loop = AudioLoop(cfg or _cfg(), self.inbox, self.outbox, self.stt, FakeTts(),
                              self.mic, self.player, fake_prob(), out=lambda s: None,
                              **kw)  # fmt: skip
        self.thread = threading.Thread(target=self.loop.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.inbox.put(Shutdown())
        self.thread.join(TIMEOUT_S)
        assert not self.thread.is_alive()

    def send(self, msg) -> None:
        self.inbox.put(msg)

    def collect(self, until, timeout_s=TIMEOUT_S):
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            try:
                self.got.append(self.outbox.get(timeout=0.02))
            except queue.Empty:
                pass
            if until(self.got):
                return self.got
        raise AssertionError(f"batas waktu; pesan: {self.got}")

    def of(self, kind):
        return [m for m in self.got if isinstance(m, kind)]


def _has(kind, n=1):
    return lambda ms: sum(isinstance(m, kind) for m in ms) >= n


# --- pesan dan config -------------------------------------------------------------------


@pytest.mark.parametrize(
    "msg",
    [
        SpeechStarted("s1", 1.5),
        Transcript("s1", "biaya", True, 0.4, 1.2, False, None),
        Transcript("s1", "", False, 0.0, 0.1, False, "min_speech"),
        Speak("s1", "Halo.", "u1"),
        StopSpeaking("s1"),
        SpeechDone("s1", "u1", 0.3, interrupted=True),
        ListenControl("push_to_talk", "s1"),
        AudioStatus(mic_ok=True, speaker_ok=False, ready=True, message="x"),
    ],
)
def test_audio_messages_pickle_roundtrip(msg):
    assert pickle.loads(pickle.dumps(msg)) == msg


def test_worker_config_requires_vad_values():
    with pytest.raises(AudioWorkerConfigError) as err:
        AudioWorkerConfig.from_settings(_settings(), {}, **FAKES)
    text = str(err.value)
    assert "audio.vad.threshold" in text and "audio.max_utterance_s" in text


def test_worker_config_filters_null_means_off_and_pickles():
    cfg = _cfg()
    assert cfg.filters == {"vad.min_speech_ms": None, "stt.no_speech_threshold": None}
    assert pickle.loads(pickle.dumps(cfg)) == cfg


def test_worker_config_rejects_fakes_and_diagnose_in_prod():
    with pytest.raises(AudioWorkerConfigError, match="prod"):
        AudioWorkerConfig.from_settings(_settings("prod"), VALUES, **FAKES)
    with pytest.raises(AudioWorkerConfigError, match="diagnosis"):
        AudioWorkerConfig.from_settings(_settings("prod"), VALUES, diagnose=True)


# --- AudioLoop ----------------------------------------------------------------------------


def test_auto_mode_sends_speech_started_and_transcript():
    mic = GatedMic(SPEECH)
    mic.gate.set()
    with Harness(stt=FakeStt(["biaya kuliah berapa"]), mic=mic) as h:
        h.collect(_has(AudioStatus))
        assert h.got[0] == AudioStatus(True, True, True, "mikrofon siap; speaker siap")
        h.send(ListenControl("auto", "s1"))
        h.collect(_has(Transcript))
    (started,) = h.of(SpeechStarted)
    (t,) = h.of(Transcript)
    assert started.session_id == "s1"
    assert (t.session_id, t.text, t.ok, t.cut_by_max, t.filtered_by) == (
        "s1", "biaya kuliah berapa", True, False, None,
    )  # fmt: skip


def test_push_to_talk_captures_one_utterance_then_off():
    mic = GatedMic(SPEECH * 2)
    mic.gate.set()
    stt = FakeStt(["satu", "dua"])
    with Harness(stt=stt, mic=mic) as h:
        h.send(ListenControl("push_to_talk", "s1"))
        h.collect(_has(Transcript))
        time.sleep(0.3)
        h.got += [h.outbox.get_nowait() for _ in range(h.outbox.qsize())]
        assert h.loop.mode == "off"
    assert len(h.of(Transcript)) == 1 and stt.calls == 1


def test_mic_paused_while_speaking_and_resumed_only_when_listening():
    log: list[str] = []
    h = Harness(mic=GatedMic([], log), player=LoggingPlayer(log))
    with h:
        h.send(ListenControl("auto", "s1"))
        h.collect(lambda ms: "mic resume" in log)
        h.send(Speak("s1", "Satu dua. Tiga empat.", "u1"))
        h.collect(_has(SpeechDone))
        h.collect(lambda ms: log[-1] == "mic resume")
        first_play = log.index("play")
        assert "mic pause" in log[log.index("mic resume") : first_play]  # K-6
        assert log.count("play") == 2

        h.send(ListenControl("off", "s1"))
        h.collect(lambda ms: log[-1] == "mic pause")
        h.send(Speak("s1", "Lima.", "u2"))
        h.collect(_has(SpeechDone, 2))
        time.sleep(0.2)
        assert "mic resume" not in log[log.index("play", first_play + 2) :]  # mode off
    done = h.of(SpeechDone)[0]
    assert done.utterance_id == "u1" and not done.interrupted
    assert done.tts_first_audio_s is not None and done.tts_first_audio_s >= 0


def test_stop_speaking_interrupts_and_drops_queued_speak():
    player = FakePlayer(speed=1.0)  # FakeTts: 0,1 s per kata
    text = "Satu dua tiga empat lima. Enam tujuh delapan sembilan sepuluh. Sebelas dua belas."
    with Harness(player=player) as h:
        h.send(Speak("s1", text, "u1"))
        h.send(Speak("s1", "Antre.", "u2"))
        end = time.monotonic() + TIMEOUT_S
        while "start" not in player.events and time.monotonic() < end:
            time.sleep(0.01)
        h.send(StopSpeaking("s1"))
        h.collect(_has(SpeechDone, 2), timeout_s=3.0)
    u1, u2 = h.of(SpeechDone)
    assert u1.utterance_id == "u1" and u1.interrupted and u1.tts_first_audio_s is not None
    assert u2.utterance_id == "u2" and u2.interrupted and u2.tts_first_audio_s is None
    assert len(player.started) == 1  # kalimat sisa tidak diputar


def test_session_id_from_last_speak_attached_to_transcript():
    mic = GatedMic(SPEECH)
    with Harness(stt=FakeStt(["jalur masuk"]), mic=mic) as h:
        h.send(ListenControl("auto", "s1"))
        h.send(Speak("s2", "Halo.", "u1"))
        h.collect(_has(SpeechDone))
        mic.gate.set()
        h.collect(_has(Transcript))
    assert h.of(SpeechStarted)[0].session_id == "s2"
    assert h.of(Transcript)[0].session_id == "s2"


def test_min_speech_filtered_transcript_sent_without_text():
    mic = GatedMic([("bicara", 3), ("diam", 6)] + SPEECH)  # 96 ms lalu ucapan normal
    mic.gate.set()
    stt = FakeStt(["biaya kuliah"])
    with Harness(cfg=_cfg(**{"vad.min_speech_ms": 100}), stt=stt, mic=mic) as h:
        h.send(ListenControl("auto", "s1"))
        h.collect(_has(Transcript, 2))
    short, normal = h.of(Transcript)
    assert (short.ok, short.text, short.filtered_by) == (False, "", "min_speech")
    assert normal.ok and normal.filtered_by is None and stt.calls == 1  # tetap mendengarkan


def test_no_speaker_answers_speak_immediately():
    with Harness(player=None, speaker_message="speaker tidak tersedia: x") as h:
        h.collect(_has(AudioStatus))
        h.send(Speak("s1", "Halo.", "u1"))
        h.collect(_has(SpeechDone))
    assert not h.of(AudioStatus)[0].speaker_ok
    assert h.of(SpeechDone)[0] == SpeechDone("s1", "u1", None, False)


def test_no_mic_reports_mic_down_and_still_speaks():
    inbox: queue.Queue = queue.Queue()
    outbox: queue.Queue = queue.Queue()
    cfg = AudioWorkerConfig.from_settings(_settings(), VALUES, **FAKES,
                                          factory_options={"no_mic": True})  # fmt: skip
    thread = threading.Thread(target=run_audio_worker, args=(cfg, inbox, outbox), daemon=True)
    thread.start()
    status = outbox.get(timeout=TIMEOUT_S)
    assert not status.mic_ok and status.speaker_ok and status.ready
    assert ErrorCode.MIC_DOWN in status.message
    inbox.put(ListenControl("auto", "s1"))  # diabaikan tanpa error
    inbox.put(Speak("s1", "Halo.", "u1"))
    done = outbox.get(timeout=TIMEOUT_S)
    assert isinstance(done, SpeechDone) and not done.interrupted
    inbox.put(Shutdown())
    thread.join(TIMEOUT_S)
    assert not thread.is_alive()


def test_stt_error_stops_worker_with_error():
    class BrokenStt:
        def transcribe(self, pcm):
            raise RuntimeError("rusak")

    mic = GatedMic(SPEECH)
    mic.gate.set()
    h = Harness(stt=BrokenStt(), mic=mic)
    h.thread = threading.Thread(target=lambda: pytest.raises(RuntimeError, h.loop.run),
                                daemon=True)  # fmt: skip
    h.thread.start()
    h.send(ListenControl("auto", "s1"))
    h.thread.join(TIMEOUT_S)
    assert not h.thread.is_alive() and mic.closed


# --- Player -------------------------------------------------------------------------------


class FakeSd:
    def __init__(self, fail_query=False, fail_play=False) -> None:
        self.fail_query, self.fail_play = fail_query, fail_play
        self.calls: list[str] = []

    def query_devices(self, device, kind):
        if self.fail_query:
            raise ValueError("No output device")
        return {"name": "speaker"}

    def play(self, samples, rate, device=None):
        if self.fail_play:
            raise RuntimeError("PortAudio")
        self.calls.append(f"play {rate}")

    def wait(self):
        self.calls.append("wait")

    def stop(self):
        self.calls.append("stop")


def test_sounddevice_player():
    sd = FakeSd()
    player = SounddevicePlayer(sd=sd)
    player.start(AudioClip(np.zeros(10, dtype=np.int16), 22050, 0.0))
    player.wait()
    player.stop()
    assert sd.calls == ["play 22050", "wait", "stop"]
    with pytest.raises(SpeakerUnavailable):
        SounddevicePlayer(sd=FakeSd(fail_query=True))
    with pytest.raises(SpeakerUnavailable):
        SounddevicePlayer(sd=FakeSd(fail_play=True)).start(
            AudioClip(np.zeros(1, dtype=np.int16), 16000, 0.0)
        )


# --- logika bus-demo ----------------------------------------------------------------------


class RecordingBus:
    def __init__(self) -> None:
        self.sent: list = []
        self.dead: set = set()

    def send(self, target, msg) -> None:
        assert target == "audio"
        self.sent.append(msg)


def test_bus_demo_reactions():
    bus = RecordingBus()
    demo = cli.BusDemo(bus, turns=1, out=lambda s: None)
    demo.handle(AudioStatus(True, True, True, "siap"), spawn_s=3.0)
    assert bus.sent[-1].text == cli.DEMO_GREETING
    demo.handle(SpeechDone(demo.session_id, "u1", 0.2))
    assert bus.sent[-1] == ListenControl("auto", demo.session_id)

    n = len(bus.sent)
    demo.handle(Transcript(demo.session_id, "", False, 0.3, 0.2, False, "no_speech"))
    assert len(bus.sent) == n  # tersaring: tanpa Speak, tetap mendengarkan
    assert demo.stats.filtered == {"min_speech": 0, "no_speech": 1}

    demo.handle(Transcript(demo.session_id, "", False, 0.3, 1.0, False, None))
    assert bus.sent[-1].text == cli.DEMO_SORRY
    demo.handle(SpeechDone(demo.session_id, bus.sent[-1].utterance_id, 0.2))
    demo.handle(Transcript(demo.session_id, "biaya kuliah", True, 0.5, 1.5, False, None))
    assert bus.sent[-1].text == "Kamu bertanya: biaya kuliah"
    demo.handle(SpeechDone(demo.session_id, bus.sent[-1].utterance_id, 0.2))
    assert demo.done and demo.answered == 1


def test_bus_demo_push_to_talk_resends_after_filtered():
    bus = RecordingBus()
    demo = cli.BusDemo(bus, turns=1, push_to_talk=True, out=lambda s: None)
    demo.handle(AudioStatus(True, True, True, "siap"))
    demo.handle(SpeechDone(demo.session_id, "u1", 0.2))
    demo.handle(Transcript(demo.session_id, "", False, 0.0, 0.1, False, "min_speech"))
    assert bus.sent[-1] == ListenControl("push_to_talk", demo.session_id)


def test_bus_demo_stop_after_measures_interrupt():
    bus = RecordingBus()
    now = [100.0]
    demo = cli.BusDemo(bus, turns=1, stop_after=2.0, clock=lambda: now[0], out=lambda s: None)
    demo.handle(AudioStatus(True, True, True, "siap"))
    assert bus.sent[-1].text == cli.DEMO_LONG_TEXT
    now[0] += 2.0
    demo.tick()
    assert bus.sent[-1] == StopSpeaking(demo.session_id)
    now[0] += 0.1
    demo.handle(SpeechDone(demo.session_id, "u1", 0.4, interrupted=True))
    assert demo.done and demo.stats.stop_interrupted
    assert demo.stats.stop_s == pytest.approx(0.1)


def test_bus_demo_refused_in_prod():
    args = cli.build_parser().parse_args(["bus-demo"])
    with pytest.raises(cli.AudioCliError, match="app.mode: dev"):
        cli.cmd_bus_demo(args, _settings("prod"))


def test_transcript_and_speech_done_carry_e09_times():
    """E-09: Transcript.vad_s/ended_t dan SpeechDone.first_audio_t (jam monotonic yang sama)."""
    mic = GatedMic(SPEECH)
    mic.gate.set()
    ticks = iter(range(1000, 100000))
    with Harness(mic=mic, clock=lambda: float(next(ticks))) as h:
        h.send(ListenControl("auto", "s1"))
        h.collect(_has(Transcript))
        h.send(Speak("s1", "Halo.", "u1"))
        h.collect(_has(SpeechDone))
    (t,) = h.of(Transcript)
    # min_silence 160 ms = 5 potongan diam 32 ms sebelum VAD menyatakan ucapan selesai
    assert t.vad_s == pytest.approx(5 * 512 / 16000)
    assert t.ended_t is not None and t.ended_t >= 1000
    (done,) = h.of(SpeechDone)
    assert done.first_audio_t is not None and done.first_audio_t > t.ended_t
    assert done.tts_first_audio_s is not None and done.tts_first_audio_s > 0
