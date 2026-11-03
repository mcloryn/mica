"""M-12: python -m mica.eval color (E-08). Aturan di docs/E-08.md (pra-registrasi 18 Okt 2026).

Frame E-07 (data/eval/vision/<nama>/) + colors.csv dan colors_rater2.csv (frame, track,
color_label; track = indeks baris orang di label YOLO). Cohen's kappa antar-penilai; hanya
pasangan yang disepakati masuk akurasi. Orang diambil dari deteksi yolo26n-pose yang cocok
(IoU >= 0,5) dengan kotak label, lalu setiap region x metode (lut_vote, lut_mean; amandemen 1)
menamai warnanya (warna teratas, tanpa min_majority). Pemenang macro-F1, lalu sweep
min_majority bila pemenang lut_vote. Frame hanya di
memori (N-08); hasil berisi angka, ID, dan label saja.

--area-grid (docs/AMANDEMEN-2026-11-03.md bagian C): pada pemenang tahap 1, tahap 2a
(min_kp_conf x shrink x torso_aspect, hanya keypoint_torso), tahap 2b (box_upper top x bottom x
side), lalu tahap 3 (min_majority pada parameter akhir, hanya lut_vote). Deteksi dijalankan sekali
per frame dan dipakai semua kombinasi; hasil di area_grid.csv dan area_verdict.md.

--split tuning|laporan (docs/AMANDEMEN-2026-11-03b.md C): hanya frame dengan field split itu.
--area-grid hanya boleh pada tuning. Pada laporan (--from-run <run tuning>): nilai pemenang
tuning dipakai apa adanya; akurasi per warna dengan n dan interval Wilson 95% (n < 10 ditandai
"data tidak cukup untuk disimpulkan"), akurasi semua gambar (tidak terdeteksi = gagal), akurasi
gambar terdeteksi, dan jumlah tidak terdeteksi. Hasil di report_per_color.csv dan report.md.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from mica.eval.vision import (
    Predictor,
    VisionEvalError,
    VisionFrame,
    iou_matrix,
    read_yolo_labels,
)
from mica.vision.color import COLOR_NAMES, ColorNamer, result_from_distribution
from mica.vision.region import ClothingRegion
from mica.vision.types import PersonTrack

EXPERIMENT = "E-08"
REGIONS = ("keypoint_torso", "box_upper")
METHODS = ("lut_vote", "lut_mean")  # amandemen 1 E-08
ADR_CHOICE = ("keypoint_torso", "lut_vote")  # pemecah seri terakhir (docs/E-08.md)
# nilai coba area pakaian, SDD bagian 12 (docs/E-08.md)
TRIAL_VALUES = {
    "box_upper.top": 0.35,
    "box_upper.bottom": 0.65,
    "box_upper.side": 0.25,
    "keypoint_torso.min_kp_conf": 0.5,
    "keypoint_torso.shrink": 0.15,
    "keypoint_torso.torso_aspect": 1.2,
}
MIN_MAJORITY_GRID = (0.5, 0.6, 0.7)
MATCH_IOU = 0.5
NO_PRED = "(tanpa prediksi)"
E08_RULE = (
    "Aturan E-08 (docs/E-08.md, 18 Okt 2026, amandemen 1): kombinasi region x {lut_vote, "
    "lut_mean} dengan macro-F1 tertinggi (tanpa min_majority; seri -> akurasi, lalu "
    "keypoint_torso + lut_vote); lalu, hanya bila pemenang lut_vote, min_majority {0,5; 0,6; "
    "0,7}: presisi (benar / disebut warna) tertinggi, seri -> nilai lebih kecil. lut_mean: sweep "
    "dilewati, cakupan 100 %. Cakupan selalu dilaporkan."
)

Key = tuple[str, int]  # (frame, track)


# --- label penilai dan kesepakatan --------------------------------------------------------


def load_color_labels(path: Path) -> dict[Key, str]:
    path = Path(path)
    if not path.is_file():
        raise VisionEvalError(f"{path.as_posix()} tidak ada")
    out: dict[Key, str] = {}
    errors: list[str] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = {"frame", "track", "color_label"} - set(reader.fieldnames or ())
        if missing:
            raise VisionEvalError(f"{path.as_posix()}: kolom wajib tidak ada: {sorted(missing)}")
        for no, row in enumerate(reader, start=2):
            label = (row["color_label"] or "").strip().lower()
            try:
                key = ((row["frame"] or "").strip(), int(row["track"]))
            except (TypeError, ValueError):
                errors.append(f"baris {no}: track harus bilangan bulat")
                continue
            if not key[0] or key[1] < 0:
                errors.append(f"baris {no}: frame wajib dan track >= 0")
            elif label not in COLOR_NAMES:
                errors.append(f"baris {no}: label {label!r} bukan salah satu {COLOR_NAMES}")
            elif key in out:
                errors.append(f"baris {no}: ({key[0]}, {key[1]}) ganda")
            else:
                out[key] = label
    if errors:
        raise VisionEvalError(f"{path.as_posix()}:\n  " + "\n  ".join(errors))
    return out


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Kappa Cohen dua penilai; None bila tidak terdefinisi (kosong atau peluang sepakat 1)."""
    if not a or len(a) != len(b):
        return None
    labels = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum((a.count(k) / n) * (b.count(k) / n) for k in labels)
    if pe >= 1.0:
        return None
    return (po - pe) / (1.0 - pe)


