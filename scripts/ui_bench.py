"""Pengukuran percobaan ADR-19 (docs/UI-WEB.md, tahap 1): PySide6 vs UI web.

python scripts/ui_bench.py [--config config/dev.yaml] [--reps 3] [--out results/ADR-19]

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
Hasil: results/ADR-19/ui-bench-<cap waktu>/ (per_run.csv, latencies.csv, summary.csv, run.json).
Aturan tahap 1 diterapkan mekanis: LOLOS bila (a) dan (b), dengan (b) = p95 jeda tampil x 3 <= 1,0 s.
Kode aplikasi (mica.ui, mica.webui) tidak diubah untuk pengukuran; kait hanya di skrip ini.
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
            emit("done", latencies=latencies, updates=len(latencies))

    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(poll)
    timer.start()
    apply_ui_settings(app, window, settings)
    kiosk.timer.start()
    return app.exec()


# --- proses anak: web -------------------------------------------------------------------


def child_web(config: Path) -> int:
    import asyncio

    from mica.config import load_settings
    from mica.webui.app import build_controller, serve
    from mica.webui.browser import EdgeBrowser
    from mica.webui.server import WebUi

    class BenchWebUi(WebUi):
        def handle_message(self, data: dict[str, Any]) -> None:
            first = self.first_render_at is None
            super().handle_message(data)
            if first and self.first_render_at is not None:
                emit("painted")

    settings = load_settings(config)
    webui = BenchWebUi(settings.ui, dev=True)
    controller = build_controller(settings, webui, fake_workers=True, fake_pipeline=True)
    browser = EdgeBrowser(settings.ui.fullscreen)
    commands = stdin_commands()
    driver = Driver(controller, webui.vm)

    async def run() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(serve(webui, controller, browser, stop=stop,
                                         on_ready=lambda url: emit("url", url=url,
                                                                   edge_pid=browser.pid)))  # fmt: skip
        start_index = 0
        while not task.done():
            try:
                cmd = commands.get_nowait()
            except queue.Empty:
                cmd = None
            if cmd == "go":
                start_index = len(webui.ack_latencies_s)
                driver.active = True
            elif cmd == "quit":
                stop.set()
            driver.tick()
            if driver.done and driver.active:
                driver.active = False
                # tunggu ack pembaruan terakhir (paling lama 5 s)
                deadline = time.perf_counter() + 5.0
                while webui.sent_at and time.perf_counter() < deadline:
                    await asyncio.sleep(0.01)
                lat = webui.ack_latencies_s[start_index:]
                emit("done", latencies=lat, updates=len(lat))
            await asyncio.sleep(0.05)
        await task

    asyncio.run(run())
    return 0


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


def run_once(ui: str, rep: int, config: Path) -> dict[str, Any]:
    from mica.eval.environment import power_status

    power = power_status()
    t0 = time.time()
    proc = subprocess.Popen([sys.executable, __file__, "--child", ui, "--config", str(config)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8")  # fmt: skip
    try:
        painted = read_event(proc, "painted")
        startup_s = painted["wall"] - t0
        cpu = cpu_idle_pct(proc.pid, IDLE_S)
        uss_idle, n_idle = uss_mb(proc.pid)
        assert proc.stdin is not None
        proc.stdin.write("go\n")
        proc.stdin.flush()
        done = read_event(proc, "done")
        uss_after, n_after = uss_mb(proc.pid)
        proc.stdin.write("quit\n")
        proc.stdin.flush()
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            for p in reversed(tree(proc.pid)):
                p.kill()
    lat = done["latencies"]
    return {
        "ui": ui, "rep": rep, "startup_s": startup_s, "uss_idle_mb": uss_idle,
        "uss_after_mb": uss_after, "cpu_idle_pct": cpu, "n_processes_idle": n_idle,
        "n_processes_after": n_after, "n_updates": len(lat),
        "lat_p50_ms": 1000 * statistics.median(lat) if lat else None,
        "lat_p95_ms": 1000 * percentile(lat, 95) if lat else None,
        "power_source": (power or {}).get("source"),
        "battery_percent": (power or {}).get("battery_percent"),
        "_latencies": lat,
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
    parser.add_argument("--child", choices=("pyside6", "web"))
    args = parser.parse_args(argv)
    if args.child == "pyside6":
        return child_pyside6(args.config)
    if args.child == "web":
        return child_web(args.config)

    from mica.config import load_settings
    from mica.eval.environment import collect_environment
    from mica.kb.index import package_version
    from mica.webui.browser import find_edge

    settings = load_settings(args.config)
    if settings.app.mode != "dev":
        print("error: ui_bench hanya untuk mode dev (pekerja dan pipeline palsu)", file=sys.stderr)
        return 2
    environment = collect_environment()
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/unit/test_webui.py"],
                           check=False, capture_output=True, text=True)  # fmt: skip
    tests_line = (tests.stdout.strip().splitlines() or ["-"])[-1]
    print(f"tes UI web: {tests_line}", flush=True)
    runs: list[dict[str, Any]] = []
    for rep in range(1, args.reps + 1):
        for ui in ("pyside6", "web"):
            print(f"[{ui} ulangan {rep}] ...", flush=True)
            r = run_once(ui, rep, args.config)
            runs.append(r)
            print(f"  mulai {r['startup_s']:.2f} s | USS diam {r['uss_idle_mb']:.0f} MB | "
                  f"CPU diam {r['cpu_idle_pct']:.2f}% | p95 {r['lat_p95_ms']:.1f} ms "
                  f"({r['n_updates']} pembaruan)", flush=True)  # fmt: skip

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    out = args.out / f"ui-bench-{stamp}"
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
    for ui in ("pyside6", "web"):
        rs = [r for r in runs if r["ui"] == ui]
        lat = [x for r in rs for x in r["_latencies"]]
        summary[ui] = {
            "ui": ui, "n_runs": len(rs), "n_updates": len(lat),
            "startup_median_s": statistics.median(r["startup_s"] for r in rs),
            "uss_idle_median_mb": statistics.median(r["uss_idle_mb"] for r in rs),
            "uss_after_median_mb": statistics.median(r["uss_after_mb"] for r in rs),
            "cpu_idle_median_pct": statistics.median(r["cpu_idle_pct"] for r in rs),
            "lat_p50_s": percentile(lat, 50), "lat_p95_s": percentile(lat, 95),
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
    }  # fmt: skip
    verdict, reasons = decide(summary["web"], functional)
    with (out / "summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        cols = list(summary["web"]) + ["keputusan_tahap1", "alasan"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerow({**summary["pyside6"], "keputusan_tahap1": "", "alasan": "pembanding"})
        w.writerow({**summary["web"], "keputusan_tahap1": verdict, "alasan": "; ".join(reasons)})
    info = {
        "experiment": "ADR-19 tahap 1", "protocol": "docs/UI-WEB.md (pra-registrasi 17 Okt 2026)",
        "config": args.config.as_posix(), "fullscreen": settings.ui.fullscreen,
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
                     "aiohttp": package_version("aiohttp"), "psutil": package_version("psutil"),
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
