"""scripts/ui_preview_opt.py (Langkah 38): Condition.spec dan subperintah decide."""

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("ui_preview_opt", ROOT / "scripts/ui_preview_opt.py")
opt = importlib.util.module_from_spec(_spec)
sys.modules["ui_preview_opt"] = opt
_spec.loader.exec_module(opt)

BASE = "base:static=21e25ae"
K2 = "k2:static=21e25ae,edge=--disable-gpu-compositing"


@pytest.mark.parametrize(
    "text", [BASE + ",preview=public", K2.replace(",edge", ",preview=public,fps=2,edge")]
)
def test_spec_roundtrip(text):
    c = opt.Condition.parse(text)
    assert opt.Condition.parse(c.spec()) == c
    assert opt.Condition.from_describe(c.describe()) == c


def _stats(median, lo, hi):
    return {"median": median, "min": lo, "max": hi}


def _write_run(folder, cand_uss, reps=10, cand_reps=10):
    a, b = opt.Condition.parse(BASE), opt.Condition.parse(K2)
    summary = {
        "a": a.describe(),
        "b": b.describe(),
        "reps": reps,
        "summary": {
            "base": {"uss": _stats(390, 388, 393), "cpu": _stats(13, 10, 16), "p95": _stats(4, 3, 6)},
            "k2": {"uss": _stats(cand_uss, cand_uss - 1, cand_uss + 1), "cpu": _stats(14, 12, 17),
                   "p95": _stats(4.5, 3.5, 5.5)},
        },
    }  # fmt: skip
    (folder / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with (folder / "per_run.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order", "condition"])
        w.writerows([[i, "base"] for i in range(reps)] + [[i, "k2"] for i in range(cand_reps)])
    return folder / "summary.json"


def test_decide_k2_passes(tmp_path, capsys):
    path = _write_run(tmp_path, cand_uss=218)
    assert opt.main(["decide", "--summary", str(path)]) == 0
    out = capsys.readouterr().out
    assert "k2 LOLOS aturan pra-registrasi vs base" in out
    final = "akhir:static=21e25ae,preview=public,edge=--disable-gpu-compositing"
    assert out.strip().splitlines()[-1] == f"FINAL={final}"
    assert json.loads((tmp_path / "decision.json").read_text(encoding="utf-8"))["better"] is True


def test_decide_k2_fails_keeps_base(tmp_path, capsys):
    path = _write_run(tmp_path, cand_uss=445)
    assert opt.main(["decide", "--summary", str(path)]) == 0
    out = capsys.readouterr().out
    assert "k2 TIDAK LOLOS aturan pra-registrasi vs base" in out
    assert out.strip().splitlines()[-1] == "FINAL=akhir:static=21e25ae,preview=public"


def test_decide_refuses_incomplete_run(tmp_path, capsys):
    path = _write_run(tmp_path, cand_uss=218, cand_reps=9)
    assert opt.main(["decide", "--summary", str(path)]) == 6
    (tmp_path / "per_run.csv").unlink()
    _write_run(tmp_path, cand_uss=218)
    (tmp_path / "aborted.json").write_text("{}", encoding="utf-8")
    assert opt.main(["decide", "--summary", str(path)]) == 6
    assert "FINAL=" not in capsys.readouterr().out


def test_gc_verdict_amendment_2():
    assert opt.gc_verdict(30.0, 25.0) == "turun lagi setelah GC (sampah GC)"
    assert opt.gc_verdict(30.0, 30.0) == "tidak turun (bocor)"
    assert opt.gc_verdict(30.0, 31.0) == "tidak turun (bocor)"


def test_grow_cdp_gc_dry_run_adds_debug_port(tmp_path, capsys):
    code = opt.main(["grow", "--out", str(tmp_path), "--condition", "fps10:static=now,fps=10",
                     "--cdp-gc", "--dry-run"])  # fmt: skip
    assert code == 0
    out = capsys.readouterr().out
    assert "--edge-extra=--remote-debugging-port=" in out and "--fake-camera" in out
    raw = (tmp_path / "config-fps10.yaml").read_text(encoding="utf-8")
    assert "preview_fps: 10" in raw and "camera_preview: public" in raw
