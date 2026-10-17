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


class FakeStt:
    """SpeechToText palsu: mengembalikan teks dari daftar secara berurutan."""

    def __init__(self, texts=None, threads=4) -> None:
        self.texts = list(texts or [])
        self.threads = threads
        self.calls = 0

    def transcribe(self, pcm16k):
        from mica.audio.stt import Transcript

        self.calls += 1
        text = self.texts.pop(0) if self.texts else ""
        audio_s = len(pcm16k) / 16000
        return Transcript(text, bool(text), 0.1 * audio_s, audio_s)


class FakeMic:
    """Mikrofon palsu: memutar pola potongan 512 sampel (ucapan = amplitudo 1000, diam = 0).

    pattern berisi jumlah potongan per segmen, mis. [("diam", 5), ("bicara", 10), ...]. Setelah
    pola habis, read_chunk mengembalikan None. pause() membuang sisa buffer (K-6): potongan yang
    dibaca saat pause tidak pernah sampai ke pemanggil.
    """

    def __init__(self, pattern, loop=False) -> None:
        self.chunks = []
        for kind, n in pattern:
            value = 1000 if kind == "bicara" else 0
            self.chunks += [np.full(512, value, dtype=np.int16)] * n
        self.loop = loop
        self.pos = 0
        self.paused = False
        self.events: list[str] = []
        self.input_rate = 16000
        self.resampled = False
        self.closed = False

    def read_chunk(self, timeout_s=1.0):
        if self.pos >= len(self.chunks):
            return None
        chunk = self.chunks[self.pos]
        self.pos += 1
        return chunk

    def pause(self) -> None:
        self.paused = True
        self.events.append("pause")

    def resume(self) -> None:
        self.paused = False
        self.events.append("resume")

    def close(self) -> None:
        self.closed = True


def fake_prob():
    """prob ucapan palsu untuk SpeechSegmenter: 1 bila potongan berisi suara, selain itu 0."""
    return lambda chunk: 1.0 if np.abs(chunk).max() > 0 else 0.0


class FakePlayer:
    """Player palsu: start() mencatat clip; wait() memblok selama durasi clip x speed atau sampai
    stop(). events mencatat urutan "start"/"stop"."""

    def __init__(self, speed: float = 0.0) -> None:
        import threading

        self.speed = speed
        self.events: list[str] = []
        self.started: list[float] = []  # durasi clip yang mulai diputar
        self.stopped = threading.Event()
        self.until = 0.0

    def start(self, clip) -> None:
        self.stopped.clear()
        self.events.append("start")
        self.started.append(clip.duration_s)
        self.until = time.monotonic() + clip.duration_s * self.speed

    def wait(self) -> None:
        remaining = self.until - time.monotonic()
        if remaining > 0:
            self.stopped.wait(remaining)
        self.until = 0.0

    def stop(self) -> None:
        self.events.append("stop")
        self.stopped.set()


# Factory proses suara palsu ("tests.fakes:make_fake_..."), hanya diterima worker saat dev.


def make_fake_audio_mic(device: int | None, options: dict[str, Any]) -> FakeMic:
    if options.get("no_mic"):
        from mica.audio.mic import MicUnavailable

        raise MicUnavailable("tidak ada mikrofon (palsu)")
    return FakeMic([tuple(p) for p in options.get("mic_pattern", [])])


def make_fake_stt(cfg: Any, options: dict[str, Any]) -> FakeStt:
    return FakeStt(options.get("texts"))


def make_fake_tts(cfg: Any, options: dict[str, Any]) -> FakeTts:
    return FakeTts()


def make_fake_player(cfg: Any, options: dict[str, Any]) -> FakePlayer:
    if options.get("no_speaker"):
        from mica.audio.player import SpeakerUnavailable

        raise SpeakerUnavailable("tidak ada speaker (palsu)")
    return FakePlayer(float(options.get("play_speed", 0.0)))


def make_fake_prob(options: dict[str, Any]):
    return fake_prob()
