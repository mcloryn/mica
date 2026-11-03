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


def test_cli_color_refused_in_prod(tmp_path, monkeypatch, capsys):
    from mica.config import load_settings

    settings = load_settings(DEV_YAML)
    prod = settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "prod"})})
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: prod)
    code = cli.main(["color", "--config", "x", "--dataset", str(tmp_path)])
    assert code == 2
    assert "mode prod" in capsys.readouterr().err


# --- grid area baju (PROD-5, docs/AMANDEMEN-2026-11-03.md bagian C) -----------------------


def kp_person(shoulders, hips, conf=0.9, hip_conf=None, box=(10.0, 10.0, 90.0, 90.0)):
    kp = np.zeros((17, 3))
    kp[5], kp[6] = (*shoulders[0], conf), (*shoulders[1], conf)
    hc = conf if hip_conf is None else hip_conf
    kp[11], kp[12] = (*hips[0], hc), (*hips[1], hc)
    return PersonTrack(0, box, 0.9, kp)


def area_run(images, people, true, winner=("keypoint_torso", "lut_vote"), namer=None):
    frames = [ev.VisionFrame(fid, Path(f"{fid}.png"), Path(f"{fid}.txt"), "R01", "terang",
                             "dekat") for (fid, _track), _p in people]  # fmt: skip
    namers = {"lut_vote": namer or ChannelNamer(), "lut_mean": namer or ChannelNamer()}
    return ec.run_area_grid(ec.ComboRow(*winner, len(people)), namers, frames, dict(people),
                            true, images, make_region)  # fmt: skip


def test_area_grid_shrink_chosen_from_data_and_unused_keys_stay_trial():
    # torso 30..70; merah hanya 41..59: shrink 0,20 (38..62) merah 56 %, 0,15 dan 0,10 biru
    def images(frame):
        img = np.zeros((100, 100, 3), np.uint8)
        img[30:70, 30:70] = BGR["biru"]
        img[41:59, 41:59] = BGR["merah"]
        return img

    p = kp_person(((30, 30), (70, 30)), ((30, 70), (70, 70)))
    keys = [(f"f{i}", 0) for i in range(3)]
    result = area_run(images, [(k, p) for k in keys], dict.fromkeys(keys, "merah"))
    assert len(result.rows) == 27 + 27
    assert result.values["keypoint_torso.shrink"] == 0.20
    # min_kp_conf seri (conf 0,9) -> nilai coba; torso_aspect dan box_upper tanpa item -> nilai coba
    assert result.values["keypoint_torso.min_kp_conf"] == 0.5
    assert result.unswept["2a"] == ["keypoint_torso.torso_aspect"]
    assert result.unswept["2b"] == list(ec.STAGE_2B)
    assert all(result.values[k] == ec.TRIAL_VALUES[k] for k in ec.STAGE_2B)
    assert result.winners["2a"].accuracy == 1.0 and result.min_majority is not None
    assert "Untuk E-07 bagian 2: --min-kp-conf 0.5" in ec.area_verdict(result)


def test_area_grid_min_kp_conf_and_fallback_counts():
    # keypoint conf 0,6: min_kp_conf 0,7 jatuh ke cadangan box_upper (hijau) -> salah
    def images(frame):
        img = np.zeros((100, 100, 3), np.uint8)
        img[10:90, 10:90] = BGR["hijau"]
        img[20:45, 20:50] = BGR["merah"]
        return img

    p = kp_person(((20, 20), (50, 20)), ((20, 45), (50, 45)), conf=0.6)
    keys = [("f1", 0), ("f2", 0)]
    result = area_run(images, [(k, p) for k in keys], dict.fromkeys(keys, "merah"))
    rows_07 = [r for r in result.rows if r.stage == "2a"
               and r.values["keypoint_torso.min_kp_conf"] == 0.7]  # fmt: skip
    assert all(r.sources["fallback"] == 2 and r.accuracy == 0.0 for r in rows_07)
    assert result.values["keypoint_torso.min_kp_conf"] == 0.5
    assert result.winners["2a"].sources["keypoint"] == 2


def test_area_grid_box_upper_region_runs_only_stage_2b():
    # box 10..90 (tinggi 80); biru di y < 47, merah di bawahnya. Label biru: hanya top 0,30 +
    # bottom 0,60 (baris 34..58: biru 13, merah 11) yang benar
    def images(frame):
        img = np.zeros((100, 100, 3), np.uint8)
        img[10:47, 10:90] = BGR["biru"]
        img[47:90, 10:90] = BGR["merah"]
        return img

    p = kp_person(((30, 30), (70, 30)), ((30, 70), (70, 70)))
    keys = [("f1", 0)]
    result = area_run(images, [(keys[0], p)], {keys[0]: "biru"}, winner=("box_upper", "lut_mean"))
    assert list(result.winners) == ["2b"] and len(result.rows) == 27
    assert (result.values["box_upper.top"], result.values["box_upper.bottom"]) == (0.30, 0.60)
    assert result.values["box_upper.side"] == 0.25  # seri -> nilai coba
    assert result.min_majority_sweep == [] and result.min_majority is None  # lut_mean
    verdict = ec.area_verdict(result)
    assert "Tahap 3 dilewati" in verdict and "--min-kp-conf 0.5" in verdict


