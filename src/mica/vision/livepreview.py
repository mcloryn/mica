"""Pratinjau kamera untuk UI kiosk (ui.camera_preview; Langkah 37). Berbeda dengan preview.py (jendela
OpenCV dev): di sini gambar kecil dibuat di proses kamera, di-JPEG di memori, lalu dikirim lewat
antrean multiprocessing TERPISAH dari bus event (maxsize 1, frame lama dibuang). Bus event tetap
tanpa frame (SDD M-13); tidak ada yang ditulis ke disk (N-08).

- Gambar dikecilkan ke lebar PREVIEW_WIDTH lalu dicerminkan horizontal (seperti cermin).
- public: SELURUH gambar di-pixelate kecuali kotak target; tanpa target seluruh gambar
  di-pixelate (aman-gagal: orang yang tidak terdeteksi juga tersamar). Overlay: kotak target +
  label warna, tanpa angka.
- debug (dev saja): tanpa pixelate; overlay semua kotak orang, kotak target, area baju yang
  dipakai, label warna, lebar bahu, dan skor.
- Overlay memakai hasil deteksi terakhir; pratinjau tidak pernah memanggil detektor.
"""

from __future__ import annotations

import queue
from typing import Any

import numpy as np

from mica.vision.region import Rect, shoulder_width_ratio
from mica.vision.types import PersonTrack

PREVIEW_WIDTH = 320  # px; lebar gambar pratinjau (nilai desain)
JPEG_QUALITY = 70  # nilai desain
MODES = ("off", "public", "debug")
# warna overlay (BGR); bukan token UI karena digambar di gambar, bukan di halaman
TARGET_BGR = (0, 200, 255)
OTHER_BGR = (200, 200, 200)
REGION_BGR = (255, 160, 0)


def pixelate(image: np.ndarray, block: int) -> np.ndarray:
    """Rata-rata per blok block x block (INTER_AREA), lalu diperbesar tanpa interpolasi."""
    import cv2

    h, w = image.shape[:2]
    small = cv2.resize(image, (max(1, w // block), max(1, h // block)),
                       interpolation=cv2.INTER_AREA)  # fmt: skip
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def _mirror_box(box: tuple[float, float, float, float], scale: float, width: int) -> Rect:
    x1, y1, x2, y2 = (v * scale for v in box)
    rx1, rx2 = width - x2, width - x1
    return round(rx1), round(y1), round(rx2), round(y2)


def _clip(rect: Rect, w: int, h: int) -> Rect | None:
    x1, y1, x2, y2 = max(rect[0], 0), max(rect[1], 0), min(rect[2], w), min(rect[3], h)
    return None if x2 <= x1 or y2 <= y1 else (x1, y1, x2, y2)


class PreviewRenderer:
    """render(frame, tracks, target, region, color) -> gambar BGR kecil yang sudah dicerminkan."""

    def __init__(self, mode: str, pixel_block: int, min_kp_conf: float | None = None,
                 width: int = PREVIEW_WIDTH) -> None:  # fmt: skip
        if mode not in ("public", "debug"):
            raise ValueError(f"mode pratinjau harus public atau debug, bukan {mode!r}")
        self.mode = mode
        self.pixel_block = pixel_block
        self.min_kp_conf = min_kp_conf
        self.width = width

    def base(self, frame: np.ndarray) -> tuple[np.ndarray, float]:
        """Gambar dikecilkan dan dicerminkan (tanpa pixelate/overlay) + faktor skala."""
        import cv2

        h, w = frame.shape[:2]
        scale = self.width / w
        small = cv2.resize(frame, (self.width, max(1, round(h * scale))),
                           interpolation=cv2.INTER_AREA)  # fmt: skip
        return cv2.flip(small, 1), scale

    def render(
        self,
        frame: np.ndarray,
        tracks: list[PersonTrack],
        target: PersonTrack | None,
        region: Rect | None,
        color: str | None,
    ) -> np.ndarray:
        import cv2

        image, scale = self.base(frame)
        h, w = image.shape[:2]
        target_rect = _clip(_mirror_box(target.box_xyxy, scale, w), w, h) if target else None
        if self.mode == "public":
            out = pixelate(image, self.pixel_block)
            if target_rect is not None:  # hanya kotak target yang tidak disamarkan
                x1, y1, x2, y2 = target_rect
                out[y1:y2, x1:x2] = image[y1:y2, x1:x2]
            image = out
        else:
            for t in tracks:
                if target is not None and t.track_id == target.track_id:
                    continue
                r = _clip(_mirror_box(t.box_xyxy, scale, w), w, h)
                if r is not None:
                    cv2.rectangle(image, r[:2], r[2:], OTHER_BGR, 1)
                    cv2.putText(image, f"{t.track_id} {t.conf:.2f}", (r[0] + 2, r[1] + 12),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.35, OTHER_BGR, 1)  # fmt: skip
            if region is not None:
                rr = _clip(_mirror_box(region, scale, w), w, h)
                if rr is not None:
                    cv2.rectangle(image, rr[:2], rr[2:], REGION_BGR, 1)
        if target_rect is not None:
            x1, y1, x2, y2 = target_rect
            cv2.rectangle(image, (x1, y1), (x2 - 1, y2 - 1), TARGET_BGR, 2)
            label = color or ""
            if self.mode == "debug" and target is not None:
                ratio = (shoulder_width_ratio(target, frame.shape[1], self.min_kp_conf)
                         if self.min_kp_conf is not None else None)  # fmt: skip
                label = f"{label} {target.conf:.2f}" + (f" bahu {ratio:.2f}" if ratio else "")
            if label.strip():
                cv2.putText(image, label.strip(), (x1 + 4, y1 + 16), cv2.FONT_HERSHEY_SIMPLEX,
                            0.45, TARGET_BGR, 1, cv2.LINE_AA)  # fmt: skip
        return image


def encode_jpeg(image: np.ndarray, quality: int = JPEG_QUALITY) -> bytes:
    """JPEG di memori (cv2.imencode); tidak pernah ke disk (N-08)."""
    import cv2

    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("encode JPEG pratinjau gagal")
    return buf.tobytes()


def put_latest(q: Any, item: Any, attempts: int = 3) -> bool:
    """Taruh item di antrean maxsize 1; bila penuh, item lama dibuang dulu (frame lama dibuang)."""
    for _ in range(attempts):
        try:
            q.put_nowait(item)
            return True
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
    return False
