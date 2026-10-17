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


def greeting(color: str | None) -> str:
    return GREETING_COLOR.format(warna=color) if color else GREETING
