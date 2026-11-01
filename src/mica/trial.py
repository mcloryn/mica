"""Nilai coba SDD bagian 12 untuk mencoba kamera dan mikrofon asli di dev (Langkah 41).

--trial-values (python -m mica, python -m mica.webui): kunci config yang null diisi TRIAL_VALUES
di memori; file config tidak diubah. Hanya boleh saat app.mode: dev; config prod ditolak
(config prod baru diisi dari hasil eksperimen, SDD bagian 12). Saat aktif, daftar kunci dan
nilainya dicatat sebagai peringatan dan UI web menampilkan label "NILAI COBA (dev)".
Dipakai juga oleh scripts/startup_profile.py dan sumber gambar palsu (mica.ui.devfakes).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mica.config import CFG_INVALID, ConfigError, Settings, read_raw, settings_from_raw

log = logging.getLogger(__name__)

# NILAI COBA SDD bagian 12 ("Nilai coba hanya untuk dev dan demo"); bukan hasil eksperimen
TRIAL_VALUES: dict[str, float] = {
    "vision.dwell_s": 2.0,  # E-07: nilai coba 2 dan 3 detik
    "vision.leave_s": 3.0,
    "vision.min_shoulder_ratio": 0.22,  # E-07: rasio bahu 0,22 (kalibrasi dev)
    "vision.color.min_majority": 0.6,  # E-08
    "vision.box_upper.top": 0.35,  # E-08: kotak 0,35/0,65/0,25
    "vision.box_upper.bottom": 0.65,
    "vision.box_upper.side": 0.25,
    "vision.keypoint_torso.min_kp_conf": 0.5,  # E-08: keypoint 0,5/0,15/1,2
    "vision.keypoint_torso.shrink": 0.15,
    "vision.keypoint_torso.torso_aspect": 1.2,
    "audio.vad.threshold": 0.5,  # E-05: bawaan Silero
    "audio.vad.min_silence_ms": 500,  # E-05: anggaran akhir ucapan 0,5 detik
    "audio.vad.min_speech_ms": 250,  # E-05: bawaan min_speech_duration_ms Silero
    "audio.stt.no_speech_threshold": 0.6,  # E-05: bawaan Whisper
    "audio.max_utterance_s": 15,  # E-05: tanpa sumber, ditetapkan di E-05
}


def fill_nulls(raw: dict[str, Any], values: dict[str, Any] = TRIAL_VALUES) -> dict[str, Any]:
    """Isi kunci (bertitik) yang null atau tidak ada di raw; kunci yang sudah berisi dibiarkan.
    Kembalikan kunci yang diisi beserta nilainya."""
    filled: dict[str, Any] = {}
    for dotted, value in values.items():
        node = raw
        *parents, last = dotted.split(".")
        for key in parents:
            node = node.setdefault(key, {})
        if node.get(last) is None:
            node[last] = value
            filled[dotted] = value
    return filled


def load_trial_settings(
    path: Path, env_file: Path | None = None
) -> tuple[Settings, dict[str, Any]]:
    """Settings dengan nilai coba di memori (dev saja) dan daftar kunci yang diisi."""
    raw = read_raw(path)
    mode = (raw.get("app") or {}).get("mode")
    if mode != "dev":
        raise ConfigError(
            CFG_INVALID,
            f"--trial-values hanya boleh saat app.mode: dev ({path} memakai mode {mode}); "
            "config prod diisi dari hasil eksperimen, bukan nilai coba",
        )
    filled = fill_nulls(raw)
    settings = settings_from_raw(raw, env_file)
    if filled:
        listing = ", ".join(f"{k}={v}" for k, v in filled.items())
        log.warning("PERINGATAN NILAI COBA (dev, SDD bagian 12, bukan hasil eksperimen): %s",
                    listing)  # fmt: skip
    return settings, filled
