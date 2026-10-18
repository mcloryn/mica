"""Diagnosis Langkah 37: UI lama (static e8c24a2^) vs UI baru, preview off, selang-seling."""

import shutil
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "D:/SKRIPSI/mica/scripts")
import ui_bench

ROOT = Path("D:/SKRIPSI/mica")
STATIC = ROOT / "src/mica/webui/static"
SP = Path(__file__).parent
NEW = SP / "static_new"
OLD = SP / "static_nofont"


def snapshot():
    if NEW.exists():
        shutil.rmtree(NEW)
    shutil.copytree(STATIC, NEW)
    if OLD.exists():
        shutil.rmtree(OLD)
    OLD.mkdir()
    shutil.copytree(STATIC, OLD, dirs_exist_ok=True)
    tok = (OLD / "tokens.css").read_text(encoding="utf-8")
    i = tok.index("@font-face")
    j = tok.index("}", i) + 1
    (OLD / "tokens.css").write_text(tok[:i] + tok[j:], encoding="utf-8")
    for name in ():
        data = subprocess.run(
            ["git", "show", f"e8c24a2^:src/mica/webui/static/{name}"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        (OLD / name).write_bytes(data)


def use(src):
    for f in STATIC.iterdir():
        if f.is_file():
            f.unlink()
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, STATIC / f.name)


if __name__ == "__main__":
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    cfg = Path(sys.argv[1])
    snapshot()
    res = {"old": [], "new": []}
    try:
        for rep in range(1, reps + 1):
            for cond, src in (("old", OLD), ("new", NEW)):
                use(src)
                r = ui_bench.run_once("web", rep, cfg)
                res[cond].append(r)
                print(
                    cond,
                    rep,
                    f"USS {r['uss_idle_mb']:.1f} CPU {r['cpu_idle_pct']:.2f} start {r['startup_s']:.2f} "
                    f"p95 {r['lat_p95_ms']:.2f}",
                    {k: round(v, 2) for k, v in r["_cpu_by_kind"].items() if v > 0.1},
                    {k: round(v, 1) for k, v in r["_uss_by_kind"].items() if v > 5},
                    flush=True,
                )
    finally:
        use(NEW)
    for cond, rs in res.items():
        print(
            cond,
            "median USS",
            statistics.median(r["uss_idle_mb"] for r in rs),
            "CPU",
            statistics.median(r["cpu_idle_pct"] for r in rs),
            "start",
            statistics.median(r["startup_s"] for r in rs),
        )
