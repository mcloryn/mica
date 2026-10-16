"""M-07 area pakaian (ADR-13, Terbuka): piksel dada dari satu track, hanya di memori (N-08).

KeypointTorsoRegion memakai keypoint COCO bahu (5, 6) dan pinggul (11, 12) dari model -pose:
- bahu + pinggul yakin -> kotak keempat titik, dipersempit `shrink` per sisi ("keypoint");
- hanya bahu yakin (duduk dekat, pinggul tertutup) -> bawah = bahu + torso_aspect x lebar bahu,
  dibatasi bawah box ("keypoint+box");
- selain itu -> BoxUpperRegion ("fallback").
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from mica.vision.types import PersonTrack

Rect = tuple[int, int, int, int]  # x1, y1, x2, y2 piksel, sudah dipotong ke frame
L_SHOULDER, R_SHOULDER, L_HIP, R_HIP = 5, 6, 11, 12  # indeks keypoint COCO


class ClothingRegion(Protocol):
    def locate(self, frame_shape: tuple[int, ...], track: PersonTrack) -> tuple[Rect, str] | None:
        """(kotak, sumber) atau None bila tidak ada area yang bisa dipakai."""
        ...

    def extract(self, frame: np.ndarray, track: PersonTrack) -> np.ndarray | None: ...


def _clip(x1: float, y1: float, x2: float, y2: float, frame_shape: tuple[int, ...]) -> Rect | None:
    h, w = frame_shape[:2]
    rx1, ry1 = max(round(x1), 0), max(round(y1), 0)
    rx2, ry2 = min(round(x2), w), min(round(y2), h)
    if rx2 <= rx1 or ry2 <= ry1:
        return None
    return rx1, ry1, rx2, ry2


def _crop(frame: np.ndarray, located: tuple[Rect, str] | None) -> np.ndarray | None:
    if located is None:
        return None
    x1, y1, x2, y2 = located[0]
    return frame[y1:y2, x1:x2]


class BoxUpperRegion:
    """Potongan kotak: baris top..bottom dan kolom side..(1-side), fraksi dari box orang."""

    def __init__(self, top: float, bottom: float, side: float) -> None:
        self.top = top
        self.bottom = bottom
        self.side = side

    def rect(self, frame_shape: tuple[int, ...], track: PersonTrack) -> Rect | None:
        x1, y1, x2, y2 = track.box_xyxy
        bw, bh = x2 - x1, y2 - y1
        return _clip(
            x1 + self.side * bw, y1 + self.top * bh, x2 - self.side * bw, y1 + self.bottom * bh,
            frame_shape,
        )  # fmt: skip

    def locate(self, frame_shape: tuple[int, ...], track: PersonTrack) -> tuple[Rect, str] | None:
        r = self.rect(frame_shape, track)
        return None if r is None else (r, "box")

    def extract(self, frame: np.ndarray, track: PersonTrack) -> np.ndarray | None:
        return _crop(frame, self.locate(frame.shape, track))


def _confident(keypoints: np.ndarray | None, index: int, min_conf: float) -> bool:
    return (
        keypoints is not None
        and len(keypoints) > index
        and keypoints.shape[-1] >= 3
        and float(keypoints[index][2]) >= min_conf
    )


def shoulder_width_ratio(track: PersonTrack, frame_w: int, min_conf: float) -> float | None:
    """|x bahu kiri - x bahu kanan| / lebar frame; None bila bahu tidak yakin."""
    kp = track.keypoints
    if frame_w <= 0 or not (
        _confident(kp, L_SHOULDER, min_conf) and _confident(kp, R_SHOULDER, min_conf)
    ):
        return None
    assert kp is not None
    return abs(float(kp[L_SHOULDER][0]) - float(kp[R_SHOULDER][0])) / frame_w


class KeypointTorsoRegion:
    def __init__(
        self, min_kp_conf: float, shrink: float, torso_aspect: float, fallback: BoxUpperRegion
    ) -> None:
        self.min_kp_conf = min_kp_conf
        self.shrink = shrink
        self.torso_aspect = torso_aspect
        self.fallback = fallback

    def _torso(self, frame_shape: tuple[int, ...], track: PersonTrack) -> tuple[Rect, str] | None:
        kp = track.keypoints
        c = self.min_kp_conf
        if kp is None or not (_confident(kp, L_SHOULDER, c) and _confident(kp, R_SHOULDER, c)):
            return None
        shoulders = kp[[L_SHOULDER, R_SHOULDER], :2].astype(float)
        top = float(shoulders[:, 1].min())
        if _confident(kp, L_HIP, c) and _confident(kp, R_HIP, c):
            hips = kp[[L_HIP, R_HIP], :2].astype(float)
            points = np.vstack([shoulders, hips])
            bottom = float(hips[:, 1].max())
            source = "keypoint"
        else:
            points = shoulders
            width = float(abs(shoulders[0, 0] - shoulders[1, 0]))
            bottom = min(top + self.torso_aspect * width, track.box_xyxy[3])
            source = "keypoint+box"
        x1, x2 = float(points[:, 0].min()), float(points[:, 0].max())
        dx, dy = self.shrink * (x2 - x1), self.shrink * (bottom - top)
        rect = _clip(x1 + dx, top + dy, x2 - dx, bottom - dy, frame_shape)
        return None if rect is None else (rect, source)

    def locate(self, frame_shape: tuple[int, ...], track: PersonTrack) -> tuple[Rect, str] | None:
        torso = self._torso(frame_shape, track)
        if torso is not None:
            return torso
        r = self.fallback.rect(frame_shape, track)
        return None if r is None else (r, "fallback")

    def extract(self, frame: np.ndarray, track: PersonTrack) -> np.ndarray | None:
        return _crop(frame, self.locate(frame.shape, track))
