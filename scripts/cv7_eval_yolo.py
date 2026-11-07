"""CV-7: evaluasi lapisan YOLO (imgsz 640) dari deteksi tersimpan CV-2b, tanpa prediksi ulang.

python scripts/cv7_eval_yolo.py --data-dir D:/SKRIPSI/datasets/coco
    --run-dir D:/SKRIPSI/cv-hasil/20261030-151542 --log D:/SKRIPSI/cv-hasil/sweep-imgsz.log
    --out D:/SKRIPSI/cv-hasil/cv7-eval-yolo.json

pycocotools COCOeval (person_keypoints_val2017.json, catIds=[1]) atas dets-640.json: box AP@50,
AP@50:95 (all, medium, large), AR@100 large, keypoint AP@50:95 (all, large). Nilai titik dicek
terhadap official_stats 640 di accuracy.json dan blok COCOeval pertama di log (3 desimal).
CI 95% bootstrap persentil per gambar (B=1000, seed 20261030) untuk box AP@50 dan AP@50:95 all,
memakai bootstrap_counts/accumulate dari scripts/cv_imgsz_sweep.py (cara CV-2b). AP@50:95 all
juga harus sama dengan support.box_all.640.ap_ci di accuracy.json (sampel yang sama).
Tidak ada gambar yang dibaca atau ditulis; keluaran hanya angka.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cv_imgsz_sweep", ROOT / "scripts/cv_imgsz_sweep.py")
sweep = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(sweep)

IMGSZ = 640
SEED = sweep.SEED
BOOTSTRAP = sweep.BOOTSTRAP
TOL = 1e-12

# indeks COCOeval.stats (summarize)
BBOX_STATS = {
    "box_ap50_all": 1,
    "box_ap_all": 0,
    "box_ap_medium": 4,
    "box_ap_large": 5,
    "box_ar100_large": 11,
}
KP_STATS = {"keypoint_ap_all": 0, "keypoint_ap_large": 4}

_LINE = re.compile(
    r"Average (Precision|Recall)\s+\((AP|AR)\) @\[ IoU=(\S+)\s*\| area=\s*(\w+) \| "
    r"maxDets=\s*(\d+) \] = (-?[0-9.]+)"
)


def iou50_records(rec: Any) -> Any:
    """EvalRecords hanya ambang IoU 0,50 (baris pertama IOU_THRS) -> accumulate memberi AP@50."""
    if not np.isclose(sweep.IOU_THRS[0], 0.5):
        raise ValueError("IOU_THRS[0] harus 0,50")
    return sweep.EvalRecords(image=rec.image, tps=rec.tps[:1], fps=rec.fps[:1], npig=rec.npig)


def point_metrics(bbox_stats: list[float], kp_stats: list[float]) -> dict[str, float]:
    out = {k: float(bbox_stats[i]) for k, i in BBOX_STATS.items()}
    out.update({k: float(kp_stats[i]) for k, i in KP_STATS.items()})
    return out


def parse_log_blocks(text: str) -> list[list[float]]:
    """Blok summarize COCOeval berurutan (12 baris bbox, 10 baris keypoints) -> daftar stats."""
    blocks: list[list[float]] = []
    current: list[float] = []
    for line in text.splitlines():
        m = _LINE.search(line)
        if m is None:
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(float(m.group(6)))
    if current:
        blocks.append(current)
    return blocks


def compare(
    ours: dict[str, float], reference: dict[str, float], tol: float
) -> dict[str, dict[str, float]]:
    """Kunci yang selisihnya > tol (kosong = cocok)."""
    bad = {}
    for k, v in reference.items():
        if abs(ours[k] - v) > tol:
            bad[k] = {"ours": ours[k], "reference": v}
    return bad


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--log", type=Path, required=True, help="log sweep (UTF-16)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--bootstrap", type=int, default=BOOTSTRAP)
    ap.add_argument("--seed", type=int, default=SEED)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    from pycocotools.coco import COCO

    args = parse_args(argv)
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    timing: dict[str, float] = {}
    accuracy = json.loads((args.run_dir / "accuracy.json").read_text(encoding="utf-8"))
    dets_file = args.run_dir / f"dets-{IMGSZ}.json"

    t0 = time.perf_counter()
    gt = COCO(str(args.data_dir / sweep.ANNOTATIONS))
    img_ids = sweep.select_image_ids(gt.getImgIds(), None)
    dets = json.loads(dets_file.read_text(encoding="utf-8"))
    timing["load_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    b = sweep.coco_records(gt, dets, "bbox", img_ids)
    k = sweep.coco_records(gt, dets, "keypoints", img_ids)
    timing["evaluate_s"] = time.perf_counter() - t0
    del dets

    ours = point_metrics(b["stats"], k["stats"])
    off = accuracy["official_stats"][str(IMGSZ)]
    mismatch_json = compare(ours, point_metrics(off["bbox_stats"], off["keypoints_stats"]), TOL)
    blocks = parse_log_blocks(args.log.read_text(encoding="utf-16"))
    mismatch_log = compare(
        {kk: round(v, 3) for kk, v in ours.items()}, point_metrics(blocks[0], blocks[1]), 1e-9
    )

    rec_all = b["records"]["all"]
    rec50 = iou50_records(rec_all)
    ap50_own, _ = sweep.accumulate(rec50)
    ap_all_own, _ = sweep.accumulate(rec_all)
    if abs(ap50_own - ours["box_ap50_all"]) > 1e-9 or abs(ap_all_own - ours["box_ap_all"]) > 1e-9:
        raise SystemExit("accumulate tidak sama dengan COCOeval (AP@50 / AP all)")

    t0 = time.perf_counter()
    counts = sweep.bootstrap_counts(rec_all.n_images, args.bootstrap, args.seed)
    s50 = np.array([sweep.accumulate(rec50, c)[0] for c in counts])
    s_all = np.array([sweep.accumulate(rec_all, c)[0] for c in counts])
    timing["bootstrap_s"] = time.perf_counter() - t0
    ci50 = sweep.percentile_ci(s50)
    ci_all = sweep.percentile_ci(s_all)
    ref_ci = accuracy["support"]["box_all"][str(IMGSZ)]["ap_ci"]
    ci_all_matches = bool(np.allclose(ci_all, ref_ci, rtol=0, atol=TOL))

    result = {
        "task": "CV-7",
        "started": started,
        "imgsz": IMGSZ,
        "run_dir": str(args.run_dir),
        "dets_file": str(dets_file),
        "dets_sha256": sha256_file(dets_file),
        "annotations": str(args.data_dir / sweep.ANNOTATIONS),
        "cat_ids": [sweep.PERSON_CAT_ID],
        "n_images": rec_all.n_images,
        "metrics": ours,
        "ci95": {"box_ap50_all": ci50, "box_ap_all": ci_all},
        "bootstrap": {"B": args.bootstrap, "seed": args.seed, "method": "percentile, per image"},
        "checks": {
            "mismatch_accuracy_json": mismatch_json,
            "mismatch_log_3dp": mismatch_log,
            "ci_box_ap_all_matches_accuracy_json": ci_all_matches,
            "accuracy_json_ci_box_ap_all": ref_ci,
        },
        "model_sha256": accuracy["environment"]["model_sha256"],
        "environment_cv2b": accuracy["environment"],
        "python_cv7": sys.version,
        "timing": timing,
        "finished": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({kk: result[kk] for kk in ("metrics", "ci95", "checks", "timing")}, indent=1))
    ok = not mismatch_json and not mismatch_log and ci_all_matches
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
