import json
import logging
import sys
import types
from importlib import metadata

import numpy as np
import pytest
from kb_samples import FakeEmbedder, make_kb_folder, write_blank_pdf

from mica.config import EmbedderConfig, KbConfig
from mica.core.types import ErrorCode
from mica.kb.embedder import BgeM3Embedder
from mica.kb.index import (
    KB_FILES,
    KbLoadError,
    build_kb,
    list_kbs,
    load_kb,
    tokenize,
)
from mica.kb.parsers import KbBuildError


def _kb_config(chunk_tokens: int | None = 8, overlap_tokens: int | None = 2) -> KbConfig:
    return KbConfig(
        active_id="dev-2026-10-15",
        chunker="structure_then_fixed",
        chunk_tokens=chunk_tokens,
        overlap_tokens=overlap_tokens,
        embedder=EmbedderConfig(model="fake/embedder"),
    )


@pytest.fixture
def src(tmp_path):
    return make_kb_folder(tmp_path / "src")


@pytest.fixture
def kb_root(tmp_path):
    return tmp_path / "kb"


def _build(src, kb_root, kb_id="dev-2026-10-15", **kwargs):
    embedder = kwargs.pop("embedder", FakeEmbedder())
    return build_kb(src, kb_id, "dev", kwargs.pop("kb_config", _kb_config()), embedder, kb_root)


def test_build_writes_all_files(src, kb_root):
    folder = _build(src, kb_root)
    assert folder == kb_root / "dev-2026-10-15"
    for name in KB_FILES:
        assert (folder / name).is_file(), name
    assert sorted(p.name for p in kb_root.iterdir()) == ["dev-2026-10-15"]  # tanpa sisa folder tmp


