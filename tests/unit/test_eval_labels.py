"""Langkah 65: metrik E-02 dari label per jawaban (mica.eval.labels)."""

import csv
import json

import pytest

from mica.eval import __main__ as eval_cli
from mica.eval.annotation import AnnotationError
from mica.eval.labels import (
    LABEL_COLUMNS,
    LABELS_FILE,
    LABELS_SUMMARY_FILE,
    load_labels,
    summarize_labels,
)


def _row(qid, kind, status, label, dense="0.6", flag="0", alasan="sesuai potongan"):
    row = dict.fromkeys(LABEL_COLUMNS, "")
    row.update(qid=qid, type=kind, status=status, label=label, dense_at1=dense,
               hanya_di_potongan_tak_dikutip=flag, alasan=alasan)  # fmt: skip
    return row


def _write(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LABEL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


ROWS = [
    _row("a1", "answerable", "answered", "benar", "0.70"),
    _row("a2", "answerable", "answered", "halusinasi", "0.65"),
    _row("a3", "answerable", "refused_gate", "penolakan-keliru", "0.45"),
    _row("a4", "answerable", "answered", "salah", "0.60", flag="1"),
    _row("u1", "out_of_kb", "refused_llm", "penolakan-tepat", "0.55"),
    _row("u2", "out_of_kb", "answered", "halusinasi", "0.58"),
]


def test_summary_follows_preregistration():
    s = summarize_labels(ROWS)
    assert (s["benar"]["k"], s["benar"]["n"]) == (1, 4)
    assert (s["halusinasi"]["k"], s["halusinasi"]["n"]) == (2, 4)  # 4 jawaban tidak ditolak
    assert (s["halusinasi_sdd_dikutip"]["k"], s["halusinasi_sdd_dikutip"]["n"]) == (3, 4)
    assert (s["penolakan_tepat"]["k"], s["penolakan_tepat"]["n"]) == (1, 2)
    assert (s["penolakan_keliru"]["k"], s["penolakan_keliru"]["n"]) == (1, 4)
    assert s["qids"]["halusinasi"] == ["a2", "u2"]
    assert s["gate_stages"]["answerable"] == {
        "lolos": 3, "gerbang_1": 1, "gerbang_2": 0, "gerbang_3": 0
    }  # fmt: skip
    assert s["gate_stages"]["out_of_kb"]["gerbang_2"] == 1
    assert s["dense_at1_spread"]["answerable"]["min"] == 0.45
    assert s["dense_at1_spread"]["out_of_kb"]["median"] == pytest.approx(0.565)
    low, high = s["benar"]["ci95_wilson"]
    assert 0 < low < 0.25 < high < 1


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (_row("x", "answerable", "answered", "oke"), "bukan salah satu"),
        (_row("x", "answerable", "refused_gate", "benar"), "penolakan-keliru"),
        (_row("x", "out_of_kb", "refused_check", "penolakan-keliru"), "penolakan-tepat"),
        (
            _row("x", "answerable", "answered", "penolakan-keliru"),
            "hanya untuk jawaban yang ditolak",
        ),
        (_row("x", "out_of_kb", "answered", "benar"), "hanya untuk soal answerable"),
        (_row("x", "answerable", "answered", "benar", flag=""), "0 atau 1"),
        (_row("x", "answerable", "answered", "benar", alasan=" "), "alasan kosong"),
        (_row("x", "followup", "answered", "benar"), "type"),
    ],
)
def test_inconsistent_labels_rejected(tmp_path, row, message):
    with pytest.raises(AnnotationError, match=message):
        load_labels(_write(tmp_path / LABELS_FILE, [row]))


def test_duplicate_qid_rejected(tmp_path):
    rows = [ROWS[0], ROWS[0]]
    with pytest.raises(AnnotationError, match="qid ganda"):
        load_labels(_write(tmp_path / LABELS_FILE, rows))


def test_cli_writes_summary(tmp_path, capsys):
    _write(tmp_path / LABELS_FILE, ROWS)
    assert eval_cli.main(["labels", "--run", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "benar: 1/4 = 0.2500" in out and "penolakan_tepat: 1/2" in out
    summary = json.loads((tmp_path / LABELS_SUMMARY_FILE).read_text(encoding="utf-8"))
    assert summary["counts"]["halusinasi"] == 2


def test_cli_rejects_invalid_labels(tmp_path, capsys):
    _write(tmp_path / LABELS_FILE, [_row("x", "answerable", "answered", "oke")])
    assert eval_cli.main(["labels", "--run", str(tmp_path)]) == 2
    assert "label tidak valid" in capsys.readouterr().err
