"""M-12: metrik retrieval (E-01, SDD 9.4). Peringkat dihitung mulai dari 1."""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence

import numpy as np


def first_relevant_rank(ranked: Sequence[str], relevant: Collection[str]) -> int | None:
    for rank, chunk_id in enumerate(ranked, start=1):
        if chunk_id in relevant:
            return rank
    return None


def hit_at(ranked: Sequence[str], relevant: Collection[str], k: int) -> bool:
    """True bila ada >= 1 chunk relevan di k teratas (dasar Recall@k per pertanyaan)."""
    return any(chunk_id in relevant for chunk_id in ranked[:k])


def reciprocal_rank(ranked: Sequence[str], relevant: Collection[str], cutoff: int = 10) -> float:
    """1/rank chunk relevan pertama di `cutoff` teratas; 0 bila tidak ada."""
    rank = first_relevant_rank(ranked[:cutoff], relevant)
    return 0.0 if rank is None else 1.0 / rank


def ndcg_at(ranked: Sequence[str], relevant: Collection[str], k: int = 10) -> float:
    """nDCG@k dengan gain biner; IDCG dari min(jumlah relevan, k). 0 bila tidak ada relevan."""
    if not relevant:
        return 0.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(ranked[:k], start=1)
        if chunk_id in relevant
    )
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return dcg / ideal


def percentile(values: Sequence[float], q: float) -> float:
    """Persentil dengan interpolasi linear (numpy default)."""
    if not values:
        return float("nan")
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))
