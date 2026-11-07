"""scripts/cv7_eval_yolo.py (CV-7): AP@50 dari EvalRecords, parsing log, dan pemetaan stats."""

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("cv7_eval_yolo", ROOT / "scripts/cv7_eval_yolo.py")
cv7 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cv7)
sweep = cv7.sweep


def _records():
    # 2 gambar, 3 deteksi urut skor; T=10 ambang: deteksi 0 TP hanya pada IoU 0,50
    t = len(sweep.IOU_THRS)
    tps = np.zeros((t, 3), dtype=bool)
    tps[0, 0] = True
    tps[:, 1] = True
    fps = ~tps
    return sweep.EvalRecords(
        image=np.array([0, 1, 0]), tps=tps, fps=fps, npig=np.array([1, 1], dtype=np.int64)
    )


def test_iou50_records_keeps_first_threshold_only():
    rec = _records()
    r50 = cv7.iou50_records(rec)
    assert r50.tps.shape == (1, 3)
    ap50, ar50 = sweep.accumulate(r50)
    assert ar50 == 1.0  # kedua GT ditemukan pada IoU 0,50
    assert ap50 > sweep.accumulate(rec)[0]  # AP@50:95 lebih kecil
    # bobot bootstrap tetap berlaku
    w = np.array([0, 2])
    assert sweep.accumulate(r50, w)[1] == 1.0


def test_point_metrics_indices():
    bbox = [float(i) for i in range(12)]
    kp = [float(10 + i) for i in range(10)]
    m = cv7.point_metrics(bbox, kp)
    assert m == {
        "box_ap50_all": 1.0,
        "box_ap_all": 0.0,
        "box_ap_medium": 4.0,
        "box_ap_large": 5.0,
        "box_ar100_large": 11.0,
        "keypoint_ap_all": 10.0,
        "keypoint_ap_large": 14.0,
    }


def test_parse_log_blocks_and_compare():
    lines = [
        "Evaluate annotation type *bbox*",
        " Average Precision  (AP) @[ IoU=0.50:0.95 | area=   all | maxDets=100 ] = 0.426",
        " Average Precision  (AP) @[ IoU=0.50      | area=   all | maxDets=100 ] = 0.601",
        " Average Recall     (AR) @[ IoU=0.50:0.95 | area= large | maxDets=100 ] = 0.826",
        "DONE (t=0.08s)",
        " Average Precision  (AP) @[ IoU=0.50:0.95 | area=   all | maxDets= 20 ] = 0.560",
        " Average Precision  (AP) @[ IoU=0.50:0.95 | area= small | maxDets=100 ] = -1.000",
    ]
    text = "\r\n".join(lines)
    blocks = cv7.parse_log_blocks(text)
    assert blocks == [[0.426, 0.601, 0.826], [0.560, -1.0]]
    assert cv7.compare({"a": 0.4261, "b": 1.0}, {"a": 0.426}, 1e-3) == {}
    assert cv7.compare({"a": 0.43}, {"a": 0.426}, 1e-3) == {"a": {"ours": 0.43, "reference": 0.426}}
