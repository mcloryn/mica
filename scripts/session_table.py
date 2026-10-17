"""Cetak tabel transisi M-09 dari kode ke results/M-09/transitions.md.

python scripts/session_table.py [--out results/M-09/transitions.md]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mica.core.session import transitions_markdown

DEFAULT_OUT = Path("results/M-09/transitions.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/session_table.py")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(transitions_markdown(), encoding="utf-8")
    print(f"tersimpan: {args.out.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
