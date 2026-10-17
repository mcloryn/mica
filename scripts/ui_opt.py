"""Optimasi switch Edge satu per satu (Langkah 31 bagian C), keputusan mekanis.

python scripts/ui_opt.py --before <folder summary bench sebelum> [--out results/ADR-19]
                         --candidate=--switch [--candidate=--switch ...]

Setiap kandidat diukur dengan bench tahap 1 (scripts/ui_bench.py --ui web --reps 3, median,
daya AC) di atas switch yang sudah dipertahankan (lewat --edge-extra, tanpa mengubah kode
aplikasi). Aturan, ditetapkan sebelum mengukur:
- dipertahankan HANYA bila median CPU diam ATAU median RAM USS diam turun, metrik lain tidak
  naik (waktu mulai, RAM USS diam, RAM USS setelah 20 pertanyaan, CPU diam, jeda p50, jeda
  p95; semuanya median/persentil 3 ulangan), tes UI web lulus, dan aturan (a) tahap 1 lulus
  (keputusan bench LOLOS);
- selain itu dibatalkan; pembanding kandidat berikutnya tetap kondisi terakhir yang
  dipertahankan.
Hasil: results/ADR-19/ui-opt-<cap waktu>/changes.csv (+ folder bench setiap kandidat).
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

BENCH = Path(__file__).with_name("ui_bench.py")
METRICS = ("startup_median_s", "uss_idle_median_mb", "uss_after_median_mb",
           "cpu_idle_median_pct", "lat_p50_s", "lat_p95_s")  # fmt: skip
TARGETS = ("cpu_idle_median_pct", "uss_idle_median_mb")


def read_summary(folder: Path) -> dict[str, Any]:
    with (folder / "summary.csv").open(encoding="utf-8-sig") as f:
        row = next(r for r in csv.DictReader(f) if r["ui"] == "web")
    out: dict[str, Any] = {k: float(row[k]) for k in METRICS}
    out["verdict"] = row["keputusan_tahap1"]
    out["folder"] = folder.as_posix()
    return out


def decide(before: dict[str, Any], after: dict[str, Any]) -> tuple[bool, str]:
    reasons = []
    improved = [m for m in TARGETS if after[m] < before[m]]
    if not improved:
        reasons.append("CPU diam dan RAM USS diam tidak turun")
    worse = [m for m in METRICS if after[m] > before[m]]
    if worse:
        reasons.append("naik: " + ", ".join(worse))
    if after["verdict"] != "LOLOS":
        reasons.append(f"tahap 1: {after['verdict']}")
    if reasons:
        return False, "; ".join(reasons)
    return True, "turun: " + ", ".join(improved) + "; metrik lain tidak naik; tahap 1 LOLOS"


def run_bench(extra: list[str], out: Path, name: str) -> Path | None:
    cmd = [sys.executable, str(BENCH), "--ui", "web", "--reps", "3", "--out", str(out),
           "--name", name, *(f"--edge-extra={x}" for x in extra)]  # fmt: skip
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, encoding="utf-8")
    print(proc.stdout[-600:], proc.stderr[-400:], flush=True)
    if proc.returncode != 0:
        return None
    line = next(x for x in reversed(proc.stdout.splitlines()) if x.startswith("tersimpan: "))
    return Path(line.removeprefix("tersimpan: ").strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/ui_opt.py")
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("results/ADR-19"))
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--kept", action="append", default=[],
                        help="switch yang sudah dipertahankan sebelumnya")  # fmt: skip
    args = parser.parse_args(argv)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    out = args.out / f"ui-opt-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    before = read_summary(args.before)
    kept: list[str] = list(args.kept)
    rows = []
    fields = ["no", "change", "kept_before", *(f"{m}_before" for m in METRICS),
              *(f"{m}_after" for m in METRICS), "verdict_after", "decision", "reason",
              "before_folder", "after_folder"]  # fmt: skip
    for i, cand in enumerate(args.candidate, 1):
        print(f"[{i}] {cand} (di atas {kept or 'tanpa tambahan'})", flush=True)
        folder = run_bench([*kept, cand], out, f"{i:02d}")
        if folder is None:
            row = {"no": i, "change": cand, "kept_before": " ".join(kept),
                   "decision": "BERHENTI", "reason": "bench gagal (mis. tidak AC)"}  # fmt: skip
            rows.append(row)
            break
        after = read_summary(folder)
        keep, reason = decide(before, after)
        row = {"no": i, "change": cand, "kept_before": " ".join(kept),
               **{f"{m}_before": before[m] for m in METRICS},
               **{f"{m}_after": after[m] for m in METRICS},
               "verdict_after": after["verdict"],
               "decision": "DIPERTAHANKAN" if keep else "DIBATALKAN", "reason": reason,
               "before_folder": before["folder"], "after_folder": after["folder"]}  # fmt: skip
        rows.append(row)
        print(f"  -> {row['decision']}: {reason}", flush=True)
        if keep:
            kept.append(cand)
            before = after
        with (out / "changes.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    with (out / "changes.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"dipertahankan: {kept}")
    print(f"tersimpan: {out.as_posix()}")
    return 0 if all(r["decision"] != "BERHENTI" for r in rows) else 3


if __name__ == "__main__":
    raise SystemExit(main())
