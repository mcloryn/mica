"""Membaca pengaturan yang bisa dikalibrasi dari config/mica.yaml."""

from pathlib import Path

import yaml

# Folder utama project. File ini ada di src/mica/config.py, jadi naik dua tingkat.
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
SETTINGS_FILE = CONFIG_DIR / "mica.yaml"
TRACKER_FILE = CONFIG_DIR / "bytetrack_mica.yaml"

with open(SETTINGS_FILE, encoding="utf-8") as f:
    SETTINGS = yaml.safe_load(f)
