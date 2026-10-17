"""M-08 SpeechToText: faster-whisper small int8 di CPU (ADR-09 Terbuka; Groq Whisper menyusul E-05).

Model harus sudah ada di models/whisper/faster-whisper-<model> (python -m mica.audio fetch-stt-model,
dev saja) dan dimuat hanya dari file lokal; file yang hilang memberi STT_MODEL_MISSING.
faster-whisper diimpor lazy supaya ctranslate2 hanya dimuat oleh pemakai STT.
Parameter: language "id", condition_on_previous_text=False, vad_filter=False (VAD sudah
dilakukan SpeechSegmenter), beam_size bawaan library. Teks kosong -> ok=False.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from mica.audio.vad import SAMPLE_RATE
from mica.core.types import ErrorCode

DEFAULT_WHISPER_DIR = Path("models/whisper")
MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
LANGUAGE = "id"
LIBRARY_DEFAULT_THREADS = 4  # docstring WhisperModel faster-whisper 1.2.1: cpu_threads 0 = 4

# Model STT ADR-09 pada revisi Systran/faster-whisper-small yang dikunci (main per 17 Okt 2026,
# dari https://huggingface.co/api/models/Systran/faster-whisper-small); sha256 diukur saat itu.
WHISPER_REPO = "Systran/faster-whisper-small"
WHISPER_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
WHISPER_MODEL = "small"
WHISPER_SHA256 = {
    "config.json": "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828",
    "model.bin": "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
    "tokenizer.json": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
    "vocabulary.txt": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
}


@dataclass(frozen=True)
class Transcript:
    text: str
    ok: bool
    stt_s: float
    audio_s: float


class SttModelMissing(Exception):
    def __init__(self, path: Path) -> None:
        self.code = ErrorCode.STT_MODEL_MISSING
        self.path = path
        super().__init__(
            f"{self.code}: model STT {Path(path).as_posix()} tidak lengkap; "
            "unduh dulu di mode dev: python -m mica.audio fetch-stt-model"
        )


class SpeechToText(Protocol):
    def transcribe(self, pcm16k: np.ndarray) -> Transcript: ...


def whisper_dir(model: str, whisper_root: Path = DEFAULT_WHISPER_DIR) -> Path:
    """audio.stt.model ("small") -> models/whisper/faster-whisper-small."""
    return Path(whisper_root) / f"faster-whisper-{model}"


def effective_threads(cpu_threads: int | None) -> int:
    """Jumlah thread CPU yang dipakai ctranslate2 untuk nilai audio.stt.threads ini."""
    if cpu_threads:
        return cpu_threads
    omp = os.environ.get("OMP_NUM_THREADS")
    return int(omp) if omp and omp.isdigit() and int(omp) > 0 else LIBRARY_DEFAULT_THREADS


def _load_whisper(path: str, compute_type: str, cpu_threads: int) -> Any:
    from faster_whisper import WhisperModel

    return WhisperModel(
        path,
        device="cpu",
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        local_files_only=True,
    )


class FasterWhisperStt:
    def __init__(
        self,
        model_dir: Path,
        compute_type: str = "int8",
        cpu_threads: int | None = None,
        loader: Callable[[str, str, int], Any] = _load_whisper,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        model_dir = Path(model_dir)
        if not all((model_dir / name).is_file() for name in MODEL_FILES):
            raise SttModelMissing(model_dir)
        self.model_dir = model_dir
        self.cpu_threads = cpu_threads  # None = bawaan library (0)
        self.threads = effective_threads(cpu_threads)
        self.clock = clock
        self.model = loader(str(model_dir), compute_type, cpu_threads or 0)

    def transcribe(self, pcm16k: np.ndarray) -> Transcript:
        audio = np.asarray(pcm16k, dtype=np.int16).astype(np.float32) / 32768.0
        audio_s = len(audio) / SAMPLE_RATE
        start = self.clock()
        segments, _info = self.model.transcribe(
            audio, language=LANGUAGE, condition_on_previous_text=False, vad_filter=False
        )
        text = " ".join(s.text.strip() for s in segments).strip()  # generator: dekode di sini
        return Transcript(text, bool(text), self.clock() - start, audio_s)
