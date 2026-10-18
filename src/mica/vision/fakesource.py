"""Sumber gambar palsu untuk mengembangkan UI kiosk tanpa kamera (dev saja; Langkah 37).

Adegan buatan di memori: latar ruangan berpola dan satu siluet (kepala bulat polos, badan dan
kaki persegi) tanpa wajah orang sungguhan. Siluet berjalan masuk, berhenti di tengah, lalu
pergi, berulang setiap CYCLE_S detik. Detektor palsu mengembalikan kotak dan keypoint siluet
dari waktu adegan yang sama, jadi PresenceTracker, warna, dan pratinjau berjalan seperti kamera
asli. Dipakai worker lewat factory "mica.vision.fakesource:make_camera" dan ":make_detector",
yang hanya diterima saat app.mode: dev. Frame tidak pernah ditulis ke disk (N-08).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np

from mica.vision.camera import Camera
from mica.vision.types import PersonTrack

FRAME_W, FRAME_H = 640, 480
CYCLE_S = 30.0
SHIRT_BGR = (200, 90, 30)  # biru (BGR)
SKIN_BGR = (150, 170, 200)
PANTS_BGR = (60, 50, 40)
FPS = 15.0


class FakeScene:
    """frame(t) dan posisi siluet pada detik t sejak mulai (berulang tiap CYCLE_S)."""

    def __init__(self) -> None:
        ys, xs = np.mgrid[0:FRAME_H, 0:FRAME_W]
        bg = np.empty((FRAME_H, FRAME_W, 3), dtype=np.uint8)
        bg[..., 0] = 170 + (xs // 40 % 2) * 20  # panel dinding bergaris
        bg[..., 1] = 175 + (ys * 30 // FRAME_H)
        bg[..., 2] = 180
        bg[FRAME_H * 3 // 4 :] = (110, 120, 130)  # lantai
        bg[60:180, 470:600] = (90, 140, 70)  # papan pengumuman
        self.background = bg

    @staticmethod
    def person_center(t: float) -> float | None:
        """x tengah siluet; None = tidak ada orang. 0-4 s kosong, 4-8 masuk, 8-20 berhenti,
        20-24 pergi, 24-30 kosong."""
        c = t % CYCLE_S
        if c < 4 or c >= 24:
            return None
        if c < 8:
            return -80 + (c - 4) / 4 * (FRAME_W / 2 + 80)
        if c < 20:
            return FRAME_W / 2
        return FRAME_W / 2 + (c - 20) / 4 * (FRAME_W / 2 + 80)

    @staticmethod
    def box(cx: float) -> tuple[float, float, float, float]:
        return cx - 90, 70.0, cx + 90, float(FRAME_H)

    def frame(self, t: float) -> np.ndarray:
        import cv2

        img = self.background.copy()
        cx = self.person_center(t)
        if cx is not None:
            c = round(cx)
            cv2.circle(img, (c, 120), 45, SKIN_BGR, -1)  # kepala polos tanpa wajah
            cv2.rectangle(img, (c - 85, 170), (c + 85, 360), SHIRT_BGR, -1)
            cv2.rectangle(img, (c - 70, 360), (c + 70, FRAME_H), PANTS_BGR, -1)
        return img


def scripted_tracks(scene: FakeScene, t: float) -> list[PersonTrack]:
    cx = scene.person_center(t)
    if cx is None:
        return []
    kp = np.zeros((17, 3), dtype=np.float32)
    kp[5], kp[6] = (cx + 75, 175, 0.9), (cx - 75, 175, 0.9)  # bahu
    kp[11], kp[12] = (cx + 60, 355, 0.9), (cx - 60, 355, 0.9)  # pinggul
    return [PersonTrack(1, scene.box(cx), 0.88, kp)]


class FakeCapture:
    def __init__(self, scene: FakeScene, clock: Callable[[], float], start: float) -> None:
        self.scene, self.clock, self.start = scene, clock, start
        self.next = clock()

    def isOpened(self) -> bool:
        return True

    def read(self) -> tuple[bool, np.ndarray]:
        wait = self.next - self.clock()
        if wait > 0:
            time.sleep(wait)  # laju seperti webcam
        self.next = max(self.next + 1.0 / FPS, self.clock())
        return True, self.scene.frame(self.clock() - self.start)

    def release(self) -> None:
        pass


class FakeDetector:
    def __init__(self, scene: FakeScene, clock: Callable[[], float], start: float) -> None:
        self.scene, self.clock, self.start = scene, clock, start

    def detect_and_track(self, frame: np.ndarray) -> list[PersonTrack]:
        return scripted_tracks(self.scene, self.clock() - self.start)


_SHARED: dict[str, Any] = {}


def _shared() -> tuple[FakeScene, float]:
    """Satu adegan dan waktu mulai bersama kamera dan detektor di proses kamera yang sama."""
    if "scene" not in _SHARED:
        _SHARED["scene"] = FakeScene()
        _SHARED["start"] = time.monotonic()
    return _SHARED["scene"], _SHARED["start"]


def make_camera(source: int | str, options: dict[str, Any]) -> Camera:
    scene, start = _shared()
    return Camera(source, open_capture=lambda _s: FakeCapture(scene, time.monotonic, start))


def make_detector(cfg: Any, options: dict[str, Any]) -> FakeDetector:
    scene, start = _shared()
    return FakeDetector(scene, time.monotonic, start)
