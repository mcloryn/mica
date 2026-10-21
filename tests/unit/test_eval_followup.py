"""Langkah 55: alat ukur rag.followup_mode (mica.eval.followup) dan aturan docs/FOLLOWUP.md."""

import json
from datetime import date
from pathlib import Path

import pytest
from test_pipeline import _settings

from mica.core.types import Chunk, ScoredChunk
from mica.eval import followup as fu
from mica.rag.retriever import DENSE_TOP1

ROOT = Path(__file__).resolve().parents[2]


def _chunk(cid):
    return Chunk(cid, "doc", "Dok", "Bagian", date(2026, 9, 29), "dev", cid, True)


class KeywordRetriever:
    """Chunk 'biaya' bila kata biaya ada di kueri, 'alamat' bila alamat; urutan sesuai posisi."""

    def search(self, query, k):
        q = query.lower()
        found = sorted((q.find(w), w) for w in ("alamat", "biaya", "sore") if w in q)
        ids = [w for _, w in found] + ["lain1", "lain2", "lain3", "lain4", "lain5"]
        return [ScoredChunk(_chunk(c), 1.0, {}, {DENSE_TOP1: 0.6}) for c in ids[:k]]


def _files(tmp_path):
    dataset = tmp_path / "questions.jsonl"
    rows = [
        {"qid": "d1", "question": "Biaya kuliah berapa?", "type": "answerable", "split": "dev",
         "gold_chunk_ids": ["biaya"], "gold_refs": [], "prev_qid": None},
        {"qid": "d2", "question": "Kalau yang sore?", "type": "followup", "split": "dev",
         "gold_chunk_ids": ["biaya"], "gold_refs": [], "prev_qid": "d1"},
        {"qid": "t1", "question": "Alamat kampus?", "type": "answerable", "split": "test",
         "gold_chunk_ids": ["alamat"], "gold_refs": [], "prev_qid": None},
    ]  # fmt: skip
    dataset.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    switch = tmp_path / "switch.jsonl"
    pairs = [{"qid": "ts1", "prev_question": "Di mana alamat kampus?",
              "question": "Biaya kuliah S1?", "gold_chunk_ids": ["biaya"]}]  # fmt: skip
    switch.write_text("".join(json.dumps(r) + "\n" for r in pairs), encoding="utf-8")
    return dataset, switch


def test_load_items_groups_and_skips_test_split(tmp_path):
    items = fu.load_items(*_files(tmp_path))
    assert [(i.qid, i.group) for i in items] == [
        ("d1", "non_followup"),
        ("d2", "followup"),
        ("ts1", "followup"),
    ]
    assert items[1].previous == "Biaya kuliah berapa?"


def test_concat_misses_topic_switch_dual_and_rewrite_keep_it(tmp_path):
    items = fu.load_items(*_files(tmp_path))
    settings = _settings(tmp_path)
    r = KeywordRetriever()
    concat = fu.summarize(fu.evaluate_mode(settings, "concat", r, items))
    dual = fu.summarize(fu.evaluate_mode(settings, "dual", r, items))

    class Rewriter:
        last_latency_s = 0.8

        def rewrite(self, q, prev, timeout_s):
            return "Biaya kuliah kelas sore?" if "sore" in q else q

    rw = fu.summarize(fu.evaluate_mode(settings, "llm_rewrite", r, items, Rewriter()))
    # concat: kueri ganti topik diawali "alamat", chunk biaya turun ke peringkat 2 (masih top-5)
    assert concat["followup"]["n"] == 2 and dual["followup"]["n"] == 2
    assert rw["latency"]["rewrite_calls"] == 2 and rw["latency"]["rewrite_p95_s"] == 0.8
    assert concat["latency"]["rewrite_calls"] == 0


def _summary(main_hits, non_hits=10, search_ms=100.0, rewrite=None, n=16):
    return {
        "followup": {"n": n, "hits@5": main_hits},
        "non_followup": {"n": 10, "hits@5": non_hits},
        "latency": {"search_p95_ms": search_ms, "rewrite_p95_s": rewrite},
    }


ANSWER = {"llm_p95_s": 2.0, "total_p95_s": 4.0}


def test_decide_picks_highest_recall():
    out = fu.decide({"concat": _summary(10), "dual": _summary(14),
                     "llm_rewrite": _summary(12, rewrite=0.9)}, ANSWER)  # fmt: skip
    assert out["chosen"] == "dual"


def test_decide_tie_within_one_question_prefers_no_extra_llm():
    out = fu.decide({"concat": _summary(10), "dual": _summary(13),
                     "llm_rewrite": _summary(14, rewrite=0.9)}, ANSWER)  # fmt: skip
    assert out["tied_with_best"] == ["dual", "llm_rewrite"] and out["chosen"] == "dual"


def test_decide_rejects_lower_non_followup_and_budget():
    out = fu.decide({"concat": _summary(10), "dual": _summary(15, non_hits=9),
                     "llm_rewrite": _summary(16, rewrite=2.5)}, ANSWER)  # fmt: skip
    # dual: non_followup turun; llm_rewrite: 2,5 + 2,0 > 4 s
    assert out["eligible"] == ["concat"] and out["chosen"] == "concat"
    assert not out["checks"]["llm_rewrite"]["llm_budget"]


def test_decide_retrieval_budget():
    out = fu.decide({"concat": _summary(10), "dual": _summary(15, search_ms=600)}, ANSWER)
    assert not out["checks"]["dual"]["retrieval_budget"] and out["chosen"] == "concat"


def test_answer_llm_p95_from_logs(tmp_path):
    rows = [
        {"llm_provider": fu.LLM_MODEL, "timings": {"llm": v, "total": v + 1}}
        for v in (1.0, 2.0, 3.0)
    ] + [{"llm_provider": "groq:lain", "timings": {"llm": 9}}]
    (tmp_path / "turns-2026-10-21.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows) + "rusak\n", encoding="utf-8"
    )
    out = fu.answer_llm_p95(tmp_path)
    assert out["n"] == 3 and out["llm_p95_s"] == pytest.approx(2.9)


def test_run_followup_writes_outputs(tmp_path):
    dataset, switch = _files(tmp_path)
    run, run_dir = fu.run_followup(_settings(tmp_path), KeywordRetriever(), dataset, switch,
                                   tmp_path / "out", ["concat", "dual"], tmp_path / "cache",
                                   tmp_path)  # fmt: skip
    assert (run_dir / "per_item.csv").is_file() and (run_dir / "run.json").is_file()
    assert run["decision"]["chosen"] in ("concat", "dual")


def test_repo_topic_switch_set_is_dev_and_annotated():
    lines = (ROOT / "data/eval/dev_topic_switch.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert 10 <= len(rows) <= 15
    assert all(r["split"] == "dev" and "dibuat Claude Code" in r["source"] for r in rows)
    assert all(r["gold_chunk_ids"] and r["prev_question"] for r in rows)
