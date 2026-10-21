"""Pengukuran laju pratinjau kamera (diagnosis patah-patah; dev saja, --measure-preview).

Hanya angka yang direkam; tidak ada frame, JPEG, audio, atau teks (N-08). Tiga bagian:
- VisionMeter (proses kamera): per detik jumlah frame yang dibaca dari kamera, CAP_PROP_FPS dan
  resolusi yang dilaporkan, JPEG pratinjau yang dikirim, waktu baca kamera, waktu deteksi YOLO,
  dan waktu pixelate + encode JPEG per frame.
- AudioMeter (proses suara): selang sintesis Piper dan selang pemutaran per clip, ringkasan per
  Speak (waktu sampai suara pertama, total sintesis), dan setelan thread onnxruntime Piper.
- PreviewMeasurement (proses utama): setiap detik menggabungkan angka pekerja, jumlah frame
  yang dikirim server ke /preview, jumlah frame yang digambar browser (dilaporkan app.js), CPU%
  per proses (utama, vision, suara, edge) dan total mesin, serta status saat itu:
  IDLE, MELAYANI-diam (GREETING/READY tanpa suara), MELAYANI-lain (LISTENING/THINKING tanpa
  suara), TTS-menyusun (Piper sedang sintesis, boleh sambil memutar clip sebelumnya),
  TTS-memutar (memutar, tanpa sintesis).
  Ringkasan ditulis ke results/preview-fps/<timestamp>/summary.json.
- Langkah 49: setiap baris per detik juga ditambahkan ke results/preview-fps/live-<timestamp>.jsonl
  (live_line: angka saja, status kasar IDLE/MELAYANI/TTS-menyusun/TTS-memutar) dan diteruskan ke
  on_row (panel angka UI web, dev saja).

Semua jam memakai time.monotonic (sama di semua proses Windows, seperti K-3 E-09).
"""

from __future__ import annotations

import json
import os
import queue
import statistics
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path("results/preview-fps")
WINDOW_S = 1.0  # satu baris per detik
SAMPLE_S = 0.1  # status sesi dibaca 10x per detik
SUMMARY_NAME = "summary.json"
STATES = ("IDLE", "MELAYANI-diam", "MELAYANI-lain", "TTS-menyusun", "TTS-memutar")
CPU_GROUPS = ("utama", "vision", "suara", "edge", "lain")


class MeasureRefused(Exception):
    pass


def check_allowed(mode: str) -> None:
    if mode != "dev":
        raise MeasureRefused("--measure-preview hanya boleh saat app.mode: dev (ditolak di kiosk)")


def _put(out: Any, record: dict[str, Any]) -> None:
    try:
        out.put_nowait(record)
    except queue.Full:  # pengukuran tidak boleh menahan pekerja
        pass


def _ms(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "median": None, "max": None}
    return {"n": len(values), "median": statistics.median(values), "max": max(values)}


class VisionMeter:
    """Dipanggil dari loop proses kamera; mengirim satu dict angka per detik ke `out`."""

    def __init__(self, out: Any, clock: Callable[[], float] = time.monotonic) -> None:
        self.out = out
        self.clock = clock
        self.start = clock()
        self.frames = 0
        self.previews = 0
        self.read_ms: list[float] = []
        self.detect_ms: list[float] = []
        self.render_ms: list[float] = []
        self.cap_fps: float | None = None
        self.size: tuple[int, int] | None = None

    def camera(self, capture: Any) -> None:
        """CAP_PROP_FPS yang dilaporkan driver (None untuk sumber tanpa get, mis. palsu)."""
        get = getattr(capture, "get", None)
        if get is None or self.cap_fps is not None:
            return
        import cv2

        try:
            self.cap_fps = float(get(cv2.CAP_PROP_FPS))
        except Exception:  # noqa: BLE001 - angka opsional
            self.cap_fps = None

    def frame(self, shape: tuple[int, ...], read_s: float) -> None:
        self.frames += 1
        self.size = (int(shape[1]), int(shape[0]))
        self.read_ms.append(read_s * 1000)

    def detected(self, seconds: float) -> None:
        self.detect_ms.append(seconds * 1000)

    def rendered(self, seconds: float, sent: bool) -> None:
        self.render_ms.append(seconds * 1000)
        self.previews += int(sent)

    def tick(self) -> None:
        now = self.clock()
        if now - self.start < WINDOW_S:
            return
        span = now - self.start
        _put(self.out, {
            "src": "vision", "t0": self.start, "t1": now,
            "capture_fps": self.frames / span, "preview_put_fps": self.previews / span,
            "cap_prop_fps": self.cap_fps,
            "width": self.size[0] if self.size else None,
            "height": self.size[1] if self.size else None,
            "read_ms": _ms(self.read_ms), "detect_ms": _ms(self.detect_ms),
            "render_encode_ms": _ms(self.render_ms),
        })  # fmt: skip
        self.start = now
        self.frames = self.previews = 0
        self.read_ms, self.detect_ms, self.render_ms = [], [], []


