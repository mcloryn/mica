"""python -m mica setup: unduh semua model kiosk dengan revisi/sha256 terkunci (N-14).

Urutan: yolo26n-pose, yolo26n (vision, E-07 membandingkan keduanya), tabel warna, BGE-M3
(kb.embedder.revision), faster-whisper (audio.stt.model), suara Piper (audio.tts.voice).
Memakai pengunduh yang sudah ada (mica.vision/mica.audio fetch-*); file yang sudah ada dan
cocok dilewati, file yang ada tetapi sha256-nya salah tidak ditimpa otomatis (dilaporkan).
Berbeda dari fetch-* (dev saja), setup boleh dijalankan dengan config kiosk karena dipakai
saat pemasangan, sebelum kiosk berjalan; kiosk sendiri tidak pernah mengunduh.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mica.config import ConfigError, Settings, load_settings

DEFAULT_MODELS_DIR = Path("models")
DEFAULT_CONFIG = Path("config/kiosk.yaml")
# file yang dibutuhkan SentenceTransformer untuk BGE-M3 di snapshot revisi terkunci
EMBEDDER_FILES = (
    "modules.json", "config.json", "config_sentence_transformers.json",
    "sentence_bert_config.json", "1_Pooling/config.json", "model.safetensors",
    "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
    "sentencepiece.bpe.model",
)  # fmt: skip
VISION_MODELS = ("yolo26n-pose", "yolo26n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _yolo(path: Path) -> Path:
    from mica.vision.__main__ import _download_asset

    return _download_asset(path)


def _bytes(url: str) -> bytes:
    from mica.vision.__main__ import _download_bytes

    return _download_bytes(url)


def _file(url: str, dest: Path) -> None:
    from mica.audio.__main__ import _download

    _download(url, dest)


def _embedder(model: str, revision: str, cache_dir: Path) -> None:
    from mica.kb.embedder import BgeM3Embedder

    BgeM3Embedder(model, revision=revision, cache_dir=cache_dir).load()


@dataclass(frozen=True)
class Downloaders:
    """Pengunduh yang bisa diganti di tes (tanpa jaringan)."""

    yolo: Callable[[Path], Path] = _yolo
    url_bytes: Callable[[str], bytes] = _bytes
    url_file: Callable[[str, Path], None] = _file
    embedder: Callable[[str, str, Path], None] = _embedder


@dataclass(frozen=True)
class Component:
    name: str
    files: tuple[tuple[Path, str | None], ...]  # (path, sha256 terkunci; None = cukup ada)
    fetch: Callable[[], Any] | None = None
    blocked: str | None = None  # alasan komponen tidak bisa diunduh/diperiksa
    used: bool = True  # dipakai config ini (check hanya memeriksa yang dipakai)
    extra: dict[str, Any] = field(default_factory=dict)


def components(
    settings: Settings,
    models_dir: Path = DEFAULT_MODELS_DIR,
    dl: Downloaders | None = None,
) -> list[Component]:
    from mica.audio.__main__ import (
        VOICE,
        VOICE_SHA256,
        fetch_locked,
        voice_url,
        whisper_url,
    )
    from mica.audio.stt import WHISPER_MODEL, WHISPER_SHA256, whisper_dir
    from mica.vision.__main__ import fetch_colors, fetch_model
    from mica.vision.color import COLORS_NPY_SHA256, DEFAULT_COLORS_FILE
    from mica.vision.detector import MODEL_SHA256, model_path

    dl = dl or Downloaders()
    models_dir = Path(models_dir)
    out: list[Component] = []
    for name in VISION_MODELS:
        out.append(Component(
            name,
            ((model_path(name, models_dir), MODEL_SHA256[name]),),
            lambda n=name: fetch_model(n, models_dir, dl.yolo),
            used=settings.vision.model == name,
        ))  # fmt: skip
    out.append(Component(
        "tabel warna",
        ((models_dir / DEFAULT_COLORS_FILE.name, COLORS_NPY_SHA256),),
        lambda: fetch_colors(models_dir, dl.url_bytes),
        used=True,  # lut_vote dan lut_mean sama-sama memakai tabel
    ))  # fmt: skip

    emb = settings.kb.embedder
    if emb.revision is None:
        out.append(Component("BGE-M3", (), blocked="kb.embedder.revision null di config; "
                             "revisi terkunci wajib (N-14)"))  # fmt: skip
    else:
        snapshot = models_dir / f"models--{emb.model.replace('/', '--')}" / "snapshots"
        files = tuple((snapshot / emb.revision / f, None) for f in EMBEDDER_FILES)
        out.append(Component("BGE-M3", files,
                             lambda: dl.embedder(emb.model, emb.revision, models_dir)))  # fmt: skip

    stt = settings.audio.stt
    if stt.backend != "faster_whisper" or stt.model != WHISPER_MODEL:
        out.append(Component("faster-whisper", (), blocked=f"audio.stt {stt.backend}/{stt.model}"
                             " tidak punya revisi terkunci", used=False))  # fmt: skip
    else:
        root = whisper_dir(stt.model, models_dir / "whisper")
        out.append(Component(
            f"faster-whisper-{stt.model}",
            tuple((root / n, s) for n, s in WHISPER_SHA256.items()),
            lambda: fetch_locked(WHISPER_SHA256, whisper_url, root, dl.url_file),
        ))  # fmt: skip

    voice = settings.audio.tts.voice
    if voice != VOICE:
        out.append(Component("suara Piper", (), blocked=f"audio.tts.voice {voice} tidak punya "
                             "revisi terkunci"))  # fmt: skip
    else:
        piper = models_dir / "piper"
        out.append(Component(
            f"suara {VOICE}",
            tuple((piper / n, s) for n, s in VOICE_SHA256.items()),
            lambda: fetch_locked(VOICE_SHA256, voice_url, piper, dl.url_file),
        ))  # fmt: skip
    return out


def verify(component: Component) -> tuple[bool, str]:
    """Tanpa jaringan: semua file ada dan sha256 cocok."""
    if component.blocked:
        return False, component.blocked
    for path, expected in component.files:
        if not path.is_file():
            return False, f"file hilang: {path.as_posix()}"
        if expected is not None and sha256_file(path) != expected:
            return False, f"sha256 tidak cocok: {path.as_posix()} (hapus file lalu setup lagi)"
    return True, "ada, sha256/revisi cocok"


def size_mb(component: Component) -> float:
    return sum(p.stat().st_size for p, _ in component.files if p.is_file()) / 2**20


def run_setup(
    settings: Settings,
    only: str | None = None,
    models_dir: Path = DEFAULT_MODELS_DIR,
    dl: Downloaders | None = None,
    out: Callable[[str], None] = print,
) -> int:
    comps = components(settings, models_dir, dl)
    if only is not None:
        comps = [c for c in comps if c.name == only]
        if not comps:
            names = ", ".join(c.name for c in components(settings, models_dir, dl))
            out(f"komponen tidak dikenal: {only}; pilihan: {names}")
            return 2
    rows: list[tuple[str, str, float]] = []
    for c in comps:
        ok, message = verify(c)
        if ok:
            status = "sudah ada"
        elif c.blocked or c.fetch is None:
            status = f"gagal: {message}"
        else:
            out(f"--- {c.name}: mengunduh ---")
            try:
                c.fetch()
                ok, message = verify(c)
                status = "diunduh" if ok else f"gagal: {message}"
            except Exception as exc:  # noqa: BLE001 - satu komponen gagal, lanjut ke berikutnya
                status = f"gagal: {exc}"
        rows.append((c.name, status, size_mb(c)))
    width = max(len(name) for name, _, _ in rows)
    out("")
    out(f"{'komponen'.ljust(width)}  {'ukuran':>9}  status")
    for name, status, mb in rows:
        out(f"{name.ljust(width)}  {mb:7.1f} MB  {status}")
    return 1 if any(s.startswith("gagal") for _, s, _ in rows) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mica setup")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--only", help="satu komponen saja, mis. yolo26n-pose atau BGE-M3")
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    args = parser.parse_args(argv)
    try:
        # setup tidak butuh nilai TBD (ambang); hanya pilihan model dan revisinya
        settings = load_settings(args.config, require_complete=False)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return run_setup(settings, args.only, args.models_dir)
