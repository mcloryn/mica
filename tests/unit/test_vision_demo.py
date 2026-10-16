import argparse
import os
from pathlib import Path

import numpy as np
import pytest

import mica.vision.__main__ as cli
from mica.config import load_settings
from mica.vision.camera import Camera
from mica.vision.detector import UltralyticsDetector, model_path
from mica.vision.types import PersonTrack

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
# data uji (bukan ambang)
TEST_ARGS = ["--dwell-s", "1", "--leave-s", "1", "--min-ratio", "0.3", "--fps-busy", "2",
             "--min-majority", "0.5", "--box-top", "0.2", "--box-bottom", "0.5", "--box-side", "0.2"]  # fmt: skip


def write_fake_table(models_dir):
    from test_vision_color import fake_table

    from mica.vision.color import DEFAULT_COLORS_FILE

    models_dir.mkdir(parents=True, exist_ok=True)
    np.save(models_dir / DEFAULT_COLORS_FILE.name, fake_table())


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeCapture:
    def __init__(self, frames):
        self.frames = frames  # dibagi antar-pembukaan ulang: frame tidak berulang

    def isOpened(self):
        return True

    def read(self):
        return (True, self.frames.pop(0)) if self.frames else (False, None)

    def release(self):
        pass


class FakeDetector:
    """Orang setinggi 60% frame dengan track ID 1 pada present_calls panggilan pertama."""

    def __init__(self, present_calls=10**9):
        self.calls = 0
        self.present_calls = present_calls

    def detect_and_track(self, frame):
        self.calls += 1
        if self.calls > self.present_calls:
            return []
        h = frame.shape[0]
        return [PersonTrack(1, (0.0, h * 0.4, 10.0, float(h)), 0.9)]


@pytest.fixture
def no_disk_writes(monkeypatch, tmp_path):
    import cv2

    def forbidden(*args, **kwargs):
        raise AssertionError("demo tidak boleh menulis gambar atau video (N-08)")

    monkeypatch.setattr(cv2, "imwrite", forbidden)
    monkeypatch.setattr(cv2, "VideoWriter", forbidden)
    monkeypatch.chdir(tmp_path)
    write_fake_table(tmp_path / "models")
    return tmp_path


def _files(root):
    return sorted(p.relative_to(root).as_posix() for p in Path(root).rglob("*"))


def _run_main(argv, clock, frames=20, detector=None):
    detector = detector or FakeDetector()
    frame_list = [np.zeros((100, 80, 3), dtype=np.uint8) for _ in range(frames)]

    def camera_factory(source):
        return Camera(source, open_capture=lambda s: FakeCapture(frame_list), clock=clock)

    code = cli.main(
        argv,
        detector_factory=lambda settings, path: detector,
        camera_factory=camera_factory,
        clock=clock,
        sleep=clock.sleep,
    )
    return code, detector


def test_demo_headless_writes_no_files(no_disk_writes, capsys):
    clock = FakeClock()
    argv = ["demo", "--config", str(DEV_YAML), "--no-window", "--seconds", "15", *TEST_ARGS]
    before = _files(no_disk_writes)
    code, detector = _run_main(argv, clock, frames=20, detector=FakeDetector(present_calls=10))
    out = capsys.readouterr().out
    assert code == 0 and detector.calls == 20
    assert _files(no_disk_writes) == before == ["models", "models/color_names_w2c.npy"]
    assert "SUMBER NILAI: argumen CLI (uji coba, nilai coba, bukan E-07/E-08)" in out
    assert "color.min_majority = 0.5 (argumen CLI)" in out and "box_upper.top = 0.2" in out
    assert "PersonArrived track=1 warna=hitam (1.00)" in out  # frame hitam, tabel palsu
    assert "warna frame: hitam 1.00" in out
    assert "dwell_s = 1.0 (argumen CLI)" in out and "min_box_height_ratio = 0.3" in out
    assert "tracker bytetrack.yaml | perangkat cpu" in out
    assert "PersonArrived track=1" in out
    assert "PersonLeft track=1" in out  # orang pergi setelah panggilan ke-10
    assert "rasio box terbesar 0.600" in out
    assert "ID switch: 0" in out


def test_demo_rate_limited_by_state(no_disk_writes):
    clock = FakeClock()
    detector = FakeDetector()
    camera = Camera(
        0, open_capture=lambda s: FakeCapture([np.zeros((10, 10, 3), np.uint8)] * 100), clock=clock
    )
    presence = cli.PresenceTracker(dwell_s=1.0, leave_s=1.0, min_box_height_ratio=0.3)
    stats = cli.run_demo(
        detector, camera, presence, fps_idle=5, fps_busy=2, seconds=5.0, show_window=False,
        clock=clock, sleep=clock.sleep, out=lambda s: None,
    )  # fmt: skip
    # 0-1 s: 5 fps (CANDIDATE), lalu ENGAGED 2 fps selama 4 s -> 5 + 1 + 4*2 = 14 frame
    assert detector.calls == pytest.approx(14, abs=1)
    assert [type(e).__name__ for _, e in stats.events] == ["CameraStatus", "PersonArrived"]


