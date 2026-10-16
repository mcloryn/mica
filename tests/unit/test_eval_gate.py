import csv
import json
from pathlib import Path

import pytest
from kb_samples import FakeEmbedder, make_kb_folder

from mica.config import load_settings
from mica.eval import __main__ as eval_cli
from mica.eval import environment
from mica.eval.dataset import DatasetError, load_questions
from mica.eval.gate import GateScore, rejected, run_gate, sweep, thresholds
from mica.kb.index import build_kb, load_kb
from mica.rag.retriever import DenseRetriever

DEV_YAML = Path(__file__).resolve().parents[2] / "config" / "dev.yaml"


def _q(qid, type_, question, oos=None, prev=None, split="dev"):
    q = {"qid": qid, "question": question, "type": type_, "topic": "x", "gold_chunk_ids": [],
         "reference_answer": "", "split": split, "prev_qid": prev}
    if oos is not None:
        q["oos_level"] = oos
    return q


QUESTIONS = [
    _q("a1", "answerable", "Berapa biaya pendaftaran?"),
    _q("f1", "followup", "Kalau beasiswa?", prev="a1"),
    _q("j1", "out_of_kb", "Cuaca hari ini?", oos="jauh"),
    _q("k1", "out_of_kb", "Biaya wisuda?", oos="dekat"),
    _q("p1", "false_premise", "Biaya kedokteran?"),
    _q("t1", "answerable", "Pertanyaan test", split="test"),
]


def _write(path, questions):
    path.write_text("".join(json.dumps(q) + "\n" for q in questions), encoding="utf-8")
    return path


# --- dataset: oos_level ------------------------------------------------------


def test_oos_level_required_for_out_of_kb(tmp_path):
    bad = [dict(q) for q in QUESTIONS]
    del bad[2]["oos_level"]
    with pytest.raises(DatasetError) as exc:
        load_questions(_write(tmp_path / "q.jsonl", bad))
    assert "oos_level" in str(exc.value) and "j1" in str(exc.value)


def test_oos_level_must_be_known_value(tmp_path):
    bad = [dict(q) for q in QUESTIONS]
    bad[2]["oos_level"] = "sedang"
    with pytest.raises(DatasetError):
        load_questions(_write(tmp_path / "q.jsonl", bad))


def test_oos_level_forbidden_for_other_types(tmp_path):
    bad = [dict(q) for q in QUESTIONS]
    bad[0]["oos_level"] = "dekat"
    with pytest.raises(DatasetError) as exc:
        load_questions(_write(tmp_path / "q.jsonl", bad))
    assert "a1" in str(exc.value)
    ok = [dict(q) for q in QUESTIONS]
    ok[0]["oos_level"] = None  # null boleh
    assert len(load_questions(_write(tmp_path / "q2.jsonl", ok))) == len(QUESTIONS)


# --- sweep ----------------------------------------------------------------------


def test_thresholds_range():
    ts = thresholds()
    assert len(ts) == 61 and ts[0] == 0.30 and ts[-1] == 0.90 and ts[30] == 0.60


def test_rejected_matches_gate_rule():
    assert rejected(0.59, 0.60) is True
    assert rejected(0.60, 0.60) is False  # sama dengan ambang = lolos
    assert rejected(None, 0.60) is True


def test_sweep_counts():
    scores = [
        GateScore("a1", "answerable", None, 0.70, "c"),
        GateScore("a2", "answerable", None, 0.40, "c"),
        GateScore("f1", "followup", None, 0.55, "c"),
        GateScore("j1", "out_of_kb", "jauh", 0.20, "c"),
        GateScore("k1", "out_of_kb", "dekat", 0.65, "c"),
        GateScore("p1", "false_premise", None, 0.50, "c"),
    ]
    rows = {r["threshold"]: r for r in sweep(scores)}
    r = rows["0.55"]
    assert (r["answerable_followup_n"], r["false_reject_n"], r["false_reject_rate"]) == (
        3, 1, "0.3333")
    assert (r["jauh_n"], r["jauh_reject_n"]) == (1, 1)
    assert (r["dekat_n"], r["dekat_reject_n"]) == (1, 0)
    assert (r["false_premise_n"], r["false_premise_reject_n"]) == (1, 1)
    assert rows["0.30"]["false_reject_n"] == 0
    assert rows["0.90"]["false_reject_n"] == 3 and rows["0.90"]["dekat_reject_rate"] == "1.0000"


# --- run ------------------------------------------------------------------------


