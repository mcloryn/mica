"""M-12: metrik E-02 dari label per jawaban (Langkah 65, docs/EVAL-DEV-OFFICIAL.md).

labels_claude.csv di folder run generation berisi satu baris per soal dengan label salah satu
LABELS. Label penolakan wajib cocok dengan status (ditolak gerbang 1, 2, atau 3); label lain hanya
untuk jawaban yang tidak ditolak. Metrik mengikuti pra-registrasi:

- % benar = benar / soal terjawab (answerable);
- % halusinasi = halusinasi / jawaban yang tidak ditolak;
- % penolakan tepat = penolakan-tepat / soal tidak terjawab (out_of_kb);
- % penolakan keliru = penolakan-keliru / soal terjawab.

Kolom hanya_di_potongan_tak_dikutip (0/1) menandai jawaban yang klaimnya hanya didukung potongan
yang diambil tetapi tidak dikutip; halusinasi versi SDD 2.4 = halusinasi + baris bertanda itu.
Nilai label hanya dibaca, tidak pernah diubah.
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from typing import Any

from mica.eval.annotation import AnnotationError, wilson_interval

LABELS_FILE = "labels_claude.csv"
LABELS_SUMMARY_FILE = "labels_summary.json"
LABELS = ("benar", "salah", "halusinasi", "penolakan-tepat", "penolakan-keliru")
GATE_STAGE = {"refused_gate": 1, "refused_llm": 2, "refused_check": 3}
LABEL_COLUMNS = (
    "qid",
    "type",
    "topic",
    "question",
    "status",
    "gate_stage",
    "dense_at1",
    "answer",
    "reference_answer",
    "cited_chunks",
    "label",
    "hanya_di_potongan_tak_dikutip",
    "alasan",
)
TYPES = ("answerable", "out_of_kb")


def _check_row(r: dict[str, str]) -> str | None:
    """Pesan kesalahan untuk satu baris, atau None bila baris konsisten."""
    label, status, kind = r.get("label", "").strip(), r.get("status", "").strip(), r.get("type")
    if label not in LABELS:
        return f"label {label!r} bukan salah satu dari {LABELS}"
    if kind not in TYPES:
        return f"type {kind!r} bukan salah satu dari {TYPES}"
    if (r.get("hanya_di_potongan_tak_dikutip") or "").strip() not in ("0", "1"):
        return "hanya_di_potongan_tak_dikutip harus 0 atau 1"
    if not (r.get("alasan") or "").strip():
        return "alasan kosong"
    if status in GATE_STAGE:
        expected = "penolakan-tepat" if kind == "out_of_kb" else "penolakan-keliru"
        if label != expected:
            return f"status {status} pada soal {kind} harus berlabel {expected}"
    elif label.startswith("penolakan"):
        return f"label {label} hanya untuk jawaban yang ditolak (status {status})"
    elif label == "benar" and kind != "answerable":
        return "label benar hanya untuk soal answerable"
    return None


def load_labels(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise AnnotationError(f"{path}: tidak ada baris")
    errors = [f"{r.get('qid', '?')}: {msg}" for r in rows if (msg := _check_row(r))]
    qids = [r.get("qid") for r in rows]
    if len(set(qids)) != len(qids):
        errors.append("qid ganda")
    if errors:
        raise AnnotationError(f"{path}: label tidak valid: " + "; ".join(errors))
    return rows


def _rate(k: int, n: int) -> dict[str, Any]:
    if n == 0:
        return {"k": k, "n": n, "rate": None, "ci95_wilson": None}
    return {"k": k, "n": n, "rate": k / n, "ci95_wilson": list(wilson_interval(k, n))}


def _spread(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
        "values": sorted(values),
    }


def summarize_labels(rows: list[dict[str, str]]) -> dict[str, Any]:
    answerable = [r for r in rows if r["type"] == "answerable"]
    unanswerable = [r for r in rows if r["type"] == "out_of_kb"]
    answered = [r for r in rows if r["status"].strip() not in GATE_STAGE]

    def count(label: str, group: list[dict[str, str]]) -> int:
        return sum(r["label"].strip() == label for r in group)

    def qids(label: str) -> list[str]:
        return [r["qid"] for r in rows if r["label"].strip() == label]

    halluc_sdd = sum(
        r["label"].strip() == "halusinasi" or r["hanya_di_potongan_tak_dikutip"].strip() == "1"
        for r in answered
    )
    stages: dict[str, dict[str, int]] = {}
    for kind, group in (("answerable", answerable), ("out_of_kb", unanswerable)):
        stages[kind] = {"lolos": 0, "gerbang_1": 0, "gerbang_2": 0, "gerbang_3": 0}
        for r in group:
            stage = GATE_STAGE.get(r["status"].strip())
            stages[kind]["lolos" if stage is None else f"gerbang_{stage}"] += 1

    def scores(group: list[dict[str, str]]) -> list[float]:
        return [float(r["dense_at1"]) for r in group if (r.get("dense_at1") or "").strip()]

    return {
        "n": len(rows),
        "n_answerable": len(answerable),
        "n_out_of_kb": len(unanswerable),
        "counts": {label: count(label, rows) for label in LABELS},
        "benar": _rate(count("benar", answerable), len(answerable)),
        "halusinasi": _rate(count("halusinasi", answered), len(answered)),
        "halusinasi_sdd_dikutip": _rate(halluc_sdd, len(answered)),
        "penolakan_tepat": _rate(count("penolakan-tepat", unanswerable), len(unanswerable)),
        "penolakan_keliru": _rate(count("penolakan-keliru", answerable), len(answerable)),
        "qids": {label: qids(label) for label in LABELS},
        "gate_stages": stages,
        "dense_at1": {"answerable": scores(answerable), "out_of_kb": scores(unanswerable)},
        "dense_at1_spread": {
            "answerable": _spread(scores(answerable)),
            "out_of_kb": _spread(scores(unanswerable)),
        },
    }


def run_labels(run_dir: Path) -> dict[str, Any]:
    """Baca labels_claude.csv di run_dir, tulis labels_summary.json, kembalikan isinya."""
    run_dir = Path(run_dir)
    rows = load_labels(run_dir / LABELS_FILE)
    summary: dict[str, Any] = {"run": run_dir.as_posix(), "source": LABELS_FILE}
    summary.update(summarize_labels(rows))
    (run_dir / LABELS_SUMMARY_FILE).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary
