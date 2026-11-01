"""AppController ujung ke ujung: bus palsu di dalam proses, pipeline palsu, jam palsu.

Tanpa kamera, mikrofon, speaker, Qt, atau Groq. Angka di sini data uji, bukan ambang.
"""

import itertools
import json
import logging
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

from mica.audio.messages import (
    AudioStatus,
    ListenControl,
    Speak,
    SpeechDone,
    SpeechStarted,
    StopSpeaking,
    Transcript,
)
from mica.core.bus import SetVisionRate
from mica.core.controller import AppController
from mica.core.logging import InteractionLog
from mica.core.session import (
    ClearScreen,
    Session,
    ShowView,
    TextSubmitted,
    TopicTapped,
    VisitState,
)
from mica.core.texts import FILLER, GREETING_COLOR
from mica.core.types import FinalAnswer
from mica.rag.prompts import UNAVAILABLE
from mica.vision.types import CameraStatus, PersonArrived, PersonLeft

ROOT = Path(__file__).resolve().parents[2]
V = VisitState
IDLE_S = 30.0
PHONE, EMAIL = "081234567890", "budi@example.com"


class FakeBus:
    names = ("vision", "audio")

    def __init__(self) -> None:
        self.inbox: list = []
        self.sent: list = []
        self.stopped = False

    def push(self, *msgs) -> None:
        self.inbox += msgs

    def poll(self):
        out, self.inbox = self.inbox, []
        return out

    def send(self, target, msg) -> None:
        self.sent.append((target, msg))

    def stop(self) -> None:
        self.stopped = True

    def of(self, kind, target=None):
        return [m for t, m in self.sent if isinstance(m, kind) and target in (None, t)]


class FakePipeline:
    def __init__(self, text="Biaya Sistem Informasi Rp7.500.000 per tahun.", fail=False,
                 gate=None) -> None:  # fmt: skip
        self.text = text
        self.fail = fail
        self.gate = gate
        self.calls: list = []

    def answer(self, question, history, session_id, *, input_mode="text"):
        self.calls.append((str(question), tuple(history), session_id, input_mode))
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail:
            raise RuntimeError(f"Groq 429 untuk {question}")
        return FinalAnswer("answered", self.text, (), {"total": 0.1})


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class Rig:
    def __init__(self, tmp_path, pipeline=None, fps_busy=2.0) -> None:
        ids = (f"s{i}" for i in itertools.count())
        self.session = Session(5.0, fps_busy, 0.5, IDLE_S, 10.0, new_session_id=lambda: next(ids))
        self.bus = FakeBus()
        self.pipeline = pipeline or FakePipeline()
        self.views: list = []
        self.clock = Clock()
        self.log_dir = tmp_path / "logs"
        self.ctrl = AppController(
            self.bus, self.session, self.pipeline, self.views.append, self.clock,
            InteractionLog(self.log_dir), wall_clock=lambda: datetime(2026, 10, 17, tzinfo=UTC),
        )  # fmt: skip

    def step(self, *msgs, dt=0.05):
        self.clock.t += dt
        self.bus.push(*msgs)
        self.ctrl.step()

    def finish_pipeline(self):
        for f in list(self.ctrl.pending):
            f.result(timeout=5)
        self.step()

    @property
    def sid(self):
        return self.session.session_id

    def greet(self):
        self.step(AudioStatus(True, True, True, "siap"))
        self.step(PersonArrived(1, (0.0, 0.0, 1.0, 1.0), 0.0, "merah", 0.9))
        return self.bus.of(Speak)[-1]

    def to_ready(self):
        greeting = self.greet()
        self.step(SpeechDone(self.sid, greeting.utterance_id, 0.2))

    def ask_by_voice(self, text="biaya kuliah berapa"):
        self.step(SpeechStarted(self.sid, self.clock.t))
        self.step(Transcript(self.sid, text, True, 0.5, 1.5))

    def log_text(self):
        files = sorted(self.log_dir.glob("*.jsonl")) if self.log_dir.exists() else []
        return "".join(p.read_text(encoding="utf-8") for p in files)


