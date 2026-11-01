"""Entry point aplikasi.

python -m mica [--config config/prod.yaml] [--fake-workers] [--fake-pipeline]
               [--record-resources <folder> [--resource-interval 5] [--e09]]
    jalankan check dulu; bila ada GAGAL, cetak tabel dan keluar 1 tanpa membuka jendela.
    Bila OK: proses vision + suara (start_workers), AppController, dan UI sesuai ui.backend:
    web (mica.webui.app: server Flask + Edge kiosk, UI utama) atau pyside6 (mica.ui.app, cadangan).
    --fake-* hanya boleh di mode dev. --record-resources (perekam E-09, mica.eval.resources)
    hanya di mode dev kecuali dengan --e09, dan hanya untuk ui.backend web (PySide6 dibekukan).
python -m mica setup [--config ...] [--only <komponen>]   lihat mica/setup.py
python -m mica check [--config ...]                       lihat mica/check.py
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mica.check import DEFAULT_CONFIG, DEFAULT_ENV, failed, format_table, run_check
from mica.config import Settings


def _launch_pyside6(settings: Settings, args: argparse.Namespace) -> int:
    from PySide6.QtWidgets import QApplication

    from mica.ui.app import apply_ui_settings, build

    app = QApplication.instance() or QApplication(sys.argv[:1])
    kiosk = build(settings, fake_workers=args.fake_workers, fake_pipeline=args.fake_pipeline)
    apply_ui_settings(app, kiosk.window, settings)  # type: ignore[arg-type]
    kiosk.timer.start()
    return app.exec()


def _launch_web(settings: Settings, args: argparse.Namespace) -> int:
    from mica.webui.app import run

    return run(settings, fake_workers=args.fake_workers, fake_pipeline=args.fake_pipeline,
               record_resources=getattr(args, "record_resources", None),
               resource_interval=getattr(args, "resource_interval", 5.0),
               e09=getattr(args, "e09", False),
               trial=getattr(args, "trial_values", False))  # fmt: skip


# ui.backend -> peluncur UI (ADR-19, Provisional; pilihan akhir di E-09)
LAUNCHERS: dict[str, Callable[[Settings, argparse.Namespace], int]] = {
    "pyside6": _launch_pyside6,
    "web": _launch_web,
}


def _launch(settings: Settings, args: argparse.Namespace) -> int:
    return LAUNCHERS[settings.ui.backend](settings, args)


def main(
    argv: list[str] | None = None,
    check: Callable[..., tuple[list[Any], Settings | None]] = run_check,
    launch: Callable[[Settings, argparse.Namespace], int] = _launch,
) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["setup"]:
        from mica.setup import main as setup_main

        return setup_main(argv[1:])
    if argv[:1] == ["check"]:
        from mica.check import main as check_main

        return check_main(argv[1:])

    from mica.core import startup

    startup.begin()  # Langkah 40: tahap dibuffer sampai logging.dir diketahui (run web)
    startup.mark("main_start")
    parser = argparse.ArgumentParser(prog="python -m mica")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--fake-workers", action="store_true", help="bus palsu (dev saja)")
    parser.add_argument("--fake-pipeline", action="store_true", help="jawaban palsu (dev saja)")
    parser.add_argument("--trial-values", action="store_true",
                        help="isi kunci null dengan nilai coba SDD bagian 12 (dev saja)")  # fmt: skip
    from mica.eval.resources import add_arguments

    add_arguments(parser)
    args = parser.parse_args(argv)

    rows, settings = check(args.config, args.env_file)
    startup.mark("check_done")
    if failed(rows) or settings is None:
        print(format_table(rows))
        print("MICA tidak dijalankan.")
        return 1
    if args.trial_values:  # Langkah 41: setelah check, di memori; prod ditolak
        from mica.config import ConfigError
        from mica.trial import load_trial_settings

        try:
            settings, _filled = load_trial_settings(args.config, args.env_file)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if settings.app.mode != "dev" and (args.fake_workers or args.fake_pipeline):
        print("error: --fake-workers/--fake-pipeline hanya boleh saat app.mode: dev",
              file=sys.stderr)  # fmt: skip
        return 2
    if args.record_resources is not None:
        from mica.eval.resources import RecorderRefused, check_allowed

        try:
            check_allowed(settings.app.mode, args.e09)
        except RecorderRefused as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if settings.ui.backend != "web":
            print("error: --record-resources hanya untuk ui.backend: web", file=sys.stderr)
            return 2
    return launch(settings, args)


if __name__ == "__main__":
    sys.exit(main())
