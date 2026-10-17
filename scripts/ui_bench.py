"""Pengukuran percobaan ADR-19 (docs/UI-WEB.md, tahap 1): PySide6 vs UI web.

python scripts/ui_bench.py [--config config/dev.yaml] [--reps 3] [--out results/ADR-19]
                           [--ui both|pyside6|web] [--name ui-bench]
                           [--cover-window] [--edge-switches on|off]

Per UI dan ulangan, proses anak menjalankan UI dengan pekerja palsu + pipeline palsu, lalu:
1. waktu mulai = peluncuran proses anak -> layar pertama digambar (jam dinding kedua proses);
2. diam 60 detik di layar awal: CPU rata-rata (persen satu inti) dan RAM USS seluruh pohon
   proses UI (PySide6: proses anak; web: proses anak + semua proses Edge turunannya);
3. 20 pertanyaan ketik berurutan ("pertanyaan uji N", bukan dari set dev/uji), masing-masing
   ditunggu sampai READY; jeda tampil setiap pembaruan ViewModel:
   - web: server mengirim JSON -> browser membalas setelah requestAnimationFrame berikutnya;
   - PySide6: show_item pertama sejak paint terakhir -> event Paint berikutnya di jendela
     (bench memanggil window.update() supaya setiap pembaruan memicu Paint); event Paint
     diterima sebelum widget selesai digambar, setara dengan requestAnimationFrame;
4. RAM USS lagi setelah 20 pertanyaan.
Hasil: results/ADR-19/<--name>-<cap waktu>/ (per_run.csv, latencies.csv, summary.csv, run.json).
Aturan tahap 1 diterapkan mekanis: LOLOS bila (a) dan (b), dengan (b) = p95 jeda tampil x 3 <= 1,0 s.
Kode aplikasi (mica.ui, mica.webui) tidak diubah untuk pengukuran; kait hanya di skrip ini.

--cover-window (uji Edge berhenti menggambar, Langkah 30 bagian D): setelah layar pertama
tampil, skrip membuka Notepad lewat subprocess, memaksimalkan dan membawanya ke depan, lalu
menjalankan masa diam dan 20 pertanyaan, dan menutup Notepad. Persen luas jendela Edge yang
tertutup Notepad dicatat. --edge-switches off meluncurkan Edge tanpa RENDERING_SWITCHES
(mica.webui.browser) sebagai pembanding.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import queue
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

IDLE_S = 60.0  # protokol: diam 60 detik
N_QUESTIONS = 20  # protokol: 20 pertanyaan ketik
FACTOR = 3.0  # protokol: perkiraan laptop kiosk ~1/3 laptop dev
LIMIT_S = 1.0  # protokol: Nielsen, bukti [52]
QUESTION = "pertanyaan uji {n}"
CHILD_TIMEOUT_S = 180.0  # non-ADR: batas tunggu satu tahap proses anak


def emit(event: str, **data: Any) -> None:
    print(json.dumps({"event": event, "wall": time.time(), **data}), flush=True)


def stdin_commands() -> queue.Queue[str]:
    q: queue.Queue[str] = queue.Queue()

    def read() -> None:
        for line in sys.stdin:
            q.put(line.strip())

    threading.Thread(target=read, daemon=True).start()
    return q


class Driver:
    """Mengirim 20 pertanyaan berurutan: berikutnya setelah jawaban sebelumnya selesai (READY)."""

    def __init__(self, controller: Any, vm: Any) -> None:
        self.controller = controller
        self.vm = vm
        self.asked = 0
        self.active = False
        self.done = False

    def tick(self) -> None:
        from mica.core.session import TextSubmitted, VisitState

        if not self.active or self.done:
            return
        state = self.controller.session.state
        answered = sum(m.role == "mica" for m in self.vm.messages)
        if answered < self.asked or state not in (VisitState.IDLE, VisitState.READY):
            return
        if self.asked == N_QUESTIONS:
            self.done = True
            return
        self.asked += 1
        self.controller.submit(TextSubmitted(QUESTION.format(n=self.asked)))


# --- proses anak: PySide6 ---------------------------------------------------------------


def child_pyside6(config: Path) -> int:
    from PySide6.QtCore import QEvent, QObject, QTimer
    from PySide6.QtWidgets import QApplication

    from mica.config import load_settings
    from mica.ui.app import apply_ui_settings, build

    settings = load_settings(config)
    app = QApplication(sys.argv[:1])
    kiosk = build(settings, fake_workers=True, fake_pipeline=True)
    window, controller = kiosk.window, kiosk.controller
    pending: list[float] = []
    latencies: list[float] = []
    state = {"painted": False, "measure": False}
    original = controller.view

    def view(item: Any) -> None:
        if state["measure"] and not pending:
            pending.append(time.perf_counter())
        original(item)
        window.update()

    controller.view = view

    class PaintWatch(QObject):
        def eventFilter(self, obj: Any, event: Any) -> bool:
            if event.type() == QEvent.Type.Paint and hasattr(obj, "window") and \
                    obj.window() is window:  # fmt: skip
                now = time.perf_counter()
                if not state["painted"]:
                    state["painted"] = True
                    emit("painted")
                if pending:
                    latencies.append(now - pending.pop())
            return False

    watch = PaintWatch()
    app.installEventFilter(watch)
    driver = Driver(controller, window.vm)
    commands = stdin_commands()

    def poll() -> None:
        try:
            cmd = commands.get_nowait()
        except queue.Empty:
            cmd = None
        if cmd == "go":
            state["measure"] = True
            driver.active = True
        elif cmd == "quit":
            window.close()
            app.quit()
            return
        driver.tick()
        if driver.done and driver.active:
            driver.active = False
            emit("done", latencies=latencies, updates=len(latencies), unacked=len(pending))

    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(poll)
    timer.start()
    apply_ui_settings(app, window, settings)
    kiosk.timer.start()
    return app.exec()


# --- proses anak: web -------------------------------------------------------------------


def child_web(config: Path, keep_rendering: bool = True, edge_extra: tuple[str, ...] = ()) -> int:
    from mica.config import load_settings
    from mica.webui.app import build_controller, serve
    from mica.webui.browser import EdgeBrowser
    from mica.webui.server import WebUi

    driver: Driver | None = None

    class BenchWebUi(WebUi):
        def handle_message(self, data: dict[str, Any]) -> None:
            first = self.first_render_at is None
            super().handle_message(data)
            if first and self.first_render_at is not None:
                emit("painted")

        def tick(self) -> None:
            # Driver memanggil controller.submit, jadi harus di thread poll (pemilik controller)
            if driver is not None:
                driver.tick()
            sent["_ticks"] = sent.get("_ticks", 0) + 1
            super().tick()

        def _send(self, ws: Any, payload: dict[str, Any]) -> None:
            sent[payload.get("type", "?")] = sent.get(payload.get("type", "?"), 0) + 1
            super()._send(ws, payload)

    sent: dict[str, int] = {}  # pesan server -> browser per jenis (diagnosis: kirim saat diam?)

    settings = load_settings(config)
    webui = BenchWebUi(settings.ui, dev=True)
    controller = build_controller(settings, webui, fake_workers=True, fake_pipeline=True)

    def popen(cmd: list[str]) -> subprocess.Popen:
        # --edge-extra: switch kandidat disisipkan sebelum --kiosk/URL tanpa mengubah kode aplikasi
        return subprocess.Popen([cmd[0], *edge_extra, *cmd[1:]])

    browser = EdgeBrowser(settings.ui.fullscreen, keep_rendering=keep_rendering, popen=popen)
    commands = stdin_commands()
    driver = Driver(controller, webui.vm)
    stop = threading.Event()
    server = threading.Thread(target=serve, args=(webui, controller, browser),
                              kwargs={"stop": stop, "on_ready": lambda url: emit(
                                  "url", url=url, edge_pid=browser.pid)})  # fmt: skip
    server.start()
    start_index = 0
    while server.is_alive():
        try:
            cmd = commands.get(timeout=0.05)
        except queue.Empty:
            cmd = None
        if cmd == "go":
            with webui.lock:
                start_index = len(webui.ack_latencies_s)
            driver.active = True
        elif cmd == "quit":
            stop.set()
        elif cmd == "stats":
            with webui.lock:
                emit("stats", sent=dict(sent), seq=webui.seq, ticks=sent.get("_ticks", 0))
        if driver.done and driver.active:
            driver.active = False
            # tunggu ack pembaruan terakhir (paling lama 5 s)
            deadline = time.perf_counter() + 5.0
            while webui.sent_at and time.perf_counter() < deadline:
                time.sleep(0.01)
            with webui.lock:
                lat = webui.ack_latencies_s[start_index:]
                unacked = len(webui.sent_at)
            # pembaruan yang tidak pernah di-ack browser (mis. jendela tidak di depan)
            emit("done", latencies=lat, updates=len(lat), unacked=unacked)
    server.join()
    return 0


# --- penutup jendela (--cover-window) ---------------------------------------------------


def _top_windows(pids: set[int]) -> list[int]:
    """HWND jendela tingkat atas yang terlihat dan berjudul milik pids (Windows, ctypes)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd: int, _lparam: int) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        visible = user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0
        if pid.value in pids and visible:
            found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found