def test_demo_missing_values_names_arguments(capsys):
    code = cli.main(["demo", "--config", str(DEV_YAML), "--no-window", "--dwell-s", "1"])
    err = capsys.readouterr().err
    assert code == 2
    assert "--leave-s" in err and "--min-ratio" in err and "--fps-busy" in err
    assert "--min-majority" in err and "--box-top" in err and "--box-side" in err
    assert "--dwell-s" not in err


def test_resolve_presence_values_arguments_override_config():
    vision = load_settings(DEV_YAML).vision.model_copy(
        update={"dwell_s": 9.0, "leave_s": 8.0, "min_box_height_ratio": 0.7, "fps_busy": 3.0}
    )
    args = argparse.Namespace(dwell_s=1.5, leave_s=None, min_ratio=None, fps_busy=None)
    values, sources = cli.resolve_presence_values(vision, args)
    assert values == {
        "dwell_s": 1.5,
        "leave_s": 8.0,
        "min_box_height_ratio": 0.7,
        "fps_busy": 3.0,
    }
    assert sources["dwell_s"] == "argumen CLI" and sources["leave_s"] == "config"


def _kiosk_settings():
    settings = load_settings(DEV_YAML)
    return settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "kiosk"})})


def test_demo_refused_in_kiosk(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda path: _kiosk_settings())
    clock = FakeClock()
    code, detector = _run_main(["demo", "--no-window", "--seconds", "1", *TEST_ARGS], clock)
    assert code == 2 and detector.calls == 0
    assert "app.mode: dev" in capsys.readouterr().err


def test_fetch_model_refused_in_kiosk(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda path: _kiosk_settings())
    assert cli.main(["fetch-model"]) == 2
    assert "app.mode: dev" in capsys.readouterr().err


def _fetch_args(models_dir):
    return argparse.Namespace(models_dir=models_dir)


def test_fetch_model_downloads_to_models_dir(tmp_path, capsys):
    settings = load_settings(DEV_YAML)
    target = model_path(settings.vision.model, tmp_path / "models")
    synced = []

    def download(path):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"bobot")
        return path

    code = cli.cmd_fetch_model(
        _fetch_args(tmp_path / "models"), settings, download, lambda: synced.append(1)
    )
    out = capsys.readouterr().out
    assert code == 0 and target.read_bytes() == b"bobot" and synced == [1]
    # sha256 dari b"bobot"
    import hashlib

    assert f"sha256 {hashlib.sha256(b'bobot').hexdigest()}" in out


def test_fetch_model_rejects_download_elsewhere(tmp_path):
    settings = load_settings(DEV_YAML)
    elsewhere = tmp_path / "weights" / "yolo26n.pt"

    def download(path):
        elsewhere.parent.mkdir(parents=True)
        elsewhere.write_bytes(b"x")
        return elsewhere

    with pytest.raises(cli.DemoError):
        cli.cmd_fetch_model(_fetch_args(tmp_path / "models"), settings, download, lambda: None)


def test_demo_missing_color_table_reports_code(tmp_path, capsys):
    argv = ["demo", "--config", str(DEV_YAML), "--models-dir", str(tmp_path), "--no-window",
            "--seconds", "1", *TEST_ARGS]  # fmt: skip
    assert cli.main(argv) == 2
    assert "VISION_COLORS_MISSING" in capsys.readouterr().err


def test_demo_missing_model_reports_code(tmp_path, capsys):
    write_fake_table(tmp_path)
    argv = ["demo", "--config", str(DEV_YAML), "--models-dir", str(tmp_path), "--no-window",
            "--seconds", "1", *TEST_ARGS]  # fmt: skip
    assert cli.main(argv) == 2
    assert "VISION_MODEL_MISSING" in capsys.readouterr().err


# --- tes asap dengan bobot asli ---------------------------------------------------------

REAL_MODEL = ROOT / model_path(load_settings(DEV_YAML).vision.model)


