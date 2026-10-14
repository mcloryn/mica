"""Rekam video uji dari webcam, lalu catat keterangannya di data/video/video_list.csv.

Contoh:
    python scripts/record_video.py --shirt putih --light redup --split dev
    python scripts/record_video.py --shirt hitam --light terang --split dev --seconds 20

Video disimpan di data/video/ (tidak ikut ke GitHub karena berisi wajah orang).
Dua detik pertama tidak direkam karena kamera masih menyesuaikan cahaya.
Tekan q untuk berhenti lebih awal.
"""

import argparse
import csv
import sys
import time
from datetime import datetime

import cv2

from mica.config import ROOT
from mica.vision.camera import open_source

VIDEO_DIR = ROOT / "data" / "video"
VIDEO_LIST = VIDEO_DIR / "video_list.csv"
COLUMNS = ["file", "split", "lighting", "shirt", "people", "seconds", "frames", "fps", "note"]
FOURCC = cv2.VideoWriter_fourcc(*"mp4v")
WARMUP_SECONDS = 2.0  # kamera masih menyesuaikan cahaya, jadi belum direkam


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--shirt", required=True,
                   help="warna baju sebenarnya; jika lebih dari satu orang, pisahkan dengan / (misal putih/hitam)")
    p.add_argument("--light", required=True, choices=["terang", "redup"])
    p.add_argument("--split", required=True, choices=["dev", "uji"])
    p.add_argument("--people", type=int, default=1, help="jumlah orang di video")
    p.add_argument("--seconds", type=float, default=15.0, help="lama rekaman")
    p.add_argument("--note", default="", help="misalnya: berjalan melintas, jarak 3 m")
    p.add_argument("--camera", default="0", help="indeks webcam")
    return p.parse_args()


def check_video_list():
    """Hentikan program jika video_list.csv masih memakai format kolom lama."""
    if VIDEO_LIST.exists():
        with open(VIDEO_LIST, encoding="utf-8") as f:
            header = f.readline().strip().split(",")
        if header != COLUMNS:
            sys.exit("data/video/video_list.csv memakai format kolom yang berbeda. "
                     f"Kolom yang benar: {','.join(COLUMNS)}")


def rewrite_with_fps(source, target, fps, size):
    """Salin video frame demi frame ke file baru dengan FPS yang benar."""
    reader = cv2.VideoCapture(str(source))
    writer = cv2.VideoWriter(str(target), FOURCC, fps, size)
    while True:
        ok, frame = reader.read()
        if not ok:
            break
        writer.write(frame)
    reader.release()
    writer.release()


def main():
    args = parse_args()
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    check_video_list()

    capture, _ = open_source(args.camera)
    if not capture.isOpened():
        sys.exit(f"Tidak bisa membuka kamera: {args.camera}")

    ok, frame = capture.read()
    if not ok:
        sys.exit("Kamera terbuka tetapi tidak mengirim gambar.")
    height, width = frame.shape[:2]

    name = f"{args.split}_{args.light}_{args.shirt.replace('/', '-')}_{datetime.now():%Y%m%d_%H%M%S}.mp4"
    temp_file = VIDEO_DIR / f"_sementara_{name}"
    # FPS asli kamera baru diketahui setelah rekaman selesai. Jadi rekam dulu ke file
    # sementara (FPS-nya asal), lalu salin ke file akhir dengan FPS yang terukur.
    writer = cv2.VideoWriter(str(temp_file), FOURCC, 30.0, (width, height))

    start = time.perf_counter()
    recording_start = None
    frames = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        now = time.perf_counter()
        preview = frame.copy()
        if now - start < WARMUP_SECONDS:
            cv2.putText(preview, "Menyiapkan kamera...", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 200, 255), 2)
        else:
            if recording_start is None:
                recording_start = now
            writer.write(frame)
            frames += 1
            remaining = args.seconds - (now - recording_start)
            cv2.putText(preview, f"REKAM  sisa {remaining:4.1f} detik", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            if remaining <= 0:
                break
        cv2.imshow("MICA - rekam video uji (q untuk berhenti)", preview)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    duration = time.perf_counter() - recording_start if recording_start else 0.0
    capture.release()
    writer.release()
    cv2.destroyAllWindows()

    if frames == 0 or duration <= 0:
        temp_file.unlink(missing_ok=True)
        sys.exit("Tidak ada frame yang terekam.")

    fps = frames / duration
    rewrite_with_fps(temp_file, VIDEO_DIR / name, fps, (width, height))
    temp_file.unlink()

    is_new_list = not VIDEO_LIST.exists()
    with open(VIDEO_LIST, "a", newline="", encoding="utf-8") as f:
        list_writer = csv.writer(f)
        if is_new_list:
            list_writer.writerow(COLUMNS)
        list_writer.writerow([name, args.split, args.light, args.shirt, args.people,
                              f"{duration:.1f}", frames, f"{fps:.2f}", args.note])

    print(f"Tersimpan: data/video/{name} ({frames} frame, {duration:.1f} detik, {fps:.1f} FPS)")


if __name__ == "__main__":
    main()
