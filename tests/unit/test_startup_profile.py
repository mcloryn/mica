"""scripts/startup_profile.py (Langkah 40): config profil (nilai coba SDD 12 hanya untuk null),
ringkasan tahap dari baris sintetis, dan dry-run tanpa menjalankan aplikasi."""

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "startup_profile", ROOT / "scripts/startup_profile.py"
)
prof = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prof)


def test_make_config_fills_only_null_trial_values(tmp_path):
    path, filled = prof.make_config(ROOT / "config/dev.yaml", tmp_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["logging"]["dir"] == (tmp_path / "logs").as_posix()
    assert raw["vision"]["dwell_s"] == 2.0 and raw["audio"]["vad"]["threshold"] == 0.5
    assert raw["vision"]["conf"] == 0.1  # nilai yang sudah ada tidak diganti
    assert set(filled) <= set(prof.TRIAL_VALUES)
    dev = yaml.safe_load((ROOT / "config/dev.yaml").read_text(encoding="utf-8"))
    assert dev["vision"]["dwell_s"] is None  # config repo tidak diubah


def _rows(stages):
    return [{"proc": p, "stage": s, "s": t} for p, s, t in stages]


def test_summarize_milestones_and_spans():
    runs = [
        {"rows": _rows([("main", "pipeline_build_start", 1.0), ("main", "pipeline_ready", 21.0),
                        ("main", "ui_first_render", 23.0), ("vision", "model_load_start", 2.0),
                        ("vision", "model_load_done", 5.0), ("main", "all_ready", 40.0)])},
        {"rows": _rows([("main", "pipeline_build_start", 1.0), ("main", "pipeline_ready", 25.0),
                        ("main", "ui_first_render", 27.0), ("vision", "model_load_start", 2.0),
                        ("vision", "model_load_done", 7.0), ("main", "all_ready", 44.0)])},
    ]  # fmt: skip
    report, table = prof.summarize(runs, "uji", 2)
    by = {(r["kind"], r["label"]): r for r in table}
    assert by[("tonggak", "semua siap")]["median"] == 42.0
    assert by[("tonggak", "UI tampil (render pertama)")]["min"] == 23.0
    assert by[("rentang", "kamera: muat YOLO")]["median"] == 4.0
    assert by[("rentang", "utama: rakit pipeline")]["max"] == 24.0
    assert by[("tonggak", "kamera siap (CameraStatus ok)")]["n"] == 0
    assert "| semua siap | 42.00 (40.00-44.00) |" in report


def test_dry_run_does_not_start_app(tmp_path, capsys):
    assert prof.main(["--label", "uji", "--dry-run", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "-m mica --config" in out and "aplikasi TIDAK dijalankan" in out
    (folder,) = tmp_path.iterdir()
    assert sorted(p.name for p in folder.iterdir()) == ["config.yaml"]
