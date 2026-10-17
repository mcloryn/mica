"""UI web (ADR-19, opsi ui.backend: web): Microsoft Edge sebagai proses anak.

Flag (Microsoft Learn, "Configure Microsoft Edge kiosk mode", ms.date 14 Okt 2025, bukti [53];
dicek 17 Okt 2026): --kiosk <url> --edge-kiosk-type=fullscreen (Digital/Interactive signage,
layar penuh) dan --no-first-run.
Flag lain: --user-data-dir=<folder> (Chromium, "User Data Directory",
chromium.googlesource.com/chromium/src/+/main/docs/user_data_dir.md) supaya Edge berjalan
sebagai instance terpisah yang bisa diukur dan ditutup tanpa menyentuh Edge milik pengguna.
Uji 17 Okt 2026 (Edge 155): PID yang diluncurkan adalah proses browser itu sendiri; menutup
jendela membuatnya keluar beserta semua proses anaknya.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

EDGE_PATHS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


class EdgeMissing(Exception):
    pass


def find_edge(paths: tuple[Path, ...] = EDGE_PATHS) -> Path:
    for path in paths:
        if path.is_file():
            return path
    raise EdgeMissing("Microsoft Edge tidak ditemukan di " + ", ".join(str(p) for p in paths))


def edge_command(edge: Path, url: str, user_data_dir: Path, fullscreen: bool) -> list[str]:
    cmd = [str(edge), f"--user-data-dir={user_data_dir}", "--no-first-run"]
    if fullscreen:
        return [*cmd, "--kiosk", url, "--edge-kiosk-type=fullscreen"]
    return [*cmd, url]  # jendela biasa (ui.fullscreen false)


class EdgeBrowser:
    def __init__(self, fullscreen: bool, edge: Path | None = None,
                 popen: Callable[..., Any] = subprocess.Popen) -> None:  # fmt: skip
        self.fullscreen = fullscreen
        self.edge = edge or find_edge()
        self.popen = popen
        self.proc: Any = None
        self.profile: Path | None = None

    def start(self, url: str) -> None:
        self.profile = Path(tempfile.mkdtemp(prefix="mica-edge-"))
        self.proc = self.popen(edge_command(self.edge, url, self.profile, self.fullscreen))

    @property
    def pid(self) -> int | None:
        return None if self.proc is None else self.proc.pid

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def close(self, timeout_s: float = 5.0) -> None:
        """Tutup Edge beserta semua proses anaknya, lalu hapus profil sementara."""
        if self.proc is not None and self.proc.poll() is None:
            import psutil

            try:
                tree = psutil.Process(self.proc.pid)
                children = tree.children(recursive=True)
                tree.terminate()
                _gone, alive = psutil.wait_procs([tree, *children], timeout=timeout_s)
                for p in alive:
                    p.kill()
            except psutil.NoSuchProcess:
                pass
        if self.profile is not None:
            shutil.rmtree(self.profile, ignore_errors=True)
            self.profile = None
