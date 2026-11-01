"""Buka UI web di browser default dalam jendela biasa (RF-2, 1 Nov 2026; ADR-19 final, SDD M-10).

Alamat server dibuka dengan modul `webbrowser` bawaan Python (`webbrowser.open(url, new=1)`).
Browser bukan bagian aplikasi: tidak diluncurkan sebagai proses anak, tidak diberi switch, dan
tidak dipantau. Menutup tab atau jendela browser tidak mematikan server; aplikasi berhenti dengan
Ctrl+C di terminal. Peluncur Edge layar penuh beserta switch-nya (Langkah 29 sampai 38) ada di tag
tahap1-beku.

find_edge dan EDGE_PATHS dipertahankan hanya untuk alat dev yang memakai Edge headless
(tests/unit/test_answer_format.py, scripts/ui_screens.py), bukan untuk menjalankan aplikasi.
"""

from __future__ import annotations

import webbrowser
from collections.abc import Callable
from pathlib import Path

EDGE_PATHS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


class EdgeMissing(Exception):
    pass


def find_edge(paths: tuple[Path, ...] = EDGE_PATHS) -> Path:
    """Alat dev saja (uji kesetaraan answer_format.js, tangkapan layar)."""
    for path in paths:
        if path.is_file():
            return path
    raise EdgeMissing("Microsoft Edge tidak ditemukan di " + ", ".join(str(p) for p in paths))


class DefaultBrowser:
    """Membuka URL di browser default, jendela baru (new=1). Tidak menyimpan PID."""

    def __init__(self, opener: Callable[..., bool] = webbrowser.open) -> None:
        self.opener = opener
        self.opened = False

    def start(self, url: str) -> bool:
        """True bila browser berhasil diminta membuka URL; False bila tidak ada browser."""
        try:
            self.opened = bool(self.opener(url, new=1))
        except webbrowser.Error:
            self.opened = False
        return self.opened
