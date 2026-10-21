"""Uji terpandu (--guided-test, dev saja): kotak petunjuk kecil di halaman kiosk berisi langkah
sekarang, hitung mundur, dan langkah berikutnya; program menutup sendiri setelah skenario selesai.

Skenario dimulai saat halaman pertama kali tampil (ack render pertama), bukan saat proses mulai,
supaya penguji melihat langkah pertama dari awal. Pembagian waktu PHASES adalah NILAI DESAIN
skenario uji (Langkah 50), bukan hasil ukur. Fase aktif ikut dicatat di file live per detik
--measure-preview (phase). Tidak ada teks pertanyaan, frame, atau audio yang dicatat (N-08).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class GuidedRefused(Exception):
    pass


def check_allowed(mode: str) -> None:
    if mode != "dev":
        raise GuidedRefused("--guided-test hanya boleh saat app.mode: dev (ditolak di kiosk)")


@dataclass(frozen=True)
class Phase:
    key: str
    start_s: float
    end_s: float
    text: str


# NILAI DESAIN skenario uji (Langkah 50), bukan hasil ukur; total 5 menit
PHASES = (
    Phase("idle", 0, 45, "Menjauh dari kamera, jangan terlihat di pratinjau."),
    Phase("disapa", 45, 90, "Berdiri di depan kiosk dan tunggu sampai MICA menyapa."),
    Phase("ketik", 90, 180, "Ketik 2 pertanyaan bebas tentang PMB; dengarkan jawaban sampai habis."),
    Phase("suara", 180, 255,
          "Tanya 2 pertanyaan lewat suara (tahan tombol Bicara); dengarkan sampai habis."),
    Phase("pergi", 255, 300, "Menjauh dari kamera dan tunggu sampai sesi berakhir."),
)  # fmt: skip
CLOSE_DELAY_S = 3.0  # non-ADR: pesan "uji selesai" tampil sebentar sebelum program menutup


def total_s(phases: tuple[Phase, ...] = PHASES) -> float:
    return phases[-1].end_s


def phase_at(elapsed: float, phases: tuple[Phase, ...] = PHASES) -> Phase | None:
    for phase in phases:
        if phase.start_s <= elapsed < phase.end_s:
            return phase
    return None


def guide_payload(elapsed: float | None, phases: tuple[Phase, ...] = PHASES) -> dict[str, Any]:
    """Isi kotak petunjuk: langkah sekarang, sisa detik langkah ini, dan langkah berikutnya."""
    n = len(phases)
    if elapsed is None:
        first = phases[0]
        return {"type": "guide", "phase": None, "step": 0, "steps": n,
                "text": "Uji terpandu dimulai saat halaman tampil.", "remaining_s": None,
                "next": first.text, "done": False}  # fmt: skip
    phase = phase_at(elapsed, phases)
    if phase is None:
        return {"type": "guide", "phase": "selesai", "step": n, "steps": n,
                "text": "Uji selesai. Program menutup sendiri.", "remaining_s": None,
                "next": None, "done": True}  # fmt: skip
    i = phases.index(phase)
    nxt = phases[i + 1].text if i + 1 < n else None
    return {"type": "guide", "phase": phase.key, "step": i + 1, "steps": n, "text": phase.text,
            "remaining_s": max(0, int(phase.end_s - elapsed + 0.999)), "next": nxt,
            "done": False}  # fmt: skip


class GuidedTest:
    """Thread latar: kirim petunjuk ke halaman setiap detik; set stop setelah skenario selesai."""

    def __init__(
        self,
        started: Callable[[], float | None],
        push: Callable[[dict[str, Any]], None],
        stop: threading.Event,
        phases: tuple[Phase, ...] = PHASES,
        clock: Callable[[], float] = time.perf_counter,
        close_delay_s: float = CLOSE_DELAY_S,
    ) -> None:
        self.started = started  # jam saat halaman pertama tampil (WebUi.first_render_at) atau None
        self.push = push
        self.stop = stop
        self.phases = phases
        self.clock = clock
        self.close_delay_s = close_delay_s
        self.thread: threading.Thread | None = None
        self.finished = False

    def elapsed(self) -> float | None:
        start = self.started()
        return None if start is None else self.clock() - start

    def phase(self) -> str | None:
        """Fase aktif untuk file live: None sebelum mulai, "selesai" setelah skenario."""
        elapsed = self.elapsed()
        if elapsed is None:
            return None
        found = phase_at(elapsed, self.phases)
        return found.key if found is not None else "selesai"

    def step(self) -> bool:
        """Satu putaran; True bila program sudah boleh ditutup."""
        elapsed = self.elapsed()
        payload = guide_payload(elapsed, self.phases)
        self.push(payload)
        if payload["done"]:
            assert elapsed is not None
            if elapsed >= total_s(self.phases) + self.close_delay_s:
                self.finished = True
                return True
        return False

    def _loop(self) -> None:
        while not self.stop.is_set():
            if self.step():
                self.stop.set()  # serve() berhenti rapi: Edge, server, pekerja ditutup
                return
            self.stop.wait(1.0)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name="mica-guided-test", daemon=True)
        self.thread.start()
