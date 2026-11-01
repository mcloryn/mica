"""E-09: timings lengkap per giliran, first_response (K-3), dan latency_s sapaan (N-06).

Pekerja palsu dengan waktu terkendali: bus palsu di dalam proses, jam palsu, pipeline palsu.
Angka di sini data uji, bukan ambang.
"""

import itertools
import json
from datetime import UTC, datetime

import pytest

from mica.audio.messages import AudioStatus, Speak, SpeechDone, SpeechStarted, Transcript
from mica.core.controller import TURN_TIMING_KEYS, AppController
from mica.core.logging import InteractionLog, TurnRecord
from mica.core.session import Session, TextSubmitted, VisitState
from mica.core.texts import FILLER
from mica.core.types import FinalAnswer, ScrubbedText
from mica.vision.types import PersonArrived, PersonLeft

V = VisitState
PIPE = {"scrub": 0.001, "retrieval": 0.2, "gate": 0.01, "llm": 1.5, "check": 0.05, "total": 1.8}


class Bus:
    names = ("vision", "audio")

    def __init__(self) -> None:
        self.inbox: list = []
        self.sent: list = []

    def poll(self):
        out, self.inbox = self.inbox, []
        return out

    def send(self, target, msg) -> None:
        self.sent.append((target, msg))

    def speaks(self):
        return [m for _, m in self.sent if isinstance(m, Speak)]


class RunPipeline:
    """Pipeline dengan run(): baris M-06 berisi timings tahap pipeline."""

    def answer(self, question, history, session_id, *, input_mode="text"):
        return self.run(question, history, session_id, input_mode=input_mode)[0]

    def run(self, question, history, session_id, *, input_mode="text"):
        final = FinalAnswer("answered", "Biaya Rp7.500.000.", (), dict(PIPE))
        record = TurnRecord(datetime(2026, 10, 18, tzinfo=UTC), session_id, len(history),
                            input_mode, ScrubbedText(str(question)), (), {"passed": True},
                            "groq:x", "ok", "answered", final.text, (), {"ran": True},
                            dict(PIPE), "kb", "hash", "0.1.0")  # fmt: skip
        return final, record


class AnswerOnly:
    """Pipeline tanpa run() (seperti pipeline palsu dev): baris giliran dibuat controller."""

    def answer(self, question, history, session_id, *, input_mode="text"):
        return FinalAnswer("answered", "jawaban palsu", (), {"total": 0.0})


class Rig:
    def __init__(self, tmp_path, pipeline=None) -> None:
        ids = (f"s{i}" for i in itertools.count())
        self.session = Session(5.0, 2.0, 0.5, 30.0, 10.0, new_session_id=lambda: next(ids))
        self.bus = Bus()
        self.t = 0.0
        self.log_dir = tmp_path / "logs"
        self.ctrl = AppController(self.bus, self.session, pipeline or RunPipeline(),
                                    lambda item: None, lambda: self.t, InteractionLog(self.log_dir),
                                    wall_clock=lambda: datetime(2026, 10, 18, tzinfo=UTC))  # fmt: skip

    def at(self, t, *msgs):
        self.t = t
        self.bus.inbox += msgs
        self.ctrl.step()

    def finish_pipeline(self, t):
        for f in list(self.ctrl.pending):
            f.result(timeout=5)
        self.at(t)

    def lines(self, kind):
        files = sorted(self.log_dir.glob(f"{kind}-*.jsonl"))
        text = "".join(p.read_text(encoding="utf-8") for p in files)
        return [json.loads(line) for line in text.splitlines()]

    def greet_and_ready(self, arrived=1.0, audio_start=2.5):
        self.at(0.5, AudioStatus(True, True, True, "siap"))
        self.at(1.1, PersonArrived(1, (0.0, 0.0, 1.0, 1.0), arrived))
        greeting = self.bus.speaks()[-1]
        self.at(4.0, SpeechDone(self.session.session_id, greeting.utterance_id, 0.4,
                                first_audio_t=audio_start))  # fmt: skip
        assert self.session.state == V.READY


