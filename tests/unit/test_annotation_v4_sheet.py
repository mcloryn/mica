"""Lembar anotasi v4 120b (dev): isi answer, salinan LLM-as-judge, dan lembar buta penilai manusia."""

import csv
import json
from pathlib import Path

from mica.core.types import joined_answer
from mica.eval.annotation import load_annotations, summarize
from mica.rag.prompts import SYSTEM_PARAPHRASE, system_prompt

ROOT = Path(__file__).resolve().parents[2]
V4 = ROOT / "results/E-02/20261020-130025-E-02-dev-hybrid-gpt-oss-120b-gateoff"
V3 = ROOT / "results/E-02/20261020-113556-E-02-dev-hybrid-gpt-oss-120b-gateoff"


def _rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r["qid"]: r for r in csv.DictReader(f)}


def test_run_is_v4():
    run = json.loads((V4 / "run.json").read_text(encoding="utf-8"))
    assert run["prompt_variant"] == "v4" and run["prompt_version"] == "v4"


def test_sheet_answer_is_joined_answer():
    sheet, per_q = _rows(V4 / "annotate_generation.csv"), _rows(V4 / "per_question.csv")
    for qid, row in sheet.items():
        items = per_q[qid]["items"].split("; ") if per_q[qid]["items"] else []
        assert row["answer"] == joined_answer(per_q[qid]["answer"], items), qid
    v3 = _rows(V3 / "annotate_generation.csv")
    for qid in ("d005", "d014", "d021"):
        assert sheet[qid]["answer"] != v3[qid]["answer"]
        assert per_q[qid]["items"] and per_q[qid]["items"] in sheet[qid]["answer"]


def test_llm_judge_copy_and_summary():
    main = load_annotations(V4 / "annotate_generation.csv")
    judge = load_annotations(V4 / "annotate_generation_llm_judge.csv")
    assert main == judge and len(main) == 28
    s = summarize(main)
    assert (s["benar"], s["halusinasi"]) == (27, 2)
    assert s["halusinasi_qids"] == ["d008", "d019"] and s["salah_qids"] == ["d040"]
    saved = json.loads((V4 / "annotation_summary.json").read_text(encoding="utf-8"))
    assert saved["halusinasi"] == 2 and saved["n"] == 28
    # setiap catatan memuat kutipan bukti; kasus batas ditandai RAGU
    assert all('"' in r["catatan"] for r in main)
    assert {r["qid"] for r in main if "RAGU:" in r["catatan"]} == {"d008", "d019", "d040"}


def test_blind_sheet_for_human_rater_has_no_values():
    blind = _rows(V4 / "annotate_generation_hasa.csv")
    main = _rows(V4 / "annotate_generation.csv")
    assert list(blind) == list(main)
    for qid, row in blind.items():
        assert row["benar"] == row["halusinasi"] == row["catatan"] == ""
        assert row["answer"] == main[qid]["answer"]
        assert row["cited_chunks"] == main[qid]["cited_chunks"]


def test_paraphrase_is_prompt_v2_and_config_unchanged():
    # nama varian 20b di config = "paraphrase" = prompt v2 (hash di test_prompt_v3.V2_GOLDEN)
    from tests.unit.test_prompt_v3 import V2_GOLDEN, _sha

    assert _sha(system_prompt("paraphrase")) == V2_GOLDEN["system_paraphrase"]
    assert SYSTEM_PARAPHRASE == system_prompt("paraphrase")
    import yaml

    for name in ("dev.yaml", "prod.yaml"):  # keputusan menunggu penilai manusia
        raw = yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))
        assert raw["llm"]["prompt_variants"] == {}
