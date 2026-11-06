"""V2-3: run R, V6, V6G di set dev v2 (docs/PRA-REGISTRASI-V2.md bagian 3).

Konfigurasi = config/prod.yaml + override di skrip ini (prod.yaml tidak diubah). Model Hugging
Face dimuat offline (app.mode prod). Hasil per soal ditambahkan ke eval/dev/v2_3/<run>.jsonl
begitu selesai, sehingga run bisa dilanjutkan bila putus.

  python scripts/v2_3_runs.py default   # retrieval config bawaan identik dengan B0 (10 soal)
  python scripts/v2_3_runs.py R         # P1, retrieval saja
  python scripts/v2_3_runs.py V6        # P1 + P2, pipeline penuh
  python scripts/v2_3_runs.py V6G       # P3 diputar ulang atas keluaran LLM V6 yang sama
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

from mica.config import read_raw, settings_from_raw
from mica.core.logging import InteractionLog
from mica.core.types import LlmAnswer, ScoredChunk
from mica.rag.followup import FollowupResult
from mica.rag.pii import scrub_pii
from mica.rag.pipeline import make_pipeline

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval/dev/v2_3"
B0 = ROOT / "eval/dev/v2_baseline/runs.jsonl"
SOAL = ROOT / "data/eval/dev-v2-soal.csv"
KUNCI = ROOT / "data/eval/dev_v2_kunci.csv"
RERANKER_REV = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
POOL = 50

OVERRIDES: dict[str, dict[str, Any]] = {
    "default": {},
    "R": {"rag": {"reranker": {"enabled": True, "revision": RERANKER_REV}}},
    "V6": {
        "rag": {"reranker": {"enabled": True, "revision": RERANKER_REV}, "prompt_variant": "v6"}
    },
    "V6G": {
        "rag": {
            "reranker": {"enabled": True, "revision": RERANKER_REV},
            "prompt_variant": "v6",
            "gate": {"sentence_verify": {"enabled": True, "temperature": 0.0}},
        }
    },
}


def merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        out[k] = merge(out.get(k, {}), v) if isinstance(v, dict) else v
    return out


def settings_for(run: str):
    raw = merge(read_raw(ROOT / "config/prod.yaml"), OVERRIDES[run])
    return settings_from_raw(raw, ROOT / ".env", require_complete=False)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def items() -> list[dict[str, Any]]:
    keys = {r["qid"]: r for r in read_csv(KUNCI)}
    return [
        {"qid": r["qid"], "question": r["pertanyaan"], "jenis": keys[r["qid"]]["jenis"],
         "gold": [c for c in keys[r["qid"]]["chunk_gold"].split("|") if c]}
        for r in read_csv(SOAL)
    ]  # fmt: skip


def done_rows(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {json.loads(x)["qid"]: json.loads(x) for x in path.read_text("utf-8").splitlines() if x}


def hit_dict(h: ScoredChunk) -> dict[str, Any]:
    return {"chunk_id": h.chunk.chunk_id, "score": h.score, "ranks": dict(h.ranks),
            "raw_scores": dict(h.raw_scores)}  # fmt: skip


def retrieval_rows(run: str, only: int | None = None) -> None:
    settings = settings_for(run)
    pipeline = make_pipeline(settings, log=InteractionLog(OUT / f"logs-{run}"))
    path = OUT / f"{run}.jsonl"
    done = done_rows(path)
    k = settings.rag.top_k
    with path.open("a", encoding="utf-8") as f:
        for it in items()[:only] if only else items():
            if it["qid"] in done:
                continue
            q = scrub_pii(it["question"])
            started = time.perf_counter()
            top = pipeline.followup.search(q, None, k).hits
            latency = time.perf_counter() - started
            pool = pipeline.followup.search(q, None, POOL).hits
            ids = [h.chunk.chunk_id for h in pool]
            ranks = [ids.index(c) + 1 for c in it["gold"] if c in ids]
            row = {"qid": it["qid"], "jenis": it["jenis"], "gold": it["gold"],
                   "top5": [hit_dict(h) for h in top], "top20": ids[:20],
                   "gold_rank": min(ranks) if ranks else None, "latency_s": latency}  # fmt: skip
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(run, it["qid"], row["gold_rank"], f"{latency:.2f}s", flush=True)


def check_default() -> int:
    """Retrieval config bawaan (prod tanpa override) harus identik dengan B0 untuk 10 soal."""
    retrieval_rows("default", only=10)
    b0 = {
        r["qid"]: r for r in map(json.loads, B0.read_text("utf-8").splitlines()) if r["set"] == "v2"
    }
    now = done_rows(OUT / "default.jsonl")
    same = 0
    report = []
    for qid, row in now.items():
        a = [(h["chunk_id"], round(h["score"], 12)) for h in row["top5"]]
        b = [(h["chunk_id"], round(h["score"], 12)) for h in b0[qid]["top5"]]
        ok = a == b and abs(row["top5"][0]["raw_scores"]["dense@1"] - b0[qid]["dense_at_1"]) < 1e-9
        same += ok
        report.append({"qid": qid, "identik": ok})
    (OUT / "default_check.json").write_text(json.dumps({"identik": same, "n": len(now),
                                                        "per_soal": report}, indent=2) + "\n",
                                            encoding="utf-8")  # fmt: skip
    print(f"identik {same}/{len(now)}")
    return 0 if same == len(now) else 1


class CaptureLlm:
    """Membungkus rantai LLM: menyimpan keluaran mentah (sebelum validasi/cek) untuk V6G."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.name = getattr(inner, "name", "llm")
        self.last: LlmAnswer | None = None

    def generate(self, request: Any, timeout_s: float) -> LlmAnswer:
        self.last = None
        self.last = self.inner.generate(request, timeout_s)
        return self.last