def test_chunks_match_dense_rows(src, kb_root):
    folder = _build(src, kb_root)
    lines = (folder / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    dense = np.load(folder / "dense.npy")
    assert len(lines) == dense.shape[0] > 0
    assert dense.dtype == np.float32
    assert np.allclose(np.linalg.norm(dense, axis=1), 1.0, atol=1e-5)


def test_manifest_content(src, kb_root):
    manifest = json.loads((_build(src, kb_root) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kb_id"] == "dev-2026-10-15"
    assert manifest["source_type"] == "dev"
    embedder = manifest["embedder"]
    assert embedder["model"] == "fake/embedder"
    assert embedder["revision"] == "0" * 40
    assert embedder["weights_file"] == "fake.safetensors"
    assert embedder["dim"] == 8
    assert embedder["sentence_transformers"] == metadata.version("sentence-transformers")
    import torch

    assert embedder["torch"] == str(torch.__version__)
    assert embedder["torch"].startswith(metadata.version("torch"))
    assert manifest["chunker"]["chunk_tokens"] == 8
    assert len(manifest["config_hash"]) == 64
    docs = {d["doc_id"]: d for d in manifest["documents"]}
    assert set(docs) == {"brosur", "biaya", "panduan", "jalur"}
    assert docs["biaya"]["path"] == "biaya.md"
    assert docs["biaya"]["valid_from"] == "2026-08-01"
    assert len(docs["biaya"]["sha256"]) == 64


def test_pdf_without_text_logged_in_build_log(src, kb_root):
    write_blank_pdf(src / "pindaian.pdf")
    folder = _build(src, kb_root)
    log = (folder / "build.log").read_text(encoding="utf-8")
    assert ErrorCode.KB_PDF_NO_TEXT in log and "pindaian.pdf" in log


def test_build_log_handler_detached(src, kb_root):
    _build(src, kb_root)
    assert not any(
        isinstance(h, logging.FileHandler) for h in logging.getLogger("mica.kb").handlers
    )


def test_failed_embedding_leaves_no_folder(src, kb_root):
    with pytest.raises(RuntimeError):
        _build(src, kb_root, embedder=FakeEmbedder(fail_on_call=True))
    assert list(kb_root.iterdir()) == []


def test_missing_date_leaves_no_folder(src, kb_root):
    (src / "baru.txt").write_text("Dokumen tanpa tanggal.", encoding="utf-8")
    with pytest.raises(KbBuildError) as exc:
        _build(src, kb_root)
    assert exc.value.code == ErrorCode.KB_MISSING_DATE
    assert list(kb_root.iterdir()) == []


def test_null_chunk_size_leaves_no_folder(src, kb_root):
    with pytest.raises(ValueError):
        _build(src, kb_root, kb_config=_kb_config(None, None))
    assert list(kb_root.iterdir()) == []


def test_duplicate_kb_id_rejected(src, kb_root):
    folder = _build(src, kb_root)
    before = (folder / "manifest.json").read_bytes()
    embedder = FakeEmbedder()
    with pytest.raises(KbBuildError) as exc:
        _build(src, kb_root, embedder=embedder)
    assert exc.value.code == ErrorCode.KB_INVALID
    assert embedder.calls == 0
    assert (folder / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("kb_id", ["", "../luar", "a/b", "official-<YYYY-MM-DD>"])
def test_invalid_kb_id_rejected(src, kb_root, kb_id):
    with pytest.raises(KbBuildError):
        _build(src, kb_root, kb_id=kb_id)


def test_load_kb_reads_same_chunks(src, kb_root):
    folder = _build(src, kb_root)
    kb = load_kb("dev-2026-10-15", kb_root)
    lines = (folder / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(kb.chunks) == len(lines) == kb.dense.shape[0]
    assert kb.chunks[0].chunk_id == json.loads(lines[0])["chunk_id"]
    # embedding yang dimuat sama dengan hasil embed ulang teks chunk
    again = FakeEmbedder().embed([c.text for c in kb.chunks])
    assert np.allclose(kb.dense, again)
    assert kb.bm25.corpus_size == len(kb.chunks)
    assert any(c.is_table for c in kb.chunks)
    assert all(c.valid_from.isoformat() for c in kb.chunks)


def test_load_kb_missing_rejected(kb_root):
    with pytest.raises(KbLoadError) as exc:
        load_kb("tidak-ada", kb_root)
    assert exc.value.code == ErrorCode.KB_INVALID


@pytest.mark.parametrize(
    "damage",
    [
        lambda f: (f / "manifest.json").write_text("{rusak", encoding="utf-8"),
        lambda f: (f / "dense.npy").unlink(),
        lambda f: np.save(f / "dense.npy", np.zeros((1, 8), dtype=np.float32)),
        lambda f: (f / "chunks.jsonl").write_text("", encoding="utf-8"),
    ],
    ids=["manifest", "dense-hilang", "dense-beda", "chunks-kosong"],
)
def test_load_kb_damaged_rejected(src, kb_root, damage):
    damage(_build(src, kb_root))
    with pytest.raises(KbLoadError) as exc:
        load_kb("dev-2026-10-15", kb_root)
    assert exc.value.code == ErrorCode.KB_INVALID


def test_list_kbs_ignores_tmp(src, kb_root):
    _build(src, kb_root)
    (kb_root / ".tmp-x").mkdir()
    assert [p.name for p in list_kbs(kb_root)] == ["dev-2026-10-15"]


def test_tokenize():
    assert tokenize("Biaya UKT Rp7.000.000, per-semester!") == [
        "biaya",
        "ukt",
        "rp7",
        "000",
        "000",
        "per",
        "semester",
    ]


def test_bge_embedder_loads_lazily(tmp_path, monkeypatch):
    # Bila model dimuat saat dibuat, impor ini akan gagal.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    embedder = BgeM3Embedder("BAAI/bge-m3", cache_dir=tmp_path / "models")
    assert embedder.revision == "unknown"
    with pytest.raises(ImportError):
        embedder.embed(["x"])


REV = "9a0624b896d81da7492a910ffa53731274b6cf3d"


def _fake_sentence_transformers(monkeypatch):
    calls = []

    class FakeST:
        def __init__(self, model_id, **kwargs):
            calls.append((model_id, kwargs))

    monkeypatch.setitem(
        sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeST)
    )
    return calls


def test_bge_embedder_passes_pinned_revision(tmp_path, monkeypatch):
    calls = _fake_sentence_transformers(monkeypatch)
    embedder = BgeM3Embedder("BAAI/bge-m3", revision=REV, cache_dir=tmp_path)
    embedder._load()
    model_id, kwargs = calls[0]
    assert model_id == "BAAI/bge-m3"
    assert kwargs["revision"] == REV
    assert kwargs["model_kwargs"] == {"use_safetensors": True}
    assert kwargs["cache_folder"] == str(tmp_path)
    assert embedder.revision == REV


def test_bge_embedder_unpinned_uses_main(tmp_path, monkeypatch):
    calls = _fake_sentence_transformers(monkeypatch)
    BgeM3Embedder("BAAI/bge-m3", cache_dir=tmp_path)._load()
    assert calls[0][1]["revision"] is None


def test_bge_embedder_weights_file_from_snapshot(tmp_path):
    snapshot = tmp_path / "models--BAAI--bge-m3" / "snapshots" / REV
    snapshot.mkdir(parents=True)
    embedder = BgeM3Embedder("BAAI/bge-m3", revision=REV, cache_dir=tmp_path)
    assert embedder.weights_file == "unknown"
    (snapshot / "pytorch_model.bin").write_bytes(b"")
    assert embedder.weights_file == "pytorch_model.bin"
    (snapshot / "model.safetensors").write_bytes(b"")
    assert embedder.weights_file == "model.safetensors"  # safetensors diutamakan


def test_bge_embedder_revision_from_cache(tmp_path):
    ref = tmp_path / "models--BAAI--bge-m3" / "refs" / "main"
    ref.parent.mkdir(parents=True)
    ref.write_text("abc123\n", encoding="utf-8")
    assert BgeM3Embedder("BAAI/bge-m3", cache_dir=tmp_path).revision == "abc123"
