"""M-02: embedding chunk dengan BGE-M3 (ADR-02) lewat sentence-transformers."""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, Protocol

import numpy as np

DEFAULT_CACHE_DIR = Path("models")
WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")
SETUP_HINT = "jalankan: python -m mica setup"
# RF-5 (temuan 39): di mode prod model Hugging Face hanya dimuat dari cache lokal models/
HF_OFFLINE_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}


class ModelNotCached(Exception):
    """Model Hugging Face tidak ada di cache lokal saat mode offline (prod)."""

    def __init__(self, model_id: str, revision: str | None, cache_dir: Path) -> None:
        super().__init__(
            f"model {model_id}@{revision} tidak ada di cache lokal {Path(cache_dir).as_posix()} "
            f"(mode prod tidak mengunduh); {SETUP_HINT}"
        )


def hf_offline(mode: str) -> bool:
    """True bila model Hugging Face wajib dimuat tanpa internet (app.mode prod)."""
    return mode == "prod"


def force_hf_offline(environ: MutableMapping[str, str] | None = None) -> None:
    """Pasang HF_HUB_OFFLINE dan TRANSFORMERS_OFFLINE (proses utama mode prod, sebelum pipeline
    dirakit; diwarisi proses anak). local_files_only di pemuat tetap jaring utama."""
    target = os.environ if environ is None else environ
    target.update(HF_OFFLINE_ENV)


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
        offline: bool = False,
        loader: Any = None,
    ) -> None:
        self.model_id = model_id
        self.pinned_revision = revision  # None = main (hanya untuk dev)
        self.cache_dir = Path(cache_dir)
        self.batch_size = batch_size
        self.offline = offline  # prod: local_files_only, tidak pernah mengunduh (RF-5)
        self._loader = loader  # tes: pengganti kelas SentenceTransformer
        self._model: Any = None

    def _load(self) -> Any:
        # Dimuat saat pertama dipakai; unduhan pertama disimpan di models/ (bukan di prod).
        if self._model is None:
            loader = self._loader
            if loader is None:
                from sentence_transformers import SentenceTransformer

                loader = SentenceTransformer
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            # Revisi terkunci wajib berisi model.safetensors: use_safetensors=True mencegah
            # transformers memuat atau mengunduh pytorch_model.bin sebagai gantinya.
            model_kwargs = {"use_safetensors": True} if self.pinned_revision else {}
            offline: dict[str, Any] = {"local_files_only": True} if self.offline else {}
            try:
                self._model = loader(
                    self.model_id,
                    revision=self.pinned_revision,
                    cache_folder=str(self.cache_dir),
                    device="cpu",
                    model_kwargs=model_kwargs,
                    **offline,
                )
            except OSError as exc:  # huggingface_hub LocalEntryNotFoundError adalah OSError
                if not self.offline:
                    raise
                raise ModelNotCached(self.model_id, self.pinned_revision, self.cache_dir) from exc
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
