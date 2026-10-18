"""Ukur ulang UI kiosk baru (Langkah 37): kondisi 1 vs baseline putaran 2, kondisi 2 vs kondisi 1.

python scripts/ui_preview_bench.py [--reps 10] [--out results/ADR-19]

- Kondisi 1 (c1): desain baru, ui.camera_preview off, pekerja dan pipeline palsu.
- Kondisi 2 (c2): desain baru, ui.camera_preview public pada ui.preview_fps nilai coba, dengan
  proses kamera asli + sumber gambar palsu (mica.vision.fakesource; detektor palsu, tanpa YOLO).
- Bench tahap 1 yang sama (ui_bench.run_once: Edge kiosk, diam 60 s lalu 20 pertanyaan, AC
  wajib), selang-seling c1, c2, c1, c2, ... sebanyak --reps per kondisi.
- Aturan putaran 2 (docs/UI-WEB.md): metrik c1 "naik" bila median c1 > maksimum baseline
  (results/ADR-19/ui-opt2-combo-20261018-042512, baris k1+k2 = konfigurasi master saat itu).
  Metrik: RAM USS diam, CPU diam, waktu mulai, p95 jeda. c2 vs c1 dilaporkan apa adanya
  (selisih median, per jenis proses); keputusan akhir di E-09 (amandemen 1).
Hasil: <out>/ui-l37-<cap waktu>/ (per_run.csv, by_kind.csv, summary.csv, comparison.md, run.json,
config-c1.yaml, config-c2.yaml).
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_bench

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "results/ADR-19/ui-opt2-combo-20261018-042512/summary.csv"
BASELINE_ROW = "k1+k2"  # dipertahankan di putaran 2, jadi konfigurasi master
METRICS = ("uss_idle_mb", "cpu_idle_pct", "startup_s", "lat_p95_ms")
TARGETS = ("uss_idle_mb", "cpu_idle_pct")  # bila naik: cari penyebab di desain baru


def write_config(base: Path, out: Path, preview: str) -> Path:
    raw = yaml.safe_load(base.read_text(encoding="utf-8"))
    raw["ui"]["camera_preview"] = preview
    out.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out


def baseline() -> dict[str, float]:
    with BASELINE.open(encoding="utf-8-sig") as f:
        row = next(r for r in csv.DictReader(f) if r["condition"] == BASELINE_ROW)
    return {k: float(v) for k, v in row.items() if k not in ("condition",) and v}


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"n_runs": len(runs)}
    for m in METRICS:
        xs = [r[m] for r in runs if r[m] is not None]
        out[f"{m}_median"] = statistics.median(xs) if xs else None
        out[f"{m}_min"] = min(xs) if xs else None
        out[f"{m}_max"] = max(xs) if xs else None
    out["n_unacked"] = sum(r["n_unacked"] for r in runs)
    return out


def kinds_median(runs: list[dict[str, Any]], key: str) -> dict[str, float]:
    kinds = sorted({k for r in runs for k in r[key]})
    return {k: statistics.median(r[key].get(k, 0.0) for r in runs) for k in kinds}


def compare_baseline(c1: dict[str, Any], base: dict[str, float]) -> list[tuple[str, str]]:
    rows = []
    for m in METRICS:
        med, bmax, bmed = c1[f"{m}_median"], base[f"{m}_max"], base[f"{m}_median"]
        verdict = "naik" if med > bmax else ("turun" if med < bmed else "tetap")
        rows.append((m, f"{med:.3f} vs baseline median {bmed:.3f} / maks {bmax:.3f}: {verdict}"))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/ui_preview_bench.py")
    parser.add_argument("--reps", type=int, default=10)
    parser.add_argument("--config", type=Path, default=ROOT / "config/dev.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "results/ADR-19")
    parser.add_argument("--name", default="ui-l37")
    args = parser.parse_args(argv)
    from mica.config import load_settings
    from mica.eval.environment import collect_environment

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    run_dir = args.out / f"{args.name}-{stamp}"
    run_dir.mkdir(parents=True)
    configs = {"c1": write_config(args.config, run_dir / "config-c1.yaml", "off"),
               "c2": write_config(args.config, run_dir / "config-c2.yaml", "public")}  # fmt: skip
    extra = {"c1": (), "c2": ("--fake-camera",)}
    settings = load_settings(configs["c2"])
    ui_bench.require_ac()
    runs: dict[str, list[dict[str, Any]]] = {"c1": [], "c2": []}
    order = 0
    for rep in range(1, args.reps + 1):
        for cond in ("c1", "c2"):
            order += 1
            r = ui_bench.run_once("web", rep, configs[cond], child_extra=extra[cond])
            r.update(order=order, condition=cond)
            runs[cond].append(r)
            print(f"{order:>2} {cond} #{rep}: mulai {r['startup_s']:.2f} s | USS diam "
                  f"{r['uss_idle_mb']:.1f} MB | CPU diam {r['cpu_idle_pct']:.2f}% | p95 "
                  f"{r['lat_p95_ms']:.2f} ms | {r['power_source']}", flush=True)  # fmt: skip
    all_runs = runs["c1"] + runs["c2"]
    fields = ["order", "condition", "rep", "startup_s", "uss_idle_mb", "uss_after_mb",
              "cpu_idle_pct", "n_processes_idle", "n_updates", "n_unacked", "lat_p50_ms",
              "lat_p95_ms", "power_source", "battery_percent"]  # fmt: skip
    with (run_dir / "per_run.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(all_runs, key=lambda r: r["order"]))
    with (run_dir / "by_kind.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order", "condition", "kind", "cpu_idle_pct", "uss_idle_mb"])
        for r in sorted(all_runs, key=lambda r: r["order"]):
            for k in sorted(set(r["_cpu_by_kind"]) | set(r["_uss_by_kind"])):
                w.writerow([r["order"], r["condition"], k, r["_cpu_by_kind"].get(k, 0.0),
                            r["_uss_by_kind"].get(k, 0.0)])  # fmt: skip
    summary = {c: summarize(rs) for c, rs in runs.items()}
    with (run_dir / "summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["condition", *summary["c1"]])
        w.writeheader()
        for c, s in summary.items():
            w.writerow({"condition": c, **s})
    base = baseline()
    c1_vs_base = compare_baseline(summary["c1"], base)
    deltas = {m: summary["c2"][f"{m}_median"] - summary["c1"][f"{m}_median"] for m in METRICS}
    kinds = {c: {"cpu": kinds_median(rs, "_cpu_by_kind"), "uss": kinds_median(rs, "_uss_by_kind")}
             for c, rs in runs.items()}  # fmt: skip
    raised = [m for m, text in c1_vs_base if m in TARGETS and text.endswith("naik")]
    lines = ["# Langkah 37: ukur ulang UI kiosk", "",
             (f"Baseline: {BASELINE.relative_to(ROOT).as_posix()} baris {BASELINE_ROW}; "
             f"{args.reps} ulangan per kondisi, selang-seling, daya AC."), "",
             "## Kondisi 1 (desain baru, pratinjau off) vs baseline", ""]  # fmt: skip
    lines += [f"- {m}: {text}" for m, text in c1_vs_base]
    lines += ["", ("RAM/CPU diam c1 naik di atas maksimum baseline: " + ", ".join(raised)
                   + " -> cari penyebab di desain baru") if raised
              else "RAM dan CPU diam c1 tidak di atas maksimum baseline.", "",
              "## Kondisi 2 (pratinjau public, sumber palsu) vs kondisi 1", ""]  # fmt: skip
    lines += [f"- {m}: c2 {summary['c2'][f'{m}_median']:.3f} - c1 "
              f"{summary['c1'][f'{m}_median']:.3f} = {d:+.3f}" for m, d in deltas.items()]  # fmt: skip
    lines += [
        "",
        "Median per jenis proses (CPU diam %, USS diam MB):",
        "",
        "| jenis | c1 CPU | c2 CPU | c1 USS | c2 USS |",
        "| --- | --- | --- | --- | --- |",
    ]
    for k in sorted(set(kinds["c1"]["cpu"]) | set(kinds["c2"]["cpu"])):
        lines.append(f"| {k} | {kinds['c1']['cpu'].get(k, 0):.2f} | {kinds['c2']['cpu'].get(k, 0):.2f}"
                     f" | {kinds['c1']['uss'].get(k, 0):.1f} | {kinds['c2']['uss'].get(k, 0):.1f} |")  # fmt: skip
    lines += ["", "Keputusan akhir pratinjau public ada di E-09 (docs/E-09.md, amandemen 1)."]
    (run_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps({
        "step": "Langkah 37", "reps": args.reps, "order": "selang-seling c1, c2",
        "conditions": {"c1": "camera_preview off, FakeWorkerBus, FakePipeline",
                       "c2": "camera_preview public, preview_fps "
                       f"{settings.ui.preview_fps}, pixel_block {settings.ui.preview_pixel_block} "
                       "(nilai coba desain), proses kamera asli + sumber dan detektor palsu"},
        "baseline": {"path": BASELINE.relative_to(ROOT).as_posix(), "row": BASELINE_ROW, **base},
        "summary": summary, "c1_vs_baseline": dict(c1_vs_base), "c2_minus_c1_median": deltas,
        "by_kind_median": kinds, "environment": collect_environment(),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # fmt: skip
    print((run_dir / "comparison.md").read_text(encoding="utf-8"))
    print(f"tersimpan: {run_dir.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
