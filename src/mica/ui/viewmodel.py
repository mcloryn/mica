"""M-10 ViewModel: state tampilan murni (tanpa Qt) yang dibangun dari ShowView dan ClearScreen.

ShowView dari M-09 adalah potret satu giliran (transkripsi + jawaban). ViewModel mengubahnya
menjadi daftar pesan percakapan: pertanyaan masuk saat status THINKING dengan transkripsi,
jawaban masuk saat ShowView membawa jawaban untuk giliran yang sedang terbuka. ClearScreen
mengosongkan percakapan sehingga layar kembali ke layar awal (F-15).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from mica.core import texts
from mica.core.session import ClearScreen, ShowView, VisitState
from mica.core.types import Chunk


@dataclass(frozen=True)
class Source:
    title: str
    valid_from: date  # tanggal berlaku (F-16)


@dataclass(frozen=True)
class Message:
    role: Literal["visitor", "mica"]
    text: str
    sources: tuple[Source, ...] = ()


@dataclass
class ViewModel:
    status: VisitState = VisitState.IDLE
    status_message: str | None = None
    messages: list[Message] = field(default_factory=list)
    last_transcript: str | None = None  # bisa diedit lalu dikirim ulang (US-03)
    send_enabled: bool = True
    camera_ok: bool = True
    mic_ok: bool = True
    turn_open: bool = False  # pertanyaan sudah tampil, jawaban belum

    @property
    def home(self) -> bool:
        """Layar awal (tombol topik) selama belum ada percakapan."""
        return not self.messages

    def apply(self, item: ShowView | ClearScreen) -> None:
        if isinstance(item, ClearScreen):
            self.messages.clear()
            self.last_transcript = None
            self.status_message = None
            self.turn_open = False
            return
        if item.status == VisitState.THINKING and item.transcript and not self.turn_open:
            self.messages.append(Message("visitor", item.transcript))
            self.last_transcript = item.transcript
            self.turn_open = True
        if item.answer is not None and self.turn_open:
            sources = tuple(_source(c) for c in item.sources)
            self.messages.append(Message("mica", item.answer, sources))
            self.turn_open = False
        self.status = item.status
        self.status_message = item.message
        self.send_enabled = item.send_enabled
        self.camera_ok = item.camera_ok
        self.mic_ok = item.mic_ok


def _source(chunk: Chunk) -> Source:
    return Source(chunk.doc_title, chunk.valid_from)


def source_line(source: Source) -> str:
    """Misalnya "Biaya Kuliah (berlaku 29 September 2026)"."""
    d = source.valid_from
    return f"{source.title} (berlaku {d.day} {texts.MONTHS[d.month - 1]} {d.year})"
