"""CLI uji cepat M-06 (mode dev): satu pertanyaan lewat AnswerPipeline yang sama dengan kiosk.

python -m mica.ask "<pertanyaan>" [--prev "<pertanyaan sebelumnya>"] [--config config/dev.yaml]

Baris log ditulis ke logging.dir seperti biasa (sudah disamarkan, di luar repo).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from mica.config import CFG_INVALID, ConfigError, load_settings
from mica.core.types import Turn
from mica.kb.index import DEFAULT_KB_ROOT, KbLoadError
from mica.rag.pii import scrub_pii
from mica.rag.pipeline import AnswerPipeline, make_pipeline

ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mica.ask")
    parser.add_argument("question")
    parser.add_argument("--prev", help="pertanyaan sebelumnya, untuk mencoba followup")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "dev.yaml")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--kb-root", type=Path, default=DEFAULT_KB_ROOT)
    return parser


def run(args: argparse.Namespace, pipeline: AnswerPipeline) -> int:
    # riwayat dari --prev hanya berisi pertanyaannya; jawaban sebelumnya tidak diketahui
    history = [Turn(question=scrub_pii(args.prev), answer="")] if args.prev else []
    final, record = pipeline.run(args.question, history, session_id=uuid.uuid4().hex)

    print(f"status   : {final.status}")
    print(f"jawaban  : {final.text}")
    print("sumber   :" + ("" if final.sources else " -"))
    for chunk in final.sources:
        print(f"  - {chunk.chunk_id} | {chunk.doc_title}")
    gate = record.gate
    print(f"gerbang  : skor {gate['score']} | ambang {gate['threshold']} | lolos {gate['passed']}")
    print(f"provider : {record.llm_provider or '-'} (status LLM {record.llm_status or '-'})")
    print(f"sitasi   : {list(record.citations)}")
    print(f"token    : {record.llm_usage}")
    print(f"cek angka: {record.fact_check}")
    if record.error_code:
        print(f"kode     : {record.error_code}")
    print("timings  : " + ", ".join(f"{k} {v:.3f} s" for k, v in final.timings.items()))
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config, env_file=args.env_file)
        if settings.app.mode != "dev":
            raise ConfigError(CFG_INVALID, "python -m mica.ask hanya untuk app.mode: dev")
        pipeline = make_pipeline(settings, kb_root=args.kb_root)
        return run(args, pipeline)
    except (ConfigError, KbLoadError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
