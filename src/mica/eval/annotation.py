"""M-12: ringkasan anotasi halusinasi dari annotate_generation.csv satu run generation (E-02, E-04).

Kolom benar dan halusinasi wajib 0 atau 1 di setiap baris; nilai lain atau kosong ditolak.
Tingkat halusinasi = halusinasi / jumlah baris, dengan interval kepercayaan 95% Wilson.
Nilai anotasi hanya dibaca, tidak pernah diubah.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

ANNOTATION_FILE = "annotate_generation.csv"
SUMMARY_FILE = "annotation_summary.json"
SUGGESTION_FILE = "annotate_generation_saran_claude.csv"
COMPARED_COLUMNS = ("benar", "halusinasi", "catatan")
Z_95 = 1.959963984540054


class AnnotationError(ValueError):
    pass


def wilson_interval(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Interval skor Wilson untuk proporsi k/n; n = 0 ditolak."""
    if n <= 0:
        raise AnnotationError("Wilson: n harus > 0")
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    # k = 0 dan k = n diberi batas tepat 0 dan 1 (tanpa sisa pembulatan float)
    low = 0.0 if k == 0 else max(0.0, center - half)
    high = 1.0 if k == n else min(1.0, center + half)
    return low, high


def load_annotations(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise AnnotationError(f"{path}: tidak ada baris")
    bad = [
        f"{r.get('qid', '?')}.{col}={r.get(col)!r}"
        for r in rows
        for col in ("benar", "halusinasi")
        if (r.get(col) or "").strip() not in ("0", "1")
    ]
    if bad:
        raise AnnotationError(f"{path}: nilai harus 0 atau 1: {', '.join(bad)}")
    return rows


def summarize(rows: list[dict[str, str]]) -> dict[str, Any]:
    n = len(rows)
    correct = sum(int(r["benar"]) for r in rows)
    halluc = sum(int(r["halusinasi"]) for r in rows)
    low, high = wilson_interval(halluc, n)
    return {
        "n": n,
        "benar": correct,
        "halusinasi": halluc,
        "hallucination_rate": halluc / n,
        "hallucination_rate_ci95_wilson": [low, high],
        "halusinasi_qids": [r["qid"] for r in rows if r["halusinasi"].strip() == "1"],
        "salah_qids": [r["qid"] for r in rows if r["benar"].strip() == "0"],
    }


def compare_suggestions(run_dir: Path) -> dict[str, Any]:
    """Hitung baris annotate_generation.csv yang identik dengan saran_<kolom> di file saran Claude.

    Pasangan baris lewat qid; qid harus sama persis di kedua file. Teks dibandingkan setelah
    spasi di ujung dibuang. Hasil: jumlah identik per kolom dan qid yang berbeda.
    """
    final = {r["qid"]: r for r in load_annotations(run_dir / ANNOTATION_FILE)}
    with (run_dir / SUGGESTION_FILE).open(encoding="utf-8-sig", newline="") as f:
        saran = {r["qid"]: r for r in csv.DictReader(f)}
    if set(final) != set(saran):
        missing = sorted(set(final) ^ set(saran))
        raise AnnotationError(f"{run_dir}: qid berbeda antara anotasi dan saran: {missing}")
    result: dict[str, Any] = {"n": len(final)}
    for col in COMPARED_COLUMNS:
        differ = [
            q
            for q in final
            if (final[q].get(col) or "").strip() != (saran[q].get(f"saran_{col}") or "").strip()
        ]
        result[col] = {"identical": len(final) - len(differ), "different_qids": differ}
    return result


def run_annotation(run_dir: Path) -> dict[str, Any]:
    """Baca annotate_generation.csv di run_dir, tulis annotation_summary.json, kembalikan isinya."""
    rows = load_annotations(run_dir / ANNOTATION_FILE)
    summary: dict[str, Any] = {"run": run_dir.as_posix(), "source": ANNOTATION_FILE}
    run_json = run_dir / "run.json"
    if run_json.exists():
        meta = json.loads(run_json.read_text(encoding="utf-8"))
        summary["experiment"] = meta.get("experiment")
        summary["split"] = meta.get("split")
        summary["model"] = (meta.get("llm") or {}).get("model")
    summary.update(summarize(rows))
    (run_dir / SUMMARY_FILE).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary
