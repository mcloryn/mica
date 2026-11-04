"""V2-1: diagnosis retrieval set dev (data/eval/questions.jsonl) atas KB aktif konfigurasi prod.

Hanya membaca kode aplikasi; tidak mengubah apa pun. Gold v5 dari eval/dev/gold_v5_map.csv.
Keluaran: eval/dev/v2_diag/ (per_item.jsonl, summary.json, logs/ turn log pipeline).

Pemakaian: python scripts/v2_diag_dev.py [--no-llm]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from mica.config import ConfigError, load_settings
from mica.core.logging import InteractionLog
from mica.core.types import Turn
from mica.rag.gate import gate_signal
from mica.rag.pii import scrub_pii
from mica.rag.pipeline import make_pipeline

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "data/eval/questions.jsonl"
GOLD = ROOT / "eval/dev/gold_v5_map.csv"
OUT = ROOT / "eval/dev/v2_diag"
KS = (5, 10, 20)
POOL = 50


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="hanya retrieval, tanpa pipeline penuh")
    ap.add_argument("--sleep", type=float, default=20.0, help="jeda antarpanggilan (batas Groq)")
    ap.add_argument("--retries", type=int, default=3, help="ulang bila unavailable (HTTP 429)")
    args = ap.parse_args()

    questions = {
        r["qid"]: r
        for r in (json.loads(x) for x in QUESTIONS.read_text(encoding="utf-8").splitlines() if x)
    }
    with GOLD.open(encoding="utf-8") as f:
        gold = {r["qid"]: r for r in csv.DictReader(f)}

    try:
        settings = load_settings(ROOT / "config/prod.yaml", ROOT / ".env")
        complete = True
    except ConfigError:  # prod masih punya nilai TBD di luar RAG; RAG tidak terpengaruh
        settings = load_settings(ROOT / "config/prod.yaml", ROOT / ".env", require_complete=False)
        complete = False
    rag = settings.rag
    OUT.mkdir(parents=True, exist_ok=True)
    pipeline = make_pipeline(settings, log=InteractionLog(OUT / "logs"))
    followup = pipeline.followup
    threshold = rag.gate.threshold

    # urutan file; lanjutan (prev_qid) memakai jawaban pipeline untuk soal sebelumnya
    answers: dict[str, str] = {}
    items = []
    for qid, q in questions.items():
        g = gold.get(qid)
        if g is None or q["type"] == "out_of_kb" or g["status"] in ("tidak_ada_di_kb_v5", "ragu"):
            continue
        gold_ids = [c for c in g["chunk_id_v5"].split("|") if c]
        sq = scrub_pii(q["question"])
        prev_q = questions[q["prev_qid"]]["question"] if q["prev_qid"] else None
        prev = scrub_pii(prev_q) if prev_q else None

        hits_pool = followup.search(sq, prev, POOL).hits
        hits_k = followup.search(sq, prev, rag.top_k).hits
        ranked = [h.chunk.chunk_id for h in hits_pool]
        ranks = [ranked.index(c) + 1 for c in gold_ids if c in ranked]
        best = min(ranks) if ranks else None
        topk_ids = [h.chunk.chunk_id for h in hits_k]
        in_topk = any(c in topk_ids for c in gold_ids)
        dense1 = gate_signal(hits_k)
        gate_ok = dense1 is not None and threshold is not None and dense1 >= threshold

        item = {
            "qid": qid,
            "type": q["type"],
            "gold_status": g["status"],
            "gold_v5": gold_ids,
            "prev_qid": q["prev_qid"],
            "pool_size": len(ranked),
            "gold_rank": best,
            "gold_ranks_all": {c: (ranked.index(c) + 1 if c in ranked else None) for c in gold_ids},
            "in_topk": in_topk,
            **{f"hit@{k}": best is not None and best <= k for k in KS},
            "dense_at_1": dense1,
            "gate_pass": gate_ok,
            "topk_ids": topk_ids,
            "top10_ids": ranked[:10],
        }

        if not args.no_llm:
            history = [Turn(prev, answers.get(q["prev_qid"], ""))] if prev else []
            for attempt in range(args.retries + 1):
                time.sleep(args.sleep)
                final, record = pipeline.run(q["question"], history, session_id=f"v2diag-{qid}")
                if final.status != "unavailable":
                    break
            item["attempts"] = attempt + 1
            answers[qid] = final.text
            item.update(
                {
                    "final_status": final.status,
                    "llm_status": record.llm_status,
                    "llm_provider": record.llm_provider,
                    "error_code": record.error_code,
                    "gate_record": record.gate,
                    "citations": list(record.citations),
                    "fact_check": record.fact_check,
                    "answer": record.answer,
                    "retrieved_pipeline": [r["chunk_id"] for r in record.retrieved],
                }
            )
        items.append(item)
        print(qid, best, in_topk, round(dense1 or 0, 3), item.get("final_status"), flush=True)

    def cause(it: dict) -> str:
        if not it["gate_pass"]:
            return "a_gate"
        if not it["in_topk"]:
            return "b_not_in_topk"
        if it.get("llm_status") == "not_found":
            return "c_llm_not_found"
        return "other_" + str(it.get("final_status"))

    for it in items:
        it["cause"] = cause(it)
    n = len(items)
    summary = {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kb_id": settings.kb.active_id,
        "config_hash": settings.config_hash(),
        "settings_complete": complete,
        "retriever": rag.retriever,
        "top_k": rag.top_k,
        "rrf_k": rag.rrf_k,
        "candidates_per_retriever": rag.candidates_per_retriever,
        "followup_mode": rag.followup_mode,
        "gate_threshold": threshold,
        "prompt_variant": rag.prompt_variant,
        "llm_chain": list(settings.llm.chain),
        "n": n,
        "recall@topk": sum(it["in_topk"] for it in items) / n,
        **{f"recall@{k}": sum(it[f"hit@{k}"] for it in items) / n for k in KS},
        "not_in_pool": sum(it["gold_rank"] is None for it in items),
        "gate_fail": sum(not it["gate_pass"] for it in items),
        "causes": {
            c: sum(it["cause"] == c for it in items) for c in sorted({i["cause"] for i in items})
        },
    }
    with (OUT / "per_item.jsonl").open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
