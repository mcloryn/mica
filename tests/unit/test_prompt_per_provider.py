"""Lanjutan prompt v4: daftar tidak dobel (tampilan + TTS) dan varian prompt per penyedia.

Jawaban v4 nyata d014 dan d021 dari run 120b (dev) mengulang semua item di answer; items itu
tidak ditampilkan dan tidak dibacakan lagi. llm.prompt_variants: 120b v4, cadangan 20b v2.
"""

import csv
from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import SecretStr
from tests.unit.test_pipeline import FakeGate, FakeRetriever

from mica.audio.messages import Speak, SpeechDone, SpeechStarted, Transcript
from mica.config import ConfigError, load_settings
from mica.core.logging import InteractionLog
from mica.core.session import AnswerReady, Session, ShowView, VisitState
from mica.core.spoken import spoken_answer
from mica.core.types import Chunk, FinalAnswer, LlmAnswer, visible_items
from mica.eval import generation as gen
from mica.rag.checker import NumericFactChecker
from mica.rag.llm import GroqProvider, ProviderChain, ProviderFailed
from mica.rag.pipeline import AnswerPipeline
from mica.rag.prompts import build_prompt
from mica.ui.viewmodel import ViewModel
from mica.vision.types import PersonArrived
from mica.webui import state

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
RUN_V4 = ROOT / "results/E-02/20261020-130025-E-02-dev-hybrid-gpt-oss-120b-gateoff"
BIG, SMALL = "groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-20b"
CHUNK = Chunk("03#2", "03", "Biaya Kuliah", "Biaya S1", date(2026, 9, 29), "dev",
              "Biaya S1 Rp14.000.000 per tahun.", False)  # fmt: skip


def v4_row(qid: str) -> tuple[str, tuple[str, ...]]:
    with (RUN_V4 / "per_question.csv").open(encoding="utf-8-sig", newline="") as f:
        row = next(r for r in csv.DictReader(f) if r["qid"] == qid)
    return row["answer"], tuple(row["items"].split("; ")) if row["items"] else ()


# --- daftar tidak dobel -------------------------------------------------------------------


@pytest.mark.parametrize("qid", ["d014", "d021"])
def test_real_v4_duplicate_items_hidden(qid):
    answer, items = v4_row(qid)
    assert len(items) >= 4  # jawaban nyata: semua item juga ditulis di answer
    assert visible_items(answer, items) == ()


@pytest.mark.parametrize("qid", ["d005", "d009"])
def test_real_v4_list_items_kept(qid):
    answer, items = v4_row(qid)  # answer hanya pengantar; items tetap tampil
    assert items and visible_items(answer, items) == items


def test_visible_items_ignores_case_and_spaces_but_needs_all():
    answer = "Ada Beasiswa  Akademik dan KIP kuliah."
    assert visible_items(answer, ("beasiswa akademik", "KIP Kuliah")) == ()
    assert visible_items(answer, ("Beasiswa Akademik", "Beasiswa IP4")) == (
        "Beasiswa Akademik", "Beasiswa IP4"
    )  # fmt: skip
    assert visible_items(answer, ()) == ()


def _view(answer, items, topic=None):
    vm = ViewModel()
    vm.apply(ShowView(VisitState.THINKING, transcript="?", send_enabled=False))
    vm.apply(ShowView(VisitState.SPEAKING, transcript="?", answer=answer, sources=(CHUNK,),
                      follow_up_topic=topic, items=items))  # fmt: skip
    return state.view_json(vm)["messages"][-1]


def _speak(final):
    s = Session(fps_idle=5.0, fps_busy=2.0, min_majority=0.5, idle_reset_s=30.0,
                regreet_cooldown_s=10.0, new_session_id=lambda: "s0")  # fmt: skip
    s.handle(PersonArrived(1, (0.0, 0.0, 10.0, 10.0), 0.0, "biru", 0.9), 0.0)
    s.handle(SpeechDone(s.session_id, s.greeting_uid, 0.2), 1.0)
    s.handle(SpeechStarted(s.session_id, 2.0), 2.0)
    s.handle(Transcript(s.session_id, "pertanyaan", True, 0.5, 1.5), 3.0)
    [speak] = [a for a in s.handle(AnswerReady(s.session_id, final), 4.0) if isinstance(a, Speak)]
    return speak.text


@pytest.mark.parametrize("qid", ["d014", "d021"])
def test_duplicate_items_not_shown_nor_spoken(qid):
    answer, items = v4_row(qid)
    msg = _view(answer, items)
    assert msg["text"] == answer and msg["items"] == []
    assert _speak(FinalAnswer("answered", answer, (CHUNK,), {}, None, items)) == answer


def test_partial_items_shown_and_spoken():
    answer, items = v4_row("d005")
    assert _view(answer, items)["items"] == list(items)
    spoken = _speak(FinalAnswer("answered", answer, (CHUNK,), {}, None, items))
    assert spoken.startswith(answer + " Pertama ") and "terakhir" in spoken


# --- jawaban v2 (cadangan 20b): tanpa items dan follow_up_topic ---------------------------


def test_v2_answer_in_ui_and_tts():
    text = "Biaya kuliah S1 Rp14.000.000 per tahun. Kelas sore Rp15.000.000."
    msg = _view(text, ())
    assert msg["items"] == [] and msg["follow_up"] is None and msg["text"] == text
    assert _speak(FinalAnswer("answered", text, (CHUNK,), {})) == spoken_answer(text) == text


# --- llm.prompt_variants -------------------------------------------------------------------


