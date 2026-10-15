import csv
import json
from pathlib import Path

import pytest
from kb_samples import FakeEmbedder, make_kb_folder

from mica.config import load_settings
from mica.eval import __main__ as eval_cli
from mica.eval.dataset import DatasetError
from mica.eval.retrieval import (
    QuestionResult,
    run_retrieval,
    select_questions,
    summarize,
)
from mica.kb.index import build_kb, load_kb

DEV_YAML = Path(__file__).resolve().parents[2] / "config" / "dev.yaml"


def _q(qid, type_, question, gold=(), split="dev", prev=None):
    return {
        "qid": qid,
        "question": question,
        "type": type_,
        "topic": "x",
        "gold_chunk_ids": list(gold),
        "reference_answer": "",
        "split": split,
        "prev_qid": prev,
    }


@pytest.fixture
def env(tmp_path):
    settings = load_settings(DEV_YAML)
    kb_root = tmp_path / "kb"
    build_kb(make_kb_folder(tmp_path / "src"), settings.kb.active_id, "dev", settings.kb,
             FakeEmbedder(), kb_root)
    kb = load_kb(settings.kb.active_id, kb_root)
    ids = {c.chunk_id: c for c in kb.chunks}
    biaya = [c for c in ids if c.startswith("biaya#")]
    questions = [
        _q("a1", "answerable", "Berapa biaya pendaftaran Rp300.000", biaya[:1]),
        _q("a2", "answerable", "Beasiswa prestasi nilai rapor", biaya[-1:]),
        _q("t1", "answerable", "Biaya test split", biaya[:1], split="test"),
        _q("f1", "followup", "Kalau beasiswa?", biaya[-1:], prev="a1"),
        _q("o1", "out_of_kb", "Ada asrama?"),
    ]
    data = tmp_path / "eval"
    data.mkdir()
    dataset = data / "questions.jsonl"
    dataset.write_text("".join(json.dumps(q) + "\n" for q in questions), encoding="utf-8")
    # pool hanya berisi dua chunk per pertanyaan, supaya sebagian hasil berstatus unjudged
    pool = data / "pool.csv"
    with pool.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["qid", "chunk_id", "relevant"])
        writer.writeheader()
        for q in questions:
            for chunk_id in biaya[:2]:
                writer.writerow({"qid": q["qid"], "chunk_id": chunk_id, "relevant": "0"})
    return settings, kb, kb_root, dataset, pool, tmp_path


def test_select_questions_dev_answerable_and_followup(env):
    _, _, _, dataset, _, _ = env
    from mica.eval.dataset import load_questions

    selected = select_questions(load_questions(dataset))
    assert [(g, q["qid"]) for g, q in selected] == [
        ("answerable", "a1"),
        ("answerable", "a2"),
        ("followup_tanpa_rewrite", "f1"),
    ]


def test_select_questions_requires_gold():
    with pytest.raises(DatasetError) as exc:
        select_questions([_q("a1", "answerable", "x")])
    assert "a1" in str(exc.value)


def _result(hit5, rr, ndcg, latency, unjudged=0):
    return QuestionResult("q", "answerable", "answerable", 1, None, hit5, rr, ndcg, latency, (),
                          unjudged)


def test_summarize_recall_is_fraction_of_questions_with_hit():
    m = summarize([_result(True, 1.0, 1.0, 10.0, 1), _result(False, 1 / 6, 0.356, 30.0, 2)])
    assert m["recall@5"] == 0.5
    assert m["mrr@10"] == pytest.approx((1 + 1 / 6) / 2)
    assert m["ndcg@10"] == pytest.approx((1 + 0.356) / 2)
    assert m["latency_p50_ms"] == 20.0
    assert m["latency_p95_ms"] == pytest.approx(29.0)
    assert m["unjudged"] == 3


