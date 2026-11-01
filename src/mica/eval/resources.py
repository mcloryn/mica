"""Perekam sumber daya untuk E-09 (docs/E-09.md): RAM USS dan CPU per kelompok proses.

Setiap `interval_s` detik (bawaan 5, nilai coba) thread latar membaca, dengan psutil, setiap
proses di kelompok:
- utama: proses MICA (server, controller, pipeline);
- vision, suara: proses pekerja dari bus beserta turunannya;
- edge: proses browser Edge beserta semua turunannya (renderer, gpu, utility, ...);
- lain: turunan proses utama yang tidak masuk kelompok di atas.
Satu baris CSV per kelompok per sampel: ts, elapsed_s, group, n_processes, cpu_pct (persen satu
inti, dari selisih cpu_times sejak sampel sebelumnya), uss_mb. Tidak ada isi lain yang direkam:
tanpa command line, nama jendela, gambar, atau audio (N-08).

Hanya boleh di app.mode dev, kecuali E-09 dengan flag eksplisit --e09 (dicatat di run.json).
"""

from __future__ import annotations

import csv
import json
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_INTERVAL_S = 5.0  # nilai coba (docs/E-09.md)
GROUPS = ("utama", "vision", "suara", "edge", "lain")
FIELDS = ("ts", "elapsed_s", "group", "n_processes", "cpu_pct", "uss_mb")
CSV_NAME = "resources.csv"


class RecorderRefused(Exception):
    pass


def check_allowed(mode: str, e09: bool) -> None:
    if mode != "dev" and not e09:
        raise RecorderRefused(
            "--record-resources hanya untuk app.mode: dev; di prod hanya untuk E-09 dengan --e09"
        )


def _now() -> datetime:
    return datetime.now().astimezone()


def _tree(pid: int) -> list[Any]:
    import psutil

    try:
        root = psutil.Process(pid)
        return [root, *root.children(recursive=True)]
    except psutil.NoSuchProcess:
        return []


def pid_groups(main_pid: int, roots: dict[str, int | None]) -> dict[str, list[int]]:
    """{kelompok: pid}. roots: {"vision": pid, "suara": pid, "edge": pid}; None = tidak ada.
    Kelompok selain utama memuat root beserta semua turunannya; sisa turunan utama -> lain."""
    out: dict[str, list[int]] = {g: [] for g in GROUPS}
    out["utama"] = [main_pid]
    taken = {main_pid}
    for group in ("vision", "suara", "edge"):
        pid = roots.get(group)
        if pid is None:
            continue
        pids = [p.pid for p in _tree(pid) if p.pid not in taken]
        out[group] = pids
        taken.update(pids)
    out["lain"] = [p.pid for p in _tree(main_pid) if p.pid not in taken]
    return out


