import logging
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from kb_samples import FakeEmbedder, make_kb_folder
from rank_bm25 import BM25Okapi

from mica.config import load_settings
from mica.core.types import Chunk, ScoredChunk
from mica.kb.index import KnowledgeBase, build_kb, tokenize
from mica.rag import __main__ as rag_cli
from mica.rag.rerank import RerankedRetriever
from mica.rag.retriever import (
    Bm25Retriever,
    DenseRetriever,
    HybridRrfRetriever,
    embedder_for_kb,
    make_retriever,
    top_indices,
)

DEV_YAML = Path(__file__).resolve().parents[2] / "config" / "dev.yaml"

TEXTS = [
    "Biaya kuliah Sistem Informasi kelas pagi Rp6.500.000 per semester.",
    "Biaya kuliah Teknik Informatika kelas pagi Rp7.000.000 per semester.",
    "Pembayaran uang kuliah dapat dicicil enam kali.",
    "Akreditasi program studi Teknologi Informasi adalah Baik Sekali.",
    "Fasilitas laboratorium komputer dan perpustakaan.",
    "Jadwal pendaftaran gelombang 1 dan gelombang 2.",
]


def _chunk(i: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=f"doc#{i}",
        doc_id="doc",
        doc_title="Dokumen",
        section=f"Bagian {i}",
        valid_from=date(2026, 9, 29),
        source_type="dev",
        text=text,
        is_table=False,
    )


def make_kb(texts=TEXTS, embedder=None) -> KnowledgeBase:
    embedder = embedder or FakeEmbedder()
    chunks = tuple(_chunk(i, t) for i, t in enumerate(texts))
    dense = embedder.embed(list(texts)) if texts else np.zeros((0, 8), dtype=np.float32)
    bm25 = BM25Okapi([tokenize(t) for t in texts]) if texts else None
    manifest = {
        "kb_id": "tes",
        "embedder": {
            "model": embedder.model_id,
            "revision": embedder.revision,
            "weights_file": embedder.weights_file,
            "dim": 8,
        },
    }
    return KnowledgeBase(kb_id="tes", manifest=manifest, chunks=chunks, dense=dense, bm25=bm25)


class FakeCrossEncoder:
    """Skor = jumlah kata kueri yang muncul di teks (deterministik)."""

    def __init__(self):
        self.calls = 0

    def predict(self, pairs, **kwargs):
        self.calls += 1
        return [
            float(len(set(tokenize(q)) & set(tokenize(t)))) for q, t in pairs
        ]


def _bm25(kb):
    return Bm25Retriever(kb)


def _dense(kb):
    return DenseRetriever(kb, FakeEmbedder())


def _hybrid(kb):
    return HybridRrfRetriever(kb.chunks, [_bm25(kb), _dense(kb)], 60, 10)


def _reranked(kb):
    return RerankedRetriever(_hybrid(kb), "fake/reranker", pool=10, loader=FakeCrossEncoder)


IMPLEMENTATIONS = [_bm25, _dense, _hybrid, _reranked]
IDS = ["bm25", "dense", "hybrid", "rerank"]


@pytest.mark.parametrize("factory", IMPLEMENTATIONS, ids=IDS)
@pytest.mark.parametrize("k", [1, 3])
def test_contract_k_sorted_types(factory, k):
    hits = factory(make_kb()).search("biaya kuliah semester informasi", k)
    assert len(hits) == k
    assert all(isinstance(h, ScoredChunk) and isinstance(h.chunk, Chunk) for h in hits)
    assert all(isinstance(h.score, float) for h in hits)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    assert len({h.chunk.chunk_id for h in hits}) == k
    assert all(h.ranks and all(isinstance(r, int) and r >= 1 for r in h.ranks.values())
               for h in hits)


@pytest.mark.parametrize("factory", IMPLEMENTATIONS, ids=IDS)
def test_k_larger_than_kb_returns_all(factory):
    kb = make_kb()
    hits = factory(kb).search("biaya kuliah informasi pembayaran akreditasi fasilitas jadwal", 50)
    assert len(hits) == len(kb.chunks)


@pytest.mark.parametrize("factory", IMPLEMENTATIONS, ids=IDS)
def test_empty_kb(factory):
    assert factory(make_kb(texts=())).search("biaya", 5) == []


@pytest.mark.parametrize("factory", IMPLEMENTATIONS, ids=IDS)
def test_invalid_k(factory):
    with pytest.raises(ValueError):
        factory(make_kb()).search("biaya", 0)


