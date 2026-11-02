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
import threading
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
    ColorNamesLutMean,
    ColorResult,
    ColorsMissing,
    ColorVoting,
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
    if method == "lut_mean":
        return ColorNamesLutMean.load(path, min_majority)
    return ColorNamesLut.load(path, min_majority)


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
    threads: int | None = None  # vision.threads -> torch.set_num_threads; None = bawaan torch
    camera_source: int | str = 0
    status_interval_s: float = STATUS_INTERVAL_S
    # dev/tes saja: "modul:fungsi"; camera_factory(source, options) -> Camera,
    # detector_factory(cfg, options) -> PersonDetector
    camera_factory: str | None = None
    detector_factory: str | None = None
    factory_options: dict[str, Any] = field(default_factory=dict)
    # dev saja: jendela pratinjau di proses ini (frame tetap tidak lewat bus), dengan hitung
    # mundur setelah kamera siap dan aba-aba (detik sejak hitung mundur selesai, teks)
    preview: bool = False
    prompts: tuple[tuple[float, str], ...] = ()
    countdown_s: float = 0.0
    preview_seconds: float | None = None  # untuk baris "sisa waktu" di jendela
    # pratinjau UI kiosk (ui.camera_preview; mica.vision.livepreview): JPEG kecil lewat antrean
    # terpisah dari bus, dengan laju dan blok pixelate dari config
    camera_preview: str = "off"
    pause_during_tts: bool = False  # vision.pause_during_tts (Langkah 51)
    preview_fps: float | None = None
    preview_pixel_block: int | None = None
    # dev saja (--measure-preview): angka laju/waktu ke antrean pengukuran (mica.eval.preview_meter)
    measure: bool = False
    # CV-3c, uji kemampuan saja (--test-exposure, dev + --measure-preview): exposure manual kamera.
    # None (bawaan, dev dan prod) = exposure otomatis. Bukan kunci config.
    test_exposure: float | None = None

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
        preview: bool = False,
        prompts: tuple[tuple[float, str], ...] = (),
        countdown_s: float = 0.0,
        preview_seconds: float | None = None,
    ) -> VisionWorkerConfig:
        """overrides: nilai coba untuk kunci vision.* (termasuk "presence_signal")."""
        _check_dev_only(settings.app.mode, bool(camera_factory or detector_factory), preview)
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
            threads=vision.threads,
            camera_source=camera_source,
            status_interval_s=status_interval_s,
            camera_factory=camera_factory,
            detector_factory=detector_factory,
            factory_options=dict(factory_options or {}),
            preview=preview,
            prompts=tuple(prompts),
            countdown_s=countdown_s,
            preview_seconds=preview_seconds,
            camera_preview=settings.ui.camera_preview,
            pause_during_tts=settings.vision.pause_during_tts,
            preview_fps=settings.ui.preview_fps,
            preview_pixel_block=settings.ui.preview_pixel_block,
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        _check_dev_only(self.mode, bool(self.camera_factory or self.detector_factory), self.preview)
        if self.measure and self.mode != "dev":
            raise WorkerConfigError("pengukuran pratinjau hanya boleh saat app.mode: dev")
        if self.test_exposure is not None and (self.mode != "dev" or not self.measure):
            raise WorkerConfigError(
                "exposure manual (--test-exposure) hanya untuk uji kemampuan dev "
                "dengan --measure-preview"
            )
        if self.camera_preview == "debug" and self.mode != "dev":
            raise WorkerConfigError(
                "pratinjau debug (tanpa samaran) hanya boleh saat app.mode: dev"
            )
        if self.camera_preview != "off" and not (self.preview_fps and self.preview_pixel_block):
            raise WorkerConfigError(
                "ui.preview_fps dan ui.preview_pixel_block wajib bila pratinjau aktif"
            )

    def check_files(self) -> None:
        """Bobot model dan tabel warna harus ada sebelum proses anak dimulai."""
        if self.detector_factory is None and not Path(self.model_file).is_file():
            raise ModelMissing(Path(self.model_file))
        if not Path(self.colors_file).is_file():  # lut_vote dan lut_mean memakai tabel
            raise ColorsMissing(Path(self.colors_file))


