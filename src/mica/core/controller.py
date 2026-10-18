"""KioskController tanpa Qt: memompa bus, meneruskan event ke M-09, mengeksekusi Action (SDD 3.3,
M-10 Struktur).

- step(): poll bus -> event -> Session.handle(event, now) -> eksekusi aksi; lalu jawaban M-06
  yang sudah selesai (AnswerReady) dan terakhir Tick(now). M-10 memanggil step() dari QTimer.
- submit(event): event dari UI (TopicTapped, TextSubmitted, StopTapped) diproses segera.
- Speak, StopSpeaking, ListenControl -> bus "audio"; SetVisionRate -> bus "vision" (pekerja
  yang tidak dimulai dilewati); ShowView, ClearScreen -> view sink; Ignored -> log debug.
- RunPipeline dijalankan di ThreadPoolExecutor(max_workers=1), setara QThreadPool 1 thread
  (SDD 3.3). Teks pertanyaan melewati scrub_pii sebelum masuk pipeline (N-09). Exception
  pipeline -> FinalAnswer(unavailable) dengan teks baku SDD.
- Event kunjungan dicatat lewat InteractionLog.log_event (M-11): greeted, person_left,
  idle_reset, camera_down, mic_down. Teks pertanyaan dan nama warna tidak pernah dicatat.
- Baris giliran (TurnRecord, SDD 6.2) ditulis controller, bukan pipeline, setelah audio jawaban
  mulai, supaya timings lengkap (E-09, docs/E-09.md): vad dan stt dari Transcript, tahap
  pipeline dari baris M-06, tts_first_audio dari SpeechDone, total = akhir ucapan (suara) atau
  kirim (ketik) sampai audio jawaban mulai (tanpa audio: sampai jawaban diterima controller),
  first_response (K-3) = akhir ucapan sampai UI mengirim ack tampilan transkripsi + "berpikir"
  (view_rendered). total milik pipeline disimpan sebagai timings.pipeline. Kunci yang tidak
  berlaku bernilai null (input ketik: vad, stt, first_response).
- greeted dicatat saat audio sapaan mulai (SpeechDone sapaan) dengan latency_s = PersonArrived.t
  (target memenuhi dwell_s) sampai first_audio_t; null bila tidak ada audio atau sesi direset.
- display (opsional, UI web): info tampilan saja tanpa mengubah M-09: teks sapaan yang diucapkan
  (Speak saat IDLE -> GREETING) dan target vision (PersonArrived warna -> terkunci; PersonLeft ->
  tanpa orang). Tidak ada frame; PySide6 tidak memakainya.
- Tidak mengimpor Qt; waktu dari clock (monotonic) dan wall_clock (ts log) yang bisa disuntik.
"""

from __future__ import annotations

import logging
import queue
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, Protocol

from mica.audio.messages import (
    AudioStatus,
    ListenControl,
    ReleaseTalk,
    Speak,
    SpeechDone,
    StopSpeaking,
    Transcript,
)
from mica.core import texts
from mica.core.bus import SetVisionRate
from mica.core.logging import TIMING_KEYS, EventRecord, TurnRecord
from mica.core.session import (
    AnswerReady,
    ClearScreen,
    Event,
    Ignored,
    RunPipeline,
    Session,
    ShowView,
    Tick,
    VisitState,
)
from mica.core.types import ErrorCode, FinalAnswer
from mica.rag.pii import scrub_pii
from mica.rag.prompts import UNAVAILABLE
from mica.vision.types import CameraStatus, PersonArrived, PersonLeft

log = logging.getLogger(__name__)
UI_EVENTS = ("TalkTapped", "StopTapped", "TextSubmitted", "TopicTapped")


class Pipeline(Protocol):
    def answer(
        self,
        question: str,
        history: Any,
        session_id: str,
        *,
        input_mode: Literal["voice", "text"] = "text",
    ) -> FinalAnswer: ...


class EventLog(Protocol):
    def log_event(self, record: EventRecord) -> None: ...


