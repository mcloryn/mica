"""Sweep vision.imgsz pada COCO val2017 person (CV-1, pra-registrasi di docs/IMGSZ.md).

python scripts/cv_imgsz_sweep.py --data-dir D:/SKRIPSI/datasets/coco --out-dir D:/SKRIPSI/cv-hasil
    [--sizes 640 480 416 320 256] [--bootstrap 1000] [--seed 20261030] [--speed] [--dry-run]

Akurasi (bawaan): untuk tiap imgsz, yolo26n-pose.pt memprediksi semua gambar di
annotations/person_keypoints_val2017.json (model.predict, kelas person, CPU, conf 0,001), lalu
pycocotools COCOeval dijalankan sekali per imgsz (bbox dan keypoints). evalImgs untuk area 'large'
diratakan jadi EvalRecords; bootstrap berpasangan per gambar cukup mengulang accumulate dengan
bobot = berapa kali gambar terambil (tanpa evaluate ulang). Aturan pilih: lihat choose_imgsz.
--speed: hanya pengukuran kecepatan (20 gambar pemanasan + 200 gambar terkunci), dilaporkan saja.
--dry-run: cek path dan cetak rencana, tanpa memuat model, data, atau pycocotools.

Dataset dan keluaran di luar repo. Tidak ada gambar yang ditulis ke disk; keluaran hanya angka.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

SIZES = (640, 480, 416, 320, 256)  # kelipatan 32 (stride YOLO)
REFERENCE = 640
SEED = 20261030
BOOTSTRAP = 1000
CI_LEVEL = 0.95
EVAL_CONF = 0.001  # bawaan val Ultralytics 8.4 (cfg/default.yaml), supaya kurva PR lengkap
PERSON_CAT_ID = 1  # COCO category_id person
PERSON_CLASS = 0  # indeks kelas person di model YOLO
SPEED_WARMUP = 20
SPEED_IMAGES = 200
ANNOTATIONS = Path("annotations/person_keypoints_val2017.json")
IMAGES = Path("val2017")
MODEL_FILE = ROOT / "models" / "yolo26n-pose.pt"
# sama persis dengan COCOeval Params
IOU_THRS = np.linspace(0.5, 0.95, int(np.round((0.95 - 0.5) / 0.05)) + 1, endpoint=True)
REC_THRS = np.linspace(0.0, 1.00, int(np.round((1.00 - 0.0) / 0.01)) + 1, endpoint=True)


# --- accumulate + bootstrap (tanpa pycocotools, dites dengan data mainan) ------------------


@dataclass(frozen=True)
class EvalRecords:
    """evalImgs satu kategori, satu area, satu maxDet, diratakan dan diurutkan skor menurun.

    image: indeks gambar (0..n_images-1) tiap deteksi; tps/fps: (T, N) bool;
    npig: jumlah GT tidak diabaikan per gambar (n_images,).
    """

    image: np.ndarray
    tps: np.ndarray
    fps: np.ndarray
    npig: np.ndarray

    @property
    def n_images(self) -> int:
        return int(self.npig.shape[0])


def records_from_evalimgs(
    eval_imgs: list[dict[str, Any] | None], max_det: int, n_thrs: int = len(IOU_THRS)
) -> EvalRecords:
    """Daftar evalImg COCOeval (urut imgIds, None = tanpa GT dan deteksi) -> EvalRecords.

    Urutan sama dengan COCOeval.accumulate: skor dipotong max_det per gambar, digabung menurut
    urutan gambar, lalu argsort(-skor, kind='mergesort').
    """
    scores, image, dtm, dtig = [], [], [], []
    npig = np.zeros(len(eval_imgs), dtype=np.int64)
    for i, e in enumerate(eval_imgs):
        if e is None:
            continue
        s = np.asarray(e["dtScores"][:max_det], dtype=np.float64)
        scores.append(s)
        image.append(np.full(len(s), i, dtype=np.int64))
        dtm.append(np.asarray(e["dtMatches"]).reshape(n_thrs, -1)[:, :max_det])
        dtig.append(np.asarray(e["dtIgnore"]).reshape(n_thrs, -1)[:, :max_det])
        npig[i] = int(np.count_nonzero(np.asarray(e["gtIgnore"]) == 0))
    if scores:
        s = np.concatenate(scores)
        order = np.argsort(-s, kind="mergesort")
        m = np.concatenate(dtm, axis=1)[:, order].astype(bool)
        ig = np.concatenate(dtig, axis=1)[:, order].astype(bool)
        img = np.concatenate(image)[order]
    else:
        m = ig = np.zeros((n_thrs, 0), dtype=bool)
        img = np.zeros(0, dtype=np.int64)
    return EvalRecords(
        image=img, tps=np.logical_and(m, ~ig), fps=np.logical_and(~m, ~ig), npig=npig
    )


def accumulate(rec: EvalRecords, weights: np.ndarray | None = None) -> tuple[float, float]:
    """(AP, AR) seperti COCOeval.accumulate + summarize untuk satu kategori/area/maxDet.

    weights[i] = berapa kali gambar i terambil (bootstrap). Bobot w setara menggandakan gambar w
    kali: titik antara yang hilang tidak mengubah presisi terinterpolasi (amplop maksimum dari
    kanan). Bedanya hanya urutan seri skor antar-gambar berbeda, yang juga sembarang di
    pycocotools. -1 bila tidak ada GT (sama dengan COCOeval).
    """
    w = np.ones(rec.n_images) if weights is None else np.asarray(weights, dtype=np.float64)
    npig = float(np.dot(w, rec.npig))
    if npig == 0:
        return -1.0, -1.0
    dw = w[rec.image]
    tp_sum = np.cumsum(rec.tps * dw, axis=1)
    fp_sum = np.cumsum(rec.fps * dw, axis=1)
    n_thrs, nd = tp_sum.shape
    precision = np.zeros((n_thrs, len(REC_THRS)))
    recall = np.zeros(n_thrs)
    if nd:
        rc = tp_sum / npig
        pr = tp_sum / (tp_sum + fp_sum + np.spacing(1))
        env = np.maximum.accumulate(pr[:, ::-1], axis=1)[:, ::-1]
        recall = rc[:, -1]
        for t in range(n_thrs):
            idx = np.searchsorted(rc[t], REC_THRS, side="left")
            ok = idx < nd
            precision[t, ok] = env[t, idx[ok]]
    return float(precision.mean()), float(recall.mean())


def bootstrap_counts(n_images: int, n_boot: int, seed: int) -> np.ndarray:
    """(B, n_images): berapa kali tiap gambar terambil; dipakai sama untuk semua imgsz (berpasangan)."""
    rng = np.random.default_rng(seed)
    counts = np.empty((n_boot, n_images), dtype=np.int32)
    for b in range(n_boot):
        counts[b] = np.bincount(rng.integers(0, n_images, size=n_images), minlength=n_images)
    return counts


def percentile_ci(samples: np.ndarray, level: float = CI_LEVEL) -> tuple[float, float]:
    alpha = (1.0 - level) / 2.0
    lo, hi = np.percentile(np.asarray(samples, dtype=np.float64), [100 * alpha, 100 * (1 - alpha)])
    return float(lo), float(hi)


def paired_bootstrap(
    records: dict[int, EvalRecords], counts: np.ndarray, reference: int = REFERENCE
) -> dict[int, dict[str, Any]]:
    """AP tiap imgsz dan selisih (AP_ref - AP_imgsz) pada sampel gambar yang sama."""
    n = {r.n_images for r in records.values()}
    if len(n) != 1 or counts.shape[1] != n.pop():
        raise ValueError("semua imgsz harus dievaluasi pada daftar gambar yang sama")
    ap = {s: np.array([accumulate(r, c)[0] for c in counts]) for s, r in records.items()}
    out: dict[int, dict[str, Any]] = {}
    for s, r in records.items():
        diff = ap[reference] - ap[s]
        out[s] = {
            "ap": accumulate(r)[0],
            "ap_ci": percentile_ci(ap[s]),
            "diff": accumulate(records[reference])[0] - accumulate(r)[0],
            "diff_ci": percentile_ci(diff),
        }
    return out


def choose_imgsz(results: dict[int, dict[str, Any]], reference: int = REFERENCE) -> int:
    """ATURAN PILIH (dikunci): imgsz terkecil yang CI 95% selisihnya terhadap acuan mencakup 0;
    bila tidak ada, acuan. Kecepatan tidak ikut menentukan."""
    for s in sorted(results):
        if s == reference:
            continue
        lo, hi = results[s]["diff_ci"]
        if lo <= 0.0 <= hi:
            return s
    return reference


# --- kecepatan (dilaporkan saja) ------------------------------------------------------------


def speed_image_ids(image_ids: list[int], seed: int) -> tuple[list[int], list[int]]:
    """(pemanasan 20, terukur 200) dari id gambar terurut, deterministik dari seed."""
    rng = np.random.default_rng(seed)
    pick = rng.choice(np.array(sorted(image_ids)), SPEED_WARMUP + SPEED_IMAGES, replace=False)
    ids = [int(i) for i in pick]
    return ids[:SPEED_WARMUP], ids[SPEED_WARMUP:]


def summarize_speed(speeds: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    """dict speed Ultralytics (ms) per gambar -> median dan p95 per tahap dan total."""
    keys = ("preprocess", "inference", "postprocess")
    table = {k: np.array([s[k] for s in speeds], dtype=np.float64) for k in keys}
    table["total"] = sum(table[k] for k in keys)
    return {
        k: {"median": float(np.median(v)), "p95": float(np.percentile(v, 95))}
        for k, v in table.items()
    }


# --- COCO + Ultralytics (lazy import; tidak dipakai tes) -------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def environment(model_file: Path, threads: int | None) -> dict[str, Any]:
    import pycocotools
    import torch
    import ultralytics

    try:
        import psutil

        ram = psutil.virtual_memory().total
    except ImportError:  # pragma: no cover
        ram = None
    return {
        "python": sys.version,
        "torch": torch.__version__,
        "ultralytics": ultralytics.__version__,
        "pycocotools": getattr(pycocotools, "__version__", "tidak tersedia"),
        "cpu": platform.processor(),
        "ram_bytes": ram,
        "torch_threads": threads,
        "model_sha256": sha256_file(model_file),
    }


def load_model(model_file: Path) -> Any:
    sys.path.insert(0, str(ROOT / "src"))
    from mica.vision.detector import _load_yolo, disable_ultralytics_sync

    if not model_file.is_file():
        raise SystemExit(f"bobot {model_file} tidak ada")
    disable_ultralytics_sync()
    return _load_yolo(str(model_file))


def predict(model: Any, image: np.ndarray, imgsz: int, conf: float) -> Any:
    return model.predict(
        image, imgsz=imgsz, conf=conf, classes=[PERSON_CLASS], device="cpu", save=False,
        verbose=False,
    )[0]  # fmt: skip


def coco_detections(result: Any, image_id: int) -> list[dict[str, Any]]:
    """Results Ultralytics (koordinat gambar asli) -> format hasil COCO (bbox xywh + keypoints)."""
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return []
    xyxy = boxes.xyxy.cpu().numpy()
    conf = boxes.conf.cpu().numpy()
    kp = result.keypoints.data.cpu().numpy() if result.keypoints is not None else None
    out = []
    for i in range(len(xyxy)):
        x1, y1, x2, y2 = (float(v) for v in xyxy[i])
        det: dict[str, Any] = {
            "image_id": image_id,
            "category_id": PERSON_CAT_ID,
            "bbox": [x1, y1, x2 - x1, y2 - y1],
            "score": float(conf[i]),
        }
        if kp is not None:
            det["keypoints"] = [float(v) for v in kp[i].reshape(-1)]
        out.append(det)
    return out


def coco_records(gt: Any, dets: list[dict[str, Any]], iou_type: str) -> dict[str, Any]:
    """COCOeval sekali; stats resmi + EvalRecords untuk area all/medium/large (maxDet terakhir)."""
    from pycocotools.cocoeval import COCOeval

    dt = gt.loadRes(dets)
    ev = COCOeval(gt, dt, iouType=iou_type)
    ev.params.catIds = [PERSON_CAT_ID]
    ev.params.imgIds = sorted(gt.getImgIds())
    ev.evaluate()
    ev.accumulate()
    ev.summarize()
    p = ev.params
    n_img = len(p.imgIds)
    recs = {}
    for label in ("all", "medium", "large"):
        a = p.areaRngLbl.index(label)
        recs[label] = records_from_evalimgs(
            ev.evalImgs[a * n_img : (a + 1) * n_img], max_det=p.maxDets[-1]
        )
    return {"stats": [float(x) for x in ev.stats], "records": recs, "img_ids": p.imgIds}


# --- CLI ------------------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--data-dir", type=Path, required=True, help="folder COCO (annotations/, val2017/)"
    )
    ap.add_argument("--out-dir", type=Path, required=True, help="folder keluaran, di luar repo")
    ap.add_argument("--sizes", type=int, nargs="+", default=list(SIZES))
    ap.add_argument("--bootstrap", type=int, default=BOOTSTRAP, help="B, jumlah sampel bootstrap")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument(
        "--threads", type=int, default=None, help="torch threads (--speed); None=bawaan"
    )
    ap.add_argument("--speed", action="store_true", help="ukur kecepatan saja (dilaporkan)")
    ap.add_argument("--dry-run", action="store_true", help="cek path dan cetak rencana saja")
    args = ap.parse_args(argv)
    if REFERENCE not in args.sizes:
        ap.error(f"--sizes wajib memuat acuan {REFERENCE}")
    if any(s % 32 for s in args.sizes):
        ap.error("--sizes harus kelipatan 32 (stride YOLO)")
    if ROOT in args.out_dir.resolve().parents or args.out_dir.resolve() == ROOT:
        ap.error("--out-dir harus di luar repo")
    return args


def plan(args: argparse.Namespace) -> dict[str, Any]:
    ann = args.data_dir / ANNOTATIONS
    return {
        "mode": "speed" if args.speed else "accuracy",
        "sizes": sorted(args.sizes, reverse=True),
        "bootstrap": args.bootstrap,
        "seed": args.seed,
        "annotations": str(ann),
        "annotations_exists": ann.is_file(),
        "images_exists": (args.data_dir / IMAGES).is_dir(),
        "model": str(MODEL_FILE),
        "model_exists": MODEL_FILE.is_file(),
        "out_dir": str(args.out_dir),
    }


def run_accuracy(args: argparse.Namespace, out: Path) -> dict[str, Any]:  # pragma: no cover
    import cv2
    from pycocotools.coco import COCO

    gt = COCO(str(args.data_dir / ANNOTATIONS))
    model = load_model(MODEL_FILE)
    sizes = sorted(args.sizes, reverse=True)
    box: dict[str, dict[int, EvalRecords]] = {"all": {}, "medium": {}, "large": {}}
    kp_large: dict[int, EvalRecords] = {}
    official: dict[int, dict[str, Any]] = {}
    for s in sizes:
        dets: list[dict[str, Any]] = []
        for img_id in sorted(gt.getImgIds()):
            info = gt.loadImgs(img_id)[0]
            image = cv2.imread(str(args.data_dir / IMAGES / info["file_name"]))
            dets += coco_detections(predict(model, image, s, EVAL_CONF), img_id)
            del image
        (out / f"dets-{s}.json").write_text(json.dumps(dets), encoding="utf-8")
        b = coco_records(gt, dets, "bbox")
        k = coco_records(gt, dets, "keypoints")
        for label, by_size in box.items():
            by_size[s] = b["records"][label]
        kp_large[s] = k["records"]["large"]
        official[s] = {"bbox_stats": b["stats"], "keypoints_stats": k["stats"]}
        # cek pra-registrasi: accumulate sendiri harus sama dengan COCOeval (stats[5]/[11])
        ap_l, ar_l = accumulate(box["large"][s])
        if abs(ap_l - b["stats"][5]) > 1e-9 or abs(ar_l - b["stats"][11]) > 1e-9:
            raise SystemExit(f"accumulate tidak sama dengan COCOeval pada imgsz {s}")
    n_images = box["large"][REFERENCE].n_images
    counts = bootstrap_counts(n_images, args.bootstrap, args.seed)
    primary = paired_bootstrap(box["large"], counts)
    support = {
        "box_all": paired_bootstrap(box["all"], counts),
        "box_medium": paired_bootstrap(box["medium"], counts),
        "keypoint_large": paired_bootstrap(kp_large, counts),
    }
    return {
        "primary_box_ap_large": primary,
        "chosen_imgsz": choose_imgsz(primary),
        "support": support,
        "ar_large": {s: accumulate(r)[1] for s, r in box["large"].items()},
        "official_stats": official,
        "n_images": n_images,
    }


def run_speed(args: argparse.Namespace) -> dict[str, Any]:  # pragma: no cover
    import cv2
    import torch
    from pycocotools.coco import COCO

    if args.threads is not None:
        torch.set_num_threads(args.threads)
    gt = COCO(str(args.data_dir / ANNOTATIONS))
    warm, measured = speed_image_ids(gt.getImgIds(), args.seed)
    model = load_model(MODEL_FILE)
    out: dict[str, Any] = {"warmup_ids": warm, "measured_ids": measured, "per_size": {}}
    for s in sorted(args.sizes, reverse=True):
        speeds = []
        for i, img_id in enumerate(warm + measured):
            image = cv2.imread(str(args.data_dir / IMAGES / gt.loadImgs(img_id)[0]["file_name"]))
            result = predict(model, image, s, EVAL_CONF)
            del image
            if i >= len(warm):
                speeds.append(dict(result.speed))
        out["per_size"][s] = summarize_speed(speeds)
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    info = plan(args)
    if args.dry_run:
        print(json.dumps(info, indent=1))
        return 0
    if not (info["annotations_exists"] and info["images_exists"] and info["model_exists"]):
        print(json.dumps(info, indent=1), file=sys.stderr)
        return 2
    out = args.out_dir / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=False)
    result = run_speed(args) if args.speed else run_accuracy(args, out)
    threads = None
    if args.speed:
        import torch

        threads = int(torch.get_num_threads())
    result = {"plan": info, "environment": environment(MODEL_FILE, threads), **result}
    name = "speed.json" if args.speed else "accuracy.json"
    (out / name).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print(out / name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
