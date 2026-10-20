"""Prompt v4 + field items (pra-registrasi docs/PROMPT-V4.md).

v2 dan v3 tidak berubah (hash), skema items Groq/Gemini, validasi, cek angka dan eval atas
answer + items, UI <ul>, TTS "A, B, dan C." / "Pertama ..., terakhir ...", dan --prompt-variant di
python -m mica.webui (dev saja).
"""

import hashlib
import json
from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from tests.unit.test_pipeline import FakeGate, FakeRetriever, _settings

from mica.audio.messages import Speak, SpeechDone, SpeechStarted, Transcript
from mica.core import texts
from mica.core.session import AnswerReady, Session, ShowView, VisitState
from mica.core.spoken import spoken_items, spoken_with_items
from mica.core.types import (
    Chunk,
    FinalAnswer,
    LlmAnswer,
    ScoredChunk,
    ScrubbedText,
    Turn,
    joined_answer,
)
from mica.eval import generation as gen
from mica.rag import prompts
from mica.rag.llm import (
    MAX_ITEMS,
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
from mica.webui import app as webui_app
from mica.webui import state
from mica.webui.app import WebUiError
from mica.webui.server import STATIC_DIR

TOPICS = ("Program Studi", "Biaya", "Beasiswa", "Pendaftaran", "Fasilitas", "Lokasi")
CHUNK = Chunk("03#2", "03", "Biaya Kuliah", "Biaya S1", date(2026, 9, 29), "dev",
              "Biaya S1 Rp14.000.000 per tahun.", False)  # fmt: skip


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _request(variant, topics=TOPICS):
    return build_prompt(ScrubbedText("Berapa biaya?"), [Turn(ScrubbedText("halo"), "hai")],
                        [ScoredChunk(CHUNK, 0.5, {"dense": 1})], variant, topics)  # fmt: skip


def _groq():
    return GroqProvider("openai/gpt-oss-120b", api_key=SecretStr("x"), temperature=0.2,
                        reasoning_effort="low")  # fmt: skip


def _gemini():
    return GeminiProvider("gemini-3.8-flash", mode="dev", api_key=SecretStr("x"), temperature=0.2,
                          reasoning_effort="low")  # fmt: skip


# --- v3 tidak berubah (v2: tests/unit/test_prompt_v3.py) ----------------------------------

# Hash dari kode commit f3e6818 (v3 dievaluasi dengan kode ini), dihitung 20 Okt 2026 sebelum v4.
V3_GOLDEN = {
    "system": "baee8bf5d6c6d2aab678e41d0b61af9633bede801aade4730325663a7c959c9a",
    "groq": "fb8ceecb5b9a6610fb899d0b9a28f05ae456c147227fbd22246e2bd2f88bd24d",
    "gemini": "aae6669490bef5b016a12c93a257f18d23b30b48700f04032c6ff6ab876bd121",
}


def test_v3_prompt_and_request_body_unchanged():
    assert _sha(system_prompt("v3", TOPICS)) == V3_GOLDEN["system"]
    assert _sha(_groq().request_body(_request("v3"))) == V3_GOLDEN["groq"]
    assert _sha(_gemini().request_body(_request("v3"))) == V3_GOLDEN["gemini"]
    assert not _request("v3").items_field and not _request("paraphrase").items_field


def test_v3_output_with_items_rejected():
    content = json.dumps({"status": "answered", "answer": "x", "citations": [],
                          "follow_up_topic": None, "items": []})  # fmt: skip
    with pytest.raises(_BadOutput, match="tidak dikenal"):
        parse_output(content, TOPICS)


# --- v4: teks prompt ----------------------------------------------------------------------


def test_v4_rules():
    v4 = system_prompt("v4", TOPICS)
    for rule in (prompts._ROLE, prompts._ONLY_SOURCES, prompts._ONLY_ASKED,
                 prompts._FALSE_PREMISE, prompts._EXACT_V3, prompts._INJECTION,
                 prompts._NO_ARITHMETIC, prompts._CITATIONS, prompts._DATA_NOT_INSTRUCTIONS,
                 prompts._FOLLOW_UP_V3.format(topics=", ".join(TOPICS))):  # fmt: skip
        assert rule in v4
    # diganti: nada tanpa wajib "kamu", bentuk tanpa baris "- ", plus items dan arahan kontak
    assert prompts._TONE_V3 not in v4 and prompts._FORM_V3 not in v4
    assert prompts._TONE_V4 in v4 and prompts._FORM_V4 in v4
    assert prompts._ITEMS_V4 in v4 and prompts._CONTACT_V4 in v4
    assert '"- "' not in v4 and "bila wajar" in v4 and "paling banyak 10 item" in v4
    assert "Jangan mengarang unit atau kontak" in v4 and '"items"' in v4
    assert prompt_version("v4") == "v4" and prompt_version("v3") == "v3"
    with pytest.raises(ValueError, match="topik"):
        system_prompt("v4")


def test_v4_request_carries_items_and_topics():
    req = _request("v4")
    assert req.items_field and req.follow_up_topics == TOPICS
    assert "v4" in gen.PROMPT_VARIANTS and gen.PER_QUESTION_COLUMNS[-1] == "items"


# --- v4: skema ----------------------------------------------------------------------------


def test_groq_schema_items_after_answer():
    schema = output_schema(("a",), TOPICS, items=True)
    assert list(schema["properties"]) == ["status", "answer", "items", "citations",
                                          "follow_up_topic"]  # fmt: skip
    assert schema["properties"]["items"] == {
        "type": "array", "items": {"type": "string"}, "maxItems": MAX_ITEMS
    }  # fmt: skip
    assert schema["required"] == ["status", "answer", "items", "citations", "follow_up_topic"]
    assert MAX_ITEMS == 10
    body = _groq().request_body(_request("v4"))
    assert "items" in body["response_format"]["json_schema"]["schema"]["required"]


def test_gemini_schema_items():
    schema = gemini_schema(("a",), TOPICS, items=True)
    assert schema["properties"]["items"] == {
        "type": "ARRAY", "items": {"type": "STRING"}, "maxItems": MAX_ITEMS
    }  # fmt: skip
    assert schema["propertyOrdering"] == ["status", "answer", "items", "citations",
                                          "follow_up_topic"]  # fmt: skip
    assert "items" in schema["required"]
    body = _gemini().request_body(_request("v4"))
    assert "items" in body["generationConfig"]["responseSchema"]["properties"]


def _v4(**kw):
    data = {"status": "answered", "answer": "Ada tiga jalur:", "items": ["A", "B", "C"],
            "citations": ["a"], "follow_up_topic": None, **kw}  # fmt: skip
    return json.dumps(data)


@pytest.mark.parametrize("values", [["A", "B", "C"], []])
def test_v4_parse_output_items(values):
    out = parse_output(_v4(items=values), TOPICS, items=True)
    assert out == ("answered", "Ada tiga jalur:", ("a",), None, tuple(values))


@pytest.mark.parametrize(
    "content",
    [
        json.dumps({"status": "answered", "answer": "x", "citations": [], "follow_up_topic": None}),
        _v4(items="A, B"),
        _v4(items=["A", 2]),
        _v4(items=[str(i) for i in range(MAX_ITEMS + 1)]),
    ],
)
def test_v4_parse_output_rejects(content):
    with pytest.raises(_BadOutput):
        parse_output(content, TOPICS, items=True)


# --- pipeline: cek angka atas answer + items ----------------------------------------------


class V4Llm:
    name = "fake"

    def __init__(self, answer, items, citations=("03_biaya#2",), status="answered"):
        self.reply = LlmAnswer(status, answer, tuple(citations), "groq:fake", 0.4, None,
                               "Beasiswa", tuple(items))  # fmt: skip
        self.requests = []

    def generate(self, request, timeout_s):
        self.requests.append(request)
        return self.reply


def _v4_pipeline(tmp_path, llm):
    from mica.core.logging import InteractionLog
    from mica.rag.checker import NumericFactChecker
    from mica.rag.pipeline import AnswerPipeline

    settings = _settings(tmp_path, prompt_variant="v4")
    return AnswerPipeline(settings, FakeRetriever(), FakeGate(True), llm, NumericFactChecker(),
                          kb_id="dev-test", log=InteractionLog(tmp_path / "logs"))  # fmt: skip


def test_v4_pipeline_passes_items(tmp_path):
    llm = V4Llm("Biaya SI per tahun:", ["kelas pagi Rp14.000.000", "kelas sore Rp15.000.000"])
    final, record = _v4_pipeline(tmp_path, llm).run("biaya SI berapa?", [], "s1")
    assert llm.requests[0].items_field
    assert final.status == "answered" and final.text == "Biaya SI per tahun:"
    assert final.items == ("kelas pagi Rp14.000.000", "kelas sore Rp15.000.000")
    assert record.answer == ("Biaya SI per tahun: kelas pagi Rp14.000.000; "
                             "kelas sore Rp15.000.000")  # fmt: skip
    assert record.prompt_version == "v4"


def test_v4_fact_check_covers_items(tmp_path):
    llm = V4Llm("Biaya SI per tahun:", ["kelas pagi Rp14.000.000", "kelas malam Rp99.000.000"])
    final, record = _v4_pipeline(tmp_path, llm).run("biaya SI berapa?", [], "s1")
    assert final.status == "refused_check" and final.items == ()
    assert record.fact_check["passed"] is False


def test_joined_answer():
    assert joined_answer("Ada tiga jalur:", ("A", "B", "C")) == "Ada tiga jalur: A; B; C"
    assert joined_answer("Biaya Rp14.000.000.", ()) == "Biaya Rp14.000.000."


# --- eval: cache, per_question, anotasi, copy ---------------------------------------------


def test_v4_cache_round_trip_and_v3_format(tmp_path):
    cache = gen.LlmCache(tmp_path)
    cache.put("k", LlmAnswer("answered", "x", ("a",), "groq:m", 0.5, None, None, ("A", "B")))
    assert cache.get("k").items == ("A", "B")
    cache.put("e", LlmAnswer("answered", "x", ("a",), "groq:m", 0.5, None, "Biaya", ()))
    data = json.loads((tmp_path / "e.json").read_text(encoding="utf-8"))
    assert "items" not in data and cache.get("e").items == ()


def _row(**kw):
    base = {"qid": "d004", "type": "answerable", "oos_level": None, "question": "jalur?",
                "reference_answer": "", "gate_score": 0.6, "llm_status": "answered",
                "answer": "Ada tiga jalur:", "citations": ("c#1",), "check_passed": True,
                "check_unsupported": (), "status_on": "answered", "status_off": "answered",
                "final_text": "", "provider": "groq:m", "usage": None, "timings": {}, "error_code": None,
                "llm_latency_s": 0.5, "from_cache": False, "items": ("Prestasi", "Minat Bakat", "Reguler"),
                "retrieved_ids": ("c#1",)}  # fmt: skip
    return gen.GenerationRow(**{**base, **kw})


def test_per_question_and_annotation_use_items():
    row = _row()
    assert gen._per_question_row(row)["items"] == "Prestasi; Minat Bakat; Reguler"
    assert gen._per_question_row(row)["answer"] == "Ada tiga jalur:"
    [ann] = gen.annotation_rows([row], SimpleNamespace(chunks=[]))
    assert ann["answer"] == "Ada tiga jalur: Prestasi; Minat Bakat; Reguler"
    assert gen._per_question_row(_row(items=()))["items"] == ""


def test_copy_rate_scores_answer_plus_items(tmp_path, monkeypatch):
    import csv

    import mica.rag.gate
    import mica.rag.llm
    import mica.rag.pipeline
    import mica.rag.retriever
    from mica.eval import copy_rate as cr
    from mica.eval.retrieval import sha256_file

    dataset = tmp_path / "q.jsonl"
    dataset.write_text('{"qid": "d004", "split": "dev"}\n', encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    (run / "run.json").write_text(json.dumps({
        "llm": {"model_override": "groq:m", "provider": "x"}, "kb_id": "kb1", "gate_off": True,
        "prompt_variant": "v4", "dataset": {"path": str(dataset), "sha256": sha256_file(dataset)},
    }), encoding="utf-8")  # fmt: skip
    with open(run / "per_question.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["qid", "llm_status", "answer", "citations", "items"])
        w.writeheader()
        w.writerow({"qid": "d004", "llm_status": "answered", "answer": "Ada tiga jalur:",
                    "citations": "c#1", "items": "Prestasi; Minat Bakat; Reguler"})  # fmt: skip

    class Llm:
        stats = SimpleNamespace(api_calls=0, from_cache=1)

    monkeypatch.setattr(gen, "effective_settings", lambda *a, **k: None)
    monkeypatch.setattr(gen, "EvalLlm", lambda *a, **k: Llm())
    monkeypatch.setattr(gen, "answer_questions", lambda *a, **k: [_row()])
    monkeypatch.setattr(gen, "dev_questions", lambda qs: qs)
    monkeypatch.setattr("mica.eval.dataset.load_questions", lambda path: [])
    monkeypatch.setattr(mica.rag.llm, "make_llm", lambda eff: SimpleNamespace(providers=[None]))
    monkeypatch.setattr(mica.rag.retriever, "make_retriever", lambda *a, **k: None)
    monkeypatch.setattr(mica.rag.gate, "make_gate", lambda eff: None)
    monkeypatch.setattr(mica.rag.pipeline, "AnswerPipeline", lambda *a, **k: None)
    _model, items, _info = cr.load_run(run, None, SimpleNamespace(kb_id="kb1"), tmp_path, None)
    assert items[0].answer == "Ada tiga jalur: Prestasi; Minat Bakat; Reguler"


# --- TTS dan sesi --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "items", "spoken"),
    [
        ("Ada tiga jalur masuk S1:", ["Prestasi", "Minat Bakat", "Reguler."],
         "Ada tiga jalur masuk S1: Prestasi, Minat Bakat, dan Reguler."),
        ("Pendaftaran online punya enam langkah:",
         ["daftar akun Google", "isi data diri", "pilih jalur", "verifikasi berkas",
          "daftar ulang", "resmi jadi mahasiswa baru"],
         ("Pendaftaran online punya enam langkah: Pertama daftar akun Google, kedua isi data "
         "diri, ketiga pilih jalur, keempat verifikasi berkas, kelima daftar ulang, terakhir "
         "resmi jadi mahasiswa baru.")),
        ("Tahapannya:", ["A", "B"], "Tahapannya: Pertama A, terakhir B."),
        ("Biaya Rp14.000.000 per tahun.", [], "Biaya Rp14.000.000 per tahun."),
    ],
)  # fmt: skip
def test_spoken_with_items(text, items, spoken):
    assert spoken_with_items(text, items) == spoken


def test_spoken_items_unordered_and_empty():
    assert spoken_items(["A", "B"]) == "A dan B." and spoken_items([]) == ""


def _answered(final):
    s = Session(fps_idle=5.0, fps_busy=2.0, min_majority=0.5, idle_reset_s=30.0,
                regreet_cooldown_s=10.0, new_session_id=lambda: "s0")  # fmt: skip
    s.handle(PersonArrived(1, (0.0, 0.0, 10.0, 10.0), 0.0, "biru", 0.9), 0.0)
    s.handle(SpeechDone(s.session_id, s.greeting_uid, 0.2), 1.0)
    s.handle(SpeechStarted(s.session_id, 2.0), 2.0)
    s.handle(Transcript(s.session_id, "jalur masuk apa saja", True, 0.5, 1.5), 3.0)
    return s, s.handle(AnswerReady(s.session_id, final), 4.0)


def test_session_speaks_answer_items_offer():
    items = ("Jalur Prestasi", "Jalur Minat Bakat", "Jalur Reguler")
    final = FinalAnswer("answered", "Ada tiga jalur masuk S1:", (CHUNK,), {}, "Biaya", items)
    s, actions = _answered(final)
    [speak] = [a for a in actions if isinstance(a, Speak)]
    assert speak.text == ("Ada tiga jalur masuk S1: Jalur Prestasi, Jalur Minat Bakat, dan "
                          "Jalur Reguler. Mau tahu soal biaya juga?")  # fmt: skip
    show = next(a for a in actions if isinstance(a, ShowView))
    assert show.answer == "Ada tiga jalur masuk S1:" and show.items == items
    assert s.history[-1].answer == ("Ada tiga jalur masuk S1: Jalur Prestasi; Jalur Minat "
                                    "Bakat; Jalur Reguler")  # fmt: skip
    done = s.handle(SpeechDone(s.session_id, s.answer_uid, 1.0), 5.0)
    assert next(a for a in done if isinstance(a, ShowView)).items == items


# --- UI web ---------------------------------------------------------------------------------


def test_view_json_items():
    vm = ViewModel()
    vm.apply(ShowView(VisitState.THINKING, transcript="jalur?", send_enabled=False))
    vm.apply(ShowView(VisitState.SPEAKING, transcript="jalur?", answer="Ada tiga jalur:",
                      sources=(CHUNK,), items=("A", "B", "C")))  # fmt: skip
    msg = state.view_json(vm)["messages"][-1]
    assert msg["text"] == "Ada tiga jalur:" and msg["items"] == ["A", "B", "C"]


def test_app_js_items_list_with_text_content():
    js = (STATIC_DIR / "app.js").read_text("utf-8")
    assert 'm.items.map((x) => el("li", "", x))' in js and "innerHTML" not in js
    assert 'el("ul", "answer-items")' in js
    assert '$("prompt_badge").textContent = c.prompt_badge' in js
    assert 'id="prompt_badge"' in (STATIC_DIR / "index.html").read_text("utf-8")


def test_prompt_badge_only_in_dev():
    ui = _settings().ui
    assert state.config_json(ui, dev=True, prompt_label="v4")["prompt_badge"] == "PROMPT v4 (dev)"
    assert state.config_json(ui, dev=False, prompt_label="v4")["prompt_badge"] is None
    assert state.config_json(ui, dev=True)["prompt_badge"] is None
    assert texts.PROMPT_BADGE.format(versi="v4") == "PROMPT v4 (dev)"


# --- python -m mica.webui --prompt-variant ------------------------------------------------


@pytest.mark.parametrize(("label", "variant"), [("v2", "paraphrase"), ("v3", "v3"), ("v4", "v4")])
def test_with_prompt_variant_dev(label, variant):
    settings = webui_app.with_prompt_variant(_settings(), label)
    assert settings.rag.prompt_variant == variant


def _kiosk_settings():
    s = _settings()
    return s.model_copy(update={"app": s.app.model_copy(update={"mode": "kiosk"})})


def test_with_prompt_variant_rejected_in_kiosk():
    with pytest.raises(WebUiError, match="dev"):
        webui_app.with_prompt_variant(_kiosk_settings(), "v4")


def test_main_prompt_variant_kiosk_exit_2(monkeypatch, capsys):
    monkeypatch.setattr(webui_app, "load_settings", lambda *a, **k: _kiosk_settings())
    monkeypatch.setattr(webui_app, "run", lambda *a, **k: pytest.fail("run tidak boleh jalan"))
    assert webui_app.main(["--prompt-variant", "v4", "--no-browser"]) == 2
    assert "--prompt-variant hanya boleh" in capsys.readouterr().err


def test_main_prompt_variant_dev_passes_label(monkeypatch):
    seen = {}
    monkeypatch.setattr(webui_app, "load_settings", lambda *a, **k: _settings())
    monkeypatch.setattr(webui_app, "run", lambda s, **k: seen.update(s=s, **k) or 0)
    assert webui_app.main(["--prompt-variant", "v4", "--no-browser"]) == 0
    assert seen["s"].rag.prompt_variant == "v4" and seen["prompt_label"] == "v4"
