"""Pencatatan waktu tahap start-up (Langkah 40): proses utama, pekerja kamera, pekerja suara.

- mark(stage) mencatat time.monotonic(), jam yang sama untuk semua proses di satu mesin (seperti
  timings E-09, docs/E-09.md), ke logs/startup-<tanggal>.jsonl (logging.dir), satu baris JSON:
  ts, run, pid, proc, stage, t. Hanya nama tahap dan waktu; tidak ada gambar, audio, atau teks
  pengunjung (N-08, N-09).
- Proses utama memanggil begin() di awal (tahap dibuffer di memori) lalu init(log_dir) setelah
  config dimuat; init() menulis buffer dan memasang variabel lingkungan MICA_STARTUP_LOG dan
  MICA_STARTUP_RUN sehingga proses anak (spawn) menulis ke file yang sama.
- Tanpa begin()/init() (tes, alat dev) mark() hanya menulis ke logger "mica.startup" (debug).
- StartupBus: pembungkus pasif Bus. poll() meneruskan semua pesan apa adanya dan mencatat
  CameraStatus(ok=True) / AudioStatus(ready=True) pertama, lalu "all_ready" bila UI sudah
  digambar, pipeline siap, dan pekerja yang ada sudah siap. Tidak mengubah pesan (M-09 tetap).
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("mica.startup")

ENV_FILE = "MICA_STARTUP_LOG"
ENV_RUN = "MICA_STARTUP_RUN"
_lock = threading.Lock()
_buffer: list[dict[str, Any]] | None = None
_proc = "main"
DEFAULT_PATH_OVERRIDE: Path | None = None  # tes: pengganti logs/startup-<tanggal>.jsonl


def active() -> bool:
    """True bila tahap sedang dicatat (begin() atau file dari init()/proses induk)."""
    return _buffer is not None or ENV_FILE in os.environ


def set_process(name: str) -> None:
    """Nama proses untuk baris berikutnya (dipanggil di awal proses anak)."""
    global _proc
    _proc = name


def begin() -> None:
    """Proses utama: mulai membuffer tahap sebelum folder log diketahui."""
    global _buffer
    with _lock:
        if _buffer is None and ENV_FILE not in os.environ:
            _buffer = []


def init(log_dir: Path) -> Path:
    """Proses utama: tentukan file log tahap dan tulis buffer. Run yang sudah dimulai (env ada,
    mis. dari alat profil) tidak diganti."""
    global _buffer
    day = datetime.now().astimezone().date().isoformat()
    default = DEFAULT_PATH_OVERRIDE or Path(log_dir) / f"startup-{day}.jsonl"
    path = Path(os.environ.get(ENV_FILE) or default)
    os.environ[ENV_FILE] = str(path)
    os.environ.setdefault(ENV_RUN, uuid.uuid4().hex[:12])
    with _lock:
        pending, _buffer = _buffer or [], None
    path.parent.mkdir(parents=True, exist_ok=True)
    for row in pending:
        _write(path, {**row, "run": os.environ[ENV_RUN]})
    return path


def _write(path: Path, row: dict[str, Any]) -> None:
    with _lock, path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def mark(stage: str, proc: str | None = None) -> float:
    """Catat tahap pada time.monotonic(); kembalikan waktunya."""
    t = time.monotonic()
    row = {"ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
           "run": os.environ.get(ENV_RUN), "pid": os.getpid(), "proc": proc or _proc,
           "stage": stage, "t": t}  # fmt: skip
    log.debug("startup %s %s %.3f", row["proc"], stage, t)
    path = os.environ.get(ENV_FILE)
    if path:
        _write(Path(path), row)
    else:
        with _lock:
            if _buffer is not None:
                _buffer.append(row)
    return t


def timed_import(module: str) -> Any:
    """import module dengan tahap import_<module>_start/_done (modul yang memang akan dimuat)."""
    key = module.replace(".", "_")
    mark(f"import_{key}_start")
    mod = importlib.import_module(module)
    mark(f"import_{key}_done")
    return mod


class StartupBus:
    """Pembungkus pasif Bus/FakeWorkerBus untuk tahap camera_ready, audio_ready, all_ready."""

    def __init__(self, bus: Any) -> None:
        self._bus = bus
        names = set(getattr(bus, "names", ()))
        self.waiting = {n for n in ("vision", "audio") if n in names}
        if getattr(bus, "vision", "absent") is None:  # FakeWorkerBus tanpa kamera palsu
            self.waiting.discard("vision")
        self.ui_rendered = False
        self.pipeline_ready = False
        self.all_ready_at: float | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._bus, name)

    def poll(self, *args: Any, **kwargs: Any) -> list[Any]:
        from mica.audio.messages import AudioStatus
        from mica.vision.types import CameraStatus

        out = self._bus.poll(*args, **kwargs)
        for msg in out:
            if "vision" in self.waiting and isinstance(msg, CameraStatus) and msg.ok:
                self.waiting.discard("vision")
                mark("camera_ready")
            elif "audio" in self.waiting and isinstance(msg, AudioStatus) and msg.ready:
                self.waiting.discard("audio")
                mark("audio_ready")
        self._check()
        return out

    def note_ui_rendered(self) -> None:
        if not self.ui_rendered:
            self.ui_rendered = True
            self._check()

    def note_pipeline_ready(self) -> None:
        if not self.pipeline_ready:
            self.pipeline_ready = True
            self._check()

    def _check(self) -> None:
        if (self.all_ready_at is None and self.ui_rendered and self.pipeline_ready
                and not self.waiting):  # fmt: skip
            self.all_ready_at = mark("all_ready")
