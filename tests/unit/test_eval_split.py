"""--split dev|test di perintah eval (docs/DATASET.md) dan --prompt-variant di eval generation.

Data sintetis dan KB kecil di tmp_path; data/eval/official/ di repo tidak disentuh."""

import json
from pathlib import Path

import pytest
from kb_samples import FakeEmbedder, make_kb_folder
from test_eval_generation import QUESTIONS, FakeProvider

from mica.config import load_settings
from mica.eval import __main__ as eval_cli
from mica.eval.generation import effective_settings, run_generation
from mica.eval.official import SplitRefused, check_split, lock_dataset
from mica.kb.index import build_kb, load_kb

DEV_YAML = Path(__file__).resolve().parents[2] / "config" / "dev.yaml"


def _q(qid, type_, question, split, prev=None):
    return {"qid": qid, "question": question, "type": type_, "topic": "x", "gold_chunk_ids": [],
            "reference_answer": "", "split": split, "prev_qid": prev}  # fmt: skip


def _kb(tmp_path, source_type):
    settings = load_settings(DEV_YAML)
    root = tmp_path / f"kb-{source_type}"
    build_kb(make_kb_folder(tmp_path / f"src-{source_type}"), settings.kb.active_id, source_type,
             settings.kb, FakeEmbedder(), root)  # fmt: skip
    return root


@pytest.fixture
def env(tmp_path):
    root_dev, root_official = _kb(tmp_path, "dev"), _kb(tmp_path, "official")
    kb = load_kb(load_settings(DEV_YAML).kb.active_id, root_official)
    biaya = [c.chunk_id for c in kb.chunks if c.chunk_id.startswith("biaya#")]
    rows = [{**_q(f"o-test-00{i}", "answerable", f"Berapa biaya pendaftaran {i}?", "test"),
             "gold_chunk_ids": biaya[:1]} for i in range(1, 4)]  # fmt: skip
    test = tmp_path / "official" / "test.jsonl"
    test.parent.mkdir()
    test.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    pool = test.parent / "pool.csv"
    pool.write_text("qid,chunk_id,relevant\n" + "".join(f"{r['qid']},{biaya[0]},1\n" for r in rows),
                    encoding="utf-8")  # fmt: skip
    lock = tmp_path / "LOCK"
    return {"tmp": tmp_path, "dev_kb": root_dev, "official_kb": root_official, "test": test,
            "lock": lock}  # fmt: skip


# --- penjaga ------------------------------------------------------------------------------


