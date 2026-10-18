"""M-12: python -m mica.eval vision (E-07 bagian deteksi). Aturan di docs/E-07.md (pra-registrasi
18 Okt 2026).

Dataset data/eval/vision/<nama>/: images/, labels/ (YOLO, kelas 0 = person), manifest.jsonl
(id, file, relawan, persetujuan, cahaya, jarak). Frame relawan tidak di-commit (.gitignore) dan
hanya dibaca di memori; hasil berisi angka dan ID saja.

Per model: predict sekali per frame pada conf terkecil (waktu dinding per frame), lalu metrik
gaya COCO satu kelas per conf (kotak di bawah conf dibuang): IoU rata-rata pasangan cocok pada
IoU 0,5, mAP@50, mAP@50:95 (AP interpolasi 101 titik recall), dan bootstrap berpasangan 1000
resample frame dengan seed tetap. Pemenang dipilih mekanis (verdict.md).
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from mica.eval.metrics import percentile
from mica.vision.types import PersonTrack

EXPERIMENT = "E-07"
BOOTSTRAP_SEED = 20261018  # docs/E-07.md, ditetapkan sebelum data
BOOTSTRAP_N = 1000
DEFAULT_CONF = 0.1  # bawaan model.track Ultralytics 8.4 (nilai dev vision.conf)
IOU_THRESHOLDS = tuple(round(0.5 + 0.05 * i, 2) for i in range(10))  # 0,50 ... 0,95
RECALL_POINTS = np.linspace(0.0, 1.0, 101)
USED_MODEL = "yolo26n-pose"  # amandemen 1 E-07: kiosk wajib model dengan keypoint
E07_DETECTION_RULE = (
    "Aturan E-07 deteksi (docs/E-07.md, 18 Okt 2026, amandemen 1): yolo26n-pose dipakai; "
    "yolo26n hanya pembanding biaya model pose. Bila CI 95% bootstrap selisih mAP@50:95 "
    "(yolo26n-pose - yolo26n, conf 0,1, 1000 resample frame berpasangan, seed 20261018) "
    "seluruhnya di bawah 0, tidak ada pergantian otomatis dan hasil dicatat sebagai item "
    "pembimbing. vision.conf = nilai dengan mAP@50:95 tertinggi pada yolo26n-pose; seri -> 0,1, "
    "lalu nilai lebih kecil."
)

Predictor = Callable[[np.ndarray], list[PersonTrack]]


class VisionEvalError(Exception):
    pass


# --- dataset ------------------------------------------------------------------------------


@dataclass(frozen=True)
class VisionFrame:
    id: str
    file: Path
    label_file: Path
    relawan: str
    cahaya: str
    jarak: str


def read_manifest(path: Path) -> list[dict[str, Any]]:
    """manifest.jsonl -> baris; satu baris tanpa persetujuan true menolak seluruh manifest."""
    path = Path(path)
    if not path.is_file():
        raise VisionEvalError(f"{path.as_posix()} tidak ada")
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"baris {no}: bukan JSON ({exc.msg})")
            continue
        rid = str(row.get("id") or f"baris {no}")
        if row.get("persetujuan") is not True:
            errors.append(f"{rid}: persetujuan bukan true (data tanpa persetujuan ditolak)")
        elif not row.get("id") or not row.get("file"):
            errors.append(f"{rid}: id dan file wajib")
        elif rid in seen:
            errors.append(f"{rid}: id ganda")
        else:
            seen.add(rid)
            rows.append(row)
    if errors:
        raise VisionEvalError(f"{path.as_posix()}:\n  " + "\n  ".join(errors))
    if not rows:
        raise VisionEvalError(f"{path.as_posix()}: kosong")
    return rows


def load_frames(dataset: Path) -> list[VisionFrame]:
    dataset = Path(dataset)
    frames = []
    errors = []
    for row in read_manifest(dataset / "manifest.jsonl"):
        missing = [k for k in ("relawan", "cahaya", "jarak") if not row.get(k)]
        if missing:
            errors.append(f"{row['id']}: field wajib kosong: {', '.join(missing)}")
            continue
        image = dataset / row["file"]
        label = dataset / "labels" / f"{Path(row['file']).stem}.txt"
        if not image.is_file():
            errors.append(f"{row['id']}: gambar {image.as_posix()} tidak ada")
        elif not label.is_file():
            errors.append(f"{row['id']}: label {label.as_posix()} tidak ada")
        else:
            frames.append(
                VisionFrame(
                    str(row["id"]),
                    image,
                    label,
                    str(row["relawan"]),
                    str(row["cahaya"]),
                    str(row["jarak"]),
                )
            )
    if errors:
        raise VisionEvalError(f"{dataset.as_posix()}:\n  " + "\n  ".join(errors))
    return frames


def read_yolo_labels(path: Path, width: int, height: int) -> np.ndarray:
    """Label YOLO (0 cx cy w h, ternormalisasi) -> kotak xyxy piksel (n, 4), urutan baris."""
    boxes = []
    for no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 5:
            raise VisionEvalError(f"{Path(path).as_posix()} baris {no}: harus 5 kolom")
        if parts[0] != "0":
            raise VisionEvalError(
                f"{Path(path).as_posix()} baris {no}: kelas {parts[0]}, hanya 0 (person)"
            )
        cx, cy, w, h = (float(v) for v in parts[1:])
        boxes.append(
            (
                (cx - w / 2) * width,
                (cy - h / 2) * height,
                (cx + w / 2) * width,
                (cy + h / 2) * height,
            )
        )
    return np.asarray(boxes, dtype=np.float64).reshape(-1, 4)


def read_image(path: Path) -> np.ndarray:
    """Gambar BGR di memori saja (N-08)."""
    import cv2

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise VisionEvalError(f"{Path(path).as_posix()}: gambar tidak bisa dibaca")
    return image


# --- prediksi -----------------------------------------------------------------------------


def tracks_from_predict(result: Any) -> list[PersonTrack]:
    """Results model.predict (tanpa tracker) -> PersonTrack; track_id = urutan deteksi."""
    from mica.vision.detector import _np

    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return []
    xyxy, conf = _np(boxes.xyxy), _np(boxes.conf)
    keypoints = getattr(result, "keypoints", None)
    kp = _np(keypoints.data) if keypoints is not None else None
    return [
        PersonTrack(
            i,
            tuple(float(v) for v in xyxy[i]),
            float(conf[i]),  # type: ignore[arg-type]
            kp[i] if kp is not None else None,
        )
        for i in range(len(xyxy))
    ]


def ultralytics_predictor(model_file: Path, conf: float, imgsz: int | None) -> Predictor:
    """Predictor CPU kelas person; bobot harus sudah ada (tidak pernah mengunduh)."""
    from mica.vision.detector import (
        DEVICE,
        PERSON_CLASS,
        ModelMissing,
        _load_yolo,
        disable_ultralytics_sync,
    )

    model_file = Path(model_file)
    if not model_file.is_file():
        raise ModelMissing(model_file)
    disable_ultralytics_sync()
    model = _load_yolo(str(model_file))
    kwargs: dict[str, Any] = {
        "conf": conf,
        "classes": [PERSON_CLASS],
        "device": DEVICE,
        "save": False,
        "verbose": False,
    }
    if imgsz is not None:
        kwargs["imgsz"] = imgsz

    def predict(frame: np.ndarray) -> list[PersonTrack]:
        results = model.predict(frame, **kwargs)
        return tracks_from_predict(results[0]) if results else []

    return predict


# --- metrik -------------------------------------------------------------------------------


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU kotak xyxy (n, 4) x (m, 4) -> (n, m)."""
    a = np.asarray(a, dtype=np.float64).reshape(-1, 4)
    b = np.asarray(b, dtype=np.float64).reshape(-1, 4)
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.where(union > 0, union, 1.0), 0.0)