# urutan kunci timings baris giliran: SDD 6.2, lalu K-3, lalu kunci tambahan pipeline
TURN_TIMING_KEYS = (*TIMING_KEYS, "first_response")
VOICE_ONLY_KEYS = ("vad", "stt", "first_response")


@dataclass
class _TurnTiming:
    """Waktu satu giliran yang dikumpulkan controller sampai audio jawaban mulai."""

    session_id: str
    input_mode: Literal["voice", "text"]
    start_t: float  # suara: akhir ucapan; ketik: saat dikirim
    question: str
    vad: float | None = None
    stt: float | None = None
    first_response: float | None = None
    answer: FinalAnswer | None = None
    record: Any = None
    answered_t: float | None = None
    answer_uid: str | None = None


@dataclass
class _PendingGreeting:
    session_id: str
    ts: datetime
    arrived_t: float | None
    uid: str | None
    with_color: bool = False


def _now_local() -> datetime:
    return datetime.now().astimezone()


@dataclass(frozen=True)
class DebugInfo:
    """Isi panel debug M-10 (dev saja). Pertanyaan tidak ikut; hanya angka dan status."""

    state: VisitState
    camera_fps: float | None = None
    final_status: str | None = None
    gate: dict[str, Any] | None = None  # passed, score, threshold
    top_hits: tuple[tuple[str, float], ...] = ()  # (chunk_id, skor) teratas
    llm_provider: str | None = None
    timings: dict[str, float] | None = None


@dataclass(frozen=True)
class DisplayUpdate:
    """Info tampilan tambahan untuk ViewModel (bukan bagian ShowView M-09)."""

    greeting: str | None = None  # teks sapaan yang baru diucapkan
    target_present: bool | None = None  # None = tidak berubah
    target_color: str | None = None  # warna PersonArrived (None = tanpa warna)


