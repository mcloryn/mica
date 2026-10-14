"""Cek apakah laptop sudah siap untuk mengerjakan MICA.

Jalankan dari folder utama project:
    python scripts/check_setup.py
"""

import importlib.util
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Nama modul yang diimpor -> nama paket di requirements.txt.
BASE_PACKAGES = {
    "dotenv": "python-dotenv",
    "fitz": "pymupdf",
    "bs4": "beautifulsoup4",
    "requests": "requests",
}

all_ok = True


def check(name, ok, hint=""):
    """Cetak [OK] atau [BELUM] untuk satu pengecekan, beserta saran jika belum."""
    global all_ok
    print(f"[{'OK' if ok else 'BELUM'}] {name}")
    if not ok:
        all_ok = False
        if hint:
            print(f"        -> {hint}")


check(
    f"Python {sys.version_info.major}.{sys.version_info.minor} (minimal 3.11)",
    sys.version_info >= (3, 11),
    "Install Python 3.11 dari https://www.python.org/downloads/",
)
check("Git terpasang", shutil.which("git") is not None,
      "Install Git dari https://git-scm.com/downloads")
check("Sedang di dalam virtual environment", sys.prefix != sys.base_prefix,
      "Jalankan: python -m venv .venv, lalu aktifkan (lihat README)")

for module, package in BASE_PACKAGES.items():
    check(f"Paket {package}", importlib.util.find_spec(module) is not None,
          "Jalankan: pip install -r requirements.txt")

check("Paket mica terpasang", importlib.util.find_spec("mica") is not None,
      "Jalankan: pip install -e .")
check("File .env sudah dibuat", (ROOT / ".env").exists(),
      "Salin .env.example menjadi .env")

print()
print("Semua siap. Lingkungan kerja dapat digunakan." if all_ok
      else "Masih ada yang BELUM. Ikuti saran di atas, lalu jalankan lagi.")
