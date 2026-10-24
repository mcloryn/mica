"""Penjaga dataset vs KB aktif (Langkah 61).

data/eval/questions.jsonl dibuat dan dianotasi pada KB dev. Setelah kb.active_id pindah ke KB
resmi, perintah eval tidak boleh diam-diam menilai dataset itu pada KB lain: gold_chunk_ids dan
gold_refs-nya menunjuk chunk/dokumen KB dev, jadi Recall/MRR akan nol tanpa pesan yang jelas.

Dataset ditolak bila:
- pool_meta.json di folder dataset (ditulis annotate export) mencatat kb_id lain untuk file ini;
- ada gold_chunk_ids yang tidak ada di KB aktif;
- ada doc_id di gold_refs yang tidak ada di KB aktif;
- ada baris dengan field kb_id (KB tempat soal dibuat, Langkah 65) yang bukan KB aktif.
Dataset tanpa anotasi dan tanpa pool_meta lolos (misalnya set resmi sebelum dianotasi).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from mica.eval.annotate import POOL_META_FILE
from mica.eval.dataset import DatasetError, Question, load_questions, parse_gold_ref

_EXAMPLES = 3


class DatasetKbMismatch(DatasetError):
    pass


def _pool_meta_kb_id(dataset: Path) -> str | None:
    """kb_id dari pool_meta.json di folder dataset, bila pool itu dibuat dari file ini."""
    path = Path(dataset).parent / POOL_META_FILE
    if not path.exists():
        return None
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    recorded = str(meta.get("dataset") or "").replace("\\", "/")
    if Path(recorded).name != Path(dataset).name:
        return None
    kb_id = meta.get("kb_id")
    return str(kb_id) if kb_id else None


def check_dataset_kb(
    dataset: Path,
    items: Iterable[Question | dict[str, Any]],
    kb_id: str,
    chunk_ids: Iterable[str],
    doc_ids: Iterable[str],
) -> None:
    """DatasetKbMismatch bila dataset dibuat/dianotasi untuk KB selain kb_id."""
    problems: list[str] = []
    meta_kb = _pool_meta_kb_id(dataset)
    if meta_kb is not None and meta_kb != kb_id:
        problems.append(f"{POOL_META_FILE} mencatat kb_id {meta_kb}")

    known_chunks = set(chunk_ids)
    known_docs = set(doc_ids)
    missing_chunks: list[str] = []
    missing_docs: list[str] = []
    other_kb: list[str] = []
    for item in items:
        row_kb = item.get("kb_id")
        if row_kb is not None and row_kb != kb_id:
            other_kb.append(f"{item.get('qid')}: {row_kb}")
        for cid in item.get("gold_chunk_ids") or []:
            if cid not in known_chunks:
                missing_chunks.append(f"{item.get('qid')}: {cid}")
        for ref in item.get("gold_refs") or []:
            doc_id, _ = parse_gold_ref(str(ref))
            if doc_id not in known_docs:
                missing_docs.append(f"{item.get('qid')}: {doc_id}")
    if missing_chunks:
        problems.append(
            f"{len(missing_chunks)} gold_chunk_ids tidak ada di KB, mis. "
            + ", ".join(missing_chunks[:_EXAMPLES])
        )
    if missing_docs:
        problems.append(
            f"{len(missing_docs)} doc_id gold_refs tidak ada di KB, mis. "
            + ", ".join(missing_docs[:_EXAMPLES])
        )
    if other_kb:
        problems.append(
            f"{len(other_kb)} baris mencatat kb_id lain, mis. " + ", ".join(other_kb[:_EXAMPLES])
        )
    if problems:
        raise DatasetKbMismatch(
            f"dataset {Path(dataset).as_posix()} tidak cocok dengan KB aktif {kb_id}: "
            + "; ".join(problems)
            + ". Dataset ini dibuat untuk KB lain; buat/anotasi dataset untuk KB ini, "
            "atau set kb.active_id ke KB asal dataset."
        )


def check_dataset_files(dataset: Path, kb: Any, extra: Iterable[Path] = ()) -> None:
    """Muat dataset (dan file tambahan JSONL, mis. set ganti topik) lalu cek terhadap kb."""
    chunk_ids = [c.chunk_id for c in kb.chunks]
    doc_ids = {c.doc_id for c in kb.chunks}
    check_dataset_kb(dataset, load_questions(dataset), kb.kb_id, chunk_ids, doc_ids)
    for path in extra:
        rows = [
            json.loads(line)
            for line in Path(path).read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
        check_dataset_kb(path, rows, kb.kb_id, chunk_ids, doc_ids)
