"""MICA Computer Vision: deteksi orang, tracking, warna baju (Lab), dan sapaan.

Contoh:
    python scripts/run_cv.py                                  # webcam
    python scripts/run_cv.py --source data/video/uji_x.mp4    # video rekaman (untuk pengujian)
    python scripts/run_cv.py --source data/video/uji_x.mp4 --no-display

Tekan q untuk berhenti.
Setiap run membuat folder logs/<waktu>/ berisi:
    events.csv      kapan orang terlihat (seen), disapa (greeted, dengan warnanya), dan pergi (left)
    info.txt        sumber video, jumlah frame, dan FPS rata-rata
    mica.yaml, bytetrack_mica.yaml   salinan pengaturan yang dipakai run ini

Logika CV-nya ada di src/mica/vision/pipeline.py, sama dengan yang dipakai aplikasi web.
"""

import argparse
import csv
import shutil
import sys
import time
from datetime import datetime

import cv2

from mica.config import ROOT, SETTINGS_FILE, TRACKER_FILE
from mica.greeting import make_greeting
from mica.vision.camera import open_source
from mica.vision.pipeline import GREETED, MODEL, SEEN, VisionPipeline

EVENT_COLUMNS = ["time_s", "frame", "event", "track_id", "color", "votes", "conf"]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default="0", help="nomor webcam (0, 1, ...) atau path file video")
    p.add_argument("--no-display", action="store_true", help="jangan tampilkan jendela video")
    return p.parse_args()


def main():
    args = parse_args()
    capture, is_file = open_source(args.source)
    if not capture.isOpened():
        sys.exit(f"Tidak bisa membuka sumber: {args.source}")
    video_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0

    # Folder log baru untuk setiap run, dinamai dengan waktu mulai.
    log_dir = ROOT / "logs" / datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "info.txt").write_text(f"sumber: {args.source}\n", encoding="utf-8")
    # Salinan config disimpan bersama log supaya setiap run tahu persis nilai yang dipakai.
    shutil.copy(SETTINGS_FILE, log_dir)
    shutil.copy(TRACKER_FILE, log_dir)

    events_file = open(log_dir / "events.csv", "w", newline="", encoding="utf-8")
    writer = csv.writer(events_file)
    writer.writerow(EVENT_COLUMNS)

    pipeline = VisionPipeline(str(ROOT / MODEL), mode="debug")
    frame_number, start = 0, time.perf_counter()

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frame_number += 1
            # Video rekaman: waktu dihitung dari nomor frame supaya hasilnya bisa diulang persis.
            now = frame_number / video_fps if is_file else time.perf_counter() - start

            image, events = pipeline.process(frame, now)
            for event in events:
                if event.kind == SEEN:
                    print(f"[ID {event.track_id}] terlihat pertama kali (conf {event.conf:.2f})")
                elif event.kind == GREETED:
                    print(f"[ID {event.track_id}] {make_greeting(event.color)}  ({event.votes} suara)")
                else:
                    print(f"[ID {event.track_id}] sudah pergi, catatannya dihapus")
                conf = "" if event.conf is None else f"{event.conf:.2f}"
                writer.writerow([f"{now:.2f}", frame_number, event.kind, event.track_id,
                                 event.color, event.votes, conf])

            if not args.no_display:
                cv2.imshow("MICA", image)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        # Bagian ini tetap dijalankan walaupun program berhenti karena error atau Ctrl+C.
        duration = time.perf_counter() - start
        fps = frame_number / duration if duration > 0 else 0.0
        capture.release()
        cv2.destroyAllWindows()
        events_file.close()
        with open(log_dir / "info.txt", "a", encoding="utf-8") as f:
            f.write(f"jumlah_frame: {frame_number}\nfps_rata_rata: {fps:.2f}\n")
        print(f"\nSelesai: {frame_number} frame, rata-rata {fps:.1f} FPS. Log di {log_dir}")


if __name__ == "__main__":
    main()