@pytest.fixture
def env(tmp_path):
    settings = load_settings(DEV_YAML)
    kb_root = tmp_path / "kb"
    build_kb(make_kb_folder(tmp_path / "src"), settings.kb.active_id, "dev", settings.kb,
             FakeEmbedder(), kb_root)
    kb = load_kb(settings.kb.active_id, kb_root)
    return settings, kb, kb_root, _write(tmp_path / "questions.jsonl", QUESTIONS), tmp_path


class SpyEmbedder(FakeEmbedder):
    def __init__(self):
        super().__init__()
        self.queries = []

    def embed(self, texts):
        self.queries.extend(texts)
        return super().embed(texts)


def test_run_gate_outputs(env):
    settings, kb, _, dataset, tmp = env
    spy = SpyEmbedder()
    run_dir, scores = run_gate(settings, kb, dataset, tmp / "out", embedder=spy,
                               environment={"git_dirty": False})
    assert [s.qid for s in scores] == ["a1", "f1", "j1", "k1", "p1"]  # hanya split dev
    assert "Berapa biaya pendaftaran? Kalau beasiswa?" in spy.queries  # followup concat
    # skor gerbang = cosine dense peringkat 1 yang dihitung langsung
    top = DenseRetriever(kb, FakeEmbedder()).search("Berapa biaya pendaftaran?", 1)[0]
    a1 = scores[0]
    assert a1.score == pytest.approx(top.score, abs=1e-6)
    assert a1.dense_top1_chunk_id == top.chunk.chunk_id
    assert all(s.score is not None and s.dense_top1_chunk_id for s in scores)

    with (run_dir / "gate_scores.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == ["qid", "type", "oos_level", "gate_score", "dense_top1_chunk_id"]
    assert {r["qid"]: r["oos_level"] for r in rows}["k1"] == "dekat"
    with (run_dir / "sweep.csv").open(encoding="utf-8-sig", newline="") as f:
        sweep_rows = list(csv.DictReader(f))
    assert len(sweep_rows) == 61 and sweep_rows[0]["answerable_followup_n"] == "2"

    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["experiment"] == "E-02" and run["retriever"] == "hybrid"
    assert run["config_hash"] == settings.config_hash()
    assert run["gate_threshold_config"] == settings.rag.gate.threshold
    assert run["n_questions"] == {"answerable": 1, "followup": 1, "jauh": 1, "dekat": 1,
                                  "false_premise": 1}
    assert run["environment"] == {"git_dirty": False}


def test_run_gate_does_not_change_config(env):
    settings, kb, _, dataset, tmp = env
    before = DEV_YAML.read_bytes()
    run_gate(settings, kb, dataset, tmp / "out", embedder=FakeEmbedder(), environment={})
    assert DEV_YAML.read_bytes() == before


def test_run_gate_rejects_bm25(env):
    settings, kb, _, dataset, tmp = env
    bm25 = settings.model_copy(
        update={"rag": settings.rag.model_copy(update={"retriever": "bm25"})})
    with pytest.raises(ValueError):
        run_gate(bm25, kb, dataset, tmp / "out", embedder=FakeEmbedder(), environment={})


def test_cli_gate(env, capsys):
    _, _, kb_root, dataset, tmp = env
    code = eval_cli.main(
        ["--kb-root", str(kb_root), "gate", "--config", str(DEV_YAML),
         "--dataset", str(dataset), "--out", str(tmp / "E-02-gate")],
        embedder_factory=lambda m, r: FakeEmbedder(),
    )
    out = capsys.readouterr().out
    assert code == 0 and "kelompok | n | min | median | maks" in out
    run_json = next((tmp / "E-02-gate").glob("*-dev-hybrid/run.json"))
    env_info = json.loads(run_json.read_text(encoding="utf-8"))["environment"]
    assert {"git_dirty", "power", "power_plan", "torch_num_threads"} <= set(env_info)


# --- environment ------------------------------------------------------------------


def test_power_info_null_outside_windows(monkeypatch):
    monkeypatch.setattr(environment.sys, "platform", "linux")
    assert environment.power_status() is None
    assert environment.power_plan() is None


@pytest.mark.skipif(environment.sys.platform != "win32", reason="khusus Windows")
def test_power_info_on_windows():
    status = environment.power_status()
    assert status is not None and status["source"] in ("ac", "battery", "unknown")
    plan = environment.power_plan()
    assert plan is None or (plan["guid"] is None or len(plan["guid"]) == 36)


def test_torch_threads():
    assert environment.torch_threads() >= 1
