"""Mencari area baju dari titik tubuh (keypoints) hasil YOLO pose."""

from mica.config import SETTINGS

# Nomor titik tubuh dalam format COCO (17 titik, dihitung dari 0).
LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_HIP, RIGHT_HIP = 11, 12

# Nilai kalibrasi dari config/mica.yaml.
MIN_KEYPOINT_CONF = SETTINGS["shirt_region"]["min_keypoint_conf"]
SHRINK = SETTINGS["shirt_region"]["shrink"]
MIN_SIZE = SETTINGS["shirt_region"]["min_size"]


def shirt_region(keypoints, frame_height, frame_width,
                 min_conf=MIN_KEYPOINT_CONF, shrink=SHRINK, min_size=MIN_SIZE):
    """Kembalikan kotak area baju (x1, y1, x2, y2) atau None jika bahu tidak terlihat.

    keypoints: array 17 x 3 berisi (x, y, keyakinan) untuk satu orang.
    """
    left_shoulder, right_shoulder = keypoints[LEFT_SHOULDER], keypoints[RIGHT_SHOULDER]
    if left_shoulder[2] < min_conf or right_shoulder[2] < min_conf:
        return None

    x1 = min(left_shoulder[0], right_shoulder[0])
    x2 = max(left_shoulder[0], right_shoulder[0])
    top = (left_shoulder[1] + right_shoulder[1]) / 2

    # Batas bawah: rata-rata pinggul yang terlihat. Jika pinggul tidak terlihat
    # (misalnya duduk di depan laptop), pakai tepi bawah frame.
    hips = [keypoints[i][1] for i in (LEFT_HIP, RIGHT_HIP) if keypoints[i][2] >= min_conf]
    bottom = sum(hips) / len(hips) if hips else frame_height

    # Kecilkan area dari tiap sisi supaya lengan dan latar belakang tidak ikut terbaca.
    dx = (x2 - x1) * shrink
    dy = (bottom - top) * shrink
    x1, x2 = max(0, int(x1 + dx)), min(frame_width, int(x2 - dx))
    y1, y2 = max(0, int(top + dy)), min(frame_height, int(bottom - dy))

    if x2 - x1 < min_size or y2 - y1 < min_size:  # terlalu kecil untuk dibaca warnanya
        return None
    return x1, y1, x2, y2