@dataclass
class Agreement:
    agreed: dict[Key, str]
    n_both: int
    n_disagree: int
    only_first: list[Key]
    only_second: list[Key]
    kappa: float | None

    def summary(self) -> dict[str, Any]:
        return {
            "kappa": self.kappa,
            "n_dinilai_keduanya": self.n_both,
            "n_sepakat": len(self.agreed),
            "n_tidak_sepakat": self.n_disagree,
            "n_hanya_penilai1": len(self.only_first),
            "n_hanya_penilai2": len(self.only_second),
        }


def agreement(first: Mapping[Key, str], second: Mapping[Key, str]) -> Agreement:
    both = sorted(set(first) & set(second))
    a = [first[k] for k in both]
    b = [second[k] for k in both]
    agreed = {k: first[k] for k in both if first[k] == second[k]}
    return Agreement(
        agreed,
        len(both),
        len(both) - len(agreed),
        sorted(set(first) - set(second)),
        sorted(set(second) - set(first)),
        cohen_kappa(a, b),
    )


# --- metrik -------------------------------------------------------------------------------


def confusion(true: Sequence[str], pred: Sequence[str | None]) -> np.ndarray:
    """Baris = label benar (COLOR_NAMES), kolom = prediksi (COLOR_NAMES + tanpa prediksi)."""
    m = np.zeros((len(COLOR_NAMES), len(COLOR_NAMES) + 1), dtype=np.int64)
    for t, p in zip(true, pred, strict=True):
        m[COLOR_NAMES.index(t), len(COLOR_NAMES) if p is None else COLOR_NAMES.index(p)] += 1
    return m


def f1_scores(true: Sequence[str], pred: Sequence[str | None]) -> dict[str, dict[str, float]]:
    """Per label (gabungan label benar dan prediksi): n, benar, recall, presisi, F1."""
    labels = [c for c in COLOR_NAMES if c in set(true) | {p for p in pred if p is not None}]
    out = {}
    for c in labels:
        tp = sum(t == c and p == c for t, p in zip(true, pred, strict=True))
        n_true = sum(t == c for t in true)
        n_pred = sum(p == c for p in pred)
        recall = tp / n_true if n_true else 0.0
        precision = tp / n_pred if n_pred else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out[c] = {"n": n_true, "benar": tp, "recall": recall, "presisi": precision, "f1": f1}
    return out


def macro_f1(true: Sequence[str], pred: Sequence[str | None]) -> float:
    scores = f1_scores(true, pred)
    return float(np.mean([s["f1"] for s in scores.values()])) if scores else 0.0


def accuracy(true: Sequence[str], pred: Sequence[str | None]) -> float:
    return sum(t == p for t, p in zip(true, pred, strict=True)) / len(true) if true else 0.0


# --- pencocokan orang dan prediksi --------------------------------------------------------


def match_people(gt: np.ndarray, tracks: Sequence[PersonTrack]) -> dict[int, PersonTrack]:
    """Kotak label -> deteksi dengan IoU tertinggi (>= 0,5), satu deteksi per kotak."""
    if not len(gt) or not tracks:
        return {}
    ious = iou_matrix(gt, np.asarray([t.box_xyxy for t in tracks]))
    pairs = sorted(
        ((ious[g, d], g, d) for g in range(len(gt)) for d in range(len(tracks))), reverse=True
    )
    out: dict[int, PersonTrack] = {}
    used: set[int] = set()
    for iou, g, d in pairs:
        if iou < MATCH_IOU:
            break
        if g not in out and d not in used:
            out[g] = tracks[d]
            used.add(d)
    return out


@dataclass(frozen=True)
class Prediction:
    top: str | None
    majority: float


@dataclass
class ComboRow:
    region: str
    method: str
    n: int = 0
    accuracy: float = 0.0
    macro_f1: float = 0.0
    n_no_pred: int = 0

    @property
    def name(self) -> str:
        return f"{self.region}_{self.method}"

    def row(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "metode": self.method,
            "n": self.n,
            "akurasi": f"{self.accuracy:.4f}",
            "macro_f1": f"{self.macro_f1:.4f}",
            "n_tanpa_prediksi": self.n_no_pred,
        }


def select_combo(rows: Sequence[ComboRow]) -> tuple[ComboRow | None, list[str]]:
    """Tahap 1 aturan E-08 -> (pemenang, alasan)."""
    valid = [r for r in rows if r.n > 0]
    if not valid:
        return None, ["tidak ada frame sepakat yang terdeteksi"]
    best = max(valid, key=lambda r: (r.macro_f1, r.accuracy, (r.region, r.method) == ADR_CHOICE))
    reasons = [f"macro-F1 tertinggi: {best.name} ({best.macro_f1:.4f})"]
    tied = [r for r in valid if r.macro_f1 == best.macro_f1]
    if len(tied) > 1:
        reasons.append(
            "seri macro-F1: " + ", ".join(r.name for r in tied) + " -> akurasi, lalu pilihan ADR"
        )
    return best, reasons


def sweep_min_majority(
    true: Sequence[str], preds: Sequence[Prediction], grid: Sequence[float] = MIN_MAJORITY_GRID
) -> list[dict[str, Any]]:
    rows = []
    for m in grid:
        named = [
            (t, p.top)
            for t, p in zip(true, preds, strict=True)
            if p.top is not None and p.majority >= m
        ]
        correct = sum(t == p for t, p in named)
        rows.append(
            {
                "min_majority": m,
                "n": len(true),
                "disebut": len(named),
                "benar": correct,
                "presisi": correct / len(named) if named else None,
                "cakupan": len(named) / len(true) if true else None,
            }
        )
    return rows