def _area_row(values, f1=0.5, acc=0.5, stage="2b"):
    return ec.AreaRow(stage, {**ec.TRIAL_VALUES, **values}, 4, acc, f1, 0, {"box": 4}, [])


def test_area_rule_order_and_tiebreaks():
    a = _area_row({"box_upper.top": 0.40}, f1=0.6, acc=0.1)
    b = _area_row({}, f1=0.5, acc=0.9)
    assert ec.choose_area([b, a], "2b")[0] is a  # macro-F1 dulu
    c = _area_row({"box_upper.top": 0.40}, acc=0.6)
    d = _area_row({}, acc=0.5)
    assert ec.choose_area([d, c], "2b")[0] is c  # lalu akurasi
    e = _area_row({"box_upper.top": 0.30, "box_upper.side": 0.30})
    f = _area_row({"box_upper.top": 0.40})
    assert ec.choose_area([e, f], "2b")[0] is f  # lalu jarak ke nilai coba
    g = _area_row({"box_upper.top": 0.40})
    h = _area_row({"box_upper.top": 0.30})
    assert ec.choose_area([g, h], "2b")[0] is h  # lalu nilai lebih kecil


def test_cli_color_area_grid_with_fakes(tmp_path, monkeypatch, capsys):
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
                     "--area-grid"])  # fmt: skip
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert "Untuk E-07 bagian 2: --min-kp-conf" in captured.out
    run_dir = next((tmp_path / "res").iterdir())
    grid = (run_dir / "area_grid.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(grid) == 1 + 27 + 27
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["area_grid"]["n_combinations"] == 54
    assert run["area_grid"]["min_kp_conf_for_e07"] in ec.AREA_GRID["keypoint_torso.min_kp_conf"]


def test_cli_color_without_area_grid_unchanged(tmp_path):
    frames = ev.load_frames(make_dataset(tmp_path / "ds", COLORS))
    ec.run_color(frames, labels(COLORS), labels(COLORS), lambda img: [person()], regions(),
                 {"lut_vote": ChannelNamer(), "lut_mean": ChannelNamer()}, tmp_path / "out", {},
                 images=image_for(COLORS))  # fmt: skip
    assert not (tmp_path / "out" / "area_grid.csv").exists()
    assert "area_grid" not in json.loads((tmp_path / "out" / "run.json").read_text("utf-8"))


# --- split tuning/laporan dan laporan Wilson (PROD-8, amandemen kedua C) -------------------


def _split_dataset(root, colors, splits):
    make_dataset(root, colors)
    rows = [json.loads(x) for x in (root / "manifest.jsonl").read_text("utf-8").splitlines()]
    for r in rows:
        r["split"] = splits[r["id"]]
    (root / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    labels_csv = "".join(f"{fid},0,{c}\n" for fid, c in colors.items())
    (root / "colors.csv").write_text("frame,track,color_label\n" + labels_csv, encoding="utf-8")
    return root


REPORT_COLORS = {"f1": "merah", "f2": "merah", "f3": "merah", "f4": "biru", "f5": "biru",
                 "t1": "merah", "t2": "biru"}  # fmt: skip
SPLITS = {k: ("tuning" if k.startswith("t") else "laporan") for k in REPORT_COLORS}
WINNER = {"region": "keypoint_torso", "method": "lut_vote", "values": dict(ec.TRIAL_VALUES),
          "min_majority": 0.5, "from_run": "run-tuning"}  # fmt: skip


def test_split_ids_requires_split_field(tmp_path):
    root = _split_dataset(tmp_path / "ds", REPORT_COLORS, SPLITS)
    assert ec.split_ids(root, "tuning") == {"t1", "t2"}
    plain = make_dataset(tmp_path / "plain", COLORS)
    with pytest.raises(ev.VisionEvalError, match="field split"):
        ec.split_ids(plain, "tuning")


def test_report_wilson_undetected_counted_as_failure(tmp_path):
    colors = {k: v for k, v in REPORT_COLORS.items() if SPLITS[k] == "laporan"}
    frames = ev.load_frames(make_dataset(tmp_path / "ds", colors))
    images = image_for(colors)

    def predictor(img):  # f5 (biru) tidak terdeteksi
        return [] if img[50, 50, 0] == 255 and predictor.seen_blue else _mark(img)

    def _mark(img):
        predictor.seen_blue = predictor.seen_blue or img[50, 50, 0] == 255
        return [person()]

    predictor.seen_blue = False
    truth = labels(colors)
    result = ec.run_report(frames, truth, truth, predictor, WINNER,
                           {"lut_vote": ChannelNamer(), "lut_mean": ChannelNamer()},
                           tmp_path / "out", {"note": "sintetis"}, images=images)  # fmt: skip
    assert (result.n_all, result.n_detected, result.n_undetected, result.correct) == (5, 4, 1, 4)
    by = {r["warna"]: r for r in result.per_color}
    assert (by["merah"]["n"], by["merah"]["benar"]) == (3, 3)
    assert (by["biru"]["n"], by["biru"]["benar"]) == (2, 1)
    assert by["merah"]["wilson_bawah"] == pytest.approx(0.43849, abs=1e-4)  # Wilson 3/3
    assert by["merah"]["wilson_atas"] == 1.0
    assert by["biru"]["catatan"] == ec.NOT_ENOUGH  # n < 10
    report = (tmp_path / "out" / "report.md").read_text("utf-8")
    assert "Akurasi semua gambar (tidak terdeteksi = gagal): 4/5 = 0.8000" in report
    assert "Akurasi gambar terdeteksi: 4/4 = 1.0000" in report
    assert "Tidak terdeteksi YOLO: 1 dari 5" in report and "batas bawah" in report
    assert (tmp_path / "out" / "report_per_color.csv").is_file()
    # catatan kelima: tebakan per gambar dan confusion matrix laporan
    items = {i["frame"]: i for i in result.items}
    assert items["f5"]["terdeteksi"] == 0 and items["f5"]["tebakan"] == ""
    assert items["f4"] == {"frame": "f4", "track": 0, "label": "biru", "terdeteksi": 1,
                           "tebakan": "biru", "mayoritas": "1.000", "disebut": 1}  # fmt: skip
    confusion = {r["label_benar"]: r for r in ec.report_confusion(result.items)}
    assert confusion["biru"]["biru"] == 1 and confusion["biru"][ec.UNDETECTED] == 1
    assert confusion["merah"]["merah"] == 3 and confusion["merah"][ec.UNDETECTED] == 0
    text = (tmp_path / "out" / "confusion.csv").read_text("utf-8-sig")
    assert text.splitlines()[0].endswith("(tanpa prediksi),(tidak terdeteksi)")
    assert len((tmp_path / "out" / "per_item.csv").read_text("utf-8-sig").splitlines()) == 6


def test_winner_from_run_requires_tuning_with_area_grid(tmp_path):
    run = tmp_path / "r"
    run.mkdir()
    (run / "run.json").write_text(json.dumps({"split": "laporan"}), "utf-8")
    with pytest.raises(ev.VisionEvalError, match="bukan run split tuning"):
        ec.winner_from_run(run)
    (run / "run.json").write_text(json.dumps({"split": "tuning", "decision": {
        "region": "box_upper", "method": "lut_mean"}}), "utf-8")  # fmt: skip
    with pytest.raises(ev.VisionEvalError, match="tanpa --area-grid"):
        ec.winner_from_run(run)


def _cli_env(tmp_path, monkeypatch):
    import mica.vision.color as vc

    root = _split_dataset(tmp_path / "ds", REPORT_COLORS, SPLITS)
    models = tmp_path / "models"
    models.mkdir()
    (models / "yolo26n-pose.pt").write_bytes(b"x")
    (models / "color_names_w2c.npy").write_bytes(b"x")
    monkeypatch.setattr(ev, "ultralytics_predictor", lambda *a: lambda img: [person()])
    monkeypatch.setattr(ev, "read_image", lambda path: image_for(REPORT_COLORS)(
        type("F", (), {"id": Path(path).stem})()))  # fmt: skip
    monkeypatch.setattr(vc.ColorNamesLut, "load", classmethod(lambda cls, p, m: ChannelNamer()))
    base = ["color", "--config", str(DEV_YAML), "--dataset", str(root), "--models-dir",
            str(models), "--labels", "colors.csv", "--labels2", "colors.csv"]  # fmt: skip
    return base


def test_cli_tuning_then_laporan(tmp_path, monkeypatch, capsys):
    base = _cli_env(tmp_path, monkeypatch)
    assert cli.main([*base, "--split", "tuning", "--area-grid", "--out",
                     str(tmp_path / "tun")]) == 0  # fmt: skip
    tuning = next((tmp_path / "tun").iterdir())
    run = json.loads((tuning / "run.json").read_text("utf-8"))
    assert run["split"] == "tuning" and run["dataset"]["n_frame"] == 2
    capsys.readouterr()
    assert cli.main([*base, "--split", "laporan", "--from-run", str(tuning), "--out",
                     str(tmp_path / "lap")]) == 0  # fmt: skip
    out = capsys.readouterr().out
    assert "Akurasi semua gambar (tidak terdeteksi = gagal): 5/5" in out
    report = next((tmp_path / "lap").iterdir())
    assert json.loads((report / "run.json").read_text("utf-8"))["n_all"] == 5


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (
            ["--split", "laporan", "--area-grid", "--from-run", "x"],
            "hanya boleh pada --split tuning",
        ),
        (["--split", "laporan"], "butuh --from-run"),
        (["--split", "tuning", "--from-run", "x"], "hanya untuk --split laporan"),
    ],
)
def test_cli_split_rules(tmp_path, monkeypatch, capsys, extra, message):
    base = _cli_env(tmp_path, monkeypatch)
    assert cli.main([*base, *extra, "--out", str(tmp_path / "o")]) == 2
    assert message in capsys.readouterr().err
