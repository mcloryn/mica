"""Coretan versi kios di atas video: tanda sudut di sekitar orang dan pita nama warna bajunya.

Versi debug (kotak biru, kerangka badan, conf) tetap memakai result.plot() bawaan Ultralytics.
"""

import cv2

PAPER = (236, 240, 238)  # BGR dari #eef0ec, warna latar halaman web
FONT = cv2.FONT_HERSHEY_DUPLEX


def draw_corners(image, box, color=PAPER, thickness=2):
    """Gambar 4 sudut siku di kotak (x1, y1, x2, y2), seperti jendela bidik kamera."""
    x1, y1, x2, y2 = box
    length = max(12, int(min(x2 - x1, y2 - y1) * 0.18))  # panjang garis sudut, ikut ukuran kotak
    for x, y, dx, dy in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
        cv2.line(image, (x, y), (x + dx * length, y), color, thickness, cv2.LINE_AA)
        cv2.line(image, (x, y), (x, y + dy * length), color, thickness, cv2.LINE_AA)


def draw_color_tag(image, text, x, y, rgb):
    """Gambar pita berisi `text` di atas titik (x, y), diisi warna `rgb` (warna baju)."""
    scale, font_thickness, padding = 0.6, 1, 8
    (width, height), _ = cv2.getTextSize(text, FONT, scale, font_thickness)
    y = max(y, height + 2 * padding)  # jangan sampai keluar dari tepi atas gambar
    x2, y1 = x + width + 2 * padding, y - height - 2 * padding
    fill = (rgb[2], rgb[1], rgb[0])  # OpenCV memakai urutan BGR
    cv2.rectangle(image, (x, y1), (x2, y), fill, -1)
    cv2.rectangle(image, (x, y1), (x2, y), PAPER, 1)  # garis tepi supaya pita hitam tetap terlihat
    # Teks gelap di atas warna terang, teks terang di atas warna gelap.
    is_light = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] > 150
    text_color = (30, 30, 30) if is_light else PAPER
    cv2.putText(image, text, (x + padding, y - padding), FONT, scale, text_color, font_thickness, cv2.LINE_AA)
