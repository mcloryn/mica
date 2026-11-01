"""M-12 eval vision-scenarios (E-07 skenario): jadwal deteksi, cooldown M-09, sapaan
benar/terlewat/salah/ganda, aturan pemilihan dan pemecah seri, grid pada urutan deteksi palsu,
pembaca video, dan CLI dengan detektor palsu."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mica.eval import __main__ as cli
from mica.eval import vision_scenarios as es
from mica.eval.vision import VisionEvalError
from mica.vision.types import PersonArrived, PersonLeft, PersonTrack

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
W, H = 200, 100


def track(tid: int, ratio: float) -> PersonTrack:
    kp = np.zeros((17, 3))
    kp[5] = (W / 2 + ratio * W / 2, 30, 0.9)
    kp[6] = (W / 2 - ratio * W / 2, 30, 0.9)
    return PersonTrack(tid, (60.0, 10.0, 140.0, 95.0), 0.9, kp)


# skenario: A lewat 2..3,5 s; B berhenti 10..20 s; B kembali 24..30 s (jeda 4 s)
SCRIPT = [(1, 2.0, 3.5), (2, 10.0, 20.0), (3, 24.0, 30.0)]
APPEARANCES = [
    es.Appearance("k1", "A", "lewat", 2.0, None, 3.5),
    es.Appearance("k1", "B", "berhenti", 9.5, 10.0, 20.0),
    es.Appearance("k1", "B", "berhenti", 24.0, 24.0, 30.0),
]


class ScriptedDetector:
    def __init__(self, script=SCRIPT):
        self.script = script
        self.t = 0.0

    def detect_and_track(self, frame):
        t = float(frame[0, 0, 0]) / 10  # waktu disandikan di piksel (indeks frame)
        return [track(tid, 0.3) for tid, a, b in self.script if a <= t < b]


def frames(seconds=40.0, fps=10):
    for i in range(int(seconds * fps)):
        frame = np.zeros((H, W, 3), dtype=np.uint16)
        frame[0, 0, 0] = i
        yield i / fps, frame


# --- unit ---------------------------------------------------------------------------------


def test_detect_clip_follows_visionloop_schedule():
    dets, times = es.detect_clip(
        frames(2.0), ScriptedDetector(), fps=5, clock=iter(range(99)).__next__
    )
    assert [round(t, 1) for t, _tr, _s in dets] == [
        0.0,
        0.2,
        0.4,
        0.6,
        0.8,
        1.0,
        1.2,
        1.4,
        1.6,
        1.8,
    ]
    assert times == [1] * 10


def test_greetings_apply_m09_cooldown():
    events = [PersonArrived(1, (0, 0, 1, 1), 5.0), PersonLeft(1, 10.0, 5.0),
              PersonArrived(2, (0, 0, 1, 1), 20.0), PersonLeft(2, 25.0, 5.0),
              PersonArrived(3, (0, 0, 1, 1), 60.0)]  # fmt: skip
    assert es.greetings(events, 0) == [5.0, 20.0, 60.0]
    assert es.greetings(events, 30) == [5.0, 60.0]  # 20 < 10 + 30


def test_score_clip_counts_each_kind():
    apps = [
        es.Appearance("k", "A", "lewat", 0.0, None, 5.0),
        es.Appearance("k", "B", "berhenti", 10.0, 11.0, 20.0),
        es.Appearance("k", "C", "berhenti", 30.0, 31.0, 40.0),
        es.Appearance("k", "B", "berhenti", 22.0, 22.0, 28.0),  # kembali, jeda 2 s
    ]
    s = es.score_clip([1.0, 12.5, 15.0, 23.0, 50.0], apps, cooldown_s=0)
    assert (s.correct, s.missed, s.false_pass, s.false_outside, s.double) == (2, 1, 1, 1, 1)
    assert s.latencies == [1.5, 1.0]
    # cooldown 30: B kembali dalam cooldown -> tidak boleh disapa; sapaan 23 menjadi ganda
    s = es.score_clip([12.5, 23.0], apps, cooldown_s=30)
    assert (s.correct, s.missed, s.double) == (1, 1, 1)


def test_owner_prefers_stopping_appearance():
    apps = [es.Appearance("k", "A", "lewat", 0.0, None, 10.0),
            es.Appearance("k", "B", "berhenti", 2.0, 4.0, 12.0),
            es.Appearance("k", "C", "berhenti", 1.0, 6.0, 12.0)]  # fmt: skip
    assert es.owner(5.0, apps) == 1  # berhenti terakhir sebelum t
    assert es.owner(3.0, apps) == 1  # belum ada yang berhenti: berhenti paling awal
    assert es.owner(11.0, [apps[0]]) is None


def grid_row(dwell, leave, ratio, cooldown, missed=0, false=0, double=0, lat=(1.0,)):
    s = es.Score(correct=1, missed=missed, false_pass=false, double=double, latencies=list(lat))
    return es.GridRow(dwell, leave, ratio, cooldown, s, 1)


def test_select_rule_and_tie_breaks():
    rows = [
        grid_row(1, 2, 0.18, 0, missed=1),
        grid_row(1, 2, 0.18, 30),
        grid_row(2, 2, 0.18, 0),
        grid_row(2, 3, 0.22, 0),
        grid_row(2, 2, 0.26, 0),
        grid_row(3, 5, 0.26, 60, lat=(2.5,)),  # p95 + 1 > 3: tidak lolos
        grid_row(3, 5, 0.26, 30, double=1),  # ganda: tidak lolos
    ]
    winner = es.select(rows)
    assert winner is not None and winner.key() == (2, 3, 0.22, 0)  # dwell, lalu leave
    rows.append(grid_row(2, 2, 0.18, 30))
    assert es.select(rows).key() == (2, 2, 0.18, 30)  # cooldown sebelum leave


def test_select_none_when_nothing_passes():
    assert es.select([grid_row(1, 2, 0.2, 0, lat=())]) is None
    assert es.select([grid_row(1, 2, 0.2, 0, lat=(2.1,))]) is None


def test_grid_on_scripted_detections():
    dets, _ = es.detect_clip(frames(), ScriptedDetector(), fps=5)
    rows = {
        r.key(): r for r in es.evaluate_grid({"k1": dets}, APPEARANCES, es.GRIDS["default"], 0.5)
    }
    assert len(rows) == 81
    r = rows[(1.0, 2.0, 0.22, 0.0)]  # A lewat 1,5 s >= dwell 1 -> sapaan salah
    assert (r.score.correct, r.score.false_pass, r.score.missed, r.score.double) == (2, 1, 0, 0)
    assert r.score.latencies == pytest.approx([1.0, 1.0])
    r = rows[(2.0, 5.0, 0.22, 0.0)]  # leave 5: B kembali sebelum PersonLeft -> terlewat
    assert (r.score.correct, r.score.missed) == (1, 1)
    r = rows[(2.0, 5.0, 0.22, 30.0)]  # kembali dalam cooldown: tidak wajib disapa
    assert (r.score.correct, r.score.missed, r.score.double, r.n_required) == (1, 0, 0, 1)
    assert not rows[(3.0, 2.0, 0.22, 0.0)].passes  # waktu sapaan 3 + 1 > 3
    winner = es.select(list(rows.values()))
    assert winner is not None and winner.key() == (2.0, 5.0, 0.26, 60.0)


def test_annotations_validation(tmp_path):
    p = tmp_path / "annotations.jsonl"
    p.write_text(json.dumps({"clip": "k1", "orang": "A", "jenis": "berhenti", "masuk": 5,
                             "berhenti": 3, "pergi": 9}) + "\n", encoding="utf-8")  # fmt: skip
    with pytest.raises(VisionEvalError, match="masuk <= berhenti <= pergi"):
        es.load_annotations(p, ["k1"])
    p.write_text(json.dumps({"clip": "k9", "orang": "A", "jenis": "lewat", "masuk": 1,
                             "pergi": 2}) + "\n", encoding="utf-8")  # fmt: skip
    with pytest.raises(VisionEvalError, match="tidak ada di manifest"):
        es.load_annotations(p, ["k1"])


def test_read_video_times(tmp_path):
    import cv2

    path = tmp_path / "k.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (32, 24))
    for _ in range(5):
        writer.write(np.zeros((24, 32, 3), np.uint8))
    writer.release()
    out = [(t, f.shape) for t, f in es.read_video(path)]
    assert [round(t, 2) for t, _ in out] == [0.0, 0.1, 0.2, 0.3, 0.4]


# --- run dan CLI --------------------------------------------------------------------------


def make_dataset(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "k1.mp4").write_bytes(b"")
    (root / "manifest.jsonl").write_text(
        json.dumps({"id": "k1", "file": "k1.mp4", "persetujuan": True}) + "\n", encoding="utf-8"
    )
    rows = [{"clip": a.clip, "orang": a.person, "jenis": a.kind, "masuk": a.enter,
             "pergi": a.leave, **({"berhenti": a.stop} if a.stop is not None else {})}
            for a in APPEARANCES]  # fmt: skip
    (root / "annotations.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return root


def test_cli_vision_scenarios_with_fake_detector(tmp_path, monkeypatch, capsys):
    import mica.vision.detector as det

    root = make_dataset(tmp_path / "ds")
    models = tmp_path / "models"
    models.mkdir()
    (models / "yolo26n-pose.pt").write_bytes(b"x")
    monkeypatch.setattr(det, "UltralyticsDetector", lambda *a, **k: ScriptedDetector())
    monkeypatch.setattr(es, "read_video", lambda path: frames())
    code = cli.main(["vision-scenarios", "--config", str(DEV_YAML), "--dataset", str(root),
                     "--model", "yolo26n-pose", "--models-dir", str(models),
                     "--out", str(tmp_path / "res"), "--note", "sintetis"])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0, out
    assert "vision.dwell_s = 2, vision.leave_s = 5" in out
    run_dir = next((tmp_path / "res").iterdir())
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["fps_detect"] == 5 and run["min_kp_conf"] == 0.5
    assert run["winner"]["regreet_cooldown_s"] == 60.0
    assert (run_dir / "grid.csv").read_text(encoding="utf-8-sig").count("\n") == 82


def test_cli_vision_scenarios_rejects_model_without_pose(tmp_path, capsys):
    code = cli.main(["vision-scenarios", "--config", str(DEV_YAML), "--dataset", str(tmp_path),
                     "--model", "yolo26n"])  # fmt: skip
    assert code == 2
    assert "-pose" in capsys.readouterr().err


def test_cli_vision_scenarios_refused_in_prod(tmp_path, monkeypatch, capsys):
    from mica.config import load_settings

    settings = load_settings(DEV_YAML)
    prod = settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "prod"})})
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: prod)
    code = cli.main(["vision-scenarios", "--config", "x", "--dataset", str(tmp_path),
                     "--model", "yolo26n-pose"])  # fmt: skip
    assert code == 2
    assert "mode prod" in capsys.readouterr().err
