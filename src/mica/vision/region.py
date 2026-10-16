"""M-07 area pakaian (ADR-13, Terbuka): piksel dada dari satu track, hanya di memori (N-08)."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from mica.vision.types import PersonTrack

Rect = tuple[int, int, int, int]  # x1, y1, x2, y2 piksel, sudah dipotong ke frame


class ClothingRegion(Protocol):
    def extract(self, frame: np.ndarray, track: PersonTrack) -> np.ndarray | None: ...


class BoxUpperRegion:
    """Potongan kotak: baris top..bottom dan kolom side..(1-side), fraksi dari box orang."""

    def __init__(self, top: float, bottom: float, side: float) -> None:
        self.top = top
        self.bottom = bottom
        self.side = side

    def rect(self, frame_shape: tuple[int, ...], track: PersonTrack) -> Rect | None:
        h, w = frame_shape[:2]
        x1, y1, x2, y2 = track.box_xyxy
        bw, bh = x2 - x1, y2 - y1
        rx1 = max(round(x1 + self.side * bw), 0)
        rx2 = min(round(x2 - self.side * bw), w)
        ry1 = max(round(y1 + self.top * bh), 0)
        ry2 = min(round(y1 + self.bottom * bh), h)
        if rx2 <= rx1 or ry2 <= ry1:
            return None
        return rx1, ry1, rx2, ry2

    def extract(self, frame: np.ndarray, track: PersonTrack) -> np.ndarray | None:
        r = self.rect(frame.shape, track)
        if r is None:
            return None
        x1, y1, x2, y2 = r
        return frame[y1:y2, x1:x2]


class KeypointTorsoRegion:
    """Torso dari keypoint bahu dan pinggul (model -pose); belum dibuat, untuk E-08."""

    def extract(self, frame: np.ndarray, track: PersonTrack) -> np.ndarray | None:
        raise NotImplementedError(
            "KeypointTorsoRegion (vision.region: keypoint_torso) butuh model yolo26n-pose dan "
            "dibuat untuk E-08; pakai vision.region: box_upper"
        )