class KioskController:
    def __init__(
        self,
        bus: Any,
        session: Session,
        pipeline: Pipeline,
        view: Callable[[ShowView | ClearScreen], None],
        clock: Callable[[], float] = time.monotonic,
        interaction_log: EventLog | None = None,
        wall_clock: Callable[[], datetime] = _now_local,
        debug: Callable[[DebugInfo], None] | None = None,
        display: Callable[[DisplayUpdate], None] | None = None,
    ) -> None:
        """debug (dev saja): menerima DebugInfo; bila pipeline punya run(), baris log M-06
        (gerbang, skor, penyedia) dipakai untuk panel debug."""
        self.bus = bus
        self.session = session
        self.pipeline = pipeline
        self.view = view
        self.clock = clock
        self.interaction_log = interaction_log
        self.wall_clock = wall_clock
        self.debug = debug
        self.display = display
        self.debug_info = DebugInfo(session.state)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mica-pipeline")
        self.answers: queue.Queue[tuple[AnswerReady, Any]] = queue.Queue()
        self.pending: list[Future[None]] = []
        self.turns: list[_TurnTiming] = []  # giliran yang barisnya belum ditulis
        self.greeting: _PendingGreeting | None = None
        self.turn_index: dict[str, int] = {}
        # (status, ada transkripsi, monotonic) dari UI; diisi thread UI, dibaca step()
        self.rendered: queue.Queue[tuple[str, bool, float]] = queue.Queue()

    # --- masukan ------------------------------------------------------------------------

    def step(self) -> None:
        now = self.clock()
        while True:
            try:
                self._on_rendered(*self.rendered.get_nowait())
            except queue.Empty:
                break
        for msg in self.bus.poll():
            self.dispatch(msg, now)
        while True:
            try:
                ready, record = self.answers.get_nowait()
            except queue.Empty:
                break
            turn = next((t for t in self.turns
                         if t.session_id == ready.session_id and t.answer is None), None)  # fmt: skip
            if turn is not None:
                turn.answer, turn.record, turn.answered_t = ready.answer, record, now
            self.dispatch(ready, now)
            if turn is not None:
                current = (self.session.session_id == ready.session_id
                           and self.session.state == VisitState.SPEAKING)  # fmt: skip
                if current and self.session.answer_uid is not None:
                    turn.answer_uid = self.session.answer_uid
                else:
                    self._finish_turn(turn, None)  # jawaban sesi lama: tanpa audio
            if record is not None or self.debug is not None:
                self._update_debug(final=ready.answer, record=record)
        self.dispatch(Tick(now), now)
        self.pending = [f for f in self.pending if not f.done()]

    def submit(self, event: Event) -> None:
        """Event dari UI (TopicTapped, TextSubmitted, StopTapped)."""
        self.dispatch(event, self.clock())

    def view_rendered(self, status: str, has_transcript: bool, t: float) -> None:
        """UI: tampilan dengan status ini sudah digambar (ack) pada monotonic t. Aman dipanggil
        dari thread lain; diproses di step() berikutnya."""
        self.rendered.put((status, has_transcript, t))

    def dispatch(self, event: Event, now: float) -> None:
        before_state = self.session.state
        before_id = self.session.session_id
        before_view = self.session.view
        actions = self.session.handle(event, now)
        for action in actions:
            self._execute(action)
        self._track_timing(event, before_state, before_id, now)
        self._log_visit(event, actions, before_state, before_id, before_view)
        if self.display is not None:
            self._update_display(event, actions, before_state)
        if self.debug is not None:
            fps = event.fps if isinstance(event, CameraStatus) else self.debug_info.camera_fps
            self._update_debug(state=self.session.state, camera_fps=fps)

    def _update_display(self, event: Event, actions: list[Any], before_state: VisitState) -> None:
        assert self.display is not None
        if isinstance(event, PersonArrived):
            self.display(DisplayUpdate(target_present=True, target_color=event.color))
        elif isinstance(event, PersonLeft):
            self.display(DisplayUpdate(target_present=False))
        if before_state == VisitState.IDLE and self.session.state == VisitState.GREETING:
            speak = next((a for a in actions if isinstance(a, Speak)), None)
            if speak is not None:
                self.display(DisplayUpdate(greeting=speak.text))

    def _update_debug(self, final: FinalAnswer | None = None, record: Any = None,
                      **changes: Any) -> None:  # fmt: skip
        if self.debug is None:
            return
        if final is not None:
            changes.update(final_status=final.status, timings=dict(final.timings))
        if record is not None:
            hits = sorted(record.retrieved, key=lambda h: h["score"], reverse=True)
            changes.update(
                gate=dict(record.gate),
                top_hits=tuple((h["chunk_id"], float(h["score"])) for h in hits[:3]),
                llm_provider=record.llm_provider,
            )
        info = replace(self.debug_info, **changes)
        if info != self.debug_info:
            self.debug_info = info
            self.debug(info)

    # --- aksi ---------------------------------------------------------------------------

    def _send(self, target: str, msg: Any) -> None:
        names = getattr(self.bus, "names", (target,))
        if target in names:
            self.bus.send(target, msg)

    def _execute(self, action: Any) -> None:
        if isinstance(action, ListenControl):  # Langkah 42: diagnosis mikrofon
            log.info("ListenControl(%s) ke proses suara", action.mode)
        if isinstance(action, (Speak, StopSpeaking, ListenControl, ReleaseTalk)):
            self._send("audio", action)
        elif isinstance(action, SetVisionRate):
            self._send("vision", action)
        elif isinstance(action, (ShowView, ClearScreen)):
            self.view(action)
        elif isinstance(action, RunPipeline):
            self.pending.append(self.executor.submit(self._run, action))
        elif isinstance(action, Ignored):
            # tanpa teks pertanyaan: hanya nama event, state, dan alasan. Tombol UI yang diabaikan
            # dicatat INFO supaya terlihat (Langkah 42: Bicara diabaikan di luar READY)
            level = logging.INFO if action.event in UI_EVENTS else logging.DEBUG
            log.log(level, "diabaikan %s di %s: %s", action.event, action.state, action.reason)
        else:
            raise TypeError(f"aksi tidak dikenal: {type(action).__name__}")

    def _run(self, action: RunPipeline) -> None:
        """Di thread pipeline; hasil dikirim ke Session lewat antrean pada step() berikutnya."""
        question = scrub_pii(action.question)  # N-09: sebelum pipeline (API, log)
        record = None
        try:
            # history sudah berisi pertanyaan yang di-scrub (Session); run() memberi baris M-06
            # untuk log giliran (ditulis controller) dan panel debug
            run = getattr(self.pipeline, "run", None)
            if run is not None:
                answer, record = run(question, action.history, action.session_id,
                                     input_mode=action.input_mode)  # fmt: skip
            else:
                answer = self.pipeline.answer(question, action.history, action.session_id,
                                              input_mode=action.input_mode)  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - pipeline tidak boleh mematikan kiosk
            log.warning("%s: pipeline gagal (%s)", ErrorCode.LLM_UNAVAILABLE, type(exc).__name__)
            answer = FinalAnswer("unavailable", UNAVAILABLE, (), {})
        self.answers.put((AnswerReady(action.session_id, answer), record))

    # --- waktu giliran dan sapaan (E-09) -------------------------------------------------

    def _track_timing(self, event: Event, before_state: VisitState, before_id: str,
                      now: float) -> None:  # fmt: skip
        after = self.session
        if after.state == VisitState.THINKING and before_state != VisitState.THINKING:
            if isinstance(event, Transcript):
                vad = event.vad_s
                end = now if event.ended_t is None else event.ended_t - (vad or 0.0)
                self.turns.append(_TurnTiming(after.session_id, "voice", end, after.question or "",
                                              vad=vad, stt=event.stt_s))  # fmt: skip
            else:
                self.turns.append(_TurnTiming(after.session_id, "text", now,
                                              after.question or ""))  # fmt: skip
        if before_state == VisitState.IDLE and after.state == VisitState.GREETING:
            self._finish_greeting(None)
            arrived = event.t if isinstance(event, PersonArrived) else None
            self.greeting = _PendingGreeting(after.session_id, self.wall_clock(), arrived,
                                             after.greeting_uid)  # fmt: skip
        if isinstance(event, SpeechDone):
            if self.greeting is not None and event.utterance_id == self.greeting.uid:
                self._finish_greeting(event)
            for turn in list(self.turns):
                if turn.answer_uid is not None and turn.answer_uid == event.utterance_id:
                    self._finish_turn(turn, event)
        reset = before_state != VisitState.IDLE and after.state == VisitState.IDLE
        audio_restart = (isinstance(event, AudioStatus) and before_state == VisitState.GREETING
                         and after.state == VisitState.READY)  # fmt: skip
        g = self.greeting
        if g is not None and (audio_restart or (reset and g.session_id == before_id)):
            self._finish_greeting(None)  # sapaan tanpa audio: sesi direset atau suara restart
        for turn in list(self.turns):
            if turn.answer_uid is None:
                continue
            gone = reset and turn.session_id == before_id
            superseded = after.answer_uid != turn.answer_uid  # Speak hilang (restart) atau baru
            if gone or superseded:
                self._finish_turn(turn, None)

    def _on_rendered(self, status: str, has_transcript: bool, t: float) -> None:
        """K-3: ack pertama tampilan "berpikir" + transkripsi untuk giliran suara terakhir."""
        if status != VisitState.THINKING.value or not has_transcript:
            return
        for turn in reversed(self.turns):
            if turn.session_id != self.session.session_id:
                continue
            if turn.input_mode == "voice" and turn.first_response is None and t >= turn.start_t:
                turn.first_response = t - turn.start_t
            break

    def _finish_greeting(self, done: SpeechDone | None) -> None:
        g, self.greeting = self.greeting, None
        if g is None or self.interaction_log is None:
            return
        latency = None
        if done is not None and done.first_audio_t is not None and g.arrived_t is not None:
            latency = done.first_audio_t - g.arrived_t
        self.interaction_log.log_event(
            EventRecord(g.ts, g.session_id, "greeted", g.with_color, latency)
        )

    def _turn_timings(self, turn: _TurnTiming, done: SpeechDone | None) -> dict[str, float | None]:
        if turn.record is not None:
            base = dict(turn.record.timings)
        else:
            base = dict(turn.answer.timings if turn.answer is not None else {})
        pipeline_total = base.pop("total", None)
        end = turn.answered_t
        if done is not None and done.first_audio_t is not None:
            end = done.first_audio_t
        measured: dict[str, float | None] = {
            "vad": turn.vad, "stt": turn.stt,
            "tts_first_audio": done.tts_first_audio_s if done is not None else None,
            "total": None if end is None else end - turn.start_t,
            "first_response": turn.first_response,
        }  # fmt: skip
        if turn.input_mode == "text":
            measured.update(dict.fromkeys(VOICE_ONLY_KEYS))
        timings: dict[str, float | None] = {}
        for key in TURN_TIMING_KEYS:
            timings[key] = measured[key] if key in measured else base.pop(key, None)
        timings.update(base)  # tambahan pipeline: scrub, gate
        timings["pipeline"] = pipeline_total
        return timings

    def _finish_turn(self, turn: _TurnTiming, done: SpeechDone | None) -> None:
        if turn in self.turns:
            self.turns.remove(turn)
        log_turn = getattr(self.interaction_log, "log_turn", None)
        if log_turn is None or turn.answer is None:
            return
        timings = self._turn_timings(turn, done)
        index = self.turn_index.get(turn.session_id, 0)
        self.turn_index[turn.session_id] = index + 1
        if turn.record is not None:
            record = replace(turn.record, timings=timings)
        else:  # pipeline tanpa run() (pipeline palsu) atau pipeline gagal
            answer = turn.answer
            record = TurnRecord(
                ts=self.wall_clock(), session_id=turn.session_id, turn_index=index,
                input_mode=turn.input_mode, question=scrub_pii(turn.question), retrieved=(),
                gate={}, llm_provider=None, llm_status=None, final_status=answer.status,
                answer=answer.text, sources=tuple(c.chunk_id for c in answer.sources),
                fact_check={}, timings=timings, kb_id="-", config_hash="-", app_version="-",
            )  # fmt: skip
        log_turn(record)

    # --- log kunjungan M-11 -------------------------------------------------------------

    def _log_visit(
        self,
        event: Event,
        actions: list[Any],
        before_state: VisitState,
        before_id: str,
        before_view: ShowView,
    ) -> None:
        if self.interaction_log is None:
            return
        after = self.session
        kind: str | None = None
        with_color = False
        if before_state == VisitState.IDLE and after.state == VisitState.GREETING:
            # dicatat saat audio sapaan mulai (_finish_greeting), dengan latency_s
            speak = next(a for a in actions if isinstance(a, Speak))
            if self.greeting is not None:
                self.greeting.with_color = speak.text != texts.GREETING
            return
        if before_state != VisitState.IDLE and after.state == VisitState.IDLE:
            kind = "idle_reset" if isinstance(event, Tick) else "person_left"
            session_id = before_id
        elif isinstance(event, CameraStatus) and before_view.camera_ok and not event.ok:
            kind, session_id = "camera_down", after.session_id
        elif isinstance(event, AudioStatus) and before_view.mic_ok and not event.mic_ok:
            kind, session_id = "mic_down", after.session_id
        if kind is not None:
            self.interaction_log.log_event(
                EventRecord(self.wall_clock(), session_id, kind, with_color, None)
            )

    # --- berhenti -----------------------------------------------------------------------

    def shutdown(self) -> None:
        """Hentikan executor (pertanyaan yang belum mulai dibatalkan) lalu bus. Sapaan dan
        giliran yang belum tercatat ditulis tanpa waktu audio."""
        self.executor.shutdown(wait=True, cancel_futures=True)
        self._finish_greeting(None)
        for turn in list(self.turns):
            self._finish_turn(turn, None)
        stop = getattr(self.bus, "stop", None)
        if stop is not None:
            stop()
