"""E-04: banding dua model dari per_question.csv dua run eval generation (offline, tanpa API).

Pakai:
  python scripts/compare_models.py RUN_A RUN_B --labels 20b 120b --thresholds 0.55 \
      --out-dir results/E-04 --prefix compare-dev-v2 [--notes results/E-04/compare-dev-v2-notes.csv]

Ambang null selalu dihitung; --thresholds menambah ambang lain. Status pada ambang t mengikuti
ScoreThresholdGate: gate_score < t -> refused_gate, selain itu final_status_check_on (cek angka on).

Aturan nilai pra-registrasi:
- answerable/followup benar (1) bila answered;
- out_of_kb benar (1) bila refused_*;
- false_premise: false_premise = terbaik, refused_* = aman, selain itu gagal.

Keluaran: <prefix>.csv (satu baris per pertanyaan) dan <prefix>-summary.csv (per model x ambang).
--notes: CSV berkolom id,catatan; bila diberikan, kolom catatan ditambahkan di <prefix>.csv.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ANSWER_TYPES = ("answerable", "followup")


def load_run(run_dir: Path) -> dict[str, dict[str, str]]:
    with open(run_dir / "per_question.csv", encoding="utf-8-sig") as f:
        return {r["qid"]: r for r in csv.DictReader(f)}


def status_at(row: dict[str, str], threshold: float | None) -> str:
    if threshold is not None and float(row["gate_score"]) < threshold:
        return "refused_gate"
    return row["final_status_check_on"]


def score(row: dict[str, str], status: str) -> str:
    kind = row["type"]
    if kind in ANSWER_TYPES:
        return "1" if status == "answered" else "0"
    if kind == "out_of_kb":
        return "1" if status.startswith("refused_") else "0"
    if kind == "false_premise":
        if status == "false_premise":
            return "terbaik"
        return "aman" if status.startswith("refused_") else "gagal"
    return ""


def percentile(values: list[float], p: float) -> float:
    """Interpolasi linear antartitik terurut (sama dengan numpy.percentile bawaan)."""
    xs = sorted(values)
    pos = (len(xs) - 1) * p / 100
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _suffix(threshold: float | None) -> str:
    return "" if threshold is None else "_g" + f"{threshold:.2f}".replace(".", "")


def per_question(
    runs: dict[str, dict[str, dict[str, str]]],
    thresholds: list[float | None],
    notes: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    labels = list(runs)
    ids = list(runs[labels[0]])
    for label in labels[1:]:
        if list(runs[label]) != ids:
            raise ValueError(f"qid atau urutannya berbeda antara {labels[0]} dan {label}")
    rows = []
    for q in ids:
        base = runs[labels[0]][q]
        row = {"id": q, "kategori": base["type"], "oos_level": base["oos_level"]}
        for t in thresholds:
            sfx = _suffix(t)
            for label in labels:
                row[f"status_{label}{sfx}"] = status_at(runs[label][q], t)
            for label in labels:
                row[f"benar_{label}{sfx}"] = score(runs[label][q], row[f"status_{label}{sfx}"])
        if notes is not None:
            row["catatan"] = notes.get(q, "")
        rows.append(row)
    return rows


def summary(
    runs: dict[str, dict[str, dict[str, str]]], thresholds: list[float | None]
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for label, run in runs.items():
        rs = list(run.values())
        for t in thresholds:
            st = {r["qid"]: status_at(r, t) for r in rs}
            ans = [r for r in rs if r["type"] in ANSWER_TYPES]
            fr = sum(st[r["qid"]] != "answered" for r in ans)
            oos = [r for r in rs if r["type"] == "out_of_kb"]
            jauh = [r for r in oos if r["oos_level"] == "jauh"]
            dekat = [r for r in oos if r["oos_level"] == "dekat"]

            def rejected(xs: list[dict[str, str]], st: dict[str, str] = st) -> int:
                return sum(st[r["qid"]].startswith("refused_") for r in xs)

            fp = [score(r, st[r["qid"]]) for r in rs if r["type"] == "false_premise"]
            # token dan latensi hanya dari pertanyaan yang benar-benar memanggil LLM
            called = [r for r in rs if st[r["qid"]] != "refused_gate"]
            lat = [float(r["llm_latency_s"]) for r in called if r["llm_latency_s"]]
            ptok = sum(int(r["prompt_tokens"] or 0) for r in called)
            ctok = sum(int(r["completion_tokens"] or 0) for r in called)
            out.append(
                {
                    "model": label,
                    "threshold": "null" if t is None else f"{t:.2f}",
                    "fact_check": "on",
                    "salah_tolak": f"{fr}/{len(ans)}",
                    "salah_tolak_rate": f"{fr / len(ans):.4f}" if ans else "",
                    "tolak_benar": f"{rejected(oos)}/{len(oos)}",
                    "tolak_benar_jauh": f"{rejected(jauh)}/{len(jauh)}",
                    "tolak_benar_dekat": f"{rejected(dekat)}/{len(dekat)}",
                    "premis_terbaik": fp.count("terbaik"),
                    "premis_aman": fp.count("aman"),
                    "premis_gagal": fp.count("gagal"),
                    "gagal_skema": sum(r["error_code"] == "LLM_BAD_OUTPUT" for r in called),
                    "unavailable": sum(r["error_code"] == "LLM_UNAVAILABLE" for r in called),
                    "llm_dipanggil": len(called),
                    "prompt_tokens": ptok,
                    "completion_tokens": ctok,
                    "total_tokens": ptok + ctok,
                    "llm_latency_p50_s": f"{percentile(lat, 50):.3f}" if lat else "",
                    "llm_latency_p95_s": f"{percentile(lat, 95):.3f}" if lat else "",
                }
            )
    return out


def differing(
    runs: dict[str, dict[str, dict[str, str]]], threshold: float | None
) -> list[tuple[str, dict[str, str]]]:
    labels = list(runs)
    result = []
    for q in runs[labels[0]]:
        if len({status_at(runs[label][q], threshold) for label in labels}) > 1:
            result.append((q, {label: runs[label][q]["answer"] for label in labels}))
    return result


def _write(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def load_notes(path: Path) -> dict[str, str]:
    with open(path, encoding="utf-8-sig") as f:
        return {r["id"]: r["catatan"] for r in csv.DictReader(f)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_a", type=Path)
    ap.add_argument("run_b", type=Path)
    ap.add_argument("--labels", nargs=2, required=True, metavar=("A", "B"))
    ap.add_argument("--thresholds", nargs="*", type=float, default=[])
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--notes", type=Path)
    args = ap.parse_args(argv)

    runs = {args.labels[0]: load_run(args.run_a), args.labels[1]: load_run(args.run_b)}
    thresholds: list[float | None] = [None, *args.thresholds]
    notes = load_notes(args.notes) if args.notes else None
    _write(args.out_dir / f"{args.prefix}.csv", per_question(runs, thresholds, notes))
    summ = summary(runs, thresholds)
    _write(args.out_dir / f"{args.prefix}-summary.csv", summ)

    for s in summ:
        print(s)
    for t in thresholds:
        print(f"\nBERBEDA (ambang {'null' if t is None else f'{t:.2f}'}):")
        for q, answers in differing(runs, t):
            print(f"{q}: " + " | ".join(f"{k}: {v}" for k, v in answers.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
