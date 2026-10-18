"""Teks yang diucapkan atau ditampilkan M-09 (satu tempat supaya mudah ditinjau dan diuji E-06)."""

from __future__ import annotations

GREETING = "Halo, selamat datang di Universitas Mikroskil. Ada yang bisa saya bantu?"
GREETING_COLOR = (
    "Halo, selamat datang di Universitas Mikroskil. Kamu yang berbaju {warna}, "
    "ada yang bisa saya bantu?"
)
PLEASE_ASK = "Silakan bertanya"
FILLER = "Sebentar, saya carikan."
NOT_HEARD = "Maaf, belum terdengar jelas. Silakan ulangi atau ketik."
CAMERA_DOWN = "Kamera tidak tersedia; silakan bertanya lewat sentuhan atau ketik."
MIC_DOWN = "Mikrofon tidak tersedia; silakan ketik pertanyaan."


TALK_NOW = "Silakan bicara"

# M-10: pemberitahuan permanen (N-08) dan label UI
NOTICE_CAMERA = "Kamera aktif untuk mendeteksi pengunjung. Gambar tidak disimpan."
NOTICE_AI = "Pertanyaanmu diproses oleh layanan AI pihak ketiga."
STATUS_LABELS = {
    "IDLE": "Selamat datang",
    "GREETING": "Menyapa",
    "READY": "Siap",
    "LISTENING": "Mendengarkan",
    "THINKING": "Berpikir",
    "SPEAKING": "Berbicara",
}
CAMERA_ON, CAMERA_OFF = "Kamera: aktif", "Kamera: tidak tersedia"
MIC_ON, MIC_OFF = "Mikrofon: aktif", "Mikrofon: tidak tersedia"
HOME_TITLE = "Pilih topik atau ketik pertanyaanmu"
INPUT_PLACEHOLDER = "Ketik pertanyaan di sini"
SEND, TALK, STOP, RESEND = "Kirim", "Bicara", "Berhenti", "Kirim ulang"
TRANSCRIPT_LABEL = "Transkripsi (bisa diedit):"
SOURCES_LABEL = "Sumber:"
VISITOR, MICA = "Kamu", "MICA"
# UI web (Langkah 37): pil status, pemberitahuan ringkas, dan teks kolom kamera
PILLS = {  # status M-09 -> (kunci tampilan, label pil)
    "IDLE": ("ready", "Siap"),
    "READY": ("ready", "Siap"),
    "GREETING": ("speaking", "Berbicara"),
    "LISTENING": ("listening", "Mendengarkan"),
    "THINKING": ("thinking", "Berpikir"),
    "SPEAKING": ("speaking", "Berbicara"),
}
APP_TITLE = "Asisten PMB Universitas Mikroskil"
# Langkah 37c: pemberitahuan sebagai kalimat biasa di footer (N-08)
NOTICE_SHORT = (
    "Kamera aktif, gambar tidak disimpan. Jawaban disusun AI dari dokumen resmi PMB dan bisa "
    "keliru; pastikan ke staf PMB untuk hal penting."
)
NOTICE_SHORT_NO_CAMERA = (
    "Kamera tidak aktif, gambar tidak disimpan. Jawaban disusun AI dari dokumen resmi PMB dan "
    "bisa keliru; pastikan ke staf PMB untuk hal penting."
)
APPROACH = "Belum ada yang terdeteksi. Berdirilah di depan layar."
CAMERA_UNAVAILABLE = (
    "Kamera sedang tidak aktif, kamu tetap bisa bertanya dengan mengetik atau bicara"
)
WEARING = "Kamu memakai baju {warna}"  # warna sesi, huruf kecil biasa
DETECTED_NO_COLOR = "Kamu sudah terdeteksi di depan layar."
CAMERA_INFO = "MICA menyapa berdasarkan warna baju. Gambar kamera tidak disimpan."
WELCOME_TITLE = "Tanya apa saja seputar PMB"
TOPICS_HINT = "Pilih topik, lalu lengkapi pertanyaanmu"
CAMERA_TITLE = "Kamera"
MIC_UNAVAILABLE_BUTTON = "Mikrofon tidak tersedia, silakan ketik"
STATUS_LINES = {  # kunci pil -> kalimat status di atas bilah input
    "ready": "Silakan bicara atau ketik pertanyaan",
    "listening": "Mendengarkan...",
    "thinking": "Mencari di dokumen PMB...",
    "speaking": "Menjawab...",
}
STATUS_READY_NO_MIC = "Silakan ketik pertanyaan"
# UI web saat mulai (Langkah 40, N-10): UI tampil lebih dulu, kamera/suara/pipeline menyusul
CAMERA_STARTING = "Menyiapkan kamera..."
MIC_STARTING = "Menyiapkan mikrofon..."
STATUS_PREPARING_ANSWER = "Menyiapkan jawaban..."
MONTHS = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
          "September", "Oktober", "November", "Desember")  # fmt: skip


def greeting(color: str | None) -> str:
    return GREETING_COLOR.format(warna=color) if color else GREETING