@pytest.mark.parametrize("factory", IMPLEMENTATIONS, ids=IDS)
def test_same_query_same_result(factory):
    retriever = factory(make_kb())
    first = retriever.search("biaya kuliah", 4)
    assert retriever.search("biaya kuliah", 4) == first


def test_bm25_finds_lexical_match_and_skips_zero_score():
    hits = _bm25(make_kb()).search("dicicil", 5)
    assert [h.chunk.chunk_id for h in hits] == ["doc#2"]
    assert hits[0].ranks == {"bm25": 1}
    assert _bm25(make_kb()).search("???", 5) == []  # kueri tanpa token


def test_bm25_keeps_matches_with_negative_score():
    # kata di lebih dari separuh chunk membuat skor BM25Okapi negatif; chunk tetap ditemukan
    kb = make_kb(texts=["kampus mikroskil", "kampus mikroskil", "kampus mikroskil", "lain"])
    assert kb.bm25.get_scores(["kampus"])[0] < 0
    hits = _bm25(kb).search("kampus", 5)
    assert [h.chunk.chunk_id for h in hits] == ["doc#0", "doc#1", "doc#2"]


def test_bm25_uses_build_tokenizer():
    # "Rp6.500.000" ditokenisasi \w+ menjadi rp6, 500, 000 seperti saat build
    hits = _bm25(make_kb()).search("RP6", 1)
    assert hits[0].chunk.chunk_id == "doc#0"


def test_dense_exact_cosine():
    kb = make_kb()
    query = TEXTS[3]  # FakeEmbedder: teks yang sama -> vektor yang sama -> cosine 1
    hits = _dense(kb).search(query, 3)
    assert hits[0].chunk.chunk_id == "doc#3"
    assert hits[0].score == pytest.approx(1.0, abs=1e-5)
    expected = kb.dense @ FakeEmbedder().embed([query])[0]
    assert [h.score for h in hits] == pytest.approx(sorted(expected, reverse=True)[:3], abs=1e-6)
    assert [h.ranks["dense"] for h in hits] == [1, 2, 3]


class StubSource:
    def __init__(self, name, order):
        self.name = name
        self.order = order

    def rank(self, query, n):
        return [(i, 1.0) for i in self.order[:n]]


def test_rrf_matches_manual_calculation():
    chunks = tuple(_chunk(i, f"c{i}") for i in range(5))
    hybrid = HybridRrfRetriever(
        chunks, [StubSource("bm25", [2, 0, 1]), StubSource("dense", [0, 3])], 60, 10
    )
    hits = hybrid.search("x", 5)
    # c0: 1/(60+2) + 1/(60+1); c2: 1/61; c3: 1/62; c1: 1/63; c4 tidak ditemukan
    expected = [
        ("doc#0", 1 / 62 + 1 / 61, {"bm25": 2, "dense": 1}),
        ("doc#2", 1 / 61, {"bm25": 1}),
        ("doc#3", 1 / 62, {"dense": 2}),
        ("doc#1", 1 / 63, {"bm25": 3}),
    ]
    assert [(h.chunk.chunk_id, h.ranks) for h in hits] == [(c, r) for c, _, r in expected]
    assert [h.score for h in hits] == pytest.approx([s for _, s, _ in expected], abs=1e-12)


def test_rrf_uses_candidates_per_retriever():
    chunks = tuple(_chunk(i, f"c{i}") for i in range(5))
    hybrid = HybridRrfRetriever(
        chunks, [StubSource("bm25", [4, 3, 2]), StubSource("dense", [0, 1, 2])], 60, 2
    )
    ids = {h.chunk.chunk_id for h in hybrid.search("x", 5)}
    assert ids == {"doc#4", "doc#3", "doc#0", "doc#1"}  # c2 di luar 2 kandidat teratas


def test_rrf_tie_broken_by_kb_order():
    chunks = tuple(_chunk(i, f"c{i}") for i in range(3))
    hybrid = HybridRrfRetriever(
        chunks, [StubSource("bm25", [2, 1]), StubSource("dense", [1, 2])], 60, 10
    )
    # c1 dan c2 sama-sama 1/61 + 1/62: c1 lebih dulu karena urutannya di KB lebih awal
    assert [h.chunk.chunk_id for h in hybrid.search("x", 2)] == ["doc#1", "doc#2"]


