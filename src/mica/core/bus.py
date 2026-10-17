"""M-13 Bus: pesan antarproses, proses pekerja, dan pengawasannya (SDD 3.2, 3.3, 5.2, 8.1; ADR-20).

Proses utama memegang Bus; pekerja berjalan di proses anak dengan konteks multiprocessing
"spawn" (eksplisit, sama di Windows dan di tes). Antrean:
- bus.to_main: pekerja -> utama (PersonArrived, PersonLeft, CameraStatus);
- bus.to_vision: utama -> vision (SetVisionRate, Shutdown).
Hanya pesan kecil yang lewat bus; frame dan audio tidak pernah (N-08).

Pengawasan (8.1): poll() memeriksa is_alive() setiap pekerja. Mati pertama -> dimulai ulang
sekali (log WORKER_RESTART). Mati lagi -> tidak dimulai ulang; poll() mengembalikan status
"tidak tersedia" pekerja itu (vision: CameraStatus(ok=False)) dan log WORKER_DEAD. Proses
utama tetap berjalan.

Proses suara (M-08) belum dibuat. Titik sambungnya: nama "audio" di WORKER_NAMES, antrean
to_audio, entry di _start_process, dan AudioStatus(mic_ok=False) di _dead_status.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import pickle
import queue
import time
from dataclasses import dataclass
from typing import Any

from mica.config import Settings
from mica.core.types import ErrorCode
from mica.vision.types import CameraStatus, PersonArrived, PersonLeft
from mica.vision.worker import VisionWorkerConfig, WorkerConfigError, run_vision_worker

log = logging.getLogger(__name__)

MP_CONTEXT = "spawn"
WORKER_NAMES = ("vision",)  # M-08: tambah "audio"
JOIN_TIMEOUT_S = 5.0  # non-ADR: batas tunggu pekerja berhenti sendiri sebelum terminate


@dataclass(frozen=True)
class SetVisionRate:
    fps: float


@dataclass(frozen=True)
class Shutdown:
    pass


# PersonArrived, PersonLeft, CameraStatus: tipe event vision/types.py (tidak diduplikasi)
Message = PersonArrived | PersonLeft | CameraStatus | SetVisionRate | Shutdown


class Bus:
    def __init__(self, settings: Settings, vision: VisionWorkerConfig) -> None:
        self.settings = settings
        self.vision_cfg = vision
        self.ctx = mp.get_context(MP_CONTEXT)
        self.to_main: Any = self.ctx.Queue()
        self.to_vision: Any = self.ctx.Queue()
        self.processes: dict[str, Any] = {}
        self.started_at: dict[str, float] = {}  # time.monotonic saat proses dimulai
        self.restarts: dict[str, int] = {name: 0 for name in WORKER_NAMES}
        self.dead: set[str] = set()
        self._stopping = False

    # --- proses -----------------------------------------------------------------------

    def _start_process(self, name: str) -> None:
        if name != "vision":  # M-08: entry proses suara
            raise ValueError(f"pekerja tidak dikenal: {name}")
        proc = self.ctx.Process(
            target=run_vision_worker,
            args=(self.vision_cfg, self.to_vision, self.to_main),
            name="mica-vision",
            daemon=True,  # ikut mati bila proses utama mati: tidak ada proses yatim
        )
        proc.start()
        self.processes[name] = proc
        self.started_at[name] = time.monotonic()

    def start(self) -> Bus:
        for name in WORKER_NAMES:
            self._start_process(name)
        return self

    def _dead_status(self, name: str) -> Message:
        # M-08: "audio" -> AudioStatus(mic_ok=False, speaker_ok=False)
        return CameraStatus(
            ok=False, message=f"{ErrorCode.WORKER_DEAD}: proses {name} mati", fps=None
        )

    def _supervise(self) -> list[Message]:
        out: list[Message] = []
        for name, proc in self.processes.items():
            if name in self.dead or proc.is_alive():
                continue
            exitcode = proc.exitcode
            if self.restarts[name] == 0:
                self.restarts[name] = 1
                log.warning(
                    "%s: proses %s mati (exitcode %s), dimulai ulang sekali",
                    ErrorCode.WORKER_RESTART,
                    name,
                    exitcode,
                )
                if name == "vision":
                    # antrean masuk diganti: proses yang dibunuh bisa meninggalkan kuncinya
                    self.to_vision = self.ctx.Queue()
                self._start_process(name)
            else:
                self.dead.add(name)
                log.error(
                    "%s: proses %s mati lagi (exitcode %s), tidak dimulai ulang",
                    ErrorCode.WORKER_DEAD,
                    name,
                    exitcode,
                )
                out.append(self._dead_status(name))
        return out

    # --- pesan ------------------------------------------------------------------------

    def send(self, target: str, msg: Message) -> None:
        if target != "vision":  # M-08: "audio" -> to_audio
            raise ValueError(f"tujuan bus tidak dikenal atau belum ada: {target}")
        if target in self.dead:
            log.debug("pesan ke %s dibuang: pekerja mati", target)
            return
        self.to_vision.put(msg)

    def poll(self, max_items: int = 100) -> list[Message]:
        """Non-blocking: status pengawasan lalu paling banyak max_items pesan dari to_main."""
        out = [] if self._stopping else self._supervise()
        while len(out) < max_items:
            try:
                out.append(self.to_main.get_nowait())
            except queue.Empty:
                break
            # pesan rusak dari pekerja yang dibunuh saat menulis
            except (EOFError, OSError, ValueError, pickle.UnpicklingError) as exc:
                log.warning("pesan bus rusak dibuang: %r", exc)
        return out

    def stop(self, timeout_s: float = JOIN_TIMEOUT_S) -> None:
        """Shutdown ke setiap pekerja, join dengan batas waktu, lalu terminate/kill bila perlu."""
        self._stopping = True
        for name, proc in self.processes.items():
            if proc.is_alive():
                try:
                    self.send(name, Shutdown())
                except ValueError:
                    pass
        deadline = time.monotonic() + timeout_s
        for proc in self.processes.values():
            proc.join(max(deadline - time.monotonic(), 0.0))
        for proc in self.processes.values():
            if proc.is_alive():
                proc.terminate()
                proc.join(1.0)
            if proc.is_alive():
                proc.kill()
                proc.join(1.0)
        for q in (self.to_main, self.to_vision):
            q.cancel_join_thread()  # jangan tertahan menunggu pesan yang tak akan dibaca
            q.close()


def start_workers(settings: Settings, vision: VisionWorkerConfig | None = None) -> Bus:
    """vision None -> dibuat dari config; nilai TBD (null) membuat worker ditolak sebelum spawn."""
    cfg = vision if vision is not None else VisionWorkerConfig.from_settings(settings)
    if cfg.mode != settings.app.mode:
        raise WorkerConfigError(
            f"VisionWorkerConfig.mode {cfg.mode} != app.mode {settings.app.mode}"
        )
    cfg.validate()
    cfg.check_files()
    return Bus(settings, cfg).start()
