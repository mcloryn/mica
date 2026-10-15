"""M-02: embedding chunk dengan BGE-M3 (ADR-02) lewat sentence-transformers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import numpy as np

DEFAULT_CACHE_DIR = Path("models")
WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")


class Embedder(Protocol):
    model_id: str

    @property
    def revision(self) -> str:
        """Hash commit model yang dipakai."""
        ...

    @property
    def weights_file(self) -> str:
        """Nama file bobot yang dimuat."""
        ...

    def embed(self, texts: list[str]) -> np.ndarray:
        """Matriks float32 (len(texts) x dimensi), setiap baris bernorma 1."""
        ...

    def count_tokens(self, text: str) -> int:
        """Jumlah token menurut tokenizer model yang sama, tanpa token khusus."""
        ...


class BgeM3Embedder:
    def __init__(
        self,
        model_id: str,
        revision: str | None = None,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        batch_size: int = 16,
    ) -> None:
        self.model_id = model_id
        self.pinned_revision = revision  # None = main (hanya untuk dev)
        self.cache_dir = Path(cache_dir)
        self.batch_size = batch_size
        self._model: Any = None

    def _load(self) -> Any:
        # Dimuat saat pertama dipakai; unduhan pertama disimpan di models/.
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            # Revisi terkunci wajib berisi model.safetensors: use_safetensors=True mencegah
            # transformers memuat atau mengunduh pytorch_model.bin sebagai gantinya.
            model_kwargs = {"use_safetensors": True} if self.pinned_revision else {}
            self._model = SentenceTransformer(
                self.model_id,
                revision=self.pinned_revision,
                cache_folder=str(self.cache_dir),
                device="cpu",
                model_kwargs=model_kwargs,
            )
        return self._model

    def load(self) -> None:
        """Muat model sekarang (misalnya sebelum mengukur latensi pencarian)."""
        self._load()

    def _repo_cache(self) -> Path:
        return self.cache_dir / f"models--{self.model_id.replace('/', '--')}"

    @property
    def revision(self) -> str:
        if self.pinned_revision:
            return self.pinned_revision
        ref = self._repo_cache() / "refs" / "main"
        return ref.read_text(encoding="utf-8").strip() if ref.exists() else "unknown"

    @property
    def weights_file(self) -> str:
        """File bobot di snapshot revisi yang dipakai; transformers mengutamakan safetensors."""
        snapshot = self._repo_cache() / "snapshots" / self.revision
        for name in WEIGHT_FILES:
            if (snapshot / name).exists():
                return name
        return "unknown"

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
