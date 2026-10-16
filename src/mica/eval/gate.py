"""M-12 gate: skor gerbang M-04 per pertanyaan dan sweep ambang untuk E-02 (SDD 9.5).

Skrip ini hanya mengukur. Ambang tidak dipilih di sini, dan config tidak diubah.
"""

from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mica.config import Settings
from mica.eval.dataset import Question, load_questions, retrieval_query
from mica.eval.environment import collect_environment
from mica.eval.retrieval import sha256_file
from mica.kb.embedder import Embedder
from mica.kb.index import KnowledgeBase
from mica.rag.gate import make_gate
from mica.rag.retriever import DenseRetriever, embedder_for_kb, make_retriever

EXPERIMENT = "E-02"
SPLIT = "dev"
# ambang dalam perseratus supaya langkah 0,01 tidak bergeser karena galat float
SWEEP_FROM, SWEEP_TO = 30, 90
GROUPS = ("answerable", "followup", "jauh", "dekat", "false_premise")
SCORE_COLUMNS = ("qid", "type", "oos_level", "gate_score", "dense_top1_chunk_id")
SWEEP_COLUMNS = (
    "threshold",
    "answerable_followup_n",
    "false_reject_n",
    "false_reject_rate",
    "jauh_n",
    "jauh_reject_n",
    "jauh_reject_rate",
    "dekat_n",
    "dekat_reject_n",
    "dekat_reject_rate",
    "false_premise_n",
    "false_premise_reject_n",
    "false_premise_reject_rate",
)


@dataclass(frozen=True)
class GateScore:
    qid: str
    type: str
    oos_level: str | None
    score: float | None
    dense_top1_chunk_id: str | None

    @property
    def group(self) -> str:
        return self.oos_level if self.type == "out_of_kb" and self.oos_level else self.type


def thresholds() -> list[float]:
    return [round(t / 100, 2) for t in range(SWEEP_FROM, SWEEP_TO + 1)]


def rejected(score: float | None, threshold: float) -> bool:
    """Sama dengan ScoreThresholdGate: lolos bila skor >= ambang; tanpa skor = ditolak."""
    return score is None or score < threshold


def score_questions(
    settings: Settings, kb: KnowledgeBase, questions: list[Question], embedder: Embedder
) -> list[GateScore]:
    if settings.rag.retriever == "bm25":
        raise ValueError("eval gate butuh skor dense; rag.retriever tidak boleh bm25")
    retriever = make_retriever(settings, kb, embedder_factory=lambda m, r: embedder)
    gate = make_gate(settings)
    dense = DenseRetriever(kb, embedder)
    by_qid = {q["qid"]: q for q in questions}
    results: list[GateScore] = []
    for q in questions:
        if q.get("split") != SPLIT:
            continue
        query = retrieval_query(q, by_qid)  # followup: prev_qid + pertanyaan (concat)
        decision = gate.decide(retriever.search(query, settings.rag.top_k))
        top = dense.search(query, 1)
        top_id = top[0].chunk.chunk_id if top else None
        # Sinyal gerbang harus sama dengan cosine dense peringkat 1 yang dihitung langsung.
        if top and (decision.score is None or abs(decision.score - top[0].score) > 1e-5):
            raise RuntimeError(
                f"{q['qid']}: skor gerbang {decision.score} != dense #1 {top[0].score}"
            )
        results.append(GateScore(q["qid"], q["type"], q.get("oos_level"), decision.score, top_id))
    return results


def sweep(scores: list[GateScore]) -> list[dict[str, Any]]:
    by_group = {g: [s.score for s in scores if s.group == g] for g in GROUPS}
    wanted = by_group["answerable"] + by_group["followup"]

    def stats(values: list[float | None], t: float) -> tuple[int, int, str]:
        n = len(values)
        k = sum(rejected(v, t) for v in values)
        return n, k, f"{k / n:.4f}" if n else ""

    rows = []
    for t in thresholds():
        n_ok, fr, fr_rate = stats(wanted, t)
        n_far, far, far_rate = stats(by_group["jauh"], t)
        n_near, near, near_rate = stats(by_group["dekat"], t)
        n_fp, fp, fp_rate = stats(by_group["false_premise"], t)
        rows.append(
            {
                "threshold": f"{t:.2f}",
                "answerable_followup_n": n_ok,
                "false_reject_n": fr,
                "false_reject_rate": fr_rate,
                "jauh_n": n_far,
                "jauh_reject_n": far,
                "jauh_reject_rate": far_rate,
                "dekat_n": n_near,
                "dekat_reject_n": near,
                "dekat_reject_rate": near_rate,
                "false_premise_n": n_fp,
                "false_premise_reject_n": fp,
                "false_premise_reject_rate": fp_rate,
            }
        )
    return rows


def group_stats(scores: list[GateScore]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for g in GROUPS:
        values = [s.score for s in scores if s.group == g and s.score is not None]
        out[g] = {
            "n": len(values),
            "min": min(values) if values else None,
            "median": statistics.median(values) if values else None,
            "max": max(values) if values else None,
        }
    return out


def run_gate(
    settings: Settings,
    kb: KnowledgeBase,
    dataset: Path,
    out_root: Path,
    embedder: Embedder | None = None,
    started_at: datetime | None = None,
    environment: dict[str, Any] | None = None,
) -> tuple[Path, list[GateScore]]:
    started_at = started_at or datetime.now().astimezone()
    environment = environment if environment is not None else collect_environment()
    questions = load_questions(dataset)
    if embedder is None:
        embedder = embedder_for_kb(kb)
        load = getattr(embedder, "load", None)
        if load is not None:
            load()
    scores = score_questions(settings, kb, questions, embedder)

    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(out_root) / f"{stamp}-{SPLIT}-{settings.rag.retriever}"
    run_dir.mkdir(parents=True, exist_ok=False)
    with (run_dir / "gate_scores.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SCORE_COLUMNS)
        writer.writeheader()
        for s in scores:
            writer.writerow(
                {
                    "qid": s.qid,
                    "type": s.type,
                    "oos_level": s.oos_level or "",
                    "gate_score": "" if s.score is None else f"{s.score:.6f}",
                    "dense_top1_chunk_id": s.dense_top1_chunk_id or "",
                }
            )
    with (run_dir / "sweep.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SWEEP_COLUMNS)
        writer.writeheader()
        writer.writerows(sweep(scores))

    info = kb.manifest["embedder"]
    run = {
        "experiment": EXPERIMENT,
        "component": "gate",
        "split": SPLIT,
        "retriever": settings.rag.retriever,
        "gate_signal": "dense@1 (cosine dense peringkat 1)",
        "gate_threshold_config": settings.rag.gate.threshold,
        "top_k": settings.rag.top_k,
        "followup_query": "concat",
        "config_hash": settings.config_hash(),
        "kb_id": kb.kb_id,
        "dataset": {"path": Path(dataset).as_posix(), "sha256": sha256_file(dataset)},
        "embedder": {"model": info["model"], "revision": info["revision"]},
        "sweep": {"from": SWEEP_FROM / 100, "to": SWEEP_TO / 100, "step": 0.01},
        "n_questions": {g: sum(s.group == g for s in scores) for g in GROUPS},
        "score_stats": group_stats(scores),
        "environment": environment,
        "started_at": started_at.isoformat(),
    }
    (run_dir / "run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return run_dir, scores
