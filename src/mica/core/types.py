"""Tipe data internal SDD 5.1 dan kode error SDD 8.1.

Modul ini hanya boleh mengimpor library standar supaya bisa diimpor modul mana pun tanpa siklus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Literal


class ErrorCode(StrEnum):
    # SDD 8.1
    LLM_FALLBACK = "LLM_FALLBACK"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_BAD_OUTPUT = "LLM_BAD_OUTPUT"
    REFUSED_GATE = "REFUSED_GATE"
    REFUSED_CHECK = "REFUSED_CHECK"
    CAMERA_DOWN = "CAMERA_DOWN"
    MIC_DOWN = "MIC_DOWN"
    STT_EMPTY = "STT_EMPTY"
    COLOR_UNSURE = "COLOR_UNSURE"
    WORKER_RESTART = "WORKER_RESTART"
    WORKER_DEAD = "WORKER_DEAD"
    KB_INVALID = "KB_INVALID"
    # M-02
    KB_PDF_NO_TEXT = "KB_PDF_NO_TEXT"
    KB_MISSING_DATE = "KB_MISSING_DATE"
    # M-01
    CFG_INVALID = "CFG_INVALID"
    CFG_GEMINI_IN_KIOSK = "CFG_GEMINI_IN_KIOSK"
    # M-07
    VISION_MODEL_MISSING = "VISION_MODEL_MISSING"
    VISION_COLORS_MISSING = "VISION_COLORS_MISSING"


class ScrubbedText(str):
    """Penanda teks yang sudah melewati scrub_pii; hanya teks ini yang boleh ke API atau log."""

    __slots__ = ()


@dataclass(frozen=True)
class Chunk:
    chunk_id: str  # "<doc_id>#<urutan>"
    doc_id: str
    doc_title: str
    section: str  # judul bagian, untuk sumber (F-09)
    valid_from: date  # tanggal berlaku (F-16)
    source_type: Literal["official", "dev"]
    text: str
    is_table: bool


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float  # skor akhir dari retriever terpilih
    ranks: dict[str, int]  # peringkat per retriever, untuk analisis E-01
    # skor asli per retriever, misalnya {"bm25": 9.48, "dense": 0.71}; skor RRF hanya berbasis
    # peringkat, jadi gate (M-04) memakai skor asli ini (cosine dense). Kunci "dense@1" berisi
    # cosine dense peringkat 1 untuk kueri itu, sama di semua hasil, walau chunk tersebut tidak
    # masuk top-k hasil fusi.
    raw_scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class GateDecision:
    """Keputusan RelevanceGate (M-04): lolos ke LLM atau ditolak sebelum LLM dipanggil."""

    passed: bool
    score: float | None  # sinyal gerbang (cosine dense peringkat 1); None bila tidak tersedia
    threshold: float | None  # rag.gate.threshold yang dipakai; None = gerbang belum dikalibrasi


@dataclass(frozen=True)
class CheckResult:
    """Hasil FactChecker (M-04): angka di jawaban yang tidak ditemukan di potongan sumber."""

    passed: bool
    unsupported: tuple[str, ...]  # teks asli angka yang tidak didukung sumber
    checked: int  # jumlah angka yang diekstrak dari jawaban


@dataclass(frozen=True)
class Turn:
    question: ScrubbedText  # sudah melewati scrub_pii
    answer: str


@dataclass(frozen=True)
class LlmRequest:
    system: str
    user: str  # pertanyaan + potongan bernomor
    allowed_chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class LlmAnswer:
    status: Literal["answered", "not_found", "false_premise"]
    answer: str
    citations: tuple[str, ...]  # harus subset allowed_chunk_ids
    provider: str
    latency_s: float
    # prompt_tokens, completion_tokens, total_tokens dari respons penyedia; None bila tidak ada
    usage: dict[str, int] | None = None


class LlmUnavailable(Exception):
    """Semua penyedia di rantai gagal (kuota, timeout, jaringan, galat server)."""


class LlmBadOutput(Exception):
    """Keluaran LLM tidak sesuai skema SDD 5.3 setelah satu kali coba ulang."""


@dataclass(frozen=True)
class FinalAnswer:
    status: Literal[
        "answered", "refused_gate", "refused_llm", "false_premise", "refused_check", "unavailable"
    ]
    text: str  # yang ditampilkan dan dibacakan
    sources: tuple[Chunk, ...]  # kosong bila menolak
    timings: dict[str, float]
