"""CLI evaluasi (M-12). Saat ini subperintah annotate dan retrieval.

python -m mica.eval annotate export --config <yaml> --dataset <jsonl> --out <pool.csv> [--force]
python -m mica.eval annotate import --dataset <jsonl> --pool <pool.csv>
python -m mica.eval retrieval --config <yaml> --dataset <jsonl> --out <folder>
    [--retrievers bm25,dense,hybrid] [--pool <pool.csv>]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mica.config import ConfigError, load_settings
from mica.eval.annotate import POOL_DEPTH, export_pool, import_pool
from mica.eval.dataset import DatasetError
from mica.eval.retrieval import MAIN_GROUP, run_retrieval
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

    ret = sub.add_parser("retrieval", help="E-01: Recall@5, MRR, nDCG@10, latensi")
    ret.add_argument("--config", type=Path, required=True)
    ret.add_argument("--dataset", type=Path, required=True)
    ret.add_argument("--out", type=Path, required=True)
    ret.add_argument(
        "--retrievers",
        type=_retriever_list,
        help="daftar dipisah koma, misalnya bm25,dense,hybrid (default: rag.retriever)",
    )
    ret.add_argument("--pool", type=Path, help="default: pool.csv di folder dataset")
    return parser


def _retriever_list(value: str) -> list[str]:
    kinds = [v.strip() for v in value.split(",") if v.strip()]
    unknown = [k for k in kinds if k not in ("bm25", "dense", "hybrid")]
    if not kinds or unknown:
        raise argparse.ArgumentTypeError(f"retriever tidak dikenal: {unknown or value!r}")
    return list(dict.fromkeys(kinds))


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


def cmd_retrieval(args: argparse.Namespace, embedder_factory: EmbedderFactory | None) -> int:
    settings = load_settings(args.config)
    kb = load_kb(settings.kb.active_id, args.kb_root)
    retrievers = args.retrievers or [settings.rag.retriever]
    pool = args.pool or args.dataset.parent / "pool.csv"
    embedder = None
    if embedder_factory is not None:
        info = kb.manifest["embedder"]
        embedder = embedder_factory(info["model"], info["revision"])
    runs, summary = run_retrieval(
        settings, kb, args.dataset, pool, args.out, retrievers, embedder=embedder
    )
    print(f"KB {kb.kb_id} | split dev | {len(runs)} run -> {summary}")
    print("retriever | Recall@5 | MRR | nDCG@10 | p50 ms | p95 ms | unjudged")
    for run in runs:
        m = run.metrics[MAIN_GROUP]
        print(
            f"{run.retriever} | {m['recall@5']:.4f} | {m['mrr@10']:.4f} | {m['ndcg@10']:.4f} | "
            f"{m['latency_p50_ms']:.2f} | {m['latency_p95_ms']:.2f} | {m['unjudged']}"
        )
    return 0


def main(argv: list[str] | None = None, embedder_factory: EmbedderFactory | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "retrieval":
            return cmd_retrieval(args, embedder_factory)
        if args.action == "export":
            return cmd_export(args, embedder_factory)
        return cmd_import(args)
    except (ConfigError, KbLoadError, DatasetError, FileExistsError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
