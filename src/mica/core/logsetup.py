"""Log konsol untuk mode dev (Langkah 42): INFO ke stderr di proses utama dan proses anak.

Tanpa ini, log INFO (mis. tombol Bicara diabaikan, mikrofon dibuka) tidak pernah terlihat karena
aplikasi tidak memasang handler. Hanya dipasang saat app.mode: dev dan bila root logger belum
punya handler. Log tidak berisi audio, gambar, atau teks pengunjung (N-08, N-09).
"""

from __future__ import annotations

import logging

FORMAT = "[%(asctime)s] %(levelname)s %(processName)s %(name)s: %(message)s"


def configure_dev_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format=FORMAT)
