"""Pembungkus webcam M-07: frame hanya di memori (N-08); gagal baca -> CameraStatus, buka ulang."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from mica.vision.types import CameraStatus

# non-ADR: jeda antar percobaan membuka ulang kamera (SDD 8.1, "coba lagi berkala")
REOPEN_INTERVAL_S = 2.0


def _open_cv2(source: int | str) -> Any:
    import cv2

    if isinstance(source, int) and sys.platform == "win32":
        # backend bawaan Windows (MSMF) butuh sekitar 1 menit untuk membuka webcam di laptop dev
        # (diukur 16 Okt 2026: MSMF 59 s, DSHOW 1,9 s)
        return cv2.VideoCapture(source, cv2.CAP_DSHOW)
    return cv2.VideoCapture(source)


class Camera:
    """read() -> (frame | None, CameraStatus | None); status hanya dikirim saat berubah."""

    def __init__(
        self,
        source: int | str,
        open_capture: Callable[[int | str], Any] = _open_cv2,
        clock: Callable[[], float] = time.monotonic,
        reopen_interval_s: float = REOPEN_INTERVAL_S,
    ) -> None:
        self.source = source
        self.open_capture = open_capture
        self.clock = clock
        self.reopen_interval_s = reopen_interval_s
        self.capture: Any = None
        self.ok: bool | None = None  # belum diketahui
        self.last_open_attempt: float | None = None

    def _status(self, ok: bool, message: str) -> CameraStatus | None:
        if ok == self.ok:
            return None
        self.ok = ok
        return CameraStatus(ok=ok, message=message)

    def _try_open(self) -> bool:
        now = self.clock()
        if self.last_open_attempt is not None and (
            now - self.last_open_attempt < self.reopen_interval_s
        ):
            return False
        self.last_open_attempt = now
        from mica.core import startup

        startup.mark("camera_open_start")
        capture = self.open_capture(self.source)
        if capture is not None and capture.isOpened():
            self.capture = capture
            startup.mark("camera_open_done")
            return True
        startup.mark("camera_open_failed")
        if capture is not None:
            capture.release()
        return False

    def read(self) -> tuple[np.ndarray | None, CameraStatus | None]:
        if self.capture is None and not self._try_open():
            return None, self._status(False, f"kamera {self.source} tidak bisa dibuka")
        ok, frame = self.capture.read()
        if not ok or frame is None:
            self.release()  # dibuka ulang pada read berikutnya setelah jeda
            return None, self._status(False, f"gagal membaca frame dari kamera {self.source}")
        return frame, self._status(True, f"kamera {self.source} terbuka")

    def release(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