def test_check_split_rules(env):
    test, lock = env["test"], env["lock"]
    assert check_split("dev", test, "dev", lock) == {"split": "dev", "lock": None}  # belum dikunci
    with pytest.raises(SplitRefused, match="belum dikunci"):
        check_split("test", test, "official", lock)
    lock_dataset(test, "set uji sintetis", lock, commit="abc", git_dirty=False)
    info = check_split("test", test, "official", lock)
    assert info["split"] == "test" and info["lock"]["version"] == 1
    assert check_split("test", None, "official", lock)["lock"]["dataset"] == test.as_posix()
    with pytest.raises(SplitRefused, match="KB source_type official"):
        check_split("test", test, "dev", lock)
    with pytest.raises(SplitRefused, match="set uji terkunci"):
        check_split("dev", test, "dev", lock)  # set uji tidak boleh dipakai sebagai dev
    test.write_text(test.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(SplitRefused, match="tidak cocok dengan LOCK"):
        check_split("test", test, "official", lock)


def _retrieval(env, kb_root, split, *extra):
    out = env["tmp"] / "out"
    code = eval_cli.main(["--kb-root", str(kb_root), "--lock", str(env["lock"]), "retrieval",
                          "--config", str(DEV_YAML), "--dataset", str(env["test"]),
                          "--out", str(out), "--retrievers", "bm25", "--split", split, *extra],
                         embedder_factory=lambda m, r: FakeEmbedder())  # fmt: skip
    return code, out


def test_retrieval_test_split_requires_lock_and_official_kb(env, capsys):
    code, _ = _retrieval(env, env["official_kb"], "test")
    assert code == 2 and "belum dikunci" in capsys.readouterr().err
    lock_dataset(env["test"], "set uji sintetis", env["lock"])
    code, _ = _retrieval(env, env["dev_kb"], "test")
    assert code == 2 and "KB source_type official" in capsys.readouterr().err
    code, out = _retrieval(env, env["official_kb"], "test")
    assert code == 0
    (run_dir,) = out.glob("*-test-bm25")
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["split"] == "test" and run["lock"]["version"] == 1
    assert run["lock"]["sha256"] == run["dataset"]["sha256"]
    assert run["n_questions"]["answerable"] == 3


def test_retrieval_hash_mismatch_refused(env, capsys):
    lock_dataset(env["test"], "set uji sintetis", env["lock"])
    env["test"].write_text(env["test"].read_text(encoding="utf-8").replace("1?", "satu?"),
                           encoding="utf-8")  # fmt: skip
    code, _ = _retrieval(env, env["official_kb"], "test")
    assert code == 2 and "tidak cocok dengan LOCK" in capsys.readouterr().err


def test_latency_test_split_needs_config(env, capsys):
    code = eval_cli.main(["--lock", str(env["lock"]), "latency", "--logs", str(env["tmp"]),
                          "--label", "x", "--out", str(env["tmp"] / "lat"), "--split", "test"])  # fmt: skip
    assert code == 2 and "--config" in capsys.readouterr().err


def test_copy_refuses_run_with_other_split(env, capsys):
    run = env["tmp"] / "gen-run"
    run.mkdir()
    (run / "run.json").write_text(json.dumps({"split": "dev", "dataset": {"path": "x",
                                              "sha256": "0"}}), encoding="utf-8")  # fmt: skip
    code = eval_cli.main(["--kb-root", str(env["official_kb"]), "--lock", str(env["lock"]),
                          "copy", "--config", str(DEV_YAML), "--runs", str(run),
                          "--out", str(env["tmp"] / "copy"), "--split", "test"],
                         embedder_factory=lambda m, r: FakeEmbedder())  # fmt: skip
    assert code == 2 and "bukan test" in capsys.readouterr().err


# --- --prompt-variant ---------------------------------------------------------------------


def test_prompt_variant_recorded_in_run_json(tmp_path):
    settings = load_settings(DEV_YAML)
    kb_root = _kb(tmp_path, "dev")
    kb = load_kb(settings.kb.active_id, kb_root)
    dataset = tmp_path / "questions.jsonl"
    dataset.write_text("".join(json.dumps(q) + "\n" for q in QUESTIONS), encoding="utf-8")
    other = "plain" if settings.rag.prompt_variant == "paraphrase" else "paraphrase"
    run_dir, _, _ = run_generation(settings, kb, dataset, tmp_path / "out",
                                   provider=FakeProvider(), embedder=FakeEmbedder(),
                                   cache_dir=tmp_path / "cache", environment={}, progress=None,
                                   prompt_variant=other)  # fmt: skip
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["prompt_variant"] == other and run["prompt_variant_source"] == "--prompt-variant"
    assert run["prompt_variant_config"] == settings.rag.prompt_variant
    assert run["split"] == "dev" and run["lock"] is None
    assert effective_settings(settings, True).rag.prompt_variant == settings.rag.prompt_variant
    with pytest.raises(ValueError, match="--prompt-variant"):
        effective_settings(settings, True, prompt_variant="lain")


def test_cli_generation_parser_split_and_prompt_variant():
    args = eval_cli.build_parser().parse_args(
        ["generation", "--config", "c", "--dataset", "d", "--out", "o", "--split", "test",
         "--prompt-variant", "plain"])  # fmt: skip
    assert (args.split, args.prompt_variant) == ("test", "plain")
    defaults = eval_cli.build_parser().parse_args(["generation", "--config", "c", "--dataset", "d",
                                                   "--out", "o"])  # fmt: skip
    assert (defaults.split, defaults.prompt_variant) == ("dev", None)
    for cmd in (["retrieval", "--config", "c", "--dataset", "d", "--out", "o"],
                ["copy", "--config", "c", "--runs", "r"], ["latency", "--label", "x"],
                ["stt", "--config", "c", "--dataset", "d"]):  # fmt: skip
        assert eval_cli.build_parser().parse_args(cmd).split == "dev"