def tts_threads(tts: Any) -> dict[str, Any]:
    """Setelan thread onnxruntime sesi Piper (0 = bawaan onnxruntime) + jumlah core mesin."""
    info: dict[str, Any] = {"logical_cores": os.cpu_count()}
    try:
        import psutil

        info["physical_cores"] = psutil.cpu_count(logical=False)
    except Exception:  # noqa: BLE001
        info["physical_cores"] = None
    session = getattr(getattr(tts, "voice", None), "session", None)
    if session is None:
        return info
    try:
        opts = session.get_session_options()
        info.update(intra_op_num_threads=opts.intra_op_num_threads,
                    inter_op_num_threads=opts.inter_op_num_threads,
                    execution_mode=str(opts.execution_mode))  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - pengukuran tidak boleh mematikan proses suara
        info["error"] = repr(exc)
        return info
    try:
        info["allow_spinning"] = opts.get_session_config_entry("session.intra_op.allow_spinning")
    except Exception:  # noqa: BLE001 - kunci tidak diset = bawaan onnxruntime (spinning aktif)
        info["allow_spinning"] = "bawaan"
    return info


class AudioMeter:
    """Dipanggil dari thread kerja proses suara; selang sintesis/putar dan ringkasan Speak."""

    def __init__(self, out: Any, clock: Callable[[], float] = time.monotonic) -> None:
        self.out = out
        self.clock = clock

    def info(self, tts: Any) -> None:
        _put(self.out, {"src": "audio", "kind": "tts_info", **tts_threads(tts)})

    def synth(self, start: float, end: float) -> None:
        _put(self.out, {"src": "audio", "kind": "synth", "t0": start, "t1": end})

    def play(self, start: float, duration_s: float) -> None:
        _put(self.out, {"src": "audio", "kind": "play", "t0": start, "t1": start + duration_s})

    def speak(self, received: float, first_audio_s: float | None, synth_s: list[float],
              audio_s: float, chars: int, interrupted: bool) -> None:  # fmt: skip
        _put(self.out, {"src": "audio", "kind": "speak", "t0": received,
                        "first_audio_s": first_audio_s, "synth_total_s": sum(synth_s),
                        "synth_first_s": synth_s[0] if synth_s else None,
                        "n_clips": len(synth_s), "audio_s": audio_s, "chars": chars,
                        "interrupted": interrupted})  # fmt: skip


def _overlap(intervals: list[tuple[float, float]], t0: float, t1: float) -> float:
    return sum(max(0.0, min(b, t1) - max(a, t0)) for a, b in intervals)


def label_state(session_states: list[str], synth_frac: float, play_frac: float) -> str:
    if synth_frac > 0:
        return "TTS-menyusun"
    if play_frac > 0:
        return "TTS-memutar"
    if session_states and all(s == "IDLE" for s in session_states):
        return "IDLE"
    if session_states and all(s in ("IDLE", "GREETING", "READY") for s in session_states):
        return "MELAYANI-diam"
    return "MELAYANI-lain"


