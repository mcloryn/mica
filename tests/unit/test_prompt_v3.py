"""Prompt v3 + follow_up_topic (pra-registrasi docs/PROMPT-V3.md).

v2 tidak berubah (teks prompt, badan request, kunci cache), skema enum follow_up_topic untuk
Groq dan Gemini, teks tawaran, normalisasi TTS baris "- ", dan alurnya sampai Speak/ShowView/UI.
"""

import hashlib
import json
from datetime import date

import pytest
from pydantic import SecretStr
from tests.unit.test_pipeline import FakeGate, FakeRetriever, _settings
from tests.unit.test_pipeline import _pipeline as _v2_pipeline

from mica.audio.messages import Speak, SpeechDone, SpeechStarted, Transcript
from mica.core import texts
from mica.core.session import AnswerReady, Session, ShowView, VisitState
from mica.core.spoken import spoken_answer
from mica.core.types import (
    Chunk,
    FinalAnswer,
    LlmAnswer,
    ScoredChunk,
    ScrubbedText,
    Turn,
)
from mica.eval.generation import PER_QUESTION_COLUMNS, PROMPT_VARIANTS, LlmCache
from mica.rag import prompts
from mica.rag.llm import (
    GeminiProvider,
    GroqProvider,
    _BadOutput,
    gemini_schema,
    output_schema,
    parse_output,
)
from mica.rag.prompts import build_prompt, prompt_version, system_prompt
from mica.ui.viewmodel import ViewModel
from mica.vision.types import PersonArrived
from mica.webui import state
from mica.webui.answer_format import format_answer

TOPICS = ("Program Studi", "Biaya", "Beasiswa", "Pendaftaran", "Fasilitas", "Lokasi")
CHUNK = Chunk("03#2", "03", "Biaya Kuliah", "Biaya S1", date(2026, 9, 29), "dev",
              "Biaya S1 Rp14.000.000 per tahun.", False)  # fmt: skip


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _request(variant="paraphrase", topics=()):
    return build_prompt(ScrubbedText("Berapa biaya?"), [Turn(ScrubbedText("halo"), "hai")],
                        [ScoredChunk(CHUNK, 0.5, {"dense": 1})], variant, topics)  # fmt: skip


def _groq():
    return GroqProvider("openai/gpt-oss-120b", api_key=SecretStr("x"), temperature=0.2,
                        reasoning_effort="low")  # fmt: skip


def _gemini():
    return GeminiProvider("gemini-3.8-flash", mode="dev", api_key=SecretStr("x"), temperature=0.2,
                          reasoning_effort="low")  # fmt: skip


# --- v2 tidak berubah ---------------------------------------------------------------------

# Hash diambil SEBELUM v3 ditambahkan (20 Okt 2026, commit 35fa9d7): teks prompt v2 dan badan
# request yang dipakai kunci cache LLM (eval generation) harus tetap sama persis.
V2_GOLDEN = {
    "system_paraphrase": "df5f91903dd29cc30c344f63235aa5c82d7aa26c5b0398404590bd8cf862febb",
    "system_plain": "c1d7c19ad3f578565a6ee228eb0e7f17447088c6c912f259c645b628cbe9e5fa",
    "groq": "c8d402b97682c6f77cee010842f296970e21c83c07a1630bfce35db6f12d5cc6",
    "gemini": "242cf939ed7dba9e225364aa90219343a574e9f8d20d68838c9ba11773d07091",
}


def test_v2_prompt_and_request_body_unchanged():
    assert _sha(system_prompt("paraphrase")) == V2_GOLDEN["system_paraphrase"]
    assert _sha(system_prompt("plain")) == V2_GOLDEN["system_plain"]
    assert _sha(_groq().request_body(_request())) == V2_GOLDEN["groq"]
    assert _sha(_gemini().request_body(_request())) == V2_GOLDEN["gemini"]


def test_v2_ignores_topics_and_sends_no_follow_up_field():
    req = _request("paraphrase", TOPICS)  # pipeline selalu meneruskan ui.topics
    assert req == _request("paraphrase") and req.follow_up_topics == ()
    assert _sha(_groq().request_body(req)) == V2_GOLDEN["groq"]
    assert "follow_up_topic" not in json.dumps(_gemini().request_body(req))
    assert prompt_version("paraphrase") == "v2" == prompt_version("plain")


