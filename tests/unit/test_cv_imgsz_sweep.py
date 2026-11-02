"""scripts/cv_imgsz_sweep.py (CV-1): accumulate, bootstrap, dan aturan pilih dengan data mainan."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("cv_imgsz_sweep", ROOT / "scripts/cv_imgsz_sweep.py")
sweep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sweep)


def _img(scores, matches, gt_ignore, dt_ignore=None):
    """evalImg mainan dengan satu ambang IoU (T=1), format COCOeval."""
    d = len(scores)
    return {
        "dtScores": list(scores),
        "dtMatches": np.array([matches], dtype=float).reshape(1, d),
        "dtIgnore": np.array([dt_ignore or [0] * d], dtype=float).reshape(1, d),
        "gtIgnore": np.array(gt_ignore, dtype=float),
    }


def _reference_accumulate(eval_imgs, max_det):
    """Salinan langsung loop COCOeval.accumulate (pycocotools) untuk T ambang, satu area."""
    e_list = [e for e in eval_imgs if e is not None]
    if not e_list:
        return -1.0, -1.0
    dt_scores = np.concatenate([e["dtScores"][:max_det] for e in e_list])
    inds = np.argsort(-dt_scores, kind="mergesort")
    dtm = np.concatenate([e["dtMatches"][:, :max_det] for e in e_list], axis=1)[:, inds]
    dt_ig = np.concatenate([e["dtIgnore"][:, :max_det] for e in e_list], axis=1)[:, inds]
    gt_ig = np.concatenate([e["gtIgnore"] for e in e_list])
    npig = np.count_nonzero(gt_ig == 0)
    if npig == 0:
        return -1.0, -1.0
    tps = np.logical_and(dtm, np.logical_not(dt_ig))
    fps = np.logical_and(np.logical_not(dtm), np.logical_not(dt_ig))
    tp_sum = np.cumsum(tps, axis=1).astype(dtype=float)
    fp_sum = np.cumsum(fps, axis=1).astype(dtype=float)
    n_thr = tp_sum.shape[0]
    precision = np.zeros((n_thr, len(sweep.REC_THRS)))
    recall = np.zeros(n_thr)
    for t, (tp, fp) in enumerate(zip(tp_sum, fp_sum, strict=True)):
        nd = len(tp)
        rc = tp / npig
        pr = (tp / (fp + tp + np.spacing(1))).tolist()
        q = np.zeros(len(sweep.REC_THRS))
        recall[t] = rc[-1] if nd else 0
        for i in range(nd - 1, 0, -1):
            if pr[i] > pr[i - 1]:  # noqa: PLR1730 - salinan apa adanya dari pycocotools
                pr[i - 1] = pr[i]
        idx = np.searchsorted(rc, sweep.REC_THRS, side="left")
        try:
            for ri, pi in enumerate(idx):
                q[ri] = pr[pi]
        except IndexError:
            pass
        precision[t] = q
    return float(precision.mean()), float(recall.mean())


def _random_eval_imgs(rng, n_images, n_thr):
    imgs = []
    for _ in range(n_images):
        if rng.random() < 0.1:
            imgs.append(None)
            continue
        d, g = int(rng.integers(0, 6)), int(rng.integers(0, 4))
        imgs.append(
            {
                "dtScores": sorted(rng.random(d).tolist(), reverse=True),
                "dtMatches": (rng.random((n_thr, d)) < 0.5).astype(float) * 7,
                "dtIgnore": (rng.random((n_thr, d)) < 0.1).astype(float),
                "gtIgnore": (rng.random(g) < 0.2).astype(float),
            }
        )
    return imgs


def test_accumulate_hand_computed():
    imgs = [_img([0.9, 0.6], [1, 0], [0]), _img([0.8], [0], [0])]
    rec = sweep.records_from_evalimgs(imgs, max_det=100, n_thrs=1)
    ap, ar = sweep.accumulate(rec)
    # urut 0.9 TP, 0.8 FP, 0.6 FP; recall 0,5 -> presisi 1 untuk 51 dari 101 titik recall
    assert ap == pytest.approx(51 / 101)
    assert ar == pytest.approx(0.5)
    # gambar 0 terambil dua kali, gambar 1 tidak: semua titik recall presisi 1
    assert sweep.accumulate(rec, np.array([2, 0])) == pytest.approx((1.0, 1.0))


def test_ignored_detection_and_no_gt():
    imgs = [_img([0.9, 0.8], [0, 1], [0], dt_ignore=[1, 0])]
    rec = sweep.records_from_evalimgs(imgs, max_det=100, n_thrs=1)
    assert sweep.accumulate(rec) == pytest.approx((1.0, 1.0))  # FP diabaikan tidak dihitung
    empty = sweep.records_from_evalimgs([_img([0.5], [0], [1]), None], max_det=100, n_thrs=1)
    assert sweep.accumulate(empty) == (-1.0, -1.0)


def test_max_det_truncates_per_image():
    imgs = [_img([0.9, 0.8, 0.7], [0, 0, 1], [0])]
    rec = sweep.records_from_evalimgs(imgs, max_det=2, n_thrs=1)
    assert sweep.accumulate(rec) == pytest.approx((0.0, 0.0))


def test_matches_reference_full_and_resampled():
    rng = np.random.default_rng(7)
    n_thr = 3
    for _ in range(20):
        imgs = _random_eval_imgs(rng, 12, n_thr)
        rec = sweep.records_from_evalimgs(imgs, max_det=4, n_thrs=n_thr)
        assert sweep.accumulate(rec) == pytest.approx(_reference_accumulate(imgs, 4))
        # bobot = gandakan gambar secara eksplisit
        counts = sweep.bootstrap_counts(len(imgs), 3, int(rng.integers(1 << 30)))
        for c in counts:
            dup = [imgs[i] for i in range(len(imgs)) for _ in range(c[i])]
            assert sweep.accumulate(rec, c) == pytest.approx(_reference_accumulate(dup, 4))


def test_bootstrap_counts_deterministic():
    a = sweep.bootstrap_counts(50, 10, sweep.SEED)
    assert a.shape == (10, 50) and (a.sum(axis=1) == 50).all()
    assert (a == sweep.bootstrap_counts(50, 10, sweep.SEED)).all()
    assert not (a == sweep.bootstrap_counts(50, 10, sweep.SEED + 1)).all()


def test_paired_bootstrap_and_rule():
    rng = np.random.default_rng(1)
    base = _random_eval_imgs(rng, 40, 2)
    worse = [None if e is None else {**e, "dtMatches": np.zeros_like(e["dtMatches"])} for e in base]
    records = {
        640: sweep.records_from_evalimgs(base, 100, 2),
        480: sweep.records_from_evalimgs(base, 100, 2),  # identik dengan acuan
        320: sweep.records_from_evalimgs(worse, 100, 2),  # tidak ada TP
    }
    counts = sweep.bootstrap_counts(40, 200, sweep.SEED)
    res = sweep.paired_bootstrap(records, counts)
    assert res[480]["diff"] == 0 and res[480]["diff_ci"] == (0.0, 0.0)
    assert res[320]["diff_ci"][0] > 0
    assert sweep.choose_imgsz(res) == 480
    assert sweep.choose_imgsz({640: res[640], 320: res[320]}) == 640


def test_paired_bootstrap_requires_same_images():
    a = sweep.records_from_evalimgs([_img([0.9], [1], [0])], 100, 1)
    b = sweep.records_from_evalimgs([_img([0.9], [1], [0])] * 2, 100, 1)
    with pytest.raises(ValueError):
        sweep.paired_bootstrap({640: a, 320: b}, np.ones((1, 1), dtype=int))


def test_percentile_ci_and_speed_summary():
    assert sweep.percentile_ci(np.arange(101)) == pytest.approx((2.5, 97.5))
    speeds = [{"preprocess": 1.0, "inference": float(i), "postprocess": 0.5} for i in range(1, 101)]
    s = sweep.summarize_speed(speeds)
    assert s["inference"]["median"] == pytest.approx(50.5)
    assert s["total"]["median"] == pytest.approx(52.0)
    assert s["inference"]["p95"] == pytest.approx(np.percentile(np.arange(1, 101), 95))


def test_speed_ids_locked():
    ids = list(range(1000, 6000))
    warm, measured = sweep.speed_image_ids(ids, sweep.SEED)
    assert len(warm) == 20 and len(measured) == 200 and not set(warm) & set(measured)
    assert (warm, measured) == sweep.speed_image_ids(list(reversed(ids)), sweep.SEED)


def test_cli_dry_run_and_validation(tmp_path, capsys):
    assert (
        sweep.main(["--data-dir", str(tmp_path), "--out-dir", str(tmp_path / "o"), "--dry-run"])
        == 0
    )
    assert '"annotations_exists": false' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        sweep.parse_args(["--data-dir", ".", "--out-dir", str(tmp_path), "--sizes", "320"])
    with pytest.raises(SystemExit):
        sweep.parse_args(["--data-dir", ".", "--out-dir", str(tmp_path), "--sizes", "640", "300"])
    with pytest.raises(SystemExit):
        sweep.parse_args(["--data-dir", ".", "--out-dir", str(ROOT / "x")])


def test_threads_set_after_warm_up_predict():
    calls = []

    class FakeModel:
        def predict(self, image, **kw):
            calls.append(("predict", image.shape, kw["imgsz"]))
            return [object()]

    class FakeTorch:
        n = 8

        def set_num_threads(self, n):
            calls.append(("set", n))
            self.n = n

        def get_num_threads(self):
            return self.n

    assert sweep.warm_up_threads(FakeModel(), 7, 640, FakeTorch()) == 7
    assert calls == [("predict", (480, 640, 3), 640), ("set", 7)]
    calls.clear()
    assert sweep.warm_up_threads(FakeModel(), None, 320, FakeTorch()) == 8
    assert calls == [("predict", (480, 640, 3), 320)]


def test_select_image_ids_and_versions():
    assert sweep.select_image_ids([5, 1, 3], None) == [1, 3, 5]
    assert sweep.select_image_ids([5, 1, 3], 2) == [1, 3]
    assert sweep.package_version("numpy") == np.__version__
    assert sweep.package_version("paket-yang-tidak-ada-xyz") == "tidak tersedia"


def test_cli_threads_and_max_images(tmp_path, capsys):
    base = ["--data-dir", str(tmp_path), "--out-dir", str(tmp_path / "o")]
    assert sweep.main([*base, "--threads", "7", "--max-images", "20", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert '"threads": 7' in out and '"max_images": 20' in out and '"trial": true' in out
    for bad in (["--threads", "0"], ["--max-images", "0"]):
        with pytest.raises(SystemExit):
            sweep.parse_args([*base, *bad])
