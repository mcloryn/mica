"""Langkah 55: banding rag.followup_mode (concat, dual, llm_rewrite) di set dev, docs/FOLLOWUP.md.

python -m mica.eval followup --config config/dev.yaml [--dataset data/eval/questions.jsonl]
    [--switch data/eval/dev_topic_switch.jsonl] [--modes concat,dual,llm_rewrite]
    [--out results/FOLLOWUP] [--cache-dir data/cache/llm/rewrite] [--logs logs]

Kelompok (aturan pra-registrasi docs/FOLLOWUP.md):
- followup: pertanyaan dev bertipe followup (pertanyaan sebelumnya dari prev_qid) + pasangan
  ganti topik (dev_topic_switch.jsonl). Metrik utama Recall@5 kelompok gabungan ini.
- non_followup: pertanyaan dev answerable tanpa pertanyaan sebelumnya.
Kueri dibuat lewat mica.rag.followup.make_followup, sama dengan AnswerPipeline. Teks di-scrub
sebelum retrieval dan API. llm_rewrite memakai CachedRewriter (hemat kuota Groq); latensi
rewrite = latensi panggilan API asli yang tersimpan di cache. Latensi retrieval = waktu search
saja (median 3 ulangan, satu kueri pemanasan), seperti E-01.
"""

from __future__ import annotations

import csv
import json
import statistics
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mica.config import Settings
from mica.eval.dataset import load_questions
from mica.eval.environment import collect_environment
from mica.eval.metrics import hit_at, percentile, reciprocal_rank
from mica.eval.retrieval import sha256_file
from mica.rag.followup import CachedRewriter, GroqQueryRewriter, make_followup
from mica.rag.pii import scrub_pii
from mica.rag.retriever import Retriever

MODES = ("concat", "dual", "llm_rewrite")
DEPTH = 10
RECALL_K = 5
LATENCY_REPEATS = 3
FOLLOWUP_GROUP = "followup"  # gabungan followup dev + ganti topik (metrik utama)
NON_FOLLOWUP_GROUP = "non_followup"
LLM_MODEL = "groq:openai/gpt-oss-120b"  # sumber p95 LLM jawaban dari log giliran


@dataclass(frozen=True)
class Item:
    qid: str
    kind: str  # followup | topic_switch | answerable
    group: str
    question: str
    previous: str | None
    gold: tuple[str, ...]


@dataclass(frozen=True)
class ItemResult:
    item: Item
    query: str
    top_ids: tuple[str, ...]
    hit5: bool
    rr: float
    search_ms: float
    rewrite_s: float | None
    rewrite_fallback: bool


def load_items(dataset: Path, switch: Path) -> list[Item]:
    questions = [q for q in load_questions(dataset) if q.get("split") == "dev"]
    by_qid = {q["qid"]: q for q in questions}
    items: list[Item] = []
    for q in questions:
        if q["type"] == "answerable":
            items.append(Item(q["qid"], "answerable", NON_FOLLOWUP_GROUP, q["question"], None,
                              tuple(q["gold_chunk_ids"])))  # fmt: skip
        elif q["type"] == "followup":
            prev = by_qid[q["prev_qid"]]["question"]
            items.append(Item(q["qid"], "followup", FOLLOWUP_GROUP, q["question"], prev,
                              tuple(q["gold_chunk_ids"])))  # fmt: skip
    for line in Path(switch).read_text(encoding="utf-8").splitlines():
        if line.strip():
            t = json.loads(line)
            items.append(Item(t["qid"], "topic_switch", FOLLOWUP_GROUP, t["question"],
                              t["prev_question"], tuple(t["gold_chunk_ids"])))  # fmt: skip
    return items


def with_mode(settings: Settings, mode: str) -> Settings:
    rag = settings.rag.model_copy(update={"followup_mode": mode})
    return settings.model_copy(update={"rag": rag})


