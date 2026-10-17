"""Uji asap eval stt TANPA mikrofon: dataset sintetis sementara, lalu python -m mica.eval stt.

python scripts/e05_smoke_synthetic.py [--config config/dev.yaml] [--out results/E-05]

Dataset dibuat di folder temp di luar repo dan dihapus setelah run:
- 5 pertanyaan dev answerable pertama (urutan qid) disintesis Piper, di-resample ke 16 kHz,
  diberi diam di depan;
- 3 "diam": nol digital ditambah derau putih sangat kecil;
- 2 "bising": derau putih.
Parameter sinyal di bawah hanya untuk membuat data sintetis, bukan ambang MICA. Nilai coba
VAD dan penyaring sama dengan pilot (0.5/500/15, min_speech 250, no_speech 0.6). run.json
ditandai "sintetis, bukan hasil E-05"; synthetic.json mencatat cara pembuatannya.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
LEAD_S = 0.5  # diam sebelum ucapan sintetis (data sintetis, bukan ambang)
NOISE_S = 3.0  # panjang rekaman diam/bising sintetis
QUIET_STD = 1.0  # derau "sangat kecil": simpangan baku 1 LSB int16
NOISE_STD = 3277.0  # derau putih sekitar -20 dBFS RMS (0,1 x 32767)
SEED = 0
N_QUESTIONS, N_SILENT, N_NOISY = 5, 3, 2
TRIAL = ["--vad-threshold", "0.5", "--min-silence-ms", "500", "--max-utterance-s", "15",
         "--min-speech-ms", "250", "--no-speech-threshold", "0.6"]  # fmt: skip
NOTE = "sintetis, bukan hasil E-05"


def write_wav(path: Path, pcm: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(np.asarray(pcm, dtype=np.int16).tobytes())


def noise(std: float, seconds: float, rng: np.random.Generator) -> np.ndarray:
    x = rng.normal(0.0, std, int(seconds * SAMPLE_RATE))
    return np.clip(np.round(x), -32768, 32767).astype(np.int16)


def build_dataset(folder: Path, config: Path) -> dict:
    from mica.audio.listen import DEFAULT_DATASET, load_script_questions
    from mica.audio.mic import resample_int16
    from mica.audio.tts import PiperTts, voice_path
    from mica.config import load_settings

    settings = load_settings(config)
    tts = PiperTts(voice_path(settings.audio.tts.voice), settings.audio.tts.length_scale)
    rng = np.random.default_rng(SEED)
    rows = []
    for q in load_script_questions(DEFAULT_DATASET, N_QUESTIONS):
        clip = tts.synthesize(q["question"])
        speech = resample_int16(clip.samples, clip.sample_rate, SAMPLE_RATE)
        pcm = np.concatenate([np.zeros(int(LEAD_S * SAMPLE_RATE), dtype=np.int16), speech])
        write_wav(folder / f"{q['qid']}.wav", pcm)
        rows.append({"id": f"sint-{q['qid']}", "file": f"{q['qid']}.wav", "jenis": "pertanyaan",
                     "referensi": q["question"], "qid": q["qid"], "penutur": "SINTETIS-PIPER",
                     "persetujuan": True})  # fmt: skip
    for i in range(1, N_SILENT + 1):
        write_wav(folder / f"diam{i}.wav", noise(QUIET_STD, NOISE_S, rng))
        rows.append({"id": f"sint-diam{i}", "file": f"diam{i}.wav", "jenis": "diam",
                     "penutur": "SINTETIS", "persetujuan": True})  # fmt: skip
    for i in range(1, N_NOISY + 1):
        write_wav(folder / f"bising{i}.wav", noise(NOISE_STD, NOISE_S, rng))
        rows.append({"id": f"sint-bising{i}", "file": f"bising{i}.wav", "jenis": "bising",
                     "penutur": "SINTETIS", "persetujuan": True})  # fmt: skip
    (folder / "manifest.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    return {
        "note": NOTE,
        "voice": settings.audio.tts.voice,
        "questions": [r["qid"] for r in rows if r.get("qid")],
        "resample": "mica.audio.mic.resample_int16 dari laju suara Piper ke 16000 Hz",
        "lead_silence_s": LEAD_S,
        "silent": {"n": N_SILENT, "seconds": NOISE_S, "white_noise_std_lsb": QUIET_STD},
        "noisy": {"n": N_NOISY, "seconds": NOISE_S, "white_noise_std_lsb": NOISE_STD},
        "seed": SEED,
    }


def main(argv: list[str] | None = None) -> int:
    from mica.eval.__main__ import main as eval_main

    parser = argparse.ArgumentParser(prog="python scripts/e05_smoke_synthetic.py")
    parser.add_argument("--config", type=Path, default=Path("config/dev.yaml"))
    parser.add_argument("--out", type=Path, default=Path("results/E-05"))
    args = parser.parse_args(argv)
    run_name = "smoke-synthetic-" + datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    tmp = Path(tempfile.mkdtemp(prefix="mica-e05-"))  # di luar repo
    try:
        synthetic = build_dataset(tmp, args.config)
        code = eval_main(["stt", "--config", str(args.config), "--dataset",
                          str(tmp / "manifest.jsonl"), "--out", str(args.out), "--run-name",
                          run_name, "--note", NOTE, *TRIAL])  # fmt: skip
        if code == 0:
            (args.out / run_name / "synthetic.json").write_text(
                json.dumps(synthetic, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
        return code
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"folder sementara dihapus: {not tmp.exists()}")


if __name__ == "__main__":
    raise SystemExit(main())
