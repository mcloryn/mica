"""M-02: membangun dan memuat KB berversi di data/kb/<kb_id>/ (SDD 6.1)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import pickle
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi

from mica.config import KbConfig
from mica.core.types import Chunk, ErrorCode
from mica.kb.chunker import make_chunker
from mica.kb.embedder import Embedder
from mica.kb.parsers import (
    KbBuildError,
    SourceType,
    doc_id_for,
    iter_source_files,
    load_sources,
    source_key,
)

DEFAULT_KB_ROOT = Path("data/kb")
FORMAT_VERSION = 1
KB_FILES = ("manifest.json", "chunks.jsonl", "dense.npy", "bm25.pkl", "build.log")
_KB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_TOKEN = re.compile(r"\w+")

logger = logging.getLogger(__name__)


class KbLoadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(f"{ErrorCode.KB_INVALID}: {message}")
        self.code = ErrorCode.KB_INVALID
        self.message = message


def tokenize(text: str) -> list[str]:
    # Provisional untuk E-01: huruf kecil + \w+, tanpa stemming dan tanpa stopword.
    return _TOKEN.findall(text.lower())


@dataclass(frozen=True)
class KnowledgeBase:
    kb_id: str
    manifest: dict[str, Any]
    chunks: tuple[Chunk, ...]
    dense: np.ndarray
    bm25: BM25Okapi


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def kb_config_hash(kb: KbConfig) -> str:
    """Hash konfigurasi chunker dan embedder (tanpa active_id)."""
    payload = json.dumps(
        kb.model_dump(mode="json", exclude={"active_id"}), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _chunk_to_json(chunk: Chunk) -> str:
    data = dataclasses.asdict(chunk)
    data["valid_from"] = chunk.valid_from.isoformat()
    return json.dumps(data, ensure_ascii=False)


def _chunk_from_json(line: str) -> Chunk:
    data = json.loads(line)
    data["valid_from"] = date.fromisoformat(data["valid_from"])
    return Chunk(**data)


def _check_kb_id(kb_id: str) -> None:
    if not _KB_ID.match(kb_id):
        raise KbBuildError(ErrorCode.KB_INVALID, f"kb_id tidak valid: {kb_id!r}")


def build_kb(
    src: Path,
    kb_id: str,
    source_type: SourceType,
    kb_config: KbConfig,
    embedder: Embedder,
    kb_root: Path = DEFAULT_KB_ROOT,
) -> Path:
    """Bangun KB di folder sementara, lalu rename ke kb_root/kb_id. KB lama tidak pernah ditimpa."""
    src, kb_root = Path(src), Path(kb_root)
    _check_kb_id(kb_id)
    final = kb_root / kb_id
    if final.exists():
        raise KbBuildError(ErrorCode.KB_INVALID, f"KB {kb_id!r} sudah ada; KB tidak boleh ditimpa")

    kb_root.mkdir(parents=True, exist_ok=True)
    tmp = kb_root / f".tmp-{kb_id}-{uuid.uuid4().hex[:8]}"
    tmp.mkdir()
    handler = logging.FileHandler(tmp / "build.log", encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    kb_logger = logging.getLogger("mica.kb")
    previous_level = kb_logger.level
    kb_logger.addHandler(handler)
    if kb_logger.getEffectiveLevel() > logging.INFO:
        kb_logger.setLevel(logging.INFO)
    try:
        logger.info("build %s dari %s (source_type=%s)", kb_id, src, source_type)
        docs = load_sources(src, source_type)  # peringatan KB_PDF_NO_TEXT masuk build.log
        paths = {doc_id_for(src, path): path for path in iter_source_files(src)}
        if not docs:
            raise KbBuildError(ErrorCode.KB_INVALID, f"tidak ada dokumen terbaca di {src}")

        chunker = make_chunker(
            kb_config.chunker,
            kb_config.chunk_tokens,
            kb_config.overlap_tokens,
            embedder.count_tokens,
        )
        chunks = [c for doc in docs for c in chunker.split(doc)]
        if not chunks:
            raise KbBuildError(ErrorCode.KB_INVALID, "tidak ada chunk yang dihasilkan")
        logger.info("%d dokumen, %d chunk", len(docs), len(chunks))

        dense = embedder.embed([c.text for c in chunks])
        if dense.ndim != 2 or dense.shape[0] != len(chunks):
            raise KbBuildError(
                ErrorCode.KB_INVALID, f"bentuk embedding {dense.shape} tidak cocok dengan chunk"
            )
        dense = dense.astype(np.float32, copy=False)
        if not np.allclose(np.linalg.norm(dense, axis=1), 1.0, atol=1e-3):
            raise KbBuildError(ErrorCode.KB_INVALID, "embedding belum dinormalisasi")
        np.save(tmp / "dense.npy", dense)

        with (tmp / "chunks.jsonl").open("w", encoding="utf-8", newline="\n") as f:
            for chunk in chunks:
                f.write(_chunk_to_json(chunk) + "\n")

        with (tmp / "bm25.pkl").open("wb") as f:
            pickle.dump(BM25Okapi([tokenize(c.text) for c in chunks]), f)

        manifest = {
            "format_version": FORMAT_VERSION,
            "kb_id": kb_id,
            "source_type": source_type,
            "built_at": datetime.now().astimezone().isoformat(),
            "config_hash": kb_config_hash(kb_config),
            "chunker": {
                "kind": kb_config.chunker,
                "chunk_tokens": kb_config.chunk_tokens,
                "overlap_tokens": kb_config.overlap_tokens,
            },
            "embedder": {
                "model": embedder.model_id,
                "revision": embedder.revision,
                "weights_file": embedder.weights_file,
                "sentence_transformers": _package_version("sentence-transformers"),
                "torch": _package_version("torch"),
                "dim": int(dense.shape[1]),
            },
            "n_chunks": len(chunks),
            "documents": [
                {
                    "doc_id": doc.doc_id,
                    "title": doc.doc_title,
                    "group": doc.group,
                    "path": source_key(src, paths[doc.doc_id]),
                    "sha256": _sha256(paths[doc.doc_id]),
                    "valid_from": doc.valid_from.isoformat() if doc.valid_from else None,
                }
                for doc in docs
            ],
        }
        (tmp / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("selesai")
    except BaseException:
        _detach(kb_logger, handler, previous_level)
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    # build.log harus ditutup dulu sebelum folder di-rename (Windows mengunci file terbuka)
    _detach(kb_logger, handler, previous_level)
    try:
        tmp.rename(final)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final


def _detach(kb_logger: logging.Logger, handler: logging.Handler, level: int) -> None:
    kb_logger.removeHandler(handler)
    handler.close()
    kb_logger.setLevel(level)


def list_kbs(kb_root: Path = DEFAULT_KB_ROOT) -> list[Path]:
    kb_root = Path(kb_root)
    if not kb_root.exists():
        return []
    return sorted(p for p in kb_root.iterdir() if p.is_dir() and not p.name.startswith("."))


def read_manifest(folder: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KbLoadError(f"{folder}: manifest.json tidak terbaca ({exc})") from exc
    required = ("format_version", "kb_id", "source_type", "config_hash", "embedder", "n_chunks")
    missing = [k for k in required if k not in manifest]
    if missing:
        raise KbLoadError(f"{folder}: manifest.json tanpa field {missing}")
    return manifest


def load_kb(kb_id: str, kb_root: Path = DEFAULT_KB_ROOT) -> KnowledgeBase:
    folder = Path(kb_root) / kb_id
    if not folder.is_dir():
        raise KbLoadError(f"KB {kb_id!r} tidak ditemukan di {kb_root}")
    missing_files = [name for name in KB_FILES if not (folder / name).exists()]
    if missing_files:
        raise KbLoadError(f"{folder}: file hilang {missing_files}")

    manifest = read_manifest(folder)
    if manifest["kb_id"] != kb_id:
        raise KbLoadError(f"{folder}: manifest kb_id {manifest['kb_id']!r} != {kb_id!r}")
    if manifest["format_version"] != FORMAT_VERSION:
        raise KbLoadError(f"{folder}: format_version {manifest['format_version']} tidak didukung")

    try:
        with (folder / "chunks.jsonl").open(encoding="utf-8") as f:
            chunks = tuple(_chunk_from_json(line) for line in f if line.strip())
        dense = np.load(folder / "dense.npy", allow_pickle=False)
        with (folder / "bm25.pkl").open("rb") as f:
            bm25 = pickle.load(f)  # file buatan build_kb sendiri
    except (OSError, ValueError, TypeError, KeyError, pickle.UnpicklingError) as exc:
        raise KbLoadError(f"{folder}: isi KB rusak ({exc})") from exc

    n = manifest["n_chunks"]
    if len(chunks) != n or dense.shape != (n, manifest["embedder"].get("dim")):
        raise KbLoadError(
            f"{folder}: jumlah tidak cocok (manifest {n}, chunk {len(chunks)}, dense {dense.shape})"
        )
    if not isinstance(bm25, BM25Okapi) or bm25.corpus_size != n:
        raise KbLoadError(f"{folder}: indeks BM25 tidak cocok dengan chunk")
    if any(c.source_type != manifest["source_type"] for c in chunks):
        raise KbLoadError(f"{folder}: source_type chunk tidak cocok dengan manifest")
    return KnowledgeBase(kb_id=kb_id, manifest=manifest, chunks=chunks, dense=dense, bm25=bm25)
