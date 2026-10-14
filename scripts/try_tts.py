"""Coba suara MICA: mengucapkan satu kalimat dengan TTS (edge-tts) lewat speaker laptop. Butuh internet.

Jalankan:
    python scripts/try_tts.py                          # mengucapkan sapaan contoh
    python scripts/try_tts.py "Selamat pagi, ada yang bisa dibantu?"
"""

import sys
import tempfile
import time
from pathlib import Path

import pygame

from mica.greeting import make_greeting
from mica.speech.tts import synthesize  # fungsi TTS yang sama dengan aplikasi web

MP3_FILE = Path(tempfile.gettempdir()) / "mica_tts.mp3"


def say(text):
    """Ubah teks menjadi suara, putar sampai selesai. Kembalikan (detik_membuat, detik_memutar)."""
    start = time.perf_counter()
    MP3_FILE.write_bytes(synthesize(text))  # minta audio MP3 ke layanan TTS
    created = time.perf_counter()

    pygame.mixer.music.load(str(MP3_FILE))
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():  # tunggu sampai suara selesai diputar
        time.sleep(0.05)
    pygame.mixer.music.unload()  # lepas file supaya bisa ditimpa di kalimat berikutnya
    return created - start, time.perf_counter() - created


def main():
    text = " ".join(sys.argv[1:]) or make_greeting("abu-abu")
    pygame.mixer.init()
    print(f"Mengucapkan: {text}")
    create_seconds, play_seconds = say(text)
    print(f"Waktu membuat suara: {create_seconds:.2f} detik, lama suara: {play_seconds:.2f} detik")


if __name__ == "__main__":
    main()
