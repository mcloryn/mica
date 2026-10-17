"""M-08 MicStream: mikrofon mono int16 16 kHz lewat sounddevice (non-ADR, SDD M-08).

- Bila perangkat tidak mendukung 16 kHz, rekam di laju bawaan perangkat lalu resample ke 16 kHz
  (resampled = True; dilaporkan pemanggil).
- read_chunk() mengembalikan potongan tepat CHUNK_SAMPLES untuk SpeechSegmenter.
- pause()/resume() untuk K-6: audio yang masuk saat pause dibuang, termasuk isi buffer.
- Tidak ada mikrofon atau stream gagal dibuka -> MicUnavailable (MIC_DOWN).
Audio hanya di memori, tidak pernah ditulis ke disk (N-08).
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

import numpy as np

from mica.audio.vad import CHUNK_SAMPLES, SAMPLE_RATE
from mica.core.types import ErrorCode


class MicUnavailable(Exception):
    def __init__(self, reason: str) -> None:
        self.code = ErrorCode.MIC_DOWN
        super().__init__(f"{self.code}: {reason}")


def resample_int16(samples: np.ndarray, rate_in: int, rate_out: int) -> np.ndarray:
    """Resample sederhana: rata-rata bergerak sebagai filter anti-alias saat turun laju, lalu
    interpolasi linear (non-ADR; cukup untuk ucapan, tanpa dependensi tambahan)."""
    x = np.asarray(samples, dtype=np.float32)
    if rate_in == rate_out or len(x) == 0:
        return np.asarray(samples, dtype=np.int16)
    if rate_in > rate_out:
        width = int(np.ceil(rate_in / rate_out))
        if width > 1:
            x = np.convolve(x, np.ones(width, dtype=np.float32) / width, mode="same")
    n_out = round(len(x) * rate_out / rate_in)
    t_out = np.arange(n_out) * (rate_in / rate_out)
    y = np.interp(t_out, np.arange(len(x)), x)
    return np.clip(np.round(y), -32768, 32767).astype(np.int16)


def _default_stream_factory(**kwargs: Any) -> Any:
    import sounddevice as sd

    return sd.InputStream(**kwargs)


def _supports_16k(device: int | None) -> bool:
    import sounddevice as sd

    try:
        sd.check_input_settings(device=device, samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    except Exception:  # noqa: BLE001 - PortAudio melempar berbagai jenis error
        return False
    return True


def _device_rate(device: int | None) -> int:
    import sounddevice as sd

    try:
        info = sd.query_devices(device, kind="input")
    except Exception as exc:  # noqa: BLE001
        raise MicUnavailable(f"tidak ada mikrofon ({exc})") from None
    return int(info["default_samplerate"])


class MicStream:
    def __init__(
        self,
        device: int | None = None,
        stream_factory: Callable[..., Any] = _default_stream_factory,
        supports_16k: Callable[[int | None], bool] = _supports_16k,
        device_rate: Callable[[int | None], int] = _device_rate,
    ) -> None:
        self.device = device
        self.input_rate = device_rate(device)  # juga memeriksa mikrofon ada
        if supports_16k(device):
            self.input_rate = SAMPLE_RATE
        self.resampled = self.input_rate != SAMPLE_RATE
        self.queue: queue.Queue[np.ndarray] = queue.Queue()
        self.buffer = np.zeros(0, dtype=np.int16)
        self.paused = threading.Event()
        try:
            self.stream = stream_factory(
                device=device,
                samplerate=self.input_rate,
                channels=1,
                dtype="int16",
                blocksize=0,
                callback=self._callback,
            )
            self.stream.start()
        except Exception as exc:  # noqa: BLE001
            raise MicUnavailable(f"stream mikrofon gagal dibuka ({exc})") from None

    def _callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if self.paused.is_set():
            return  # K-6: audio saat MICA bicara dibuang
        self.queue.put(np.array(indata[:, 0], dtype=np.int16, copy=True))

    def _flush(self) -> None:
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self.buffer = np.zeros(0, dtype=np.int16)

    def pause(self) -> None:
        self.paused.set()
        self._flush()

    def resume(self) -> None:
        self._flush()  # buang apa pun yang masuk di sela pause
        self.paused.clear()

    def read_chunk(self, timeout_s: float = 1.0) -> np.ndarray | None:
        """Potongan CHUNK_SAMPLES pada 16 kHz, atau None bila belum ada audio dalam timeout."""
        while len(self.buffer) < CHUNK_SAMPLES:
            try:
                block = self.queue.get(timeout=timeout_s)
            except queue.Empty:
                return None
            if self.paused.is_set():
                continue
            if self.resampled:
                block = resample_int16(block, self.input_rate, SAMPLE_RATE)
            self.buffer = np.concatenate([self.buffer, block])
        chunk, self.buffer = self.buffer[:CHUNK_SAMPLES], self.buffer[CHUNK_SAMPLES:]
        return chunk

    def close(self) -> None:
        try:
            self.stream.stop()
            self.stream.close()
        finally:
            self._flush()
