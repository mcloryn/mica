"""V2-3c B: ukur latensi reranker bge-reranker-v2-m3 di CPU (tanpa Groq, config default tidak diubah).

Kondisi: 1 sekarang (bawaan CrossEncoder), 2 max_length=512, 3 = 2 + threads = core fisik,
4 = 3 dengan kandidat 10. Latensi diukur pada 20 kueri dev pertama (rerank saja, kandidat dari
hybrid). Urutan top-5 dan recall@5 dicek pada 68 soal dev v2 jenis ada/sebagian dengan gold,
dibanding run R (eval/dev/v2_3/R.jsonl).

  python scripts/v2_rerank_bench.py --cores 14
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from pathlib import Path

import torch

from mica.config import read_raw, settings_from_raw
from mica.kb.embedder import DEFAULT_CACHE_DIR
from mica.kb.index import DEFAULT_KB_ROOT, load_kb
from mica.rag.pii import scrub_pii
from mica.rag.retriever import embedder_for_kb, make_retriever

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval/dev/v2_3/rerank_bench"
MODEL = "BAAI/bge-reranker-v2-m3"
REV = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, round(p * len(xs)) - 1))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cores", type=int, required=True, help="jumlah core fisik")
    ap.add_argument("--n-latency", type=int, default=20)
    # satu kondisi per proses supaya model reranker (~2,3 GB) tidak menumpuk di memori;
    # hasilnya ditulis ke rerank_bench/cond<N>.json
    ap.add_argument("--cond", type=int, choices=[1, 2, 3, 4], default=None)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    from sentence_transformers import CrossEncoder

    settings = settings_from_raw(read_raw(ROOT / "config/prod.yaml"), ROOT / ".env",
                                 require_complete=False)  # fmt: skip
    kb = load_kb(settings.kb.active_id, DEFAULT_KB_ROOT)
    emb = embedder_for_kb(kb, offline=True)
    emb.load()
    hybrid = make_retriever(settings, kb, embedder_factory=lambda m, r: emb)  # reranker mati

    with (ROOT / "data/eval/dev_v2_kunci.csv").open(encoding="utf-8") as f:
        keys = {r["qid"]: r for r in csv.DictReader(f, delimiter=";")}
    with (ROOT / "data/eval/dev-v2-soal.csv").open(encoding="utf-8") as f:
        soal = list(csv.DictReader(f, delimiter=";"))
    r_top5 = {
        r["qid"]: [h["chunk_id"] for h in r["top5"]]
        for r in map(json.loads, (ROOT / "eval/dev/v2_3/R.jsonl").read_text("utf-8").splitlines())
    }
    gold_q = [
        (s["qid"], s["pertanyaan"], [c for c in keys[s["qid"]]["chunk_gold"].split("|") if c])
        for s in soal
        if keys[s["qid"]]["jenis"] in ("ada", "sebagian") and keys[s["qid"]]["chunk_gold"]
    ]
    lat_q = [(s["qid"], s["pertanyaan"]) for s in soal[: args.n_latency]]

    default_threads = torch.get_num_threads()
    cands = {}
    for qid, q, *_ in [*lat_q, *[(a, b) for a, b, _ in gold_q]]:
        if qid not in cands:
            cands[qid] = hybrid.search(scrub_pii(q), 20)

    conds = [
        {"id": 1, "max_length": None, "threads": default_threads, "pool": 20},
        {"id": 2, "max_length": 512, "threads": default_threads, "pool": 20},
        {"id": 3, "max_length": 512, "threads": args.cores, "pool": 20},
        {"id": 4, "max_length": 512, "threads": args.cores, "pool": 10},
    ]
    results = {"default_threads": default_threads, "physical_cores": args.cores,
               "logical_cores": os.cpu_count(), "conditions": []}  # fmt: skip
    if args.cond is not None:
        conds = [c for c in conds if c["id"] == args.cond]
    for c in conds:
        torch.set_num_threads(c["threads"])
        kw = {"max_length": c["max_length"]} if c["max_length"] else {}
        model = CrossEncoder(MODEL, revision=REV, cache_folder=str(DEFAULT_CACHE_DIR), device="cpu",
                             local_files_only=True, model_kwargs={"use_safetensors": True}, **kw)  # fmt: skip
        tok = model.tokenizer
        eff_max = model.max_length if model.max_length is not None else tok.model_max_length

        def rerank(q: str, hits, model=model):
            pairs = [(q, h.chunk.text) for h in hits]
            t = time.perf_counter()
            scores = model.predict(pairs)  # batch_size bawaan predict = 32
            dt = time.perf_counter() - t
            order = sorted(range(len(hits)), key=lambda i: (-float(scores[i]), i))[:5]
            return [hits[i].chunk.chunk_id for i in order], dt, pairs

        model.predict([("pemanasan", "teks")])  # pemanasan, tidak diukur
        lats, lens, trunc, npairs = [], [], 0, 0
        for qid, q in lat_q:
            hits = cands[qid][: c["pool"]]
            _, dt, pairs = rerank(scrub_pii(q), hits)
            lats.append(dt)
            for a, b in pairs:
                n = len(tok(a, b, truncation=False)["input_ids"])
                lens.append(n)
                trunc += n > 512
                npairs += 1
        hit5 = same = 0
        for qid, q, gold in gold_q:
            top5, _, _ = rerank(scrub_pii(q), cands[qid][: c["pool"]])
            hit5 += any(g in top5 for g in gold)
            same += top5 == r_top5[qid]
        row = {
            **c, "effective_max_length": eff_max, "batch_size": 32,
            "torch_threads_effective": torch.get_num_threads(),
            "p50_s": statistics.median(lats), "p95_s": pct(lats, 0.95), "mean_s": statistics.mean(lats),
            "mean_tokens_per_pair": statistics.mean(lens), "max_tokens_per_pair": max(lens),
            "pairs_over_512": trunc, "pairs": npairs,
            "recall5": hit5, "n_gold": len(gold_q), "top5_same_as_R": same,
        }  # fmt: skip
        results["conditions"].append(row)
        print(json.dumps(row), flush=True)
    name = "results.json" if args.cond is None else f"cond{args.cond}.json"
    (OUT / name).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
