"""M-12 annotate: pooling kandidat untuk anotasi relevansi manual, lalu impor hasilnya.

export: per pertanyaan answerable/followup, kandidat = gabungan top-N bm25, dense, dan hybrid
ditambah chunk yang cocok dengan gold_refs. Baris diurutkan menurut urutan chunk di KB (bukan
peringkat retriever) supaya anotator tidak terpengaruh peringkat.
import: kolom relevant (1/0) -> gold_chunk_ids di questions.jsonl.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mica.config import Settings
from mica.eval.dataset import (
    DatasetError,
    Question,
    load_questions,
    parse_gold_ref,
    retrieval_query,
    save_questions,
)
from mica.kb.index import KnowledgeBase
from mica.rag.retriever import (
    Bm25Retriever,
    DenseRetriever,
    EmbedderFactory,
    HybridRrfRetriever,
    Retriever,
    embedder_for_kb,
)

POOL_DEPTH = 10
POOL_RETRIEVERS = ("bm25", "dense", "hybrid")
POOL_TYPES = ("answerable", "followup")
POOL_COLUMNS = (
    "qid",
    "question",
    "reference_answer",
    "chunk_id",
    "doc_id",
    "section",
    "from_gold_ref",
    "text",
    "relevant",
)
POOL_META_FILE = "pool_meta.json"


@dataclass(frozen=True)
class PoolResult:
    rows: int
    questions: int
    unmatched_gold_refs: list[str]  # "qid: ref" yang tidak cocok dengan chunk mana pun


def _pool_retrievers(
    settings: Settings, kb: KnowledgeBase, embedder_factory: EmbedderFactory | None
) -> dict[str, Retriever]:
    rag = settings.rag
    if rag.rrf_k is None or rag.candidates_per_retriever is None:
        raise ValueError("rag.rrf_k dan rag.candidates_per_retriever wajib diisi untuk pooling")
    bm25 = Bm25Retriever(kb)
    dense = DenseRetriever(kb, embedder_for_kb(kb, embedder_factory))
    hybrid = HybridRrfRetriever(kb.chunks, [bm25, dense], rag.rrf_k, rag.candidates_per_retriever)
    return {"bm25": bm25, "dense": dense, "hybrid": hybrid}


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export_pool(
    settings: Settings,
    kb: KnowledgeBase,
    dataset: Path,
    out: Path,
    embedder_factory: EmbedderFactory | None = None,
    depth: int = POOL_DEPTH,
    force: bool = False,
) -> PoolResult:
    out = Path(out)
    meta_path = out.parent / POOL_META_FILE
    if out.exists() and not force:
        # pool.csv bisa berisi anotasi manual; jangan ditimpa diam-diam
        raise FileExistsError(f"{out} sudah ada; pakai --force untuk menimpa")

    questions = load_questions(dataset)
    by_qid = {q["qid"]: q for q in questions}
    retrievers = _pool_retrievers(settings, kb, embedder_factory)
    position = {c.chunk_id: i for i, c in enumerate(kb.chunks)}
    by_ref: dict[tuple[str, str], list[str]] = {}
    for c in kb.chunks:
        by_ref.setdefault((c.doc_id, c.section), []).append(c.chunk_id)
    chunk_by_id = {c.chunk_id: c for c in kb.chunks}

    rows: list[dict[str, str]] = []
    unmatched: list[str] = []
    pooled_questions = 0
    for q in questions:
        if q["type"] not in POOL_TYPES:
            continue
        pooled_questions += 1
        query = retrieval_query(q, by_qid)
        candidates: set[str] = set()
        for retriever in retrievers.values():
            candidates.update(h.chunk.chunk_id for h in retriever.search(query, depth))
        gold: set[str] = set()
        for ref in q.get("gold_refs", []):
            matched = by_ref.get(parse_gold_ref(ref), [])
            if not matched:
                unmatched.append(f"{q['qid']}: {ref}")
            gold.update(matched)
        for chunk_id in sorted(candidates | gold, key=position.__getitem__):
            c = chunk_by_id[chunk_id]
            rows.append(
                {
                    "qid": q["qid"],
                    "question": q["question"],
                    "reference_answer": q.get("reference_answer") or "",
                    "chunk_id": c.chunk_id,
                    "doc_id": c.doc_id,
                    "section": c.section,
                    "from_gold_ref": "ya" if chunk_id in gold else "tidak",
                    "text": c.text,
                    "relevant": "",
                }
            )

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=POOL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    meta = {
        "kb_id": kb.kb_id,
        "config_hash": settings.config_hash(),
        "retrievers": list(POOL_RETRIEVERS),
        "depth": depth,
        "rrf_k": settings.rag.rrf_k,
        "candidates_per_retriever": settings.rag.candidates_per_retriever,
        "embedder": {
            "model": kb.manifest["embedder"]["model"],
            "revision": kb.manifest["embedder"]["revision"],
        },
        "dataset": str(dataset),
        "dataset_sha256": _sha256(dataset),
        "pool_file": out.name,
        "rows": len(rows),
        "questions": pooled_questions,
        "created_at": datetime.now().astimezone().isoformat(),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return PoolResult(rows=len(rows), questions=pooled_questions, unmatched_gold_refs=unmatched)


def _read_pool(pool: Path) -> list[dict[str, str]]:
    try:
        text = Path(pool).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DatasetError(
            f"{pool} bukan UTF-8; simpan dari Excel sebagai 'CSV UTF-8 (Comma delimited)'"
        ) from exc
    # Excel dengan pengaturan regional Indonesia menyimpan CSV memakai pemisah titik koma.
    header = text.split("\n", 1)[0]
    delimiter = ";" if header.count(";") > header.count(",") else ","
    reader = csv.DictReader(text.splitlines(keepends=True), delimiter=delimiter)
    missing = [c for c in ("qid", "chunk_id", "relevant") if c not in (reader.fieldnames or [])]
    if missing:
        raise DatasetError(f"{pool}: kolom {missing} tidak ada")
    return list(reader)


def import_pool(dataset: Path, pool: Path) -> dict[str, list[str]]:
    """Isi gold_chunk_ids dari kolom relevant; questions.jsonl ditulis ulang hanya bila valid."""
    questions = load_questions(dataset)
    by_qid = {q["qid"]: q for q in questions}
    rows = _read_pool(pool)

    errors: list[str] = []
    gold: dict[str, list[str]] = {}
    for n, row in enumerate(rows, start=2):  # baris 1 = judul kolom
        qid, chunk_id = row["qid"].strip(), row["chunk_id"].strip()
        value = (row["relevant"] or "").strip()
        if qid not in by_qid:
            errors.append(f"baris {n}: qid {qid!r} tidak ada di dataset")
            continue
        gold.setdefault(qid, [])
        if value == "":
            errors.append(f"baris {n}: relevant kosong (qid {qid}, {chunk_id})")
        elif value not in ("0", "1"):
            errors.append(f"baris {n}: relevant harus 1 atau 0, bukan {value!r} (qid {qid})")
        elif value == "1" and chunk_id not in gold[qid]:
            gold[qid].append(chunk_id)

    for q in questions:
        if q["type"] in POOL_TYPES and q["qid"] not in gold:
            errors.append(f"qid {q['qid']}: tidak ada di pool")
        elif q["type"] == "answerable" and not gold.get(q["qid"]):
            errors.append(f"qid {q['qid']}: answerable tanpa satu pun chunk relevan")
    if errors:
        raise DatasetError("anotasi belum bisa diimpor:\n  " + "\n  ".join(errors))

    updated: list[Question] = []
    for q in questions:
        if q["qid"] in gold:
            q = {**q, "gold_chunk_ids": gold[q["qid"]]}
        updated.append(q)
    save_questions(dataset, updated)
    return gold