def _rect(hwnd: int) -> tuple[int, int, int, int]:
    import ctypes
    from ctypes import wintypes

    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def _overlap_pct(inner: tuple[int, ...], outer: tuple[int, ...]) -> float:
    """Persen luas `outer` (jendela Edge) yang tertutup `inner` (Notepad)."""
    w = max(0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    h = max(0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    area = max(1, (outer[2] - outer[0]) * (outer[3] - outer[1]))
    return 100.0 * w * h / area


class Cover:
    """Notepad dimaksimalkan di depan jendela Edge; ditutup lagi di close()."""

    def __init__(self, ui_root_pid: int) -> None:
        self.ui_root_pid = ui_root_pid
        self.pids: set[int] = set()

    @staticmethod
    def _notepads() -> set[int]:
        import psutil

        out = set()
        for p in psutil.process_iter(["name"]):
            if (p.info["name"] or "").lower() == "notepad.exe":
                out.add(p.pid)
        return out

    def open(self) -> dict[str, Any]:
        import ctypes

        before = self._notepads()
        subprocess.Popen(["notepad.exe"])  # Notepad Windows 11 bisa berpindah proses (stub)
        deadline = time.time() + 15
        hwnds: list[int] = []
        while time.time() < deadline and not hwnds:
            time.sleep(0.2)
            self.pids = self._notepads() - before
            hwnds = _top_windows(self.pids)
        if not hwnds:
            return {"opened": False, "reason": "jendela Notepad baru tidak ditemukan"}
        user32 = ctypes.windll.user32
        hwnd = hwnds[0]
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        user32.SetForegroundWindow(hwnd)
        time.sleep(1.0)
        ui_windows = _top_windows({p.pid for p in tree(self.ui_root_pid)})
        note = _rect(hwnd)
        return {
            "opened": True, "notepad_rect": note,
            "notepad_foreground": user32.GetForegroundWindow() == hwnd,
            "ui_rects": [_rect(w) for w in ui_windows],
            "ui_coverage_pct": [_overlap_pct(note, _rect(w)) for w in ui_windows],
        }  # fmt: skip

    def close(self) -> None:
        import psutil

        for pid in self.pids:
            try:
                psutil.Process(pid).terminate()
            except psutil.NoSuchProcess:
                pass
        self.pids = set()


# --- proses induk -----------------------------------------------------------------------


def tree(pid: int) -> list[Any]:
    import psutil

    root = psutil.Process(pid)
    return [root, *root.children(recursive=True)]


def uss_mb(pid: int) -> tuple[float, int]:
    import psutil

    total, n = 0, 0
    for p in tree(pid):
        try:
            total += p.memory_full_info().uss
            n += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return total / 2**20, n


def cpu_idle_pct(pid: int, seconds: float) -> float:
    """Rata-rata CPU pohon proses selama `seconds` (persen satu inti); proses yang hilang di tengah
    jalan dilewati."""
    import psutil

    def times(procs: list[Any]) -> dict[int, float]:
        out = {}
        for p in procs:
            try:
                t = p.cpu_times()
                out[p.pid] = t.user + t.system
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return out

    procs = tree(pid)
    start, t0 = times(procs), time.perf_counter()
    time.sleep(seconds)
    end, elapsed = times(procs), time.perf_counter() - t0
    used = sum(end[k] - start[k] for k in end if k in start)
    return 100.0 * used / elapsed


def read_event(proc: subprocess.Popen, name: str, timeout_s: float = CHILD_TIMEOUT_S) -> dict:
    deadline = time.time() + timeout_s
    assert proc.stdout is not None
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError(f"proses anak berhenti sebelum '{name}' (kode {proc.poll()})")
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue  # keluaran lain (log library)
        if msg.get("event") == name:
            return msg
    raise TimeoutError(f"tidak ada '{name}' dalam {timeout_s} s")


class NotOnAc(Exception):
    """Langkah 31: semua bench wajib di daya AC; di baterai bench berhenti."""


def require_ac() -> dict[str, Any] | None:
    from mica.eval.environment import power_status

    power = power_status()
    source = (power or {}).get("source")
    if source != "ac":
        raise NotOnAc(f"sumber daya terbaca '{source}', bukan AC: colok charger lalu ulangi")
    return power


def run_once(ui: str, rep: int, config: Path, cover_window: bool = False,
             edge_switches: bool = True, edge_extra: tuple[str, ...] = ()) -> dict[str, Any]:  # fmt: skip
    power = require_ac()  # dicek sebelum setiap ulangan
    child = [sys.executable, __file__, "--child", ui, "--config", str(config),
             "--edge-switches", "on" if edge_switches else "off",
             *(f"--edge-extra={x}" for x in edge_extra)]  # fmt: skip
    cover = Cover(0) if cover_window else None
    cover_info: dict[str, Any] = {}
    t0 = time.time()
    proc = subprocess.Popen(child, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8")  # fmt: skip
    try:
        painted = read_event(proc, "painted")
        startup_s = painted["wall"] - t0
        if cover is not None:
            cover.ui_root_pid = proc.pid
            cover_info = cover.open()
        cpu = cpu_idle_pct(proc.pid, IDLE_S)
        uss_idle, n_idle = uss_mb(proc.pid)
        assert proc.stdin is not None
        proc.stdin.write("go\n")
        proc.stdin.flush()
        done = read_event(proc, "done")
        uss_after, n_after = uss_mb(proc.pid)
        if cover is not None:
            cover.close()
        proc.stdin.write("quit\n")
        proc.stdin.flush()
        proc.wait(timeout=30)
    finally:
        if cover is not None:
            cover.close()
        if proc.poll() is None:
            for p in reversed(tree(proc.pid)):
                p.kill()
    lat = done["latencies"]
    return {
        "ui": ui, "rep": rep, "startup_s": startup_s, "uss_idle_mb": uss_idle,
        "uss_after_mb": uss_after, "cpu_idle_pct": cpu, "n_processes_idle": n_idle,
        "n_processes_after": n_after, "n_updates": len(lat),
        "n_unacked": int(done.get("unacked", 0)),
        "lat_p50_ms": 1000 * statistics.median(lat) if lat else None,
        "lat_p95_ms": 1000 * percentile(lat, 95) if lat else None,
        "power_source": (power or {}).get("source"),
        "battery_percent": (power or {}).get("battery_percent"),
        "cover_window": cover_window, "edge_switches": edge_switches,
        "cover_opened": cover_info.get("opened"),
        "cover_foreground": cover_info.get("notepad_foreground"),
        "cover_ui_pct": max(cover_info.get("ui_coverage_pct") or [0.0]) if cover_info else None,
        "_latencies": lat, "_cover": cover_info,
    }  # fmt: skip


def percentile(values: list[float], q: float) -> float:
    from mica.eval.metrics import percentile as pct

    return pct(values, q)


def decide(web: dict[str, Any], functional: dict[str, bool]) -> tuple[str, list[str]]:
    reasons = []
    for name, ok in functional.items():
        if not ok:
            reasons.append(f"(a) gagal: {name}")
    p95x3 = web["lat_p95_s"] * FACTOR
    if p95x3 > LIMIT_S:
        reasons.append(f"(b) gagal: p95 x 3 = {p95x3:.3f} s > {LIMIT_S} s")
    else:
        reasons.append(f"(b) lolos: p95 x 3 = {p95x3:.3f} s <= {LIMIT_S} s")
    return ("BATAL" if any("gagal" in r for r in reasons) else "LOLOS"), reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/ui_bench.py")
    parser.add_argument("--config", type=Path, default=Path("config/dev.yaml"))
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--out", type=Path, default=Path("results/ADR-19"))
    parser.add_argument(
        "--ui",
        choices=("both", "pyside6", "web"),
        default="both",
        help="UI yang diukur (both = PySide6 sebagai pembanding + web)",
    )
    parser.add_argument("--name", default="ui-bench", help="awalan folder hasil")
    parser.add_argument("--cover-window", action="store_true",
                        help="tutup jendela UI dengan Notepad selama diam + 20 pertanyaan")  # fmt: skip
    parser.add_argument("--edge-switches", choices=("on", "off"), default="on",
                        help="off = Edge tanpa RENDERING_SWITCHES (pembanding uji)")  # fmt: skip
    parser.add_argument("--edge-extra", action="append", default=[], metavar="SWITCH",
                        help="switch Edge tambahan untuk menguji kandidat (boleh berulang); "
                        "tulis --edge-extra=--switch")  # fmt: skip
    parser.add_argument("--child", choices=("pyside6", "web"))
    args = parser.parse_args(argv)
    if args.child == "pyside6":
        return child_pyside6(args.config)
    if args.child == "web":
        return child_web(args.config, keep_rendering=args.edge_switches == "on",
                         edge_extra=tuple(args.edge_extra))  # fmt: skip

    from mica.config import load_settings
    from mica.eval.environment import collect_environment
    from mica.kb.index import package_version
    from mica.webui.browser import find_edge

    settings = load_settings(args.config)
    if settings.app.mode != "dev":
        print("error: ui_bench hanya untuk mode dev (pekerja dan pipeline palsu)", file=sys.stderr)
        return 2
    try:
        require_ac()
        return _bench(args, settings, collect_environment, package_version, find_edge)
    except NotOnAc as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


def _bench(args: argparse.Namespace, settings: Any, collect_environment: Any,
           package_version: Any, find_edge: Any) -> int:  # fmt: skip
    environment = collect_environment()
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/unit/test_webui.py"],
                           check=False, capture_output=True, text=True)  # fmt: skip
    tests_line = (tests.stdout.strip().splitlines() or ["-"])[-1]
    print(f"tes UI web: {tests_line}", flush=True)
    uis = ("pyside6", "web") if args.ui == "both" else (args.ui,)
    runs: list[dict[str, Any]] = []
    for rep in range(1, args.reps + 1):
        for ui in uis:
            print(f"[{ui} ulangan {rep}] ...", flush=True)
            r = run_once(ui, rep, args.config, args.cover_window, args.edge_switches == "on",
                         tuple(args.edge_extra))  # fmt: skip
            runs.append(r)
            p95 = "-" if r["lat_p95_ms"] is None else f"{r['lat_p95_ms']:.1f} ms"
            print(f"  mulai {r['startup_s']:.2f} s | USS diam {r['uss_idle_mb']:.0f} MB | "
                  f"CPU diam {r['cpu_idle_pct']:.2f}% | p95 {p95} "
                  f"({r['n_updates']} pembaruan, {r['n_unacked']} tanpa ack)", flush=True)  # fmt: skip
            if r["_cover"]:
                print(f"  penutup: {r['_cover']}", flush=True)

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    out = args.out / f"{args.name}-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    fields = [k for k in runs[0] if not k.startswith("_")]
    with (out / "per_run.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(runs)
    with (out / "latencies.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ui", "rep", "i", "latency_s"])
        for r in runs:
            w.writerows([r["ui"], r["rep"], i, f"{x:.6f}"] for i, x in enumerate(r["_latencies"]))

    summary: dict[str, dict[str, Any]] = {}
    for ui in uis:
        rs = [r for r in runs if r["ui"] == ui]
        lat = [x for r in rs for x in r["_latencies"]]
        summary[ui] = {
            "ui": ui, "n_runs": len(rs), "n_updates": len(lat),
            "startup_median_s": statistics.median(r["startup_s"] for r in rs),
            "uss_idle_median_mb": statistics.median(r["uss_idle_mb"] for r in rs),
            "uss_after_median_mb": statistics.median(r["uss_after_mb"] for r in rs),
            "cpu_idle_median_pct": statistics.median(r["cpu_idle_pct"] for r in rs),
            "lat_p50_s": percentile(lat, 50), "lat_p95_s": percentile(lat, 95),
            "n_unacked": sum(r["n_unacked"] for r in rs),
        }  # fmt: skip
        summary[ui]["p95x3_s"] = summary[ui]["lat_p95_s"] * FACTOR
    # (a) fungsional: bagian yang dibuktikan tes otomatis dan oleh run ini
    functional = {
        "tes UI web lulus (event sama dengan PySide6, tampilan ViewModel, tanpa aset internet, "
        "Origin, 127.0.0.1)": tests.returncode == 0,
        "Edge kiosk layar penuh (--kiosk --edge-kiosk-type=fullscreen)": settings.ui.fullscreen,
        "layar pertama tampil di Edge di setiap ulangan": all(r["startup_s"] > 0 for r in runs
                                                               if r["ui"] == "web"),
        "20 pertanyaan terjawab tampil di setiap ulangan": all(r["n_updates"] > 0 for r in runs
                                                                 if r["ui"] == "web"),
        "setiap pembaruan web di-ack browser (tampil)": all(r["n_unacked"] == 0 for r in runs
                                                            if r["ui"] == "web"),
    }  # fmt: skip
    verdict, reasons = decide(summary["web"], functional) if "web" in summary else ("-", [])
    with (out / "summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        cols = list(summary[uis[0]]) + ["keputusan_tahap1", "alasan"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        if "pyside6" in summary:
            w.writerow({**summary["pyside6"], "keputusan_tahap1": "", "alasan": "pembanding"})
        if "web" in summary:
            w.writerow({**summary["web"], "keputusan_tahap1": verdict,
                        "alasan": "; ".join(reasons)})  # fmt: skip
    info = {
        "experiment": "ADR-19 tahap 1", "protocol": "docs/UI-WEB.md (pra-registrasi 17 Okt 2026)",
        "cover_window": args.cover_window, "edge_switches": args.edge_switches,
        "edge_extra": args.edge_extra,
        "cover_details": [{"ui": r["ui"], "rep": r["rep"], **r["_cover"]} for r in runs
                          if r["_cover"]],
        "config": args.config.as_posix(), "uis": list(uis), "web_server": "Flask + flask-sock "
        "(server Werkzeug, threaded)", "fullscreen": settings.ui.fullscreen,
        "font_scale": settings.ui.font_scale, "workers": "palsu (mica.ui.devfakes.FakeWorkerBus)",
        "pipeline": "palsu (mica.ui.devfakes.FakePipeline)", "reps": args.reps,
        "idle_s": IDLE_S, "n_questions": N_QUESTIONS, "question_template": QUESTION,
        "factor": FACTOR, "limit_s": LIMIT_S,
        "latency_definition": {
            "web": "kirim JSON -> ack browser setelah requestAnimationFrame berikutnya (jam Python)",
            "pyside6": "show_item pertama sejak paint terakhir -> event Paint berikutnya jendela; "
                       "bench memanggil window.update() agar setiap pembaruan memicu Paint",
        },
        "functional_checks": functional,
        "functional_by_tests": {"command": "pytest -q tests/unit/test_webui.py",
                                "result": tests_line, "returncode": tests.returncode},
        "decision": {"verdict": verdict, "reasons": reasons},
        "versions": {"PySide6-Essentials": package_version("PySide6-Essentials"),
                     "Flask": package_version("Flask"),
                     "flask-sock": package_version("flask-sock"),
                     "Werkzeug": package_version("Werkzeug"), "psutil": package_version("psutil"),
                     "edge": _edge_version(find_edge())},
        "environment": environment, "python": platform.python_version(),
    }  # fmt: skip
    (out / "run.json").write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8")  # fmt: skip
    print(json.dumps({"summary": summary, "verdict": verdict, "reasons": reasons}, indent=1))
    print(f"tersimpan: {out.as_posix()}")
    return 0


def _edge_version(path: Path) -> str | None:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              f"(Get-Item '{path}').VersionInfo.ProductVersion"],
                             check=False, capture_output=True, text=True, timeout=20)  # fmt: skip
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