class CpuSampler:
    """CPU% per kelompok proses (persen satu inti) dan total mesin (persen semua core)."""

    def __init__(self, groups: Callable[[], dict[str, list[int]]]) -> None:
        import psutil

        self.psutil = psutil
        self.groups = groups
        self.procs: dict[int, Any] = {}
        self.last: dict[int, tuple[float, float]] = {}
        psutil.cpu_percent(None)

    def _cpu(self, pid: int, now: float) -> float | None:
        try:
            proc = self.procs.get(pid) or self.psutil.Process(pid)
            self.procs[pid] = proc
            t = proc.cpu_times()
        except (self.psutil.NoSuchProcess, self.psutil.AccessDenied):
            return None
        used = t.user + t.system
        prev = self.last.get(pid)
        self.last[pid] = (used, now)
        if prev is None or now <= prev[1]:
            return None
        return 100.0 * (used - prev[0]) / (now - prev[1])

    def sample(self) -> dict[str, float | None]:
        now = time.monotonic()
        out: dict[str, float | None] = {}
        for group, pids in self.groups().items():
            values = [v for v in (self._cpu(p, now) for p in pids) if v is not None]
            out[group] = sum(values) if values else None
        out["total_machine"] = self.psutil.cpu_percent(None)
        return out


class PreviewMeasurement:
    """Thread latar di proses utama; summary.json ditulis ulang setiap 10 detik dan saat stop."""

    def __init__(
        self,
        folder: Path,
        source: Any,
        sent: Callable[[], int],
        drawn: Callable[[], int],
        session_state: Callable[[], str | None],
        cpu: Callable[[], dict[str, float | None]] | None,
        info: dict[str, Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        live_path: Path | None = None,
        on_row: Callable[[dict[str, Any]], None] | None = None,
        gaps: Callable[[], list[float]] | None = None,
        extra: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        # Langkah 50: jeda antar gambar di browser (ms, dilaporkan app.js per gambar) dan info
        # tambahan per detik (fase uji terpandu, penanda alur dari ViewModel; tanpa teks)
        self.gaps = gaps
        self.extra = extra
        self.folder = Path(folder)
        self.live_path = Path(live_path) if live_path is not None else None
        self.on_row = on_row
        self.source = source  # antrean pengukuran dari pekerja (Bus.measure), boleh None
        self.sent = sent
        self.drawn = drawn
        self.session_state = session_state
        self.cpu = cpu
        self.info = dict(info or {})
        self.clock = clock
        self.rows: list[dict[str, Any]] = []
        self.vision: list[dict[str, Any]] = []
        self.synth: list[tuple[float, float]] = []
        self.play: list[tuple[float, float]] = []
        self.speaks: list[dict[str, Any]] = []
        self.tts_info: dict[str, Any] | None = None
        self.states: list[str] = []
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.started_at = datetime.now().astimezone()
        self.t0 = clock()
        self.window_start = self.t0
        self.last_sent = 0
        self.last_drawn = 0

    @classmethod
    def new_folder(cls, root: Path = DEFAULT_ROOT) -> Path:
        return Path(root) / datetime.now().strftime("%Y%m%d-%H%M%S")

    @staticmethod
    def live_file(folder: Path) -> Path:
        """results/preview-fps/<ts>/ -> results/preview-fps/live-<ts>.jsonl"""
        folder = Path(folder)
        return folder.parent / f"live-{folder.name}.jsonl"

    def emit(self, row: dict[str, Any]) -> None:
        line = live_line(row, self.started_at.timestamp() + row["t"])
        if self.live_path is not None:
            self.live_path.parent.mkdir(parents=True, exist_ok=True)
            with self.live_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        if self.on_row is not None:
            try:
                self.on_row(line)
            except Exception:  # noqa: BLE001, S110 - panel UI tidak boleh menghentikan pengukuran
                pass

    def drain(self) -> None:
        while self.source is not None:
            try:
                rec = self.source.get_nowait()
            except queue.Empty:
                return
            except (EOFError, OSError, ValueError):
                self.source = None
                return
            self.receive(rec)

    def receive(self, rec: dict[str, Any]) -> None:
        if rec.get("src") == "vision":
            self.vision.append(rec)
        elif rec.get("kind") == "synth":
            self.synth.append((rec["t0"], rec["t1"]))
        elif rec.get("kind") == "play":
            self.play.append((rec["t0"], rec["t1"]))
        elif rec.get("kind") == "speak":
            self.speaks.append({k: v for k, v in rec.items() if k != "src"})
        elif rec.get("kind") == "tts_info":
            self.tts_info = {k: v for k, v in rec.items() if k not in ("src", "kind")}

    def sample_state(self) -> None:
        state = self.session_state()
        if state is not None:
            self.states.append(str(state))

    def close_window(self, now: float) -> dict[str, Any]:
        """Satu baris untuk [window_start, now): pekerja vision dicocokkan menurut irisan waktu."""
        t0, span = self.window_start, max(now - self.window_start, 1e-9)
        sent, drawn = self.sent(), self.drawn()
        vis = [v for v in self.vision if v["t1"] > t0 and v["t0"] < now]
        synth_frac = _overlap(self.synth, t0, now) / span
        play_frac = _overlap(self.play, t0, now) / span
        row: dict[str, Any] = {
            "t": round(t0 - self.t0, 3),
            "state": label_state(self.states, synth_frac, play_frac),
            "session_states": sorted(set(self.states)),
            "synth_frac": round(synth_frac, 3), "play_frac": round(play_frac, 3),
            "server_sent_fps": (sent - self.last_sent) / span,
            "browser_drawn_fps": (drawn - self.last_drawn) / span,
        }  # fmt: skip
        if vis:
            v = vis[-1]
            row.update(capture_fps=v["capture_fps"], preview_put_fps=v["preview_put_fps"],
                       cap_prop_fps=v["cap_prop_fps"], width=v["width"], height=v["height"],
                       read_ms=v["read_ms"], detect_ms=v["detect_ms"],
                       render_encode_ms=v["render_encode_ms"])  # fmt: skip
        if self.cpu is not None:
            row["cpu_pct"] = self.cpu()
        if self.gaps is not None:
            gaps = [round(g) for g in self.gaps()]
            row["browser_gaps_ms"] = gaps
            row["browser_gap_max_ms"] = max(gaps) if gaps else None
        if self.extra is not None:
            row.update(self.extra())
        self.last_sent, self.last_drawn = sent, drawn
        self.window_start, self.states = now, []
        self.vision = [v for v in self.vision if v["t1"] > now]
        return row

    def step(self) -> None:
        self.drain()
        self.sample_state()
        now = self.clock()
        if now - self.window_start >= WINDOW_S:
            with self.lock:
                row = self.close_window(now)
                self.rows.append(row)
            self.emit(row)

    def _loop(self) -> None:
        next_write = self.clock() + 10.0
        while not self.stop_event.wait(SAMPLE_S):
            self.step()
            if self.clock() >= next_write:
                self.write()
                next_write = self.clock() + 10.0

    def start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.thread = threading.Thread(target=self._loop, name="mica-preview-meter", daemon=True)
        self.thread.start()

    def stop(self) -> Path:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(5.0)
        self.drain()
        return self.write()

    def summary(self) -> dict[str, Any]:
        with self.lock:
            rows = list(self.rows)
        by_state: dict[str, Any] = {}
        for state in STATES:
            sel = [r for r in rows if r["state"] == state]
            if sel:
                by_state[state] = aggregate(sel)
        return {
            "tool": "mica.eval.preview_meter (--measure-preview)",
            "content": "hanya angka; tanpa frame, JPEG, audio, atau teks (N-08)",
            "started_at": self.started_at.isoformat(),
            "seconds": len(rows),
            "definitions": {
                "capture_fps": "frame yang dibaca loop proses kamera dari cv2 per detik",
                "preview_put_fps": "JPEG pratinjau yang masuk antrean pratinjau per detik",
                "server_sent_fps": "JPEG yang dikirim server ke WebSocket /preview per detik",
                "browser_drawn_fps": "event load <img> pratinjau di browser per detik",
                "render_encode_ms": "pixelate + overlay + encode JPEG per frame pratinjau",
                "cpu_pct": "per kelompok: persen satu inti; total_machine: persen semua core",
                "state": list(STATES),
            },
            **self.info,
            "tts_threads": self.tts_info,
            "by_state": by_state,
            "tts_speaks": list(self.speaks),
            "rows": rows,
        }

    def write(self) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / SUMMARY_NAME
        path.write_text(json.dumps(self.summary(), ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")  # fmt: skip
        return path


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "min": None, "max": None}
    return {"median": round(statistics.median(values), 2), "min": round(min(values), 2),
            "max": round(max(values), 2)}  # fmt: skip


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Median/min/max per detik untuk satu status."""

    def col(key: str) -> list[float]:
        return [r[key] for r in rows if r.get(key) is not None]

    def ms(key: str, part: str) -> list[float]:
        return [r[key][part] for r in rows if r.get(key) and r[key].get(part) is not None]

    out: dict[str, Any] = {"n_seconds": len(rows)}
    for key in ("capture_fps", "preview_put_fps", "server_sent_fps", "browser_drawn_fps"):
        out[key] = _stats(col(key))
    for key in ("read_ms", "detect_ms", "render_encode_ms"):
        out[key] = {"median_of_median": _stats(ms(key, "median"))["median"],
                    "max": _stats(ms(key, "max"))["max"]}  # fmt: skip
    cpus = [r["cpu_pct"] for r in rows if r.get("cpu_pct")]
    out["cpu_pct"] = {g: _stats([c[g] for c in cpus if c.get(g) is not None])
                      for g in (*CPU_GROUPS, "total_machine")}  # fmt: skip
    out["cap_prop_fps"] = sorted({r["cap_prop_fps"] for r in rows if r.get("cap_prop_fps")})
    out["resolution"] = sorted({f"{r['width']}x{r['height']}" for r in rows if r.get("width")})
    return out


def coarse_state(state: str) -> str:
    """Status kasar Langkah 49: MELAYANI-diam dan MELAYANI-lain -> MELAYANI."""
    return "MELAYANI" if state.startswith("MELAYANI") else state


def live_line(row: dict[str, Any], wall_ts: float) -> dict[str, Any]:
    """Satu baris live-*.jsonl / panel: angka saja, dibulatkan."""

    def r(value: Any, nd: int = 1) -> Any:
        return None if value is None else round(float(value), nd)

    def med(key: str) -> Any:
        part = row.get(key) or {}
        return r(part.get("median"))

    cpu = row.get("cpu_pct") or {}
    return {
        "ts": datetime.fromtimestamp(wall_ts).astimezone().isoformat(timespec="seconds"),
        "t": r(row["t"]),
        "status": coarse_state(row["state"]),
        "state_detail": row["state"],
        "capture_fps": r(row.get("capture_fps")),
        "preview_put_fps": r(row.get("preview_put_fps")),
        "server_sent_fps": r(row.get("server_sent_fps")),
        "browser_drawn_fps": r(row.get("browser_drawn_fps")),
        "cpu_pct": {g: r(cpu.get(g)) for g in ("utama", "vision", "suara", "edge",
                                                "total_machine")},
        "read_ms": med("read_ms"),
        "detect_ms": med("detect_ms"),
        "render_encode_ms": med("render_encode_ms"),
        "synth_frac": row.get("synth_frac"),
        "play_frac": row.get("play_frac"),
        "browser_gap_max_ms": row.get("browser_gap_max_ms"),
        "browser_gaps_ms": row.get("browser_gaps_ms"),
        "phase": row.get("phase"),
        "view": row.get("view"),
    }  # fmt: skip
