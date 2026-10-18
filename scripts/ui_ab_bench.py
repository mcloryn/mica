"""A/B gaya UI web (Langkah 37b): file statis versi sebelum (ref git) vs versi sekarang.

python scripts/ui_ab_bench.py --before db85a13 [--reps 10] [--out results/ADR-19]

Bench tahap 1 yang sama (ui_bench.run_once: Edge kiosk, diam 60 s lalu 20 pertanyaan, pekerja
dan pipeline palsu, AC wajib), ui.camera_preview off, selang-seling sebelum, sesudah, ... Versi
sebelum dilayani dari salinan static di folder hasil (--static-dir; server dan logika sama).
Aturan putaran 2 (docs/UI-WEB.md): metrik "naik" bila median sesudah > maksimum sebelum, "turun"
bila median sesudah < median sebelum. Tujuan: memastikan RAM dan CPU diam tidak naik.
Hasil: <out>/ui-37b-<cap waktu>/ (per_run.csv, summary.csv, comparison.md, run.json).
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_bench

ROOT = Path(__file__).resolve().parents[1]
STATIC = "src/mica/webui/static"
METRICS = ("uss_idle_mb", "cpu_idle_pct", "startup_s", "lat_p95_ms")


def export_static(ref: str, out: Path) -> list[str]:
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref, STATIC], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()  # fmt: skip
    for name in names:
        data = subprocess.run(["git", "show", f"{ref}:{name}"], cwd=ROOT, capture_output=True,
                              check=True).stdout  # fmt: skip
        target = out / Path(name).relative_to(STATIC)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return names


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"n_runs": len(runs)}
    for m in METRICS:
        xs = [r[m] for r in runs if r[m] is not None]
        out[f"{m}_median"] = statistics.median(xs)
        out[f"{m}_min"], out[f"{m}_max"] = min(xs), max(xs)
    out["n_unacked"] = sum(r["n_unacked"] for r in runs)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/ui_ab_bench.py")
    parser.add_argument("--before", required=True, help="ref git versi sebelum, mis. db85a13")
    parser.add_argument("--reps", type=int, default=10)
    parser.add_argument("--config", type=Path, default=ROOT / "config/dev.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "results/ADR-19")
    args = parser.parse_args(argv)
    from mica.eval.environment import collect_environment

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    run_dir = args.out / f"ui-37b-{stamp}"
    run_dir.mkdir(parents=True)
    static_before = run_dir / "static-before"
    files = export_static(args.before, static_before)
    raw = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    raw["ui"]["camera_preview"] = "off"
    config = run_dir / "config.yaml"
    config.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    ui_bench.require_ac()
    extra = {"sebelum": ("--static-dir", str(static_before)), "sesudah": ()}
    runs: dict[str, list[dict[str, Any]]] = {"sebelum": [], "sesudah": []}
    order = 0
    for rep in range(1, args.reps + 1):
        for cond in ("sebelum", "sesudah"):
            order += 1
            r = ui_bench.run_once("web", rep, config, child_extra=extra[cond])
            r.update(order=order, condition=cond)
            runs[cond].append(r)
            print(f"{order:>2} {cond} #{rep}: USS diam {r['uss_idle_mb']:.1f} MB | CPU diam "
                  f"{r['cpu_idle_pct']:.2f}% | mulai {r['startup_s']:.2f} s | p95 "
                  f"{r['lat_p95_ms']:.2f} ms | {r['power_source']}", flush=True)  # fmt: skip
    fields = ["order", "condition", "rep", "startup_s", "uss_idle_mb", "uss_after_mb",
              "cpu_idle_pct", "n_processes_idle", "n_updates", "n_unacked", "lat_p50_ms",
              "lat_p95_ms", "power_source", "battery_percent"]  # fmt: skip
    with (run_dir / "per_run.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(runs["sebelum"] + runs["sesudah"], key=lambda r: r["order"]))
    summary = {c: summarize(rs) for c, rs in runs.items()}
    with (run_dir / "summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["condition", *summary["sebelum"]])
        w.writeheader()
        for c, s in summary.items():
            w.writerow({"condition": c, **s})
    verdicts = {}
    lines = ["# Langkah 37b: A/B gaya UI web (pratinjau off)", "",
             (f"Sebelum = static {args.before}; sesudah = pohon kerja sekarang; {args.reps} "
             "ulangan per kondisi, selang-seling, daya AC. Aturan putaran 2."), "",
             "| metrik | sebelum median | sebelum maks | sesudah median | hasil |",
             "| --- | --- | --- | --- | --- |"]  # fmt: skip
    for m in METRICS:
        b, a = summary["sebelum"], summary["sesudah"]
        med = a[f"{m}_median"]
        v = "naik" if med > b[f"{m}_max"] else ("turun" if med < b[f"{m}_median"] else "tetap")
        verdicts[m] = v
        lines.append(f"| {m} | {b[f'{m}_median']:.3f} | {b[f'{m}_max']:.3f} | {med:.3f} | {v} |")
    ok = verdicts["uss_idle_mb"] != "naik" and verdicts["cpu_idle_pct"] != "naik"
    lines += [
        "",
        "RAM dan CPU diam tidak naik." if ok else "RAM atau CPU diam NAIK: cari penyebab.",
    ]
    (run_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps({
        "step": "Langkah 37b", "before_ref": args.before, "static_before_files": files,
        "reps": args.reps, "camera_preview": "off", "summary": summary, "verdicts": verdicts,
        "environment": collect_environment(),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # fmt: skip
    print((run_dir / "comparison.md").read_text(encoding="utf-8"))
    print(f"tersimpan: {run_dir.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
