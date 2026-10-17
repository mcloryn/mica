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

from mica.audio.messages import AudioStatus, ListenControl, Speak, StopSpeaking
from mica.core import texts
from mica.core.bus import SetVisionRate
from mica.core.logging import EventRecord
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
from mica.vision.types import CameraStatus

log = logging.getLogger(__name__)


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
        self.debug_info = DebugInfo(session.state)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mica-pipeline")
        self.answers: queue.Queue[tuple[AnswerReady, Any]] = queue.Queue()
        self.pending: list[Future[None]] = []

    # --- masukan ------------------------------------------------------------------------

    def step(self) -> None:
        now = self.clock()
        for msg in self.bus.poll():
            self.dispatch(msg, now)
        while True:
            try:
                ready, record = self.answers.get_nowait()
            except queue.Empty:
                break
            self.dispatch(ready, now)
            if record is not None or self.debug is not None:
                self._update_debug(final=ready.answer, record=record)
        self.dispatch(Tick(now), now)
        self.pending = [f for f in self.pending if not f.done()]

    def submit(self, event: Event) -> None:
        """Event dari UI (TopicTapped, TextSubmitted, StopTapped)."""
        self.dispatch(event, self.clock())

    def dispatch(self, event: Event, now: float) -> None:
        before_state = self.session.state
        before_id = self.session.session_id
        before_view = self.session.view
        actions = self.session.handle(event, now)
        for action in actions:
            self._execute(action)
        self._log_visit(event, actions, before_state, before_id, before_view)
        if self.debug is not None:
            fps = event.fps if isinstance(event, CameraStatus) else self.debug_info.camera_fps
            self._update_debug(state=self.session.state, camera_fps=fps)

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
        if isinstance(action, (Speak, StopSpeaking, ListenControl)):
            self._send("audio", action)
        elif isinstance(action, SetVisionRate):
            self._send("vision", action)
        elif isinstance(action, (ShowView, ClearScreen)):
            self.view(action)
        elif isinstance(action, RunPipeline):
            self.pending.append(self.executor.submit(self._run, action))
        elif isinstance(action, Ignored):
            # tanpa teks pertanyaan: hanya nama event, state, dan alasan
            log.debug("diabaikan %s di %s: %s", action.event, action.state, action.reason)
        else:
            raise TypeError(f"aksi tidak dikenal: {type(action).__name__}")

    def _run(self, action: RunPipeline) -> None:
        """Di thread pipeline; hasil dikirim ke Session lewat antrean pada step() berikutnya."""
        question = scrub_pii(action.question)  # N-09: sebelum pipeline (API, log)
        record = None
        try:
            # history sudah berisi pertanyaan yang di-scrub (Session)
            run = getattr(self.pipeline, "run", None)
            if self.debug is not None and run is not None:
                answer, record = run(question, action.history, action.session_id,
                                     input_mode=action.input_mode)  # fmt: skip
            else:
                answer = self.pipeline.answer(question, action.history, action.session_id,
                                              input_mode=action.input_mode)  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - pipeline tidak boleh mematikan kiosk
            log.warning("%s: pipeline gagal (%s)", ErrorCode.LLM_UNAVAILABLE, type(exc).__name__)
            answer = FinalAnswer("unavailable", UNAVAILABLE, (), {})
        self.answers.put((AnswerReady(action.session_id, answer), record))

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
            kind = "greeted"
            speak = next(a for a in actions if isinstance(a, Speak))
            with_color = speak.text != texts.GREETING
            session_id = after.session_id
        elif before_state != VisitState.IDLE and after.state == VisitState.IDLE:
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
        """Hentikan executor (pertanyaan yang belum mulai dibatalkan) lalu bus."""
        self.executor.shutdown(wait=True, cancel_futures=True)
        stop = getattr(self.bus, "stop", None)
        if stop is not None:
            stop()
