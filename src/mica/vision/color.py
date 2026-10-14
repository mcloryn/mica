"""Membaca warna baju di ruang warna CIELAB (Lab) dengan referensi terdekat (CIE76)."""

import cv2
import numpy as np

from mica.config import SETTINGS

# Warna referensi dalam RGB, diatur di config/mica.yaml (bagian reference_colors).
REFERENCE_RGB = {name: tuple(rgb) for name, rgb in SETTINGS["reference_colors"].items()}


def to_lab(image_bgr):
    """Ubah gambar BGR 8-bit menjadi Lab dengan L 0..100 dan a, b sekitar -127..127."""
    # Dibagi 255 dulu supaya OpenCV memakai rumus float dan memberi nilai Lab asli.
    return cv2.cvtColor(image_bgr.astype(np.float32) / 255, cv2.COLOR_BGR2LAB)


# Hitung Lab tiap warna referensi sekali saja, saat modul dimuat.
COLOR_NAMES = list(REFERENCE_RGB)
REFERENCE_BGR = np.array([[(b, g, r) for r, g, b in REFERENCE_RGB.values()]], dtype=np.uint8)
REFERENCE_LAB = to_lab(REFERENCE_BGR)[0]  # bentuknya (jumlah warna) x 3


def read_color(patch):
    """Kembalikan (nama_warna, lab_median, jarak) untuk satu potongan area baju."""
    lab = to_lab(patch).reshape(-1, 3)        # semua piksel jadi daftar N x 3
    median = np.median(lab, axis=0)           # warna "tengah", tahan terhadap bayangan kecil
    distances = np.linalg.norm(REFERENCE_LAB - median, axis=1)  # CIE76: jarak lurus di ruang Lab
    nearest = int(np.argmin(distances))
    return COLOR_NAMES[nearest], median, float(distances[nearest])
