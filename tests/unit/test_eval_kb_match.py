import json
from pathlib import Path

import pytest
from kb_samples import FakeEmbedder, make_kb_folder

from mica.config import load_settings
from mica.eval import __main__ as eval_cli
from mica.eval.kb_match import DatasetKbMismatch, check_dataset_files, check_dataset_kb
from mica.kb.index import build_kb, load_kb

DEV_YAML = Path(__file__).resolve().parents[2] / "config" / "dev.yaml"
REPO_DATASET = Path(__file__).resolve().parents[2] / "data" / "eval" / "questions.jsonl"


def _q(qid, gold_chunk_ids=(), gold_refs=()):
    return {
        "qid": qid,
        "question": f"pertanyaan {qid}",
        "type": "answerable",
        "topic": "x",
        "gold_chunk_ids": list(gold_chunk_ids),
        "gold_refs": list(gold_refs),
        "reference_answer": "",
        "split": "dev",
        "prev_qid": None,
    }


def _write(path, questions):
    path.write_text("".join(json.dumps(q) + "\n" for q in questions), encoding="utf-8")
    return path


def _meta(folder, dataset_name, kb_id):
    (folder / "pool_meta.json").write_text(
        json.dumps({"kb_id": kb_id, "dataset": f"data\\eval\\{dataset_name}"}), encoding="utf-8"
    )


# --- check_dataset_kb ---------------------------------------------------------------


def test_matching_gold_passes(tmp_path):
    ds = tmp_path / "q.jsonl"
    items = [_q("a", ["d#0"], ["d::Bagian"])]
    check_dataset_kb(ds, items, "kb-1", ["d#0", "d#1"], {"d"})


def test_unannotated_dataset_without_pool_meta_passes(tmp_path):
    check_dataset_kb(tmp_path / "q.jsonl", [_q("a")], "kb-1", [], set())


def test_unknown_gold_chunk_rejected(tmp_path):
    items = [_q("a", ["03_biaya#2"]), _q("b", ["d#0"])]
    with pytest.raises(DatasetKbMismatch) as exc:
        check_dataset_kb(tmp_path / "q.jsonl", items, "official-x", ["d#0"], {"d"})
    msg = str(exc.value)
    assert "official-x" in msg and "1 gold_chunk_ids" in msg and "a: 03_biaya#2" in msg


def test_unknown_gold_ref_doc_rejected(tmp_path):
    items = [_q("a", gold_refs=["03_biaya::Biaya Kuliah"])]
    with pytest.raises(DatasetKbMismatch) as exc:
        check_dataset_kb(tmp_path / "q.jsonl", items, "official-x", [], {"pmb/pedoman"})
    assert "doc_id gold_refs" in str(exc.value) and "03_biaya" in str(exc.value)


def test_pool_meta_other_kb_rejected(tmp_path):
    _meta(tmp_path, "q.jsonl", "dev-2026-10-15-v2")
    with pytest.raises(DatasetKbMismatch) as exc:
        check_dataset_kb(tmp_path / "q.jsonl", [_q("a")], "official-x", [], set())
    assert "pool_meta.json mencatat kb_id dev-2026-10-15-v2" in str(exc.value)


def test_pool_meta_same_kb_or_other_file_passes(tmp_path):
    _meta(tmp_path, "q.jsonl", "official-x")
    check_dataset_kb(tmp_path / "q.jsonl", [_q("a")], "official-x", [], set())
    _meta(tmp_path, "lain.jsonl", "dev-2026-10-15-v2")  # pool untuk file lain
    check_dataset_kb(tmp_path / "q.jsonl", [_q("a")], "official-x", [], set())


def test_mismatch_is_dataset_error():
    from mica.eval.dataset import DatasetError

    assert issubclass(DatasetKbMismatch, DatasetError)  # ditangkap main() -> exit 2


# --- dengan KB nyata (kecil) ----------------------------------------------------------


@pytest.fixture
def env(tmp_path):
    settings = load_settings(DEV_YAML)
    kb_root = tmp_path / "kb"
    build_kb(
        make_kb_folder(tmp_path / "src"), "official-test", "official", settings.kb,
        FakeEmbedder(), kb_root,
    )  # fmt: skip
    return load_kb("official-test", kb_root), kb_root, tmp_path


def test_check_dataset_files_extra(env):
    kb, _, tmp = env
    good = kb.chunks[0].chunk_id
    ds = _write(tmp / "q.jsonl", [_q("a", [good])])
    switch = _write(tmp / "switch.jsonl", [{"qid": "ts1", "gold_chunk_ids": ["lama#9"]}])
    check_dataset_files(ds, kb)
    with pytest.raises(DatasetKbMismatch) as exc:
        check_dataset_files(ds, kb, extra=[switch])
    assert "switch.jsonl" in str(exc.value)


@pytest.mark.parametrize("command", ["gate", "retrieval", "generation"])
def test_cli_refuses_dev_dataset_on_other_kb(env, capsys, tmp_path, command, monkeypatch):
    _, kb_root, tmp = env
    settings = load_settings(DEV_YAML)
    # KB aktif di config diarahkan ke KB uji; dataset menunjuk chunk KB dev
    monkeypatch.setattr(
        eval_cli,
        "load_settings",
        lambda *a, **k: settings.model_copy(
            update={"kb": settings.kb.model_copy(update={"active_id": "official-test"})}
        ),
    )
    ds = _write(tmp / "questions.jsonl", [_q("d001", ["03_biaya_kuliah_dan_syarat_masuk#2"])])
    code = eval_cli.main(
        ["--kb-root", str(kb_root), command, "--config", str(DEV_YAML),
         "--dataset", str(ds), "--out", str(tmp / "out")],
        embedder_factory=lambda m, r: FakeEmbedder(),
    )  # fmt: skip
    err = capsys.readouterr().err
    assert code == 2
    assert "tidak cocok dengan KB aktif official-test" in err
    assert not (tmp / "out").exists()  # tidak ada run yang ditulis


@pytest.mark.skipif(not REPO_DATASET.exists(), reason="dataset dev repo tidak ada")
def test_repo_dev_dataset_rejected_on_official_kb(env):
    """questions.jsonl (dibuat di KB dev) tidak boleh dinilai pada KB lain."""
    kb, _, _ = env
    with pytest.raises(DatasetKbMismatch):
        check_dataset_files(REPO_DATASET, kb)
