"""M-02: embedding chunk dengan BGE-M3 (ADR-02) lewat sentence-transformers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import numpy as np

DEFAULT_CACHE_DIR = Path("models")


class Embedder(Protocol):
    model_id: str

    @property
    def revision(self) -> str: ...

    def embed(self, texts: list[str]) -> np.ndarray:
        """Matriks float32 (len(texts) x dimensi), setiap baris bernorma 1."""
        ...

    def count_tokens(self, text: str) -> int:
        """Jumlah token menurut tokenizer model yang sama, tanpa token khusus."""
        ...


class BgeM3Embedder:
    def __init__(
        self, model_id: str, cache_dir: Path = DEFAULT_CACHE_DIR, batch_size: int = 16
    ) -> None:
        self.model_id = model_id
        self.cache_dir = Path(cache_dir)
        self.batch_size = batch_size
        self._model: Any = None

    def _load(self) -> Any:
        # Dimuat saat pertama dipakai; unduhan pertama disimpan di models/.
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._model = SentenceTransformer(
                self.model_id, cache_folder=str(self.cache_dir), device="cpu"
            )
        return self._model

    @property
    def revision(self) -> str:
        """Commit model di cache Hugging Face (refs/main), untuk manifest KB."""
        ref = self.cache_dir / f"models--{self.model_id.replace('/', '--')}" / "refs" / "main"
        return ref.read_text(encoding="utf-8").strip() if ref.exists() else "unknown"

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = self._load().encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=len(texts) > self.batch_size,
        )
        return np.asarray(vectors, dtype=np.float32)

    def count_tokens(self, text: str) -> int:
        return len(self._load().tokenizer.encode(text, add_special_tokens=False))
