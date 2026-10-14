"""Membuka sumber gambar: webcam atau file video."""

import sys

import cv2


def open_source(source):
    """Buka webcam (jika source berupa angka, misalnya "0") atau file video.

    Kembalikan (capture, is_file).
    """
    if str(source).isdigit():
        # Di Windows, backend DirectShow (DSHOW) membuka webcam lebih cepat daripada bawaan.
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        return cv2.VideoCapture(int(source), backend), False
    return cv2.VideoCapture(str(source)), True
