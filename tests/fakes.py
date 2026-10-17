"""Kamera dan detektor palsu untuk tes vision worker di proses anak (spawn).

Diimpor lewat path "tests.fakes:make_fake_camera" dan "tests.fakes:make_fake_detector"; hanya
diterima worker saat app.mode: dev. Frame dibuat di memori dan tidak pernah ditulis.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from mica.vision.camera import Camera
from mica.vision.types import PersonTrack

FRAME_SHAPE = (120, 100, 3)
RED_BGR = (0, 0, 255)


class FakeCapture:
    def __init__(self, period_s: float) -> None:
        self.period_s = period_s
        self.frame = np.empty(FRAME_SHAPE, dtype=np.uint8)
        self.frame[:] = RED_BGR

    def isOpened(self) -> bool:
        return True

    def read(self) -> tuple[bool, np.ndarray]:
        time.sleep(self.period_s)
        return True, self.frame.copy()

    def release(self) -> None:
        pass


def make_fake_camera(source: int | str, options: dict[str, Any]) -> Camera:
    period = float(options.get("camera_period_s", 0.01))
    return Camera(source, open_capture=lambda _s: FakeCapture(period))


class FakeDetector:
    """Satu orang (track 1, box 70% tinggi frame, keypoint bahu dan pinggul) selama
    present_s = [mulai, akhir) detik sejak panggilan pertama setelah pemanasan."""

    def __init__(self, present_s: tuple[float, float] | None) -> None:
        self.present_s = present_s
        self.calls = 0
        self.t0: float | None = None

    def detect_and_track(self, frame: np.ndarray) -> list[PersonTrack]:
        self.calls += 1
        if self.calls == 1:  # pemanasan worker
            return []
        now = time.monotonic()
        if self.t0 is None:
            self.t0 = now
        if self.present_s is None:
            return []
        start, end = self.present_s
        if not start <= now - self.t0 < end:
            return []
        h, w = frame.shape[:2]
        kp = np.zeros((17, 3), dtype=np.float32)
        kp[5], kp[6] = (w * 0.7, h * 0.4, 0.9), (w * 0.3, h * 0.4, 0.9)  # bahu
        kp[11], kp[12] = (w * 0.65, h * 0.9, 0.9), (w * 0.35, h * 0.9, 0.9)  # pinggul
        return [PersonTrack(1, (w * 0.2, h * 0.3, w * 0.8, float(h)), 0.9, kp)]


def make_fake_detector(cfg: Any, options: dict[str, Any]) -> FakeDetector:
    present = options.get("present_s")
    return FakeDetector(tuple(present) if present is not None else None)


class FakeTts:
    """TextToSpeech palsu: satu clip per kalimat (dipisah titik), 0,1 s sunyi per kata."""

    sample_rate = 16000

    def __init__(self, voice_file=None, length_scale=None) -> None:
        self.voice_file = voice_file
        self.length_scale = length_scale
        self.calls: list[str] = []

    def stream(self, text: str):
        from mica.audio.tts import AudioClip

        self.calls.append(text)
        for sentence in [s for s in text.split(".") if s.strip()]:
            n = int(0.1 * self.sample_rate) * len(sentence.split())
            yield AudioClip(np.zeros(n, dtype=np.int16), self.sample_rate, 0.01)

    def synthesize(self, text: str):
        from mica.audio.tts import concat

        return concat(list(self.stream(text)))