def _settings(tmp_path, variants):
    raw = yaml.safe_load(DEV_YAML.read_text(encoding="utf-8"))
    raw["llm"]["chain"] = [BIG, SMALL]
    raw["llm"]["prompt_variants"] = variants
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_settings(path)


MAPPING = {BIG: "v4", SMALL: "paraphrase"}


def test_config_default_empty_and_mapping_validated(tmp_path):
    assert load_settings(DEV_YAML).llm.prompt_variants == {}  # bawaan belum diganti ke v4
    prod = yaml.safe_load((ROOT / "config" / "prod.yaml").read_text(encoding="utf-8"))
    assert prod["llm"]["prompt_variants"] == {}  # prod butuh nilai TBD; cek isi YAML saja
    s = _settings(tmp_path, MAPPING)
    assert s.llm.prompt_variant_for(BIG, "paraphrase") == "v4"
    assert s.llm.prompt_variant_for(SMALL, "v4") == "paraphrase"
    with pytest.raises(ConfigError):
        _settings(tmp_path, {"groq:model-lain": "v4"})
    with pytest.raises(ConfigError):
        _settings(tmp_path, {BIG: "v9"})


class Fake:
    """Penyedia palsu bernama seperti entri rantai; bisa gagal (pindah ke cadangan)."""

    def __init__(self, name, fail=False, items=()):
        self.name, self.fail, self.items, self.requests = name, fail, items, []

    def request_body(self, request):  # dipakai kunci cache EvalLlm
        return {"system": request.system, "user": request.user}

    def generate(self, request, timeout_s):
        self.requests.append(request)
        if self.fail:
            raise ProviderFailed("HTTP 429", 429, "1")
        return LlmAnswer("answered", "Biaya SI kelas pagi Rp14.000.000 per tahun.",
                         ("03_biaya#2",), self.name, 0.3, None,
                         "Beasiswa" if request.follow_up_topics else None, self.items)  # fmt: skip


def _pipeline(tmp_path, big_fails):
    big, small = Fake(BIG, fail=big_fails), Fake(SMALL)
    settings = _settings(tmp_path, MAPPING)
    pipeline = AnswerPipeline(settings, FakeRetriever(), FakeGate(True), ProviderChain([big, small]),
                              NumericFactChecker(), kb_id="dev-test",
                              log=InteractionLog(tmp_path / "logs"))  # fmt: skip
    return pipeline, big, small, settings


def test_primary_120b_uses_v4(tmp_path):
    pipeline, big, small, _ = _pipeline(tmp_path, big_fails=False)
    final, record = pipeline.run("berapa biaya SI?", [], "s1")
    [req] = big.requests
    assert req.items_field and req.follow_up_topics and small.requests == []
    assert final.follow_up_topic == "Beasiswa" and record.prompt_version == "v4"


def settings_system_v2():
    from mica.rag.prompts import SYSTEM_PARAPHRASE

    return SYSTEM_PARAPHRASE


def test_fallback_20b_uses_v2_request(tmp_path):
    pipeline, big, small, _ = _pipeline(tmp_path, big_fails=True)
    final, record = pipeline.run("berapa biaya SI?", [], "s1")
    [req] = small.requests
    assert not req.items_field and req.follow_up_topics == () and req.alternates == ()
    # yang dikirim ke 20b = alternatif v2 yang dibawa request utama
    assert req == big.requests[0].for_provider(SMALL)
    assert req.system == settings_system_v2()
    assert "follow_up_topic" not in req.system and '"items"' not in req.system
    assert final.status == "answered" and final.follow_up_topic is None and final.items == ()
    assert record.prompt_version == "v2" and record.llm_provider == SMALL


def test_v2_alternate_body_equals_plain_v2_body(tmp_path):
    from mica.core.types import ScoredChunk, ScrubbedText

    pipeline, *_rest, settings = _pipeline(tmp_path, big_fails=False)
    hits = [ScoredChunk(CHUNK, 0.5, {"dense": 1})]
    request = pipeline._request(ScrubbedText("Berapa biaya?"), [], hits)
    alternate = request.for_provider(SMALL)
    plain_v2 = build_prompt(ScrubbedText("Berapa biaya?"), [], hits, "paraphrase",
                            settings.ui.topics)  # fmt: skip
    groq = GroqProvider("openai/gpt-oss-20b", api_key=SecretStr("x"), temperature=0.2,
                        reasoning_effort="low")  # fmt: skip
    assert groq.request_body(alternate) == groq.request_body(plain_v2)
    assert gen.cache_key(groq, alternate) == gen.cache_key(groq, plain_v2)
    assert request.for_provider(BIG) is request and request.items_field


def test_eval_llm_uses_request_for_its_provider(tmp_path):
    from mica.core.types import ScoredChunk, ScrubbedText

    pipeline, *_rest = _pipeline(tmp_path, big_fails=False)
    request = pipeline._request(ScrubbedText("Berapa biaya?"), [],
                                [ScoredChunk(CHUNK, 0.5, {"dense": 1})])  # fmt: skip
    small = Fake(SMALL)
    llm = gen.EvalLlm(small, gen.TokenRateLimiter())
    llm.generate(request, 5)
    assert small.requests == [request.for_provider(SMALL)] and not small.requests[0].items_field


def test_effective_settings_prompt_variants(tmp_path):
    s = _settings(tmp_path, MAPPING)
    assert gen.effective_settings(s, True, SMALL).llm.prompt_variants == {SMALL: "paraphrase"}
    assert gen.effective_settings(s, True, BIG).llm.prompt_variants == {BIG: "v4"}
    assert gen.effective_settings(s, True, BIG, "v3").llm.prompt_variants == {}
    assert gen.effective_settings(s, True).llm.prompt_variants == MAPPING