def select_min_majority(rows: Sequence[dict[str, Any]]) -> float | None:
    """Presisi tertinggi; seri -> nilai lebih kecil; tanpa sebutan warna tidak bisa dipilih."""
    valid = [r for r in rows if r["presisi"] is not None]
    if not valid:
        return None
    return min(valid, key=lambda r: (-r["presisi"], r["min_majority"]))["min_majority"]


def coverage(preds: Sequence[Prediction]) -> float | None:
    """Persen sapaan berwarna tanpa min_majority (lut_mean: ada warna bila area berpiksel)."""
    return sum(p.top is not None for p in preds) / len(preds) if preds else None


# --- run ----------------------------------------------------------------------------------


def _f(x: float | None) -> str:
    return "" if x is None else f"{x:.4f}"


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def predict_items(
    frames: Sequence[VisionFrame],
    keys: Sequence[Key],
    predictor: Predictor,
    regions: Mapping[str, ClothingRegion],
    namers: Mapping[str, ColorNamer],
    images: Callable[[VisionFrame], np.ndarray],
) -> dict[Key, dict[str, Prediction]]:
    """Prediksi per (frame, track) per kombinasi; orang tanpa deteksi cocok tidak ada di hasil."""
    by_frame: dict[str, list[int]] = {}
    for fid, tr in keys:
        by_frame.setdefault(fid, []).append(tr)
    frame_of = {f.id: f for f in frames}
    unknown = sorted(set(by_frame) - set(frame_of))
    if unknown:
        raise VisionEvalError(f"frame tidak ada di manifest: {', '.join(unknown)}")
    out: dict[Key, dict[str, Prediction]] = {}
    for fid, tracks_wanted in by_frame.items():
        frame = frame_of[fid]
        image = images(frame)
        h, w = image.shape[:2]
        gt = read_yolo_labels(frame.label_file, w, h)
        bad = [t for t in tracks_wanted if t >= len(gt)]
        if bad:
            raise VisionEvalError(f"{fid}: track {bad} melebihi {len(gt)} baris label")
        matched = match_people(gt, predictor(image))
        for tr in tracks_wanted:
            person = matched.get(tr)
            if person is None:
                continue
            preds: dict[str, Prediction] = {}
            for rname, region in regions.items():
                pixels = region.extract(image, person)
                for mname, namer in namers.items():
                    if pixels is None or pixels.size == 0:
                        preds[f"{rname}_{mname}"] = Prediction(None, 0.0)
                        continue
                    result = namer.name(pixels)
                    dist = np.asarray(result.distribution, dtype=float)
                    top = result_from_distribution(dist, 0.0, result.pixels)
                    preds[f"{rname}_{mname}"] = Prediction(top.top, top.majority)
            out[(fid, tr)] = preds
        del image  # N-08
    return out


