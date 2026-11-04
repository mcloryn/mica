"""V2-2b: baseline pipeline penuh (config prod) di set dev v2 + set dev lama (kunci v5).

Hanya membaca kode aplikasi. Hasil ditambahkan per soal ke eval/dev/v2_baseline/runs.jsonl
begitu selesai; soal yang sudah ada dilewati, jadi run bisa dilanjutkan bila putus.

Pemakaian: python scripts/v2_baseline_dev.py [--sleep 20] [--retries 3]
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
from mica.rag.pii import scrub_pii
from mica.rag.pipeline import make_pipeline

ROOT = Path(__file__).resolve().parents[1]
V2_SOAL = ROOT / "data/eval/dev-v2-soal.csv"
V2_KUNCI = ROOT / "data/eval/dev_v2_kunci.csv"
OLD_SOAL = ROOT / "data/eval/questions.jsonl"
OLD_KUNCI = ROOT / "data/eval/dev_lama_kunci_v5.csv"
OUT = ROOT / "eval/dev/v2_baseline"
POOL = 50


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def load_items() -> list[dict]:
    kunci = {r["qid"]: r for r in read_csv(V2_KUNCI)}
    items = [
        {"set": "v2", "qid": r["qid"], "question": r["pertanyaan"], "prev_qid": None,
         "key": kunci[r["qid"]]}
        for r in read_csv(V2_SOAL)
    ]  # fmt: skip
    old = {
        r["qid"]: r
        for r in (json.loads(x) for x in OLD_SOAL.read_text(encoding="utf-8").splitlines() if x)
    }
    for k in read_csv(OLD_KUNCI):
        if k["jenis"] == "luar_topik":
            continue
        q = old[k["qid"]]
        items.append(
            {"set": "lama", "qid": k["qid"], "question": q["question"],
             "prev_qid": q["prev_qid"], "key": k}
        )  # fmt: skip
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=20.0, help="jeda antarpanggilan (batas Groq)")
    ap.add_argument("--retries", type=int, default=3, help="ulang bila unavailable (HTTP 429)")
    args = ap.parse_args()

    try:
        settings = load_settings(ROOT / "config/prod.yaml", ROOT / ".env")
    except ConfigError:  # prod masih punya nilai TBD di luar RAG; RAG tidak terpengaruh
        settings = load_settings(ROOT / "config/prod.yaml", ROOT / ".env", require_complete=False)
    OUT.mkdir(parents=True, exist_ok=True)
    runs = OUT / "runs.jsonl"
    done: dict[str, dict] = {}
    if runs.exists():
        for line in runs.read_text(encoding="utf-8").splitlines():
            if line:
                r = json.loads(line)
                done[f"{r['set']}:{r['qid']}"] = r
    meta = {
        "kb_id": settings.kb.active_id,
        "config_hash": settings.config_hash(),
        "top_k": settings.rag.top_k,
        "gate_threshold": settings.rag.gate.threshold,
        "prompt_variant": settings.rag.prompt_variant,
        "llm_chain": list(settings.llm.chain),
        "followup_mode": settings.rag.followup_mode,
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    pipeline = make_pipeline(settings, log=InteractionLog(OUT / "logs"))
    items = load_items()
    with runs.open("a", encoding="utf-8") as f:
        for it in items:
            key = f"{it['set']}:{it['qid']}"
            if key in done:
                continue
            gold = [c for c in it["key"]["chunk_gold"].split("|") if c]
            prev_q = None
            history: list[Turn] = []
            if it["prev_qid"]:
                prev_q = scrub_pii(next(x["question"] for x in items if x["qid"] == it["prev_qid"]))
                prev_ans = done.get(f"{it['set']}:{it['prev_qid']}", {}).get("answer", "")
                history = [Turn(prev_q, prev_ans)]
            pool = pipeline.followup.search(scrub_pii(it["question"]), prev_q, POOL).hits
            ranked = [h.chunk.chunk_id for h in pool]
            ranks = [ranked.index(c) + 1 for c in gold if c in ranked]
            for attempt in range(args.retries + 1):
                time.sleep(args.sleep)
                final, rec = pipeline.run(it["question"], history, session_id=f"v2base-{key}")
                if final.status != "unavailable":
                    break
            row = {
                "set": it["set"],
                "qid": it["qid"],
                "question": it["question"],
                "prev_qid": it["prev_qid"],
                "jenis": it["key"]["jenis"],
                "gold": gold,
                "gold_rank": min(ranks) if ranks else None,
                "top20": ranked[:20],
                "final_status": final.status,
                "llm_status": rec.llm_status,
                "llm_provider": rec.llm_provider,
                "error_code": rec.error_code,
                "gate": rec.gate,
                "dense_at_1": rec.gate.get("score"),
                "top5": [
                    {"chunk_id": r["chunk_id"], "score": r["score"], "ranks": r["ranks"]}
                    for r in rec.retrieved
                ],
                "citations": list(rec.citations),
                "fact_check": rec.fact_check,
                "answer": rec.answer,
                "attempts": attempt + 1,
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            done[key] = row
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(key, row["final_status"], row["gold_rank"], flush=True)
    print("selesai", len(done))
    return 0


if __name__ == "__main__":
    sys.exit(main())