def evaluate_mode(
    settings: Settings, mode: str, retriever: Retriever, items: list[Item],
    rewriter: Any = None,
) -> list[ItemResult]:  # fmt: skip
    strategy = make_followup(with_mode(settings, mode), retriever, rewriter=rewriter)
    retriever.search(items[0].question, DEPTH)  # pemanasan, tidak diukur
    results = []
    for item in items:
        q = scrub_pii(item.question)
        prev = scrub_pii(item.previous) if item.previous else None
        timings, found = [], None
        for repeat in range(LATENCY_REPEATS if mode != "llm_rewrite" else 1):
            started = time.perf_counter()
            out = strategy.search(q, prev, DEPTH)
            timings.append((time.perf_counter() - started) * 1000)
            found = found or out
        assert found is not None
        rewrite_s = None
        search_ms = statistics.median(timings)
        if mode == "llm_rewrite" and found.rewrite_s is not None:
            # waktu search saja: ukur ulang search kueri hasil rewrite (tanpa panggilan cache)
            again = []
            for _ in range(LATENCY_REPEATS):
                started = time.perf_counter()
                retriever.search(found.query, DEPTH)
                again.append((time.perf_counter() - started) * 1000)
            search_ms = statistics.median(again)
            # CachedRewriter: latensi panggilan API asli (juga saat dibaca dari cache)
            rewrite_s = getattr(rewriter, "last_latency_s", None) or found.rewrite_s
            if found.rewrite_fallback:
                rewrite_s = found.rewrite_s
        ranked = [h.chunk.chunk_id for h in found.hits]
        results.append(ItemResult(
            item, found.query, tuple(ranked), hit_at(ranked, item.gold, RECALL_K),
            reciprocal_rank(ranked, item.gold, DEPTH), search_ms, rewrite_s,
            found.rewrite_fallback,
        ))  # fmt: skip
    return results


def _recall(results: list[ItemResult]) -> float | None:
    return sum(r.hit5 for r in results) / len(results) if results else None


def summarize(results: list[ItemResult]) -> dict[str, Any]:
    groups = {
        FOLLOWUP_GROUP: [r for r in results if r.item.group == FOLLOWUP_GROUP],
        "followup_dev": [r for r in results if r.item.kind == "followup"],
        "topic_switch": [r for r in results if r.item.kind == "topic_switch"],
        NON_FOLLOWUP_GROUP: [r for r in results if r.item.group == NON_FOLLOWUP_GROUP],
    }
    out: dict[str, Any] = {}
    for name, rs in groups.items():
        out[name] = {
            "n": len(rs),
            "hits@5": sum(r.hit5 for r in rs),
            "recall@5": _recall(rs),
            "mrr@10": sum(r.rr for r in rs) / len(rs) if rs else None,
        }
    searches = [r.search_ms for r in results]
    rewrites = [r.rewrite_s for r in results if r.rewrite_s is not None]
    out["latency"] = {
        "search_p50_ms": percentile(searches, 50),
        "search_p95_ms": percentile(searches, 95),
        "rewrite_calls": len(rewrites),
        "rewrite_p50_s": percentile(rewrites, 50) if rewrites else None,
        "rewrite_p95_s": percentile(rewrites, 95) if rewrites else None,
        "rewrite_fallbacks": sum(r.rewrite_fallback for r in results),
    }
    return out


