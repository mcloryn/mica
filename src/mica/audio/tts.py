"""M-08 TextToSpeech: Piper (ADR-11, provisional). Audio hanya di memori, tidak pernah ke disk (N-08).

normalize_for_speech dipanggil di dalam PiperTts, jadi pemanggil cukup memberi teks jawaban.
File suara harus sudah ada di models/piper/ (python -m mica.audio fetch-voice, dev saja); tidak
ada unduhan saat runtime. piper diimpor lazy supaya onnxruntime hanya dimuat oleh pemakai TTS.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from mica.audio.normalize import normalize_for_speech
from mica.core.types import ErrorCode

DEFAULT_VOICES_DIR = Path("models/piper")


@dataclass(frozen=True)
class AudioClip:
    samples: np.ndarray  # int16 mono
    sample_rate: int
    synth_s: float  # waktu sintesis clip ini

    @property
    def duration_s(self) -> float:
        return len(self.samples) / self.sample_rate if self.sample_rate > 0 else 0.0


class VoiceMissing(Exception):
    def __init__(self, path: Path) -> None:
        self.code = ErrorCode.VOICE_MISSING
        self.path = path
        super().__init__(
            f"{self.code}: file suara {Path(path).as_posix()} tidak ada; "
            "unduh dulu di mode dev: python -m mica.audio fetch-voice"
        )


class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> AudioClip: ...

    def stream(self, text: str) -> Iterator[AudioClip]:
        """Satu clip per kalimat, segera setelah kalimat itu selesai disintesis."""
        ...


def voice_path(voice: str, voices_dir: Path = DEFAULT_VOICES_DIR) -> Path:
    """audio.tts.voice ("id_ID-news_tts-medium") -> models/piper/id_ID-news_tts-medium.onnx."""
    return Path(voices_dir) / f"{voice}.onnx"


def _load_piper(model: str, config: str) -> Any:
    from piper import PiperVoice

    return PiperVoice.load(model, config_path=config)


def concat(clips: list[AudioClip]) -> AudioClip:
    if not clips:
        return AudioClip(np.zeros(0, dtype=np.int16), 0, 0.0)
    samples = np.concatenate([c.samples for c in clips])
    return AudioClip(samples, clips[0].sample_rate, sum(c.synth_s for c in clips))


class PiperTts:
    def __init__(
        self,
        voice_file: Path,
        length_scale: float | None = None,
        loader: Callable[[str, str], Any] = _load_piper,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        voice_file = Path(voice_file)
        config_file = Path(f"{voice_file}.json")
        for path in (voice_file, config_file):
            if not path.is_file():
                raise VoiceMissing(path)
        self.voice_file = voice_file
        self.length_scale = length_scale  # None = bawaan .onnx.json suara
        self.clock = clock
        self.voice = loader(str(voice_file), str(config_file))

    def _syn_config(self) -> Any:
        if self.length_scale is None:
            return None
        from piper import SynthesisConfig

        return SynthesisConfig(length_scale=self.length_scale)

    def stream(self, text: str) -> Iterator[AudioClip]:
        spoken = normalize_for_speech(text)
        start = self.clock()
        for chunk in self.voice.synthesize(spoken, syn_config=self._syn_config()):
            now = self.clock()
            samples = np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16)
            yield AudioClip(samples, chunk.sample_rate, now - start)
            start = self.clock()  # waktu pemanggil memutar clip tidak dihitung

    def synthesize(self, text: str) -> AudioClip:
        return concat(list(self.stream(text)))
