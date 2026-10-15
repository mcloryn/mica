import math

import pytest

from mica.eval.metrics import (
    first_relevant_rank,
    hit_at,
    ndcg_at,
    percentile,
    reciprocal_rank,
)

RANKED = [f"c{i}" for i in range(1, 11)]  # c1 di peringkat 1, ..., c10 di peringkat 10


def test_relevant_at_rank_1():
    relevant = {"c1"}
    assert first_relevant_rank(RANKED, relevant) == 1
    assert hit_at(RANKED, relevant, 5) is True
    assert reciprocal_rank(RANKED, relevant) == 1.0
    assert ndcg_at(RANKED, relevant) == 1.0


def test_relevant_at_rank_6():
    relevant = {"c6"}
    assert first_relevant_rank(RANKED, relevant) == 6
    assert hit_at(RANKED, relevant, 5) is False  # di luar 5 teratas
    assert reciprocal_rank(RANKED, relevant) == pytest.approx(1 / 6)
    # DCG = 1/log2(6+1) = 0.356207; IDCG = 1/log2(2) = 1
    assert ndcg_at(RANKED, relevant) == pytest.approx(0.356207, abs=1e-6)


def test_no_relevant_retrieved():
    relevant = {"z"}
    assert first_relevant_rank(RANKED, relevant) is None
    assert hit_at(RANKED, relevant, 5) is False
    assert reciprocal_rank(RANKED, relevant) == 0.0
    assert ndcg_at(RANKED, relevant) == 0.0


def test_empty_relevant_set():
    assert ndcg_at(RANKED, set()) == 0.0
    assert reciprocal_rank(RANKED, set()) == 0.0


def test_two_relevant_at_rank_2_and_4():
    relevant = {"c2", "c4"}
    # DCG = 1/log2(3) + 1/log2(5) = 0.630930 + 0.430677 = 1.061606
    # IDCG = 1/log2(2) + 1/log2(3) = 1 + 0.630930 = 1.630930  -> nDCG = 0.650920
    assert ndcg_at(RANKED, relevant) == pytest.approx(0.650920, abs=1e-6)
    assert reciprocal_rank(RANKED, relevant) == pytest.approx(0.5)


def test_relevant_not_yet_retrieved_lowers_ndcg():
    # 3 relevan, hanya 1 di daftar (peringkat 1): DCG = 1; IDCG = 1 + 0.630930 + 0.5
    assert ndcg_at(RANKED, {"c1", "x", "y"}) == pytest.approx(1 / 2.130930, abs=1e-6)


def test_mrr_cutoff():
    ranked = RANKED + ["c11"]
    assert reciprocal_rank(ranked, {"c11"}, cutoff=10) == 0.0
    assert reciprocal_rank(ranked, {"c11"}, cutoff=11) == pytest.approx(1 / 11)


def test_idcg_capped_at_k():
    relevant = {f"c{i}" for i in range(1, 16)}  # 15 relevan, k = 10
    assert ndcg_at(RANKED, relevant, 10) == pytest.approx(1.0)


def test_percentile_linear():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([1, 2, 3, 4], 95) == pytest.approx(3.85)
    assert math.isnan(percentile([], 50))
