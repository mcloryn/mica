"""CLI vision M-07, hanya untuk mode dev.

python -m mica.vision fetch-model [--config config/dev.yaml] [--models-dir models]
python -m mica.vision fetch-colors [--config config/dev.yaml] [--models-dir models]
python -m mica.vision demo [--config config/dev.yaml] [--camera 0] [--video <path>] [--no-window]
    [--seconds N] [--dwell-s X] [--leave-s X] [--min-ratio X] [--fps-busy X]

Demo tidak pernah menulis gambar atau video ke disk (N-08). Nilai kehadiran yang TBD di config
(null) wajib diberikan lewat argumen; tidak ada nilai bawaan di kode. Hal yang sama berlaku
untuk warna: --min-majority dan, bila vision.region = box_upper, --box-top/--box-bottom/--box-side.

python -m mica.vision demo ... [--countdown N] [--prompt DETIK:TEKS ...] menampilkan instruksi
berjadwal di jendela (misalnya "10:Berdiri, mundur 4-5 m") untuk uji coba dengan relawan;
--countdown memberi waktu bersiap sebelum waktu demo dihitung.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from mica.config import ConfigError, Settings, VisionConfig, load_settings
from mica.vision.camera import Camera
from mica.vision.color import (
    COLOR_NAMES,
    DEFAULT_COLORS_FILE,
    TABLE_ROWS,
    ColorNamer,
    ColorNamesLut,
    ColorResult,
    ColorsMissing,
    ColorVoting,
    HsvRuleNamer,
)
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
from mica.vision.presence import PresenceState, PresenceTracker, select_target
from mica.vision.region import BoxUpperRegion, ClothingRegion, KeypointTorsoRegion
from mica.vision.types import CameraStatus, PersonArrived, PersonLeft, PersonTrack, VisionEvent

DEFAULT_CONFIG = Path("config/dev.yaml")
# kunci config -> argumen CLI demo
PRESENCE_ARGS = (
    ("dwell_s", "--dwell-s"),
    ("leave_s", "--leave-s"),
    ("min_box_height_ratio", "--min-ratio"),
    ("fps_busy", "--fps-busy"),
)
COLOR_ARGS = (("color.min_majority", "--min-majority"),)
BOX_ARGS = (
    ("box_upper.top", "--box-top"),
    ("box_upper.bottom", "--box-bottom"),
    ("box_upper.side", "--box-side"),
)
# Tabel nama warna van de Weijer dkk. 2009 [30]; sha256 tar diukur saat unduhan pertama
# (16 Okt 2026). Halaman sumber tidak mencantumkan lisensi, jadi tabel tidak di-commit.
COLORS_URL = "https://lear.inrialpes.fr/people/vandeweijer/code/ColorNaming.tar"
COLORS_TAR_SHA256 = "4abad5c8ad4b4d2adf44a4b47cd7d6d3c97f453183e4258f26dd162e566d878a"
COLORS_MEMBER = "ColorNaming/w2c.txt"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mica.vision")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch-model", help="unduh bobot vision.model ke models/ (dev saja)")
    fetch.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    fetch.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)

    colors = sub.add_parser("fetch-colors", help="unduh tabel nama warna ke models/ (dev saja)")
    colors.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    colors.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)

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
    demo.add_argument("--min-majority", type=float, help="menimpa vision.color.min_majority")
    demo.add_argument("--box-top", type=float, help="menimpa vision.box_upper.top")
    demo.add_argument("--box-bottom", type=float, help="menimpa vision.box_upper.bottom")
    demo.add_argument("--box-side", type=float, help="menimpa vision.box_upper.side")
    demo.add_argument(
        "--prompt",
        type=_prompt,
        action="append",
        default=[],
        metavar="DETIK:TEKS",
        help="instruksi di jendela mulai detik ke-N (boleh berulang; teks ASCII)",
    )
    demo.add_argument(
        "--countdown",
        type=float,
        default=0.0,
        help="hitung mundur N detik di jendela sebelum mulai",
    )
    return parser


def _prompt(value: str) -> tuple[float, str]:
    at, sep, text = value.partition(":")
    try:
        seconds = float(at)
    except ValueError:
        seconds = -1.0
    if not sep or seconds < 0 or not text.strip():
        raise argparse.ArgumentTypeError(f"format DETIK:TEKS, didapat {value!r}")
    return seconds, text.strip()


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


# --- fetch-colors -----------------------------------------------------------------------


def _download_bytes(url: str) -> bytes:
    import httpx

    response = httpx.get(url, follow_redirects=True, timeout=120)
    response.raise_for_status()
    return response.content


def extract_w2c(tar_bytes: bytes) -> np.ndarray:
    """w2c.txt dari ColorNaming.tar -> (32768, 11) float32, dengan format diverifikasi."""
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
        member = tar.extractfile(COLORS_MEMBER)  # dibaca di memori, tidak diekstrak ke disk
        if member is None:
            raise DemoError(f"{COLORS_MEMBER} tidak ada di tar")
        data = np.loadtxt(io.BytesIO(member.read()))
    if data.shape != (TABLE_ROWS, 3 + len(COLOR_NAMES)):
        raise DemoError(f"format w2c.txt tak terduga: {data.shape}")
    i = np.arange(TABLE_ROWS)
    centers = np.stack([i % 32, (i // 32) % 32, i // 1024], axis=1) * 8 + 3.5
    if not np.allclose(data[:, :3], centers):
        raise DemoError("urutan baris w2c.txt bukan R + 32*G + 1024*B")
    probs = data[:, 3:]
    if not np.allclose(probs.sum(axis=1), 1.0, atol=1e-3):
        raise DemoError("peluang per baris w2c.txt tidak berjumlah 1")
    return probs.astype(np.float32)


def cmd_fetch_colors(
    args: argparse.Namespace,
    settings: Settings,
    download: Callable[[str], bytes] = _download_bytes,
) -> int:
    _require_dev(settings, "fetch-colors")
    path = Path(args.models_dir) / DEFAULT_COLORS_FILE.name
    if path.is_file():
        print(f"sudah ada: {path.as_posix()}")
    else:
        tar_bytes = download(COLORS_URL)
        tar_sha = hashlib.sha256(tar_bytes).hexdigest()
        print(f"{COLORS_URL} sha256 {tar_sha}")
        if tar_sha != COLORS_TAR_SHA256:
            raise DemoError(f"sha256 tar berbeda dari yang dicatat ({COLORS_TAR_SHA256})")
        table = extract_w2c(tar_bytes)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, table, allow_pickle=False)
    print(f"tabel warna: {path.as_posix()} ({path.stat().st_size} byte)")
    print(f"sha256 {sha256_file(path)}")
    return 0


# --- demo -------------------------------------------------------------------------------


def _config_value(vision: VisionConfig, key: str) -> Any:
    node: Any = vision
    for part in key.split("."):
        node = getattr(node, part)
    return node


def resolve_values(
    vision: VisionConfig, args: argparse.Namespace, pairs: tuple[tuple[str, str], ...]
) -> tuple[dict[str, float], dict[str, str]]:
    """Argumen menimpa config; null tanpa argumen -> DemoError yang menyebut argumennya."""
    values: dict[str, float] = {}
    sources: dict[str, str] = {}
    missing = []
    for key, flag in pairs:
        arg = getattr(args, flag[2:].replace("-", "_"))
        if arg is not None:
            values[key], sources[key] = float(arg), "argumen CLI"
        elif _config_value(vision, key) is not None:
            values[key], sources[key] = float(_config_value(vision, key)), "config"
        else:
            missing.append(f"{flag} (vision.{key} null, TBD)")
    if missing:
        raise DemoError("argumen kurang: " + ", ".join(missing))
    return values, sources


def resolve_presence_values(
    vision: VisionConfig, args: argparse.Namespace
) -> tuple[dict[str, float], dict[str, str]]:
    return resolve_values(vision, args, PRESENCE_ARGS)


def demo_value_pairs(vision: VisionConfig) -> tuple[tuple[str, str], ...]:
    box = BOX_ARGS if vision.region == "box_upper" else ()
    return PRESENCE_ARGS + COLOR_ARGS + box


def make_region(vision: VisionConfig, values: dict[str, float]) -> ClothingRegion:
    if vision.region == "box_upper":
        return BoxUpperRegion(
            values["box_upper.top"], values["box_upper.bottom"], values["box_upper.side"]
        )
    return KeypointTorsoRegion()


def make_color_namer(vision: VisionConfig, path: Path, min_majority: float) -> ColorNamer:
    if vision.color.method == "color_names_lut":
        return ColorNamesLut.load(path, min_majority)
    return HsvRuleNamer(min_majority)


@dataclass
class DemoStats:
    frames: int = 0
    seconds: float = 0.0
    infer_s: float = 0.0
    events: list[tuple[float, VisionEvent]] = field(default_factory=list)
    id_switches: list[tuple[float, int | None, int]] = field(default_factory=list)
    color_majorities: list[float] = field(default_factory=list)  # per frame dengan target
    color_total: np.ndarray = field(default_factory=lambda: np.zeros(len(COLOR_NAMES)))

    @property
    def fps(self) -> float:
        return self.frames / self.seconds if self.seconds > 0 else 0.0


def _wall() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _describe(event: VisionEvent) -> str:
    if isinstance(event, PersonArrived):
        conf = "-" if event.color_confidence is None else f"{event.color_confidence:.2f}"
        return f"PersonArrived track={event.track_id} warna={event.color} ({conf})"
    if isinstance(event, PersonLeft):
        return f"PersonLeft track={event.track_id} durasi={event.duration_s:.1f}s"
    if isinstance(event, CameraStatus):
        return f"CameraStatus ok={event.ok} ({event.message})"
    return repr(event)


def current_prompt(
    prompts: list[tuple[float, str]], elapsed: float
) -> tuple[str | None, tuple[float, str] | None]:
    """(instruksi yang berlaku, (detik, instruksi) berikutnya)."""
    now = None
    upcoming = None
    for at, text in sorted(prompts):
        if at <= elapsed:
            now = text
        elif upcoming is None:
            upcoming = (at, text)
    return now, upcoming


def _banner(frame: Any, lines: list[str]) -> None:
    import cv2

    h, w = frame.shape[:2]
    top = h - 34 * len(lines) - 12
    cv2.rectangle(frame, (0, top), (w, h), (0, 0, 0), -1)
    for i, line in enumerate(lines):
        scale, thick = (0.9, 2) if i == 0 else (0.6, 1)
        y = top + 32 + 34 * i
        cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick)


def _prompt_lines(
    prompts: list[tuple[float, str]], elapsed: float, seconds: float | None
) -> list[str]:
    now, upcoming = current_prompt(prompts, elapsed)
    lines = [now] if now else []
    if upcoming is not None:
        lines.append(f"Berikutnya dalam {upcoming[0] - elapsed:.0f} s: {upcoming[1]}")
    if seconds is not None:
        lines.append(f"Sisa waktu rekaman {max(seconds - elapsed, 0):.0f} s")
    return lines


def _color_text(result: ColorResult | None) -> str:
    if result is None or result.top is None:
        return "warna -"
    return f"warna {result.top} {result.majority:.2f}" + ("" if result.label else " (ragu)")


def _draw(
    frame: Any,
    tracks: list[PersonTrack],
    state: str,
    target: int | None,
    fps: float,
    lines: list[str],
    region_rect: tuple[int, int, int, int] | None = None,
    color: ColorResult | None = None,
):
    import cv2

    h = frame.shape[0]
    if region_rect is not None:
        x1, y1, x2, y2 = region_rect
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 255), 2)
        cv2.putText(
            frame, _color_text(color), (x1, min(y2 + 18, h - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
            (255, 0, 255), 2,
        )  # fmt: skip
    for t in tracks:
        x1, y1, x2, y2 = (int(v) for v in t.box_xyxy)
        color = (0, 200, 0) if t.track_id == target else (200, 200, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"id {t.track_id} r={t.height_ratio(h):.2f}"
        cv2.putText(frame, label, (x1, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    cv2.putText(
        frame, f"{state} | {fps:.1f} fps", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2
    )
    if lines:
        _banner(frame, lines)
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
    prompts: list[tuple[float, str]] | None = None,
    beep: Callable[[], None] | None = None,
    region: ClothingRegion | None = None,
    namer: ColorNamer | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    out: Callable[[str], None] = print,
) -> DemoStats:
    stats = DemoStats()
    prompts = prompts or []
    shown_prompt: str | None = None
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
            prompt, _next = current_prompt(prompts, elapsed)
            if prompt != shown_prompt:
                shown_prompt = prompt
                out(f"[{elapsed:6.2f}s {_wall()}] INSTRUKSI: {prompt}")
                if beep is not None:
                    beep()
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
            # warna area pakaian target frame ini; piksel hanya di memori (N-08)
            target = select_target(tracks, frame_h, presence.min_box_height_ratio)
            frame_color: ColorResult | None = None
            region_rect = None
            if target is not None and region is not None and namer is not None:
                pixels = region.extract(frame, target)
                if isinstance(region, BoxUpperRegion):
                    region_rect = region.rect(frame.shape, target)
                if pixels is not None:
                    frame_color = namer.name(pixels)
                    del pixels
                if frame_color is not None and frame_color.pixels:
                    stats.color_majorities.append(frame_color.majority)
                    stats.color_total += np.asarray(frame_color.distribution)
            before = presence.track_id
            was_engaged = presence.state == PresenceState.ENGAGED
            for event in presence.update(tracks, frame_h, t0, color_of=lambda t, c=frame_color: c):
                stats.events.append((elapsed, event))
                out(f"[{elapsed:6.2f}s {_wall()}] {_describe(event)}")
                if isinstance(event, PersonArrived) and presence.voting is not None:
                    voted = presence.voting.result()
                    top3 = ", ".join(f"{n} {v:.2f}" for n, v in voted.ranked(3))
                    out(f"    suara {presence.voting.frames} frame: {top3}")
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
                lines = _prompt_lines(prompts, elapsed, seconds)
                key = _draw(
                    frame, tracks, presence.state, presence.track_id, stats.fps, lines,
                    region_rect, frame_color,
                )  # fmt: skip
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
                colors = ""
                if frame_color is not None and frame_color.pixels:
                    top3 = ", ".join(f"{n} {v:.2f}" for n, v in frame_color.ranked(3))
                    colors = f" | warna frame: {top3}"
                out(
                    f"[{now - start:6.2f}s] {ratio} | {presence.state} | "
                    f"{window_frames} frame | fps rata-rata {stats.fps:.1f}{colors}"
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


def _beep() -> None:
    try:
        import winsound

        winsound.Beep(1200, 250)
    except (ImportError, RuntimeError):
        pass


def _countdown(camera: Camera, seconds: float, prompts: list[tuple[float, str]]) -> None:
    """Tampilkan kamera dan hitung mundur sebelum waktu demo dihitung (tanpa deteksi)."""
    import cv2

    first, _ = current_prompt(prompts, 0.0)
    end = time.monotonic() + seconds
    while (left := end - time.monotonic()) > 0:
        frame, _status = camera.read()
        if frame is None:
            time.sleep(0.1)
            continue
        lines = [f"Mulai dalam {left:.0f} s"] + ([f"Siapkan: {first}"] if first else [])
        _banner(frame, lines)
        cv2.imshow("MICA vision demo (q = keluar)", frame)
        del frame  # N-08
        cv2.waitKey(30)


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
    values, sources = resolve_values(vision, args, demo_value_pairs(vision))
    path = model_path(vision.model, args.models_dir)
    colors_path = Path(args.models_dir) / DEFAULT_COLORS_FILE.name
    namer = make_color_namer(vision, colors_path, values["color.min_majority"])
    region = make_region(vision, values)
    detector = detector_factory(settings, path)

    sha = sha256_file(path) if path.is_file() else "(file tidak ada)"
    print(f"model {vision.model}: {path.as_posix()} sha256 {sha}")
    print(
        f"tracker {vision.tracker} | perangkat {DEVICE} | conf {vision.conf} | imgsz {vision.imgsz}"
    )
    if colors_path.is_file():
        print(f"tabel warna: {colors_path.as_posix()} sha256 {sha256_file(colors_path)}")
    print(f"area pakaian {vision.region} | metode warna {vision.color.method}")
    if "argumen CLI" in sources.values():
        print("SUMBER NILAI: argumen CLI (uji coba, nilai coba, bukan E-07/E-08)")
    for key, _flag in demo_value_pairs(vision):
        print(f"  {key} = {values[key]} ({sources[key]})")
    print(f"  fps_idle = {vision.fps_idle} (config)")
    source: int | str = str(args.video) if args.video is not None else args.camera
    print(f"sumber {'video ' + str(args.video) if args.video else f'kamera {args.camera}'}")

    camera = camera_factory(source)
    t_warm = clock()
    _frame, status = camera.read()  # buka kamera dan muat model sebelum waktu demo dihitung
    del _frame  # N-08
    if status is not None:
        print(_describe(status))
    detector.detect_and_track(np.zeros((480, 640, 3), dtype=np.uint8))
    print(f"pemanasan kamera dan model {clock() - t_warm:.1f} s")

    if args.countdown > 0 and not args.no_window:
        _countdown(camera, args.countdown, args.prompt)

    presence = PresenceTracker(
        dwell_s=values["dwell_s"],
        leave_s=values["leave_s"],
        min_box_height_ratio=values["min_box_height_ratio"],
        voting=ColorVoting(values["color.min_majority"]),
    )
    stats = run_demo(
        detector,
        camera,
        presence,
        fps_idle=vision.fps_idle,
        fps_busy=values["fps_busy"],
        seconds=args.seconds,
        show_window=not args.no_window,
        stop_on_read_fail=args.video is not None,
        prompts=args.prompt,
        beep=None if args.no_window else _beep,
        region=region,
        namer=namer,
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
    if stats.color_majorities:
        m = np.asarray(stats.color_majorities)
        share = stats.color_total / stats.color_total.sum()
        top3 = ", ".join(f"{COLOR_NAMES[i]} {share[i]:.2f}" for i in np.argsort(share)[::-1][:3])
        print(
            f"warna per frame ({m.size} frame dengan target): proporsi terbanyak "
            f"min {m.min():.2f} | median {np.median(m):.2f} | maks {m.max():.2f}; "
            f"distribusi rata-rata: {top3}"
        )
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
        if args.command == "fetch-colors":
            return cmd_fetch_colors(args, settings)
        return cmd_demo(args, settings, detector_factory, camera_factory, clock, sleep)
    except (ConfigError, DemoError, ModelMissing, ColorsMissing) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
