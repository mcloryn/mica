"""UI web (ADR-19, opsi ui.backend: web): rakit KioskController + server Flask + Edge, tanpa Qt.

python -m mica.webui --config <yaml> [--fake-workers] [--fake-pipeline] [--no-browser] [--port N]
- Rakitan bus/pipeline/controller sama dengan mica.ui.app.build; --fake-* hanya di mode dev.
- Edge ditutup -> server, controller, dan pekerja berhenti rapi; server berhenti -> Edge ditutup.
- --no-browser: hanya server (URL dicetak), berhenti dengan Ctrl+C.
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
    bus: Any = None,
    pipeline: Any = None,
    clock: Callable[[], float] = time.monotonic,
) -> KioskController:
    dev = settings.app.mode == "dev"
    if not dev and (fake_workers or fake_pipeline or bus is not None or pipeline is not None):
        raise WebUiError("pekerja/pipeline palsu hanya boleh saat app.mode: dev (ditolak di kiosk)")
    log = InteractionLog(Path(settings.logging.dir))
    if bus is None:
        if fake_workers:
            from mica.ui.devfakes import FakeWorkerBus

            bus = FakeWorkerBus()
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

                pipeline = make_pipeline(settings, log=log)
    except Exception:
        stop = getattr(bus, "stop", None)
        if stop is not None:
            stop()
        raise
    controller = KioskController(bus, Session.from_settings(settings), pipeline, webui.show_item,
                                 clock, log, debug=webui.show_debug if dev else None)  # fmt: skip
    webui.controller = controller
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
        webui.close_sockets()
        controller.shutdown()
        if browser is not None:
            browser.close()
        stop_server(server)


def run(settings: Settings, *, fake_workers: bool = False, fake_pipeline: bool = False,
        no_browser: bool = False, port: int = 0) -> int:  # fmt: skip
    """Rakit lalu jalankan sampai Edge ditutup atau Ctrl+C (dipakai python -m mica dan main)."""
    from mica.webui.browser import EdgeBrowser, EdgeMissing

    try:
        webui = WebUi(settings.ui, dev=settings.app.mode == "dev")
        browser = None if no_browser else EdgeBrowser(settings.ui.fullscreen)
        controller = build_controller(settings, webui, fake_workers=fake_workers,
                                      fake_pipeline=fake_pipeline)  # fmt: skip
    except (WebUiError, EdgeMissing) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        serve(webui, controller, browser, port,
              on_ready=lambda url: print(f"MICA web: {url}", flush=True))  # fmt: skip
    except KeyboardInterrupt:
        print("berhenti")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mica.webui")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--fake-workers", action="store_true", help="bus palsu (dev saja)")
    parser.add_argument("--fake-pipeline", action="store_true", help="jawaban palsu (dev saja)")
    parser.add_argument("--no-browser", action="store_true", help="jangan luncurkan Edge")
    parser.add_argument("--port", type=int, default=0, help="0 = port acak bebas")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config, Path(".env"))
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return run(settings, fake_workers=args.fake_workers, fake_pipeline=args.fake_pipeline,
               no_browser=args.no_browser, port=args.port)  # fmt: skip
