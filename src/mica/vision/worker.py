"""M-07 vision worker: loop kamera di proses anak bus M-13 (SDD 3.2, 3.3, 5.2; ADR-20).

run_vision_worker(cfg, inbox, outbox) berjalan di proses anak (multiprocessing spawn):
kamera -> detektor + tracker -> PresenceTracker (+ area pakaian, ColorNamer, voting) -> event
ke outbox (bus.to_main). Pesan dari inbox (bus.to_vision): SetVisionRate dan Shutdown.

- Frame hanya ada di memori proses ini, tidak pernah dikirim lewat bus atau ditulis ke disk (N-08).
- Laju deteksi awal vision.fps_idle; SetVisionRate(fps) dari M-09 mengubahnya (SDD 3.3). Seperti
  demo, setiap frame kamera dibaca supaya buffer kamera tidak basi, tetapi detektor hanya
  berjalan sesuai laju.
- CameraStatus dikirim saat status kamera berubah dan setiap status_interval_s (SDD 5.2: 10 s),
  dengan fps deteksi terukur.
- Ultralytics/torch hanya diimpor di sini (lewat UltralyticsDetector), jadi hanya di proses anak.
- Model dimuat dan dipanaskan sebelum kamera dibuka, sehingga CameraStatus ok pertama berarti
  worker siap mendeteksi.

VisionWorkerConfig dibuat di proses utama (from_settings) dan harus bisa di-pickle. Nilai TBD
(null) di config ditolak dengan pesan yang menyebut kuncinya; perintah dev boleh memberi nilai
coba lewat overrides. Factory kamera/detektor palsu ("modul:fungsi") hanya untuk dev dan tes.
"""

from __future__ import annotations

import importlib
import queue
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from mica.config import Settings, VisionConfig
from mica.vision.camera import Camera
from mica.vision.color import (
    DEFAULT_COLORS_FILE,
    ColorNamer,
    ColorNamesLut,
    ColorResult,
    ColorsMissing,
    ColorVoting,
    HsvRuleNamer,
)
from mica.vision.detector import DEFAULT_MODELS_DIR, ModelMissing, PersonDetector, model_path
from mica.vision.presence import (
    BoxHeightSignal,
    PresenceSignal,
    PresenceTracker,
    ShoulderWidthSignal,
)
from mica.vision.region import BoxUpperRegion, ClothingRegion, KeypointTorsoRegion
from mica.vision.types import CameraStatus

STATUS_INTERVAL_S = 10.0  # SDD 5.2: CameraStatus setiap 10 detik
SIGNAL_KEYS = {  # vision.presence_signal -> kunci ambangnya
    "box_height": "min_box_height_ratio",
    "shoulder_width": "min_shoulder_ratio",
}
BOX_KEYS = ("box_upper.top", "box_upper.bottom", "box_upper.side")
KP_KEYS = ("keypoint_torso.min_kp_conf", "keypoint_torso.shrink", "keypoint_torso.torso_aspect")


class WorkerConfigError(Exception):
    pass


def required_keys(vision: VisionConfig, signal: str) -> tuple[str, ...]:
    """Kunci vision.* yang harus bernilai untuk worker dengan sinyal kehadiran ini."""
    if vision.region == "keypoint_torso":
        keypoint = KP_KEYS
    elif signal == "shoulder_width":
        keypoint = KP_KEYS[:1]  # min_kp_conf untuk bahu
    else:
        keypoint = ()
    # BoxUpperRegion juga cadangan KeypointTorsoRegion, jadi fraksinya selalu dibutuhkan
    return ("dwell_s", "leave_s", SIGNAL_KEYS[signal], "color.min_majority", *BOX_KEYS, *keypoint)


def _config_value(vision: VisionConfig, key: str) -> Any:
    node: Any = vision
    for part in key.split("."):
        node = getattr(node, part)
    return node


def make_signal(signal: str, values: Mapping[str, float]) -> PresenceSignal:
    if signal == "shoulder_width":
        return ShoulderWidthSignal(values["keypoint_torso.min_kp_conf"])
    return BoxHeightSignal()


def make_region(region: str, values: Mapping[str, float]) -> ClothingRegion:
    box = BoxUpperRegion(
        values["box_upper.top"], values["box_upper.bottom"], values["box_upper.side"]
    )
    if region == "box_upper":
        return box
    return KeypointTorsoRegion(  # model -pose dijamin validasi config
        values["keypoint_torso.min_kp_conf"],
        values["keypoint_torso.shrink"],
        values["keypoint_torso.torso_aspect"],
        fallback=box,
    )


