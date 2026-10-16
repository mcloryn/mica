"""CLI vision M-07, hanya untuk mode dev.

python -m mica.vision fetch-model [--config config/dev.yaml] [--models-dir models]
python -m mica.vision demo [--config config/dev.yaml] [--camera 0] [--video <path>] [--no-window]
    [--seconds N] [--dwell-s X] [--leave-s X] [--min-ratio X] [--fps-busy X]

Demo tidak pernah menulis gambar atau video ke disk (N-08). Nilai kehadiran yang TBD di config
(null) wajib diberikan lewat argumen; tidak ada nilai bawaan di kode.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mica.config import ConfigError, Settings, VisionConfig, load_settings
from mica.vision.camera import Camera
from mica.vision.detector import (
    DEFAULT_MODELS_DIR,
    DEVICE,
    ModelMissing,
    PersonDetector,
    UltralyticsDetector,
    disable_ultralytics_sync,
    model_path,
    sha256_file,
)
from mica.vision.presence import PresenceState, PresenceTracker
from mica.vision.types import CameraStatus, PersonArrived, PersonLeft, PersonTrack, VisionEvent

DEFAULT_CONFIG = Path("config/dev.yaml")
# kunci config -> argumen CLI demo
PRESENCE_ARGS = (
    ("dwell_s", "--dwell-s"),
    ("leave_s", "--leave-s"),
    ("min_box_height_ratio", "--min-ratio"),
    ("fps_busy", "--fps-busy"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mica.vision")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch-model", help="unduh bobot vision.model ke models/ (dev saja)")
    fetch.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    fetch.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)

    demo = sub.add_parser("demo", help="deteksi + kehadiran dari webcam atau video (dev saja)")
    demo.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    demo.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    demo.add_argument("--camera", type=int, default=0)
    demo.add_argument("--video", type=Path, help="baca file video, bukan webcam")
    demo.add_argument("--no-window", action="store_true", help="tanpa jendela OpenCV")
    demo.add_argument("--seconds", type=float, help="berhenti setelah N detik")
    demo.add_argument("--dwell-s", type=float, help="menimpa vision.dwell_s")
    demo.add_argument("--leave-s", type=float, help="menimpa vision.leave_s")
    demo.add_argument("--min-ratio", type=float, help="menimpa vision.min_box_height_ratio")
    demo.add_argument("--fps-busy", type=float, help="menimpa vision.fps_busy")
    return parser


class DemoError(Exception):
    pass


def _require_dev(settings: Settings, command: str) -> None:
    if settings.app.mode != "dev":
        raise DemoError(f"{command} hanya boleh dijalankan saat app.mode: dev")


# --- fetch-model ------------------------------------------------------------------------


def _download_asset(path: Path) -> Path:
    # attempt_download_asset mengunduh rilis GitHub ultralytics/assets ke path yang diberikan
    # (safe_download membuat folder induknya), kecuali file sudah ada di path itu atau di
    # SETTINGS["weights_dir"]; kasus kedua ditolak oleh cmd_fetch_model.
    from ultralytics.utils.downloads import attempt_download_asset

    return Path(attempt_download_asset(path))


def cmd_fetch_model(
    args: argparse.Namespace,
    settings: Settings,
    download: Callable[[Path], Path] = _download_asset,
    disable_sync: Callable[[], None] = disable_ultralytics_sync,
) -> int:
    _require_dev(settings, "fetch-model")
    path = model_path(settings.vision.model, args.models_dir)
    if path.is_file():
        print(f"sudah ada: {path.as_posix()}")
    else:
        disable_sync()
        got = download(path)
        if not path.is_file() or got.resolve() != path.resolve():
            raise DemoError(f"unduhan tidak berakhir di {path.as_posix()} (didapat {got})")
    print(f"model {settings.vision.model}: {path.as_posix()} ({path.stat().st_size} byte)")
    print(f"sha256 {sha256_file(path)}")
    return 0


# --- demo -------------------------------------------------------------------------------


def resolve_presence_values(
    vision: VisionConfig, args: argparse.Namespace
) -> tuple[dict[str, float], dict[str, str]]:
    """Argumen menimpa config; null tanpa argumen -> DemoError yang menyebut argumennya."""
    values: dict[str, float] = {}
    sources: dict[str, str] = {}
    missing = []
    for key, flag in PRESENCE_ARGS:
        arg = getattr(args, flag[2:].replace("-", "_"))
        if arg is not None:
            values[key], sources[key] = float(arg), "argumen CLI"
        elif getattr(vision, key) is not None:
            values[key], sources[key] = float(getattr(vision, key)), "config"
        else:
            missing.append(f"{flag} (vision.{key} null, TBD)")
    if missing:
        raise DemoError("argumen kurang: " + ", ".join(missing))
    return values, sources


@dataclass
class DemoStats:
    frames: int = 0
    seconds: float = 0.0
    infer_s: float = 0.0
    events: list[tuple[float, VisionEvent]] = field(default_factory=list)
    id_switches: list[tuple[float, int | None, int]] = field(default_factory=list)

    @property
    def fps(self) -> float:
        return self.frames / self.seconds if self.seconds > 0 else 0.0


def _wall() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _describe(event: VisionEvent) -> str:
    if isinstance(event, PersonArrived):
        return f"PersonArrived track={event.track_id}"
    if isinstance(event, PersonLeft):
        return f"PersonLeft track={event.track_id} durasi={event.duration_s:.1f}s"
    if isinstance(event, CameraStatus):
        return f"CameraStatus ok={event.ok} ({event.message})"
    return repr(event)


def _draw(frame: Any, tracks: list[PersonTrack], state: str, target: int | None, fps: float):
    import cv2

    h = frame.shape[0]
    for t in tracks:
        x1, y1, x2, y2 = (int(v) for v in t.box_xyxy)
        color = (0, 200, 0) if t.track_id == target else (200, 200, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"id {t.track_id} r={t.height_ratio(h):.2f}"
        cv2.putText(frame, label, (x1, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    cv2.putText(
        frame, f"{state} | {fps:.1f} fps", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2
    )
    cv2.imshow("MICA vision demo (q = keluar)", frame)
    return cv2.waitKey(1) & 0xFF


def run_demo(
    detector: PersonDetector,
    camera: Camera,
    presence: PresenceTracker,
    *,
    fps_idle: float,
    fps_busy: float,
    seconds: float | None,
    show_window: bool,
    stop_on_read_fail: bool = False,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    out: Callable[[str], None] = print,
) -> DemoStats:
    stats = DemoStats()
    start = clock()
    report_at = start + 1.0
    window_ratios: list[float] = []  # rasio box terbesar per frame dalam detik ini
    window_frames = 0
    try:
        while True:
            t0 = clock()
            elapsed = t0 - start
            if seconds is not None and elapsed >= seconds:
                break
            frame, status = camera.read()
            if status is not None:
                stats.events.append((elapsed, status))
                out(f"[{elapsed:6.2f}s {_wall()}] {_describe(status)}")
            if frame is None:
                if stop_on_read_fail:
                    break
                sleep(1.0 / fps_idle)
                continue

            t_infer = clock()
            tracks = detector.detect_and_track(frame)
            stats.infer_s += clock() - t_infer
            frame_h = frame.shape[0]
            before = presence.track_id
            was_engaged = presence.state == PresenceState.ENGAGED
            for event in presence.update(tracks, frame_h, t0):
                stats.events.append((elapsed, event))
                out(f"[{elapsed:6.2f}s {_wall()}] {_describe(event)}")
            engaged = presence.state == PresenceState.ENGAGED
            if was_engaged and engaged and presence.track_id != before:
                assert presence.track_id is not None
                stats.id_switches.append((elapsed, before, presence.track_id))
                out(f"[{elapsed:6.2f}s] ID switch {before} -> {presence.track_id}")
            stats.frames += 1
            window_frames += 1
            if tracks:
                window_ratios.append(max(t.height_ratio(frame_h) for t in tracks))

            if show_window:
                key = _draw(frame, tracks, presence.state, presence.track_id, stats.fps)
                if key == ord("q"):
                    break
            del frame  # N-08: frame hanya di memori

            now = clock()
            stats.seconds = now - start
            if now >= report_at:
                if window_ratios:
                    ratio = (
                        f"rasio box terbesar {window_ratios[-1]:.3f} "
                        f"(rentang {min(window_ratios):.3f}-{max(window_ratios):.3f})"
                    )
                else:
                    ratio = "rasio box terbesar - (tidak ada orang)"
                out(
                    f"[{now - start:6.2f}s] {ratio} | {presence.state} | "
                    f"{window_frames} frame | fps rata-rata {stats.fps:.1f}"
                )
                window_ratios, window_frames = [], 0
                report_at = now + 1.0

            fps = fps_busy if presence.state == PresenceState.ENGAGED else fps_idle
            remaining = 1.0 / fps - (clock() - t0)
            if remaining > 0:
                sleep(remaining)
    finally:
        camera.release()
        if show_window:
            import cv2

            cv2.destroyAllWindows()
    stats.seconds = clock() - start
    return stats


def _make_detector(settings: Settings, path: Path) -> PersonDetector:
    v = settings.vision
    return UltralyticsDetector(path, v.tracker, v.conf, v.imgsz)


def cmd_demo(
    args: argparse.Namespace,
    settings: Settings,
    detector_factory: Callable[[Settings, Path], PersonDetector] = _make_detector,
    camera_factory: Callable[[int | str], Camera] = Camera,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    _require_dev(settings, "demo")
    vision = settings.vision
    values, sources = resolve_presence_values(vision, args)
    path = model_path(vision.model, args.models_dir)
    detector = detector_factory(settings, path)

    sha = sha256_file(path) if path.is_file() else "(file tidak ada)"
    print(f"model {vision.model}: {path.as_posix()} sha256 {sha}")
    print(
        f"tracker {vision.tracker} | perangkat {DEVICE} | conf {vision.conf} | imgsz {vision.imgsz}"
    )
    if "argumen CLI" in sources.values():
        print("SUMBER NILAI: argumen CLI (uji coba, bukan E-07)")
    for key, _flag in PRESENCE_ARGS:
        print(f"  {key} = {values[key]} ({sources[key]})")
    print(f"  fps_idle = {vision.fps_idle} (config)")
    source: int | str = str(args.video) if args.video is not None else args.camera
    print(f"sumber {'video ' + str(args.video) if args.video else f'kamera {args.camera}'}")

    presence = PresenceTracker(
        dwell_s=values["dwell_s"],
        leave_s=values["leave_s"],
        min_box_height_ratio=values["min_box_height_ratio"],
    )
    stats = run_demo(
        detector,
        camera_factory(source),
        presence,
        fps_idle=vision.fps_idle,
        fps_busy=values["fps_busy"],
        seconds=args.seconds,
        show_window=not args.no_window,
        stop_on_read_fail=args.video is not None,
        clock=clock,
        sleep=sleep,
    )
    infer_ms = stats.infer_s / stats.frames * 1000 if stats.frames else 0.0
    print(
        f"selesai: {stats.frames} frame dalam {stats.seconds:.1f} s, fps rata-rata {stats.fps:.2f}, "
        f"inferensi rata-rata {infer_ms:.1f} ms/frame"
    )
    kinds = [_describe(e) for _, e in stats.events if not isinstance(e, CameraStatus)]
    print(f"event: {len(kinds)} ({'; '.join(kinds) or 'tidak ada'})")
    print(f"ID switch: {len(stats.id_switches)}")
    return 0


def main(
    argv: list[str] | None = None,
    detector_factory: Callable[[Settings, Path], PersonDetector] = _make_detector,
    camera_factory: Callable[[int | str], Camera] = Camera,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
        if args.command == "fetch-model":
            return cmd_fetch_model(args, settings)
        return cmd_demo(args, settings, detector_factory, camera_factory, clock, sleep)
    except (ConfigError, DemoError, ModelMissing) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
