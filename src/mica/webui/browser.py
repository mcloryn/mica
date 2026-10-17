"""UI web (ADR-19, opsi ui.backend: web): Microsoft Edge sebagai proses anak.

Flag (Microsoft Learn, "Configure Microsoft Edge kiosk mode", ms.date 14 Okt 2025, bukti [53];
dicek 17 Okt 2026): --kiosk <url> --edge-kiosk-type=fullscreen (Digital/Interactive signage,
layar penuh) dan --no-first-run.
Flag lain: --user-data-dir=<folder> (Chromium, "User Data Directory",
chromium.googlesource.com/chromium/src/+/main/docs/user_data_dir.md) supaya Edge berjalan
sebagai instance terpisah yang bisa diukur dan ditutup tanpa menyentuh Edge milik pengguna.
Switch supaya Edge tetap menggambar walau jendelanya tertutup jendela lain / di latar
(RENDERING_SWITCHES; hasil uji --cover-window di docs/UI-WEB.md, "Catatan setelah tahap 1").
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


# Switch Chromium, diverifikasi 17 Okt 2026 di sumber resmi Chromium:
# https://source.chromium.org/chromium/chromium/src/+/main:content/public/common/content_switches.cc
# (dibaca lewat cermin resminya chromium.googlesource.com/chromium/src/+/main/content/public/
# common/content_switches.cc). Edge berbasis Chromium; efeknya di Edge dibuktikan uji, bukan
# diasumsikan.
RENDERING_SWITCHES = (
    # kDisableBackgroundingOccludedWindowsForTesting: "Disable backgrounding renders for
    # occluded windows" (nama konstantanya berakhiran ForTesting)
    "--disable-backgrounding-occluded-windows",
    # kDisableRendererBackgrounding: "renderers are never told that they are backgrounded or
    # hidden", prioritas OS tetap foreground
    "--disable-renderer-backgrounding",
    # kDisableBackgroundTimerThrottling: "Disable task throttling of timer tasks from
    # background pages"
    "--disable-background-timer-throttling",
)


class EdgeMissing(Exception):
    pass


def find_edge(paths: tuple[Path, ...] = EDGE_PATHS) -> Path:
    for path in paths:
        if path.is_file():
            return path
    raise EdgeMissing("Microsoft Edge tidak ditemukan di " + ", ".join(str(p) for p in paths))


def edge_command(edge: Path, url: str, user_data_dir: Path, fullscreen: bool,
                 keep_rendering: bool = True) -> list[str]:  # fmt: skip
    cmd = [str(edge), f"--user-data-dir={user_data_dir}", "--no-first-run"]
    if keep_rendering:
        cmd += RENDERING_SWITCHES
    if fullscreen:
        return [*cmd, "--kiosk", url, "--edge-kiosk-type=fullscreen"]
    return [*cmd, url]  # jendela biasa (ui.fullscreen false)


class EdgeBrowser:
    def __init__(self, fullscreen: bool, edge: Path | None = None,
                 popen: Callable[..., Any] = subprocess.Popen,
                 keep_rendering: bool = True) -> None:  # fmt: skip
        self.fullscreen = fullscreen
        self.keep_rendering = keep_rendering  # False hanya untuk uji pembanding (ui_bench)
        self.edge = edge or find_edge()
        self.popen = popen
        self.proc: Any = None
        self.profile: Path | None = None

    def start(self, url: str) -> None:
        self.profile = Path(tempfile.mkdtemp(prefix="mica-edge-"))
        self.proc = self.popen(edge_command(self.edge, url, self.profile, self.fullscreen,
                                              self.keep_rendering))  # fmt: skip

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