@pytest.mark.slow
@pytest.mark.skipif(not REAL_MODEL.is_file(), reason=f"{REAL_MODEL.name} belum diunduh")
def test_real_model_smoke(no_disk_writes):
    settings = load_settings(DEV_YAML)
    v = settings.vision
    detector = UltralyticsDetector(REAL_MODEL, v.tracker, v.conf, v.imgsz)
    frame = np.full((480, 640, 3), 127, dtype=np.uint8)
    for _ in range(3):
        tracks = detector.detect_and_track(frame)
        assert isinstance(tracks, list)
    assert not (no_disk_writes / "runs").exists()
    assert sorted(os.listdir(no_disk_writes)) == ["models"]  # hanya tabel palsu fixture


def test_prompt_argument_and_schedule():
    args = cli.build_parser().parse_args(
        ["demo", "--prompt", "10:Berdiri, mundur", "--prompt", "0:Duduk dekat laptop"]
    )
    assert args.prompt == [(10.0, "Berdiri, mundur"), (0.0, "Duduk dekat laptop")]
    assert cli.current_prompt(args.prompt, 3.0) == ("Duduk dekat laptop", (10.0, "Berdiri, mundur"))
    assert cli.current_prompt(args.prompt, 12.0) == ("Berdiri, mundur", None)
    lines = cli._prompt_lines(args.prompt, 3.0, 20.0)
    assert lines == [
        "Duduk dekat laptop",
        "Berikutnya dalam 7 s: Berdiri, mundur",
        "Sisa waktu rekaman 17 s",
    ]
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["demo", "--prompt", "tanpa-detik"])


def test_run_demo_announces_prompt_changes(no_disk_writes):
    clock = FakeClock()
    lines, beeps = [], []
    camera = Camera(
        0, open_capture=lambda s: FakeCapture([np.zeros((10, 10, 3), np.uint8)] * 50), clock=clock
    )
    presence = cli.PresenceTracker(dwell_s=1.0, leave_s=1.0, min_box_height_ratio=0.3)
    cli.run_demo(
        FakeDetector(), camera, presence, fps_idle=5, fps_busy=2, seconds=4.0, show_window=False,
        prompts=[(0.0, "Duduk"), (2.0, "Mundur")], beep=lambda: beeps.append(1),
        clock=clock, sleep=clock.sleep, out=lines.append,
    )  # fmt: skip
    announced = [line.split("INSTRUKSI: ")[1] for line in lines if "INSTRUKSI" in line]
    assert announced == ["Duduk", "Mundur"] and len(beeps) == 2


# --- fetch-colors ------------------------------------------------------------------------


def fake_tar(rows=None):
    import io
    import tarfile

    i = np.arange(32 * 32 * 32)
    centers = np.stack([i % 32, (i // 32) % 32, i // 1024], axis=1) * 8 + 3.5
    probs = np.full((i.size, 11), 1 / 11)
    data = np.hstack([centers, probs]) if rows is None else rows
    text = "\n".join(" ".join(f"{v:.6f}" for v in row) for row in data).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(cli.COLORS_MEMBER)
        info.size = len(text)
        tar.addfile(info, io.BytesIO(text))
    return buf.getvalue()


def test_extract_w2c_checks_format():
    table = cli.extract_w2c(fake_tar())
    assert table.shape == (32768, 11) and table.dtype == np.float32
    i = np.arange(32 * 32 * 32)
    wrong = np.hstack(
        [np.stack([i // 1024, (i // 32) % 32, i % 32], 1) * 8 + 3.5, np.ones((i.size, 11)) / 11]
    )
    with pytest.raises(cli.DemoError, match="urutan"):
        cli.extract_w2c(fake_tar(wrong))


def test_fetch_colors_checks_sha_and_writes_npy(tmp_path, monkeypatch, capsys):
    import hashlib

    settings = load_settings(DEV_YAML)
    tar = fake_tar()
    args = argparse.Namespace(models_dir=tmp_path / "models")
    with pytest.raises(cli.DemoError, match="sha256"):
        cli.cmd_fetch_colors(args, settings, download=lambda url: tar)
    assert not (tmp_path / "models").exists()

    monkeypatch.setattr(cli, "COLORS_TAR_SHA256", hashlib.sha256(tar).hexdigest())
    assert cli.cmd_fetch_colors(args, settings, download=lambda url: tar) == 0
    saved = tmp_path / "models" / "color_names_w2c.npy"
    assert np.load(saved).shape == (32768, 11)
    assert f"sha256 {hashlib.sha256(saved.read_bytes()).hexdigest()}" in capsys.readouterr().out
    assert sorted(p.name for p in (tmp_path / "models").iterdir()) == ["color_names_w2c.npy"]


def test_fetch_colors_refused_in_kiosk(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda path: _kiosk_settings())
    assert cli.main(["fetch-colors"]) == 2
    assert "app.mode: dev" in capsys.readouterr().err
