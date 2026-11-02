"""CV-4: kecepatan resize OpenCV (INTER_AREA) vs pyvips (shrink, box filter). Pra-registrasi
docs/PYVIPS.md. Uji saja: kode aplikasi tidak memakai pyvips.

python scripts/cv_resize_bench.py --data-dir D:/SKRIPSI/datasets/coco --out-dir D:/SKRIPSI/cv-hasil/resize

- Gambar: 220 id COCO val2017 dari speed_image_ids (seed 20261030; 20 pemanasan + 200 terukur,
  sama dengan run kecepatan CV-2c). Tiap gambar di-crop tengah ke rasio 4:3 dan 16:9 lalu
  di-resize SEKALI ke 640x480 (Kasus A) dan 1920x1080 (Kasus B) sebelum pengukuran.
- Kasus A: 640x480 -> lebar 320 (faktor 2); Kasus B: 1920x1080 -> lebar 640 (faktor 3).
- OpenCV: cv2.resize(INTER_AREA), sama dengan src/mica/vision/livepreview.py:93-94.
- pyvips end-to-end: Image.new_from_array(frame) -> shrink(f, f) -> numpy(). Konversi diukur
  terpisah: numpy->vips (new_from_array) dan vips->numpy (numpy() dari gambar hasil yang sudah
  dihitung di memori).
- 20 pemanasan per metode per kasus, lalu tiap gambar 50 ulangan; median dan p95 (ms).
- Kesetaraan: rata-rata selisih absolut piksel OpenCV vs pyvips per gambar.
Gambar hanya di memori; keluaran hanya angka (results.json).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261030
REPEATS = 50
CASES = {"A": ((640, 480), 320), "B": ((1920, 1080), 640)}  # (lebar, tinggi) masukan, lebar keluar
DECISION_MS = 1.0  # aturan: pyvips diusulkan bila median A lebih cepat >= 1 ms per frame


def center_crop_resize(image: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Crop tengah ke rasio size lalu resize ke size (w, h); disiapkan sekali sebelum ukur."""
    import cv2

    w, h = size
    ih, iw = image.shape[:2]
    if iw * h > ih * w:  # terlalu lebar
        cw, ch = round(ih * w / h), ih
    else:
        cw, ch = iw, round(iw * h / w)
    x0, y0 = (iw - cw) // 2, (ih - ch) // 2
    crop = image[y0 : y0 + ch, x0 : x0 + cw]
    interp = cv2.INTER_AREA if cw >= w else cv2.INTER_CUBIC
    return np.ascontiguousarray(cv2.resize(crop, (w, h), interpolation=interp))


def factor(case: str) -> int:
    (w, h), out_w = CASES[case]
    f = w // out_w
    if f * out_w != w or h % f:
        raise ValueError(f"kasus {case}: faktor tidak bulat")
    return f


def resize_cv2(frame: np.ndarray, out_w: int) -> np.ndarray:
    import cv2

    h, w = frame.shape[:2]
    return cv2.resize(frame, (out_w, max(1, round(h * out_w / w))), interpolation=cv2.INTER_AREA)


def resize_vips(frame: np.ndarray, f: int) -> np.ndarray:
    import pyvips

    return pyvips.Image.new_from_array(frame).shrink(f, f).numpy()


def summarize(ms: list[float]) -> dict[str, float]:
    a = np.asarray(ms, dtype=np.float64)
    return {"median": float(np.median(a)), "p95": float(np.percentile(a, 95)), "n": int(a.size)}


def mean_abs_diff(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        raise ValueError(f"bentuk berbeda {a.shape} vs {b.shape}")
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def decide(median_cv2_ms: float, median_vips_ms: float) -> dict[str, Any]:
    gain = median_cv2_ms - median_vips_ms
    return {"gain_ms": gain, "threshold_ms": DECISION_MS, "propose_pyvips": gain >= DECISION_MS}


def time_calls(fn: Callable[[], Any], repeats: int) -> list[float]:
    out = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000)
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:  # pragma: no cover - butuh COCO + pyvips
    import cv2
    import pyvips
    from pycocotools.coco import COCO

    sys.path.insert(0, str(ROOT / "scripts"))
    from cv_imgsz_sweep import ANNOTATIONS, IMAGES, speed_image_ids

    gt = COCO(str(args.data_dir / ANNOTATIONS))
    warm_ids, ids = speed_image_ids(gt.getImgIds(), args.seed)

    def load(img_id: int) -> np.ndarray:
        return cv2.imread(str(args.data_dir / IMAGES / gt.loadImgs(img_id)[0]["file_name"]))

    raw = {i: load(i) for i in warm_ids + ids}
    out: dict[str, Any] = {
        "warmup_ids": warm_ids, "measured_ids": ids, "repeats": args.repeats,
        "threads": {"cv2_getNumThreads": cv2.getNumThreads(),
                    "vips_concurrency": int(pyvips.vips_lib.vips_concurrency_get())},
        "versions": {"opencv": cv2.__version__, "pyvips": pyvips.__version__,
                     "libvips": ".".join(str(pyvips.version(k)) for k in range(3)),
                     "numpy": np.__version__, "python": sys.version},
        "cases": {},
    }  # fmt: skip
    for case, (size, out_w) in CASES.items():
        f = factor(case)
        frames = {i: center_crop_resize(raw[i], size) for i in warm_ids + ids}
        for i in warm_ids:  # 20 pemanasan per metode
            resize_cv2(frames[i], out_w)
            resize_vips(frames[i], f)
        res: dict[str, list[float]] = {"cv2": [], "vips_e2e": [], "vips_in": [], "vips_out": []}
        diffs = []
        for i in ids:
            fr = frames[i]
            res["cv2"] += time_calls(lambda fr=fr, w=out_w: resize_cv2(fr, w), args.repeats)
            res["vips_e2e"] += time_calls(lambda fr=fr, k=f: resize_vips(fr, k), args.repeats)
            res["vips_in"] += time_calls(
                lambda fr=fr: pyvips.Image.new_from_array(fr), args.repeats
            )
            done = pyvips.Image.new_from_array(fr).shrink(f, f).copy_memory()
            res["vips_out"] += time_calls(done.numpy, args.repeats)
            diffs.append(mean_abs_diff(resize_cv2(fr, out_w), resize_vips(fr, f)))
        out["cases"][case] = {
            "input_wh": list(size), "output_w": out_w, "factor": f,
            "out_shape": list(resize_vips(frames[ids[0]], f).shape),
            **{k: summarize(v) for k, v in res.items()},
            "mean_abs_diff": {"mean": float(np.mean(diffs)), "max": float(np.max(diffs))},
        }  # fmt: skip
    a = out["cases"]["A"]
    out["decision_A"] = decide(a["cv2"]["median"], a["vips_e2e"]["median"])
    return out


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--repeats", type=int, default=REPEATS)
    args = ap.parse_args(argv)
    result = run(args)
    folder = args.out_dir / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "results.json"
    path.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