def test_voice_turn_has_all_timings_first_response_and_greeting_latency(tmp_path):
    r = Rig(tmp_path)
    r.greet_and_ready(arrived=1.0, audio_start=2.5)
    sid = r.session.session_id
    r.at(8.0, SpeechStarted(sid, 8.0))
    # VAD menyatakan selesai pada 10,0 setelah 0,4 s diam: akhir ucapan = 9,6
    r.at(11.2, Transcript(sid, "biaya kuliah", True, 1.2, 2.0, vad_s=0.4, ended_t=10.0))
    # pipeline palsu bisa selesai di step yang sama; THINKING tidak diperiksa
    r.ctrl.view_rendered("READY", False, 11.25)  # bukan tampilan berpikir: diabaikan
    r.ctrl.view_rendered("THINKING", True, 11.3)
    r.ctrl.view_rendered("THINKING", True, 11.9)  # ack berikutnya tidak menimpa
    r.at(11.35)
    r.finish_pipeline(13.0)
    answer = r.bus.speaks()[-1]
    assert answer.text != FILLER and r.lines("turns") == []  # menunggu audio jawaban
    r.at(14.0, SpeechDone(sid, answer.utterance_id, 0.3, first_audio_t=13.4))
    (turn,) = r.lines("turns")
    timings = turn["timings"]
    assert list(timings)[: len(TURN_TIMING_KEYS)] == list(TURN_TIMING_KEYS)
    assert turn["input_mode"] == "voice"
    assert timings["vad"] == 0.4 and timings["stt"] == 1.2
    assert timings["retrieval"] == 0.2 and timings["llm"] == 1.5 and timings["check"] == 0.05
    assert timings["gate"] == 0.01 and timings["pipeline"] == 1.8
    assert timings["tts_first_audio"] == 0.3
    assert timings["total"] == pytest.approx(13.4 - 9.6)
    assert timings["first_response"] == pytest.approx(11.3 - 9.6)
    (greeted,) = [e for e in r.lines("events") if e["event"] == "greeted"]
    assert greeted["latency_s"] == pytest.approx(2.5 - 1.0)


def test_text_turn_voice_keys_null_not_zero(tmp_path):
    r = Rig(tmp_path, AnswerOnly())
    r.at(0.5, AudioStatus(True, True, True, "siap"))
    r.t = 2.0
    r.ctrl.submit(TextSubmitted("jalur masuk apa saja"))
    r.ctrl.view_rendered("THINKING", True, 2.1)  # ketik: tidak dihitung sebagai K-3
    r.finish_pipeline(2.5)
    answer = r.bus.speaks()[-1]
    r.at(3.5, SpeechDone(r.session.session_id, answer.utterance_id, 0.2, first_audio_t=3.0))
    (turn,) = r.lines("turns")
    timings = turn["timings"]
    assert turn["input_mode"] == "text" and turn["kb_id"] == "-"  # baris dari controller
    for key in ("vad", "stt", "first_response"):
        assert key in timings and timings[key] is None
    for key in ("retrieval", "llm", "check"):  # pipeline palsu tanpa tahap: null, bukan hilang
        assert key in timings and timings[key] is None
    assert timings["tts_first_audio"] == 0.2 and timings["total"] == pytest.approx(1.0)
    assert timings["pipeline"] == 0.0


def test_reset_before_audio_logs_nulls(tmp_path):
    r = Rig(tmp_path)
    r.at(0.5, AudioStatus(True, True, True, "siap"))
    r.at(1.1, PersonArrived(1, (0.0, 0.0, 1.0, 1.0), 1.0))
    r.at(1.5, PersonLeft(1, 1.5, 0.5))  # pergi sebelum audio sapaan mulai
    events = r.lines("events")
    assert [e["event"] for e in events] == ["greeted", "person_left"]
    assert events[0]["latency_s"] is None

    r.t = 5.0
    r.ctrl.submit(TextSubmitted("biaya"))
    r.finish_pipeline(6.0)
    sid = r.session.session_id
    r.at(6.5, PersonArrived(2, (0.0, 0.0, 1.0, 1.0), 6.5))  # tidak mereset (bukan IDLE)
    r.at(7.0, PersonLeft(2, 7.0, 1.0))  # pergi sebelum audio jawaban: tts null
    (turn,) = r.lines("turns")
    assert turn["session_id"] == sid and turn["timings"]["tts_first_audio"] is None
    assert turn["timings"]["total"] == pytest.approx(1.0)  # sampai jawaban diterima controller


def test_stale_answer_after_reset_still_logged(tmp_path):
    r = Rig(tmp_path)
    r.at(0.5, AudioStatus(True, True, True, "siap"))
    r.t = 1.0
    r.ctrl.submit(TextSubmitted("biaya"))
    sid = r.session.session_id
    r.at(1.2, PersonLeft(1, 1.2, 0.1))  # reset saat pipeline berjalan
    r.finish_pipeline(2.0)
    (turn,) = r.lines("turns")
    assert turn["session_id"] == sid and turn["timings"]["tts_first_audio"] is None


def test_shutdown_flushes_pending(tmp_path):
    r = Rig(tmp_path)
    r.at(0.5, AudioStatus(True, True, True, "siap"))
    r.at(1.1, PersonArrived(1, (0.0, 0.0, 1.0, 1.0), 1.0))
    r.ctrl.shutdown()
    assert [e["event"] for e in r.lines("events")] == ["greeted"]
