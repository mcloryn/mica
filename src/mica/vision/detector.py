"""M-07 PersonDetector: deteksi dan pelacakan orang (ADR-12 YOLO26n, ADR-15 ByteTrack).

Ultralytics diimpor secara lazy supaya modul lain dan tes tidak ikut memuat torch. Bobot model
harus sudah ada di models/ (python -m mica.vision fetch-model, dev saja); detektor tidak pernah
mengunduh saat runtime.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from mica.core.types import ErrorCode
from mica.vision.types import PersonTrack

DEFAULT_MODELS_DIR = Path("models")
PERSON_CLASS = 0  # COCO "person"
DEVICE = "cpu"  # N-02: laptop tanpa GPU


class ModelMissing(Exception):
    def __init__(self, path: Path) -> None:
        self.code = ErrorCode.VISION_MODEL_MISSING
        self.path = path
        super().__init__(
            f"{self.code}: bobot model {path.as_posix()} tidak ada; "
            "unduh dulu di mode dev: python -m mica.vision fetch-model"
        )


class PersonDetector(Protocol):
    def detect_and_track(self, frame: np.ndarray) -> list[PersonTrack]: ...


def model_path(model: str, models_dir: Path = DEFAULT_MODELS_DIR) -> Path:
    """vision.model ("yolo26n") -> models/yolo26n.pt."""
    return Path(models_dir) / f"{model}.pt"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def disable_ultralytics_sync() -> None:
    """Matikan analitik dan laporan crash Ultralytics (tersimpan di settings pengguna)."""
    from ultralytics import settings

    settings.update({"sync": False})


def _load_yolo(path: str) -> Any:
    from ultralytics import YOLO

    return YOLO(path)


def _np(value: Any) -> np.ndarray:
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        return value.numpy()
    return np.asarray(value)


def tracks_from_result(result: Any) -> list[PersonTrack]:
    """Results Ultralytics -> PersonTrack; box tanpa ID track (is_track False) dilewati."""
    boxes = result.boxes
    if boxes is None or len(boxes) == 0 or not boxes.is_track:
        return []
    ids = _np(boxes.id)
    xyxy = _np(boxes.xyxy)
    conf = _np(boxes.conf)
    keypoints = getattr(result, "keypoints", None)
    kp = _np(keypoints.data) if keypoints is not None else None
    tracks = []
    for i in range(len(ids)):
        x1, y1, x2, y2 = (float(v) for v in xyxy[i])
        tracks.append(
            PersonTrack(
                track_id=int(ids[i]),
                box_xyxy=(x1, y1, x2, y2),
                conf=float(conf[i]),
                keypoints=kp[i] if kp is not None else None,
            )
        )
    return tracks


class UltralyticsDetector:
    def __init__(
        self,
        model_file: Path,
        tracker: str,
        conf: float | None,
        imgsz: int | None,
        model_factory: Callable[[str], Any] = _load_yolo,
    ) -> None:
        model_file = Path(model_file)
        if not model_file.is_file():
            raise ModelMissing(model_file)  # jangan biarkan Ultralytics mengunduh
        disable_ultralytics_sync()
        self.model_file = model_file
        self.tracker = tracker  # wajib eksplisit: bawaan Ultralytics 8.4 adalah TrackTrack
        self.conf = conf
        self.imgsz = imgsz
        self.model = model_factory(str(model_file))

    def detect_and_track(self, frame: np.ndarray) -> list[PersonTrack]:
        kwargs: dict[str, Any] = {
            "persist": True,
            "tracker": self.tracker,
            "classes": [PERSON_CLASS],
            "device": DEVICE,
            "save": False,
            "verbose": False,
        }
        if self.conf is not None:
            kwargs["conf"] = self.conf
        if self.imgsz is not None:
            kwargs["imgsz"] = self.imgsz
        results = self.model.track(frame, **kwargs)
        return tracks_from_result(results[0]) if results else []
