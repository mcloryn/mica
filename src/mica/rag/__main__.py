"""CLI coba retriever (M-03).

python -m mica.rag search "<pertanyaan>" --config config/dev.yaml [--retriever bm25|dense|hybrid] [--k 5]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from mica.config import ConfigError, load_settings
from mica.kb.index import DEFAULT_KB_ROOT, KbLoadError, load_kb
from mica.rag.retriever import EmbedderFactory, embedder_for_kb, make_retriever


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mica.rag")
    parser.add_argument("--kb-root", type=Path, default=DEFAULT_KB_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    search = sub.add_parser("search", help="cari potongan teratas untuk satu pertanyaan")
    search.add_argument("query")
    search.add_argument("--config", type=Path, required=True)
    search.add_argument("--retriever", choices=("bm25", "dense", "hybrid"))
    search.add_argument("--k", type=int)
    return parser


def cmd_search(args: argparse.Namespace, embedder_factory: EmbedderFactory | None) -> int:
    settings = load_settings(args.config)
    if args.retriever:
        rag = settings.rag.model_copy(update={"retriever": args.retriever})
        settings = settings.model_copy(update={"rag": rag})
    k = args.k or settings.rag.top_k
    kb = load_kb(settings.kb.active_id, args.kb_root)

    # Model dimuat sebelum pengukuran, supaya lama pencarian tidak termasuk waktu muat model.
    embedder = None
    if settings.rag.retriever != "bm25":
        embedder = embedder_for_kb(kb, embedder_factory)
        load = getattr(embedder, "load", None)
        if load is not None:
            load()
    retriever = make_retriever(settings, kb, embedder_factory=lambda m, r: embedder)

    started = time.perf_counter()
    hits = retriever.search(args.query, k)
    elapsed_ms = (time.perf_counter() - started) * 1000

    print(f"KB {kb.kb_id} | retriever {settings.rag.retriever} | k {k}")
    for pos, hit in enumerate(hits, start=1):
        c = hit.chunk
        preview = " ".join(c.text.split())[:100]
        print(f"{pos}. skor {hit.score:.6f} ranks {hit.ranks} | {c.doc_id} | {c.section}")
        print(f"   {preview}")
    if not hits:
        print("(tidak ada hasil)")
    print(f"lama pencarian: {elapsed_ms:.1f} ms")
    return 0


def main(argv: list[str] | None = None, embedder_factory: EmbedderFactory | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return cmd_search(args, embedder_factory)
    except (ConfigError, KbLoadError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