def _check_dev_only(mode: str, factories: bool, preview: bool) -> None:
    if mode == "dev":
        return
    if factories:
        raise WorkerConfigError(
            "factory kamera/detektor palsu hanya boleh saat app.mode: dev (ditolak di kiosk)"
        )
    if preview:
        raise WorkerConfigError(
            "pratinjau kamera hanya boleh saat app.mode: dev (ditolak di kiosk)"
        )


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
    return Camera(cfg.camera_source, exposure=cfg.test_exposure)


# CV-3: batas tunggu loop utama akan frame baru (inbox tetap diperiksa) dan batas join thread
# pembaca saat berhenti; nilai implementasi, bukan ambang SDD
GRAB_WAIT_S = 0.05
GRAB_JOIN_S = 2.0


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
        preview_out: Any = None,
        measure_out: Any = None,
        tts_busy: Any = None,
        threaded: bool = False,
    ) -> None:
        values = cfg.values
        # CV-3: threaded=True (proses vision asli) -> kamera dibaca dan pratinjau dikirim di
        # thread pembaca sendiri; loop utama hanya mengambil frame TERBARU untuk YOLO (frame lama
        # dibuang), jadi pratinjau tidak menunggu inferensi. False = loop tunggal lama (tes
        # dengan jam palsu dan scripts/camera_rate.py).
        self.threaded = threaded
        self.slot = threading.Condition()  # frame terbaru + status kamera dari thread pembaca
        self.latest_frame: np.ndarray | None = None
        self.latest_seq = 0
        self.pending_status: list[Any] = []
        self.grab_error: BaseException | None = None
        self.meter_lock = threading.Lock()  # VisionMeter dipanggil dari dua thread
        # Langkah 51: Event bersama proses suara; di-set selama Piper menyusun suara
        self.tts_busy = tts_busy if cfg.pause_during_tts else None
        self.paused_since: float | None = None
        self.skipped = 0  # jatah deteksi yang dilewati karena jeda TTS
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
        self.first_detection_marked = False
        self.running = True
        self.preview_on = cfg.preview
        self.scenario_start: float | None = None  # kamera siap + hitung mundur
        self.overlay: Any = None
        if cfg.preview:
            from mica.vision.preview import Overlay

            self.overlay = Overlay()
        self.shown: list[float] = []  # waktu frame ditampilkan / dideteksi (1 detik terakhir)
        self.detected: list[float] = []
        # pratinjau UI kiosk: hanya bila mode bukan off DAN ada antrean; tanpa itu tidak ada JPEG
        self.preview_out = preview_out
        self.renderer: Any = None
        if preview_out is not None and cfg.camera_preview != "off":
            from mica.vision.livepreview import PreviewRenderer

            assert cfg.preview_pixel_block is not None
            self.renderer = PreviewRenderer(cfg.camera_preview, cfg.preview_pixel_block,
                                            values.get("keypoint_torso.min_kp_conf"))  # fmt: skip
        self.next_preview: float | None = None
        self.previews = 0  # JPEG pratinjau yang dikirim
        # hasil deteksi terakhir untuk overlay pratinjau (pratinjau tidak memanggil detektor)
        self.last: tuple[Any, Any, Any, ColorResult | None] = ([], None, None, None)
        self.meter: Any = None
        if measure_out is not None and cfg.measure:
            from mica.eval.preview_meter import VisionMeter

            self.meter = VisionMeter(measure_out, clock)

    def _send(self, msg: Any) -> None:
        self.outbox.put(msg)

    def _status(self, ok: bool, message: str, fps: float | None) -> None:
        self.camera_ok, self.camera_message = ok, message
        self._send(CameraStatus(ok=ok, message=message, fps=fps))

    def _tts_pause(self, now: float) -> bool:
        """True selama Piper menyusun suara (vision.pause_during_tts). Saat jeda selesai, timer
        pergi PresenceTracker digeser sepanjang jeda (dibekukan)."""
        busy = self.tts_busy is not None and self.tts_busy.is_set()
        if busy and self.paused_since is None:
            self.paused_since = now
        elif not busy and self.paused_since is not None:
            self.presence.freeze(now - self.paused_since)
            self.paused_since = None
        return busy

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

    def _detect(self, frame: np.ndarray, now: float) -> None:
        tracks = self.detector.detect_and_track(frame)
        target = self.presence.target_for(tracks, frame.shape, now)
        located = self.region.locate(frame.shape, target) if target is not None else None
        color: ColorResult | None = None
        if located is not None:
            x1, y1, x2, y2 = located[0]
            color = self.namer.name(frame[y1:y2, x1:x2])  # piksel hanya di memori (N-08)
        for event in self.presence.update(tracks, frame.shape, now, color_of=lambda _t: color):
            self._send(event)
        self.last = (tracks, target, located[0] if located is not None else None, color)
        self.detections += 1
        if not self.first_detection_marked:  # Langkah 40: tahap start-up
            from mica.core import startup

            self.first_detection_marked = True
            startup.mark("first_detection")
        self.detected.append(now)
        if self.overlay is not None:
            self.overlay.tracks = tracks
            self.overlay.state = self.presence.state
            self.overlay.target = target.track_id if target is not None else None
            self.overlay.region_rect = located[0] if located is not None else None
            self.overlay.region_source = located[1] if located is not None else None
            self.overlay.color = color

    def _publish_preview(self, frame: np.ndarray) -> None:
        """JPEG pratinjau dari frame ini + hasil deteksi terakhir -> antrean (frame lama dibuang)."""
        from mica.vision.livepreview import encode_jpeg, put_latest

        tracks, target, region, color = self.last
        label = None
        if color is not None:
            if self.cfg.camera_preview == "debug" and color.top is not None:
                label = f"{color.top} {color.majority:.2f}"
            else:
                label = color.label
        start = self.clock()
        image = self.renderer.render(frame, tracks, target, region, label)
        sent = put_latest(self.preview_out, encode_jpeg(image))
        if self.meter is not None:
            with self.meter_lock:
                self.meter.rendered(self.clock() - start, sent)
        if sent:
            self.previews += 1

    def _show(self, frame: np.ndarray, now: float) -> None:
        """Gambar pratinjau; q menutup jendela tanpa menghentikan worker."""
        import cv2

        from mica.vision.preview import WINDOW, _banner, _draw, _prompt_lines, current_prompt

        self.shown = [t for t in self.shown if now - t < 1.0] + [now]
        self.detected = [t for t in self.detected if now - t < 1.0]
        assert self.scenario_start is not None
        if now < self.scenario_start:  # hitung mundur, tanpa deteksi
            first, _ = current_prompt(list(self.cfg.prompts), 0.0)
            lines = [f"Mulai dalam {self.scenario_start - now:.0f} s"]
            lines += [f"Siapkan: {first}"] if first else []
            _banner(frame, lines)
            cv2.imshow(WINDOW, frame)
            key = cv2.waitKey(1) & 0xFF
        else:
            elapsed = now - self.scenario_start
            lines = _prompt_lines(list(self.cfg.prompts), elapsed, self.cfg.preview_seconds)
            kp_conf = self.cfg.values.get("keypoint_torso.min_kp_conf")
            key = _draw(frame, self.overlay, len(self.shown), len(self.detected), lines, kp_conf)
        if key == ord("q"):
            cv2.destroyWindow(WINDOW)
            self.preview_on = False

    def _mark_first_frame(self, now: float) -> None:
        """Frame pertama: kamera siap, hitung mundur (jendela dev) dimulai."""
        from mica.core import startup

        startup.mark("camera_first_frame")
        countdown = self.cfg.countdown_s if self.cfg.preview else 0.0
        self.scenario_start = now + countdown

    def _maybe_preview(self, frame: np.ndarray, now: float) -> None:
        """JPEG pratinjau bila jatahnya tiba (1/ui.preview_fps), dengan deteksi terakhir."""
        assert self.scenario_start is not None
        due = self.next_preview is None or now >= self.next_preview - 1e-6
        if self.renderer is not None and now >= self.scenario_start and due:
            self._publish_preview(frame)
            assert self.cfg.preview_fps is not None
            step = 1.0 / self.cfg.preview_fps
            self.next_preview = max((self.next_preview or now) + step, now)

    def _report_status(self, status: Any, now: float, window_start: float) -> float:
        """CameraStatus saat berubah atau berkala; mengembalikan awal jendela hitung fps."""
        if status is not None:
            fps = self.detections / (now - window_start) if now > window_start else None
            self._status(status.ok, status.message, fps)
            self.detections = 0
            return now
        if now - window_start >= self.cfg.status_interval_s:
            fps = self.detections / (now - window_start)
            self._status(bool(self.camera_ok), self.camera_message, fps)
            self.detections = 0
            return now
        return window_start

    def _detect_if_due(self, frame: np.ndarray, now: float, next_detect: float) -> float:
        """Deteksi pada laju vision (fps_idle/fps_busy), dilewati saat jeda TTS."""
        if self._tts_pause(now):
            if now >= next_detect - 1e-6:
                self.skipped += 1
                next_detect = max(next_detect + 1.0 / self.fps, now)
        elif now >= next_detect - 1e-6:
            self._detect(frame, now)
            if self.meter is not None:
                with self.meter_lock:
                    self.meter.detected(self.clock() - now)
            next_detect = max(next_detect + 1.0 / self.fps, now)
        return next_detect

    def run(self) -> None:
        if self.threaded:
            self._run_threaded()
            return
        start = self.clock()
        next_detect = start
        window_start = start
        try:
            while self.running:
                self.handle_inbox()
                if not self.running:
                    break
                read_start = self.clock()
                frame, status = self.camera.read()
                now = self.clock()
                if self.meter is not None:
                    self.meter.tick()
                    if frame is not None:
                        self.meter.camera(getattr(self.camera, "capture", None))
                        self.meter.frame(frame.shape, now - read_start)
                window_start = self._report_status(status, now, window_start)
                if frame is None:
                    self.sleep(1.0 / self.fps)
                    continue
                if self.scenario_start is None:  # frame pertama: kamera siap
                    self._mark_first_frame(now)
                    assert self.scenario_start is not None
                    next_detect = self.scenario_start
                next_detect = self._detect_if_due(frame, now, next_detect)
                self._maybe_preview(frame, now)
                if self.preview_on:
                    self._show(frame, now)
                del frame  # N-08: frame hanya di memori
        finally:
            self.camera.release()

    def _grab_loop(self, stop: threading.Event) -> None:
        """Thread pembaca (CV-3): baca kamera secepat driver memberi frame, simpan HANYA frame
        terbaru di slot (yang lama dibuang), dan kirim pratinjau pada ui.preview_fps memakai
        deteksi terakhir. Tidak pernah menunggu YOLO."""
        try:
            while not stop.is_set():
                read_start = self.clock()
                frame, status = self.camera.read()
                now = self.clock()
                if self.meter is not None:
                    with self.meter_lock:
                        self.meter.tick()
                        if frame is not None:
                            self.meter.camera(getattr(self.camera, "capture", None))
                            self.meter.frame(frame.shape, now - read_start)
                if frame is not None and self.scenario_start is None:
                    self._mark_first_frame(now)
                with self.slot:
                    if status is not None:
                        self.pending_status.append(status)
                    if frame is not None:
                        self.latest_frame = frame
                        self.latest_seq += 1
                    self.slot.notify_all()
                if frame is None:
                    stop.wait(1.0 / self.fps)
                    continue
                self._maybe_preview(frame, now)
                del frame  # N-08: frame hanya di memori
        except BaseException as exc:  # noqa: BLE001 - dinaikkan ulang oleh loop utama
            with self.slot:
                self.grab_error = exc
                self.slot.notify_all()

    def _run_threaded(self) -> None:
        stop = threading.Event()
        grabber = threading.Thread(target=self._grab_loop, args=(stop,),
                                   name="mica-vision-grab", daemon=True)  # fmt: skip
        start = self.clock()
        next_detect = start
        window_start = start
        last_seq = 0
        started = False  # next_detect sudah disejajarkan ke scenario_start
        grabber.start()
        try:
            while self.running:
                self.handle_inbox()
                if not self.running:
                    break
                with self.slot:
                    self.slot.wait_for(
                        lambda last=last_seq: bool(self.pending_status)
                        or self.grab_error is not None
                        or self.latest_seq != last,
                        timeout=GRAB_WAIT_S,
                    )  # fmt: skip
                    statuses, self.pending_status = self.pending_status, []
                    frame, seq, error = self.latest_frame, self.latest_seq, self.grab_error
                if error is not None:
                    raise error
                now = self.clock()
                for status in statuses or [None]:
                    window_start = self._report_status(status, now, window_start)
                if frame is None or seq == last_seq:
                    continue  # belum ada frame baru; frame yang terlewat memang dibuang
                last_seq = seq
                if not started and self.scenario_start is not None:
                    next_detect, started = self.scenario_start, True
                next_detect = self._detect_if_due(frame, now, next_detect)
                if self.preview_on:
                    self._show(frame.copy(), now)  # salinan: thread pembaca memakai frame sama
                del frame  # N-08: frame hanya di memori
        finally:
            stop.set()
            grabber.join(GRAB_JOIN_S)
            with self.slot:
                self.latest_frame = None
            self.camera.release()


