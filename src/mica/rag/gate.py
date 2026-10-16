"""M-04: gerbang relevansi sebelum LLM (ADR-06, Provisional; ambang dikalibrasi di E-02).

Sinyal = cosine dense peringkat 1 untuk kueri (raw_scores["dense@1"]), bukan skor RRF: skor RRF
hanya berbasis peringkat sehingga tidak bisa dibandingkan dengan ambang antarkueri.
"""

from __future__ import annotations

from typing import Protocol

from mica.config import Settings
from mica.core.types import GateDecision, ScoredChunk
from mica.rag.retriever import DENSE_TOP1


class RelevanceGate(Protocol):
    def decide(self, hits: list[ScoredChunk]) -> GateDecision: ...


def gate_signal(hits: list[ScoredChunk]) -> float | None:
    """Cosine dense peringkat 1; None bila hasil kosong atau retriever tanpa skor dense."""
    values = [h.raw_scores[DENSE_TOP1] for h in hits if DENSE_TOP1 in h.raw_scores]
    return max(values) if values else None


class ScoreThresholdGate:
    def __init__(self, threshold: float | None) -> None:
        self.threshold = threshold

    def decide(self, hits: list[ScoredChunk]) -> GateDecision:
        score = gate_signal(hits)
        if self.threshold is None:
            # belum dikalibrasi (dev, konfigurasi C1): selalu lolos, skor tetap dicatat
            return GateDecision(passed=True, score=score, threshold=None)
        passed = score is not None and score >= self.threshold
        return GateDecision(passed=passed, score=score, threshold=self.threshold)


def make_gate(settings: Settings) -> RelevanceGate:
    return ScoreThresholdGate(settings.rag.gate.threshold)
