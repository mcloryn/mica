"""UI web (ADR-19, opsi ui.backend: web): rakit KioskController + server Flask + Edge, tanpa Qt.

python -m mica.webui --config <yaml> [--fake-workers [--fake-camera]] [--fake-pipeline] [--no-browser]
    [--port N]
    [--record-resources <folder> [--resource-interval 5] [--e09]]
- Rakitan bus/pipeline/controller sama dengan mica.ui.app.build; --fake-* hanya di mode dev.
- --fake-camera (dengan --fake-workers): proses kamera asli dengan sumber gambar palsu
  (mica.vision.fakesource) sehingga pratinjau, target, dan sapaan bisa dicoba tanpa kamera.
- Edge ditutup -> server, controller, dan pekerja berhenti rapi; server berhenti -> Edge ditutup.
- --no-browser: hanya server (URL dicetak), berhenti dengan Ctrl+C.
- --record-resources: perekam sumber daya E-09 (mica.eval.resources); hanya dev, kecuali --e09.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mica.config import ConfigError, Settings, load_settings
from mica.core.controller import KioskController
from mica.core.logging import InteractionLog
from mica.core.session import Session
from mica.webui.server import HOST, WebUi, start_server, stop_server

DEFAULT_CONFIG = Path("config/dev.yaml")
WATCH_INTERVAL_S = 0.25  # non-ADR: cek berkala apakah jendela Edge sudah ditutup


class WebUiError(Exception):
    pass


def build_controller(
    settings: Settings,
    webui: WebUi,
    *,
    fake_workers: bool = False,
    fake_pipeline: bool = False,
    fake_camera: bool = False,
    bus: Any = None,
    pipeline: Any = None,
    clock: Callable[[], float] = time.monotonic,
) -> KioskController:
    dev = settings.app.mode == "dev"
    fakes = fake_workers or fake_pipeline or fake_camera
    if not dev and (fakes or bus is not None or pipeline is not None):
        raise WebUiError("pekerja/pipeline palsu hanya boleh saat app.mode: dev (ditolak di kiosk)")
    if fake_camera and not fake_workers:
        raise WebUiError("--fake-camera hanya bersama --fake-workers")
    log = InteractionLog(Path(settings.logging.dir))
    if bus is None:
        if fake_workers:
            from mica.ui.devfakes import FakeWorkerBus, start_fake_camera

            bus = FakeWorkerBus(start_fake_camera(settings) if fake_camera else None)
        else:
            from mica.core.bus import start_workers

            bus = start_workers(settings)
    try:
        if pipeline is None:
            if fake_pipeline:
                from mica.ui.devfakes import FakePipeline

                pipeline = FakePipeline()
            else:
                from mica.rag.pipeline import make_pipeline

                pipeline = make_pipeline(settings)  # baris giliran ditulis controller
    except Exception:
        stop = getattr(bus, "stop", None)
        if stop is not None:
            stop()
        raise
    controller = KioskController(bus, Session.from_settings(settings), pipeline, webui.show_item,
                                 clock, log, debug=webui.show_debug if dev else None,
                                 display=webui.show_display)  # fmt: skip
    webui.controller = controller
    webui.preview_source = getattr(bus, "preview", None)  # None bila pratinjau off
    return controller


def serve(
    webui: WebUi,
    controller: KioskController,
    browser: Any | None,
    port: int = 0,
    stop: threading.Event | None = None,
    on_ready: Callable[[str], None] = print,
) -> None:
    """Server + thread poll 50 ms sampai stop di-set atau jendela Edge ditutup; lalu bersih-bersih."""
    stop = stop or threading.Event()
    server = start_server(webui, port)
    url = f"http://{HOST}:{webui.port}/"
    poll = threading.Thread(target=webui.poll_loop, args=(stop,), name="mica-webui-poll",
                            daemon=True)  # fmt: skip
    poll.start()
    pump = None
    if webui.preview_source is not None:
        pump = threading.Thread(target=webui.preview_loop, args=(stop,),
                                name="mica-webui-preview", daemon=True)  # fmt: skip
        pump.start()
    try:
        if browser is not None:
            browser.start(url)
        on_ready(url)
        while not stop.is_set():
            if browser is not None and not browser.alive():
                break  # jendela Edge ditutup
            stop.wait(WATCH_INTERVAL_S)
    finally:
        stop.set()
        poll.join()
        if pump is not None:
            pump.join(timeout=2)
        webui.close_sockets()
        controller.shutdown()
        if browser is not None:
            browser.close()
        stop_server(server)


def run(settings: Settings, *, fake_workers: bool = False, fake_pipeline: bool = False,
        fake_camera: bool = False, no_browser: bool = False, port: int = 0, record_resources: Path | None = None,
        resource_interval: float = 5.0, e09: bool = False) -> int:  # fmt: skip
    """Rakit lalu jalankan sampai Edge ditutup atau Ctrl+C (dipakai python -m mica dan main)."""
    from mica.eval.resources import RecorderRefused, check_allowed
    from mica.webui.browser import EdgeBrowser, EdgeMissing

    try:
        if record_resources is not None:
            check_allowed(settings.app.mode, e09)  # ditolak sebelum pekerja dimulai
        webui = WebUi(settings.ui, dev=settings.app.mode == "dev")
        browser = (
            None
            if no_browser
            else EdgeBrowser(settings.ui.fullscreen, camera_preview=settings.ui.camera_preview)
        )
        controller = build_controller(settings, webui, fake_workers=fake_workers,
                                      fake_pipeline=fake_pipeline,
                                      fake_camera=fake_camera)  # fmt: skip
    except (WebUiError, EdgeMissing, RecorderRefused) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    recorder = None
    if record_resources is not None:
        from mica.eval.resources import bus_roots, make_recorder

        recorder = make_recorder(record_resources, settings.app.mode, e09,
                                 lambda: bus_roots(controller.bus, browser), resource_interval,
                                 {"ui_backend": "web", "fake_workers": fake_workers,
                                  "fake_pipeline": fake_pipeline, "fake_camera": fake_camera,
                                  "camera_preview": settings.ui.camera_preview})  # fmt: skip
        recorder.start()
    try:
        serve(webui, controller, browser, port,
              on_ready=lambda url: print(f"MICA web: {url}", flush=True))  # fmt: skip
    except KeyboardInterrupt:
        print("berhenti")
    finally:
        if recorder is not None:
            recorder.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mica.webui")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--fake-workers", action="store_true", help="bus palsu (dev saja)")
    parser.add_argument("--fake-pipeline", action="store_true", help="jawaban palsu (dev saja)")
    parser.add_argument(
        "--fake-camera",
        action="store_true",
        help="dengan --fake-workers: proses kamera dengan sumber gambar palsu (dev)",
    )
    parser.add_argument("--no-browser", action="store_true", help="jangan luncurkan Edge")
    parser.add_argument("--port", type=int, default=0, help="0 = port acak bebas")
    from mica.eval.resources import add_arguments

    add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config, Path(".env"))
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return run(settings, fake_workers=args.fake_workers, fake_pipeline=args.fake_pipeline,
               fake_camera=args.fake_camera, no_browser=args.no_browser, port=args.port,
               record_resources=args.record_resources,
               resource_interval=args.resource_interval, e09=args.e09)  # fmt: skip
