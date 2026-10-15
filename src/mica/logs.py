"""CLI log interaksi (M-11): python -m mica.logs export --from <tanggal> --to <tanggal> --out file.csv"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from mica.core.logging import export


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"tanggal harus YYYY-MM-DD: {value!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mica.logs")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="ekspor log JSONL ke CSV")
    exp.add_argument("--from", dest="start", type=_parse_date, required=True)
    exp.add_argument("--to", dest="end", type=_parse_date, required=True)
    exp.add_argument("--out", type=Path, required=True)
    exp.add_argument("--kind", choices=("turns", "events"), default="turns")
    exp.add_argument("--dir", dest="log_dir", type=Path, default=Path("logs"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        count = export(args.log_dir, args.start, args.end, args.out, args.kind)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{count} baris {args.kind} ditulis ke {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
