"""Diagnosis CPU dan RAM UI web saat diam (Langkah 31 bagian B), per proses.

python scripts/ui_diag.py [--config config/dev.yaml] [--reps 3] [--out results/ADR-19]
                          [--name ui-diag]

Per ulangan: proses anak scripts/ui_bench.py --child web (pekerja + pipeline palsu, Edge kiosk)
dijalankan sampai layar pertama tampil, lalu diam 60 detik di layar awal (sama dengan bench
tahap 1). Untuk setiap proses di pohonnya dicatat CPU rata-rata (persen satu inti) dan RAM USS
di akhir masa diam. Jenis proses Edge dibaca dari argumen --type= (dan --utility-sub-type=) di
command line; proses tanpa --type adalah proses browser. Jumlah pesan server -> browser dan
putaran poll selama diam dicatat lewat perintah "stats" ke proses anak.
Wajib daya AC (berhenti bila baterai).
Hasil: results/ADR-19/<--name>-<cap waktu>/ (per_process.csv, by_kind.csv, run.json).
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_bench

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "mica" / "webui" / "static"


def measure_idle(root_pid: int, seconds: float) -> list[dict[str, Any]]:
    import psutil

    procs = ui_bench.tree(root_pid)
    start = {}
    for p in procs:
        try:
            t = p.cpu_times()
            start[p.pid] = t.user + t.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    t0 = time.perf_counter()
    time.sleep(seconds)
    elapsed = time.perf_counter() - t0
    rows = []
    for p in procs:
        try:
            t = p.cpu_times()
            uss = p.memory_full_info().uss / 2**20
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if p.pid not in start:
            continue
        cpu = 100.0 * (t.user + t.system - start[p.pid]) / elapsed
        rows.append({"pid": p.pid, "kind": ui_bench.process_kind(p, root_pid), "cpu_pct": cpu,
                     "uss_mb": uss})  # fmt: skip
    return rows


def frontend_findings() -> dict[str, Any]:
    """Pemeriksaan statis frontend: animasi CSS dan timer/rAF berulang."""
    import re

    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    raf = len(re.findall(r"requestAnimationFrame\(", js))
    return {
        "css_animation": bool(re.search(r"animation|@keyframes", css)),
        "css_transition": "transition" in css,
        "js_setInterval": "setInterval(" in js,
        "js_setTimeout": "setTimeout(" in js,
        "js_requestAnimationFrame_calls": raf,
        "catatan": "requestAnimationFrame hanya dipanggil sekali per pesan view (ack), "
        "tidak berulang; tanpa pesan, tidak ada rAF",
    }


def stats(proc: subprocess.Popen) -> dict[str, Any]:
    assert proc.stdin is not None
    proc.stdin.write("stats\n")
    proc.stdin.flush()
    return ui_bench.read_event(proc, "stats", 30)


def run_once(rep: int, config: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    power = ui_bench.require_ac()
    child = [sys.executable, ui_bench.__file__, "--child", "web", "--config", str(config)]
    proc = subprocess.Popen(child, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8")  # fmt: skip
    try:
        ui_bench.read_event(proc, "painted")
        before = stats(proc)
        rows = measure_idle(proc.pid, ui_bench.IDLE_S)
        after = stats(proc)
        assert proc.stdin is not None
        proc.stdin.write("quit\n")
        proc.stdin.flush()
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            for p in reversed(ui_bench.tree(proc.pid)):
                p.kill()
    sent_idle = {k: after["sent"].get(k, 0) - before["sent"].get(k, 0)
                 for k in set(after["sent"]) | set(before["sent"]) if k != "_ticks"}  # fmt: skip
    info = {"rep": rep, "messages_sent_during_idle": sent_idle,
            "poll_ticks_during_idle": after["ticks"] - before["ticks"],
            "power_source": (power or {}).get("source"),
            "battery_percent": (power or {}).get("battery_percent")}  # fmt: skip
    for r in rows:
        r["rep"] = rep
    return rows, info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/ui_diag.py")
    parser.add_argument("--config", type=Path, default=Path("config/dev.yaml"))
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--out", type=Path, default=Path("results/ADR-19"))
    parser.add_argument("--name", default="ui-diag")
    args = parser.parse_args(argv)
    from mica.eval.environment import collect_environment

    try:
        ui_bench.require_ac()
        environment = collect_environment()
        all_rows: list[dict[str, Any]] = []
        infos = []
        for rep in range(1, args.reps + 1):
            print(f"[diag ulangan {rep}] ...", flush=True)
            rows, info = run_once(rep, args.config)
            all_rows += rows
            infos.append(info)
            total = sum(r["cpu_pct"] for r in rows)
            print(f"  CPU total {total:.2f}% | USS total {sum(r['uss_mb'] for r in rows):.0f} MB"
                  f" | pesan saat diam {info['messages_sent_during_idle']}", flush=True)  # fmt: skip
    except ui_bench.NotOnAc as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    # per jenis: jumlah per ulangan, lalu median antar-ulangan
    kinds = sorted({r["kind"] for r in all_rows})
    by_kind = []
    for kind in kinds:
        per_rep = []
        for rep in range(1, args.reps + 1):
            rs = [r for r in all_rows if r["rep"] == rep and r["kind"] == kind]
            per_rep.append((len(rs), sum(r["cpu_pct"] for r in rs), sum(r["uss_mb"] for r in rs)))
        by_kind.append({
            "kind": kind, "n_processes_median": statistics.median(n for n, _, _ in per_rep),
            "cpu_pct_median": statistics.median(c for _, c, _ in per_rep),
            "uss_mb_median": statistics.median(u for _, _, u in per_rep),
        })  # fmt: skip
    totals = []
    for rep in range(1, args.reps + 1):
        rs = [r for r in all_rows if r["rep"] == rep]
        totals.append((sum(r["cpu_pct"] for r in rs), sum(r["uss_mb"] for r in rs)))
    by_kind.append({"kind": "TOTAL", "n_processes_median": statistics.median(
        len([r for r in all_rows if r["rep"] == rep]) for rep in range(1, args.reps + 1)),
        "cpu_pct_median": statistics.median(c for c, _ in totals),
        "uss_mb_median": statistics.median(u for _, u in totals)})  # fmt: skip

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    out = args.out / f"{args.name}-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    with (out / "per_process.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rep", "pid", "kind", "cpu_pct", "uss_mb"])
        w.writeheader()
        w.writerows(all_rows)
    with (out / "by_kind.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(by_kind[0]))
        w.writeheader()
        w.writerows(by_kind)
    info = {
        "experiment": "ADR-19 Langkah 31 bagian B: diagnosis CPU/RAM diam per proses",
        "config": args.config.as_posix(), "reps": args.reps, "idle_s": ui_bench.IDLE_S,
        "workers": "palsu", "pipeline": "palsu",
        "cpu_definition": "rata-rata persen satu inti selama masa diam (cpu_times user+system)",
        "ram_definition": "USS di akhir masa diam",
        "runs": infos, "frontend": frontend_findings(), "environment": environment,
    }  # fmt: skip
    (out / "run.json").write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8")  # fmt: skip
    for row in by_kind:
        print(f"{row['kind']:<40} n={row['n_processes_median']:<4} "
              f"CPU {row['cpu_pct_median']:6.2f}%  USS {row['uss_mb_median']:7.1f} MB")  # fmt: skip
    print(f"tersimpan: {out.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