def greedy_match(ious: np.ndarray, threshold: float) -> list[tuple[int, int]]:
    """Baris (deteksi, sudah urut skor turun) dipasangkan ke kolom (label) belum terpakai dengan
    IoU tertinggi bila >= threshold (pencocokan COCO). -> [(deteksi, label)]."""
    used: set[int] = set()
    pairs = []
    for d in range(ious.shape[0]):
        best, best_iou = -1, threshold
        for g in range(ious.shape[1]):
            if g not in used and ious[d, g] >= best_iou:
                best, best_iou = g, ious[d, g]
        if best >= 0:
            used.add(best)
            pairs.append((d, best))
    return pairs


@dataclass(frozen=True)
class FrameMatch:
    """Hasil pencocokan satu frame pada satu conf."""

    scores: np.ndarray  # (k,) urut turun
    tp: np.ndarray  # (len(IOU_THRESHOLDS), k) bool
    n_gt: int
    ious50: tuple[float, ...]  # IoU pasangan cocok pada IoU 0,5


def match_frame(boxes: np.ndarray, scores: np.ndarray, gt: np.ndarray, conf: float) -> FrameMatch:
    keep = np.asarray(scores) >= conf
    boxes, scores = np.asarray(boxes).reshape(-1, 4)[keep], np.asarray(scores)[keep]
    order = np.argsort(-scores, kind="mergesort")
    boxes, scores = boxes[order], scores[order]
    ious = iou_matrix(boxes, gt)
    tp = np.zeros((len(IOU_THRESHOLDS), len(scores)), dtype=bool)
    ious50: tuple[float, ...] = ()
    for i, thr in enumerate(IOU_THRESHOLDS):
        pairs = greedy_match(ious, thr)
        for d, _g in pairs:
            tp[i, d] = True
        if i == 0:
            ious50 = tuple(float(ious[d, g]) for d, g in pairs)
    return FrameMatch(scores, tp, len(gt), ious50)


