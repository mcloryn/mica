"""Teks sapaan MICA. Untuk mencoba suaranya: scripts/try_tts.py."""


def make_greeting(color: str | None) -> str:
    """Kembalikan kalimat sapaan. `color` adalah nama warna baju, atau None jika belum diketahui."""
    if color is None:
        return "Halo, selamat datang di Mikroskil! Ada yang bisa MICA bantu?"
    return f"Halo, kakak yang berbaju {color}! Selamat datang di Mikroskil. Ada yang bisa MICA bantu?"
