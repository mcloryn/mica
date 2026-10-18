"""Pesan bus M-13 untuk proses suara M-08 (SDD 5.2). Hanya library standar dan teks/angka kecil;
audio tidak pernah lewat bus (N-08).

Nama SpeechStarted dan Transcript sama dengan SDD 5.2. Tipe internal yang bernama sama di
audio/vad.py (event segmenter) dan audio/stt.py (hasil SpeechToText) tidak membawa session_id;
worker mengubahnya menjadi pesan di sini.

Penyimpangan dari SDD 5.2 (field tambahan): SpeechStarted.t, Transcript.cut_by_max,
Transcript.filtered_by, Transcript.vad_s, Transcript.ended_t, SpeechDone.interrupted,
SpeechDone.first_audio_t, AudioStatus.ready, AudioStatus.message. Waktu *_t memakai
time.monotonic proses suara; jam ini sama untuk semua proses di satu mesin (E-09, docs/E-09.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# hold (Langkah 42, audio.input_mode push_to_talk): rekam selama tombol Bicara ditahan;
# ReleaseTalk = tombol dilepas (kirim); ListenControl lain selama hold = dibatalkan
ListenMode = Literal["auto", "push_to_talk", "hold", "off"]
# no_voice (Langkah 42): rekaman tahan-tombol tanpa ucapan menurut VAD, STT tidak dipanggil
FilteredBy = Literal["min_speech", "no_speech", "no_voice"]


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
    # mode vad: diam di ujung ucapan sampai VAD menyatakan selesai (timings.vad); push-to-talk:
    # tombol dilepas sampai cek VAD selesai (amandemen 2 E-09)
    vad_s: float | None = None
    # monotonic saat VAD menyatakan ucapan selesai / cek VAD selesai; ended_t - vad_s = akhir
    # ucapan (vad) atau saat tombol dilepas (push-to-talk)
    ended_t: float | None = None


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
    first_audio_t: float | None = None  # monotonic saat clip pertama mulai diputar; None = tidak


@dataclass(frozen=True)
class ListenControl:
    mode: ListenMode
    session_id: str | None


@dataclass(frozen=True)
class ReleaseTalk:
    """Tombol Bicara dilepas (push-to-talk): rekaman hold dikirim ke cek VAD lalu STT."""

    session_id: str | None


@dataclass(frozen=True)
class AudioStatus:
    mic_ok: bool
    speaker_ok: bool
    ready: bool
    message: str


AudioMessage = (
    SpeechStarted
    | Transcript
    | Speak
    | StopSpeaking
    | SpeechDone
    | ListenControl
    | ReleaseTalk
    | AudioStatus
)