def verdict_markdown(
    agree: Agreement,
    n_undetected: int,
    rows: Sequence[ComboRow],
    winner: ComboRow | None,
    reasons: list[str],
    sweep: list[dict[str, Any]],
    chosen: float | None,
    winner_coverage: float | None,
    note: str | None,
) -> str:
    lines = ["# E-08 verdict: warna pakaian atas", ""]
    if note:
        lines += [f"Catatan: {note}", ""]
    k = agree.kappa
    lines += [
        E08_RULE,
        "",
        (
            f"Kappa Cohen = {'-' if k is None else f'{k:.3f}'} atas {agree.n_both} pasangan; "
            f"{len(agree.agreed)} sepakat, {agree.n_disagree} tidak sepakat (dikeluarkan), "
            f"{len(agree.only_first)} hanya penilai 1, {len(agree.only_second)} hanya penilai 2, "
            f"{n_undetected} sepakat tetapi tidak terdeteksi (dikeluarkan)."
        ),
        "",
        "| region | metode | n | akurasi | macro-F1 | tanpa prediksi |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        x = r.row()
        lines.append(
            f"| {r.region} | {r.method} | {r.n} | {x['akurasi']} | {x['macro_f1']} | "
            f"{r.n_no_pred} |"
        )
    lines += ["", "## Keputusan", ""] + [f"- {r}" for r in reasons]
    if winner is not None and winner.method == "lut_vote":
        lines += [
            "",
            f"min_majority pada {winner.name}:",
            "",
            "| min_majority | disebut | benar | presisi | cakupan |",
            "| --- | --- | --- | --- | --- |",
        ]
        for s in sweep:
            lines.append(
                f"| {s['min_majority']} | {s['disebut']} | {s['benar']} | "
                f"{_f(s['presisi']) or '-'} | {_f(s['cakupan']) or '-'} |"
            )
    elif winner is not None:
        lines += [
            "",
            (
                f"Pemenang {winner.name}: sweep min_majority dilewati (amandemen 1), cakupan "
                f"{_f(winner_coverage) or '-'}. Keterbatasan: sapaan selalu menyebut warna."
            ),
        ]
    lines.append("")
    if winner is None:
        lines.append("**Tidak ada pemenang.**")
    elif winner.method == "lut_mean":
        lines.append(
            f"**vision.region = {winner.region}, vision.color.method = lut_mean "
            "(min_majority tidak berlaku)**"
        )
    elif chosen is not None:
        lines.append(
            f"**vision.region = {winner.region}, vision.color.method = lut_vote, "
            f"vision.color.min_majority = {chosen}**"
        )
    else:
        lines.append(
            f"**vision.region = {winner.region}, vision.color.method = lut_vote; "
            "min_majority tidak bisa dipilih (tidak ada warna yang disebut)**"
        )
    return "\n".join(lines) + "\n"


def run_color(
    frames: Sequence[VisionFrame],
    first: Mapping[Key, str],
    second: Mapping[Key, str],
    predictor: Predictor,
    regions: Mapping[str, ClothingRegion],
    namers: Mapping[str, ColorNamer],
    run_dir: Path,
    info: dict[str, Any],
    images: Callable[[VisionFrame], np.ndarray] | None = None,
    area_region: Callable[[str, Mapping[str, float]], ClothingRegion] | None = None,
) -> tuple[list[ComboRow], ComboRow | None, float | None]:
    """area_region: bila diberi, jalankan juga grid area baju (amandemen 3 Nov 2026 bagian C)
    pada pemenang tahap 1; region dibuat dengan fungsi ini (mica.vision.worker.make_region)."""
    from mica.eval import vision

    images = images or (lambda f: vision.read_image(f.file))
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    agree = agreement(first, second)
    preds = predict_items(frames, sorted(agree.agreed), predictor, regions, namers, images)
    detected = [k for k in sorted(agree.agreed) if k in preds]
    true = [agree.agreed[k] for k in detected]
    rows: list[ComboRow] = []
    per_color = []
    for rname in regions:
        for mname in namers:
            combo = f"{rname}_{mname}"
            pred = [preds[k][combo].top for k in detected]
            rows.append(
                ComboRow(
                    rname,
                    mname,
                    len(true),
                    accuracy(true, pred),
                    macro_f1(true, pred),
                    sum(p is None for p in pred),
                )
            )
            for c, s in f1_scores(true, pred).items():
                per_color.append(
                    {
                        "region": rname,
                        "metode": mname,
                        "warna": c,
                        "n": s["n"],
                        "benar": s["benar"],
                        "akurasi_warna": _f(s["recall"]),
                        "presisi": _f(s["presisi"]),
                        "f1": _f(s["f1"]),
                    }
                )
            m = confusion(true, pred)
            cm_rows = [
                {
                    "label_benar": c,
                    **{p: int(v) for p, v in zip((*COLOR_NAMES, NO_PRED), m[i], strict=True)},
                }
                for i, c in enumerate(COLOR_NAMES)
            ]
            _write_csv(run_dir / f"confusion_{combo}.csv", cm_rows)
    winner, reasons = select_combo(rows)
    winner_preds = [preds[k][winner.name] for k in detected] if winner else []
    # amandemen 1: sweep min_majority hanya untuk lut_vote
    sweep = sweep_min_majority(true, winner_preds) if winner and winner.method == "lut_vote" else []
    chosen = select_min_majority(sweep) if sweep else None
    winner_coverage = coverage(winner_preds)
    _write_csv(run_dir / "summary.csv", [r.row() for r in rows])
    fields = ["region", "metode", "warna", "n", "benar", "akurasi_warna", "presisi", "f1"]
    _write_csv(run_dir / "per_color.csv", per_color, fields)
    sweep_fields = ["min_majority", "n", "disebut", "benar", "presisi", "cakupan"]
    _write_csv(
        run_dir / "min_majority.csv",
        [{**s, "presisi": _f(s["presisi"]), "cakupan": _f(s["cakupan"])} for s in sweep],
        sweep_fields,
    )
    items = []
    for k in sorted(set(first) | set(second)):
        l1, l2 = first.get(k), second.get(k)
        status = (
            "hanya penilai 1"
            if l2 is None
            else "hanya penilai 2"
            if l1 is None
            else "tidak sepakat"
            if l1 != l2
            else "sepakat"
            if k in preds
            else "tidak terdeteksi"
        )
        row = {
            "frame": k[0],
            "track": k[1],
            "label_penilai1": l1 or "",
            "label_penilai2": l2 or "",
            "status": status,
        }
        for combo, p in preds.get(k, {}).items():
            row[f"pred_{combo}"] = p.top or ""
            row[f"mayoritas_{combo}"] = f"{p.majority:.3f}"
        items.append(row)
    item_fields = ["frame", "track", "label_penilai1", "label_penilai2", "status"]
    item_fields += [f"{p}_{r.name}" for r in rows for p in ("pred", "mayoritas")]
    _write_csv(run_dir / "per_item.csv", items, item_fields)
    n_undetected = len(agree.agreed) - len(detected)
    (run_dir / "agreement.json").write_text(
        json.dumps(
            {**agree.summary(), "n_sepakat_tidak_terdeteksi": n_undetected},
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "verdict.md").write_text(
        verdict_markdown(
            agree,
            n_undetected,
            rows,
            winner,
            reasons,
            sweep,
            chosen,
            winner_coverage,
            info.get("note"),
        ),
        encoding="utf-8",
    )
    payload = {
        **info,
        "experiment": EXPERIMENT,
        "rule": E08_RULE,
        "amendment": "amandemen 1 E-08 (18 Okt 2026): HsvRuleNamer dihapus, lut_vote vs lut_mean",
        "labels": list(COLOR_NAMES),
        "region_values": TRIAL_VALUES,
        "region_values_source": "nilai coba SDD bagian 12 (docs/E-08.md)",
        "match_iou": MATCH_IOU,
        "metric": "prediksi = warna teratas tanpa min_majority; macro-F1 atas gabungan label "
        "benar dan prediksi; area tanpa piksel = tanpa prediksi (salah)",
        "agreement": {**agree.summary(), "n_sepakat_tidak_terdeteksi": n_undetected},
        "summary": [r.row() for r in rows],
        "decision": {
            "region": winner.region if winner else None,
            "method": winner.method if winner else None,
            "min_majority": chosen,
            "coverage": winner_coverage if winner and winner.method == "lut_mean" else None,
            "reasons": reasons,
        },
        "min_majority_sweep": sweep,
    }
    if area_region is not None and winner is not None:
        people = match_items(frames, detected, predictor, images)
        area = run_area_grid(winner, namers, frames, people, agree.agreed, images, area_region)
        payload["area_grid"] = write_area_grid(run_dir, area)
    (run_dir / "run.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return rows, winner, chosen


# --- grid area baju (amandemen 3 Nov 2026, bagian C: tahap 2a, 2b, 3) ---------------------

AREA_AMENDMENT = "docs/AMANDEMEN-2026-11-03.md bagian C"
# kandidat dipilih pengembang sebelum data, berpusat pada nilai coba (TRIAL_VALUES)
AREA_GRID: dict[str, tuple[float, ...]] = {
    "keypoint_torso.min_kp_conf": (0.3, 0.5, 0.7),
    "keypoint_torso.shrink": (0.10, 0.15, 0.20),
    "keypoint_torso.torso_aspect": (1.0, 1.2, 1.4),
    "box_upper.top": (0.30, 0.35, 0.40),
    "box_upper.bottom": (0.60, 0.65, 0.70),
    "box_upper.side": (0.20, 0.25, 0.30),
}
STAGE_2A = ("keypoint_torso.min_kp_conf", "keypoint_torso.shrink", "keypoint_torso.torso_aspect")
STAGE_2B = ("box_upper.top", "box_upper.bottom", "box_upper.side")
SOURCES = ("keypoint", "keypoint+box", "fallback", "box", "none")
# sumber area yang dipengaruhi tiap kunci (src/mica/vision/region.py). shrink dipakai
# KeypointTorsoRegion._torso untuk "keypoint" dan "keypoint+box"; min_kp_conf menentukan sumber
# sehingga selalu berpengaruh (None)
AFFECTS: dict[str, frozenset[str] | None] = {
    "keypoint_torso.min_kp_conf": None,
    "keypoint_torso.shrink": frozenset({"keypoint", "keypoint+box"}),
    "keypoint_torso.torso_aspect": frozenset({"keypoint+box"}),
    "box_upper.top": frozenset({"fallback", "box"}),
    "box_upper.bottom": frozenset({"fallback", "box"}),
    "box_upper.side": frozenset({"fallback", "box"}),
}
AREA_FIELDS = (
    "tahap", *AREA_GRID, "n", "akurasi", "macro_f1", "n_tanpa_prediksi",
    *(f"n_{s}" for s in SOURCES), "jarak_nilai_coba", "pemenang",
)  # fmt: skip
STAGE_KEYS = {"2a": STAGE_2A, "2b": STAGE_2B}


@dataclass
class AreaRow:
    stage: str
    values: dict[str, float]  # keenam kunci area
    n: int
    accuracy: float
    macro_f1: float
    n_no_pred: int
    sources: dict[str, int]
    preds: list[Prediction]

    def distance(self) -> int:
        """Jumlah jarak langkah grid ke nilai coba untuk kunci tahap ini."""
        return sum(
            abs(AREA_GRID[k].index(self.values[k]) - AREA_GRID[k].index(TRIAL_VALUES[k]))
            for k in STAGE_KEYS[self.stage]
        )

    def sort_key(self) -> tuple[Any, ...]:
        """Aturan tahap 2a/2b: macro-F1 tertinggi -> akurasi -> paling dekat nilai coba ->
        nilai lebih kecil menurut urutan kunci."""
        keys = STAGE_KEYS[self.stage]
        return (-self.macro_f1, -self.accuracy, self.distance(),
                tuple(self.values[k] for k in keys))  # fmt: skip

    def row(self, winner: bool) -> dict[str, Any]:
        return {
            "tahap": self.stage, **self.values, "n": self.n, "akurasi": f"{self.accuracy:.4f}",
            "macro_f1": f"{self.macro_f1:.4f}", "n_tanpa_prediksi": self.n_no_pred,
            **{f"n_{s}": self.sources.get(s, 0) for s in SOURCES},
            "jarak_nilai_coba": self.distance(), "pemenang": int(winner),
        }  # fmt: skip


def stage_combos(stage: str, base: Mapping[str, float]) -> list[dict[str, float]]:
    """Semua kombinasi kunci tahap ini (3 x 3 x 3), kunci lain dari base."""
    import itertools

    keys = STAGE_KEYS[stage]
    return [
        {**base, **dict(zip(keys, values, strict=True))}
        for values in itertools.product(*(AREA_GRID[k] for k in keys))
    ]


def match_items(
    frames: Sequence[VisionFrame],
    keys: Sequence[Key],
    predictor: Predictor,
    images: Callable[[VisionFrame], np.ndarray],
) -> dict[Key, PersonTrack]:
    """Deteksi sekali per frame; (frame, track) -> deteksi yang cocok dengan kotak label."""
    by_frame: dict[str, list[int]] = {}
    for fid, tr in keys:
        by_frame.setdefault(fid, []).append(tr)
    frame_of = {f.id: f for f in frames}
    out: dict[Key, PersonTrack] = {}
    for fid, wanted in by_frame.items():
        image = images(frame_of[fid])
        h, w = image.shape[:2]
        matched = match_people(read_yolo_labels(frame_of[fid].label_file, w, h), predictor(image))
        out.update({(fid, tr): matched[tr] for tr in wanted if tr in matched})
        del image  # N-08
    return out


def _name(namer: ColorNamer, pixels: np.ndarray | None) -> Prediction:
    """Sama dengan predict_items: warna teratas tanpa min_majority."""
    if pixels is None or pixels.size == 0:
        return Prediction(None, 0.0)
    result = namer.name(pixels)
    top = result_from_distribution(np.asarray(result.distribution, dtype=float), 0.0,
                                   result.pixels)  # fmt: skip
    return Prediction(top.top, top.majority)


def evaluate_area(
    stage: str,
    combos: Sequence[dict[str, float]],
    region_name: str,
    namer: ColorNamer,
    frames: Sequence[VisionFrame],
    people: Mapping[Key, PersonTrack],
    true: Mapping[Key, str],
    images: Callable[[VisionFrame], np.ndarray],
    make_region: Callable[[str, Mapping[str, float]], ClothingRegion],
) -> list[AreaRow]:
    """Satu pembacaan gambar per frame; semua kombinasi dihitung untuk frame itu."""
    keys = sorted(people)
    regions = [make_region(region_name, c) for c in combos]
    preds: list[dict[Key, Prediction]] = [{} for _ in combos]
    sources: list[dict[str, int]] = [dict.fromkeys(SOURCES, 0) for _ in combos]
    frame_of = {f.id: f for f in frames}
    for fid in sorted({k[0] for k in keys}):
        image = images(frame_of[fid])
        for key in (k for k in keys if k[0] == fid):
            person = people[key]
            for i, region in enumerate(regions):
                located = region.locate(image.shape, person)
                sources[i][located[1] if located else "none"] += 1
                preds[i][key] = _name(namer, region.extract(image, person))
        del image  # N-08
    labels = [true[k] for k in keys]
    rows = []
    for combo, pred, src in zip(combos, preds, sources, strict=True):
        tops = [pred[k].top for k in keys]
        rows.append(AreaRow(stage, dict(combo), len(keys), accuracy(labels, tops),
                            macro_f1(labels, tops), sum(t is None for t in tops), src,
                            [pred[k] for k in keys]))  # fmt: skip
    return rows


def unswept_keys(rows: Sequence[AreaRow], stage: str) -> list[str]:
    """Kunci yang sumber areanya 0 item di semua kombinasi tahap ini (bila data kurang)."""
    out = []
    for k in STAGE_KEYS[stage]:
        affected = AFFECTS[k]
        if affected is None:
            continue
        if all(sum(r.sources.get(s, 0) for s in affected) == 0 for r in rows):
            out.append(k)
    return out


def choose_area(rows: Sequence[AreaRow], stage: str) -> tuple[AreaRow, list[str]]:
    """Pemenang tahap; kunci tanpa data dikunci pada nilai coba (bukan dipilih dari data)."""
    fixed = unswept_keys(rows, stage)
    allowed = [r for r in rows if all(r.values[k] == TRIAL_VALUES[k] for k in fixed)]
    return min(allowed, key=lambda r: r.sort_key()), fixed


@dataclass
class AreaResult:
    region: str
    method: str
    values: dict[str, float]
    rows: list[AreaRow]
    unswept: dict[str, list[str]]
    min_majority_sweep: list[dict[str, Any]]
    min_majority: float | None
    winners: dict[str, AreaRow]


def run_area_grid(
    winner: ComboRow,
    namers: Mapping[str, ColorNamer],
    frames: Sequence[VisionFrame],
    people: Mapping[Key, PersonTrack],
    true: Mapping[Key, str],
    images: Callable[[VisionFrame], np.ndarray],
    make_region: Callable[[str, Mapping[str, float]], ClothingRegion],
) -> AreaResult:
    """Tahap 2a (hanya keypoint_torso), 2b, lalu 3 (min_majority, hanya lut_vote)."""
    namer = namers[winner.method]
    values = dict(TRIAL_VALUES)
    rows: list[AreaRow] = []
    unswept: dict[str, list[str]] = {}
    winners: dict[str, AreaRow] = {}
    stages = ["2a", "2b"] if winner.region == "keypoint_torso" else ["2b"]
    for stage in stages:
        stage_rows = evaluate_area(stage, stage_combos(stage, values), winner.region, namer,
                                   frames, people, true, images, make_region)  # fmt: skip
        best, fixed = choose_area(stage_rows, stage)
        values = dict(best.values)
        rows += stage_rows
        unswept[stage] = fixed
        winners[stage] = best
    final = winners[stages[-1]]
    labels = [true[k] for k in sorted(people)]
    sweep = sweep_min_majority(labels, final.preds) if winner.method == "lut_vote" else []
    return AreaResult(winner.region, winner.method, values, rows, unswept, sweep,
                      select_min_majority(sweep) if sweep else None, winners)  # fmt: skip


def area_verdict(result: AreaResult) -> str:
    lines = [
        "# E-08 grid area baju (tahap 2a, 2b, 3)",
        "",
        f"Aturan: {AREA_AMENDMENT}. Region {result.region}, metode {result.method} (tahap 1).",
        (
            "Tahap 2a/2b: macro-F1 tertinggi -> akurasi -> paling dekat nilai coba -> nilai lebih "
            "kecil. Kandidat dipilih pengembang sebelum data, berpusat pada nilai coba."
        ),
        "",
    ]
    for stage, best in result.winners.items():
        fixed = result.unswept.get(stage) or []
        note = f"; tidak di-sweep (0 item): {', '.join(fixed)}" if fixed else ""
        lines.append(
            f"- tahap {stage}: macro-F1 {best.macro_f1:.4f}, akurasi {best.accuracy:.4f}{note}"
        )
    lines += ["", "Nilai terpilih:", ""]
    lines += [f"- vision.{k} = {result.values[k]:g}" for k in AREA_GRID]
    if result.method == "lut_vote":
        lines += ["", "Tahap 3 min_majority (parameter akhir):", "",
                  "| min_majority | disebut | benar | presisi | cakupan |",
                  "| --- | --- | --- | --- | --- |"]  # fmt: skip
        for s in result.min_majority_sweep:
            lines.append(f"| {s['min_majority']} | {s['disebut']} | {s['benar']} | "
                         f"{_f(s['presisi']) or '-'} | {_f(s['cakupan']) or '-'} |")  # fmt: skip
        mm = result.min_majority
        lines += ["", f"- vision.color.min_majority = {'-' if mm is None else mm}"]
    else:
        lines += ["", "Tahap 3 dilewati (lut_mean, amandemen 1 E-08)."]
    if "2a" in result.winners:
        kp = result.values["keypoint_torso.min_kp_conf"]
        lines += ["", f"Untuk E-07 bagian 2: --min-kp-conf {kp:g}"]
    else:
        lines += ["", ("Tahap 2a tidak dijalankan (region box_upper): E-07 bagian 2 memakai "
                  "--min-kp-conf 0.5")]  # fmt: skip
    return "\n".join(lines) + "\n"


def write_area_grid(run_dir: Path, result: AreaResult) -> dict[str, Any]:
    """area_grid.csv (satu baris per kombinasi), area_verdict.md; kembalikan isi run.json."""
    rows = [r.row(r is result.winners[r.stage]) for r in result.rows]
    _write_csv(Path(run_dir) / "area_grid.csv", rows, list(AREA_FIELDS))
    (Path(run_dir) / "area_verdict.md").write_text(area_verdict(result), encoding="utf-8")
    return {
        "amendment": AREA_AMENDMENT,
        "grid": {k: list(v) for k, v in AREA_GRID.items()},
        "stages": list(result.winners),
        "n_combinations": len(result.rows),
        "values": result.values,
        "unswept": result.unswept,
        "min_majority_sweep": result.min_majority_sweep,
        "min_majority": result.min_majority,
        "min_kp_conf_for_e07": result.values["keypoint_torso.min_kp_conf"],
    }


# --- split tuning/laporan dan laporan akhir (amandemen kedua bagian C) ---------------------

REPORT_AMENDMENT = "docs/AMANDEMEN-2026-11-03b.md bagian C dan catatannya"
MIN_N_CONCLUDE = 10  # catatan 3 Nov: n < 10 di LAPORAN -> "data tidak cukup untuk disimpulkan"
NOT_ENOUGH = "data tidak cukup untuk disimpulkan"
REPORT_FIELDS = ("warna", "n", "benar", "akurasi", "wilson_bawah", "wilson_atas", "catatan")


def split_ids(dataset: Path, split: str) -> set[str]:
    """ID frame dengan field split = split di manifest (prep-peta)."""
    from mica.eval.vision import read_manifest

    rows = read_manifest(Path(dataset) / "manifest.jsonl")
    if any("split" not in r for r in rows):
        raise VisionEvalError("--split butuh field split di setiap baris manifest (prep-peta)")
    return {str(r["id"]) for r in rows if r["split"] == split}


def winner_from_run(run_dir: Path) -> dict[str, Any]:
    """Nilai pemenang dari run.json split tuning: region, metode, nilai area, min_majority."""
    path = Path(run_dir) / "run.json"
    if not path.is_file():
        raise VisionEvalError(f"{path.as_posix()} tidak ada")
    run = json.loads(path.read_text(encoding="utf-8"))
    if run.get("split") != "tuning":
        raise VisionEvalError(f"{path.as_posix()}: bukan run split tuning")
    decision = run.get("decision") or {}
    if not decision.get("region"):
        raise VisionEvalError(f"{path.as_posix()}: run tuning tanpa pemenang")
    area = run.get("area_grid")
    if area is None:
        raise VisionEvalError(f"{path.as_posix()}: run tuning tanpa --area-grid")
    return {
        "region": decision["region"],
        "method": decision["method"],
        "values": area["values"],
        "min_majority": area["min_majority"],
        "from_run": path.parent.as_posix(),
    }


def _wilson(k: int, n: int) -> tuple[float | None, float | None]:
    from mica.eval.annotation import wilson_interval

    return wilson_interval(k, n) if n > 0 else (None, None)


@dataclass
class ReportResult:
    per_color: list[dict[str, Any]]
    n_all: int
    n_detected: int
    correct: int
    min_majority: float | None
    named: int
    named_correct: int

    @property
    def n_undetected(self) -> int:
        return self.n_all - self.n_detected


def evaluate_report(
    frames: Sequence[VisionFrame],
    true: Mapping[Key, str],
    predictor: Predictor,
    winner: Mapping[str, Any],
    namers: Mapping[str, ColorNamer],
    images: Callable[[VisionFrame], np.ndarray],
    make_region: Callable[[str, Mapping[str, float]], ClothingRegion],
) -> ReportResult:
    """Nilai pemenang tuning pada split laporan. Orang tidak terdeteksi = gagal (tidak dibuang)."""
    keys = sorted(true)
    people = match_items(frames, keys, predictor, images)
    (row,) = evaluate_area("laporan", [dict(winner["values"])], winner["region"],
                           namers[winner["method"]], frames, people, true, images, make_region)  # fmt: skip
    pred = dict(zip(sorted(people), row.preds, strict=True))
    tops = {k: (pred[k].top if k in pred else None) for k in keys}
    per_color = []
    for color in COLOR_NAMES:
        mine = [k for k in keys if true[k] == color]
        if not mine:
            continue
        k_ok = sum(tops[k] == color for k in mine)
        low, high = _wilson(k_ok, len(mine))
        per_color.append({"warna": color, "n": len(mine), "benar": k_ok,
                          "akurasi": k_ok / len(mine), "wilson_bawah": low, "wilson_atas": high,
                          "catatan": NOT_ENOUGH if len(mine) < MIN_N_CONCLUDE else ""})  # fmt: skip
    mm = winner.get("min_majority")
    named = [k for k in keys if k in pred and pred[k].top is not None
             and (mm is None or pred[k].majority >= mm)]  # fmt: skip
    return ReportResult(per_color, len(keys), len(people), sum(tops[k] == true[k] for k in keys),
                        mm, len(named), sum(pred[k].top == true[k] for k in named))  # fmt: skip


def report_markdown(result: ReportResult, winner: Mapping[str, Any], note: str | None) -> str:
    def pct(x: float | None) -> str:
        return "-" if x is None else f"{x:.4f}"

    lo, hi = _wilson(result.correct, result.n_all)
    det_lo, det_hi = _wilson(result.correct, result.n_detected)
    acc_det = result.correct / result.n_detected if result.n_detected else None
    lines = ["# E-08 laporan akhir (split laporan)", ""]
    if note:
        lines += [f"Catatan: {note}", ""]
    lines += [
        (
            f"Aturan: {REPORT_AMENDMENT}. Nilai pemenang dari run tuning {winner['from_run']}: "
            f"region {winner['region']}, metode {winner['method']}."
        ),
        (
            "Akurasi PETA (potongan CCTV beresolusi rendah) ditafsirkan sebagai batas bawah untuk "
            "kamera MICA."
        ),
        "",
        "| warna | n | benar | akurasi | Wilson 95% | catatan |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in result.per_color:
        lines.append(f"| {r['warna']} | {r['n']} | {r['benar']} | {pct(r['akurasi'])} | "
                     f"{pct(r['wilson_bawah'])}-{pct(r['wilson_atas'])} | {r['catatan']} |")  # fmt: skip
    lines += [
        "",
        (
            f"- Akurasi semua gambar (tidak terdeteksi = gagal): {result.correct}/{result.n_all} = "
            f"{pct(result.correct / result.n_all if result.n_all else None)} "
            f"(Wilson 95% {pct(lo)}-{pct(hi)})"
        ),
        (
            f"- Akurasi gambar terdeteksi: {result.correct}/{result.n_detected} = {pct(acc_det)} "
            f"(Wilson 95% {pct(det_lo)}-{pct(det_hi)})"
        ),
        f"- Tidak terdeteksi YOLO: {result.n_undetected} dari {result.n_all}",
    ]
    if result.min_majority is not None:
        prec = result.named_correct / result.named if result.named else None
        cov = result.named / result.n_all if result.n_all else None
        lines.append(f"- min_majority {result.min_majority}: warna disebut {result.named}, benar "
                     f"{result.named_correct} (presisi {pct(prec)}), cakupan {pct(cov)}")  # fmt: skip
    return "\n".join(lines) + "\n"


def run_report(
    frames: Sequence[VisionFrame],
    first: Mapping[Key, str],
    second: Mapping[Key, str],
    predictor: Predictor,
    winner: Mapping[str, Any],
    namers: Mapping[str, ColorNamer],
    run_dir: Path,
    info: dict[str, Any],
    images: Callable[[VisionFrame], np.ndarray] | None = None,
    make_region: Callable[[str, Mapping[str, float]], ClothingRegion] | None = None,
) -> ReportResult:
    from mica.eval import vision
    from mica.vision.worker import make_region as default_region

    images = images or (lambda f: vision.read_image(f.file))
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    agree = agreement(first, second)
    result = evaluate_report(frames, agree.agreed, predictor, winner, namers, images,
                             make_region or default_region)  # fmt: skip
    _write_csv(run_dir / "report_per_color.csv",
               [{**r, "akurasi": _f(r["akurasi"]), "wilson_bawah": _f(r["wilson_bawah"]),
                 "wilson_atas": _f(r["wilson_atas"])} for r in result.per_color],
               list(REPORT_FIELDS))  # fmt: skip
    (run_dir / "report.md").write_text(report_markdown(result, winner, info.get("note")),
                                       encoding="utf-8")  # fmt: skip
    payload = {**info, "experiment": EXPERIMENT, "amendment": REPORT_AMENDMENT,
               "winner": dict(winner), "agreement": agree.summary(),
               "per_color": result.per_color, "n_all": result.n_all,
               "n_detected": result.n_detected, "n_undetected": result.n_undetected,
               "correct": result.correct, "min_majority": result.min_majority,
               "named": result.named, "named_correct": result.named_correct}  # fmt: skip
    (run_dir / "run.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")  # fmt: skip
    return result
