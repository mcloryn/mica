"""scripts/compare_models.py: banding dua run atau lebih dari per_question.csv sintetis."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "compare_models", ROOT / "scripts" / "compare_models.py"
)
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)

FIELDS = [
    "qid",
    "type",
    "oos_level",
    "gate_score",
    "final_status_check_on",
    "answer",
    "error_code",
    "prompt_tokens",
    "completion_tokens",
    "llm_latency_s",
    "t_retrieval",
    "t_llm",
    "follow_up_topic",
    "items",
]
# qid, type, oos_level, gate, status A, status B
ROWS = [
    ("q1", "answerable", "", 0.70, "answered", "answered"),
    ("q2", "answerable", "", 0.50, "answered", "refused_llm"),
    ("q3", "out_of_kb", "jauh", 0.40, "refused_llm", "refused_llm"),
    ("q4", "out_of_kb", "dekat", 0.60, "answered", "false_premise"),
    ("q5", "false_premise", "", 0.65, "answered", "false_premise"),
]


def _write_run(path: Path, which: int) -> Path:
    path.mkdir()
    with open(path / "per_question.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for i, (q, kind, oos, gate, a, b) in enumerate(ROWS):
            status = (a, b)[which]
            w.writerow(
                {
                    "qid": q,
                    "type": kind,
                    "oos_level": oos,
                    "gate_score": gate,
                    "final_status_check_on": status,
                    "answer": f"{q}-{status}",
                    "error_code": "LLM_BAD_OUTPUT" if (which, q) == (1, "q2") else "",
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "llm_latency_s": f"{i + 1:.1f}",
                    "t_retrieval": "0.5",
                    "t_llm": "60.0",  # memuat tunggu pembatas laju: tidak dipakai
                    "follow_up_topic": "Biaya" if q in ("q1", "q3") else "",
                    "items": "A; B; C" if q in ("q1", "q2") else "",
                }
            )
    return path


def test_compare_models_end_to_end(tmp_path: Path) -> None:
    run_a = _write_run(tmp_path / "a", 0)
    run_b = _write_run(tmp_path / "b", 1)
    notes = tmp_path / "notes.csv"
    notes.write_text("id,catatan\nq4,isi menolak\n", encoding="utf-8")
    argv = [str(run_a), str(run_b), "--labels", "A", "B", "--thresholds", "0.55"]
    argv += ["--out-dir", str(tmp_path), "--prefix", "cmp", "--notes", str(notes)]
    assert cm.main(argv) == 0

    with open(tmp_path / "cmp.csv", encoding="utf-8") as f:
        rows = {r["id"]: r for r in csv.DictReader(f)}
    assert list(rows["q1"])[-1] == "catatan"
    assert rows["q2"]["status_A_g055"] == "refused_gate"
    assert (rows["q2"]["benar_A"], rows["q2"]["benar_B"]) == ("1", "0")
    assert (rows["q4"]["benar_A"], rows["q4"]["benar_B"]) == ("0", "0")
    assert rows["q4"]["catatan"] == "isi menolak"
    assert (rows["q5"]["benar_A"], rows["q5"]["benar_B"]) == ("gagal", "terbaik")

    with open(tmp_path / "cmp-summary.csv", encoding="utf-8") as f:
        summ = {(r["model"], r["threshold"]): r for r in csv.DictReader(f)}
    a_null, a_055, b_null = summ["A", "null"], summ["A", "0.55"], summ["B", "null"]
    assert a_null["salah_tolak"] == "0/2" and a_055["salah_tolak"] == "1/2"
    assert a_null["tolak_benar"] == "1/2" and a_null["tolak_benar_jauh"] == "1/1"
    assert b_null["gagal_skema"] == "1" and b_null["premis_terbaik"] == "1"
    # ambang 0.55 menahan q2 dan q3: hanya 3 pertanyaan memanggil LLM
    assert a_055["llm_dipanggil"] == "3" and a_055["total_tokens"] == "330"
    assert a_null["llm_latency_p50_s"] == "3.000" and a_null["llm_latency_p95_s"] == "4.800"
    assert a_null["pipeline_latency_p50_s"] == "3.500"
    assert a_null["pipeline_latency_p95_s"] == "5.300"
    # q1 answered (tampil), q3 refused_llm (tidak tampil); ambang 0.55 menahan q3 sebelum LLM
    assert (a_null["follow_up_tidak_null"], a_null["follow_up_tampil"]) == ("2", "1")
    assert (a_055["follow_up_tidak_null"], a_055["follow_up_tampil"]) == ("1", "1")
    # items: q1 dan q2 answered di A (ambang null); ambang 0.55 menahan q2
    assert (a_null["items_tidak_kosong"], a_055["items_tidak_kosong"]) == ("2", "1")


def test_compare_models_without_notes_has_no_catatan(tmp_path: Path) -> None:
    runs = {"A": cm.load_run(_write_run(tmp_path / "a", 0))}
    rows = cm.per_question(runs, [None])
    assert "catatan" not in rows[0]


def test_compare_models_rejects_mismatched_ids() -> None:
    runs = {"A": {"q1": {}}, "B": {"q2": {}}}
    with pytest.raises(ValueError):
        cm.per_question(runs, [None])


def test_compare_models_three_runs_and_429_from_run_json(tmp_path: Path) -> None:
    import json

    runs = [_write_run(tmp_path / n, w) for n, w in (("a", 0), ("b", 1), ("c", 1))]
    calls = {"retries_429": 3, "wait_429_s": 30.0}
    (runs[2] / "run.json").write_text(json.dumps({"llm_calls": calls}), encoding="utf-8")
    argv = [
        *map(str, runs),
        "--labels",
        "A",
        "B",
        "C",
        "--out-dir",
        str(tmp_path),
        "--prefix",
        "c3",
    ]
    assert cm.main(argv) == 0
    with open(tmp_path / "c3.csv", encoding="utf-8") as f:
        rows = {r["id"]: r for r in csv.DictReader(f)}
    assert rows["q5"]["status_C"] == "false_premise" and rows["q5"]["benar_A"] == "gagal"
    with open(tmp_path / "c3-summary.csv", encoding="utf-8") as f:
        summ = {r["model"]: r for r in csv.DictReader(f)}
    assert list(summ) == ["A", "B", "C"]
    assert (summ["C"]["retries_429"], summ["C"]["wait_429_s"]) == ("3", "30.0")
    assert summ["A"]["retries_429"] == ""


def test_compare_models_rejects_label_count(tmp_path: Path) -> None:
    runs = [str(_write_run(tmp_path / n, 0)) for n in ("a", "b")]
    with pytest.raises(SystemExit):
        cm.main([*runs, "--labels", "A", "--out-dir", str(tmp_path), "--prefix", "x"])
