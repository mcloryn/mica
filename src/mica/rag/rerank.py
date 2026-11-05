"""M-03: reranker cross-encoder (bge-reranker-v2-m3) yang membungkus retriever lain.

Dipakai hanya bila rag.reranker.enabled = true (ADR-01 Provisional; V2-3 P1,
docs/PRA-REGISTRASI-V2.md). `Reranker` adalah Protocol penilai ulang kandidat;
`CrossEncoderReranker` implementasi cross-encoder; `RerankedRetriever` mengambil `pool`
kandidat dari retriever dasar lalu memakai Reranker untuk memilih k teratas.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from mica.core.types import ScoredChunk
from mica.kb.embedder import DEFAULT_CACHE_DIR, ModelNotCached


class CrossEncoderLike(Protocol):
    def predict(self, sentences: Sequence[tuple[str, str]], **kwargs: Any) -> Any: ...


class Reranker(Protocol):
    """Menilai ulang kandidat untuk query dan mengembalikan k teratas (skor = skor reranker)."""

    def rerank(self, query: str, hits: Sequence[ScoredChunk], k: int) -> list[ScoredChunk]: ...


class CrossEncoderReranker:
    """Cross-encoder sentence-transformers; prod: hanya dari cache lokal models/ (RF-5)."""

    def __init__(
        self,
        model_id: str,
        revision: str | None = None,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        loader: Callable[[], CrossEncoderLike] | None = None,
        offline: bool = False,
        cross_encoder: Callable[..., CrossEncoderLike] | None = None,
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.cache_dir = Path(cache_dir)
        self._loader = loader
        self.offline = offline  # prod: local_files_only, tidak pernah mengunduh (RF-5)
        self._cross_encoder = cross_encoder  # tes: pengganti kelas CrossEncoder
        self._model: CrossEncoderLike | None = None

    def load(self) -> CrossEncoderLike:
        # Dimuat saat pertama dipakai; revisi terkunci wajib berisi model.safetensors.
        if self._model is None:
            if self._loader is not None:
                self._model = self._loader()
            else:
                cross_encoder = self._cross_encoder
                if cross_encoder is None:
                    from sentence_transformers import CrossEncoder

                    cross_encoder = CrossEncoder
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                offline: dict[str, Any] = {"local_files_only": True} if self.offline else {}
                try:
                    self._model = cross_encoder(
                        self.model_id,
                        revision=self.revision,
                        cache_folder=str(self.cache_dir),
                        device="cpu",
                        model_kwargs={"use_safetensors": True} if self.revision else {},
                        **offline,
                    )
                except OSError as exc:  # huggingface_hub LocalEntryNotFoundError adalah OSError
                    if not self.offline:
                        raise
                    raise ModelNotCached(self.model_id, self.revision, self.cache_dir) from exc
        return self._model

    def rerank(self, query: str, hits: Sequence[ScoredChunk], k: int) -> list[ScoredChunk]:
        if k < 1:
            raise ValueError("k harus >= 1")
        if not hits:
            return []
        scores = self.load().predict([(query, h.chunk.text) for h in hits])
        # skor sama: pertahankan urutan retriever dasar
        order = sorted(range(len(hits)), key=lambda i: (-float(scores[i]), i))[:k]
        return [
            ScoredChunk(
                chunk=hits[i].chunk,
                score=float(scores[i]),
                ranks={**hits[i].ranks, "rerank": pos},
                raw_scores={**hits[i].raw_scores, "rerank": float(scores[i])},
            )
            for pos, i in enumerate(order, start=1)
        ]


class RerankedRetriever:
    def __init__(
        self,
        base: Any,
        model_id: str,
        revision: str | None = None,
        pool: int = 20,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        loader: Callable[[], CrossEncoderLike] | None = None,
        offline: bool = False,
        cross_encoder: Callable[..., CrossEncoderLike] | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        if pool < 1:
            raise ValueError("pool harus >= 1")
        self.base = base
        self.pool = pool  # jumlah kandidat dari retriever dasar yang dinilai ulang
        self.model_id = model_id
        self.revision = revision
        self.offline = offline
        self.reranker: Reranker = reranker or CrossEncoderReranker(
            model_id, revision, cache_dir, loader, offline, cross_encoder
        )

    def _load(self) -> CrossEncoderLike:
        load = getattr(self.reranker, "load", None)
        if load is None:
            raise TypeError("reranker ini tidak memuat model cross-encoder")
        return load()

    def search(self, query: str, k: int) -> list[ScoredChunk]:
        if k < 1:
            raise ValueError("k harus >= 1")
        hits = self.base.search(query, max(k, self.pool))
        return self.reranker.rerank(query, hits, k)
