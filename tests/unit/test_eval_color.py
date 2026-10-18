"""M-12 eval color (E-08): kappa, confusion matrix, macro-F1 (kasus mainan dihitung tangan),
aturan pemilihan dan pemecah seri, sweep min_majority, pencocokan orang, run sintetis, CLI."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mica.eval import __main__ as cli
from mica.eval import color as ec
from mica.eval import vision as ev
from mica.vision.color import COLOR_NAMES, ColorResult, result_from_distribution
from mica.vision.types import PersonTrack
from mica.vision.worker import make_region

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"

# --- kappa dan metrik ---------------------------------------------------------------------


def test_kappa_hand_value():
    # po = 3/4; pe = 0,5 x 0,25 + 0,5 x 0,75 = 0,5 -> kappa = 0,5
    assert ec.cohen_kappa(["merah", "merah", "biru", "biru"],
                          ["merah", "biru", "biru", "biru"]) == pytest.approx(0.5)  # fmt: skip
    assert ec.cohen_kappa(["merah", "biru"], ["merah", "biru"]) == pytest.approx(1.0)
    assert ec.cohen_kappa(["merah", "merah"], ["merah", "merah"]) is None  # pe = 1
    assert ec.cohen_kappa([], []) is None


def test_macro_f1_hand_value():
    true = ["merah", "merah", "biru", "hijau"]
    pred = ["merah", "biru", "biru", None]
    # merah F1 2/3, biru F1 2/3, hijau F1 0 -> 4/9
    assert ec.macro_f1(true, pred) == pytest.approx(4 / 9)
    assert ec.accuracy(true, pred) == 0.5
    scores = ec.f1_scores(true, pred)
    assert scores["biru"]["presisi"] == 0.5 and scores["biru"]["recall"] == 1.0
    assert set(scores) == {"biru", "hijau", "merah"}


def test_confusion_rows_true_columns_pred():
    m = ec.confusion(["merah", "merah", "biru"], ["merah", None, "merah"])
    merah, biru = COLOR_NAMES.index("merah"), COLOR_NAMES.index("biru")
    assert m[merah, merah] == 1 and m[merah, len(COLOR_NAMES)] == 1 and m[biru, merah] == 1
    assert m.sum() == 3 and m.shape == (11, 12)


def test_agreement_counts():
    first = {("f1", 0): "merah", ("f1", 1): "biru", ("f2", 0): "putih", ("f3", 0): "hitam"}
    second = {("f1", 0): "merah", ("f1", 1): "ungu", ("f2", 0): "putih", ("f4", 0): "hitam"}
    a = ec.agreement(first, second)
    assert a.agreed == {("f1", 0): "merah", ("f2", 0): "putih"}
    assert (a.n_both, a.n_disagree) == (3, 1)
    assert a.only_first == [("f3", 0)] and a.only_second == [("f4", 0)]


# --- aturan -------------------------------------------------------------------------------


def combo(region, method, f1, acc=0.5):
    return ec.ComboRow(region, method, 10, acc, f1, 0)


def test_select_combo_macro_f1_then_accuracy_then_adr():
    rows = [combo("box_upper", "lut_mean", 0.6), combo("keypoint_torso", "lut_mean", 0.7),
            combo("box_upper", "lut_vote", 0.5), combo("keypoint_torso", "lut_vote", 0.4)]  # fmt: skip
    assert ec.select_combo(rows)[0].name == "keypoint_torso_lut_mean"
    rows = [combo("box_upper", "lut_mean", 0.7, acc=0.8), combo("keypoint_torso", "lut_mean", 0.7, acc=0.6)]  # fmt: skip
    assert ec.select_combo(rows)[0].name == "box_upper_lut_mean"
    rows = [combo("box_upper", "lut_mean", 0.7), combo("keypoint_torso", "lut_vote", 0.7)]
    assert ec.select_combo(rows)[0].name == "keypoint_torso_lut_vote"


def test_select_combo_without_items_has_no_winner():
    winner, reasons = ec.select_combo([ec.ComboRow("box_upper", "lut_vote")])
    assert winner is None and "tidak ada frame" in reasons[0]


def test_min_majority_sweep_and_choice():
    true = ["merah", "merah", "hijau"]
    preds = [ec.Prediction("merah", 0.9), ec.Prediction("biru", 0.65), ec.Prediction("hijau", 0.55)]
    rows = ec.sweep_min_majority(true, preds)
    assert [(r["disebut"], r["benar"]) for r in rows] == [(3, 2), (2, 1), (1, 1)]
    assert rows[1]["cakupan"] == pytest.approx(2 / 3)
    assert ec.select_min_majority(rows) == 0.7
    good = [ec.Prediction("merah", 0.9), ec.Prediction("merah", 0.9), ec.Prediction("hijau", 0.9)]
    assert ec.select_min_majority(ec.sweep_min_majority(true, good)) == 0.5  # seri -> terkecil
    low = [ec.Prediction("merah", 0.4)] * 3
    assert ec.select_min_majority(ec.sweep_min_majority(true, low)) is None


def test_match_people_iou_threshold():
    gt = np.array([[0, 0, 10, 10], [50, 50, 60, 60]], dtype=float)
    tracks = [PersonTrack(0, (0, 0, 10, 9), 0.9), PersonTrack(1, (50, 50, 60, 54), 0.9)]
    matched = ec.match_people(gt, tracks)
    assert list(matched) == [0]  # IoU 0,4 untuk kotak kedua tidak cukup


def test_load_color_labels_validation(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("frame,track,color_label\nf1,0,Merah\nf1,1,emas\nf1,0,biru\n", encoding="utf-8")
    with pytest.raises(ev.VisionEvalError) as exc:
        ec.load_color_labels(p)
    assert "emas" in str(exc.value) and "ganda" in str(exc.value)
    p.write_text("frame,track,color_label\nf1,0,Merah\n", encoding="utf-8")
    assert ec.load_color_labels(p) == {("f1", 0): "merah"}


# --- run sintetis -------------------------------------------------------------------------

BGR = {"merah": (0, 0, 255), "biru": (255, 0, 0), "hijau": (0, 255, 0)}


class ChannelNamer:
    """Penamaan palsu: kanal terbesar tiap piksel -> merah/hijau/biru."""

    def name(self, pixels):
        px = np.asarray(pixels).reshape(-1, 3)
        dist = np.zeros(len(COLOR_NAMES))
        for idx, name in ((0, "biru"), (1, "hijau"), (2, "merah")):
            dist[COLOR_NAMES.index(name)] = int((px.argmax(axis=1) == idx).sum())
        return result_from_distribution(dist, 0.0, len(px))


class AlwaysWhite:
    """Penamaan palsu yang selalu salah pada data sintetis (tidak ada baju putih)."""

    def name(self, pixels) -> ColorResult:
        dist = np.zeros(len(COLOR_NAMES))
        dist[COLOR_NAMES.index("putih")] = 1.0
        return result_from_distribution(dist, 0.0, int(np.asarray(pixels).size // 3))


def person(tid=0):
    kp = np.zeros((17, 3))
    kp[5], kp[6], kp[11], kp[12] = (30, 30, 0.9), (70, 30, 0.9), (35, 70, 0.9), (65, 70, 0.9)
    return PersonTrack(tid, (10.0, 10.0, 90.0, 90.0), 0.9, kp)


def make_dataset(root: Path, colors: dict[str, str]) -> Path:
    (root / "images").mkdir(parents=True)
    (root / "labels").mkdir()
    lines = []
    for fid in colors:
        (root / "images" / f"{fid}.png").write_bytes(b"")
        (root / "labels" / f"{fid}.txt").write_text("0 0.5 0.5 0.8 0.8\n", encoding="utf-8")
        lines.append(json.dumps({"id": fid, "file": f"images/{fid}.png", "relawan": "R01",
                                 "persetujuan": True, "cahaya": "terang", "jarak": "dekat"}))  # fmt: skip
    (root / "manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def image_for(colors):
    def images(frame):
        img = np.zeros((100, 100, 3), np.uint8)
        img[30:70, 30:70] = BGR[colors[frame.id]]
        return img

    return images


COLORS = {"f1": "merah", "f2": "biru", "f3": "hijau", "f4": "merah"}


def labels(colors, override=None):
    out = {(fid, 0): c for fid, c in colors.items()}
    out.update(override or {})
    return out


def regions():
    return {r: make_region(r, ec.TRIAL_VALUES) for r in ec.REGIONS}


def test_run_color_synthetic_winner(tmp_path):
    frames = ev.load_frames(make_dataset(tmp_path / "ds", COLORS))
    second = labels(COLORS, {("f4", 0): "ungu"})  # satu tidak sepakat
    rows, winner, chosen = ec.run_color(
        frames, labels(COLORS), second, lambda img: [person()], regions(),
        {"lut_vote": ChannelNamer(), "lut_mean": ChannelNamer()},
        tmp_path / "out", {"note": "sintetis"}, images=image_for(COLORS),
    )  # fmt: skip
    assert all(r.accuracy == 1.0 and r.n == 3 for r in rows)
    assert (winner.region, winner.method) == ec.ADR_CHOICE  # seri penuh -> pilihan ADR
    assert chosen == 0.5
    agreement = json.loads((tmp_path / "out" / "agreement.json").read_text(encoding="utf-8"))
    assert agreement["n_tidak_sepakat"] == 1 and agreement["n_sepakat"] == 3
    for name in ("summary.csv", "per_color.csv", "min_majority.csv", "per_item.csv",
                 "verdict.md", "run.json", "confusion_box_upper_lut_vote.csv"):  # fmt: skip
        assert (tmp_path / "out" / name).is_file()
    verdict = (tmp_path / "out" / "verdict.md").read_text(encoding="utf-8")
    assert "vision.color.min_majority = 0.5" in verdict


def test_run_color_lut_mean_wins_skips_sweep_and_undetected(tmp_path):
    frames = ev.load_frames(make_dataset(tmp_path / "ds", COLORS))
    rows, winner, chosen = ec.run_color(
        frames, labels(COLORS), labels(COLORS),
        lambda img: [person()] if img[50, 50].any() and img[50, 50, 0] == 0 else [],
        regions(), {"lut_vote": AlwaysWhite(), "lut_mean": ChannelNamer()},
        tmp_path / "out", {}, images=image_for(COLORS),
    )  # fmt: skip
    assert (winner.region, winner.method) == ("keypoint_torso", "lut_mean")
    assert chosen is None  # amandemen 1: min_majority tidak berlaku untuk lut_mean
    assert rows[0].n == 3  # f2 (biru) tidak terdeteksi -> dikeluarkan
    verdict = (tmp_path / "out" / "verdict.md").read_text(encoding="utf-8")
    assert "sweep min_majority dilewati" in verdict and "cakupan 1.0000" in verdict
    assert "sapaan selalu menyebut warna" in verdict
    assert "vision.color.method = lut_mean" in verdict
    assert "1 sepakat tetapi tidak terdeteksi" in verdict
    run = json.loads((tmp_path / "out" / "run.json").read_text(encoding="utf-8"))
    assert run["min_majority_sweep"] == [] and run["decision"]["coverage"] == 1.0
    assert (tmp_path / "out" / "min_majority.csv").read_text(encoding="utf-8-sig").count("\n") == 1


def test_cli_color_with_fakes(tmp_path, monkeypatch, capsys):
    import mica.vision.color as vc

    root = make_dataset(tmp_path / "ds", COLORS)
    for name in ("colors.csv", "colors_rater2.csv"):
        rows = "".join(f"{fid},0,{c}\n" for fid, c in COLORS.items())
        (root / name).write_text("frame,track,color_label\n" + rows, encoding="utf-8")
    models = tmp_path / "models"
    models.mkdir()
    (models / "yolo26n-pose.pt").write_bytes(b"x")
    (models / "color_names_w2c.npy").write_bytes(b"x")
    monkeypatch.setattr(ev, "ultralytics_predictor", lambda *a: lambda img: [person()])
    monkeypatch.setattr(ev, "read_image", lambda path: image_for(COLORS)(
        type("F", (), {"id": Path(path).stem})()))  # fmt: skip
    monkeypatch.setattr(vc.ColorNamesLut, "load", classmethod(lambda cls, p, m: ChannelNamer()))
    code = cli.main(["color", "--config", str(DEV_YAML), "--dataset", str(root),
                     "--models-dir", str(models), "--out", str(tmp_path / "res"),
                     "--note", "sintetis"])  # fmt: skip
    captured = capsys.readouterr()
    out = captured.out
    assert code == 0, captured.err
    assert "Kappa Cohen = 1.000" in out
    assert "| lut_mean |" in out
    assert "vision.color.method = lut_vote, vision.color.min_majority = 0.5" in out
    run_dir = next((tmp_path / "res").iterdir())
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["region_values"]["box_upper.top"] == 0.35
    assert run["decision"]["method"] == "lut_vote"


def test_cli_color_refused_in_kiosk(tmp_path, monkeypatch, capsys):
    from mica.config import load_settings

    settings = load_settings(DEV_YAML)
    kiosk = settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "kiosk"})})
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: kiosk)
    code = cli.main(["color", "--config", "x", "--dataset", str(tmp_path)])
    assert code == 2
    assert "mode kiosk" in capsys.readouterr().err