def warm_up(cfg: VisionWorkerConfig, detector: PersonDetector) -> int | None:
    """Inferensi pemanasan (model dimuat sebelum kamera dibuka), lalu vision.threads.

    vision.threads dipasang SETELAH inferensi pertama: Ultralytics 8.4 select_device memanggil
    torch.set_num_threads(min(8, cpu_count - 1)) saat predictor disiapkan, sehingga setelan yang
    dipasang lebih awal tertimpa (ditemukan di bench docs/CPU-THREADS.md, Langkah 50).
    Mengembalikan thread intra-op torch yang berlaku (None untuk detektor palsu tanpa threads).
    """
    detector.detect_and_track(np.zeros((480, 640, 3), dtype=np.uint8))
    if cfg.threads is None and cfg.detector_factory is not None:
        return None
    from mica.vision.detector import apply_torch_threads

    return apply_torch_threads(cfg.threads)


def run_vision_worker(
    cfg: VisionWorkerConfig,
    inbox: Any,
    outbox: Any,
    preview_out: Any = None,
    measure_out: Any = None,
    tts_busy: Any = None,
) -> None:
    """Entry proses anak. Error tak terduga dilaporkan sebagai CameraStatus(ok=False), lalu
    proses keluar dengan error supaya bus memulai ulang (SDD 8.1)."""
    from mica.core import startup

    startup.set_process("vision")
    startup.mark("proc_start")
    try:
        cfg.validate()
        cfg.check_files()
        startup.timed_import("cv2")
        if cfg.detector_factory is None:  # modul yang memang dimuat UltralyticsDetector
            startup.timed_import("torch")
            startup.timed_import("ultralytics")
        startup.mark("model_load_start")
        detector = _make_detector(cfg)
        startup.mark("model_load_done")
        torch_threads = warm_up(cfg, detector)
        startup.mark("warmup_inference_done")
        loop = VisionLoop(cfg, inbox, outbox, _make_camera(cfg), detector,
                          preview_out=preview_out, measure_out=measure_out,
                          tts_busy=tts_busy, threaded=True)  # fmt: skip
        if loop.meter is not None:
            loop.meter.torch_threads = torch_threads
        loop.run()
    except Exception as exc:
        outbox.put(CameraStatus(ok=False, message=f"vision worker error: {exc}", fps=None))
        raise
