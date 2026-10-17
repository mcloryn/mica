"""CLI vision M-07, hanya untuk mode dev.

python -m mica.vision fetch-model [--config config/dev.yaml] [--models-dir models]
python -m mica.vision fetch-colors [--config config/dev.yaml] [--models-dir models]
python -m mica.vision demo [--config config/dev.yaml] [--camera 0] [--video <path>] [--no-window]
    [--seconds N] [--dwell-s X] [--leave-s X] [--min-ratio X] [--fps-busy X]

Demo tidak pernah menulis gambar atau video ke disk (N-08). Nilai kehadiran yang TBD di config
(null) wajib diberikan lewat argumen; tidak ada nilai bawaan di kode. Hal yang sama berlaku
untuk warna: --min-majority, --box-top/--box-bottom/--box-side (area kotak, juga cadangan
keypoint), dan bila vision.region = keypoint_torso: --kp-conf/--kp-shrink/--torso-aspect.
Sinyal kehadiran: --presence-signal box_height|shoulder_width dengan ambang --min-ratio atau
--min-shoulder-ratio (shoulder_width juga butuh --kp-conf).

Setiap frame kamera dibaca dan ditampilkan (laju penuh kamera); detektor dan PresenceTracker
hanya berjalan sesuai fps_idle/fps_busy, dan hasil terakhirnya digambar ulang di antara deteksi.

python -m mica.vision bus-demo [--seconds 30] [--kill-after N] <nilai coba seperti demo>
    menjalankan vision worker di proses anak lewat bus M-13; proses utama hanya mencetak pesan.

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
    ColorResult,
    ColorsMissing,
    ColorVoting,
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
from mica.vision.presence import (
    PresenceState,
    PresenceTracker,
)
from mica.vision.preview import (
    WINDOW,
    Overlay,
    _banner,
    _draw,
    _prompt_lines,
    current_prompt,
)
from mica.vision.region import (
    L_SHOULDER,
    R_SHOULDER,
    ClothingRegion,
    shoulder_width_ratio,
)
from mica.vision.types import CameraStatus, PersonArrived, PersonLeft, PersonTrack, VisionEvent
from mica.vision.worker import WorkerConfigError, make_color_namer, make_region, make_signal

DEFAULT_CONFIG = Path("config/dev.yaml")
START_TIMEOUT_S = 60.0  # bus-demo: batas tunggu kamera siap
# kunci config -> argumen CLI demo
PRESENCE_ARGS = (
    ("dwell_s", "--dwell-s"),
    ("leave_s", "--leave-s"),
    ("fps_busy", "--fps-busy"),
)
SIGNAL_ARGS = {  # vision.presence_signal -> ambangnya
    "box_height": ("min_box_height_ratio", "--min-ratio"),
    "shoulder_width": ("min_shoulder_ratio", "--min-shoulder-ratio"),
}
PRESENCE_SIGNALS = tuple(SIGNAL_ARGS)
COLOR_ARGS = (("color.min_majority", "--min-majority"),)
BOX_ARGS = (
    ("box_upper.top", "--box-top"),
    ("box_upper.bottom", "--box-bottom"),
    ("box_upper.side", "--box-side"),
)
KP_ARGS = (
    ("keypoint_torso.min_kp_conf", "--kp-conf"),
    ("keypoint_torso.shrink", "--kp-shrink"),
    ("keypoint_torso.torso_aspect", "--torso-aspect"),
)
# Tabel nama warna van de Weijer dkk. 2009 [30]; sha256 tar diukur saat unduhan pertama
# (16 Okt 2026). Halaman sumber tidak mencantumkan lisensi, jadi tabel tidak di-commit.
COLORS_URL = "https://lear.inrialpes.fr/people/vandeweijer/code/ColorNaming.tar"
COLORS_TAR_SHA256 = "4abad5c8ad4b4d2adf44a4b47cd7d6d3c97f453183e4258f26dd162e566d878a"
COLORS_MEMBER = "ColorNaming/w2c.txt"


def _add_value_args(p: argparse.ArgumentParser) -> None:
    """Argumen nilai coba yang menimpa kunci vision.* (dipakai demo dan bus-demo)."""
    p.add_argument("--dwell-s", type=float, help="menimpa vision.dwell_s")
    p.add_argument("--leave-s", type=float, help="menimpa vision.leave_s")
    p.add_argument(
        "--presence-signal", choices=PRESENCE_SIGNALS, help="menimpa vision.presence_signal"
    )
    p.add_argument("--min-ratio", type=float, help="menimpa vision.min_box_height_ratio")
    p.add_argument("--min-shoulder-ratio", type=float, help="menimpa vision.min_shoulder_ratio")
    p.add_argument("--fps-busy", type=float, help="menimpa vision.fps_busy")
    p.add_argument("--min-majority", type=float, help="menimpa vision.color.min_majority")
    p.add_argument("--box-top", type=float, help="menimpa vision.box_upper.top")
    p.add_argument("--box-bottom", type=float, help="menimpa vision.box_upper.bottom")
    p.add_argument("--box-side", type=float, help="menimpa vision.box_upper.side")
    p.add_argument("--kp-conf", type=float, help="menimpa vision.keypoint_torso.min_kp_conf")
    p.add_argument("--kp-shrink", type=float, help="menimpa vision.keypoint_torso.shrink")
    p.add_argument("--torso-aspect", type=float, help="menimpa vision.keypoint_torso.torso_aspect")


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
    _add_value_args(demo)
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

    bus = sub.add_parser(
        "bus-demo", help="vision worker di proses anak lewat bus M-13, cetak pesan (dev saja)"
    )
    bus.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    bus.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    bus.add_argument("--camera", type=int, default=0)
    bus.add_argument(
        "--seconds", type=float, default=30.0, help="berhenti N detik setelah skenario mulai"
    )
    bus.add_argument(
        "--kill-after",
        type=float,
        help="bunuh proses vision sekali N detik setelah skenario mulai (uji 8.1)",
    )
    bus.add_argument(
        "--preview", action="store_true", help="jendela pratinjau di proses kamera (dev saja)"
    )
    bus.add_argument(
        "--prompt",
        type=_prompt,
        action="append",
        default=[],
        metavar="DETIK:TEKS",
        help="aba-aba di jendela pratinjau mulai detik ke-N skenario (boleh berulang)",
    )
    bus.add_argument(
        "--countdown",
        type=float,
        default=5.0,
        help="hitung mundur N detik di jendela pratinjau setelah kamera siap",
    )
    _add_value_args(bus)
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


def presence_pairs(signal: str) -> tuple[tuple[str, str], ...]:
    return PRESENCE_ARGS[:2] + (SIGNAL_ARGS[signal],) + PRESENCE_ARGS[2:]


def resolve_presence_values(
    vision: VisionConfig, args: argparse.Namespace, signal: str = "box_height"
) -> tuple[dict[str, float], dict[str, str]]:
    return resolve_values(vision, args, presence_pairs(signal))


def resolve_signal(vision: VisionConfig, args: argparse.Namespace) -> tuple[str, str]:
    """(sinyal kehadiran, sumber); null tanpa argumen -> DemoError."""
    if args.presence_signal is not None:
        signal, source = args.presence_signal, "argumen CLI"
    elif vision.presence_signal is not None:
        signal, source = vision.presence_signal, "config"
    else:
        raise DemoError("argumen kurang: --presence-signal (vision.presence_signal null, TBD)")
    if signal == "shoulder_width" and not vision.model.endswith("-pose"):
        raise DemoError(f"presence_signal shoulder_width butuh model -pose, bukan {vision.model}")
    return signal, source


def demo_value_pairs(vision: VisionConfig, signal: str) -> tuple[tuple[str, str], ...]:
    # BoxUpperRegion juga cadangan KeypointTorsoRegion, jadi fraksinya selalu dibutuhkan
    if vision.region == "keypoint_torso":
        keypoint = KP_ARGS
    elif signal == "shoulder_width":
        keypoint = KP_ARGS[:1]  # min_kp_conf untuk bahu
    else:
        keypoint = ()
    return presence_pairs(signal) + COLOR_ARGS + BOX_ARGS + keypoint


@dataclass(frozen=True)
class TrackObs:
    """Satu track pada satu deteksi (diagnosis E-07; tidak memuat piksel)."""

    t: float
    track_id: int
    conf: float
    height: float  # tinggi box / tinggi frame
    shoulder: float | None  # lebar bahu / lebar frame tanpa syarat confidence
    l_conf: float | None
    r_conf: float | None
    signal: float | None  # nilai sinyal kehadiran yang dipakai (None = tidak terukur)
    eligible: bool
    carried: bool  # memenuhi syarat karena carry-over
    target: bool


def observe_tracks(
    t: float,
    now: float,
    tracks: list[PersonTrack],
    frame_shape: tuple[int, ...],
    presence: PresenceTracker,
    target: PersonTrack | None,
) -> list[TrackObs]:
    """Dipanggil sebelum presence.update: carry-over dinilai dari state update sebelumnya.

    t = detik sejak demo mulai (untuk laporan); now = jam monotonic yang sama dengan PresenceTracker.
    """
    eligible = presence.eligible_tracks(tracks, frame_shape, now)
    out = []
    for tr in tracks:
        kp = tr.keypoints
        l_conf = float(kp[L_SHOULDER][2]) if kp is not None else None
        r_conf = float(kp[R_SHOULDER][2]) if kp is not None else None
        value = presence.signal.value(tr, frame_shape)
        out.append(
            TrackObs(
                t=t,
                track_id=tr.track_id,
                conf=tr.conf,
                height=tr.height_ratio(frame_shape[0]),
                shoulder=shoulder_width_ratio(tr, frame_shape[1], 0.0),
                l_conf=l_conf,
                r_conf=r_conf,
                signal=value,
                eligible=tr.track_id in eligible,
                carried=value is None and tr.track_id in eligible,
                target=target is not None and tr.track_id == target.track_id,
            )
        )
    return out


def _fmt(v: float | None) -> str:
    return "-" if v is None else f"{v:.3f}"


def _obs_line(o: TrackObs) -> str:
    flags = [f for f, on in (("syarat", o.eligible), ("carry-over", o.carried),
                             ("target", o.target)) if on]  # fmt: skip
    return (
        f"    track {o.track_id}: conf {o.conf:.2f} | tinggi {o.height:.3f} | bahu {_fmt(o.shoulder)}"
        f" (conf L {_fmt(o.l_conf)} R {_fmt(o.r_conf)}) | sinyal {_fmt(o.signal)}"
        + (f" | {', '.join(flags)}" if flags else "")
    )


def track_table(observations: list[TrackObs]) -> list[str]:
    """Ringkasan per track untuk laporan."""

    def span(values: list[float]) -> str:
        return f"{min(values):.3f}-{max(values):.3f}" if values else "-"

    lines = [
        (
            "| track | muncul-terakhir (s) | n | conf deteksi | tinggi | bahu | conf bahu min L/R "
            "| syarat | carry-over | target |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for tid in sorted({o.track_id for o in observations}):
        rows = [o for o in observations if o.track_id == tid]
        lc = [o.l_conf for o in rows if o.l_conf is not None]
        rc = [o.r_conf for o in rows if o.r_conf is not None]
        kp = f"{min(lc):.2f}/{min(rc):.2f}" if lc and rc else "-"
        lines.append(
            f"| {tid} | {rows[0].t:.1f}-{rows[-1].t:.1f} | {len(rows)} "
            f"| {span([o.conf for o in rows])} | {span([o.height for o in rows])} "
            f"| {span([o.shoulder for o in rows if o.shoulder is not None])} | {kp} "
            f"| {sum(o.eligible for o in rows)} | {sum(o.carried for o in rows)} "
            f"| {sum(o.target for o in rows)} |"
        )
    return lines


@dataclass
class DemoStats:
    frames: int = 0  # frame yang dideteksi
    shown: int = 0  # frame kamera yang dibaca dan ditampilkan
    seconds: float = 0.0
    infer_s: float = 0.0
    events: list[tuple[float, VisionEvent]] = field(default_factory=list)
    id_switches: list[tuple[float, int | None, int]] = field(default_factory=list)
    color_majorities: list[float] = field(default_factory=list)  # per deteksi dengan target
    color_total: np.ndarray = field(default_factory=lambda: np.zeros(len(COLOR_NAMES)))
    region_sources: dict[str, int] = field(default_factory=dict)
    shoulder_ratios: list[tuple[float, float]] = field(default_factory=list)  # (detik, rasio)
    height_ratios: list[tuple[float, float]] = field(default_factory=list)
    track_obs: list[TrackObs] = field(default_factory=list)

    @property
    def fps(self) -> float:
        """Laju deteksi."""
        return self.frames / self.seconds if self.seconds > 0 else 0.0

    @property
    def display_fps(self) -> float:
        return self.shown / self.seconds if self.seconds > 0 else 0.0


def _wall() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _describe(event: VisionEvent) -> str:
    if isinstance(event, PersonArrived):
        conf = "-" if event.color_confidence is None else f"{event.color_confidence:.2f}"
        return f"PersonArrived track={event.track_id} warna={event.color} ({conf})"
    if isinstance(event, PersonLeft):
        return f"PersonLeft track={event.track_id} durasi={event.duration_s:.1f}s"
    if isinstance(event, CameraStatus):
        fps = "" if event.fps is None else f" fps={event.fps:.2f}"
        return f"CameraStatus ok={event.ok} ({event.message}){fps}"
    return repr(event)


def _span(values: list[float]) -> str:
    return f"{values[-1]:.3f} (rentang {min(values):.3f}-{max(values):.3f})" if values else "-"


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
    kp_conf: float | None = None,
    draw: Callable[..., int] = _draw,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    out: Callable[[str], None] = print,
) -> DemoStats:
    """Setiap frame kamera dibaca dan ditampilkan; detektor + PresenceTracker hanya berjalan
    sesuai fps_idle/fps_busy, jadi tracker menerima urutan frame yang dideteksi saja."""
    stats = DemoStats()
    prompts = prompts or []
    shown_prompt: str | None = None
    overlay = Overlay()
    start = clock()
    next_detect = start
    report_at = start + 1.0
    win_heights: list[float] = []  # rasio tinggi box terbesar per deteksi dalam detik ini
    win_shoulders: list[float] = []
    win_frames = win_shown = 0
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
            stats.shown += 1
            win_shown += 1

            if t0 >= next_detect - 1e-6:  # toleransi pembulatan jam
                _detect(frame, t0, elapsed, detector, presence, region, namer, kp_conf,
                        overlay, stats, win_heights, win_shoulders, out)  # fmt: skip
                win_frames += 1
                fps = fps_busy if presence.state == PresenceState.ENGAGED else fps_idle
                # jaga irama tetap (tidak bergeser ke frame kamera berikutnya); bila tertinggal,
                # mulai lagi dari sekarang
                next_detect = max(next_detect + 1.0 / fps, t0)

            if show_window:
                now = clock()
                stats.seconds = now - start
                lines = _prompt_lines(prompts, elapsed, seconds)
                key = draw(frame, overlay, stats.display_fps, stats.fps, lines, kp_conf)
                if key == ord("q"):
                    break
            del frame  # N-08: frame hanya di memori

            now = clock()
            stats.seconds = now - start
            if now >= report_at:
                colors = ""
                if overlay.color is not None and overlay.color.pixels:
                    top3 = ", ".join(f"{n} {v:.2f}" for n, v in overlay.color.ranked(3))
                    colors = f" | warna: {top3} [{overlay.region_source}]"
                out(
                    f"[{now - start:6.2f}s] tinggi box {_span(win_heights)} | "
                    f"lebar bahu {_span(win_shoulders)} | {overlay.state} | "
                    f"tampilan {win_shown} / deteksi {win_frames} frame{colors}"
                )
                for obs in overlay.observations:  # semua track pada deteksi terakhir
                    out(_obs_line(obs))
                win_heights, win_shoulders, win_frames, win_shown = [], [], 0, 0
                report_at = now + 1.0
    finally:
        camera.release()
        if show_window:
            import cv2

            cv2.destroyAllWindows()
    stats.seconds = clock() - start
    return stats


def _detect(
    frame: np.ndarray,
    t0: float,
    elapsed: float,
    detector: PersonDetector,
    presence: PresenceTracker,
    region: ClothingRegion | None,
    namer: ColorNamer | None,
    kp_conf: float | None,
    overlay: Overlay,
    stats: DemoStats,
    win_heights: list[float],
    win_shoulders: list[float],
    out: Callable[[str], None],
) -> None:
    t_infer = time.perf_counter()
    tracks = detector.detect_and_track(frame)
    stats.infer_s += time.perf_counter() - t_infer
    stats.frames += 1
    frame_h, frame_w = frame.shape[:2]

    # warna area pakaian target; piksel hanya di memori (N-08)
    target = presence.target_for(tracks, frame.shape, t0)
    frame_color: ColorResult | None = None
    located = None
    if target is not None and region is not None and namer is not None:
        located = region.locate(frame.shape, target)
        if located is not None:
            (x1, y1, x2, y2), source = located
            stats.region_sources[source] = stats.region_sources.get(source, 0) + 1
            frame_color = namer.name(frame[y1:y2, x1:x2])
            if frame_color.pixels:
                stats.color_majorities.append(frame_color.majority)
                stats.color_total += np.asarray(frame_color.distribution)
        else:
            stats.region_sources["none"] = stats.region_sources.get("none", 0) + 1

    observations = observe_tracks(elapsed, t0, tracks, frame.shape, presence, target)
    stats.track_obs.extend(observations)
    before = presence.track_id
    was_engaged = presence.state == PresenceState.ENGAGED
    for event in presence.update(tracks, frame.shape, t0, color_of=lambda t, c=frame_color: c):
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

    if tracks:
        tallest = max(tracks, key=lambda t: t.height)
        win_heights.append(tallest.height_ratio(frame_h))
        stats.height_ratios.append((elapsed, win_heights[-1]))
        if kp_conf is not None:
            ratio = shoulder_width_ratio(tallest, frame_w, kp_conf)
            if ratio is not None:  # hanya dicatat; kandidat syarat kehadiran E-07
                win_shoulders.append(ratio)
                stats.shoulder_ratios.append((elapsed, ratio))

    overlay.tracks = tracks
    overlay.state = presence.state
    overlay.target = target.track_id if target is not None else None
    overlay.region_rect = located[0] if located is not None else None
    overlay.region_source = located[1] if located is not None else None
    overlay.color = frame_color
    overlay.observations = observations


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
        cv2.imshow(WINDOW, frame)
        del frame  # N-08
        cv2.waitKey(1)


def _make_detector(settings: Settings, path: Path) -> PersonDetector:
    v = settings.vision
    return UltralyticsDetector(path, v.tracker, v.conf, v.imgsz)


def _summary_by_prompt(
    series: list[tuple[float, float]], prompts: list[tuple[float, str]]
) -> list[str]:
    """Rentang nilai per instruksi (untuk membandingkan kondisi uji)."""
    lines = []
    marks = sorted(prompts) or [(0.0, "seluruh run")]
    for i, (at, text) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else float("inf")
        values = [v for t, v in series if at <= t < end]
        if values:
            lines.append(
                f"    {text} ({at:.0f}-{'' if end == float('inf') else f'{end:.0f}'} s): "
                f"{min(values):.3f}-{max(values):.3f}, median {float(np.median(values)):.3f}, "
                f"n={len(values)}"
            )
        else:
            lines.append(f"    {text}: tidak ada data")
    return lines


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
    signal, signal_source = resolve_signal(vision, args)
    values, sources = resolve_values(vision, args, demo_value_pairs(vision, signal))
    path = model_path(vision.model, args.models_dir)
    colors_path = Path(args.models_dir) / DEFAULT_COLORS_FILE.name
    namer = make_color_namer(vision.color.method, colors_path, values["color.min_majority"])
    region = make_region(vision.region, values)
    kp_conf = values.get("keypoint_torso.min_kp_conf")
    detector = detector_factory(settings, path)

    sha = sha256_file(path) if path.is_file() else "(file tidak ada)"
    print(f"model {vision.model}: {path.as_posix()} sha256 {sha}")
    print(
        f"tracker {vision.tracker} | perangkat {DEVICE} | conf {vision.conf} | imgsz {vision.imgsz}"
    )
    if colors_path.is_file():
        print(f"tabel warna: {colors_path.as_posix()} sha256 {sha256_file(colors_path)}")
    print(f"area pakaian {vision.region} | metode warna {vision.color.method}")
    if "argumen CLI" in [*sources.values(), signal_source]:
        print("SUMBER NILAI: argumen CLI (uji coba, nilai coba, bukan E-07/E-08)")
    print(f"  presence_signal = {signal} ({signal_source})")
    for key, _flag in demo_value_pairs(vision, signal):
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
        min_signal=values[SIGNAL_ARGS[signal][0]],
        signal=make_signal(signal, values),
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
        kp_conf=kp_conf,
        clock=clock,
        sleep=sleep,
    )
    infer_ms = stats.infer_s / stats.frames * 1000 if stats.frames else 0.0
    print(
        f"selesai: {stats.seconds:.1f} s | tampilan {stats.shown} frame ({stats.display_fps:.2f} FPS)"
        f" | deteksi {stats.frames} frame ({stats.fps:.2f} FPS) | inferensi rata-rata "
        f"{infer_ms:.1f} ms/frame"
    )
    kinds = [_describe(e) for _, e in stats.events if not isinstance(e, CameraStatus)]
    print(f"event: {len(kinds)} ({'; '.join(kinds) or 'tidak ada'})")
    print(f"ID switch: {len(stats.id_switches)}")
    if stats.region_sources:
        print("sumber area pakaian per deteksi: " + ", ".join(
            f"{k} {v}" for k, v in sorted(stats.region_sources.items())))  # fmt: skip
    if stats.color_majorities:
        m = np.asarray(stats.color_majorities)
        share = stats.color_total / stats.color_total.sum()
        top3 = ", ".join(f"{COLOR_NAMES[i]} {share[i]:.2f}" for i in np.argsort(share)[::-1][:3])
        print(
            f"warna per deteksi ({m.size} frame dengan target): proporsi terbanyak "
            f"min {m.min():.2f} | median {np.median(m):.2f} | maks {m.max():.2f}; "
            f"distribusi rata-rata: {top3}"
        )
    if stats.track_obs:
        print("per track (semua deteksi):")
        for line in track_table(stats.track_obs):
            print(line)
    print("rasio tinggi box terbesar per instruksi:")
    for line in _summary_by_prompt(stats.height_ratios, args.prompt):
        print(line)
    if kp_conf is not None:
        print("rasio lebar bahu / lebar frame per instruksi (hanya dicatat, kandidat E-07):")
        for line in _summary_by_prompt(stats.shoulder_ratios, args.prompt):
            print(line)
    return 0


# --- bus-demo ---------------------------------------------------------------------------


def _rss_mb(pid: int | None = None) -> float | None:
    """RSS proses dalam MB bila psutil tersedia (terpasang bersama Ultralytics); selain itu None."""
    try:
        import psutil

        return psutil.Process(pid).memory_info().rss / 2**20
    except Exception:  # noqa: BLE001 - pengukuran opsional, tidak boleh menggagalkan demo
        return None


def cmd_bus_demo(
    args: argparse.Namespace,
    settings: Settings,
    camera_factory: str | None = None,
    detector_factory: str | None = None,
    factory_options: dict[str, Any] | None = None,
    poll_interval_s: float = 0.05,  # SDD 3.3: QTimer 50 ms
) -> int:
    """Vision worker di proses anak; proses utama hanya mencetak pesan bus (tanpa jendela).
    Meniru M-09 untuk laju: PersonArrived -> SetVisionRate(fps_busy), PersonLeft -> fps_idle."""
    import logging

    from mica.core.bus import SetVisionRate, start_workers
    from mica.vision.worker import VisionWorkerConfig

    _require_dev(settings, "bus-demo")
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
    vision = settings.vision
    signal, signal_source = resolve_signal(vision, args)
    values, sources = resolve_values(vision, args, demo_value_pairs(vision, signal))
    if "argumen CLI" in [*sources.values(), signal_source]:
        print("SUMBER NILAI: argumen CLI (uji coba, nilai coba, bukan E-07/E-08)")
    print(f"  presence_signal = {signal} ({signal_source})")
    for key, _flag in demo_value_pairs(vision, signal):
        print(f"  {key} = {values[key]} ({sources[key]})")
    print(f"  fps_idle = {vision.fps_idle} (config)")
    overrides: dict[str, float | str] = {"presence_signal": signal}
    overrides.update({k: v for k, v in values.items() if k != "fps_busy"})
    cfg = VisionWorkerConfig.from_settings(
        settings,
        overrides,
        models_dir=args.models_dir,
        camera_source=args.camera,
        camera_factory=camera_factory,
        detector_factory=detector_factory,
        factory_options=factory_options,
        preview=args.preview,
        prompts=tuple(args.prompt),
        countdown_s=args.countdown,
        preview_seconds=args.seconds,
    )

    # Waktu skenario (--seconds, --kill-after, aba-aba) dihitung sejak kamera siap (CameraStatus
    # ok pertama) ditambah hitung mundur pratinjau; waktu di log relatif terhadap titik itu.
    countdown = args.countdown if args.preview else 0.0
    spawn = time.monotonic()
    bus = start_workers(settings, cfg)
    zero: float | None = None
    reported_pids: set[int] = set()
    killed = False
    counts: dict[str, int] = {}
    rss: tuple[float | None, float | None] = (None, None)

    def elapsed() -> float:
        return time.monotonic() - (zero if zero is not None else spawn)

    try:
        while zero is None or elapsed() < args.seconds:
            if zero is None and time.monotonic() - spawn > START_TIMEOUT_S:
                print(f"kamera tidak siap dalam {START_TIMEOUT_S:.0f} s; berhenti")
                break
            proc = bus.processes["vision"]
            kill_due = args.kill_after is not None and zero is not None
            if kill_due and not killed and elapsed() >= args.kill_after:
                print(
                    f"[{elapsed():6.2f}s {_wall()}] --kill-after: membunuh proses vision "
                    f"pid {proc.pid}"
                )
                proc.kill()
                killed = True
            for msg in bus.poll():
                name = type(msg).__name__
                counts[name] = counts.get(name, 0) + 1
                proc = bus.processes["vision"]
                if isinstance(msg, CameraStatus) and msg.ok and proc.pid not in reported_pids:
                    reported_pids.add(proc.pid)
                    took = time.monotonic() - bus.started_at["vision"]
                    if zero is None:
                        zero = time.monotonic() + countdown
                    print(f"[{elapsed():6.2f}s {_wall()}] {_describe(msg)}")
                    print(f"    start proses kamera pid {proc.pid}: {took:.1f} s (spawn -> ok)")
                    if countdown and len(reported_pids) == 1:
                        print(f"    hitung mundur {countdown:.0f} s; skenario mulai di 0.00s")
                    rss = (_rss_mb(), _rss_mb(proc.pid))
                else:
                    print(f"[{elapsed():6.2f}s {_wall()}] {_describe(msg)}")
                if isinstance(msg, PersonArrived):
                    bus.send("vision", SetVisionRate(values["fps_busy"]))
                    print(f"    -> SetVisionRate({values['fps_busy']})")
                elif isinstance(msg, PersonLeft):
                    bus.send("vision", SetVisionRate(vision.fps_idle))
                    print(f"    -> SetVisionRate({vision.fps_idle})")
            time.sleep(poll_interval_s)
        proc = bus.processes["vision"]
        if proc.is_alive():
            rss = (_rss_mb(), _rss_mb(proc.pid))
    finally:
        bus.stop()
    alive = [p.pid for p in bus.processes.values() if p.is_alive()]
    summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "tidak ada"
    print(f"selesai {args.seconds:.0f} s | pesan: {summary}")
    print(f"restart: {bus.restarts['vision']} | mati permanen: {sorted(bus.dead) or 'tidak'}")
    main_mb, worker_mb = rss
    if main_mb is not None:
        worker = "-" if worker_mb is None else f"{worker_mb:.0f} MB"
        print(f"RAM (RSS): proses utama {main_mb:.0f} MB | proses kamera {worker}")
    print(f"torch di proses utama: {'ya' if 'torch' in sys.modules else 'tidak'}")
    print(f"proses anak tersisa: {alive or 'tidak ada'}")
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
        if args.command == "bus-demo":
            return cmd_bus_demo(args, settings)
        return cmd_demo(args, settings, detector_factory, camera_factory, clock, sleep)
    except (ConfigError, DemoError, ModelMissing, ColorsMissing, WorkerConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