def test_run_retrieval_outputs(env):
    settings, kb, _, dataset, pool, tmp = env
    out = tmp / "results" / "E-01"
    runs, summary = run_retrieval(
        settings, kb, dataset, pool, out, ["bm25", "dense", "hybrid"], embedder=FakeEmbedder()
    )
    assert [r.retriever for r in runs] == ["bm25", "dense", "hybrid"]
    assert len({r.config_hash for r in runs}) == 3  # hash dari konfigurasi efektif
    stamp = runs[0].run_dir.name.split("-dev-")[0]
    assert [r.run_dir.name for r in runs] == [f"{stamp}-dev-{k}" for k in ("bm25", "dense", "hybrid")]
    assert summary.name == f"summary-dev-{stamp}.csv"

    run = json.loads((runs[2].run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["experiment"] == "E-01" and run["split"] == "dev" and run["retriever"] == "hybrid"
    assert run["config_hash"] == runs[2].config_hash
    # dev.yaml memakai hybrid, jadi hanya run hybrid yang hash-nya sama dengan config asli
    assert settings.rag.retriever == "hybrid"
    assert runs[2].config_hash == settings.config_hash() != runs[0].config_hash
    assert run["kb_id"] == kb.kb_id
    assert len(run["dataset"]["sha256"]) == 64 and len(run["pool"]["sha256"]) == 64
    assert run["embedder"]["revision"] == kb.manifest["embedder"]["revision"]
    assert run["n_questions"] == {"answerable": 2, "followup_tanpa_rewrite": 1}
    assert set(run["metrics"]["answerable"]) >= {"recall@5", "mrr@10", "ndcg@10",
                                                  "latency_p50_ms", "latency_p95_ms", "unjudged"}
    env_info = run["environment"]
    assert env_info["python"] and env_info["torch"] and env_info["cpu_count_logical"]

    per_q = runs[0].run_dir / "per_question.csv"
    assert per_q.read_bytes().startswith(b"\xef\xbb\xbf")
    with per_q.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["qid"] for r in rows] == ["a1", "a2", "f1"]
    assert list(rows[0]) == ["qid", "type", "n_relevant", "first_relevant_rank", "hit@5", "rr",
                             "ndcg10", "latency_ms", "top5_chunk_ids", "unjudged"]
    for row in rows:
        assert len(row["top5_chunk_ids"].split()) <= 5
        assert float(row["latency_ms"]) >= 0

    with summary.open(encoding="utf-8-sig", newline="") as f:
        lines = list(csv.DictReader(f))
    assert [r["retriever"] for r in lines] == ["bm25", "dense", "hybrid"]
    assert all(r["n_questions"] == "2" and r["n_followup"] == "1" for r in lines)


def test_unjudged_counts_chunks_outside_pool(env):
    settings, kb, _, dataset, pool, tmp = env
    runs, _ = run_retrieval(settings, kb, dataset, pool, tmp / "r", ["dense"],
                            embedder=FakeEmbedder())
    # pool di fixture: dua chunk biaya pertama (urutan KB) untuk setiap qid
    pooled = [c.chunk_id for c in kb.chunks if c.chunk_id.startswith("biaya#")][:2]
    for r in runs[0].questions:
        assert r.unjudged == sum(c not in pooled for c in r.top_ids)
    assert len(runs[0].questions[0].top_ids) == min(10, len(kb.chunks))
    assert runs[0].metrics["answerable"]["unjudged"] > 0


def test_followup_query_without_rewrite(env):
    settings, kb, _, dataset, pool, tmp = env

    class Spy(FakeEmbedder):
        def __init__(self):
            super().__init__()
            self.queries = []

        def embed(self, texts):
            self.queries.extend(texts)
            return super().embed(texts)

    spy = Spy()
    run_retrieval(settings, kb, dataset, pool, tmp / "r", ["dense"], embedder=spy)
    assert "Kalau beasiswa?" in spy.queries
    assert not any("Kalau beasiswa?" in q and q != "Kalau beasiswa?" for q in spy.queries)


def test_cli_retrieval(env, capsys):
    _, _, kb_root, dataset, _, tmp = env
    out = tmp / "results" / "E-01"
    code = eval_cli.main(
        ["--kb-root", str(kb_root), "retrieval", "--config", str(DEV_YAML),
         "--dataset", str(dataset), "--out", str(out), "--retrievers", "bm25,hybrid"],
        embedder_factory=lambda m, r: FakeEmbedder(),
    )
    printed = capsys.readouterr().out
    assert code == 0
    assert "retriever | Recall@5 | MRR | nDCG@10 | p50 ms | p95 ms | unjudged" in printed
    assert len(list(out.glob("*-dev-bm25"))) == 1 and len(list(out.glob("*-dev-hybrid"))) == 1
    assert len(list(out.glob("summary-dev-*.csv"))) == 1


def test_cli_rejects_unknown_retriever(env):
    _, _, kb_root, dataset, _, tmp = env
    with pytest.raises(SystemExit):
        eval_cli.main(["--kb-root", str(kb_root), "retrieval", "--config", str(DEV_YAML),
                       "--dataset", str(dataset), "--out", str(tmp), "--retrievers", "bm25,splade"])