def test_a_main_voice_path(tmp_path):
    r = Rig(tmp_path)
    greeting = r.greet()
    assert greeting.text == GREETING_COLOR.format(warna="merah")
    assert r.bus.of(SetVisionRate, "vision") == [SetVisionRate(2.0)]
    r.step(SpeechDone(r.sid, greeting.utterance_id, 0.2))
    assert r.bus.of(ListenControl)[-1] == ListenControl("auto", r.sid)
    r.ask_by_voice(f"nomor saya {PHONE}, biaya kuliah berapa")
    assert r.bus.of(ListenControl)[-1].mode == "off"
    r.finish_pipeline()  # jawaban bisa sudah masuk di step yang sama
    assert [s.text for s in r.bus.of(Speak)][1] == FILLER
    (call,) = r.pipeline.calls
    assert PHONE not in call[0] and "[TELEPON]" in call[0] and call[3] == "voice"
    answer = r.bus.of(Speak)[-1]
    assert answer.text == r.pipeline.text and r.session.state == V.SPEAKING
    r.step(SpeechDone(r.sid, answer.utterance_id, 0.3))
    assert r.session.state == V.READY and r.bus.of(ListenControl)[-1].mode == "auto"
    assert len(r.session.history) == 1 and PHONE not in r.session.history[0].question
    assert all(t == "audio" for t, m in r.bus.sent if isinstance(m, (Speak, ListenControl)))
    assert '"event": "greeted"' in r.log_text() and '"greeted_with_color": true' in r.log_text()


def test_b_typing_while_greeting(tmp_path):
    r = Rig(tmp_path)
    r.greet()
    r.ctrl.submit(TextSubmitted("Biaya kuliah berapa?"))
    assert r.bus.of(StopSpeaking)[-1] == StopSpeaking(r.sid)
    assert r.bus.of(ListenControl)[-1] == ListenControl("off", r.sid)
    assert r.session.state == V.THINKING
    r.finish_pipeline()
    assert r.pipeline.calls[0][0] == "Biaya kuliah berapa?" and r.pipeline.calls[0][3] == "text"
    assert r.session.state == V.SPEAKING


def test_c_typing_while_listening_then_late_transcript(tmp_path):
    r = Rig(tmp_path)
    r.to_ready()
    r.step(SpeechStarted(r.sid, 1.0))
    r.ctrl.submit(TextSubmitted("Jalur masuk apa saja?"))
    r.step(Transcript(r.sid, "jalur masuk", True, 0.5, 1.0))  # telat
    r.finish_pipeline()
    assert len(r.pipeline.calls) == 1 and r.pipeline.calls[0][0] == "Jalur masuk apa saja?"
    assert FILLER not in [s.text for s in r.bus.of(Speak)]


def test_d_leave_while_pipeline_running_drops_answer(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger="mica.core.controller")
    gate = threading.Event()
    r = Rig(tmp_path, FakePipeline(gate=gate))
    r.to_ready()
    r.ask_by_voice()
    speaks_before = len(r.bus.of(Speak))
    r.step(PersonLeft(1, r.clock.t, 3.0))
    assert r.session.state == V.IDLE
    gate.set()
    r.finish_pipeline()
    assert len(r.bus.of(Speak)) == speaks_before  # jawaban lama tidak diucapkan
    assert r.session.state == V.IDLE and r.session.history == ()
    assert "diabaikan AnswerReady" in caplog.text and "session_id lama" in caplog.text
    assert isinstance(r.views[-1], ShowView) and any(isinstance(v, ClearScreen) for v in r.views)
    assert '"event": "person_left"' in r.log_text()


def test_e_pipeline_exception_gives_unavailable(tmp_path, caplog):
    r = Rig(tmp_path, FakePipeline(fail=True))
    r.to_ready()
    r.ctrl.submit(TextSubmitted(f"email saya {EMAIL}"))
    r.finish_pipeline()
    assert r.bus.of(Speak)[-1].text == UNAVAILABLE
    assert r.views[-1].answer == UNAVAILABLE and r.session.state == V.SPEAKING
    assert "LLM_UNAVAILABLE" in caplog.text and EMAIL not in caplog.text


def test_f_audio_restart_while_speaking(tmp_path):
    r = Rig(tmp_path)
    r.to_ready()
    r.ctrl.submit(TextSubmitted("Akreditasi apa?"))
    r.finish_pipeline()
    assert r.session.state == V.SPEAKING
    r.step(AudioStatus(False, False, False, "WORKER_RESTART: proses audio dimulai ulang"))
    r.step(AudioStatus(True, True, True, "siap"))
    assert r.session.state == V.READY
    assert r.bus.of(ListenControl)[-1] == ListenControl("auto", r.sid)