def average_precision(scores: np.ndarray, tp: np.ndarray, n_gt: int) -> float:
    """AP gaya COCO: presisi berinterpolasi di 101 titik recall. nan bila tanpa label."""
    if n_gt == 0:
        return float("nan")
    if len(scores) == 0:
        return 0.0
    order = np.argsort(-np.asarray(scores), kind="mergesort")
    hits = np.asarray(tp, dtype=bool)[order]
    tps = np.cumsum(hits)
    fps = np.cumsum(~hits)
    recall = tps / n_gt
    precision = tps / (tps + fps)
    precision = np.maximum.accumulate(precision[::-1])[::-1]  # amplop: maks pada recall >= r
    idx = np.searchsorted(recall, RECALL_POINTS, side="left")
    q = np.where(idx < len(precision), precision[np.minimum(idx, len(precision) - 1)], 0.0)
    return float(q.mean())


@dataclass(frozen=True)
class Pooled:
    """Deteksi semua frame digabung sekali, supaya bootstrap cukup mengulang (np.repeat)."""

    scores: np.ndarray  # (k,)
    tp: np.ndarray  # (len(IOU_THRESHOLDS), k)
    frame: np.ndarray  # (k,) indeks frame tiap deteksi
    n_gt: np.ndarray  # (n_frame,)


def pool(matches: Sequence[FrameMatch]) -> Pooled:
    counts = [len(m.scores) for m in matches]
    return Pooled(
        np.concatenate([m.scores for m in matches] or [np.zeros(0)]),
        np.concatenate([m.tp for m in matches], axis=1)
        if matches
        else np.zeros((len(IOU_THRESHOLDS), 0), dtype=bool),
        np.repeat(np.arange(len(matches)), counts),
        np.asarray([m.n_gt for m in matches], dtype=np.int64),
    )


def pooled_map(p: Pooled, weights: np.ndarray | None = None) -> tuple[float, float]:
    """(mAP@50, mAP@50:95); weights = berapa kali tiap frame dipakai (bootstrap)."""
    if weights is None:
        scores, tp, n_gt = p.scores, p.tp, int(p.n_gt.sum())
    else:
        rep = np.asarray(weights)[p.frame]
        scores, tp = np.repeat(p.scores, rep), np.repeat(p.tp, rep, axis=1)
        n_gt = int((np.asarray(weights) * p.n_gt).sum())
    aps = [average_precision(scores, tp[i], n_gt) for i in range(len(IOU_THRESHOLDS))]
    return aps[0], float(np.mean(aps))


def map_scores(matches: Sequence[FrameMatch]) -> tuple[float, float]:
    """(mAP@50, mAP@50:95) dari frame."""
    return pooled_map(pool(matches))


def bootstrap_indices(
    n_frames: int, n: int = BOOTSTRAP_N, seed: int = BOOTSTRAP_SEED
) -> np.ndarray:
    """(n, n_frames) indeks resample dengan pengembalian; sama untuk semua model (berpasangan)."""
    return np.random.default_rng(seed).integers(0, n_frames, size=(n, n_frames))


