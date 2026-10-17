"""Jendela pratinjau vision (dev saja): box, keypoint, area torso, state, warna, FPS, aba-aba.

Dipakai demo (proses tunggal) dan vision worker dengan bus-demo --preview (jendela dibuka di
proses kamera, jadi frame tidak pernah lewat bus). Tidak pernah menulis gambar ke disk (N-08).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mica.vision.color import ColorResult
from mica.vision.presence import PresenceState
from mica.vision.region import L_HIP, L_SHOULDER, R_HIP, R_SHOULDER
from mica.vision.types import PersonTrack

WINDOW = "MICA vision demo (q = keluar)"


@dataclass
class Overlay:
    """Hasil deteksi terakhir, digambar ulang di frame terbaru di antara deteksi."""

    tracks: list[PersonTrack] = field(default_factory=list)
    state: str = PresenceState.IDLE
    target: int | None = None
    region_rect: tuple[int, int, int, int] | None = None
    region_source: str | None = None
    color: ColorResult | None = None
    observations: list[Any] = field(default_factory=list)


def current_prompt(
    prompts: list[tuple[float, str]], elapsed: float
) -> tuple[str | None, tuple[float, str] | None]:
    """(instruksi yang berlaku, (detik, instruksi) berikutnya)."""
    now = None
    upcoming = None
    for at, text in sorted(prompts):
        if at <= elapsed:
            now = text
        elif upcoming is None:
            upcoming = (at, text)
    return now, upcoming


def _banner(frame: Any, lines: list[str]) -> None:
    import cv2

    h, w = frame.shape[:2]
    top = h - 34 * len(lines) - 12
    cv2.rectangle(frame, (0, top), (w, h), (0, 0, 0), -1)
    for i, line in enumerate(lines):
        scale, thick = (0.9, 2) if i == 0 else (0.6, 1)
        y = top + 32 + 34 * i
        cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick)


def _prompt_lines(
    prompts: list[tuple[float, str]], elapsed: float, seconds: float | None
) -> list[str]:
    now, upcoming = current_prompt(prompts, elapsed)
    lines = [now] if now else []
    if upcoming is not None:
        lines.append(f"Berikutnya dalam {upcoming[0] - elapsed:.0f} s: {upcoming[1]}")
    if seconds is not None:
        lines.append(f"Sisa waktu rekaman {max(seconds - elapsed, 0):.0f} s")
    return lines


def _color_text(result: ColorResult | None) -> str:
    if result is None or result.top is None:
        return "warna -"
    return f"warna {result.top} {result.majority:.2f}" + ("" if result.label else " (ragu)")


TORSO_POINTS = (L_SHOULDER, R_SHOULDER, L_HIP, R_HIP)


def _draw(
    frame: Any,
    overlay: Overlay,
    display_fps: float,
    detect_fps: float,
    lines: list[str],
    kp_conf: float | None,
) -> int:
    import cv2

    h = frame.shape[0]
    font = cv2.FONT_HERSHEY_SIMPLEX
    for t in overlay.tracks:
        x1, y1, x2, y2 = (int(v) for v in t.box_xyxy)
        color = (0, 200, 0) if t.track_id == overlay.target else (200, 200, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"id {t.track_id} r={t.height_ratio(h):.2f}"
        cv2.putText(frame, label, (x1, max(y1 - 6, 12)), font, 0.5, color, 1)
        if t.keypoints is not None:
            for i in TORSO_POINTS:
                x, y, c = (float(v) for v in t.keypoints[i][:3])
                ok = kp_conf is None or c >= kp_conf
                cv2.circle(frame, (int(x), int(y)), 5, (0, 255, 255) if ok else (0, 0, 160), -1)
    if overlay.region_rect is not None:
        x1, y1, x2, y2 = overlay.region_rect
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 255), 2)
        text = f"{_color_text(overlay.color)} [{overlay.region_source}]"
        cv2.putText(frame, text, (x1, min(y2 + 18, h - 4)), font, 0.6, (255, 0, 255), 2)
    status = f"{overlay.state} | tampilan {display_fps:.1f} FPS | deteksi {detect_fps:.1f} FPS"
    cv2.putText(frame, status, (8, 22), font, 0.6, (0, 0, 255), 2)
    if lines:
        _banner(frame, lines)
    cv2.imshow(WINDOW, frame)
    return cv2.waitKey(1) & 0xFF
