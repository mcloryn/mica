"""M-09 Session: state machine satu kunjungan (SDD 7.1, M-09; ADR-15, ADR-20).

Session.handle(event, now) -> list[Action] adalah fungsi murni: tanpa I/O, tanpa jam sistem
(waktu hanya dari argumen now), tanpa logging. Aksi dieksekusi pengontrol M-10; event yang
diabaikan dikembalikan sebagai aksi Ignored supaya pengontrol bisa mencatatnya di log debug.
session_id dan utterance_id dibuat lewat fungsi yang bisa disuntik (tes deterministik).

Aturan di luar baris tabel 7.1 (keputusan 17 Okt 2026 dan Langkah 22):
- Pesan pekerja (SpeechStarted, Transcript, SpeechDone) dan AnswerReady dengan session_id
  bukan milik kunjungan aktif dibuang.
- Transcript dengan filtered_by (penyaring min_speech/no_speech) diabaikan, tanpa Speak.
- Mengetik (TextSubmitted/TopicTapped) boleh saat GREETING (sapaan dihentikan) dan LISTENING
  (mikrofon off); teks adalah jalur cadangan N-10.
- Restart vision: CameraStatus(ok=True) setelah status tidak ok -> SetVisionRate sesuai state
  (IDLE -> fps_idle, lainnya -> fps_busy). Bila state bukan IDLE, sesi lanjut dan PersonArrived
  diabaikan sampai sesi berakhir.
- Restart audio: AudioStatus(ready=True) setelah tidak siap, atau ready=True kedua (pekerja
  hanya mengirim ready=True saat start) -> ListenControl sesuai state (READY/LISTENING -> auto,
  lainnya -> off). GREETING/SPEAKING diperlakukan seperti SpeechDone(interrupted) -> READY +
  ListenControl(auto); LISTENING -> READY.
- CameraStatus(ok=False) dan AudioStatus(mic_ok=False) hanya mengubah ShowView.
- IdleTimeout: Tick(now) dengan now - interaksi terakhir > session.idle_reset_s; null = tidak
  pernah. Jeda sapaan ulang session.regreet_cooldown_s; null = tanpa jeda.
- vision.fps_busy null -> SetVisionRate(fps_busy) tidak dikirim (laju tetap fps_idle).
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from mica.audio.messages import (
    AudioStatus,
    ListenControl,
    ListenMode,
    ReleaseTalk,
    Speak,
    SpeechDone,
    SpeechStarted,
    StopSpeaking,
    Transcript,
)
from mica.config import Settings
from mica.core import texts
from mica.core.bus import SetVisionRate
from mica.core.types import Chunk, FinalAnswer, Turn
from mica.rag.pii import scrub_pii
from mica.vision.types import CameraStatus, PersonArrived, PersonLeft


class VisitState(StrEnum):
    IDLE = "IDLE"
    GREETING = "GREETING"
    READY = "READY"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"


# --- event baru (selain pesan bus) -----------------------------------------------------


@dataclass(frozen=True)
class AnswerReady:
    session_id: str
    answer: FinalAnswer


@dataclass(frozen=True)
class TopicTapped:
    topic: str
    question: str  # saran pertanyaan untuk topik itu (ui.topics, F-14)


@dataclass(frozen=True)
class TextSubmitted:
    text: str


@dataclass(frozen=True)
class StopTapped:
    pass


@dataclass(frozen=True)
class TalkPressed:
    """Tombol Bicara mulai ditahan (push-to-talk, Langkah 42)."""


@dataclass(frozen=True)
class TalkReleased:
    """Tombol Bicara dilepas: rekaman dikirim."""


@dataclass(frozen=True)
class TalkCancelled:
    """Pointer keluar dari tombol atau pointercancel: rekaman dibatalkan."""


@dataclass(frozen=True)
class TalkTapped:
    """Tombol bicara (push-to-talk, SDD M-08 Perilaku)."""


@dataclass(frozen=True)
class Tick:
    now: float


Event = (
    PersonArrived
    | PersonLeft
    | CameraStatus
    | SpeechStarted
    | Transcript
    | SpeechDone
    | AudioStatus
    | AnswerReady
    | TopicTapped
    | TextSubmitted
    | StopTapped
    | TalkTapped
    | TalkPressed
    | TalkReleased
    | TalkCancelled
    | Tick
)


# --- aksi baru (selain pesan bus) --------------------------------------------------------


@dataclass(frozen=True)
class RunPipeline:
    session_id: str
    question: str  # teks asli; M-06 menjalankan scrub_pii sebelum API/log
    history: tuple[Turn, ...]
    input_mode: Literal["voice", "text"]


@dataclass(frozen=True)
class ShowView:
    """Potret lengkap tampilan setiap kali berubah."""

    status: VisitState
    message: str | None = None
    transcript: str | None = None  # F-05
    answer: str | None = None
    sources: tuple[Chunk, ...] = ()  # F-09
    send_enabled: bool = True  # tombol kirim nonaktif saat THINKING
    camera_ok: bool = True
    mic_ok: bool = True


@dataclass(frozen=True)
class ClearScreen:
    pass


@dataclass(frozen=True)
class Ignored:
    """Event diabaikan; pengontrol mencatatnya di log debug (SDD 7.1 baris terakhir)."""

    event: str
    state: VisitState
    reason: str


Action = Speak | StopSpeaking | SetVisionRate | ListenControl | ReleaseTalk | RunPipeline | ShowView
Action = Action | ClearScreen | Ignored


def _new_session_id() -> str:
    return uuid.uuid4().hex


def _utterance_ids() -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"u{next(counter)}"


class Session:
    def __init__(
        self,
        fps_idle: float,
        fps_busy: float | None,
        min_majority: float | None,
        idle_reset_s: float | None,
        regreet_cooldown_s: float | None,
        new_session_id: Callable[[], str] = _new_session_id,
        new_utterance_id: Callable[[], str] | None = None,
        input_mode: str = "vad",
    ) -> None:
        self.input_mode = input_mode  # audio.input_mode (Langkah 42)
        self.fps_idle = fps_idle
        self.fps_busy = fps_busy
        self.min_majority = min_majority
        self.idle_reset_s = idle_reset_s
        self.regreet_cooldown_s = regreet_cooldown_s
        self.new_session_id = new_session_id
        self.new_utterance_id = new_utterance_id or _utterance_ids()

        self.state = VisitState.IDLE
        self.session_id = new_session_id()
        self.history: tuple[Turn, ...] = ()
        self.greeting_uid: str | None = None
        self.answer_uid: str | None = None
        self.question: str | None = None  # pertanyaan yang sedang dijawab M-06
        self.last_interaction: float | None = None
        self.cooldown_until = float("-inf")
        self.ignore_arrivals = False  # setelah restart vision di tengah sesi
        self.camera_ok: bool | None = None  # None = belum ada CameraStatus
        self.audio_ready: bool | None = None
        self.mic_ok = True
        self.view = ShowView(VisitState.IDLE)

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Callable[[], str]) -> Session:
        v, s = settings.vision, settings.session
        return cls(v.fps_idle, v.fps_busy, v.color.min_majority, s.idle_reset_s,
                   s.regreet_cooldown_s, **kwargs,
                   input_mode=settings.audio.input_mode)  # fmt: skip

    # --- bantuan ------------------------------------------------------------------------

    def _ignore(self, event: object, reason: str) -> list[Action]:
        return [Ignored(type(event).__name__, self.state, reason)]

    def _show(self, **changes: object) -> ShowView:
        base = {
            "status": self.state,
            "camera_ok": self.camera_ok is not False,
            "mic_ok": self.mic_ok,
            "send_enabled": self.state != VisitState.THINKING,
        }
        self.view = ShowView(**{**base, **changes})  # type: ignore[arg-type]
        return self.view

    def _keep_view(self) -> ShowView:
        """Tampilan sama, hanya status, kamera, dan mikrofon yang diperbarui."""
        return self._show(message=self.view.message, transcript=self.view.transcript,
                          answer=self.view.answer, sources=self.view.sources)  # fmt: skip

    def _busy_rate(self) -> list[Action]:
        return [] if self.fps_busy is None else [SetVisionRate(self.fps_busy)]

    @property
    def push_to_talk(self) -> bool:
        return self.input_mode == "push_to_talk"

    def _listen(self, mode: ListenMode) -> ListenControl:
        if self.push_to_talk and mode == "auto":
            mode = "off"  # push-to-talk: mikrofon hanya merekam selama tombol ditahan
        return ListenControl(mode, self.session_id)

    def _speak(self, text: str) -> tuple[Speak, str]:
        uid = self.new_utterance_id()
        return Speak(self.session_id, text, uid), uid

    def _run(self, question: str, mode: Literal["voice", "text"]) -> RunPipeline:
        self.question = question
        return RunPipeline(self.session_id, question, self.history, mode)

    def _reset(self, now: float) -> list[Action]:
        """PersonLeft atau IdleTimeout (SDD 7.1, F-15)."""
        old = self.session_id
        self.session_id = self.new_session_id()
        self.state = VisitState.IDLE
        self.history = ()
        self.greeting_uid = self.answer_uid = self.question = None
        self.last_interaction = None
        self.ignore_arrivals = False
        self.cooldown_until = now + (self.regreet_cooldown_s or 0.0)
        return [StopSpeaking(old), ClearScreen(), self._listen("off"),
                SetVisionRate(self.fps_idle), self._show()]  # fmt: skip

    # --- handle -------------------------------------------------------------------------

    def handle(self, event: Event, now: float) -> list[Action]:
        if isinstance(event, Tick):
            return self._tick(event.now)
        if isinstance(event, CameraStatus):
            return self._camera(event)
        if isinstance(event, AudioStatus):
            return self._audio(event, now)
        worker = (SpeechStarted, Transcript, SpeechDone, AnswerReady)
        if isinstance(event, worker) and event.session_id != self.session_id:
            return self._ignore(event, "session_id lama")
        if isinstance(event, PersonLeft):
            if self.state == VisitState.IDLE:
                return self._ignore(event, "tidak ada sesi")
            return self._reset(now)
        actions = self._transition(event, now)
        if not (len(actions) == 1 and isinstance(actions[0], Ignored)):
            self.last_interaction = now  # IdleTimeout dihitung ulang setiap interaksi
        return actions

    def _tick(self, now: float) -> list[Action]:
        if (
            self.state != VisitState.IDLE
            and self.idle_reset_s is not None
            and self.last_interaction is not None
            and now - self.last_interaction > self.idle_reset_s
        ):
            return self._reset(now)  # IdleTimeout, berlaku walau kamera mati
        return []

    def _camera(self, event: CameraStatus) -> list[Action]:
        was = self.camera_ok
        self.camera_ok = event.ok
        if not event.ok:
            return [self._keep_view()] if was is not False else []
        if was is not False:
            return []  # status berkala
        # kamera kembali ok setelah mati/restart (proses baru mulai di fps_idle)
        if self.state == VisitState.IDLE:
            return [SetVisionRate(self.fps_idle), self._keep_view()]
        self.ignore_arrivals = True
        return [*self._busy_rate(), self._keep_view()]

    def _audio(self, event: AudioStatus, now: float) -> list[Action]:
        was = self.audio_ready
        mic_was = self.mic_ok
        self.audio_ready = event.ready
        self.mic_ok = event.mic_ok
        restarted = event.ready and was is not None
        if not restarted:
            return [self._keep_view()] if mic_was != self.mic_ok else []
        # proses suara baru: mode off, Speak yang berjalan hilang tanpa SpeechDone
        if self.state in (VisitState.GREETING, VisitState.SPEAKING, VisitState.LISTENING):
            self.state = VisitState.READY
            self.greeting_uid = self.answer_uid = None
            self.last_interaction = now
            return [self._listen("auto"), self._show(message=texts.PLEASE_ASK)]
        mode: ListenMode = "auto" if self.state == VisitState.READY else "off"
        return [self._listen(mode), self._keep_view()]

    def _talk(self, event: TalkPressed | TalkReleased | TalkCancelled) -> list[Action]:
        """Push-to-talk (Langkah 42): tekan = LISTENING (rekam), lepas = proses seperti
        sebelumnya (Transcript), batal = READY. Tekan saat MICA bicara = barge-in."""
        s = self.state
        if isinstance(event, TalkPressed):
            stop: list[Action] = []
            if s == VisitState.IDLE:
                self.session_id = self.new_session_id()
            elif s == VisitState.GREETING:
                self.greeting_uid = None  # SpeechDone sapaan nanti diabaikan
                stop = [StopSpeaking(self.session_id)]
            elif s == VisitState.SPEAKING:
                stop = [StopSpeaking(self.session_id)]
            elif s != VisitState.READY:
                return self._ignore(event, "tombol Bicara hanya di IDLE/READY/GREETING/SPEAKING")
            self.state = VisitState.LISTENING
            return [*stop, self._listen("hold"), self._show(message=texts.TALK_HOLD)]
        if s != VisitState.LISTENING:
            return self._ignore(event, "tombol Bicara tidak sedang ditahan")
        if isinstance(event, TalkReleased):
            return [ReleaseTalk(self.session_id), self._show(message=texts.TALK_PROCESSING)]
        self.state = VisitState.READY
        return [self._listen("off"), self._show(message=texts.TALK_CANCELLED)]

    def _transition(self, event: Event, now: float) -> list[Action]:
        s = self.state
        if isinstance(event, (TalkPressed, TalkReleased, TalkCancelled)):
            if not self.push_to_talk:
                return self._ignore(event, "audio.input_mode vad")
            return self._talk(event)
        if s == VisitState.IDLE:
            if isinstance(event, PersonArrived):
                if now < self.cooldown_until:
                    return self._ignore(event, "masih dalam jeda sapaan ulang")
                return self._greet(event)
            if isinstance(event, (TopicTapped, TextSubmitted)):
                question = _question(event)
                if not question:
                    return self._ignore(event, "teks kosong")
                self.session_id = self.new_session_id()
                return self._think(question, "text")
        elif s == VisitState.GREETING:
            if isinstance(event, SpeechDone) and event.utterance_id == self.greeting_uid:
                self.state = VisitState.READY
                return [self._listen("auto"), self._show(message=texts.PLEASE_ASK)]
            if isinstance(event, (TopicTapped, TextSubmitted)):
                # teks jalur cadangan N-10: sapaan dipotong; SpeechDone-nya nanti diabaikan
                question = _question(event)
                if not question:
                    return self._ignore(event, "teks kosong")
                self.greeting_uid = None
                stop = [StopSpeaking(self.session_id), self._listen("off")]
                return [*stop, *self._think(question, "text")]
        elif s == VisitState.READY:
            if isinstance(event, SpeechStarted):
                self.state = VisitState.LISTENING
                return [self._show(message="mendengarkan")]  # F-20
            if isinstance(event, TalkTapped):
                # satu ucapan berikutnya; proses suara kembali off setelahnya
                return [self._listen("push_to_talk"), self._show(message=texts.TALK_NOW)]
            if isinstance(event, (TopicTapped, TextSubmitted)):
                question = _question(event)
                if not question:
                    return self._ignore(event, "teks kosong")
                return self._think(question, "text")
        elif s == VisitState.LISTENING:
            if isinstance(event, Transcript):
                if event.filtered_by is not None and self.push_to_talk:
                    self.state = VisitState.READY  # tombol sudah dilepas; tidak menunggu lagi
                    return [self._show(message=texts.NOT_HEARD_HOLD)]
                if event.filtered_by is not None:
                    return self._ignore(event, f"tersaring {event.filtered_by}")
                if event.ok and event.text.strip():
                    speak, _uid = self._speak(texts.FILLER)
                    self.state = VisitState.THINKING
                    text = event.text.strip()
                    return [self._show(message="berpikir", transcript=text),
                            self._listen("off"), speak, self._run(text, "voice")]  # fmt: skip
                self.state = VisitState.READY
                not_heard = texts.NOT_HEARD_HOLD if self.push_to_talk else texts.NOT_HEARD
                return [self._show(message=not_heard)]
            if isinstance(event, (TopicTapped, TextSubmitted)):
                question = _question(event)
                if not question:
                    return self._ignore(event, "teks kosong")
                # Transcript yang datang belakangan diabaikan karena state sudah THINKING
                return [self._listen("off"), *self._think(question, "text")]
        elif s == VisitState.THINKING:
            if isinstance(event, AnswerReady):
                answer = event.answer
                speak, self.answer_uid = self._speak(answer.text)
                self.history = (*self.history, Turn(scrub_pii(self.question or ""), answer.text))
                self.state = VisitState.SPEAKING
                return [self._show(transcript=self.view.transcript, answer=answer.text,
                                   sources=answer.sources), speak]  # fmt: skip
            if isinstance(event, TextSubmitted):
                return self._ignore(event, "menunggu jawaban; tombol kirim nonaktif")
        elif s == VisitState.SPEAKING:
            if isinstance(event, SpeechDone) and event.utterance_id == self.answer_uid:
                self.state = VisitState.READY
                return [self._listen("auto"), self._keep_view()]
            if isinstance(event, StopTapped):
                self.state = VisitState.READY
                return [StopSpeaking(self.session_id), self._listen("auto"), self._keep_view()]
        if isinstance(event, PersonArrived) and self.ignore_arrivals:
            return self._ignore(event, "restart vision di tengah sesi")
        return self._ignore(event, "event lain")

    def _greet(self, event: PersonArrived) -> list[Action]:
        self.session_id = self.new_session_id()
        color = None
        if (
            self.min_majority is not None
            and event.color is not None
            and event.color_confidence is not None
            and event.color_confidence >= self.min_majority
        ):
            color = event.color
        speak, self.greeting_uid = self._speak(texts.greeting(color))
        self.state = VisitState.GREETING
        return [speak, *self._busy_rate(), self._listen("off"), self._show()]

    def _think(self, question: str, mode: Literal["voice", "text"]) -> list[Action]:
        self.state = VisitState.THINKING
        return [self._show(message="berpikir", transcript=question), self._run(question, mode)]


def _question(event: TopicTapped | TextSubmitted) -> str:
    return (event.question if isinstance(event, TopicTapped) else event.text).strip()


# --- tabel transisi (diekspor scripts/session_table.py, diuji tests/unit/test_session.py) ---


@dataclass(frozen=True)
class Transition:
    id: str
    frm: str
    event: str
    condition: str
    actions: tuple[str, ...]  # nama kelas aksi, berurutan
    to: str
    source: str  # "SDD 7.1" atau keputusan/penyimpangan


def transitions_markdown(rows: tuple[Transition, ...] | None = None) -> str:
    """Tabel transisi dari kode, untuk dibandingkan dengan SDD 7.1 (scripts/session_table.py)."""
    lines = [
        "# Tabel transisi M-09 (diekspor dari mica.core.session.TRANSITIONS)",
        "",
        "Setiap baris diuji di tests/unit/test_session.py (urutan aksi dan state tujuan).",
        "ShowView adalah potret tampilan; Ignored = dicatat di log debug oleh M-10.",
        "",
        "| ID | Dari | Event | Syarat | Aksi | Ke | Sumber |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in TRANSITIONS if rows is None else rows:
        cells = [r.id, r.frm, r.event, r.condition, ", ".join(r.actions), r.to, r.source]
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(lines) + "\n"


NON_IDLE = "Semua kecuali IDLE"
TRANSITIONS: tuple[Transition, ...] = (
    Transition("T01", "IDLE", "PersonArrived", "Jeda sapaan ulang sudah lewat",
               ("Speak", "SetVisionRate", "ListenControl", "ShowView"), "GREETING", "SDD 7.1"),
    Transition("T02", "IDLE", "PersonArrived", "Masih dalam jeda sapaan ulang", ("Ignored",),
               "IDLE", "SDD 7.1"),
    Transition("T03", "IDLE", "TopicTapped / TextSubmitted", "Teks tidak kosong",
               ("ShowView", "RunPipeline"), "THINKING", "SDD 7.1"),
    Transition("T04", "GREETING", "SpeechDone", "utterance_id sapaan",
               ("ListenControl", "ShowView"), "READY", "SDD 7.1"),
    Transition("T05", "READY", "SpeechStarted", "-", ("ShowView",), "LISTENING", "SDD 7.1"),
    Transition("T06", "READY", "TopicTapped / TextSubmitted", "Teks tidak kosong",
               ("ShowView", "RunPipeline"), "THINKING", "SDD 7.1"),
    Transition("T07", "LISTENING", "Transcript", "ok dan teks tidak kosong",
               ("ShowView", "ListenControl", "Speak", "RunPipeline"), "THINKING", "SDD 7.1"),
    Transition("T08", "LISTENING", "Transcript", "Gagal atau kosong, filtered_by None",
               ("ShowView",), "READY", "SDD 7.1"),
    Transition("T09", "LISTENING", "Transcript", "filtered_by tidak None", ("Ignored",),
               "LISTENING", "Langkah 22"),
    Transition("T10", "THINKING", "AnswerReady", "session_id cocok; tambah history",
               ("ShowView", "Speak"), "SPEAKING", "SDD 7.1"),
    Transition("T11", "THINKING", "TextSubmitted", "-", ("Ignored",), "THINKING", "SDD 7.1"),
    Transition("T12", "SPEAKING", "SpeechDone", "utterance_id jawaban",
               ("ListenControl", "ShowView"), "READY", "SDD 7.1"),
    Transition("T13", "SPEAKING", "StopTapped", "-",
               ("StopSpeaking", "ListenControl", "ShowView"), "READY",
               "SDD 7.1 + ListenControl(auto)"),
    Transition("T14", NON_IDLE, "PersonLeft", "-",
               ("StopSpeaking", "ClearScreen", "ListenControl", "SetVisionRate", "ShowView"),
               "IDLE", "SDD 7.1 + ListenControl(off)"),
    Transition("T15", NON_IDLE, "Tick (IdleTimeout)", "now - interaksi terakhir > idle_reset_s",
               ("StopSpeaking", "ClearScreen", "ListenControl", "SetVisionRate", "ShowView"),
               "IDLE", "SDD 7.1 + ListenControl(off)"),
    Transition("T18", "GREETING", "TopicTapped / TextSubmitted", "Teks tidak kosong",
               ("StopSpeaking", "ListenControl", "ShowView", "RunPipeline"), "THINKING",
               "Keputusan 17 Okt (N-10)"),
    Transition("T19", "LISTENING", "TopicTapped / TextSubmitted", "Teks tidak kosong",
               ("ListenControl", "ShowView", "RunPipeline"), "THINKING",
               "Keputusan 17 Okt (N-10)"),
    Transition("T20", "READY", "TalkTapped", "-", ("ListenControl", "ShowView"), "READY",
               "Langkah 24 (push-to-talk, M-08)"),
    Transition("P01", "IDLE", "TalkPressed", "input_mode push_to_talk; session_id baru",
               ("ListenControl", "ShowView"), "LISTENING", "Langkah 42 (keputusan 18 Okt)"),
    Transition("P02", "READY", "TalkPressed", "input_mode push_to_talk",
               ("ListenControl", "ShowView"), "LISTENING", "Langkah 42 (keputusan 18 Okt)"),
    Transition("P03", "GREETING / SPEAKING", "TalkPressed",
               "input_mode push_to_talk; barge-in, SpeechDone nanti diabaikan",
               ("StopSpeaking", "ListenControl", "ShowView"), "LISTENING",
               "Langkah 42 (keputusan 18 Okt)"),
    Transition("P04", "LISTENING", "TalkReleased", "input_mode push_to_talk",
               ("ReleaseTalk", "ShowView"), "LISTENING", "Langkah 42 (keputusan 18 Okt)"),
    Transition("P05", "LISTENING", "TalkCancelled", "input_mode push_to_talk",
               ("ListenControl", "ShowView"), "READY", "Langkah 42 (keputusan 18 Okt)"),
    Transition("P06", "LISTENING", "Transcript", "input_mode push_to_talk; filtered_by tidak None",
               ("ShowView",), "READY", "Langkah 42 (keputusan 18 Okt)"),
    Transition("P07", "THINKING / LISTENING", "TalkPressed",
               "input_mode push_to_talk; tidak bisa merekam", ("Ignored",), "Tetap", "Langkah 42"),
    Transition("P08", "Semua", "TalkPressed / TalkReleased / TalkCancelled",
               "input_mode vad", ("Ignored",), "Tetap", "Langkah 42"),
    Transition("T16", "Semua", "SpeechStarted / Transcript / SpeechDone / AnswerReady",
               "session_id lama", ("Ignored",), "Tetap", "SDD 3.3, 5.2"),
    Transition("T17", "Semua", "Event lain", "-", ("Ignored",), "Tetap", "SDD 7.1"),
    Transition("R01", "IDLE", "CameraStatus(ok=True)", "Sebelumnya ok=False (restart)",
               ("SetVisionRate", "ShowView"), "IDLE", "Keputusan 17 Okt"),
    Transition("R02", NON_IDLE, "CameraStatus(ok=True)", "Sebelumnya ok=False (restart)",
               ("SetVisionRate", "ShowView"), "Tetap", "Keputusan 17 Okt"),
    Transition("R03", NON_IDLE, "PersonArrived", "Setelah restart vision, sampai sesi berakhir",
               ("Ignored",), "Tetap", "Keputusan 17 Okt"),
    Transition("R04", "GREETING / SPEAKING / LISTENING", "AudioStatus(ready=True)",
               "Setelah tidak siap (restart)", ("ListenControl", "ShowView"), "READY",
               "Keputusan 17 Okt"),
    Transition("R05", "READY", "AudioStatus(ready=True)", "Setelah tidak siap (restart)",
               ("ListenControl", "ShowView"), "READY", "Keputusan 17 Okt"),
    Transition("R06", "IDLE / THINKING", "AudioStatus(ready=True)",
               "Setelah tidak siap (restart); ListenControl(off)", ("ListenControl", "ShowView"),
               "Tetap", "Keputusan 17 Okt"),
    Transition("D01", "Semua", "CameraStatus(ok=False)", "Sebelumnya ok/belum ada",
               ("ShowView",), "Tetap", "Langkah 22"),
    Transition("D02", "Semua", "AudioStatus(mic_ok berubah)", "Bukan restart", ("ShowView",),
               "Tetap", "Langkah 22"),
)  # fmt: skip
