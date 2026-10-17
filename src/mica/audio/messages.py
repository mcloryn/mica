"""Pesan bus M-13 untuk proses suara M-08 (SDD 5.2). Hanya library standar dan teks/angka kecil;
audio tidak pernah lewat bus (N-08).

Nama SpeechStarted dan Transcript sama dengan SDD 5.2. Tipe internal yang bernama sama di
audio/vad.py (event segmenter) dan audio/stt.py (hasil SpeechToText) tidak membawa session_id;
worker mengubahnya menjadi pesan di sini.

Penyimpangan dari SDD 5.2 (field tambahan): SpeechStarted.t, Transcript.cut_by_max,
Transcript.filtered_by, SpeechDone.interrupted, AudioStatus.ready, AudioStatus.message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ListenMode = Literal["auto", "push_to_talk", "off"]
FilteredBy = Literal["min_speech", "no_speech"]


@dataclass(frozen=True)
class SpeechStarted:
    session_id: str | None
    t: float  # waktu monotonic di proses suara


@dataclass(frozen=True)
class Transcript:
    session_id: str | None
    text: str  # kosong bila ok=False; tidak boleh ditulis ke log (N-09)
    ok: bool
    stt_s: float
    audio_s: float
    cut_by_max: bool = False
    filtered_by: FilteredBy | None = None  # None = tidak tersaring


@dataclass(frozen=True)
class Speak:
    session_id: str | None
    text: str
    utterance_id: str


@dataclass(frozen=True)
class StopSpeaking:
    session_id: str | None


@dataclass(frozen=True)
class SpeechDone:
    session_id: str | None
    utterance_id: str
    tts_first_audio_s: float | None  # Speak diterima -> clip pertama mulai diputar; None = tidak
    interrupted: bool = False


@dataclass(frozen=True)
class ListenControl:
    mode: ListenMode
    session_id: str | None


@dataclass(frozen=True)
class AudioStatus:
    mic_ok: bool
    speaker_ok: bool
    ready: bool
    message: str


AudioMessage = (
    SpeechStarted | Transcript | Speak | StopSpeaking | SpeechDone | ListenControl | AudioStatus
)