@pytest.mark.parametrize("factory", [_bm25, _dense], ids=["bm25", "dense"])
def test_equal_scores_follow_kb_order(factory):
    kb = make_kb(texts=["kampus mikroskil", "lain", "kampus mikroskil", "kampus mikroskil"])
    hits = factory(kb).search("kampus mikroskil", 3)
    assert [h.chunk.chunk_id for h in hits] == ["doc#0", "doc#2", "doc#3"]


def test_top_indices_tie_order():
    assert top_indices(np.array([0.5, 0.9, 0.5, 0.9]), 4) == [1, 3, 0, 2]


def test_reranker_reorders_and_keeps_base_ranks():
    kb = make_kb()
    encoder = FakeCrossEncoder()
    reranked = RerankedRetriever(_hybrid(kb), "fake/reranker", pool=6, loader=lambda: encoder)
    hits = reranked.search("akreditasi program studi teknologi informasi", 2)
    assert hits[0].chunk.chunk_id == "doc#3"
    assert hits[0].ranks["rerank"] == 1
    assert set(hits[0].ranks) >= {"rerank"} and len(hits[0].ranks) >= 2
    assert encoder.calls == 1


def test_reranker_loads_lazily():
    loaded = []

    def loader():
        loaded.append(True)
        return FakeCrossEncoder()

    reranked = RerankedRetriever(_hybrid(make_kb()), "fake/reranker", loader=loader)
    assert loaded == []
    reranked.search("biaya", 1)
    assert loaded == [True]


def _settings(**rag_updates):
    settings = load_settings(DEV_YAML)
    rag = settings.rag.model_copy(update=rag_updates)
    return settings.model_copy(update={"rag": rag})


def _factory_from_manifest(calls):
    def factory(model_id, revision):
        calls.append((model_id, revision))
        return FakeEmbedder()

    return factory


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("bm25", Bm25Retriever), ("dense", DenseRetriever), ("hybrid", HybridRrfRetriever)],
)
def test_make_retriever_selects_by_config(kind, expected):
    calls = []
    retriever = make_retriever(_settings(retriever=kind), make_kb(), _factory_from_manifest(calls))
    assert isinstance(retriever.inner, expected)
    if kind != "bm25":
        # model dan revisi dari manifest KB, bukan dari config
        assert calls == [("fake/embedder", "0" * 40)]


def test_make_retriever_hybrid_requires_params():
    with pytest.raises(ValueError):
        make_retriever(_settings(rrf_k=None), make_kb(), _factory_from_manifest([]))
    with pytest.raises(ValueError):
        make_retriever(_settings(candidates_per_retriever=None), make_kb(),
                       _factory_from_manifest([]))


def test_make_retriever_wraps_reranker_when_enabled():
    settings = load_settings(DEV_YAML)
    reranker = settings.rag.reranker.model_copy(update={"enabled": True})
    settings = _settings(reranker=reranker)
    retriever = make_retriever(
        settings, make_kb(), _factory_from_manifest([]), cross_encoder_loader=FakeCrossEncoder
    )
    assert isinstance(retriever.inner, RerankedRetriever)
    assert retriever.inner.model_id == "BAAI/bge-reranker-v2-m3"
    assert len(retriever.search("biaya kuliah", 3)) == 3


def test_make_retriever_logs_latency_without_query(caplog):
    retriever = make_retriever(_settings(retriever="bm25"), make_kb(), None)
    with caplog.at_level(logging.INFO, logger="mica.rag.retriever"):
        retriever.search("rahasia dicicil", 2)
    assert "latency_ms=" in caplog.text
    assert "rahasia" not in caplog.text


def test_embedder_for_kb_rejects_non_safetensors_kb():
    kb = make_kb()
    kb.manifest["embedder"]["weights_file"] = "pytorch_model.bin"
    with pytest.raises(ValueError):
        embedder_for_kb(kb)


def test_cli_search_with_built_kb(tmp_path, capsys):
    src = make_kb_folder(tmp_path / "src")
    kb_root = tmp_path / "kb"
    settings = load_settings(DEV_YAML)
    build_kb(src, settings.kb.active_id, "dev", settings.kb, FakeEmbedder(), kb_root)
    for kind in ("bm25", "dense", "hybrid"):
        code = rag_cli.main(
            ["--kb-root", str(kb_root), "search", "biaya pendaftaran", "--config", str(DEV_YAML),
             "--retriever", kind, "--k", "3"],
            embedder_factory=lambda m, r: FakeEmbedder(),
        )
        out = capsys.readouterr().out
        assert code == 0
        assert f"retriever {kind}" in out and "lama pencarian:" in out and "1. skor" in out
