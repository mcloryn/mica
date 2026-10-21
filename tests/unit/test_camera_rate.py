"""scripts/camera_rate.py (Langkah 38): laju frame, deteksi, dan JPEG pratinjau dari sumber palsu."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("camera_rate", ROOT / "scripts/camera_rate.py")
camera_rate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(camera_rate)


def test_rate_and_gaps():
    stamps = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    assert abs(camera_rate.rate(stamps, 0.0) - 10.0) < 1e-9
    assert camera_rate.rate(stamps, 0.45) == 0.0  # satu titik: tidak ada laju
    gaps = camera_rate.gaps_ms(stamps, 0.0)
    assert abs(gaps["median"] - 100.0) < 1e-6 and abs(gaps["max"] - 100.0) < 1e-6


def test_fake_source_reaches_preview_fps_without_files(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_rate, "WARMUP_S", 0.5)
    # sumber palsu tepat 15 fps; dev.yaml kini 15 (batas persis), jadi target diturunkan ke 10
    # di salinan config agar tes tidak bergantung pada pembulatan laju terukur
    dev = ROOT / "config" / "dev.yaml"
    lines = [
        "  preview_fps: 10" if ln.strip().startswith("preview_fps:") else ln
        for ln in dev.read_text(encoding="utf-8").splitlines()
    ]
    cfg = tmp_path / "dev.yaml"
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / "out"
    args = ["--fake", "--seconds", "1.5", "--out", str(out), "--config", str(cfg)]
    assert camera_rate.main(args) == 0
    # hanya angka yang ditulis; tidak ada gambar ke disk (N-08)
    assert [p.name for p in out.iterdir()] == ["camera_rate-fake.json"]
    result = json.loads((out / "camera_rate-fake.json").read_text(encoding="utf-8"))
    assert result["preview_fps_config"] == 10  # dari salinan config
    assert result["camera_read_fps"] >= 10 and result["camera_capable"]
    assert result["preview_jpeg_fps"] > 8  # sumber 15 fps, target 10 fps, 1,5 s
