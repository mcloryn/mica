"""M-12 eval vision (E-07 deteksi): IoU, mAP gaya COCO kasus mainan (dihitung tangan), bootstrap
ber-seed, aturan pemilihan, dataset, CLI dengan predictor palsu, dan penolakan mode kiosk."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mica.eval import __main__ as cli
from mica.eval import vision as ev
from mica.vision.types import PersonTrack

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
KIOSK_YAML = ROOT / "config" / "kiosk.yaml"
GT = np.array([[0.0, 0.0, 10.0, 10.0]])


def det(boxes, scores):
    return np.asarray(boxes, dtype=float).reshape(-1, 4), np.asarray(scores, dtype=float)


# --- IoU dan pencocokan -------------------------------------------------------------------


def test_iou_matrix_hand_values():
    ious = ev.iou_matrix([[0, 0, 2, 2], [0, 0, 2, 2]], [[1, 1, 3, 3], [0, 0, 2, 2], [5, 5, 6, 6]])
    assert ious[0, 0] == pytest.approx(1 / 7)
    assert ious[0, 1] == 1.0
    assert ious[0, 2] == 0.0


def test_greedy_match_one_label_per_detection():
    ious = np.array([[0.9, 0.6], [0.8, 0.0]])
    # deteksi 0 mengambil label 0 (IoU tertinggi), deteksi 1 tidak dapat label 0 lagi
    assert ev.greedy_match(ious, 0.5) == [(0, 0)]


# --- AP / mAP kasus mainan ----------------------------------------------------------------


def test_perfect_plus_duplicate_is_ap_one():
    # A IoU 1 (skor 0,9) TP; B IoU 0,5 (skor 0,8) FP karena label sudah terpakai
    m = ev.match_frame(*det([[0, 0, 10, 10], [0, 0, 10, 5]], [0.9, 0.8]), GT, 0.1)
    assert m.tp[0].tolist() == [True, False]
    assert ev.map_scores([m]) == (1.0, 1.0)
    assert m.ious50 == (1.0,)


def test_half_recall_is_51_over_101():
    # frame 1: TP skor 0,9; frame 2: FP skor 0,8 dan label terlewat
    m1 = ev.match_frame(*det([[0, 0, 10, 10]], [0.9]), GT, 0.1)
    m2 = ev.match_frame(*det([[50, 50, 60, 60]], [0.8]), GT, 0.1)
    # recall [0,5; 0,5], presisi [1; 0,5]: titik recall 0..0,50 (51 titik) presisi 1, sisanya 0
    map50, map5095 = ev.map_scores([m1, m2])
    assert map50 == pytest.approx(51 / 101)
    assert map5095 == pytest.approx(51 / 101)


def test_iou_07_counts_for_five_of_ten_thresholds():
    m = ev.match_frame(*det([[0, 0, 10, 7]], [0.9]), GT, 0.1)  # IoU 0,7
    map50, map5095 = ev.map_scores([m])
    assert map50 == 1.0
    assert map5095 == pytest.approx(0.5)  # IoU 0,50..0,70 lolos (5 dari 10)


def test_fp_before_tp_interpolated_precision():
    m = ev.match_frame(*det([[50, 50, 60, 60], [0, 0, 10, 10]], [0.9, 0.8]), GT, 0.1)
    # recall [0, 1], presisi [0, 0,5] -> amplop 0,5 di semua titik
    assert ev.map_scores([m])[0] == pytest.approx(0.5)


def test_conf_filter_drops_low_boxes():
    m = ev.match_frame(*det([[50, 50, 60, 60], [0, 0, 10, 10]], [0.2, 0.8]), GT, 0.25)
    assert len(m.scores) == 1
    assert ev.map_scores([m])[0] == 1.0


def test_no_detection_ap_zero_and_no_label_nan():
    assert ev.average_precision(np.zeros(0), np.zeros(0, bool), 3) == 0.0
    assert np.isnan(ev.average_precision(np.array([0.5]), np.array([False]), 0))


# --- bootstrap ----------------------------------------------------------------------------


def _matches(n=20, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        shift = rng.uniform(0, 6)
        out.append(
            ev.match_frame(*det([[shift, 0, 10 + shift, 10]], [rng.uniform(0.2, 1)]), GT, 0.1)
        )
    return out


def test_bootstrap_deterministic_with_seed():
    matches = _matches()
    a = ev.bootstrap_map(matches, ev.bootstrap_indices(len(matches), n=50))
    b = ev.bootstrap_map(matches, ev.bootstrap_indices(len(matches), n=50))
    c = ev.bootstrap_map(matches, ev.bootstrap_indices(len(matches), n=50, seed=1))
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)
    assert ev.BOOTSTRAP_SEED == 20261018 and ev.BOOTSTRAP_N == 1000


def test_bootstrap_weights_equal_concatenation():
    matches = _matches(5)
    weights = np.array([2, 0, 1, 0, 3])
    expanded = [m for m, w in zip(matches, weights, strict=True) for _ in range(w)]
    assert ev.pooled_map(ev.pool(matches), weights) == pytest.approx(ev.map_scores(expanded))


# --- aturan pemilihan ---------------------------------------------------------------------


def row(model, conf, map5095, p50):
    return ev.ModelRow(model, conf, 10, 10, 10, 0.8, map5095, map5095, 0, 1, p50, p50)


def test_select_clear_winner_then_conf():
    rows = [
        row("a", 0.1, 0.6, 0.2),
        row("b", 0.1, 0.4, 0.1),
        row("a", 0.25, 0.65, 0.2),
        row("a", 0.5, 0.5, 0.2),
    ]
    boots = {("a", 0.1): np.full(100, 0.6), ("b", 0.1): np.full(100, 0.4)}
    d = ev.select(rows, boots)
    assert (d.model, d.conf) == ("a", 0.25)
    assert d.diffs["a - b"]["ci_lo"] == pytest.approx(0.2)


def test_select_tie_goes_to_faster_model():
    rows = [row("a", 0.1, 0.6, 0.2), row("b", 0.1, 0.58, 0.1)]
    rng = np.random.default_rng(0)
    boots = {("a", 0.1): rng.normal(0.6, 0.05, 1000), ("b", 0.1): rng.normal(0.58, 0.05, 1000)}
    d = ev.select(rows, boots)
    assert d.model == "b"  # CI selisih memuat 0 -> FPS lebih tinggi
    assert any("seri" in r for r in d.reasons)


def test_select_conf_tie_prefers_default_then_smaller():
    rows = [row("a", 0.1, 0.6, 0.2), row("a", 0.25, 0.6, 0.2)]
    assert ev.select(rows, {("a", 0.1): np.full(10, 0.6)}).conf == 0.1
    rows = [row("a", 0.1, 0.5, 0.2), row("a", 0.25, 0.6, 0.2), row("a", 0.5, 0.6, 0.2)]
    assert ev.select(rows, {("a", 0.1): np.full(10, 0.5)}).conf == 0.25


def test_select_without_default_conf_has_no_winner():
    d = ev.select([row("a", 0.25, 0.6, 0.2)], {})
    assert d.model is None


# --- dataset ------------------------------------------------------------------------------


def make_dataset(root: Path, labels: dict[str, str], consent=True) -> Path:
    (root / "images").mkdir(parents=True)
    (root / "labels").mkdir()
    lines = []
    for i, (fid, text) in enumerate(labels.items()):
        (root / "images" / f"{fid}.png").write_bytes(b"")
        (root / "labels" / f"{fid}.txt").write_text(text, encoding="utf-8")
        lines.append(
            json.dumps(
                {
                    "id": fid,
                    "file": f"images/{fid}.png",
                    "relawan": "R01",
                    "persetujuan": consent if i == 0 else True,
                    "cahaya": "terang" if i % 2 else "redup",
                    "jarak": "dekat",
                }
            )
        )
    (root / "manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def test_yolo_labels_to_pixels(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("0 0.5 0.5 0.2 0.4\n\n", encoding="utf-8")
    assert ev.read_yolo_labels(p, 100, 50).tolist() == [[40.0, 15.0, 60.0, 35.0]]
    p.write_text("", encoding="utf-8")
    assert ev.read_yolo_labels(p, 100, 50).shape == (0, 4)


def test_yolo_labels_reject_other_class(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("2 0.5 0.5 0.2 0.4\n", encoding="utf-8")
    with pytest.raises(ev.VisionEvalError, match="kelas 2"):
        ev.read_yolo_labels(p, 100, 50)


def test_manifest_without_consent_rejected(tmp_path):
    root = make_dataset(tmp_path / "ds", {"f1": "", "f2": ""}, consent=False)
    with pytest.raises(ev.VisionEvalError, match="persetujuan"):
        ev.load_frames(root)


def test_missing_label_rejected(tmp_path):
    root = make_dataset(tmp_path / "ds", {"f1": ""})
    (root / "labels" / "f1.txt").unlink()
    with pytest.raises(ev.VisionEvalError, match="label"):
        ev.load_frames(root)


# --- run dan CLI --------------------------------------------------------------------------

LABEL = "0 0.5 0.5 0.4 0.8\n"  # kotak (30, 10, 70, 90) di gambar 100 x 100


def fake_predictor(good: bool):
    def predict(frame):
        box = (30.0, 10.0, 70.0, 90.0) if good else (30.0, 10.0, 70.0, 50.0)
        return [PersonTrack(0, box, 0.9), PersonTrack(1, (0.0, 0.0, 5.0, 5.0), 0.2)]

    return predict


def fake_clock():
    t = [0.0]

    def clock():
        t[0] += 0.05
        return t[0]

    return clock


def test_run_vision_writes_outputs(tmp_path):
    root = make_dataset(tmp_path / "ds", {f"f{i}": LABEL for i in range(4)})
    frames = ev.load_frames(root)
    rows, decision = ev.run_vision(
        frames,
        {"good": lambda: fake_predictor(True), "bad": lambda: fake_predictor(False)},
        [0.1, 0.25],
        tmp_path / "out",
        {"note": "sintetis"},
        images=lambda f: np.zeros((100, 100, 3), np.uint8),
        clock=fake_clock(),
        progress=lambda s: None,
    )
    assert decision.model == "good"
    good = {r.conf: r for r in rows if r.model == "good"}
    assert good[0.1].map50_95 == 1.0 and good[0.1].n_det == 8 and good[0.25].n_det == 4
    for name in ("summary.csv", "per_frame.csv", "per_kondisi.csv", "verdict.md", "run.json"):
        assert (tmp_path / "out" / name).is_file()
    run = json.loads((tmp_path / "out" / "run.json").read_text(encoding="utf-8"))
    assert run["bootstrap"]["seed"] == 20261018
    assert run["decision"]["model"] == "good"
    assert "vision.model = good" in (tmp_path / "out" / "verdict.md").read_text(encoding="utf-8")


def test_cli_vision_with_fake_predictors(tmp_path, monkeypatch, capsys):
    root = make_dataset(tmp_path / "ds", {f"f{i}": LABEL for i in range(3)})
    models = tmp_path / "models"
    models.mkdir()
    for m in ("yolo26n", "yolo26n-pose"):
        (models / f"{m}.pt").write_bytes(b"x")
    monkeypatch.setattr(
        ev, "ultralytics_predictor", lambda path, conf, imgsz: fake_predictor("pose" in str(path))
    )
    monkeypatch.setattr(ev, "read_image", lambda path: np.zeros((100, 100, 3), np.uint8))
    code = cli.main(
        [
            "vision",
            "--config",
            str(DEV_YAML),
            "--dataset",
            str(root),
            "--models-dir",
            str(models),
            "--out",
            str(tmp_path / "res"),
            "--note",
            "sintetis",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "vision.model = yolo26n-pose" in out
    run_dir = next((tmp_path / "res").iterdir())
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["models"]["yolo26n"]["sha256"] is not None
    assert run["environment"]["power"] is None or "source" in run["environment"]["power"]


def test_cli_vision_refused_in_kiosk(tmp_path, monkeypatch, capsys):
    from mica.config import load_settings

    settings = load_settings(DEV_YAML)
    kiosk = settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "kiosk"})})
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: kiosk)
    code = cli.main(["vision", "--config", str(KIOSK_YAML), "--dataset", str(tmp_path)])
    assert code == 2
    assert "mode kiosk" in capsys.readouterr().err


def test_cli_vision_missing_model(tmp_path, capsys):
    root = make_dataset(tmp_path / "ds", {"f1": LABEL})
    code = cli.main(
        [
            "vision",
            "--config",
            str(DEV_YAML),
            "--dataset",
            str(root),
            "--models-dir",
            str(tmp_path / "kosong"),
        ]
    )
    assert code == 2
    assert "fetch-model" in capsys.readouterr().err
