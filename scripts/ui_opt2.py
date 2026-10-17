"""Optimasi UI web putaran 2 (docs/UI-WEB.md, "Optimasi putaran 2"), keputusan mekanis.

python scripts/ui_opt2.py [--reps 10] [--out results/ADR-19] [--combo]

Kondisi diukur selang-seling (baseline, k1, k2, baseline, k1, k2, ...) dengan bench tahap 1
(ui_bench.run_once: pekerja dan pipeline palsu, Edge kiosk, AC wajib). Baseline = konfigurasi
master (mica.webui.browser); kandidat ditambahkan lewat --edge-extra. --combo: baseline vs
k1+k2 (hanya bila kedua kandidat lolos).
Aturan (ditetapkan sebelum data):
- metrik "naik" bila median kandidat > maksimum baseline; "turun" bila median kandidat <
  median baseline; metrik per ulangan: RAM USS diam, CPU diam, waktu mulai, p95 jeda;
- dipertahankan bila RAM USS diam ATAU CPU diam turun, tidak ada metrik yang naik, dan tes UI
  web + aturan (a) tahap 1 lulus.
Hasil: results/ADR-19/ui-opt2-<cap waktu>/ (per_run.csv, summary.csv, changes.csv, run.json).
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_bench

K1 = "--disable-component-extensions-with-background-pages"
K2 = "--renderer-process-limit=1"  # nilai sama dengan putaran 1
METRICS = ("uss_idle_mb", "cpu_idle_pct", "startup_s", "lat_p95_ms")
TARGETS = ("uss_idle_mb", "cpu_idle_pct")


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"n_runs": len(runs)}
    for m in METRICS:
        xs = [r[m] for r in runs if r[m] is not None]
        out[f"{m}_median"] = statistics.median(xs) if xs else None
        out[f"{m}_min"] = min(xs) if xs else None
        out[f"{m}_max"] = max(xs) if xs else None
    out["n_unacked"] = sum(r["n_unacked"] for r in runs)
    return out


def functional(runs: list[dict[str, Any]], tests_ok: bool, fullscreen: bool) -> dict[str, bool]:
    """Aturan (a) tahap 1, bagian yang dibuktikan tes dan run (sama dengan ui_bench)."""
    return {
        "tes UI web lulus": tests_ok,
        "Edge kiosk layar penuh": fullscreen,
        "layar pertama tampil di setiap ulangan": all(r["startup_s"] > 0 for r in runs),
        "20 pertanyaan terjawab tampil di setiap ulangan": all(r["n_updates"] > 0 for r in runs),
        "setiap pembaruan di-ack browser": all(r["n_unacked"] == 0 for r in runs),
    }


def decide(base: dict[str, Any], cand: dict[str, Any], func: dict[str, bool]) -> tuple[bool, str]:
    down = [m for m in TARGETS if cand[f"{m}_median"] < base[f"{m}_median"]]
    up = [m for m in METRICS if cand[f"{m}_median"] > base[f"{m}_max"]]
    reasons = []
    if not down:
        reasons.append("RAM USS diam dan CPU diam tidak turun")
    if up:
        reasons.append("naik (median > maks baseline): " + ", ".join(up))
    failed = [k for k, ok in func.items() if not ok]
    if failed:
        reasons.append("(a) gagal: " + "; ".join(failed))
    if reasons:
        return False, "; ".join(reasons)
    return True, "turun: " + ", ".join(down) + "; tidak ada metrik naik; tes dan (a) lulus"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/ui_opt2.py")
    parser.add_argument("--config", type=Path, default=Path("config/dev.yaml"))
    parser.add_argument("--reps", type=int, default=10)
    parser.add_argument("--out", type=Path, default=Path("results/ADR-19"))
    parser.add_argument("--combo", action="store_true", help="baseline vs k1+k2")
    args = parser.parse_args(argv)

    from mica.config import load_settings
    from mica.eval.environment import collect_environment
    from mica.kb.index import package_version
    from mica.webui.browser import IDLE_SWITCHES, RENDERING_SWITCHES, find_edge

    settings = load_settings(args.config)
    conditions: dict[str, tuple[str, ...]] = (
        {"baseline": (), "k1+k2": (K1, K2)} if args.combo
        else {"baseline": (), "k1": (K1,), "k2": (K2,)}
    )  # fmt: skip
    try:
        ui_bench.require_ac()
        environment = collect_environment()
        tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/unit/test_webui.py"],
                               check=False, capture_output=True, text=True)  # fmt: skip
        tests_line = (tests.stdout.strip().splitlines() or ["-"])[-1]
        print(f"tes UI web: {tests_line}", flush=True)
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        out = args.out / f"ui-opt2{'-combo' if args.combo else ''}-{stamp}"
        out.mkdir(parents=True, exist_ok=False)
        runs: list[dict[str, Any]] = []
        order = 0
        for rep in range(1, args.reps + 1):
            for cond, extra in conditions.items():
                order += 1
                print(f"[{order}] {cond} ulangan {rep} ...", flush=True)
                r = ui_bench.run_once("web", rep, args.config, edge_extra=extra)
                r = {"order": order, "condition": cond, "edge_extra": " ".join(extra), **r}
                runs.append(r)
                print(f"  USS diam {r['uss_idle_mb']:.1f} MB | CPU diam {r['cpu_idle_pct']:.2f}% | "
                      f"mulai {r['startup_s']:.2f} s | p95 {r['lat_p95_ms'] or float('nan'):.1f} ms"
                      f" | tanpa ack {r['n_unacked']}", flush=True)  # fmt: skip
                fields = [k for k in runs[0] if not k.startswith("_")]
                with (out / "per_run.csv").open("w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(runs)
    except ui_bench.NotOnAc as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    summary = {c: {"condition": c, **summarize([r for r in runs if r["condition"] == c])}
               for c in conditions}  # fmt: skip
    with (out / "summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary["baseline"]))
        w.writeheader()
        w.writerows(summary.values())
    changes = []
    for cond, extra in conditions.items():
        if cond == "baseline":
            continue
        func = functional([r for r in runs if r["condition"] == cond], tests.returncode == 0,
                          settings.ui.fullscreen)  # fmt: skip
        keep, reason = decide(summary["baseline"], summary[cond], func)
        changes.append({"condition": cond, "change": " ".join(extra),
                        "decision": "DIPERTAHANKAN" if keep else "DIBATALKAN", "reason": reason,
                        **{f"{m}_median_baseline": summary["baseline"][f"{m}_median"]
                           for m in METRICS},
                        **{f"{m}_max_baseline": summary["baseline"][f"{m}_max"] for m in METRICS},
                        **{f"{m}_median_candidate": summary[cond][f"{m}_median"]
                           for m in METRICS}})  # fmt: skip
    with (out / "changes.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(changes[0]))
        w.writeheader()
        w.writerows(changes)
    info = {
        "experiment": "ADR-19 optimasi UI web putaran 2",
        "protocol": "docs/UI-WEB.md, Optimasi putaran 2 (ditetapkan sebelum data)",
        "config": args.config.as_posix(), "reps_per_condition": args.reps,
        "order": "selang-seling per ulangan: " + ", ".join(conditions),
        "baseline_switches": list(IDLE_SWITCHES + RENDERING_SWITCHES),
        "conditions": {c: list(e) for c, e in conditions.items()},
        "rule": {"up": "median kandidat > maksimum baseline",
                 "down": "median kandidat < median baseline",
                 "keep": "RAM USS diam ATAU CPU diam turun, tidak ada metrik naik, tes + (a) lulus",
                 "metrics": list(METRICS)},
        "tests": {"command": "pytest -q tests/unit/test_webui.py", "result": tests_line,
                  "returncode": tests.returncode},
        "decisions": changes, "summary": summary,
        "power_sources": sorted({str(r["power_source"]) for r in runs}),
        "versions": {"Flask": package_version("Flask"),
                     "edge": ui_bench._edge_version(find_edge())},
        "environment": environment,
    }  # fmt: skip
    (out / "run.json").write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8")  # fmt: skip
    for c in changes:
        print(f"{c['condition']}: {c['decision']} ({c['reason']})")
    print(f"tersimpan: {out.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
