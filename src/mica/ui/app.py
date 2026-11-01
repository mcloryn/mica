"""M-10 aplikasi: QApplication + MainWindow + AppController (SDD M-10, 3.3).

python -m mica.ui [--config config/dev.yaml] [--fake-workers] [--fake-pipeline]
- QTimer 50 ms memanggil controller.step() (SDD 3.3); sinyal jendela -> controller.submit().
- Jendela ditutup -> controller.shutdown() (executor pipeline lalu bus).
- --fake-workers: bus palsu di dalam proses (mica.ui.devfakes), tanpa kamera/mikrofon/speaker;
  --fake-pipeline: jawaban palsu tanpa Groq. Keduanya ditolak di mode prod.
- ui.font_scale mengalikan ukuran font bawaan Qt.
- Panel debug dan aliran DebugInfo hanya di mode dev.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from mica.config import ConfigError, Settings, load_settings
from mica.core.controller import AppController
from mica.core.logging import InteractionLog
from mica.core.session import Session
from mica.ui.main_window import MainWindow

DEFAULT_CONFIG = Path("config/dev.yaml")
POLL_INTERVAL_MS = 50  # SDD 3.3: QTimer 50 ms


class UiError(Exception):
    pass


@dataclass
class KioskApp:
    window: MainWindow
    controller: AppController
    timer: QTimer


def build(
    settings: Settings,
    *,
    fake_workers: bool = False,
    fake_pipeline: bool = False,
    bus: Any = None,
    pipeline: Any = None,
    clock: Callable[[], float] = time.monotonic,
) -> KioskApp:
    """Rakit jendela dan controller. bus/pipeline bisa disuntik (tes); QApplication harus ada."""
    dev = settings.app.mode == "dev"
    if not dev and (fake_workers or fake_pipeline or bus is not None or pipeline is not None):
        raise UiError("pekerja/pipeline palsu hanya boleh saat app.mode: dev (ditolak di prod)")
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

                pipeline = make_pipeline(settings)  # baris giliran ditulis controller
    except Exception:
        stop = getattr(bus, "stop", None)
        if stop is not None:
            stop()
        raise
    window = MainWindow(settings.ui, dev=dev)
    controller = AppController(bus, Session.from_settings(settings), pipeline,
                                 window.show_item, clock, log,
                                 debug=window.show_debug if dev else None)  # fmt: skip
    window.event_emitted.connect(controller.submit)
    window.closed.connect(controller.shutdown)
    timer = QTimer(window)
    timer.setInterval(POLL_INTERVAL_MS)
    timer.timeout.connect(controller.step)
    window.closed.connect(timer.stop)
    return KioskApp(window, controller, timer)


def apply_ui_settings(app: QApplication, window: MainWindow, settings: Settings) -> None:
    font = app.font()
    if font.pointSizeF() > 0:
        font.setPointSizeF(font.pointSizeF() * settings.ui.font_scale)
        app.setFont(font)
    window.show()  # ui.fullscreen dihapus di RF-2; modul ini dihapus bersama PySide6


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mica.ui")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--fake-workers", action="store_true", help="bus palsu (dev saja)")
    parser.add_argument("--fake-pipeline", action="store_true", help="jawaban palsu (dev saja)")
    args = parser.parse_args(argv)
    from mica.audio.stt import SttModelMissing
    from mica.audio.tts import VoiceMissing
    from mica.audio.worker import AudioWorkerConfigError
    from mica.vision.color import ColorsMissing
    from mica.vision.detector import ModelMissing
    from mica.vision.worker import WorkerConfigError

    startup_errors = (ConfigError, UiError, WorkerConfigError, AudioWorkerConfigError,
                      ModelMissing, ColorsMissing, SttModelMissing, VoiceMissing)  # fmt: skip
    try:
        settings = load_settings(args.config, Path(".env"))
        app = QApplication.instance() or QApplication(sys.argv[:1])
        kiosk = build(settings, fake_workers=args.fake_workers, fake_pipeline=args.fake_pipeline)
    except startup_errors as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    apply_ui_settings(app, kiosk.window, settings)  # type: ignore[arg-type]
    kiosk.timer.start()
    return app.exec()
