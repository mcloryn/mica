"""M-12 retrieval: E-01 (SDD 9.4, 9.5). Recall@5, MRR@10, nDCG@10, dan latensi per retriever.

- Metrik utama: pertanyaan split dev bertipe answerable.
- followup dihitung terpisah dengan kueri apa adanya ("followup_tanpa_rewrite").
- Latensi = waktu search saja: 1 kueri pemanasan dibuang, tiap pertanyaan diukur 3 kali, median.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mica.config import Settings
from mica.eval.dataset import DatasetError, Question, load_questions
from mica.eval.environment import collect_environment
from mica.eval.metrics import (
    first_relevant_rank,
    hit_at,
    ndcg_at,
    percentile,
    reciprocal_rank,
)
from mica.kb.embedder import Embedder
from mica.kb.index import KnowledgeBase
from mica.rag.retriever import Retriever, embedder_for_kb, make_retriever

EXPERIMENT = "E-01"
SPLIT = "dev"
DEPTH = 10  # chunk teratas yang diambil per pertanyaan
RECALL_K = 5
LATENCY_REPEATS = 3
MAIN_GROUP = "answerable"
FOLLOWUP_GROUP = "followup_tanpa_rewrite"
PER_QUESTION_COLUMNS = (
    "qid",
    "type",
    "n_relevant",
    "first_relevant_rank",
    "hit@5",
    "rr",
    "ndcg10",
    "latency_ms",
    "top5_chunk_ids",
    "unjudged",
)
SUMMARY_COLUMNS = (
    "retriever",
    "run_dir",
    "config_hash",
    "kb_id",
    "n_questions",
    "recall@5",
    "mrr@10",
    "ndcg@10",
    "latency_p50_ms",
    "latency_p95_ms",
    "unjudged",
    "n_followup",
    "followup_recall@5",
    "followup_mrr@10",
    "followup_ndcg@10",
)


@dataclass(frozen=True)
class QuestionResult:
    qid: str
    type: str
    group: str
    n_relevant: int
    first_relevant_rank: int | None
    hit5: bool
    rr: float
    ndcg10: float
    latency_ms: float
    top_ids: tuple[str, ...]
    unjudged: int


@dataclass(frozen=True)
class RunResult:
    retriever: str
    run_dir: Path
    config_hash: str
    metrics: dict[str, dict[str, Any]]
    questions: tuple[QuestionResult, ...]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_pool_pairs(pool: Path) -> set[tuple[str, str]]:
    """Pasangan (qid, chunk_id) yang sudah dinilai di pool anotasi."""
    with Path(pool).open(encoding="utf-8-sig", newline="") as f:
        return {(row["qid"], row["chunk_id"]) for row in csv.DictReader(f)}


def select_questions(questions: list[Question]) -> list[tuple[str, Question]]:
    """(grup, pertanyaan) untuk split dev: answerable (utama) dan followup (terpisah)."""
    selected: list[tuple[str, Question]] = []
    missing_gold: list[str] = []
    for q in questions:
        if q.get("split") != SPLIT:
            continue
        if q["type"] == "answerable":
            if not q.get("gold_chunk_ids"):
                missing_gold.append(q["qid"])
            selected.append((MAIN_GROUP, q))
        elif q["type"] == "followup":
            selected.append((FOLLOWUP_GROUP, q))
    if missing_gold:
        raise DatasetError(
            "pertanyaan answerable tanpa gold_chunk_ids (jalankan annotate dulu): "
            + ", ".join(missing_gold)
        )
    if not any(group == MAIN_GROUP for group, _ in selected):
        raise DatasetError(f"tidak ada pertanyaan answerable di split {SPLIT}")
    return selected


def _measure(retriever: Retriever, query: str) -> tuple[list[str], float]:
    timings: list[float] = []
    ranked: list[str] = []
    for repeat in range(LATENCY_REPEATS):
        started = time.perf_counter()
        hits = retriever.search(query, DEPTH)
        timings.append((time.perf_counter() - started) * 1000)
        if repeat == 0:
            ranked = [h.chunk.chunk_id for h in hits]
    return ranked, statistics.median(timings)


def evaluate(
    retriever: Retriever,
    selected: list[tuple[str, Question]],
    pool_pairs: set[tuple[str, str]],
) -> list[QuestionResult]:
    retriever.search(selected[0][1]["question"], DEPTH)  # pemanasan, tidak diukur
    results: list[QuestionResult] = []
    for group, q in selected:
        relevant = set(q.get("gold_chunk_ids") or [])
        ranked, latency_ms = _measure(retriever, q["question"])  # followup: tanpa rewrite
        results.append(
            QuestionResult(
                qid=q["qid"],
                type=q["type"],
                group=group,
                n_relevant=len(relevant),
                first_relevant_rank=first_relevant_rank(ranked, relevant),
                hit5=hit_at(ranked, relevant, RECALL_K),
                rr=reciprocal_rank(ranked, relevant, DEPTH),
                ndcg10=ndcg_at(ranked, relevant, DEPTH),
                latency_ms=latency_ms,
                top_ids=tuple(ranked),
                unjudged=sum((q["qid"], c) not in pool_pairs for c in ranked),
            )
        )
    return results


def summarize(results: list[QuestionResult]) -> dict[str, Any]:
    if not results:
        return {"n_questions": 0}
    latencies = [r.latency_ms for r in results]
    n = len(results)
    return {
        "n_questions": n,
        "recall@5": sum(r.hit5 for r in results) / n,
        "mrr@10": sum(r.rr for r in results) / n,
        "ndcg@10": sum(r.ndcg10 for r in results) / n,
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "unjudged": sum(r.unjudged for r in results),
    }


def _write_per_question(path: Path, results: list[QuestionResult]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PER_QUESTION_COLUMNS)
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "qid": r.qid,
                    "type": r.type,
                    "n_relevant": r.n_relevant,
                    "first_relevant_rank": (
                        "" if r.first_relevant_rank is None else r.first_relevant_rank
                    ),
                    "hit@5": int(r.hit5),
                    "rr": f"{r.rr:.6f}",
                    "ndcg10": f"{r.ndcg10:.6f}",
                    "latency_ms": f"{r.latency_ms:.3f}",
                    "top5_chunk_ids": " ".join(r.top_ids[:RECALL_K]),
                    "unjudged": r.unjudged,
                }
            )


def with_retriever(settings: Settings, kind: str) -> Settings:
    """Konfigurasi efektif per run: rag.retriever diganti, sehingga config_hash ikut berubah."""
    rag = settings.rag.model_copy(update={"retriever": kind})
    return settings.model_copy(update={"rag": rag})


def run_retrieval(
    settings: Settings,
    kb: KnowledgeBase,
    dataset: Path,
    pool: Path,
    out_root: Path,
    retrievers: list[str],
    embedder: Embedder | None = None,
    started_at: datetime | None = None,
    environment: dict[str, Any] | None = None,
) -> tuple[list[RunResult], Path]:
    """Jalankan E-01 untuk setiap retriever; kembalikan hasil per run dan path summary CSV."""
    started_at = started_at or datetime.now().astimezone()
    # dicatat sekali sebelum run, supaya semua run.json memuat status repo yang sama
    environment = environment if environment is not None else collect_environment()
    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    selected = select_questions(load_questions(dataset))
    pool_pairs = read_pool_pairs(pool)
    dataset_sha, pool_sha = sha256_file(dataset), sha256_file(pool)

    # Embedder dimuat sekali, sebelum pengukuran, dan dipakai bersama oleh dense dan hybrid.
    if embedder is None and any(kind != "bm25" for kind in retrievers):
        embedder = embedder_for_kb(kb)
        load = getattr(embedder, "load", None)
        if load is not None:
            load()

    out_root = Path(out_root)
    runs: list[RunResult] = []
    for kind in retrievers:
        effective = with_retriever(settings, kind)
        retriever = make_retriever(effective, kb, embedder_factory=lambda m, r: embedder)
        results = evaluate(retriever, selected, pool_pairs)
        metrics = {
            MAIN_GROUP: summarize([r for r in results if r.group == MAIN_GROUP]),
            FOLLOWUP_GROUP: summarize([r for r in results if r.group == FOLLOWUP_GROUP]),
        }
        run_dir = out_root / f"{stamp}-{SPLIT}-{kind}"
        run_dir.mkdir(parents=True, exist_ok=False)
        _write_per_question(run_dir / "per_question.csv", results)
        info = kb.manifest["embedder"]
        run = {
            "experiment": EXPERIMENT,
            "split": SPLIT,
            "retriever": kind,
            "reranker_enabled": effective.rag.reranker.enabled,
            "config_hash": effective.config_hash(),
            "kb_id": kb.kb_id,
            "kb_config_hash": kb.manifest.get("config_hash"),
            "dataset": {"path": Path(dataset).as_posix(), "sha256": dataset_sha},
            "pool": {"path": Path(pool).as_posix(), "sha256": pool_sha},
            "embedder": {"model": info["model"], "revision": info["revision"]},
            "depth": DEPTH,
            "recall_k": RECALL_K,
            "latency": {"repeats": LATENCY_REPEATS, "aggregate": "median", "warmup_queries": 1},
            "n_questions": {group: m["n_questions"] for group, m in metrics.items()},
            "metrics": metrics,
            "environment": environment,
            "started_at": started_at.isoformat(),
        }
        (run_dir / "run.json").write_text(
            json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        runs.append(RunResult(kind, run_dir, run["config_hash"], metrics, tuple(results)))

    summary = out_root / f"summary-{SPLIT}-{stamp}.csv"
    with summary.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for run in runs:
            main, follow = run.metrics[MAIN_GROUP], run.metrics[FOLLOWUP_GROUP]
            writer.writerow(
                {
                    "retriever": run.retriever,
                    "run_dir": run.run_dir.name,
                    "config_hash": run.config_hash,
                    "kb_id": kb.kb_id,
                    "n_questions": main["n_questions"],
                    "recall@5": f"{main['recall@5']:.4f}",
                    "mrr@10": f"{main['mrr@10']:.4f}",
                    "ndcg@10": f"{main['ndcg@10']:.4f}",
                    "latency_p50_ms": f"{main['latency_p50_ms']:.2f}",
                    "latency_p95_ms": f"{main['latency_p95_ms']:.2f}",
                    "unjudged": main["unjudged"],
                    "n_followup": follow["n_questions"],
                    "followup_recall@5": _fmt(follow.get("recall@5")),
                    "followup_mrr@10": _fmt(follow.get("mrr@10")),
                    "followup_ndcg@10": _fmt(follow.get("ndcg@10")),
                }
            )
    return runs, summary


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"
