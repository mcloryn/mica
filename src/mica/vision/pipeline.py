"""Satu langkah pemrosesan CV untuk satu frame: deteksi, tracking, warna baju, keputusan sapaan.

Dipakai bersama oleh scripts/run_cv.py (terminal, untuk pengujian) dan mica.web.app (kios),
supaya logika CV hanya ditulis di satu tempat.
"""

from dataclasses import dataclass

import cv2
from ultralytics import YOLO

from mica.config import SETTINGS, TRACKER_FILE
from mica.vision.body import shirt_region
from mica.vision.color import REFERENCE_RGB, read_color
from mica.vision.overlay import draw_color_tag, draw_corners
from mica.vision.session import SessionManager

# Semua nilai kalibrasi ada di config/mica.yaml (penjelasan tiap nilai ada di sana).
MODEL = SETTINGS["model"]
TRACK_CONF = SETTINGS["detection"]["track_conf"]
GREET_CONF = SETTINGS["detection"]["greet_conf"]
MIN_FRAMES = SETTINGS["session"]["min_frames"]
FORGET_AFTER = SETTINGS["session"]["forget_after"]

# Jenis peristiwa yang dilaporkan untuk tiap orang.
SEEN = "seen"        # pertama kali terlihat
GREETED = "greeted"  # warna bajunya sudah diputuskan, saatnya disapa
LEFT = "left"        # sudah lama tidak terlihat, catatannya dihapus

PERSON_CLASS = 0               # kelas "person" pada model COCO
DEBUG_COLOR = (255, 255, 0)    # BGR biru muda untuk area baju dan label di tampilan debug


@dataclass
class Event:
    kind: str             # SEEN, GREETED, atau LEFT
    track_id: int
    color: str = ""
    votes: str = ""       # misalnya "9/10": 9 dari 10 frame membaca warna pemenang
    conf: float | None = None


class VisionPipeline:
    def __init__(self, model=MODEL, mode="debug"):
        """mode: "debug" (kotak, kerangka, conf, area baju) atau "kiosk" (bersih, untuk pengunjung)."""
        self.model = YOLO(model)
        self.mode = mode
        self.visible = []    # orang yang terlihat di frame terakhir, untuk digambar di mode kiosk
        self.session = SessionManager(min_frames=MIN_FRAMES, forget_after=FORGET_AFTER)

    def process(self, frame, time):
        """Proses satu frame. Kembalikan (gambar_bercoret, daftar_peristiwa)."""
        events = []
        result = self.model.track(frame, persist=True, tracker=str(TRACKER_FILE),
                                  classes=[PERSON_CLASS], conf=TRACK_CONF, verbose=False)[0]
        kiosk = self.mode == "kiosk"
        image = frame.copy() if kiosk else result.plot()
        self.visible = []

        if result.boxes.id is not None:
            track_ids = result.boxes.id.int().tolist()
            confs = result.boxes.conf.tolist()
            all_keypoints = result.keypoints.data.cpu().numpy()
            boxes = result.boxes.xyxy.int().tolist()
            height, width = frame.shape[:2]

            for track_id, conf, keypoints, box in zip(track_ids, confs, all_keypoints, boxes):
                if self.session.see(track_id, time):
                    events.append(Event(SEEN, track_id, conf=conf))

                # Kotak yang kurang yakin tetap dilacak, tetapi tidak ikut memilih warna.
                if conf < GREET_CONF:
                    continue
                region = shirt_region(keypoints, height, width)
                if region is None:
                    continue
                x1, y1, x2, y2 = region
                if not kiosk:
                    cv2.rectangle(image, (x1, y1), (x2, y2), DEBUG_COLOR, 2)

                if self.session.needs_color(track_id):
                    color, _, _ = read_color(frame[y1:y2, x1:x2])
                    decision = self.session.add_vote(track_id, color)
                    if decision is not None:
                        winner, count, total = decision
                        events.append(Event(GREETED, track_id, winner, f"{count}/{total}", conf))

                self.visible.append({"box": box, "color": self.session.people[track_id].color})
                if not kiosk:
                    cv2.putText(image, self.session.label(track_id), (x1, max(15, y1 - 6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, DEBUG_COLOR, 2)

        if kiosk:
            self._draw_kiosk(image)

        for track_id in self.session.remove_stale(time):
            events.append(Event(LEFT, track_id))

        return image, events

    def _draw_kiosk(self, image):
        """Tampilan untuk pengunjung: sudut siku di sekitar orang, lalu nama warna bajunya."""
        for person in self.visible:
            draw_corners(image, person["box"])
            if person["color"] is not None:
                x1, y1 = person["box"][:2]
                draw_color_tag(image, person["color"], x1, y1 - 6, REFERENCE_RGB[person["color"]])
