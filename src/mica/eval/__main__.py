"""CLI evaluasi (M-12). Saat ini baru subperintah annotate.

python -m mica.eval annotate export --config <yaml> --dataset <jsonl> --out <pool.csv> [--force]
python -m mica.eval annotate import --dataset <jsonl> --pool <pool.csv>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mica.config import ConfigError, load_settings
from mica.eval.annotate import POOL_DEPTH, export_pool, import_pool
from mica.eval.dataset import DatasetError
from mica.kb.index import DEFAULT_KB_ROOT, KbLoadError, load_kb
from mica.rag.retriever import EmbedderFactory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mica.eval")
    parser.add_argument("--kb-root", type=Path, default=DEFAULT_KB_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    annotate = sub.add_parser("annotate", help="anotasi relevansi chunk")
    annotate_sub = annotate.add_subparsers(dest="action", required=True)

    exp = annotate_sub.add_parser("export", help="buat pool kandidat untuk dianotasi")
    exp.add_argument("--config", type=Path, required=True)
    exp.add_argument("--dataset", type=Path, required=True)
    exp.add_argument("--out", type=Path, required=True)
    exp.add_argument("--force", action="store_true", help="timpa pool yang sudah ada")

    imp = annotate_sub.add_parser("import", help="isi gold_chunk_ids dari pool beranotasi")
    imp.add_argument("--dataset", type=Path, required=True)
    imp.add_argument("--pool", type=Path, required=True)
    return parser


def cmd_export(args: argparse.Namespace, embedder_factory: EmbedderFactory | None) -> int:
    settings = load_settings(args.config)
    kb = load_kb(settings.kb.active_id, args.kb_root)
    result = export_pool(
        settings, kb, args.dataset, args.out, embedder_factory=embedder_factory, force=args.force
    )
    average = result.rows / result.questions if result.questions else 0.0
    print(
        f"KB {kb.kb_id}: {result.questions} pertanyaan, {result.rows} baris pool, "
        f"rata-rata {average:.1f} kandidat per pertanyaan (kedalaman {POOL_DEPTH}) -> {args.out}"
    )
    if result.unmatched_gold_refs:
        print("peringatan: gold_refs tanpa chunk yang cocok:")
        for item in result.unmatched_gold_refs:
            print(f"  {item}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    gold = import_pool(args.dataset, args.pool)
    total = sum(len(ids) for ids in gold.values())
    print(f"{len(gold)} pertanyaan diperbarui, {total} chunk relevan -> {args.dataset}")
    return 0


def main(argv: list[str] | None = None, embedder_factory: EmbedderFactory | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        if args.action == "export":
            return cmd_export(args, embedder_factory)
        return cmd_import(args)
    except (ConfigError, KbLoadError, DatasetError, FileExistsError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