def bootstrap_map(matches: Sequence[FrameMatch], indices: np.ndarray) -> np.ndarray:
    """mAP@50:95 per resample."""
    pooled = pool(matches)
    out = np.empty(len(indices))
    for r, idx in enumerate(indices):
        out[r] = pooled_map(pooled, np.bincount(idx, minlength=len(matches)))[1]
    return out


def ci95(values: np.ndarray) -> tuple[float, float]:
    finite = np.asarray(values)[np.isfinite(values)]
    if not len(finite):
        return float("nan"), float("nan")
    lo, hi = np.percentile(finite, [2.5, 97.5])
    return float(lo), float(hi)


# --- run ----------------------------------------------------------------------------------


@dataclass
class FramePred:
    boxes: np.ndarray
    scores: np.ndarray
    time_s: float


@dataclass
class ModelRow:
    model: str
    conf: float
    n_frames: int
    n_gt: int
    n_det: int
    iou_mean: float | None
    map50: float
    map50_95: float
    ci_lo: float
    ci_hi: float
    time_p50_s: float
    time_p95_s: float

    @property
    def fps(self) -> float:
        return 1.0 / self.time_p50_s if self.time_p50_s > 0 else float("inf")

    def row(self) -> dict[str, Any]:
        def f(x: float | None) -> str:
            return "" if x is None or not np.isfinite(x) else f"{x:.4f}"

        return {
            "model": self.model,
            "conf": self.conf,
            "n_frame": self.n_frames,
            "n_label": self.n_gt,
            "n_deteksi": self.n_det,
            "iou_mean": f(self.iou_mean),
            "map50": f(self.map50),
            "map50_95": f(self.map50_95),
            "map50_95_ci_lo": f(self.ci_lo),
            "map50_95_ci_hi": f(self.ci_hi),
            "waktu_p50_s": f(self.time_p50_s),
            "waktu_p95_s": f(self.time_p95_s),
            "fps": f(self.fps),
        }


def predict_frames(
    frames: Sequence[VisionFrame],
    images: Callable[[VisionFrame], np.ndarray],
    predictor: Predictor,
    clock: Callable[[], float],
) -> list[FramePred]:
    """Satu panggilan pemanasan (tidak dihitung), lalu predict + waktu dinding per frame."""
    preds = []
    for i, frame in enumerate(frames):
        image = images(frame)
        if i == 0:
            predictor(image)  # pemanasan
        start = clock()
        tracks = predictor(image)
        elapsed = clock() - start
        boxes = np.asarray([t.box_xyxy for t in tracks], dtype=np.float64).reshape(-1, 4)
        preds.append(FramePred(boxes, np.asarray([t.conf for t in tracks]), elapsed))
        del image  # N-08: frame hanya di memori
    return preds


def model_row(
    model: str, conf: float, preds: list[FramePred], gts: list[np.ndarray], indices: np.ndarray
) -> tuple[ModelRow, list[FrameMatch], np.ndarray]:
    matches = [match_frame(p.boxes, p.scores, g, conf) for p, g in zip(preds, gts, strict=True)]
    map50, map5095 = map_scores(matches)
    boots = bootstrap_map(matches, indices)
    lo, hi = ci95(boots)
    ious = [v for m in matches for v in m.ious50]
    times = [p.time_s for p in preds]
    row = ModelRow(
        model,
        conf,
        len(matches),
        sum(m.n_gt for m in matches),
        sum(len(m.scores) for m in matches),
        float(np.mean(ious)) if ious else None,
        map50,
        map5095,
        lo,
        hi,
        percentile(times, 50),
        percentile(times, 95),
    )
    return row, matches, boots


@dataclass
class Decision:
    model: str | None
    conf: float | None
    reasons: list[str] = field(default_factory=list)
    diffs: dict[str, dict[str, float]] = field(default_factory=dict)
    outcome: str | None = None  # pose lebih baik | seri | pembanding lebih tinggi bermakna
    supervisor_item: bool = False  # True: yolo26n lebih tinggi bermakna (amandemen 1)


