"""V2-3: P1 (Reranker Protocol), P2 (prompt v6), P3 (gerbang 3 per kalimat), dan bukti bahwa
config prod tanpa kunci baru tetap berperilaku v5 (docs/PRA-REGISTRASI-V2.md)."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import yaml
from pydantic import SecretStr
from tests.unit.test_pipeline import SI, FakeGate, FakeLlm, FakeRetriever

from mica.config import ConfigError, load_settings
from mica.core.logging import InteractionLog
from mica.core.types import Chunk, ScoredChunk, ScrubbedText
from mica.rag.checker import NumericFactChecker
from mica.rag.pipeline import AnswerPipeline
from mica.rag.prompts import build_prompt, prompt_version, system_prompt
from mica.rag.rerank import CrossEncoderReranker, RerankedRetriever
from mica.rag.verifier import (
    VERIFY_SCHEMA,
    GroqSentenceVerifier,
    VerifyFailed,
    VerifyResult,
    is_courtesy,
    make_verifier,
    parse_verdicts,
    split_sentences,
    verify_with,
)

ROOT = Path(__file__).resolve().parents[2]
PROD_YAML = ROOT / "config" / "prod.yaml"
DEV_YAML = ROOT / "config" / "dev.yaml"


def _prod():
    return load_settings(PROD_YAML, require_complete=False)


def _with(path: Path, tmp_path: Path, mutate) -> object:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(raw)
    out = tmp_path / "cfg.yaml"
    out.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_settings(out, require_complete=False)


# --- default mati: prod tetap v5 ---------------------------------------------------------------


def test_prod_defaults_keep_v5_behaviour():
    s = _prod()
    assert s.rag.prompt_variant == "v5"
    assert s.rag.reranker.enabled is False
    assert s.rag.gate.sentence_verify.enabled is False
    assert make_verifier(s) is None


def test_default_sentence_verify_not_in_config_hash(tmp_path):
    s = _prod()
    assert "sentence_verify" not in s._config_dict()["rag"]["gate"]
    # menulis kunci baru dengan nilai bawaan tidak mengubah hash
    explicit = _with(PROD_YAML, tmp_path, lambda r: r["rag"]["gate"].update(
        {"sentence_verify": {"enabled": False, "provider": None, "temperature": None}}))  # fmt: skip
    assert explicit.config_hash() == s.config_hash()
    on = _with(PROD_YAML, tmp_path, lambda r: r["rag"]["gate"].update(
        {"sentence_verify": {"enabled": True}}))  # fmt: skip
    assert on.config_hash() != s.config_hash()


def test_prod_pipeline_has_no_verifier_and_log_unchanged(tmp_path):
    reply = ("answered", "Biaya kuliah S1 Sistem Informasi kelas pagi Rp14.000.000 per tahun.",
             ["03_biaya#2"])  # fmt: skip
    pipeline = AnswerPipeline(_prod(), FakeRetriever(), FakeGate(), FakeLlm(reply),
                              NumericFactChecker(), kb_id="t", log=InteractionLog(tmp_path))  # fmt: skip
    assert pipeline.verifier is None
    final, rec = pipeline.run("Biaya SI?", [], "s")
    assert final.text == reply[1]
    assert "sentence_verify" not in rec.fact_check
    assert rec.prompt_version == "v5"


# --- P2 prompt v6 ------------------------------------------------------------------------------


def test_v6_keeps_v5_rules_and_adds_three():
    v5 = system_prompt("v5", source_priority=("pmb",))
    v6 = system_prompt("v6", source_priority=("pmb",))
    body = lambda text: [line.split(". ", 1)[1] for line in text.splitlines() if ". " in line[:4]]
    v5_rules, v6_rules = body(v5), body(v6)
    assert set(v5_rules) - set(v6_rules) == {v5_rules[1]}  # hanya aturan sumber yang diganti
    assert len(v6_rules) == len(v5_rules) + 3
    assert '"biasanya"' in v6 and "sebagian pertanyaan" in v6 and "citations" in v6
    assert v6.endswith(v5.rsplit("\n\n", 1)[1])  # skema keluaran sama
    assert prompt_version("v6") == "v6" and prompt_version("v5") == "v5"


def test_v6_uses_v5_chunk_header():
    hit = ScoredChunk(SI, 0.1, {}, {})
    req5 = build_prompt(ScrubbedText("x"), [], [hit], "v5", source_priority=("pmb",))
    req6 = build_prompt(ScrubbedText("x"), [], [hit], "v6", source_priority=("pmb",))
    assert req5.user == req6.user and req5.system != req6.system


def test_v6_accepted_by_config(tmp_path):
    s = _with(DEV_YAML, tmp_path, lambda r: r["rag"].update({"prompt_variant": "v6"}))
    assert s.rag.prompt_variant == "v6"


# --- P1 reranker -------------------------------------------------------------------------------


def _hits(n):
    return [
        ScoredChunk(Chunk(f"d#{i}", "d", "D", "", date(2026, 1, 1), "dev", f"teks {i}", False),
                    0.1 - i * 0.01, {"hybrid": i + 1}, {"dense@1": 0.6})
        for i in range(n)
    ]  # fmt: skip


class _Base:
    def __init__(self, n):
        self.n = n
        self.k_seen = []

    def search(self, query, k):
        self.k_seen.append(k)
        return _hits(min(k, self.n))


class _Reverse:
    def rerank(self, query, hits, k):
        return list(reversed(hits))[:k]


def test_reranked_retriever_uses_reranker_protocol_with_pool():
    base = _Base(30)
    rr = RerankedRetriever(base, "m", pool=20, reranker=_Reverse())
    out = rr.search("q", 5)
    assert base.k_seen == [20]  # kandidat 20 -> top 5
    assert [h.chunk.chunk_id for h in out] == ["d#19", "d#18", "d#17", "d#16", "d#15"]


class _Enc:
    def predict(self, pairs, **kw):
        return [float(t.split()[-1]) for _, t in pairs]  # skor = angka di teks


def test_cross_encoder_reranker_orders_by_score_and_keeps_dense_signal():
    rr = CrossEncoderReranker("m", loader=_Enc)
    out = rr.rerank("q", _hits(6), 3)
    assert [h.chunk.chunk_id for h in out] == ["d#5", "d#4", "d#3"]
    assert out[0].ranks["rerank"] == 1 and out[0].raw_scores["dense@1"] == 0.6
    assert rr.rerank("q", [], 3) == []


# --- P3 verifikator ----------------------------------------------------------------------------


def test_split_sentences_keeps_abbreviations_and_numbers():
    text = ("Rektornya Hardy, S.Kom., M.Sc., Ph.D. Biayanya Rp14.000.000 per tahun. "
            "Alamatnya Jl. Thamrin No. 140, Medan. Silakan tanyakan langsung ke staf PMB.")  # fmt: skip
    parts = split_sentences(text)
    assert parts[-1] == "Silakan tanyakan langsung ke staf PMB."
    assert any("Rp14.000.000 per tahun." in p for p in parts)
    assert any(p.startswith("Alamatnya Jl. Thamrin No. 140") for p in parts)


def test_courtesy_without_facts_is_not_checked():
    assert is_courtesy("Silakan tanyakan langsung ke staf PMB di ruangan ini.")
    assert not is_courtesy("Silakan hubungi staf PMB di WA 081160025151.")
    assert not is_courtesy("Biaya kuliah Rp14.000.000 per tahun.")


def test_verify_with_removes_unsupported_and_skips_courtesy():
    sent = []

    def call(claims, hits):
        sent.extend(claims)
        return [(True, "ada"), (False, "tidak ada di potongan")]

    answer = "Biaya Rp14.000.000. Biasanya naik tiap tahun. Silakan tanyakan ke staf PMB."
    res = verify_with(call, answer, [])
    assert sent == ["Biaya Rp14.000.000.", "Biasanya naik tiap tahun."]
    assert res.kept_text == "Biaya Rp14.000.000. Silakan tanyakan ke staf PMB."
    assert res.removed == 1 and not res.rejected
    log = res.to_log()
    assert [s["supported"] for s in log["sentences"]] == [True, False, None]
    assert log["sentences"][2]["checked"] is False


def test_verify_rejects_when_no_claim_left_or_error():
    assert verify_with(lambda c, h: [(False, "")], "Biasanya ada.", []).rejected
    assert verify_with(lambda c, h: [], "Silakan tanyakan ke staf PMB.", []).rejected

    def boom(c, h):
        raise VerifyFailed("HTTP 429")

    res = verify_with(boom, "Biaya Rp14.000.000.", [])
    assert res.rejected and res.error == "HTTP 429" and res.kept_text == ""


def test_parse_verdicts_requires_every_sentence():
    ok = json.dumps({"verdicts": [{"id": 2, "supported": False, "reason": "x"},
                                  {"id": 1, "supported": True, "reason": "y"}]})  # fmt: skip
    assert parse_verdicts(ok, 2) == [(True, "y"), (False, "x")]
    with pytest.raises(VerifyFailed):
        parse_verdicts(json.dumps({"verdicts": [{"id": 1, "supported": True, "reason": ""}]}), 2)
    with pytest.raises(VerifyFailed):
        parse_verdicts("bukan json", 1)


def test_groq_verifier_one_call_strict_schema():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        content = json.dumps({"verdicts": [{"id": 1, "supported": True, "reason": "ok"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    v = GroqSentenceVerifier("openai/gpt-oss-120b", api_key=SecretStr("k"), timeout_s=5,
                             temperature=0.0, client=httpx.Client(transport=httpx.MockTransport(handler)))  # fmt: skip
    res = v.verify(
        "Biaya Rp14.000.000. Silakan tanyakan ke staf PMB.", [ScoredChunk(SI, 0.1, {}, {})]
    )
    assert len(bodies) == 1 and res.kept_text.startswith("Biaya")
    body = bodies[0]
    assert body["temperature"] == 0.0
    assert body["response_format"]["json_schema"]["schema"] == VERIFY_SCHEMA
    assert "03_biaya#2" in body["messages"][1]["content"]
    assert "Silakan" not in body["messages"][1]["content"]  # kalimat sopan tidak dikirim


def test_groq_verifier_http_error_fails_closed():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    v = GroqSentenceVerifier("m", api_key=SecretStr("k"), timeout_s=5, client=client)
    res = v.verify("Biaya Rp14.000.000.", [])
    assert res.rejected and res.error == "HTTP 429"


def test_make_verifier_from_config(tmp_path):
    on = _with(DEV_YAML, tmp_path, lambda r: r["rag"]["gate"].update(
        {"sentence_verify": {"enabled": True, "temperature": 0.0}}))  # fmt: skip
    on = on.model_copy(update={"api_keys": on.api_keys.model_copy(update={"groq": SecretStr("k")})})
    v = make_verifier(on)
    assert isinstance(v, GroqSentenceVerifier) and v.temperature == 0.0
    bad = _with(DEV_YAML, tmp_path, lambda r: r["rag"]["gate"].update(
        {"sentence_verify": {"enabled": True, "provider": "gemini:x"}}))  # fmt: skip
    with pytest.raises(ConfigError):
        make_verifier(bad)


class _FakeVerifier:
    def __init__(self, keep):
        self.keep = keep

    def verify(self, answer, hits):
        return verify_with(lambda c, h: [(i in self.keep, "") for i in range(len(c))], answer, hits)


def _vpipe(tmp_path, keep, answer):
    reply = ("answered", answer, ["03_biaya#2"])
    return AnswerPipeline(load_settings(DEV_YAML), FakeRetriever(), FakeGate(), FakeLlm(reply),
                          NumericFactChecker(), kb_id="t", log=InteractionLog(tmp_path),
                          verifier=_FakeVerifier(keep))  # fmt: skip


def test_pipeline_prunes_unsupported_sentence_and_logs_verdicts(tmp_path):
    answer = "Biaya SI pagi Rp14.000.000 per tahun. Biasanya naik setiap tahun."
    final, rec = _vpipe(tmp_path, {0}, answer).run("Biaya SI?", [], "s")
    assert final.status == "answered"
    assert final.text == "Biaya SI pagi Rp14.000.000 per tahun."
    sv = rec.fact_check["sentence_verify"]
    assert sv["removed"] == 1 and [s["supported"] for s in sv["sentences"]] == [True, False]
    assert rec.fact_check["passed"] is True  # cek angka lama tetap jalan atas jawaban terpangkas


def test_pipeline_rejects_when_all_claims_unsupported(tmp_path):
    final, rec = _vpipe(tmp_path, set(), "Biasanya naik setiap tahun.").run("Naik?", [], "s")
    assert final.status == "refused_check" and rec.error_code == "REFUSED_CHECK"
    assert rec.fact_check["sentence_verify"]["rejected"] is True


def test_verify_result_defaults():
    assert VerifyResult().rejected  # tanpa kalimat klaim -> ditolak
