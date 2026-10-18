"""M-12: python -m mica.eval color (E-08). Aturan di docs/E-08.md (pra-registrasi 18 Okt 2026).

Frame E-07 (data/eval/vision/<nama>/) + colors.csv dan colors_rater2.csv (frame, track,
color_label; track = indeks baris orang di label YOLO). Cohen's kappa antar-penilai; hanya
pasangan yang disepakati masuk akurasi. Orang diambil dari deteksi yolo26n-pose yang cocok
(IoU >= 0,5) dengan kotak label, lalu setiap region x metode menamai warnanya (suara terbanyak,
tanpa min_majority). Pemenang macro-F1, lalu sweep min_majority pada pemenang. Frame hanya di
memori (N-08); hasil berisi angka, ID, dan label saja.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
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
METHODS = ("color_names_lut", "hsv_rules")
ADR_CHOICE = ("keypoint_torso", "color_names_lut")  # pemecah seri terakhir (docs/E-08.md)
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
    "Aturan E-08 (docs/E-08.md, 18 Okt 2026): kombinasi region x metode dengan macro-F1 "
    "tertinggi (tanpa min_majority; seri -> akurasi, lalu keypoint_torso + color_names_lut); "
    "lalu min_majority {0,5; 0,6; 0,7} pada pemenang: presisi (benar / disebut warna) "
    "tertinggi, seri -> nilai lebih kecil. Cakupan selalu dilaporkan."
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
    available: bool
    n: int = 0
    accuracy: float = 0.0
    macro_f1: float = 0.0
    n_no_pred: int = 0
    note: str = ""

    @property
    def name(self) -> str:
        return f"{self.region}_{self.method}"

    def row(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "metode": self.method,
            "tersedia": int(self.available),
            "n": self.n,
            "akurasi": f"{self.accuracy:.4f}" if self.available else "",
            "macro_f1": f"{self.macro_f1:.4f}" if self.available else "",
            "n_tanpa_prediksi": self.n_no_pred if self.available else "",
            "catatan": self.note,
        }


def select_combo(rows: Sequence[ComboRow]) -> tuple[ComboRow | None, ComboRow | None, list[str]]:
    """-> (pemenang menurut aturan, terbaik di antara yang tersedia, alasan)."""
    available = [r for r in rows if r.available and r.n > 0]
    reasons = []
    best = (
        max(
            available,
            key=lambda r: (r.macro_f1, r.accuracy, (r.region, r.method) == ADR_CHOICE),
        )
        if available
        else None
    )
    missing = [r.name for r in rows if not r.available]
    if missing:
        reasons.append(
            "kombinasi tidak tersedia: " + ", ".join(missing) + " -> aturan E-08 "
            "tidak bisa diterapkan penuh, tidak ada pemenang"
        )
        return None, best, reasons
    if best is None:
        reasons.append("tidak ada frame sepakat yang terdeteksi")
        return None, None, reasons
    tied = [r for r in available if r.macro_f1 == best.macro_f1]
    reasons.append(f"macro-F1 tertinggi: {best.name} ({best.macro_f1:.4f})")
    if len(tied) > 1:
        reasons.append(
            "seri macro-F1: " + ", ".join(r.name for r in tied) + " -> akurasi, lalu pilihan ADR"
        )
    return best, best, reasons


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


# --- run ----------------------------------------------------------------------------------


@dataclass
class ItemResult:
    key: Key
    label1: str | None
    label2: str | None
    status: str  # sepakat | tidak sepakat | hanya penilai 1/2 | tidak terdeteksi
    preds: dict[str, Prediction] = field(default_factory=dict)


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
) -> tuple[dict[Key, dict[str, Prediction]], dict[str, str]]:
    """Prediksi per (frame, track) per kombinasi; -> (prediksi, metode tidak tersedia)."""
    by_frame: dict[str, list[int]] = {}
    for fid, tr in keys:
        by_frame.setdefault(fid, []).append(tr)
    frame_of = {f.id: f for f in frames}
    unknown = sorted(set(by_frame) - set(frame_of))
    if unknown:
        raise VisionEvalError(f"frame tidak ada di manifest: {', '.join(unknown)}")
    unavailable: dict[str, str] = {}
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
                    if mname in unavailable:
                        continue
                    try:
                        if pixels is None or pixels.size == 0:
                            preds[f"{rname}_{mname}"] = Prediction(None, 0.0)
                            continue
                        result = namer.name(pixels)
                    except NotImplementedError as exc:
                        unavailable[mname] = str(exc)
                        continue
                    dist = np.asarray(result.distribution, dtype=float)
                    voted = result_from_distribution(dist, 0.0, result.pixels)
                    preds[f"{rname}_{mname}"] = Prediction(voted.top, voted.majority)
            out[(fid, tr)] = preds
        del image  # N-08
    for preds in out.values():  # metode yang gagal di tengah jalan dibuang dari semua item
        for key in [k for k in preds if _method_of(k) in unavailable]:
            preds.pop(key, None)
    return out, unavailable


def _method_of(combo: str) -> str:
    return next(m for m in METHODS if combo.endswith(m))


def verdict_markdown(
    agree: Agreement,
    n_undetected: int,
    rows: Sequence[ComboRow],
    winner: ComboRow | None,
    best: ComboRow | None,
    reasons: list[str],
    sweep: list[dict[str, Any]],
    chosen: float | None,
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
        if r.available:
            lines.append(
                f"| {r.region} | {r.method} | {r.n} | {x['akurasi']} | "
                f"{x['macro_f1']} | {r.n_no_pred} |"
            )
        else:
            lines.append(f"| {r.region} | {r.method} | - | tidak tersedia | - | - |")
    lines += ["", "## Keputusan", ""] + [f"- {r}" for r in reasons]
    target = winner or best
    if target is not None and sweep:
        label = "pemenang" if winner else "terbaik yang tersedia (sementara, bukan keputusan)"
        lines += [
            "",
            f"min_majority pada {target.name} ({label}):",
            "",
            "| min_majority | disebut | benar | presisi | cakupan |",
            "| --- | --- | --- | --- | --- |",
        ]
        for s in sweep:
            lines.append(
                f"| {s['min_majority']} | {s['disebut']} | {s['benar']} | "
                f"{_f(s['presisi']) or '-'} | {_f(s['cakupan']) or '-'} |"
            )
    lines.append("")
    if winner is not None and chosen is not None:
        lines.append(
            f"**vision.region = {winner.region}, vision.color.method = {winner.method}, "
            f"vision.color.min_majority = {chosen}**"
        )
    elif winner is not None:
        lines.append(
            f"**vision.region = {winner.region}, vision.color.method = {winner.method}; "
            "min_majority tidak bisa dipilih (tidak ada warna yang disebut)**"
        )
    else:
        lines.append("**Tidak ada pemenang.**")
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
) -> tuple[list[ComboRow], ComboRow | None, float | None]:
    from mica.eval import vision

    images = images or (lambda f: vision.read_image(f.file))
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    agree = agreement(first, second)
    preds, unavailable = predict_items(
        frames, sorted(agree.agreed), predictor, regions, namers, images
    )
    detected = [k for k in sorted(agree.agreed) if k in preds]
    true = [agree.agreed[k] for k in detected]
    rows: list[ComboRow] = []
    per_color = []
    for rname in regions:
        for mname in namers:
            combo = f"{rname}_{mname}"
            if mname in unavailable:
                rows.append(ComboRow(rname, mname, False, note=unavailable[mname]))
                continue
            pred = [preds[k][combo].top for k in detected]
            rows.append(
                ComboRow(
                    rname,
                    mname,
                    True,
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
    winner, best, reasons = select_combo(rows)
    target = winner or best
    sweep = (
        sweep_min_majority(true, [preds[k][target.name] for k in detected])
        if target is not None
        else []
    )
    chosen = select_min_majority(sweep) if winner is not None else None
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
    combos = [f"{r.region}_{r.method}" for r in rows if r.available]
    item_fields = ["frame", "track", "label_penilai1", "label_penilai2", "status"]
    item_fields += [f"{p}_{c}" for c in combos for p in ("pred", "mayoritas")]
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
            agree, n_undetected, rows, winner, best, reasons, sweep, chosen, info.get("note")
        ),
        encoding="utf-8",
    )
    payload = {
        **info,
        "experiment": EXPERIMENT,
        "rule": E08_RULE,
        "labels": list(COLOR_NAMES),
        "region_values": TRIAL_VALUES,
        "region_values_source": "nilai coba SDD bagian 12 (docs/E-08.md)",
        "match_iou": MATCH_IOU,
        "metric": "prediksi = ColorResult.top tanpa min_majority; macro-F1 atas gabungan label "
        "benar dan prediksi; area tanpa piksel = tanpa prediksi (salah)",
        "agreement": {**agree.summary(), "n_sepakat_tidak_terdeteksi": n_undetected},
        "unavailable": unavailable,
        "summary": [r.row() for r in rows],
        "decision": {
            "region": winner.region if winner else None,
            "method": winner.method if winner else None,
            "min_majority": chosen,
            "reasons": reasons,
        },
        "min_majority_sweep": sweep,
    }
    (run_dir / "run.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return rows, winner, chosen