class CaptureFollowup:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.name = inner.name
        self.last: list[ScoredChunk] = []

    def search(self, question: Any, previous: Any, k: int) -> FollowupResult:
        res = self.inner.search(question, previous, k)
        self.last = list(res.hits)
        return res


def run_v6(sleep: float, retries: int) -> None:
    settings = settings_for("V6")
    pipeline = make_pipeline(settings, log=InteractionLog(OUT / "logs-V6"))
    llm = pipeline.llm = CaptureLlm(pipeline.llm)  # type: ignore[assignment]
    fol = pipeline.followup = CaptureFollowup(pipeline.followup)  # type: ignore[assignment]
    path = OUT / "V6.jsonl"
    done = done_rows(path)
    with path.open("a", encoding="utf-8") as f:
        for it in items():
            if it["qid"] in done:
                continue
            for attempt in range(retries + 1):
                time.sleep(sleep)
                llm.last = None  # tanpa ini, soal yang berhenti di gerbang 1 mewarisi keluaran lama
                final, rec = pipeline.run(it["question"], [], session_id=f"v6-{it['qid']}")
                if final.status != "unavailable":
                    break
            raw = llm.last
            row = row_from(it, final, rec, fol.last, attempt + 1)
            row["llm_raw"] = None if raw is None else {
                "status": raw.status, "answer": raw.answer, "citations": list(raw.citations),
                "provider": raw.provider, "usage": raw.usage,
            }  # fmt: skip
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print("V6", it["qid"], final.status, row["gold_rank"], flush=True)


def row_from(it, final, rec, hits, attempts) -> dict[str, Any]:
    top5 = [hit_dict(h) for h in hits]
    ids = [h["chunk_id"] for h in top5]
    ranks = [ids.index(c) + 1 for c in it["gold"] if c in ids]
    return {
        "qid": it["qid"], "question": it["question"], "jenis": it["jenis"], "gold": it["gold"],
        "gold_rank_top5": min(ranks) if ranks else None, "gold_rank": min(ranks) if ranks else None,
        "final_status": final.status, "llm_status": rec.llm_status, "error_code": rec.error_code,
        "gate": rec.gate, "dense_at_1": rec.gate.get("score"), "top5": top5,
        "citations": list(rec.citations), "fact_check": rec.fact_check, "answer": rec.answer,
        "prompt_version": rec.prompt_version, "attempts": attempts,
    }  # fmt: skip


