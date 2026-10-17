"""M-08 SpeechSegmenter: memotong aliran mikrofon menjadi ucapan dengan Silero VAD (ADR-10).

Input: potongan 16 kHz int16 mono sepanjang CHUNK_SAMPLES (512 sampel = 32 ms, ukuran tetap
model Silero v5/v6 di pysilero-vad). Keluaran: SpeechStarted saat ucapan mulai, lalu Utterance
saat ucapan selesai.
- mulai bila prob >= threshold;
- selesai bila diam (prob < threshold) >= min_silence_ms; diam di ujung dibuang kecuali padding;
- dipotong paksa saat panjang ucapan mencapai max_utterance_s (cut_by_max=True);
- padding PAD_MS sebelum dan sesudah ucapan.
threshold, min_silence_ms, dan max_utterance_s TBD (E-05), jadi wajib diberikan pemanggil.
Logika murni: prob dihitung lewat fungsi yang bisa diganti di tes. Audio hanya di memori (N-08).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512  # pysilero_vad.SileroVoiceActivityDetector.chunk_samples()
# Bawaan speech_pad_ms = 30 pada VADIterator dan get_speech_timestamps di silero-vad
# (snakers4/silero-vad, src/silero_vad/utils_vad.py)
PAD_MS = 30


@dataclass(frozen=True)
class SpeechStarted:
    at_s: float  # waktu audio sejak segmenter dibuat/direset


@dataclass(frozen=True)
class Utterance:
    pcm16k: np.ndarray  # int16 mono 16 kHz, termasuk padding
    audio_s: float
    cut_by_max: bool


VadEvent = SpeechStarted | Utterance


def silero_prob() -> Callable[[np.ndarray], float]:
    """Fungsi prob ucapan per potongan dari model Silero yang tertanam di pysilero-vad."""
    from pysilero_vad import SileroVoiceActivityDetector

    vad = SileroVoiceActivityDetector()
    if vad.chunk_samples() != CHUNK_SAMPLES:
        raise RuntimeError(f"pysilero-vad meminta {vad.chunk_samples()} sampel per potongan")
    return lambda chunk: float(vad(np.ascontiguousarray(chunk, dtype=np.int16).tobytes()))


class SpeechSegmenter:
    def __init__(
        self,
        threshold: float,
        min_silence_ms: float,
        max_utterance_s: float,
        prob: Callable[[np.ndarray], float],
        pad_ms: float = PAD_MS,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        self.threshold = threshold
        self.prob = prob
        self.sample_rate = sample_rate
        self.min_silence = int(min_silence_ms * sample_rate / 1000)
        self.max_samples = int(max_utterance_s * sample_rate)
        self.pad = int(pad_ms * sample_rate / 1000)
        self.reset()

    def reset(self) -> None:
        self.pre = np.zeros(0, dtype=np.int16)  # ekor audio sebelum ucapan (padding awal)
        self.speech: list[np.ndarray] = []
        self.length = 0
        self.silence = 0  # sampel diam berturut-turut di ujung ucapan
        self.in_speech = False
        self.consumed = 0  # sampel yang sudah diterima

    def _finish(self, cut_by_max: bool) -> Utterance:
        pcm = np.concatenate(self.speech) if self.speech else np.zeros(0, dtype=np.int16)
        if not cut_by_max:
            # buang diam di ujung, sisakan padding akhir
            pcm = pcm[: len(pcm) - max(self.silence - self.pad, 0)]
        self.speech, self.length, self.silence, self.in_speech = [], 0, 0, False
        return Utterance(pcm, len(pcm) / self.sample_rate, cut_by_max)

    def feed(self, chunk: np.ndarray) -> list[VadEvent]:
        chunk = np.asarray(chunk, dtype=np.int16)
        events: list[VadEvent] = []
        speaking = self.prob(chunk) >= self.threshold
        start_s = self.consumed / self.sample_rate
        self.consumed += len(chunk)

        if not self.in_speech:
            if speaking:
                self.in_speech = True
                self.speech = [self.pre[-self.pad :] if self.pad else self.pre[:0], chunk]
                self.length = sum(len(c) for c in self.speech)
                self.silence = 0
                events.append(SpeechStarted(start_s))
            else:
                self.pre = np.concatenate([self.pre, chunk])[-max(self.pad, 1) :]
        else:
            self.speech.append(chunk)
            self.length += len(chunk)
            self.silence = 0 if speaking else self.silence + len(chunk)
            if self.silence >= self.min_silence:
                events.append(self._finish(cut_by_max=False))
            elif self.length >= self.max_samples:
                events.append(self._finish(cut_by_max=True))
            if not self.in_speech:
                self.pre = chunk[-self.pad :] if self.pad else chunk[:0]
        return events