class ResourceRecorder:
    def __init__(
        self,
        folder: Path,
        groups: Callable[[], dict[str, list[int]]],
        interval_s: float = DEFAULT_INTERVAL_S,
        info: dict[str, Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = _now,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s harus > 0")
        self.folder = Path(folder)
        self.groups = groups
        self.interval_s = interval_s
        self.info = dict(info or {})
        self.clock = clock
        self.wall_clock = wall_clock
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last: dict[int, tuple[float, float]] = {}  # pid -> (cpu detik, jam)
        self.procs: dict[int, Any] = {}
        self.n_samples = 0
        self.started_at: datetime | None = None
        self.t0 = 0.0

    @property
    def csv_path(self) -> Path:
        return self.folder / CSV_NAME

    def _write_info(self, **extra: Any) -> None:
        data = {
            "tool": "mica.eval.resources (perekam sumber daya E-09)",
            "interval_s": self.interval_s, "groups": list(GROUPS), "fields": list(FIELDS),
            "cpu_definition": "persen satu inti; selisih cpu_times user+system antar-sampel",
            "ram_definition": "USS (psutil memory_full_info)",
            "content": "hanya angka proses (N-08)",
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "n_samples": self.n_samples, **self.info, **extra,
        }  # fmt: skip
        (self.folder / "run.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )

    def _proc(self, pid: int) -> Any:
        import psutil

        proc = self.procs.get(pid)
        if proc is None:
            proc = self.procs[pid] = psutil.Process(pid)
        return proc

    def sample(self) -> list[dict[str, Any]]:
        """Satu sampel semua kelompok (juga dipakai tes). Baris ditambahkan ke CSV."""
        import psutil

        now = self.clock()
        ts = self.wall_clock().isoformat()
        rows = []
        seen: set[int] = set()
        for group, pids in self.groups().items():
            cpu = uss = 0.0
            n = 0
            for pid in pids:
                try:
                    proc = self._proc(pid)
                    t = proc.cpu_times()
                    used = t.user + t.system
                    uss += proc.memory_full_info().uss / 2**20
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    self.procs.pop(pid, None)
                    continue
                n += 1
                seen.add(pid)
                prev = self.last.get(pid)
                if prev is not None and now > prev[1]:
                    cpu += 100.0 * (used - prev[0]) / (now - prev[1])
                self.last[pid] = (used, now)
            rows.append({"ts": ts, "elapsed_s": round(now - self.t0, 3), "group": group,
                         "n_processes": n, "cpu_pct": round(cpu, 3),
                         "uss_mb": round(uss, 3)})  # fmt: skip
        for pid in set(self.last) - seen:  # proses yang sudah berhenti
            self.last.pop(pid, None)
            self.procs.pop(pid, None)
        new = not self.csv_path.exists()
        with self.csv_path.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerows(rows)
        self.n_samples += 1
        return rows

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.sample()
            except Exception:  # noqa: BLE001, S110 - perekam tidak boleh mematikan aplikasi
                pass
            self.stop_event.wait(self.interval_s)

    def start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.started_at = self.wall_clock()
        self.t0 = self.clock()
        self._write_info(pid=os.getpid())
        self.thread = threading.Thread(target=self._loop, name="mica-resources", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=self.interval_s + 5)
        self._write_info(stopped_at=self.wall_clock().isoformat())


def make_recorder(
    folder: Path,
    mode: str,
    e09: bool,
    roots: Callable[[], dict[str, int | None]],
    interval_s: float = DEFAULT_INTERVAL_S,
    info: dict[str, Any] | None = None,
) -> ResourceRecorder:
    """Perekam untuk proses ini; roots dibaca ulang setiap sampel (pekerja bisa di-restart)."""
    check_allowed(mode, e09)
    main = os.getpid()
    return ResourceRecorder(Path(folder), lambda: pid_groups(main, roots()), interval_s,
                            {"app_mode": mode, "e09": e09, **(info or {})})  # fmt: skip


def add_arguments(parser: Any) -> None:
    """Flag bersama untuk python -m mica dan python -m mica.webui."""
    parser.add_argument(
        "--record-resources",
        type=Path,
        metavar="FOLDER",
        help="rekam RAM USS dan CPU per kelompok proses ke FOLDER (dev; E-09)",
    )
    parser.add_argument(
        "--resource-interval",
        type=float,
        default=DEFAULT_INTERVAL_S,
        help=f"interval perekam dalam detik (bawaan {DEFAULT_INTERVAL_S:g}, nilai coba)",
    )
    parser.add_argument("--e09", action="store_true",
                        help="izinkan perekam di app.mode prod untuk E-09 (dicatat di run.json)")  # fmt: skip


def bus_roots(bus: Any, browser: Any = None) -> dict[str, int | None]:
    """roots dari Bus.processes ("vision", "audio") dan EdgeBrowser.pid."""
    procs = getattr(bus, "processes", {}) or {}

    def pid(name: str) -> int | None:
        proc = procs.get(name)
        return getattr(proc, "pid", None) if proc is not None else None

    return {"vision": pid("vision"), "suara": pid("audio"),
            "edge": getattr(browser, "pid", None) if browser is not None else None}  # fmt: skip
