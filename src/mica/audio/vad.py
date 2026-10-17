"""M-08 SpeechSegmenter: memotong aliran mikrofon menjadi ucapan dengan Silero VAD (ADR-10).

Input: potongan 16 kHz int16 mono sepanjang CHUNK_SAMPLES (512 sampel = 32 ms, ukuran tetap
model Silero v5/v6 di pysilero-vad). Keluaran: SpeechStarted saat ucapan mulai, lalu Utterance
saat ucapan selesai.
- mulai bila prob >= threshold;
- selesai bila diam (prob < threshold) >= min_silence_ms; diam di ujung dibuang kecuali padding;
- dipotong paksa saat panjang ucapan mencapai max_utterance_s (cut_by_max=True);
- padding PAD_MS sebelum dan sesudah ucapan.
threshold, min_silence_ms, dan max_utterance_s TBD (E-05), jadi wajib diberikan pemanggil.
Utterance juga membawa statistik diagnosis (prob VAD, durasi bicara, awal sejak reset) untuk
konsol dev; is_too_short() adalah penyaring audio.vad.min_speech_ms sebelum STT.
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
    # diagnosis, hanya untuk konsol dev
    speech_s: float = 0.0  # dari potongan bicara pertama sampai terakhir, tanpa padding
    start_s: float = 0.0  # awal ucapan sejak segmenter direset (= sejak mikrofon resume)
    prob_max: float = 0.0
    prob_mean: float = 0.0  # rata-rata prob semua potongan dalam ucapan
    n_above: int = 0  # jumlah potongan dengan prob >= threshold
    # diam di ujung ucapan saat VAD menyatakan selesai (timings.vad, SDD 6.2); 0 bila cut_by_max
    trailing_silence_s: float = 0.0


VadEvent = SpeechStarted | Utterance


def silero_prob() -> Callable[[np.ndarray], float]:
    """Fungsi prob ucapan per potongan dari model Silero yang tertanam di pysilero-vad."""
    from pysilero_vad import SileroVoiceActivityDetector

    vad = SileroVoiceActivityDetector()
    if vad.chunk_samples() != CHUNK_SAMPLES:
        raise RuntimeError(f"pysilero-vad meminta {vad.chunk_samples()} sampel per potongan")
    return lambda chunk: float(vad(np.ascontiguousarray(chunk, dtype=np.int16).tobytes()))


def is_too_short(utterance: Utterance, min_speech_ms: float | None) -> bool:
    """audio.vad.min_speech_ms: ucapan yang bagian bicaranya lebih pendek dibuang sebelum STT.
    None = penyaring mati. Sepadan dengan min_speech_duration_ms Silero (bawaan 250)."""
    return min_speech_ms is not None and utterance.speech_s * 1000 < min_speech_ms


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
        self.pre_len = 0  # panjang padding awal di ucapan berjalan
        self.start_s = 0.0
        self.probs: list[float] = []

    def _finish(self, cut_by_max: bool) -> Utterance:
        pcm = np.concatenate(self.speech) if self.speech else np.zeros(0, dtype=np.int16)
        speech_s = (self.length - self.pre_len - self.silence) / self.sample_rate
        trailing_s = 0.0 if cut_by_max else self.silence / self.sample_rate
        if not cut_by_max:
            # buang diam di ujung, sisakan padding akhir
            pcm = pcm[: len(pcm) - max(self.silence - self.pad, 0)]
        probs = self.probs
        self.speech, self.length, self.silence, self.in_speech = [], 0, 0, False
        self.probs = []
        return Utterance(
            pcm,
            len(pcm) / self.sample_rate,
            cut_by_max,
            speech_s=speech_s,
            start_s=self.start_s,
            prob_max=max(probs),
            prob_mean=sum(probs) / len(probs),
            n_above=sum(p >= self.threshold for p in probs),
            trailing_silence_s=trailing_s,
        )

    def feed(self, chunk: np.ndarray) -> list[VadEvent]:
        chunk = np.asarray(chunk, dtype=np.int16)
        events: list[VadEvent] = []
        prob = self.prob(chunk)
        speaking = prob >= self.threshold
        start_s = self.consumed / self.sample_rate
        self.consumed += len(chunk)

        if not self.in_speech:
            if speaking:
                self.in_speech = True
                self.speech = [self.pre[-self.pad :] if self.pad else self.pre[:0], chunk]
                self.pre_len = len(self.speech[0])
                self.length = sum(len(c) for c in self.speech)
                self.silence = 0
                self.start_s = start_s
                self.probs = [prob]
                events.append(SpeechStarted(start_s))
            else:
                self.pre = np.concatenate([self.pre, chunk])[-max(self.pad, 1) :]
        else:
            self.speech.append(chunk)
            self.probs.append(prob)
            self.length += len(chunk)
            self.silence = 0 if speaking else self.silence + len(chunk)
            if self.silence >= self.min_silence:
                events.append(self._finish(cut_by_max=False))
            elif self.length >= self.max_samples:
                events.append(self._finish(cut_by_max=True))
            if not self.in_speech:
                self.pre = chunk[-self.pad :] if self.pad else chunk[:0]
        return events
