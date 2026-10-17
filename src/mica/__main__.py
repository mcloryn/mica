"""Entry point kiosk.

python -m mica [--config config/kiosk.yaml] [--fake-workers] [--fake-pipeline]
    jalankan check dulu; bila ada GAGAL, cetak tabel dan keluar 1 tanpa membuka jendela.
    Bila OK: proses vision + suara (start_workers), KioskController, dan UI (mica.ui.app).
    --fake-* hanya boleh di mode dev.
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


def _launch(settings: Settings, args: argparse.Namespace) -> int:
    from PySide6.QtWidgets import QApplication

    from mica.ui.app import apply_ui_settings, build

    app = QApplication.instance() or QApplication(sys.argv[:1])
    kiosk = build(settings, fake_workers=args.fake_workers, fake_pipeline=args.fake_pipeline)
    apply_ui_settings(app, kiosk.window, settings)  # type: ignore[arg-type]
    kiosk.timer.start()
    return app.exec()


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

    parser = argparse.ArgumentParser(prog="python -m mica")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--fake-workers", action="store_true", help="bus palsu (dev saja)")
    parser.add_argument("--fake-pipeline", action="store_true", help="jawaban palsu (dev saja)")
    args = parser.parse_args(argv)

    rows, settings = check(args.config, args.env_file)
    if failed(rows) or settings is None:
        print(format_table(rows))
        print("MICA tidak dijalankan.")
        return 1
    if settings.app.mode != "dev" and (args.fake_workers or args.fake_pipeline):
        print("error: --fake-workers/--fake-pipeline hanya boleh saat app.mode: dev",
              file=sys.stderr)  # fmt: skip
        return 2
    return launch(settings, args)


if __name__ == "__main__":
    sys.exit(main())