def select(rows: list[ModelRow], boots: dict[tuple[str, float], np.ndarray]) -> Decision:
    """Aturan E-07 bagian deteksi setelah amandemen 1 (docs/E-07.md), diterapkan mekanis:
    yolo26n-pose dipakai; pembanding yang lebih tinggi bermakna hanya ditandai item pembimbing."""
    base = {r.model: r for r in rows if r.conf == DEFAULT_CONF and np.isfinite(r.map50_95)}
    if USED_MODEL not in base:
        return Decision(
            None,
            None,
            [
                (
                    f"tidak ada mAP@50:95 {USED_MODEL} pada conf {DEFAULT_CONF}; aturan tidak bisa "
                    "diterapkan"
                )
            ],
        )
    pose = base[USED_MODEL]
    decision = Decision(USED_MODEL, None)
    for r in base.values():
        if r is pose:
            continue
        diff = boots[(USED_MODEL, DEFAULT_CONF)] - boots[(r.model, DEFAULT_CONF)]
        lo, hi = ci95(diff)
        decision.diffs[f"{USED_MODEL} - {r.model}"] = {
            "selisih": pose.map50_95 - r.map50_95,
            "ci_lo": lo,
            "ci_hi": hi,
        }
        ci = f"CI 95% selisih {USED_MODEL} - {r.model} = [{lo:.4f}, {hi:.4f}]"
        if hi < 0.0:
            decision.outcome = f"{r.model} lebih tinggi bermakna"
            decision.supervisor_item = True
            decision.reasons.append(
                f"{ci} seluruhnya di bawah 0: {r.model} lebih tinggi bermakna -> ITEM PEMBIMBING; "
                f"tanpa pergantian otomatis, {USED_MODEL} tetap dipakai"
            )
        elif lo > 0.0:
            decision.outcome = decision.outcome or f"{USED_MODEL} lebih baik"
            decision.reasons.append(f"{ci} seluruhnya di atas 0: {USED_MODEL} lebih baik")
        else:
            decision.outcome = decision.outcome or "seri"
            decision.reasons.append(f"{ci} memuat 0: seri, {USED_MODEL} dipakai")
        decision.reasons.append(
            f"biaya model pose: {USED_MODEL} {pose.fps:.2f} FPS vs {r.model} {r.fps:.2f} FPS "
            f"(p50 {pose.time_p50_s:.4f} vs {r.time_p50_s:.4f} s)"
        )
    own = [r for r in rows if r.model == USED_MODEL and np.isfinite(r.map50_95)]
    best = max(r.map50_95 for r in own)
    candidates = [r.conf for r in own if r.map50_95 == best]
    conf = DEFAULT_CONF if DEFAULT_CONF in candidates else min(candidates)
    decision.conf = conf
    decision.reasons.append(
        f"vision.conf pada {USED_MODEL}: "
        + ", ".join(f"{r.conf} -> {r.map50_95:.4f}" for r in sorted(own, key=lambda r: r.conf))
        + f"; dipilih {conf}"
    )
    return decision