def test_v2_output_with_follow_up_field_still_rejected():
    content = json.dumps({"status": "answered", "answer": "x", "citations": [],
                          "follow_up_topic": "Biaya"})  # fmt: skip
    with pytest.raises(_BadOutput, match="tidak dikenal"):
        parse_output(content)
    ok = json.dumps({"status": "answered", "answer": "x", "citations": ["a"]})
    assert parse_output(ok) == ("answered", "x", ("a",), None, ())


def test_v2_pipeline_final_answer_has_no_follow_up(tmp_path):
    pipeline, _llm, _ = _v2_pipeline(tmp_path, ("answered", "Biaya Rp14.000.000 per tahun.",
                                                ["03_biaya#2"]))  # fmt: skip
    final, record = pipeline.run("berapa biaya SI?", [], "s1")
    assert final.follow_up_topic is None and record.prompt_version == "v2"


def test_v2_cache_file_format_unchanged(tmp_path):
    cache = LlmCache(tmp_path)
    cache.put("k", LlmAnswer("answered", "x", ("a",), "groq:m", 0.5, None))
    data = json.loads((tmp_path / "k.json").read_text(encoding="utf-8"))
    assert set(data) == {"status", "answer", "citations", "provider", "latency_s", "usage"}
    assert cache.get("k").follow_up_topic is None


# --- v3: teks prompt ----------------------------------------------------------------------


def test_v3_keeps_every_other_v2_rule_verbatim():
    v3 = system_prompt("v3", TOPICS)
    for rule in (prompts._ROLE, prompts._ONLY_SOURCES, prompts._ONLY_ASKED,
                 prompts._FALSE_PREMISE, prompts._INJECTION, prompts._NO_ARITHMETIC,
                 prompts._CITATIONS, prompts._DATA_NOT_INSTRUCTIONS):  # fmt: skip
        assert rule in v3
    # diganti: parafrase (+ istilah resmi), dan "tanpa daftar berpoin" (+ baris "- ")
    assert prompts._EXACT_PARAPHRASE not in v3 and prompts._SPOKEN not in v3
    assert prompts._TONE_V3 in v3 and prompts._EXACT_V3 in v3 and prompts._FORM_V3 in v3
    assert '"kamu"' in v3 and "emoji" in v3 and '"- "' in v3 and "maksimal 120 kata" in v3
    assert "Program Studi, Biaya, Beasiswa, Pendaftaran, Fasilitas, Lokasi" in v3
    assert "follow_up_topic" in v3 and prompt_version("v3") == "v3"
    assert prompts.REFUSAL.startswith("Maaf, saya belum menemukan informasi itu")


def test_v3_needs_topics():
    with pytest.raises(ValueError, match="topik"):
        system_prompt("v3")


def test_v3_variant_accepted_by_config_and_eval(tmp_path):
    assert "v3" in PROMPT_VARIANTS
    assert _settings(tmp_path, prompt_variant="v3").rag.prompt_variant == "v3"
    assert "follow_up_topic" in PER_QUESTION_COLUMNS


# --- v3: skema enum -----------------------------------------------------------------------


def test_groq_schema_enum_nullable_and_required():
    schema = output_schema(("a",), TOPICS)
    assert schema["properties"]["follow_up_topic"] == {
        "anyOf": [{"type": "string", "enum": list(TOPICS)}, {"type": "null"}]
    }
    assert schema["required"] == ["status", "answer", "citations", "follow_up_topic"]
    assert schema["additionalProperties"] is False
    assert "follow_up_topic" not in output_schema(("a",))["properties"]  # v2


def test_gemini_schema_enum_nullable():
    schema = gemini_schema(("a",), TOPICS)
    assert schema["properties"]["follow_up_topic"] == {
        "type": "STRING", "format": "enum", "enum": list(TOPICS), "nullable": True
    }  # fmt: skip
    assert schema["required"][-1] == schema["propertyOrdering"][-1] == "follow_up_topic"
    assert "follow_up_topic" not in gemini_schema(("a",))["properties"]  # v2


