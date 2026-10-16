"""Tipe data M-07: track orang dan event vision (SDD M-07, tabel pesan bus)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

Box = tuple[float, float, float, float]  # x1, y1, x2, y2 dalam piksel frame


@dataclass(frozen=True)
class PersonTrack:
    track_id: int
    box_xyxy: Box
    conf: float
    keypoints: np.ndarray | None = None  # (17, 3) x, y, skor bila model pose; None bila bukan

    @property
    def height(self) -> float:
        return self.box_xyxy[3] - self.box_xyxy[1]

    def height_ratio(self, frame_h: int) -> float:
        return self.height / frame_h if frame_h > 0 else 0.0


@dataclass(frozen=True)
class PersonArrived:
    track_id: int
    box_xyxy: Box
    t: float  # waktu monotonic
    # diisi di langkah warna pakaian (ADR-13, ADR-14); None = sapaan umum
    color: str | None = None
    color_confidence: float | None = None


@dataclass(frozen=True)
class PersonLeft:
    track_id: int
    t: float
    duration_s: float  # sejak PersonArrived


@dataclass(frozen=True)
class CameraStatus:
    ok: bool
    message: str
    fps: float | None = None


VisionEvent = PersonArrived | PersonLeft | CameraStatus