class ReplayFollowup:
    name = "replay"

    def __init__(self) -> None:
        self.hits: list[ScoredChunk] = []

    def search(self, question: Any, previous: Any, k: int) -> FollowupResult:
        return FollowupResult(list(self.hits), str(question))


class ReplayLlm:
    name = "replay"

    def __init__(self) -> None:
        self.answer: LlmAnswer | None = None

    def generate(self, request: Any, timeout_s: float) -> LlmAnswer:
        assert self.answer is not None
        return self.answer


def run_v6g(sleep: float, retries: int) -> None:
    """Pipeline V6G asli (verifikator Groq + cek angka) atas retrieval + keluaran LLM V6."""
    settings = settings_for("V6G")
    pipeline = make_pipeline(settings, log=InteractionLog(OUT / "logs-V6G"))
    kb = {c.chunk_id: c for c in pipeline.retriever.inner.base.chunks}  # type: ignore[attr-defined]
    rep_f, rep_l = ReplayFollowup(), ReplayLlm()
    pipeline.followup, pipeline.llm = rep_f, rep_l  # type: ignore[assignment]
    v6 = done_rows(OUT / "V6.jsonl")
    path = OUT / "V6G.jsonl"
    done = done_rows(path)
    with path.open("a", encoding="utf-8") as f:
        for it in items():
            if it["qid"] in done:
                continue
            src = v6[it["qid"]]
            rep_f.hits = [
                ScoredChunk(kb[h["chunk_id"]], h["score"], h["ranks"], h["raw_scores"])
                for h in src["top5"]
            ]
            # baris refused_gate V6: LLM tidak dipanggil (llm_raw di sana sisa soal sebelumnya)
            raw = None if src["final_status"] == "refused_gate" else src["llm_raw"]
            rep_l.answer = None if raw is None else LlmAnswer(
                raw["status"], raw["answer"], tuple(raw["citations"]), raw["provider"], 0.0,
                raw["usage"],
            )  # fmt: skip
            calls_verifier = raw is not None and raw["status"] != "not_found"
            if raw is None:  # V6 tidak memanggil LLM (gerbang 1) atau LLM gagal: salin
                row = {**src, "replayed": False}
            else:
                for attempt in range(retries + 1):
                    if calls_verifier:
                        time.sleep(sleep * (attempt + 1))
                    final, rec = pipeline.run(it["question"], [], session_id=f"v6g-{it['qid']}")
                    err = (rec.fact_check.get("sentence_verify") or {}).get("error") or ""
                    # 429/timeout = batas Groq (8.000 token/menit), bukan putusan verifikator
                    if not err.startswith(("HTTP 429", "timeout")):
                        break
                else:  # kuota Groq habis: berhenti tanpa menulis baris (run bisa dilanjutkan)
                    print("V6G berhenti: verifikator tetap", err, "di", it["qid"], flush=True)
                    return
                row = row_from(it, final, rec, rep_f.hits, attempt + 1)
                row["llm_raw"] = raw
                row["replayed"] = True
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print("V6G", it["qid"], row["final_status"], flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", choices=["default", "R", "V6", "V6G"])
    ap.add_argument("--sleep", type=float, default=20.0)
    ap.add_argument("--retries", type=int, default=3)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    meta_path = OUT / "meta.json"
    meta = json.loads(meta_path.read_text("utf-8")) if meta_path.exists() else {}
    s = settings_for(args.run)
    meta[args.run] = {"overrides": OVERRIDES[args.run], "config_hash": s.config_hash(),
                      "kb_id": s.kb.active_id, "llm_chain": list(s.llm.chain)}  # fmt: skip
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    if args.run == "default":
        return check_default()
    if args.run == "R":
        retrieval_rows("R")
    elif args.run == "V6":
        run_v6(args.sleep, args.retries)
    else:
        run_v6g(args.sleep, args.retries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
