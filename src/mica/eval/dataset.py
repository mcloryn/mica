"""M-12: membaca, memvalidasi, dan menulis data/eval/questions.jsonl (SDD 6.3).

Setiap baris disimpan sebagai dict supaya field tambahan (misalnya gold_refs) tetap utuh saat
file ditulis ulang.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

QUESTION_TYPES = ("answerable", "out_of_kb", "false_premise", "followup")
# seberapa dekat pertanyaan di luar KB dengan topik PMB: wajib untuk out_of_kb saja
OOS_LEVELS = ("jauh", "dekat")
GOLD_REF_SEP = "::"

Question = dict[str, Any]


class DatasetError(Exception):
    pass


def parse_gold_ref(ref: str) -> tuple[str, str]:
    """"<doc_id>::<judul bagian>" -> (doc_id, section)."""
    doc_id, sep, section = ref.partition(GOLD_REF_SEP)
    if not sep or not doc_id.strip() or not section.strip():
        raise ValueError(f"gold_ref harus berformat '<doc_id>::<judul bagian>': {ref!r}")
    return doc_id.strip(), section.strip()


def validate_questions(questions: list[Question]) -> None:
    errors: list[str] = []
    seen: set[str] = set()
    for n, q in enumerate(questions, start=1):
        qid = q.get("qid")
        where = f"baris {n} (qid {qid!r})"
        if not isinstance(qid, str) or not qid.strip():
            errors.append(f"{where}: qid kosong")
        elif qid in seen:
            errors.append(f"{where}: qid ganda")
        else:
            seen.add(qid)
        if not isinstance(q.get("question"), str) or not q["question"].strip():
            errors.append(f"{where}: question kosong")
        if q.get("type") not in QUESTION_TYPES:
            errors.append(f"{where}: type {q.get('type')!r} bukan salah satu dari {QUESTION_TYPES}")
        if q.get("type") == "followup" and not q.get("prev_qid"):
            errors.append(f"{where}: followup wajib punya prev_qid")
        oos_level = q.get("oos_level")
        if q.get("type") == "out_of_kb":
            if oos_level not in OOS_LEVELS:
                errors.append(f"{where}: out_of_kb wajib punya oos_level, salah satu {OOS_LEVELS}")
        elif oos_level is not None:
            errors.append(f"{where}: oos_level hanya untuk out_of_kb, harus null atau tidak ada")
        refs = q.get("gold_refs", [])
        if not isinstance(refs, list):
            errors.append(f"{where}: gold_refs harus list")
        else:
            for ref in refs:
                try:
                    parse_gold_ref(str(ref))
                except ValueError as exc:
                    errors.append(f"{where}: {exc}")

    qids = {q.get("qid") for q in questions}
    for n, q in enumerate(questions, start=1):
        prev = q.get("prev_qid")
        if prev is None:
            continue
        if prev not in qids:
            errors.append(f"baris {n} (qid {q.get('qid')!r}): prev_qid {prev!r} tidak ada")
        elif prev == q.get("qid"):
            errors.append(f"baris {n} (qid {q.get('qid')!r}): prev_qid menunjuk dirinya sendiri")
    if errors:
        raise DatasetError("dataset tidak valid:\n  " + "\n  ".join(errors))


def load_questions(path: Path) -> list[Question]:
    questions: list[Question] = []
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise DatasetError(f"gagal membaca {path}: {exc}") from exc
    for n, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{path} baris {n}: bukan JSON valid ({exc.msg})") from exc
        if not isinstance(row, dict):
            raise DatasetError(f"{path} baris {n}: harus objek JSON")
        questions.append(row)
    validate_questions(questions)
    return questions


def save_questions(path: Path, questions: list[Question]) -> None:
    """Tulis ke file sementara lalu ganti, supaya dataset tidak setengah tertulis bila gagal."""
    validate_questions(questions)
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def retrieval_query(question: Question, by_qid: dict[str, Question]) -> str:
    """Kueri retrieval sesuai followup_mode concat (SDD 7.3): pertanyaan prev_qid + " " + pertanyaan."""
    prev = question.get("prev_qid")
    if question.get("type") == "followup" and prev:
        return by_qid[prev]["question"] + " " + question["question"]
    return question["question"]
