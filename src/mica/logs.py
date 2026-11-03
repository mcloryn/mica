"""CLI log interaksi (M-11).

python -m mica.logs export --from <tanggal> --to <tanggal> --out file.csv
python -m mica.logs gaps --from <tanggal> --to <tanggal> [--idle-reset-s 120] [--out file.csv]
    (jeda antar-giliran per sesi, validasi session.idle_reset_s; hanya waktu, tanpa isi)
"""

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
    gaps = sub.add_parser("gaps", help="jeda antar-giliran per sesi (validasi idle_reset_s)")
    gaps.add_argument("--from", dest="start", type=_parse_date, required=True)
    gaps.add_argument("--to", dest="end", type=_parse_date, required=True)
    gaps.add_argument("--dir", dest="log_dir", type=Path, default=Path("logs"))
    gaps.add_argument("--idle-reset-s", type=float,
                      help="hitung jeda yang lebih panjang dari nilai ini (mis. 120)")  # fmt: skip
    gaps.add_argument("--out", type=Path, help="CSV per sesi (tanpa isi pertanyaan)")
    return parser


def cmd_gaps(args: argparse.Namespace) -> int:
    from mica.core import gaps

    sessions = gaps.session_gaps(gaps.read_turn_times(args.log_dir, args.start, args.end))
    summary = gaps.summarize(sessions, args.idle_reset_s)
    print(gaps.format_report(sessions, summary))
    if args.out is not None:
        gaps.write_csv(args.out, sessions)
        print(f"{len(sessions)} sesi ditulis ke {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "gaps":
            return cmd_gaps(args)
        count = export(args.log_dir, args.start, args.end, args.out, args.kind)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{count} baris {args.kind} ditulis ke {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
