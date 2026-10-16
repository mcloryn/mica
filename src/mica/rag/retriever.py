"""M-03: retriever BM25, dense, dan hybrid RRF atas satu KB (ADR-01, Provisional).

Semua implementasi hanya-baca setelah dibuat, sehingga aman dipakai dari thread mana pun.
Bila skor sama, hasil diurutkan menurut urutan chunk di KB supaya deterministik.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Callable, Sequence
from typing import Protocol

import numpy as np

from mica.config import Settings
from mica.core.types import Chunk, ScoredChunk
from mica.kb.embedder import DEFAULT_CACHE_DIR, BgeM3Embedder, Embedder
from mica.kb.index import KnowledgeBase, tokenize

logger = logging.getLogger(__name__)

# (indeks chunk di KB, skor), terurut dari yang terbaik
Ranked = list[tuple[int, float]]
# kunci raw_scores untuk cosine dense peringkat 1 (sinyal gerbang M-04)
DENSE_TOP1 = "dense@1"
EmbedderFactory = Callable[[str, str | None], Embedder]  # (model_id, revision)


class Retriever(Protocol):
    def search(self, query: str, k: int) -> list[ScoredChunk]: ...


class RankedSource(Protocol):
    """Retriever dasar yang bisa mengembalikan peringkat indeks chunk (dipakai hybrid RRF)."""

    name: str

    def rank(self, query: str, n: int) -> Ranked: ...


def _check_k(k: int) -> None:
    if k < 1:
        raise ValueError("k harus >= 1")


def top_indices(scores: np.ndarray, n: int) -> list[int]:
    """n indeks dengan skor tertinggi; skor sama diurutkan menurut indeks (urutan KB)."""
    order = np.lexsort((np.arange(len(scores)), -scores))
    return [int(i) for i in order[:n]]


class _SingleRetriever:
    name = ""

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self.chunks = tuple(chunks)

    def rank(self, query: str, n: int) -> Ranked:
        raise NotImplementedError

    def search(self, query: str, k: int) -> list[ScoredChunk]:
        _check_k(k)
        return [
            ScoredChunk(
                chunk=self.chunks[i],
                score=score,
                ranks={self.name: pos},
                raw_scores={self.name: score},
            )
            for pos, (i, score) in enumerate(self.rank(query, k), start=1)
        ]


class Bm25Retriever(_SingleRetriever):
    name = "bm25"

    def __init__(self, kb: KnowledgeBase) -> None:
        super().__init__(kb.chunks)
        self.bm25 = kb.bm25

    def rank(self, query: str, n: int) -> Ranked:
        tokens = tokenize(query)  # tokenisasi yang sama dengan saat build (kb/index.py)
        if not self.chunks or not tokens:
            return []
        scores = np.asarray(self.bm25.get_scores(tokens), dtype=np.float64)
        # Chunk tanpa satu pun kata kueri tidak dianggap ditemukan BM25. Dicek lewat isi chunk,
        # bukan skor > 0, karena BM25Okapi bisa memberi skor negatif untuk kata yang sangat umum.
        query_tokens = set(tokens)
        matched = np.array(
            [not query_tokens.isdisjoint(freqs) for freqs in self.bm25.doc_freqs], dtype=bool
        )
        scores = np.where(matched, scores, -np.inf)
        return [(i, float(scores[i])) for i in top_indices(scores, n) if matched[i]]


class DenseRetriever(_SingleRetriever):
    name = "dense"

    def search(self, query: str, k: int) -> list[ScoredChunk]:
        hits = super().search(query, k)
        if not hits:
            return hits
        top1 = hits[0].score
        return [
            dataclasses.replace(h, raw_scores={**h.raw_scores, DENSE_TOP1: top1}) for h in hits
        ]

    def __init__(self, kb: KnowledgeBase, embedder: Embedder) -> None:
        super().__init__(kb.chunks)
        self.dense = kb.dense
        self.embedder = embedder

    def rank(self, query: str, n: int) -> Ranked:
        if not self.chunks:
            return []
        q = self.embedder.embed([query])[0]
        if q.shape[0] != self.dense.shape[1]:
            raise ValueError(f"dimensi kueri {q.shape[0]} != dimensi KB {self.dense.shape[1]}")
        # cosine exact: vektor KB dan kueri sudah dinormalisasi, jadi cukup dot product
        scores = (self.dense @ q).astype(np.float64)
        return [(i, float(scores[i])) for i in top_indices(scores, n)]


class HybridRrfRetriever:
    name = "hybrid"

    def __init__(
        self,
        chunks: Sequence[Chunk],
        sources: Sequence[RankedSource],
        rrf_k: int,
        candidates_per_retriever: int,
    ) -> None:
        if rrf_k < 1 or candidates_per_retriever < 1:
            raise ValueError("rrf_k dan candidates_per_retriever harus >= 1")
        self.chunks = tuple(chunks)
        self.sources = tuple(sources)
        self.rrf_k = rrf_k
        self.candidates = candidates_per_retriever

    def search(self, query: str, k: int) -> list[ScoredChunk]:
        _check_k(k)
        if not self.chunks:
            return []
        # SDD 7.3: score[c] = sum(1 / (rrf_k + rank_r(c))) atas retriever yang memuat c
        scores: dict[int, float] = {}
        ranks: dict[int, dict[str, int]] = {}
        raw: dict[int, dict[str, float]] = {}
        extra: dict[str, float] = {}
        for source in self.sources:
            ranked = source.rank(query, self.candidates)
            if source.name == DenseRetriever.name and ranked:
                # dense peringkat 1 dibawa terpisah: chunk itu bisa saja kalah di fusi RRF
                extra[DENSE_TOP1] = ranked[0][1]
            for rank, (i, raw_score) in enumerate(ranked, start=1):
                scores[i] = scores.get(i, 0.0) + 1.0 / (self.rrf_k + rank)
                ranks.setdefault(i, {})[source.name] = rank
                raw.setdefault(i, {})[source.name] = raw_score
        order = sorted(scores, key=lambda i: (-scores[i], i))[:k]
        return [
            ScoredChunk(
                chunk=self.chunks[i], score=scores[i], ranks=ranks[i], raw_scores={**raw[i], **extra}
            )
            for i in order
        ]


class _LoggedRetriever:
    """Mencatat latensi search ke log (M-03); teks kueri tidak dicatat."""

    def __init__(self, inner: Retriever, name: str) -> None:
        self.inner = inner
        self.name = name

    def search(self, query: str, k: int) -> list[ScoredChunk]:
        started = time.perf_counter()
        hits = self.inner.search(query, k)
        logger.info(
            "retriever=%s k=%d hasil=%d latency_ms=%.1f",
            self.name, k, len(hits), (time.perf_counter() - started) * 1000,
        )
        return hits


def embedder_for_kb(kb: KnowledgeBase, factory: EmbedderFactory | None = None) -> Embedder:
    """Embedder kueri harus sama dengan saat build: model dan revisi dari manifest, bukan config."""
    info = kb.manifest["embedder"]
    if factory is not None:
        return factory(info["model"], info["revision"])
    if info.get("weights_file") != "model.safetensors":
        raise ValueError(
            f"KB {kb.kb_id} dibangun dengan bobot {info.get('weights_file')!r}; "
            "bangun ulang dengan kb.embedder.revision yang berisi model.safetensors"
        )
    return BgeM3Embedder(info["model"], revision=info["revision"], cache_dir=DEFAULT_CACHE_DIR)


def make_retriever(
    settings: Settings,
    kb: KnowledgeBase,
    embedder_factory: EmbedderFactory | None = None,
    cross_encoder_loader: Callable[[], object] | None = None,
) -> Retriever:
    """Pilih retriever lewat rag.retriever; dibungkus reranker bila rag.reranker.enabled."""
    rag = settings.rag
    kind = rag.retriever
    if kind == "hybrid" and (rag.rrf_k is None or rag.candidates_per_retriever is None):
        raise ValueError("rag.rrf_k dan rag.candidates_per_retriever wajib diisi untuk hybrid")

    def dense() -> DenseRetriever:
        return DenseRetriever(kb, embedder_for_kb(kb, embedder_factory))

    retriever: Retriever
    if kind == "bm25":
        retriever = Bm25Retriever(kb)
    elif kind == "dense":
        retriever = dense()
    else:
        retriever = HybridRrfRetriever(
            kb.chunks,
            [Bm25Retriever(kb), dense()],
            rrf_k=rag.rrf_k,  # type: ignore[arg-type]  # sudah dicek di atas
            candidates_per_retriever=rag.candidates_per_retriever,  # type: ignore[arg-type]
        )

    name = kind
    if rag.reranker.enabled:
        from mica.rag.rerank import RerankedRetriever

        retriever = RerankedRetriever(
            retriever,
            model_id=rag.reranker.model,
            revision=rag.reranker.revision,
            pool=rag.candidates_per_retriever or rag.top_k,
            loader=cross_encoder_loader,
        )
        name = f"{kind}+rerank"
    return _LoggedRetriever(retriever, name)
