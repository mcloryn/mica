from datetime import date
from pathlib import Path

import pytest
import yaml

from mica.config import CFG_INVALID, ConfigError, load_settings
from mica.core.types import Chunk, GateDecision, ScoredChunk
from mica.rag.gate import ScoreThresholdGate, gate_signal, make_gate
from mica.rag.retriever import HybridRrfRetriever

DEV_YAML = Path(__file__).resolve().parents[2] / "config" / "dev.yaml"


def _chunk(i: int) -> Chunk:
    return Chunk(f"doc#{i}", "doc", "Dokumen", "Bagian", date(2026, 9, 29), "dev", f"c{i}", False)


def _hit(score: float, top1: float | None) -> ScoredChunk:
    raw = {"dense": score} if top1 is None else {"dense": score, "dense@1": top1}
    return ScoredChunk(chunk=_chunk(0), score=score, ranks={"dense": 1}, raw_scores=raw)


@pytest.mark.parametrize(
    ("signal", "passed"),
    [(0.61, True), (0.60, True), (0.59, False)],
    ids=["di-atas", "sama-dengan", "di-bawah"],
)
def test_threshold(signal, passed):
    decision = ScoreThresholdGate(0.60).decide([_hit(signal, signal)])
    assert decision == GateDecision(passed=passed, score=signal, threshold=0.60)


def test_null_threshold_always_passes_but_reports_score():
    decision = ScoreThresholdGate(None).decide([_hit(0.12, 0.12)])
    assert decision == GateDecision(passed=True, score=0.12, threshold=None)


def test_no_signal_rejected_when_threshold_set():
    assert ScoreThresholdGate(0.5).decide([]) == GateDecision(False, None, 0.5)
    bm25_only = ScoredChunk(_chunk(0), 9.0, {"bm25": 1}, {"bm25": 9.0})
    assert ScoreThresholdGate(0.5).decide([bm25_only]).passed is False
    assert ScoreThresholdGate(None).decide([]) == GateDecision(True, None, None)


def test_signal_is_dense_top1_not_rrf_score():
    hit = ScoredChunk(_chunk(0), 0.0325, {"bm25": 1, "dense": 1},
                      {"bm25": 9.5, "dense": 0.71, "dense@1": 0.71})
    assert gate_signal([hit]) == 0.71


class StubSource:
    def __init__(self, name, ranked):
        self.name = name
        self.ranked = ranked

    def rank(self, query, n):
        return self.ranked[:n]


def test_hybrid_signal_when_dense_top1_not_in_top_k():
    chunks = tuple(_chunk(i) for i in range(4))
    # dense #1 = c0 (0.80) hanya ditemukan dense; c1 ditemukan keduanya sehingga menang di RRF
    hybrid = HybridRrfRetriever(
        chunks,
        [StubSource("bm25", [(1, 9.0), (2, 5.0)]), StubSource("dense", [(0, 0.80), (1, 0.50)])],
        rrf_k=60,
        candidates_per_retriever=10,
    )
    hits = hybrid.search("x", 1)
    assert [h.chunk.chunk_id for h in hits] == ["doc#1"]
    assert hits[0].raw_scores["dense"] == 0.50
    decision = ScoreThresholdGate(0.75).decide(hits)
    assert decision.score == 0.80  # dari dense #1, bukan dense chunk hasil fusi
    assert decision.passed is True


def _write_config(tmp_path, **rag):
    raw = yaml.safe_load(DEV_YAML.read_text(encoding="utf-8"))
    for key, value in rag.items():
        if key == "threshold":
            raw["rag"]["gate"]["threshold"] = value
        else:
            raw["rag"][key] = value
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_bm25_with_threshold_rejected_at_load(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_settings(_write_config(tmp_path, retriever="bm25", threshold=0.6))
    assert exc.value.code == CFG_INVALID
    assert "rag.gate.threshold" in str(exc.value)


@pytest.mark.parametrize("retriever", ["dense", "hybrid"])
def test_dense_retrievers_accept_threshold(tmp_path, retriever):
    settings = load_settings(_write_config(tmp_path, retriever=retriever, threshold=0.6))
    gate = make_gate(settings)
    assert isinstance(gate, ScoreThresholdGate) and gate.threshold == 0.6


def test_bm25_without_threshold_allowed(tmp_path):
    settings = load_settings(_write_config(tmp_path, retriever="bm25", threshold=None))
    assert make_gate(settings).decide([]).passed is True
