"""M-08 SpeechToText: faster-whisper small int8 di CPU (ADR-09 Terbuka; Groq Whisper menyusul E-05).

Model harus sudah ada di models/whisper/faster-whisper-<model> (python -m mica.audio fetch-stt-model,
dev saja) dan dimuat hanya dari file lokal; file yang hilang memberi STT_MODEL_MISSING.
faster-whisper diimpor lazy supaya ctranslate2 hanya dimuat oleh pemakai STT.
Parameter: language "id", condition_on_previous_text=False, vad_filter=False (VAD sudah
dilakukan SpeechSegmenter), beam_size bawaan library. Teks kosong -> ok=False.
Penyaring audio.stt.no_speech_threshold: bila semua segmen punya no_speech_prob >= nilai itu,
Transcript(ok=False, text="", filtered_by="no_speech"). Berbeda dari aturan bawaan Whisper
(no_speech_prob > 0.6 DAN avg_logprob < -1.0), penyaring ini tidak melihat avg_logprob.
Statistik segmen terakhir ada di last_segments untuk konsol dev saja.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

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


FilteredBy = Literal["min_speech", "no_speech"]


@dataclass(frozen=True)
class Transcript:
    text: str
    ok: bool
    stt_s: float
    audio_s: float
    # Penyimpangan dari SDD 5.2: penyaring yang membuang ucapan ini, None bila tidak tersaring
    filtered_by: FilteredBy | None = None


@dataclass(frozen=True)
class SegmentStats:
    no_speech_prob: float
    avg_logprob: float


def is_no_speech(segments: list[SegmentStats], threshold: float | None) -> bool:
    """True bila ada segmen dan semuanya no_speech_prob >= threshold; None = penyaring mati.
    Nilai coba 0.6 = bawaan no_speech_threshold Whisper/faster-whisper."""
    if threshold is None or not segments:
        return False
    return all(s.no_speech_prob >= threshold for s in segments)


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
        no_speech_threshold: float | None = None,
        loader: Callable[[str, str, int], Any] = _load_whisper,
        clock: Callable[[], float] = time.perf_counter,
        hotwords: str | None = None,
    ) -> None:
        """hotwords: petunjuk kosakata (E-05), diteruskan ke WhisperModel.transcribe(hotwords=)
        faster-whisper 1.2.1; None = tidak dipakai (parameter tidak dikirim)."""
        model_dir = Path(model_dir)
        if not all((model_dir / name).is_file() for name in MODEL_FILES):
            raise SttModelMissing(model_dir)
        self.model_dir = model_dir
        self.cpu_threads = cpu_threads  # None = bawaan library (0)
        self.threads = effective_threads(cpu_threads)
        self.no_speech_threshold = no_speech_threshold
        self.hotwords = hotwords
        self.last_segments: list[SegmentStats] = []
        self.clock = clock
        self.model = loader(str(model_dir), compute_type, cpu_threads or 0)

    def transcribe(self, pcm16k: np.ndarray) -> Transcript:
        audio = np.asarray(pcm16k, dtype=np.int16).astype(np.float32) / 32768.0
        audio_s = len(audio) / SAMPLE_RATE
        start = self.clock()
        extra = {} if self.hotwords is None else {"hotwords": self.hotwords}
        segments, _info = self.model.transcribe(
            audio, language=LANGUAGE, condition_on_previous_text=False, vad_filter=False, **extra
        )
        decoded = list(segments)  # generator: dekode di sini
        self.last_segments = [SegmentStats(s.no_speech_prob, s.avg_logprob) for s in decoded]
        stt_s = self.clock() - start
        if is_no_speech(self.last_segments, self.no_speech_threshold):
            return Transcript("", False, stt_s, audio_s, filtered_by="no_speech")
        text = " ".join(s.text.strip() for s in decoded).strip()
        return Transcript(text, bool(text), stt_s, audio_s)


# --- Groq Whisper (ADR-09 kandidat E-05) -------------------------------------------------

# Dari https://console.groq.com/docs/speech-to-text (dicek 17 Okt 2026): endpoint transkripsi
# OpenAI-compatible, model whisper-large-v3-turbo dan whisper-large-v3, file wav diterima,
# response_format verbose_json memberi segmen dengan no_speech_prob dan avg_logprob.
GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_STT_MODELS = ("whisper-large-v3-turbo", "whisper-large-v3")


def wav_bytes(pcm16k: np.ndarray) -> bytes:
    """WAV 16 kHz mono int16 di memori (tidak pernah ditulis ke disk, N-08)."""
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(np.asarray(pcm16k, dtype=np.int16).tobytes())
    return buf.getvalue()


def _groq_post(url: str, headers: dict[str, str], data: dict[str, str],
               files: dict[str, Any]) -> dict[str, Any]:  # fmt: skip
    import httpx

    response = httpx.post(url, headers=headers, data=data, files=files)  # timeout bawaan httpx
    response.raise_for_status()
    return response.json()


class GroqWhisperStt:
    """SpeechToText lewat Groq. Audio keluar dari laptop: hanya dipanggil bila E-05/eval stt
    memilih --backend groq di mode dev (penjaga ada di pemanggil). API key tidak pernah dicetak."""

    def __init__(
        self,
        api_key: str,
        model: str,
        no_speech_threshold: float | None = None,
        post: Callable[[str, dict[str, str], dict[str, str], dict[str, Any]], dict[str, Any]]
        = _groq_post,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:  # fmt: skip
        if model not in GROQ_STT_MODELS:
            raise ValueError(f"model Groq STT tidak dikenal: {model}; pilihan {GROQ_STT_MODELS}")
        self._api_key = api_key
        self.model = model
        self.no_speech_threshold = no_speech_threshold
        self.post = post
        self.clock = clock
        self.threads = None
        self.last_segments: list[SegmentStats] = []

    def __repr__(self) -> str:
        return f"GroqWhisperStt(model={self.model!r})"  # tanpa API key

    def transcribe(self, pcm16k: np.ndarray) -> Transcript:
        audio_s = len(pcm16k) / SAMPLE_RATE
        start = self.clock()
        body = self.post(
            GROQ_STT_URL,
            {"Authorization": f"Bearer {self._api_key}"},
            {"model": self.model, "language": LANGUAGE, "response_format": "verbose_json",
             "temperature": "0"},
            {"file": ("ucapan.wav", wav_bytes(pcm16k), "audio/wav")},
        )  # fmt: skip
        stt_s = self.clock() - start
        self.last_segments = [
            SegmentStats(float(s.get("no_speech_prob", 0.0)), float(s.get("avg_logprob", 0.0)))
            for s in body.get("segments") or []
        ]
        if is_no_speech(self.last_segments, self.no_speech_threshold):
            return Transcript("", False, stt_s, audio_s, filtered_by="no_speech")
        text = str(body.get("text", "")).strip()
        return Transcript(text, bool(text), stt_s, audio_s)
