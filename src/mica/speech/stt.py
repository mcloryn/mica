"""Ucapan ke teks (STT): mengubah ucapan pengunjung menjadi teks dengan faster-whisper.

Berjalan di laptop tanpa internet. Internet hanya dibutuhkan sekali, saat model diunduh
pertama kali (sekitar 500 MB untuk model "small").
"""

from functools import lru_cache
from io import BytesIO

from faster_whisper import WhisperModel

MODEL_SIZE = "small"  # pilihan lain: "base" (lebih cepat, kurang akurat) atau "medium" (lebih akurat, lebih lambat)


@lru_cache(maxsize=1)
def load_model():
    """Muat model Whisper sekali saja, lalu dipakai ulang untuk semua pengunjung."""
    # int8: angka model diperkecil supaya hemat memori dan cepat di CPU.
    return WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")


def transcribe(audio):
    """Kembalikan teks dari rekaman `audio` (bytes, format apa pun yang dikirim browser, misalnya WebM)."""
    segments, _ = load_model().transcribe(
        BytesIO(audio),
        language="id",     # pengunjung berbicara bahasa Indonesia, jadi bahasa tidak perlu ditebak
        beam_size=5,
        vad_filter=True,   # buang bagian hening supaya Whisper tidak "mengarang" kata dari keheningan
    )
    # segments adalah generator: pengenalan suara baru benar-benar berjalan saat dibaca di sini.
    return " ".join(s.text.strip() for s in segments).strip()
