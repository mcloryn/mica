"""CV-3c: opsi uji kemampuan --test-exposure (exposure kamera manual), bawaan MATI."""

from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml
from test_bus import TEST_VALUES, _settings
from test_vision_color import fake_table

from mica.vision.camera import DSHOW_AUTO_EXPOSURE_AUTO, DSHOW_AUTO_EXPOSURE_MANUAL, Camera
from mica.vision.color import DEFAULT_COLORS_FILE
from mica.vision.worker import VisionWorkerConfig, WorkerConfigError, _make_camera
from mica.webui import app as webapp

ROOT = Path(__file__).resolve().parents[2]


class RecordingCapture:
    def __init__(self) -> None:
        self.sets: list[tuple[int, float]] = []

    def isOpened(self) -> bool:  # nama API OpenCV
        return True

    def set(self, prop: int, value: float) -> bool:
        self.sets.append((prop, value))
        return True

    def read(self):
        return True, np.zeros((4, 4, 3), dtype=np.uint8)

    def release(self) -> None:
        pass


def _open(exposure, release=False):
    cap = RecordingCapture()
    camera = Camera(0, open_capture=lambda _s: cap, exposure=exposure)
    frame, _status = camera.read()
    assert frame is not None
    if release:
        camera.release()
    return cap


def test_camera_default_keeps_auto_exposure():
    assert _open(None).sets == []  # aplikasi normal: tidak menyentuh exposure
    assert _open(None, release=True).sets == []


def test_camera_test_exposure_restores_auto_on_release():
    # driver C270 menyimpan exposure manual setelah dilepas (CV-3c), jadi dipulihkan
    sets = _open(-5.0, release=True).sets
    assert sets[-1] == (cv2.CAP_PROP_AUTO_EXPOSURE, DSHOW_AUTO_EXPOSURE_AUTO)


def test_camera_test_exposure_sets_manual_value():
    assert _open(-5.0).sets == [
        (cv2.CAP_PROP_AUTO_EXPOSURE, DSHOW_AUTO_EXPOSURE_MANUAL),
        (cv2.CAP_PROP_EXPOSURE, -5.0),
    ]


def _cfg(tmp_path, mode="dev"):
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    np.save(models / DEFAULT_COLORS_FILE.name, fake_table())
    return VisionWorkerConfig.from_settings(_settings(mode), TEST_VALUES, models_dir=models)


def test_worker_config_default_off_and_passed_to_camera(tmp_path):
    cfg = _cfg(tmp_path)
    assert cfg.test_exposure is None and _make_camera(cfg).exposure is None
    on = replace(cfg, measure=True, test_exposure=-5.0)
    on.validate()
    assert _make_camera(on).exposure == -5.0


def test_worker_config_rejects_test_exposure_without_measure_or_in_prod(tmp_path):
    cfg = _cfg(tmp_path)
    with pytest.raises(WorkerConfigError, match="test-exposure"):
        replace(cfg, test_exposure=-5.0).validate()
    with pytest.raises(WorkerConfigError):
        replace(cfg, mode="prod", camera_preview="public", measure=False,
                test_exposure=-5.0).validate()  # fmt: skip


def test_start_bus_rejects_test_exposure_without_measure():
    with pytest.raises(webapp.WebUiError, match="--test-exposure"):
        webapp._start_bus(_settings(), False, False, False, measure=False, test_exposure=-5.0)


@pytest.mark.parametrize("name", ["dev.yaml", "prod.yaml"])
def test_configs_do_not_enable_manual_exposure(name):
    text = (ROOT / "config" / name).read_text(encoding="utf-8")
    assert "exposure" not in text.lower()
    raw = yaml.safe_load(text)
    assert "test_exposure" not in raw.get("vision", {})
