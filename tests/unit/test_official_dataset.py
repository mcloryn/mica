"""Set resmi (docs/DATASET.md): split berstrata deterministik, LOCK berversi, status.

Data sintetis di tmp_path; tidak ada file di data/eval/official/ yang dibuat."""

import json
from collections import Counter
from datetime import UTC, datetime

import pytest

from mica.eval.__main__ import main
from mica.eval.dataset import load_questions
from mica.eval.official import (
    DATASET_DOC,
    OfficialDatasetError,
    dev_quota,
    lock_dataset,
    lock_status,
    normalize_question,
    read_seed,
    split_questions,
    status_lines,
    stratum,
    units,
    write_split,
)


def synthetic(n_answerable=20, n_far=4, n_near=6, n_premise=3, n_chains=3):
    rows = []

    def add(qid, type_, **extra):
        rows.append({"qid": qid, "question": f"pertanyaan sintetis {qid}?", "type": type_,
                     "oos_level": None, "prev_qid": None, "gold_refs": [], **extra})  # fmt: skip

    for i in range(n_answerable):
        add(f"a{i:02d}", "answerable")
    for i in range(n_far):
        add(f"j{i:02d}", "out_of_kb", oos_level="jauh")
    for i in range(n_near):
        add(f"k{i:02d}", "out_of_kb", oos_level="dekat")
    for i in range(n_premise):
        add(f"p{i:02d}", "false_premise")
    for i in range(n_chains):  # akar + dua followup berantai
        add(f"c{i:02d}", "answerable")
        add(f"c{i:02d}f1", "followup", prev_qid=f"c{i:02d}")
        add(f"c{i:02d}f2", "followup", prev_qid=f"c{i:02d}f1")
    return rows


def _write(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")  # fmt: skip
    return path


def test_seed_is_read_from_dataset_doc():
    assert read_seed(DATASET_DOC) == 20261018


def test_dev_quota_is_30_percent_rounded_half_up():
    assert [dev_quota(n) for n in (1, 2, 3, 4, 5, 10, 20, 23)] == [0, 1, 1, 1, 2, 3, 6, 7]


def test_split_deterministic_and_strata_kept():
    rows = synthetic()
    a, b = split_questions(rows, 7), split_questions(rows, 7)
    assert a == b  # seed sama -> hasil sama
    assert split_questions(rows, 8)["dev"] != a["dev"]  # seed lain -> pembagian lain
    assert len(a["dev"]) + len(a["test"]) == len(rows)
    assert set(a["strata"]) == {"answerable", "out_of_kb:jauh", "out_of_kb:dekat",
                                "false_premise", "followup"}  # fmt: skip
    for name, c in a["strata"].items():
        assert c["dev_units"] == dev_quota(c["units"]), name
    dev_types = Counter(stratum(u) for u in units(a["dev"]))
    assert dev_types == {"answerable": 6, "out_of_kb:jauh": 1, "out_of_kb:dekat": 2,
                         "false_premise": 1, "followup": 1}  # fmt: skip


def test_followup_chain_stays_together_and_ids_remapped():
    out = split_questions(synthetic(), 20261018)
    for split in ("dev", "test"):
        ids = {q["qid"] for q in out[split]}
        for q in out[split]:
            assert q["qid"].startswith(f"o-{split}-") and q["split"] == split
            if q["prev_qid"] is not None:
                assert q["prev_qid"] in ids  # rantai tidak terpisah
    sources = [q["source_qid"] for q in out["dev"] + out["test"]]
    assert sorted(sources) == sorted(r["qid"] for r in synthetic())
    assert [q["qid"] for q in out["test"]][:2] == ["o-test-001", "o-test-002"]


def test_write_split_refuses_to_overwrite(tmp_path):
    src = _write(tmp_path / "resmi.jsonl", synthetic())
    out = tmp_path / "official"
    result = write_split(src, out)
    assert result["seed"] == 20261018
    assert len(load_questions(out / "dev.jsonl")) == len(result["dev"])
    assert len(load_questions(out / "test.jsonl")) == len(result["test"])
    before = (out / "test.jsonl").read_bytes()
    with pytest.raises(OfficialDatasetError, match="satu kali"):
        write_split(src, out)
    assert (out / "test.jsonl").read_bytes() == before


def test_lock_versions_and_status(tmp_path):
    test = _write(tmp_path / "test.jsonl", split_questions(synthetic(), 1)["test"])
    lock = tmp_path / "LOCK"
    assert lock_status(lock) == {"locked": False, "lock_path": lock.as_posix()}
    v1 = lock_dataset(test, "set uji awal", lock, commit="abc1234", git_dirty=False,
                      now=datetime(2026, 10, 18, tzinfo=UTC))  # fmt: skip
    assert v1["version"] == 1 and v1["seed"] == 20261018 and v1["reason"] == "set uji awal"
    assert v1["per_type"]["followup"] == 4 and sum(v1["per_type"].values()) == v1["n_questions"]
    with pytest.raises(OfficialDatasetError, match="sudah terkunci"):
        lock_dataset(test, "ulang", lock)
    with pytest.raises(OfficialDatasetError, match="--reason"):
        lock_dataset(test, "  ", lock)
    st = lock_status(lock)
    assert st["hash_ok"] and st["current"]["version"] == 1
    assert "hash file: COCOK" in status_lines(st)

    rows = load_questions(test)
    rows[0]["question"] = "diubah"
    _write(test, rows)
    st = lock_status(lock)
    assert not st["hash_ok"] and "hash file: TIDAK COCOK" in status_lines(st)
    v2 = lock_dataset(test, "koreksi salah ketik dari pembimbing", lock)
    data = json.loads(lock.read_text(encoding="utf-8"))
    assert [v["version"] for v in data["versions"]] == [1, 2] and v2["sha256"] != v1["sha256"]
    assert lock_status(lock)["hash_ok"]


def test_normalize_question():
    assert normalize_question("  Biaya kuliah, BERAPA?! ") == "biaya kuliah berapa"


def test_cli_dataset_commands(tmp_path, capsys):
    src = _write(tmp_path / "resmi.jsonl", synthetic())
    out = tmp_path / "official"
    lock = tmp_path / "LOCK"
    assert main(["--lock", str(lock), "dataset", "status", "--official-dir", str(out)]) == 0
    assert "LOCK: belum ada" in capsys.readouterr().out
    assert main(["dataset", "split", "--input", str(src), "--out-dir", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "seed 20261018" in printed and "followup | 3 | 1 | 2" in printed
    assert main(["dataset", "split", "--input", str(src), "--out-dir", str(out)]) == 2
    assert main(["--lock", str(lock), "dataset", "lock", "--dataset", str(out / "test.jsonl"),
                 "--reason", "set uji awal"]) == 0  # fmt: skip
    assert main(["--lock", str(lock), "dataset", "status"]) == 0
    assert "hash file: COCOK" in capsys.readouterr().out
