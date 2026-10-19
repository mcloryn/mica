import csv
import json

import pytest

from mica.eval.__main__ import main
from mica.eval.annotation import (
    AnnotationError,
    load_annotations,
    run_annotation,
    summarize,
    wilson_interval,
)
from mica.eval.generation import ANNOTATE_COLUMNS


def _write(path, values):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ANNOTATE_COLUMNS)
        w.writeheader()
        for i, (benar, halu) in enumerate(values, start=1):
            row = dict.fromkeys(ANNOTATE_COLUMNS, "")
            row.update(qid=f"d{i:03d}", benar=benar, halusinasi=halu)
            w.writerow(row)


def test_wilson_known_values():
    # nilai rujukan Wilson 95%: 0/28 -> [0, 0.1206]; 1/28 -> [0.0063, 0.1771]; 5/10
    low, high = wilson_interval(0, 28)
    assert low == 0.0
    assert high == pytest.approx(0.12064, abs=1e-4)
    low, high = wilson_interval(1, 28)
    assert low == pytest.approx(0.00633, abs=1e-4)
    assert high == pytest.approx(0.17710, abs=1e-4)
    low, high = wilson_interval(5, 10)
    assert low == pytest.approx(0.23659, abs=1e-4)
    assert high == pytest.approx(0.76341, abs=1e-4)


def test_wilson_rejects_zero_n():
    with pytest.raises(AnnotationError):
        wilson_interval(0, 0)


def test_summarize_counts(tmp_path):
    path = tmp_path / "annotate_generation.csv"
    _write(path, [("1", "0"), ("0", "1"), ("1", "1"), ("1", "0")])
    s = summarize(load_annotations(path))
    assert (s["n"], s["benar"], s["halusinasi"]) == (4, 3, 2)
    assert s["hallucination_rate"] == 0.5
    assert s["halusinasi_qids"] == ["d002", "d003"]
    assert s["salah_qids"] == ["d002"]


@pytest.mark.parametrize("bad", ["", "2", "ya", " "])
def test_invalid_values_rejected(tmp_path, bad):
    path = tmp_path / "annotate_generation.csv"
    _write(path, [("1", "0"), ("1", bad)])
    with pytest.raises(AnnotationError, match="d002.halusinasi"):
        load_annotations(path)


def test_run_annotation_writes_summary_and_keeps_csv(tmp_path):
    path = tmp_path / "annotate_generation.csv"
    _write(path, [("1", "0"), ("1", "1")])
    before = path.read_bytes()
    (tmp_path / "run.json").write_text(
        json.dumps({"experiment": "E-04", "split": "dev", "llm": {"model": "m"}}), encoding="utf-8"
    )
    s = run_annotation(tmp_path)
    saved = json.loads((tmp_path / "annotation_summary.json").read_text(encoding="utf-8"))
    assert saved == s
    assert (s["experiment"], s["split"], s["model"], s["halusinasi"]) == ("E-04", "dev", "m", 1)
    assert path.read_bytes() == before


def test_cli_annotation(tmp_path, capsys):
    _write(tmp_path / "annotate_generation.csv", [("1", "0")])
    assert main(["annotation", "--run", str(tmp_path)]) == 0
    assert "halusinasi=0" in capsys.readouterr().out
    _write(tmp_path / "annotate_generation.csv", [("1", "")])
    assert main(["annotation", "--run", str(tmp_path)]) == 2