def test_v3_request_bodies_carry_schema():
    req = _request("v3", TOPICS)
    assert req.follow_up_topics == TOPICS
    groq = _groq().request_body(req)["response_format"]["json_schema"]["schema"]
    assert "follow_up_topic" in groq["required"]
    gem = _gemini().request_body(req)["generationConfig"]["responseSchema"]
    assert gem["properties"]["follow_up_topic"]["enum"] == list(TOPICS)


@pytest.mark.parametrize("value", ["Biaya", None])
def test_v3_parse_output_accepts_topic_or_null(value):
    content = json.dumps({"status": "answered", "answer": "x", "citations": ["a"],
                          "follow_up_topic": value})  # fmt: skip
    assert parse_output(content, TOPICS) == ("answered", "x", ("a",), value, ())


@pytest.mark.parametrize(
    "data",
    [
        {"status": "answered", "answer": "x", "citations": [], "follow_up_topic": "Kantin"},
        {"status": "answered", "answer": "x", "citations": []},  # field wajib di v3
    ],
)
def test_v3_parse_output_rejects_unknown_or_missing(data):
    with pytest.raises(_BadOutput):
        parse_output(json.dumps(data), TOPICS)


class V3Llm:
    name = "fake"

    def __init__(self, status, answer, citations, topic):
        self.reply = LlmAnswer(status, answer, tuple(citations), "groq:fake", 0.4, None, topic)
        self.requests = []

    def generate(self, request, timeout_s):
        self.requests.append(request)
        return self.reply


def _v3_pipeline(tmp_path, llm):
    from mica.core.logging import InteractionLog
    from mica.rag.checker import NumericFactChecker
    from mica.rag.pipeline import AnswerPipeline

    settings = _settings(tmp_path, prompt_variant="v3")
    return AnswerPipeline(settings, FakeRetriever(), FakeGate(True), llm, NumericFactChecker(),
                          kb_id="dev-test", log=InteractionLog(tmp_path / "logs"))  # fmt: skip


def test_v3_pipeline_passes_topics_and_follow_up(tmp_path):
    llm = V3Llm("answered", "Biaya SI kelas pagi Rp14.000.000 per tahun.", ["03_biaya#2"],
                "Beasiswa")  # fmt: skip
    final, record = _v3_pipeline(tmp_path, llm).run("berapa biaya SI?", [], "s1")
    assert llm.requests[0].follow_up_topics == TOPICS
    assert final.status == "answered" and final.follow_up_topic == "Beasiswa"
    assert record.prompt_version == "v3"


def test_v3_refusal_drops_follow_up(tmp_path):
    llm = V3Llm("not_found", "", [], "Biaya")
    final, _ = _v3_pipeline(tmp_path, llm).run("cuaca hari ini?", [], "s1")
    assert final.status == "refused_llm" and final.follow_up_topic is None


def test_v3_cache_round_trip(tmp_path):
    cache = LlmCache(tmp_path)
    cache.put("k", LlmAnswer("answered", "x", ("a",), "groq:m", 0.5, None, "Lokasi"))
    assert cache.get("k").follow_up_topic == "Lokasi"


# --- teks tawaran dan TTS -----------------------------------------------------------------


def test_follow_up_offer_text():
    assert texts.follow_up_offer("Program Studi") == "Mau tahu soal program studi juga?"
    assert texts.follow_up_offer("Biaya") == "Mau tahu soal biaya juga?"


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("Ada tiga jalur:\n- Prestasi\n- Minat Bakat\n- Reguler",
         "Ada tiga jalur: Prestasi, Minat Bakat, dan Reguler."),
        ("Syaratnya:\n- ijazah;\n- KTP,\n- pas foto.\nBawa aslinya.",
         "Syaratnya: ijazah, KTP, dan pas foto. Bawa aslinya."),
        ("Pilihannya:\r\n- pagi\r\n- sore", "Pilihannya: pagi dan sore."),
        ("- Rp14.000.000 per tahun", "Rp14.000.000 per tahun."),
        # tanpa baris "- ": identik (v2), termasuk baris baru dan tanda hubung di tengah kalimat
        ("Biaya Rp14.000.000 per tahun.", "Biaya Rp14.000.000 per tahun."),
        ("Baris satu.\nBaris dua - tiga.", "Baris satu.\nBaris dua - tiga."),
        ("Kelas -pagi saja.", "Kelas -pagi saja."),
    ],
)  # fmt: skip
def test_spoken_answer(text, spoken):
    assert spoken_answer(text) == spoken


