"""Aplikasi web MICA: video kamera dengan deteksi, sapaan bersuara, dan tanya lewat ketik atau suara.

Jalankan dari folder utama project:
    python -m mica.web.app                                  # webcam
    python -m mica.web.app --source data/video/uji_x.mp4    # video rekaman
    python -m mica.web.app --debug                          # video dengan kotak, kerangka, dan conf
Lalu buka http://127.0.0.1:5000 di browser. Tekan Ctrl+C di terminal untuk berhenti.

Alamat yang dipakai halaman web (static/mica.js):
    GET  /video          aliran gambar kamera (MJPEG)
    GET  /greetings      sapaan baru dari kamera
    POST /ask            pertanyaan pengunjung -> jawaban MICA
    POST /speak          teks -> suara MP3 (TTS)
    POST /transcribe     rekaman suara -> teks (STT)
"""

import argparse
import threading
import time

import cv2
from flask import Flask, Response, jsonify, render_template, request

from mica.chatbot import answer
from mica.config import ROOT
from mica.greeting import make_greeting
from mica.speech.stt import load_model, transcribe
from mica.speech.tts import synthesize
from mica.vision.camera import open_source
from mica.vision.pipeline import GREETED, MODEL, VisionPipeline

app = Flask(__name__)


class SharedState:
    """Data yang ditulis thread kamera dan dibaca Flask. Kunci (lock) mencegah keduanya bertabrakan."""

    def __init__(self):
        self.lock = threading.Lock()
        self.jpeg = None          # gambar terakhir (sudah dicoret), dalam format JPEG
        self.greetings = []       # semua sapaan sejak program mulai, urut dari yang paling lama
        self.conversations = {}   # track_id -> daftar pesan; ID dari ByteTrack = ID sesi chat


state = SharedState()


# ---------- Thread kamera ----------

def run_vision(source, mode):
    """Berjalan di thread terpisah: baca kamera, proses tiap frame, simpan hasilnya ke `state`."""
    capture, is_file = open_source(source)
    if not capture.isOpened():
        print(f"Tidak bisa membuka sumber: {source}")
        return
    video_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    pipeline = VisionPipeline(str(ROOT / MODEL), mode=mode)
    frame_number, start = 0, time.perf_counter()

    while True:
        ok, frame = capture.read()
        if not ok:
            print("Sumber video habis atau kamera berhenti.")
            break
        frame_number += 1
        # Video rekaman: waktu dihitung dari nomor frame supaya hasilnya bisa diulang persis.
        now = frame_number / video_fps if is_file else time.perf_counter() - start

        image, events = pipeline.process(frame, now)
        _, jpeg = cv2.imencode(".jpg", image)

        with state.lock:
            state.jpeg = jpeg.tobytes()
            for event in events:
                if event.kind == GREETED:
                    text = make_greeting(event.color)
                    state.greetings.append({"track_id": event.track_id, "color": event.color,
                                            "votes": event.votes, "text": text, "time": round(now, 2)})
                    # Sapaan menjadi pesan pertama di sesi chat orang ini.
                    state.conversations[event.track_id] = [{"role": "mica", "text": text}]
                    print(f"[ID {event.track_id}] disapa: {event.color}")
    capture.release()


# ---------- Alamat-alamat web ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video")
def video():
    """Kirim gambar terus-menerus sebagai MJPEG: deretan JPEG yang diganti satu per satu."""
    def stream():
        while True:
            with state.lock:
                jpeg = state.jpeg
            if jpeg is not None:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            time.sleep(0.05)  # sekitar 20 gambar per detik sudah cukup untuk layar
    return Response(stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/greetings")
def greetings():
    """Kembalikan sapaan baru dalam format JSON. ?since=3 artinya: mulai dari sapaan ke-4."""
    since = request.args.get("since", default=0, type=int)
    with state.lock:
        return jsonify(state.greetings[since:])


@app.route("/ask", methods=["POST"])
def ask():
    """Terima pertanyaan dari kotak chat. Isi permintaan: {"track_id": 3, "text": "..."}."""
    body = request.get_json(silent=True) or {}
    question = str(body.get("text", "")).strip()
    track_id = body.get("track_id")  # None jika belum ada pengunjung yang disapa
    if not question:
        return jsonify({"error": "Pertanyaan kosong."}), 400

    with state.lock:
        history = state.conversations.setdefault(track_id, [])
        history.append({"role": "visitor", "text": question})
        history_copy = list(history)

    # Menjawab bisa lama (nanti memanggil LLM), jadi dilakukan di luar kunci.
    reply = answer(question, history_copy)

    with state.lock:
        state.conversations[track_id].append({"role": "mica", "text": reply})
    return jsonify({"answer": reply})


@app.route("/speak", methods=["POST"])
def speak():
    """Ubah teks menjadi suara MP3 untuk diputar browser. Isi permintaan: {"text": "..."}."""
    text = str((request.get_json(silent=True) or {}).get("text", "")).strip()
    if not text:
        return jsonify({"error": "Teks kosong."}), 400
    try:
        mp3 = synthesize(text)
    except Exception as error:  # biasanya karena internet putus
        print(f"Suara gagal dibuat: {error}")
        return jsonify({"error": "Suara gagal dibuat. Periksa internet."}), 503
    return Response(mp3, mimetype="audio/mpeg")


@app.route("/transcribe", methods=["POST"])
def transcribe_audio():
    """Ubah rekaman suara dari browser menjadi teks. Isi permintaan: file audio (misalnya WebM)."""
    audio = request.get_data()
    if not audio:
        return jsonify({"error": "Rekaman kosong."}), 400
    try:
        text = transcribe(audio)
    except Exception as error:  # misalnya rekaman rusak atau formatnya tidak dikenali
        print(f"Suara gagal dikenali: {error}")
        return jsonify({"error": "Suara gagal dikenali."}), 500
    print(f"Terdengar: {text!r}")
    return jsonify({"text": text})


# ---------- Menjalankan ----------

def warm_up_stt():
    """Muat model Whisper di awal (bisa beberapa detik), supaya pengunjung pertama tidak menunggu lama."""
    print("Memuat model pengenal suara...")
    load_model()
    print("Model pengenal suara siap.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default="0", help="nomor webcam (0, 1, ...) atau path file video")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true",
                   help="tampilkan kotak, kerangka badan, dan conf di video (untuk pengujian)")
    args = p.parse_args()

    # daemon=True: kedua thread ikut berhenti saat program utama dihentikan (Ctrl+C).
    threading.Thread(target=warm_up_stt, daemon=True).start()
    threading.Thread(target=run_vision, args=(args.source, "debug" if args.debug else "kiosk"), daemon=True).start()
    print(f"Buka http://127.0.0.1:{args.port} di browser.")
    app.run(host="127.0.0.1", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
