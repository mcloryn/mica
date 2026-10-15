"""CLI KB (M-02).

python -m mica.kb init-sources --src <folder> --source-type dev|official --date YYYY-MM-DD [--force]
python -m mica.kb build --src <folder> --kb-id <id> --source-type dev|official --config <yaml>
python -m mica.kb list
python -m mica.kb inspect --kb-id <id>
python -m mica.kb check-sources --src <folder>
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

import yaml

from mica.config import ConfigError, load_settings
from mica.kb.embedder import DEFAULT_CACHE_DIR, BgeM3Embedder, Embedder
from mica.kb.index import DEFAULT_KB_ROOT, KbLoadError, build_kb, list_kbs, load_kb, read_manifest
from mica.kb.parsers import (
    SOURCES_FILE,
    KbBuildError,
    iter_source_files,
    load_sources,
    parse_file,
    source_key,
)

EmbedderFactory = Callable[[str, str | None], Embedder]  # (model_id, revision)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"tanggal harus YYYY-MM-DD: {value!r}") from exc


def _folder_size(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size} B"


def _preview(text: str, limit: int = 300) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + " ..."


class _NoAliasDumper(yaml.SafeDumper):
    # tanggal yang sama tidak ditulis sebagai &id001/*id001, supaya mudah disunting manual
    def ignore_aliases(self, data: object) -> bool:
        return True


def cmd_init_sources(args: argparse.Namespace) -> int:
    src: Path = args.src
    target = src / SOURCES_FILE
    if target.exists() and not args.force:
        print(f"error: {target} sudah ada; pakai --force untuk menimpa", file=sys.stderr)
        return 1
    entries: dict[str, dict[str, object]] = {}
    for path in iter_source_files(src):
        parsed = parse_file(src, path)
        title = path.stem
        url = None
        if parsed is not None:
            first_heading = next((b.section for b in parsed.blocks if b.section), None)
            title = parsed.frontmatter.get("title") or first_heading or path.stem
            url = parsed.frontmatter.get("url")
        entry: dict[str, object] = {"title": title, "valid_from": args.date}
        if url:
            entry["url"] = url
        entries[source_key(src, path)] = entry
    header = (
        f"# Metadata dokumen sumber ({args.source_type}), dibuat oleh init-sources.\n"
        "# valid_from wajib per dokumen (F-16); periksa judul sebelum build.\n"
    )
    body = (
        yaml.dump(entries, Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True)
        if entries
        else "{}\n"
    )
    target.write_text(header + body, encoding="utf-8")
    print(f"{len(entries)} dokumen ditulis ke {target}")
    return 0


def cmd_build(args: argparse.Namespace, embedder_factory: EmbedderFactory) -> int:
    settings = load_settings(args.config)
    embedder = embedder_factory(settings.kb.embedder.model, settings.kb.embedder.revision)
    started = time.perf_counter()
    folder = build_kb(
        args.src, args.kb_id, args.source_type, settings.kb, embedder, args.kb_root
    )
    elapsed = time.perf_counter() - started
    manifest = read_manifest(folder)
    print(
        f"KB {args.kb_id}: {len(manifest['documents'])} dokumen, {manifest['n_chunks']} chunk, "
        f"{elapsed:.1f} detik, {_human(_folder_size(folder))} -> {folder}"
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    folders = list_kbs(args.kb_root)
    if not folders:
        print(f"belum ada KB di {args.kb_root}")
    for folder in folders:
        try:
            m = read_manifest(folder)
            print(
                f"{m['kb_id']}\t{m['source_type']}\t{len(m.get('documents', []))} dokumen\t"
                f"{m['n_chunks']} chunk\t{m.get('built_at', '')}"
            )
        except KbLoadError as exc:
            print(f"{folder.name}\t(rusak: {exc.message})")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    kb = load_kb(args.kb_id, args.kb_root)
    m = kb.manifest
    print(f"kb_id: {kb.kb_id} ({m['source_type']}), dibangun {m.get('built_at', '?')}")
    e = m["embedder"]
    print(f"embedder: {e['model']} rev {e['revision']} ({e.get('weights_file', '?')})")
    print(f"chunker: {m.get('chunker')}")
    print(f"dokumen: {len(m.get('documents', []))}")
    print(f"chunk: {len(kb.chunks)} (tabel: {sum(c.is_table for c in kb.chunks)})")
    n = len(kb.chunks)
    picks = sorted({0, n // 2, n - 1}) if n else []
    for i in picks:
        c = kb.chunks[i]
        print(f"\n--- contoh {c.chunk_id} | {c.doc_title} | {c.section} | {c.valid_from}")
        print(_preview(c.text))
    table = next((c for c in kb.chunks if c.is_table), None)
    print("\n--- contoh tabel", end="")
    if table is None:
        print(": tidak ada")
    else:
        print(f" {table.chunk_id} | {table.doc_title} | {table.section}")
        print(_preview(table.text))
    return 0


def cmd_check_sources(args: argparse.Namespace) -> int:
    docs = load_sources(args.src, "dev", allow_missing_date=True)
    missing = [d.doc_id for d in docs if d.valid_from is None]
    print(f"{len(docs)} dokumen terbaca di {args.src}")
    if not missing:
        print("semua dokumen sudah punya valid_from")
        return 0
    print(f"{len(missing)} dokumen belum punya valid_from:")
    for doc_id in missing:
        print(f"  {doc_id}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mica.kb")
    parser.add_argument("--kb-root", type=Path, default=DEFAULT_KB_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-sources", help="buat sources.yaml untuk semua file")
    init.add_argument("--src", type=Path, required=True)
    init.add_argument("--source-type", choices=("dev", "official"), required=True)
    init.add_argument("--date", type=_parse_date, required=True)
    init.add_argument("--force", action="store_true")

    build = sub.add_parser("build", help="bangun KB baru")
    build.add_argument("--src", type=Path, required=True)
    build.add_argument("--kb-id", required=True)
    build.add_argument("--source-type", choices=("dev", "official"), required=True)
    build.add_argument("--config", type=Path, required=True)

    sub.add_parser("list", help="daftar KB")

    inspect = sub.add_parser("inspect", help="ringkasan satu KB")
    inspect.add_argument("--kb-id", required=True)

    check = sub.add_parser("check-sources", help="tampilkan dokumen tanpa valid_from")
    check.add_argument("--src", type=Path, required=True)
    return parser


def _default_embedder(model_id: str, revision: str | None) -> Embedder:
    return BgeM3Embedder(model_id, revision=revision, cache_dir=DEFAULT_CACHE_DIR)


def main(argv: list[str] | None = None, embedder_factory: EmbedderFactory | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init-sources":
            return cmd_init_sources(args)
        if args.command == "build":
            return cmd_build(args, embedder_factory or _default_embedder)
        if args.command == "list":
            return cmd_list(args)
        if args.command == "inspect":
            return cmd_inspect(args)
        return cmd_check_sources(args)
    except (KbBuildError, KbLoadError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