def _answered_session(answer: FinalAnswer):
    s = Session(fps_idle=5.0, fps_busy=2.0, min_majority=0.5, idle_reset_s=30.0,
                regreet_cooldown_s=10.0, new_session_id=lambda: "s0")  # fmt: skip
    s.handle(PersonArrived(1, (0.0, 0.0, 10.0, 10.0), 0.0, "biru", 0.9), 0.0)
    s.handle(SpeechDone(s.session_id, s.greeting_uid, 0.2), 1.0)
    s.handle(SpeechStarted(s.session_id, 2.0), 2.0)
    s.handle(Transcript(s.session_id, "jalur masuk apa saja", True, 0.5, 1.5), 3.0)
    return s, s.handle(AnswerReady(s.session_id, answer), 4.0)


LIST_ANSWER = "Ada tiga jalur masuk S1.\n- Jalur Prestasi\n- Jalur Minat Bakat\n- Jalur Reguler"


def test_session_speaks_normalized_list_then_offer_and_screen_keeps_text():
    final = FinalAnswer("answered", LIST_ANSWER, (CHUNK,), {}, "Pendaftaran")
    s, actions = _answered_session(final)
    [speak] = [a for a in actions if isinstance(a, Speak)]
    assert speak.text == ("Ada tiga jalur masuk S1. Jalur Prestasi, Jalur Minat Bakat, dan "
                          "Jalur Reguler. Mau tahu soal pendaftaran juga?")  # fmt: skip
    show = next(a for a in actions if isinstance(a, ShowView))
    assert show.answer == LIST_ANSWER and show.follow_up_topic == "Pendaftaran"
    assert s.history[-1].answer == LIST_ANSWER  # riwayat tanpa tawaran
    stop = s.handle(SpeechDone(s.session_id, s.answer_uid, 1.0), 5.0)
    kept = next(a for a in stop if isinstance(a, ShowView))
    assert kept.follow_up_topic == "Pendaftaran"  # tawaran tetap tampil setelah selesai bicara


def test_session_v2_answer_speaks_identical_text():
    text = "Biaya kuliah S1 Rp14.000.000 per tahun. Kelas sore Rp15.000.000."
    _s, actions = _answered_session(FinalAnswer("answered", text, (CHUNK,), {}))
    assert [a.text for a in actions if isinstance(a, Speak)] == [text]


# --- UI ------------------------------------------------------------------------------------


def test_view_json_follow_up_offer():
    vm = ViewModel()
    vm.apply(ShowView(VisitState.THINKING, transcript="jalur?", send_enabled=False))
    vm.apply(ShowView(VisitState.SPEAKING, transcript="jalur?", answer=LIST_ANSWER,
                      sources=(CHUNK,), follow_up_topic="Pendaftaran"))  # fmt: skip
    msg = state.view_json(vm)["messages"][-1]
    assert msg["text"] == LIST_ANSWER
    assert msg["follow_up"] == {"topic": "Pendaftaran", "text": "Mau tahu soal pendaftaran juga?"}


def test_formatter_renders_dash_lines_as_bullets():
    assert format_answer(LIST_ANSWER) == [
        {"type": "p", "text": "Ada tiga jalur masuk S1."},
        {"type": "ul", "items": ["Jalur Prestasi", "Jalur Minat Bakat", "Jalur Reguler"]},
    ]


def test_app_js_offer_button_reuses_topic_chip():
    from mica.webui.server import STATIC_DIR

    js = (STATIC_DIR / "app.js").read_text("utf-8")
    assert "topicButton(m.follow_up.topic, false)" in js  # sama dengan chip: mengisi kotak
    assert 'el("span", "", m.follow_up.text)' in js and "innerHTML" not in js