def make_color_namer(method: str, path: Path, min_majority: float) -> ColorNamer:
    if method == "color_names_lut":
        return ColorNamesLut.load(path, min_majority)
    return HsvRuleNamer(min_majority)


@dataclass(frozen=True)
class VisionWorkerConfig:
    mode: str
    model: str
    model_file: str
    tracker: str
    conf: float | None
    imgsz: int | None
    region: str
    color_method: str
    colors_file: str
    presence_signal: str
    values: dict[str, float]
    fps_idle: float
    camera_source: int | str = 0
    status_interval_s: float = STATUS_INTERVAL_S
    # dev/tes saja: "modul:fungsi"; camera_factory(source, options) -> Camera,
    # detector_factory(cfg, options) -> PersonDetector
    camera_factory: str | None = None
    detector_factory: str | None = None
    factory_options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        overrides: Mapping[str, float | str] | None = None,
        *,
        models_dir: Path = DEFAULT_MODELS_DIR,
        camera_source: int | str = 0,
        status_interval_s: float = STATUS_INTERVAL_S,
        camera_factory: str | None = None,
        detector_factory: str | None = None,
        factory_options: Mapping[str, Any] | None = None,
    ) -> VisionWorkerConfig:
        """overrides: nilai coba untuk kunci vision.* (termasuk "presence_signal")."""
        if (camera_factory or detector_factory) and settings.app.mode != "dev":
            raise WorkerConfigError(
                "factory kamera/detektor palsu hanya boleh saat app.mode: dev (ditolak di kiosk)"
            )
        vision = settings.vision
        overrides = dict(overrides or {})
        signal = overrides.pop("presence_signal", None) or vision.presence_signal
        if signal is None:
            raise WorkerConfigError("vision.presence_signal null (TBD); worker tidak dimulai")
        if signal not in SIGNAL_KEYS:
            raise WorkerConfigError(f"vision.presence_signal tidak dikenal: {signal}")
        if signal == "shoulder_width" and not vision.model.endswith("-pose"):
            raise WorkerConfigError(
                f"presence_signal shoulder_width butuh model -pose, bukan {vision.model}"
            )
        values: dict[str, float] = {}
        missing = []
        for key in required_keys(vision, str(signal)):
            value = overrides.get(key, _config_value(vision, key))
            if value is None:
                missing.append(f"vision.{key}")
            else:
                values[key] = float(value)
        if missing:
            raise WorkerConfigError(
                "nilai TBD (null) di config, worker tidak dimulai: " + ", ".join(missing)
            )
        cfg = cls(
            mode=settings.app.mode,
            model=vision.model,
            model_file=model_path(vision.model, models_dir).as_posix(),
            tracker=vision.tracker,
            conf=vision.conf,
            imgsz=vision.imgsz,
            region=vision.region,
            color_method=vision.color.method,
            colors_file=(Path(models_dir) / DEFAULT_COLORS_FILE.name).as_posix(),
            presence_signal=str(signal),
            values=values,
            fps_idle=vision.fps_idle,
            camera_source=camera_source,
            status_interval_s=status_interval_s,
            camera_factory=camera_factory,
            detector_factory=detector_factory,
            factory_options=dict(factory_options or {}),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if (self.camera_factory or self.detector_factory) and self.mode != "dev":
            raise WorkerConfigError(
                "factory kamera/detektor palsu hanya boleh saat app.mode: dev (ditolak di kiosk)"
            )

    def check_files(self) -> None:
        """Bobot model dan tabel warna harus ada sebelum proses anak dimulai."""
        if self.detector_factory is None and not Path(self.model_file).is_file():
            raise ModelMissing(Path(self.model_file))
        if self.color_method == "color_names_lut" and not Path(self.colors_file).is_file():
            raise ColorsMissing(Path(self.colors_file))


def load_factory(path: str) -> Callable[..., Any]:
    module, sep, name = path.partition(":")
    if not sep or not module or not name:
        raise WorkerConfigError(f"factory harus berformat modul:fungsi, didapat {path!r}")
    return getattr(importlib.import_module(module), name)


def _make_detector(cfg: VisionWorkerConfig) -> PersonDetector:
    if cfg.detector_factory is not None:
        return load_factory(cfg.detector_factory)(cfg, cfg.factory_options)
    from mica.vision.detector import UltralyticsDetector

    return UltralyticsDetector(Path(cfg.model_file), cfg.tracker, cfg.conf, cfg.imgsz)


def _make_camera(cfg: VisionWorkerConfig) -> Camera:
    if cfg.camera_factory is not None:
        return load_factory(cfg.camera_factory)(cfg.camera_source, cfg.factory_options)
    return Camera(cfg.camera_source)


class VisionLoop:
    """Isi proses vision; dipisah dari run_vision_worker supaya bisa diuji di satu proses."""

    def __init__(
        self,
        cfg: VisionWorkerConfig,
        inbox: Any,
        outbox: Any,
        camera: Camera,
        detector: PersonDetector,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        values = cfg.values
        self.cfg = cfg
        self.inbox = inbox
        self.outbox = outbox
        self.camera = camera
        self.detector = detector
        self.clock = clock
        self.sleep = sleep
        self.region = make_region(cfg.region, values)
        self.namer = make_color_namer(
            cfg.color_method, Path(cfg.colors_file), values["color.min_majority"]
        )
        self.presence = PresenceTracker(
            dwell_s=values["dwell_s"],
            leave_s=values["leave_s"],
            min_signal=values[SIGNAL_KEYS[cfg.presence_signal]],
            signal=make_signal(cfg.presence_signal, values),
            voting=ColorVoting(values["color.min_majority"]),
        )
        self.fps = cfg.fps_idle
        self.camera_ok: bool | None = None
        self.camera_message = ""
        self.detections = 0  # sejak CameraStatus terakhir
        self.running = True

    def _send(self, msg: Any) -> None:
        self.outbox.put(msg)

    def _status(self, ok: bool, message: str, fps: float | None) -> None:
        self.camera_ok, self.camera_message = ok, message
        self._send(CameraStatus(ok=ok, message=message, fps=fps))

    def handle_inbox(self) -> None:
        from mica.core.bus import SetVisionRate, Shutdown

        while True:
            try:
                msg = self.inbox.get_nowait()
            except queue.Empty:
                return
            if isinstance(msg, Shutdown):
                self.running = False
            elif isinstance(msg, SetVisionRate) and msg.fps > 0:
                self.fps = msg.fps

    def _color_of_target(self, frame: np.ndarray, now: float, tracks: list) -> ColorResult | None:
        target = self.presence.target_for(tracks, frame.shape, now)
        if target is None:
            return None
        crop = self.region.extract(frame, target)
        return None if crop is None else self.namer.name(crop)

    def run(self) -> None:
        start = self.clock()
        next_detect = start
        window_start = start
        try:
            while self.running:
                self.handle_inbox()
                if not self.running:
                    break
                frame, status = self.camera.read()
                now = self.clock()
                if status is not None:
                    fps = self.detections / (now - window_start) if now > window_start else None
                    self._status(status.ok, status.message, fps)
                    self.detections, window_start = 0, now
                elif now - window_start >= self.cfg.status_interval_s:
                    fps = self.detections / (now - window_start)
                    self._status(bool(self.camera_ok), self.camera_message, fps)
                    self.detections, window_start = 0, now
                if frame is None:
                    self.sleep(1.0 / self.fps)
                    continue
                if now >= next_detect - 1e-6:
                    tracks = self.detector.detect_and_track(frame)
                    color = self._color_of_target(frame, now, tracks)
                    for event in self.presence.update(
                        tracks, frame.shape, now, color_of=lambda _t, c=color: c
                    ):
                        self._send(event)
                    self.detections += 1
                    next_detect = max(next_detect + 1.0 / self.fps, now)
                del frame  # N-08: frame hanya di memori
        finally:
            self.camera.release()


def run_vision_worker(cfg: VisionWorkerConfig, inbox: Any, outbox: Any) -> None:
    """Entry proses anak. Error tak terduga dilaporkan sebagai CameraStatus(ok=False), lalu
    proses keluar dengan error supaya bus memulai ulang (SDD 8.1)."""
    try:
        cfg.validate()
        cfg.check_files()
        detector = _make_detector(cfg)
        # pemanasan: muat model sebelum kamera dibuka
        detector.detect_and_track(np.zeros((480, 640, 3), dtype=np.uint8))
        loop = VisionLoop(cfg, inbox, outbox, _make_camera(cfg), detector)
        loop.run()
    except Exception as exc:
        outbox.put(CameraStatus(ok=False, message=f"vision worker error: {exc}", fps=None))
        raise
