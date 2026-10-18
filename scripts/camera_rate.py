"""Cek laju kamera dan pratinjau (Langkah 38; ui.preview_fps 10 = keputusan desain pengguna).

python scripts/camera_rate.py [--fake] [--seconds 30] [--out <folder>] [--config config/dev.yaml]

VisionLoop dijalankan di proses ini dengan antrean pratinjau maxsize 1 yang langsung dikuras:
- tanpa --fake: kamera asli (vision.camera_source 0, backend seperti worker) + detektor YOLO asli
  (vision.model) pada laju deteksi config (vision.fps_idle);
- --fake: sumber gambar dan detektor palsu (mica.vision.fakesource, 15 fps).
Nilai TBD vision.* diisi nilai coba dev (mica.ui.devfakes.FAKE_CAMERA_VALUES); pratinjau
dipaksa public. Dicatat: frame terbaca per detik, deteksi per detik, JPEG pratinjau per detik
(dan jarak antar-JPEG). Frame dan JPEG hanya di memori lalu dibuang (N-08), tidak ada gambar
ke disk. Hasil (angka saja) di <out>/camera_rate[-fake].json bila --out diberikan.
Kamera dianggap sanggup bila frame terbaca per detik >= ui.preview_fps.
"""

from __future__ import annotations

import argparse
import itertools
import json
import queue
import statistics
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WARMUP_S = 3.0  # detik awal (kamera membuka, eksposur) tidak dihitung


class _Counting:
    """Bungkus objek dengan satu metode yang waktunya dicatat (kamera.read / detect_and_track)."""

    def __init__(self, inner: Any, method: str, stamps: list[float], ok: Any = None) -> None:
        self._inner, self._method, self._stamps, self._ok = inner, method, stamps, ok

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if name != self._method:
            return attr

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            result = attr(*args, **kwargs)
            if self._ok is None or self._ok(result):
                self._stamps.append(time.monotonic())
            return result

        return wrapped


def rate(stamps: list[float], start: float) -> float:
    xs = [t for t in stamps if t >= start]
    return (len(xs) - 1) / (xs[-1] - xs[0]) if len(xs) > 1 else 0.0


def gaps_ms(stamps: list[float], start: float) -> dict[str, float | None]:
    xs = [t for t in stamps if t >= start]
    gaps = [1000 * (b - a) for a, b in itertools.pairwise(xs)]
    if len(gaps) < 2:
        return {"median": None, "p95": None, "max": None}
    return {"median": statistics.median(gaps), "p95": statistics.quantiles(gaps, n=20)[-1],
            "max": max(gaps)}  # fmt: skip


def measure(config: Path, fake: bool, seconds: float) -> dict[str, Any]:
    import numpy as np

    from mica.config import load_settings
    from mica.core.bus import Shutdown
    from mica.ui.devfakes import FAKE_CAMERA_VALUES
    from mica.vision.worker import VisionLoop, VisionWorkerConfig, _make_camera, _make_detector

    settings = load_settings(config)
    factories = {}
    if fake:
        factories = {"camera_factory": "mica.vision.fakesource:make_camera",
                     "detector_factory": "mica.vision.fakesource:make_detector"}  # fmt: skip
    cfg = VisionWorkerConfig.from_settings(settings, FAKE_CAMERA_VALUES, **factories)
    cfg = replace(cfg, camera_preview="public")
    cfg.validate()
    cfg.check_files()
    detector = _make_detector(cfg)
    detector.detect_and_track(np.zeros((480, 640, 3), dtype=np.uint8))  # pemanasan seperti worker
    reads: list[float] = []
    detects: list[float] = []
    previews: list[float] = []
    camera = _Counting(_make_camera(cfg), "read", reads, ok=lambda r: r[0] is not None)
    inbox: queue.Queue[Any] = queue.Queue()
    preview_out: queue.Queue[bytes] = queue.Queue(maxsize=1)
    loop = VisionLoop(cfg, inbox, queue.Queue(), camera,  # type: ignore[arg-type]
                      _Counting(detector, "detect_and_track", detects),  # type: ignore[arg-type]
                      preview_out=preview_out)  # fmt: skip
    stop = threading.Event()

    def drain() -> None:
        while not stop.is_set():
            try:
                preview_out.get(timeout=0.2)  # JPEG dibuang (N-08)
            except queue.Empty:
                continue
            previews.append(time.monotonic())

    drainer = threading.Thread(target=drain, daemon=True)
    drainer.start()
    first_frame = threading.Event()

    def stopper() -> None:
        while not reads and not stop.is_set():
            time.sleep(0.05)
        first_frame.set()
        time.sleep(WARMUP_S + seconds)
        inbox.put(Shutdown())

    threading.Thread(target=stopper, daemon=True).start()
    t_start = time.monotonic()
    loop.run()
    stop.set()
    drainer.join(timeout=2)
    if not reads:
        return {"fake": fake, "error": "tidak ada frame terbaca dari kamera",
                "preview_fps_config": cfg.preview_fps}  # fmt: skip
    start = reads[0] + WARMUP_S
    target = float(cfg.preview_fps or 0)
    camera_fps = rate(reads, start)
    return {
        "fake": fake, "camera_source": cfg.camera_source, "model": cfg.model,
        "detector": "palsu" if fake else "YOLO asli", "seconds": seconds,
        "warmup_s": WARMUP_S, "wall_s": time.monotonic() - t_start,
        "preview_fps_config": target, "fps_idle_config": cfg.fps_idle,
        "camera_read_fps": camera_fps, "detect_fps": rate(detects, start),
        "preview_jpeg_fps": rate(previews, start), "preview_gap_ms": gaps_ms(previews, start),
        "camera_capable": camera_fps >= target,
    }  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/camera_rate.py")
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--config", type=Path, default=ROOT / "config/dev.yaml")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = measure(args.config, args.fake, args.seconds)
    text = json.dumps(result, ensure_ascii=False, indent=1)
    print(text)
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        name = "camera_rate-fake.json" if args.fake else "camera_rate.json"
        (args.out / name).write_text(text + "\n", encoding="utf-8")
    if "error" in result:
        print(f"KAMERA TIDAK SANGGUP: {result['error']}")
        return 1
    verdict = "SANGGUP" if result["camera_capable"] else "TIDAK SANGGUP"
    print(f"{'sumber palsu' if args.fake else 'kamera asli'} {verdict}: "
          f"{result['camera_read_fps']:.2f} frame/s terbaca vs ui.preview_fps "
          f"{result['preview_fps_config']:g}; JPEG pratinjau {result['preview_jpeg_fps']:.2f}/s, "
          f"deteksi {result['detect_fps']:.2f}/s")  # fmt: skip
    return 0 if result["camera_capable"] else 1


if __name__ == "__main__":
    sys.exit(main())