def answer_llm_p95(log_dir: Path, model: str = LLM_MODEL) -> dict[str, Any]:
    """p95 timings.llm dan timings.total giliran yang sampai ke LLM (log M-11 di logs/)."""
    llm, total = [], []
    for path in sorted(Path(log_dir).glob("turns-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            t = row.get("timings") or {}
            if row.get("llm_provider") == model and "llm" in t:
                llm.append(t["llm"])
                total.append(t.get("total", t["llm"]))
    return {
        "model": model,
        "n": len(llm),
        "llm_p95_s": percentile(llm, 95) if llm else None,
        "total_p95_s": percentile(total, 95) if total else None,
    }


# --- aturan pra-registrasi (docs/FOLLOWUP.md) ------------------------------------------------

RETRIEVAL_BUDGET_MS = 500.0  # SDD 3.3: retrieval + gerbang 0,5 s
LLM_BUDGET_S = 4.0  # SDD 3.3: LLM 4 s
TOTAL_BUDGET_S = 10.0  # SDD 3.3: total <= 10 s
EXTRA_LLM = {"concat": False, "dual": False, "llm_rewrite": True}


def decide(summaries: dict[str, dict[str, Any]], answer: dict[str, Any]) -> dict[str, Any]:
    """Terapkan aturan apa adanya; concat adalah pembanding non_followup."""
    base_non = summaries["concat"][NON_FOLLOWUP_GROUP]["hits@5"]
    n_main = summaries["concat"][FOLLOWUP_GROUP]["n"]
    checks: dict[str, Any] = {}
    for mode, s in summaries.items():
        lat = s["latency"]
        non_ok = s[NON_FOLLOWUP_GROUP]["hits@5"] >= base_non
        retr_ok = lat["search_p95_ms"] <= RETRIEVAL_BUDGET_MS
        rewrite = lat["rewrite_p95_s"] or 0.0
        llm_ok = total_ok = True
        if EXTRA_LLM[mode]:
            llm_ok = (
                answer["llm_p95_s"] is not None and rewrite + answer["llm_p95_s"] <= LLM_BUDGET_S
            )
            total_ok = (answer["total_p95_s"] is not None
                        and answer["total_p95_s"] + rewrite <= TOTAL_BUDGET_S)  # fmt: skip
        checks[mode] = {
            "non_followup_not_lower": non_ok, "retrieval_budget": retr_ok,
            "llm_budget": llm_ok, "total_budget": total_ok,
            "eligible": non_ok and retr_ok and llm_ok and total_ok,
            "hits@5": s[FOLLOWUP_GROUP]["hits@5"],
        }  # fmt: skip
    eligible = [m for m, c in checks.items() if c["eligible"]]
    best = max(checks[m]["hits@5"] for m in eligible)
    tied = [m for m in eligible if best - checks[m]["hits@5"] <= 1]  # seri: dalam 1 pertanyaan
    no_llm = [m for m in tied if not EXTRA_LLM[m]]
    pool = no_llm or tied
    top = max(checks[m]["hits@5"] for m in pool)
    # urutan MODES (concat, dual, llm_rewrite) = makin banyak kerja tambahan
    chosen = next(m for m in MODES if m in pool and checks[m]["hits@5"] == top)
    return {"n_followup_group": n_main, "checks": checks, "eligible": eligible,
            "tied_with_best": tied, "chosen": chosen}  # fmt: skip


def _write_items(path: Path, results: dict[str, list[ItemResult]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mode", "qid", "kind", "hit@5", "rr", "search_ms", "rewrite_s",
                    "rewrite_fallback", "query", "top5"])  # fmt: skip
        for mode, rs in results.items():
            for r in rs:
                w.writerow([mode, r.item.qid, r.item.kind, int(r.hit5), f"{r.rr:.4f}",
                            f"{r.search_ms:.2f}",
                            "" if r.rewrite_s is None else f"{r.rewrite_s:.3f}",
                            int(r.rewrite_fallback), r.query, " ".join(r.top_ids[:RECALL_K])])  # fmt: skip


def run_followup(
    settings: Settings, retriever: Retriever, dataset: Path, switch: Path, out_root: Path,
    modes: list[str], cache_dir: Path, log_dir: Path, rewriter: Any = None,
) -> tuple[dict[str, Any], Path]:  # fmt: skip
    started = datetime.now().astimezone()
    items = load_items(dataset, switch)
    results: dict[str, list[ItemResult]] = {}
    if "llm_rewrite" in modes and rewriter is None:
        entry = settings.llm.chain[0]
        _, _, model = entry.partition(":")
        from pydantic import SecretStr

        rewriter = CachedRewriter(
            GroqQueryRewriter(model, api_key=settings.api_keys.groq or SecretStr(""),
                              temperature=settings.llm.temperature,
                              reasoning_effort=settings.llm.reasoning_effort),
            cache_dir,
        )  # fmt: skip
    for mode in modes:
        results[mode] = evaluate_mode(settings, mode, retriever, items,
                                      rewriter if mode == "llm_rewrite" else None)  # fmt: skip
    summaries = {m: summarize(rs) for m, rs in results.items()}
    answer = answer_llm_p95(log_dir)
    decision = decide(summaries, answer) if "concat" in summaries else None
    run_dir = Path(out_root) / started.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_items(run_dir / "per_item.csv", results)
    run = {
        "experiment": "FOLLOWUP (Langkah 55)",
        "config_hash": settings.config_hash(),
        "kb_id": settings.kb.active_id,
        "dataset": {"path": Path(dataset).as_posix(), "sha256": sha256_file(dataset)},
        "switch": {"path": Path(switch).as_posix(), "sha256": sha256_file(switch)},
        "rewrite_model": settings.llm.chain[0],
        "rewrite_cache": {
            "hits": getattr(rewriter, "hits", None),
            "api_calls": getattr(rewriter, "calls", None),
        },
        "depth": DEPTH,
        "recall_k": RECALL_K,
        "latency_repeats": LATENCY_REPEATS,
        "summaries": summaries,
        "answer_llm_from_logs": answer,
        "decision": decision,
        "environment": collect_environment(),
        "started_at": started.isoformat(),
    }
    (run_dir / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")  # fmt: skip
    return run, run_dir