def verdict_markdown(rows: list[ModelRow], decision: Decision, note: str | None) -> str:
    lines = ["# E-07 verdict: deteksi", ""]
    if note:
        lines += [f"Catatan: {note}", ""]
    lines += [
        E07_DETECTION_RULE,
        "",
        "| model | conf | mAP@50 | mAP@50:95 | CI 95% | IoU rata-rata | p50 s | p95 s | FPS |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        x = r.row()
        lines.append(
            f"| {r.model} | {r.conf} | {x['map50']} | {x['map50_95']} | "
            f"[{x['map50_95_ci_lo']}, {x['map50_95_ci_hi']}] | {x['iou_mean']} | "
            f"{x['waktu_p50_s']} | {x['waktu_p95_s']} | {x['fps']} |"
        )
    lines += ["", "## Keputusan", ""]
    lines += [f"- {reason}" for reason in decision.reasons]
    if decision.model is None:
        lines += ["", "**Tidak ada keputusan.**", ""]
        return "\n".join(lines)
    lines += ["", f"Hasil perbandingan: {decision.outcome or '-'}."]
    if decision.supervisor_item:
        lines += ["", "**ITEM PEMBIMBING: pembanding tanpa keypoint lebih tinggi bermakna.**"]
    lines += ["", f"**vision.model = {decision.model}, vision.conf = {decision.conf}**", ""]
    return "\n".join(lines)


def condition_rows(
    frames: Sequence[VisionFrame], matches: dict[str, list[FrameMatch]]
) -> list[dict[str, Any]]:
    """mAP per kondisi cahaya dan jarak pada conf bawaan (laporan, bukan aturan)."""
    out = []
    for factor in ("cahaya", "jarak"):
        for value in sorted({getattr(f, factor) for f in frames}):
            idx = [i for i, f in enumerate(frames) if getattr(f, factor) == value]
            for model, ms in matches.items():
                m50, m5095 = map_scores([ms[i] for i in idx])
                out.append(
                    {
                        "model": model,
                        "conf": DEFAULT_CONF,
                        "faktor": factor,
                        "nilai": value,
                        "n_frame": len(idx),
                        "map50": "" if np.isnan(m50) else f"{m50:.4f}",
                        "map50_95": "" if np.isnan(m5095) else f"{m5095:.4f}",
                    }
                )
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_vision(
    frames: Sequence[VisionFrame],
    predictors: dict[str, Callable[[], Predictor]],
    confs: Sequence[float],
    run_dir: Path,
    info: dict[str, Any],
    images: Callable[[VisionFrame], np.ndarray] | None = None,
    clock: Callable[[], float] | None = None,
    progress: Callable[[str], None] = print,
) -> tuple[list[ModelRow], Decision]:
    """predictors: nama model -> factory Predictor pada conf terkecil. Tulis run_dir."""
    import time

    images = images or (lambda f: read_image(f.file))
    clock = clock or time.perf_counter
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    gts = []
    for f in frames:
        image = images(f)
        h, w = image.shape[:2]
        gts.append(read_yolo_labels(f.label_file, w, h))
        del image
    indices = bootstrap_indices(len(frames))
    rows: list[ModelRow] = []
    boots: dict[tuple[str, float], np.ndarray] = {}
    base_matches: dict[str, list[FrameMatch]] = {}
    per_frame = []
    for model, factory in predictors.items():
        progress(f"--- {model}: predict {len(frames)} frame ---")
        preds = predict_frames(frames, images, factory(), clock)
        for f, p, g in zip(frames, preds, gts, strict=True):
            per_frame.append(
                {
                    "frame": f.id,
                    "model": model,
                    "waktu_s": f"{p.time_s:.4f}",
                    "n_label": len(g),
                    "n_deteksi": len(p.scores),
                }
            )
        for conf in sorted(confs):
            row, matches, b = model_row(model, conf, preds, gts, indices)
            rows.append(row)
            boots[(model, conf)] = b
            if conf == DEFAULT_CONF:
                base_matches[model] = matches
            progress(f"  conf {conf}: mAP@50 {row.map50:.4f}, mAP@50:95 {row.map50_95:.4f}")
    decision = select(rows, boots)
    _write_csv(run_dir / "summary.csv", [r.row() for r in rows])
    _write_csv(run_dir / "per_frame.csv", per_frame)
    _write_csv(run_dir / "per_kondisi.csv", condition_rows(frames, base_matches))
    (run_dir / "verdict.md").write_text(
        verdict_markdown(rows, decision, info.get("note")), encoding="utf-8"
    )
    payload = {
        **info,
        "experiment": EXPERIMENT,
        "rule": E07_DETECTION_RULE,
        "metric": "gaya COCO satu kelas: pencocokan greedy per frame urut skor, AP interpolasi "
        "101 titik recall, mAP@50:95 = rata-rata IoU 0,50:0,05:0,95; IoU rata-rata pasangan "
        "cocok pada IoU 0,5",
        "prediction": f"predict sekali per model pada conf {min(confs)}; conf lain = buang "
        "kotak di bawah conf; waktu = satu panggilan predict, satu pemanasan tidak dihitung",
        "bootstrap": {
            "n": BOOTSTRAP_N,
            "seed": BOOTSTRAP_SEED,
            "unit": "frame",
            "paired": True,
            "ci": "percentile 2,5 dan 97,5",
        },
        "summary": [r.row() for r in rows],
        "decision": {
            "model": decision.model,
            "conf": decision.conf,
            "outcome": decision.outcome,
            "supervisor_item": decision.supervisor_item,
            "reasons": decision.reasons,
            "diffs": decision.diffs,
        },
    }
    (run_dir / "run.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return rows, decision