def test_g_idle_timeout_with_fake_clock(tmp_path):
    r = Rig(tmp_path)
    r.to_ready()
    old = r.sid
    r.step(dt=IDLE_S)  # tepat idle_reset_s: belum melewati
    assert r.session.state == V.READY
    r.step(dt=1.0)
    assert r.session.state == V.IDLE and r.bus.of(StopSpeaking)[-1] == StopSpeaking(old)
    assert r.bus.of(SetVisionRate)[-1] == SetVisionRate(5.0)
    assert any(isinstance(v, ClearScreen) for v in r.views)
    assert '"event": "idle_reset"' in r.log_text()


def test_h_no_raw_pii_in_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    r = Rig(tmp_path)
    r.to_ready()
    r.ask_by_voice(f"hubungi {PHONE} atau {EMAIL}, biaya kuliah berapa")
    r.finish_pipeline()
    r.ctrl.submit(TextSubmitted(f"saya di {PHONE}"))  # SPEAKING: diabaikan, tetap tanpa teks
    r.step(CameraStatus(ok=False, message="kamera putus"))
    r.step(AudioStatus(False, True, True, "MIC_DOWN: tidak ada mikrofon"))
    r.step(PersonLeft(1, r.clock.t, 5.0))
    text = r.log_text() + caplog.text
    assert PHONE not in text and EMAIL not in text
    # sejak E-09 controller juga menulis turns-*.jsonl; urutan event dibaca dari events-*.jsonl
    lines = "".join(p.read_text(encoding="utf-8") for p in r.log_dir.glob("events-*.jsonl"))
    events = [json.loads(line)["event"] for line in lines.splitlines()]
    assert events == ["greeted", "camera_down", "mic_down", "person_left"]
    assert all(PHONE not in c[0] and EMAIL not in c[0] for c in r.pipeline.calls)


def test_fps_busy_null_sends_no_busy_rate(tmp_path):
    r = Rig(tmp_path, fps_busy=None)
    r.greet()
    assert r.bus.of(SetVisionRate) == []


def test_shutdown_stops_executor_and_bus(tmp_path):
    r = Rig(tmp_path)
    r.ctrl.shutdown()
    assert r.bus.stopped and r.ctrl.executor._shutdown


def test_controller_imports_no_heavy_modules():
    code = (
        "import sys, mica.core.controller\n"
        "print([m for m in ('PySide6', 'torch', 'ctranslate2', 'onnxruntime') if m in sys.modules])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True, cwd=ROOT)  # fmt: skip
    assert out.stdout.strip() == "[]"


def test_display_hook_reports_greeting_and_target_without_changing_session(tmp_path):
    from mica.core.controller import DisplayUpdate
    from mica.vision.types import PersonLeft

    plain, hooked = Rig(tmp_path / "a"), Rig(tmp_path / "b")
    updates: list = []
    hooked.ctrl.display = updates.append
    for r in (plain, hooked):
        r.greet()
        r.step(PersonLeft(1, 1.0, 1.0))
    assert updates == [
        DisplayUpdate(target_present=True, target_color="merah"),
        DisplayUpdate(greeting=GREETING_COLOR.format(warna="merah")),
        DisplayUpdate(target_present=False),
    ]
    # M-09 tidak berubah: aksi dan state sama dengan controller tanpa hook
    assert [type(m) for _, m in plain.bus.sent] == [type(m) for _, m in hooked.bus.sent]
    assert plain.views == hooked.views and plain.session.state == hooked.session.state


def test_topic_chip_runs_without_previous_question(tmp_path):
    # Langkah 55 (opsi A Langkah 53): pertanyaan chip dijawab tanpa konteks; ketikan tetap
    # membawa history ke pipeline (rag.followup_mode memutuskan cara memakainya)
    rig = Rig(tmp_path)
    rig.to_ready()
    rig.step(TextSubmitted("Di mana alamat kampus?"))
    rig.finish_pipeline()
    rig.step(SpeechDone(rig.sid, rig.bus.of(Speak)[-1].utterance_id, 0.2))
    rig.step(TopicTapped("Biaya", "Bagaimana rincian biaya kuliah S1 di Mikroskil?"))
    rig.finish_pipeline()
    rig.step(SpeechDone(rig.sid, rig.bus.of(Speak)[-1].utterance_id, 0.2))
    rig.step(TextSubmitted("Kalau kelas sorenya?"))
    rig.finish_pipeline()
    (_, h1, *_), (q2, h2, *_), (_, h3, *_) = rig.pipeline.calls
    assert h1 == () and h2 == () and q2.startswith("Bagaimana rincian biaya")
    assert [t.question for t in h3][-1].startswith("Bagaimana rincian biaya")
