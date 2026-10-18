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


# Switch pengurang kerja latar (Langkah 31 bagian C), hanya yang lolos aturan keputusan
# results/ADR-19/ui-opt-20261017-232949/changes.csv. Diverifikasi 17 Okt 2026 di
# https://source.chromium.org/chromium/chromium/src/+/main:chrome/common/chrome_switches.h
# (dibaca lewat cermin resmi chromium.googlesource.com).
IDLE_SWITCHES = (
    # kDisableComponentUpdate: menonaktifkan pembaruan komponen (component updater).
    # Bench tahap 1 AC: CPU diam 7,06% -> 4,35%, RAM USS diam 196,9 -> 194,0 MB.
    "--disable-component-update",
    # Putaran 2 (docs/UI-WEB.md, "Optimasi putaran 2"): gabungan k1+k2 lolos,
    # results/ADR-19/ui-opt2-combo-20261018-042512 (10 ulangan selang-seling, AC, median):
    # RAM USS diam 194,5 -> 175,1 MB, CPU diam 5,04% -> 4,10%.
    # kDisableComponentExtensionsWithBackgroundPages (chrome/common/chrome_switches.h, dicek
    # 17 Okt 2026): "Disable default component extensions with background pages".
    "--disable-component-extensions-with-background-pages",
    # kRendererProcessLimit (https://source.chromium.org/chromium/chromium/src/+/main:content/
    # public/common/content_switches.cc, dicek 17 Okt 2026): "Overrides the default/calculated
    # limit to the number of renderer processes". Nilai 1: kiosk hanya punya satu halaman.
    "--renderer-process-limit=1",
)


# Switch biaya pratinjau kamera (Langkah 38, pra-registrasi docs/UI-PREVIEW-OPT.md), hanya bila
# ui.camera_preview bukan off (kondisi yang diukur). kDisableGpuCompositing: "Prevent the
# compositor from using its GPU implementation" (https://chromium.googlesource.com/chromium/src/
# +/HEAD/content/public/common/content_switches.cc, dicek 18 Okt 2026). K2 lolos aturan
# keputusan: results/ADR-19/ui-preview-opt-20261018-1712/03-k2-vs-base (10 ulangan
# selang-seling, AC, median): RAM USS diam 391,3 -> 218,1 MB (GPU Edge 213,4 -> 38,3 MB),
# CPU diam 15,70% -> 13,80%, p95 jeda 4,71 -> 3,63 ms.
PREVIEW_SWITCHES = ("--disable-gpu-compositing",)


class EdgeMissing(Exception):
    pass


def find_edge(paths: tuple[Path, ...] = EDGE_PATHS) -> Path:
    for path in paths:
        if path.is_file():
            return path
    raise EdgeMissing("Microsoft Edge tidak ditemukan di " + ", ".join(str(p) for p in paths))


def edge_command(edge: Path, url: str, user_data_dir: Path, fullscreen: bool,
                 keep_rendering: bool = True, camera_preview: str = "off") -> list[str]:  # fmt: skip
    cmd = [str(edge), f"--user-data-dir={user_data_dir}", "--no-first-run", *IDLE_SWITCHES]
    if keep_rendering:
        cmd += RENDERING_SWITCHES
    if camera_preview != "off":
        cmd += PREVIEW_SWITCHES
    if fullscreen:
        return [*cmd, "--kiosk", url, "--edge-kiosk-type=fullscreen"]
    return [*cmd, url]  # jendela biasa (ui.fullscreen false)


class EdgeBrowser:
    def __init__(self, fullscreen: bool, edge: Path | None = None,
                 popen: Callable[..., Any] = subprocess.Popen,
                 keep_rendering: bool = True, camera_preview: str = "off") -> None:  # fmt: skip
        self.fullscreen = fullscreen
        self.keep_rendering = keep_rendering  # False hanya untuk uji pembanding (ui_bench)
        self.camera_preview = camera_preview  # ui.camera_preview; bukan off -> PREVIEW_SWITCHES
        self.edge = edge or find_edge()
        self.popen = popen
        self.proc: Any = None
        self.profile: Path | None = None

    def start(self, url: str) -> None:
        self.profile = Path(tempfile.mkdtemp(prefix="mica-edge-"))
        self.proc = self.popen(edge_command(self.edge, url, self.profile, self.fullscreen,
                                              self.keep_rendering,
                                              self.camera_preview))  # fmt: skip

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
