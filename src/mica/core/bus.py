"""M-13 Bus: pesan antarproses, proses pekerja, dan pengawasannya (SDD 3.2, 3.3, 5.2, 8.1; ADR-20).

Proses utama memegang Bus; pekerja berjalan di proses anak dengan konteks multiprocessing
"spawn" (eksplisit, sama di Windows dan di tes). Antrean:
- bus.to_main: pekerja -> utama (PersonArrived, PersonLeft, CameraStatus; SpeechStarted,
  Transcript, SpeechDone, AudioStatus);
- bus.to_vision: utama -> vision (SetVisionRate, Shutdown);
- bus.to_audio: utama -> suara (ListenControl, Speak, StopSpeaking, Shutdown).
Hanya pesan kecil yang lewat bus; frame dan audio tidak pernah (N-08).

Pengawasan (8.1): poll() memeriksa is_alive() setiap pekerja. Mati pertama -> dimulai ulang
sekali (log WORKER_RESTART). Mati lagi -> tidak dimulai ulang; poll() mengembalikan status
"tidak tersedia" pekerja itu (vision: CameraStatus(ok=False); suara: AudioStatus(mic_ok=False,
speaker_ok=False, ready=False)) dan log WORKER_DEAD. Proses utama tetap berjalan.

Setelah restart, antrean masuk pekerja diganti baru dan pekerja mulai dari keadaan awal: vision
kembali ke fps_idle, suara kembali ke mode off (Speak yang belum selesai hilang tanpa
SpeechDone). M-09 wajib mengirim ulang SetVisionRate saat CameraStatus ok berikutnya dan
ListenControl saat AudioStatus(ready=True) berikutnya. Supaya restart terlihat walau proses
dibunuh paksa, poll() mengembalikan status tidak tersedia dengan WORKER_RESTART tepat sebelum
proses baru dimulai (vision: CameraStatus(ok=False); suara: AudioStatus(ready=False)).
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import pickle
import queue
import time
from dataclasses import dataclass, replace
from typing import Any

from mica.audio.messages import (
    AudioStatus,
    ListenControl,
    Speak,
    SpeechDone,
    SpeechStarted,
    StopSpeaking,
    Transcript,
)
from mica.audio.worker import AudioWorkerConfig, AudioWorkerConfigError, run_audio_worker
from mica.config import Settings
from mica.core.types import ErrorCode
from mica.vision.types import CameraStatus, PersonArrived, PersonLeft
from mica.vision.worker import VisionWorkerConfig, WorkerConfigError, run_vision_worker

log = logging.getLogger(__name__)

MP_CONTEXT = "spawn"
WORKER_NAMES = ("vision", "audio")
JOIN_TIMEOUT_S = 5.0  # non-ADR: batas tunggu pekerja berhenti sendiri sebelum terminate


@dataclass(frozen=True)
class SetVisionRate:
    fps: float


@dataclass(frozen=True)
class Shutdown:
    pass


# PersonArrived, PersonLeft, CameraStatus: tipe event vision/types.py; pesan suara di
# audio/messages.py (tidak diduplikasi)
Message = (
    PersonArrived
    | PersonLeft
    | CameraStatus
    | SetVisionRate
    | Shutdown
    | SpeechStarted
    | Transcript
    | Speak
    | StopSpeaking
    | SpeechDone
    | ListenControl
    | AudioStatus
)


def rss_mb(pid: int | None = None) -> float | None:
    """RSS proses dalam MB bila psutil tersedia (terpasang bersama Ultralytics); selain itu None."""
    try:
        import psutil

        return psutil.Process(pid).memory_info().rss / 2**20
    except Exception:  # noqa: BLE001 - pengukuran opsional, tidak boleh menggagalkan demo
        return None


class Bus:
    def __init__(
        self,
        settings: Settings,
        vision: VisionWorkerConfig | None = None,
        audio: AudioWorkerConfig | None = None,
    ) -> None:
        """Hanya pekerja yang config-nya diberikan yang dimulai."""
        if vision is None and audio is None:
            raise ValueError("Bus butuh minimal satu pekerja (vision atau audio)")
        self.settings = settings
        self.vision_cfg = vision
        self.audio_cfg = audio
        self.names = tuple(n for n, c in (("vision", vision), ("audio", audio)) if c is not None)
        self.ctx = mp.get_context(MP_CONTEXT)
        self.to_main: Any = self.ctx.Queue()
        self.to_vision: Any = self.ctx.Queue()
        self.to_audio: Any = self.ctx.Queue()
        self.processes: dict[str, Any] = {}
        self.started_at: dict[str, float] = {}  # time.monotonic saat proses dimulai
        self.restarts: dict[str, int] = {name: 0 for name in self.names}
        self.dead: set[str] = set()
        self._stopping = False

    # --- proses -----------------------------------------------------------------------

    def _start_process(self, name: str) -> None:
        if name == "vision":
            target: Any = run_vision_worker
            args: tuple[Any, ...] = (self.vision_cfg, self.to_vision, self.to_main)
        elif name == "audio":
            target, args = run_audio_worker, (self.audio_cfg, self.to_audio, self.to_main)
        else:
            raise ValueError(f"pekerja tidak dikenal: {name}")
        proc = self.ctx.Process(
            target=target,
            args=args,
            name=f"mica-{name}",
            daemon=True,  # ikut mati bila proses utama mati: tidak ada proses yatim
        )
        proc.start()
        self.processes[name] = proc
        self.started_at[name] = time.monotonic()

    def start(self) -> Bus:
        for name in self.names:
            self._start_process(name)
        return self

    def _dead_status(self, name: str) -> Message:
        return self._down_status(name, f"{ErrorCode.WORKER_DEAD}: proses {name} mati")

    def _down_status(self, name: str, message: str) -> Message:
        if name == "audio":
            return AudioStatus(mic_ok=False, speaker_ok=False, ready=False, message=message)
        return CameraStatus(ok=False, message=message, fps=None)

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
                # antrean masuk diganti: proses yang dibunuh bisa meninggalkan kuncinya
                if name == "vision":
                    assert self.vision_cfg is not None
                    self.to_vision = self.ctx.Queue()
                    # hitung mundur pratinjau (dev) hanya sekali, bukan lagi setelah restart
                    self.vision_cfg = replace(self.vision_cfg, countdown_s=0.0)
                else:
                    self.to_audio = self.ctx.Queue()  # mode kembali off
                # proses yang dibunuh paksa tidak sempat melapor; status ini membuat M-09
                # mengenali restart saat status ok/ready berikutnya datang
                out.append(self._down_status(name, f"{ErrorCode.WORKER_RESTART}: proses {name} "
                                                   "dimulai ulang"))  # fmt: skip
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
        if target not in self.names:
            raise ValueError(f"tujuan bus tidak dikenal atau tidak dimulai: {target}")
        if target in self.dead:
            log.debug("pesan ke %s dibuang: pekerja mati", target)
            return
        (self.to_vision if target == "vision" else self.to_audio).put(msg)

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
        for q in (self.to_main, self.to_vision, self.to_audio):
            q.cancel_join_thread()  # jangan tertahan menunggu pesan yang tak akan dibaca
            q.close()


def start_workers(
    settings: Settings,
    vision: VisionWorkerConfig | None = None,
    audio: AudioWorkerConfig | None = None,
    workers: tuple[str, ...] | None = None,
) -> Bus:
    """Mulai vision saja, audio saja, atau keduanya.

    workers None -> pekerja yang config-nya diberikan, atau keduanya bila tidak ada config yang
    diberikan. Pekerja terpilih tanpa config dibuat dari settings; nilai TBD (null) membuat
    worker ditolak sebelum spawn.
    """
    if workers is None:
        given = tuple(n for n, c in (("vision", vision), ("audio", audio)) if c is not None)
        workers = given or WORKER_NAMES
    unknown = set(workers) - set(WORKER_NAMES)
    if unknown:
        raise ValueError(f"pekerja tidak dikenal: {sorted(unknown)}")
    vision_cfg = audio_cfg = None
    if "vision" in workers:
        vision_cfg = vision if vision is not None else VisionWorkerConfig.from_settings(settings)
        if vision_cfg.mode != settings.app.mode:
            raise WorkerConfigError(
                f"VisionWorkerConfig.mode {vision_cfg.mode} != app.mode {settings.app.mode}"
            )
        vision_cfg.validate()
        vision_cfg.check_files()
    if "audio" in workers:
        audio_cfg = audio if audio is not None else AudioWorkerConfig.from_settings(settings)
        if audio_cfg.mode != settings.app.mode:
            raise AudioWorkerConfigError(
                f"AudioWorkerConfig.mode {audio_cfg.mode} != app.mode {settings.app.mode}"
            )
        audio_cfg.validate()
        audio_cfg.check_files()
    return Bus(settings, vision_cfg, audio_cfg).start()
