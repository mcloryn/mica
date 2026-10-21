"""Langkah 55: rag.followup_mode concat | dual | llm_rewrite (mica.rag.followup)."""

import json
from datetime import date

import httpx
import pytest
from pydantic import SecretStr
from test_pipeline import ANSWER_SI, FakeRetriever, _pipeline, _settings

from mica.config import ConfigError
from mica.core.types import Chunk, ScoredChunk, ScrubbedText, Turn
from mica.rag.followup import (
    REWRITE_SCHEMA,
    CachedRewriter,
    ConcatFollowup,
    DualFollowup,
    GroqQueryRewriter,
    LlmRewriteFollowup,
    RewriteFailed,
    make_followup,
    parse_rewrite,
    rrf_fuse,
)
from mica.rag.retriever import DENSE_TOP1


def _chunk(cid):
    return Chunk(cid, "doc", "Dok", "Bagian", date(2026, 9, 29), "dev", f"isi {cid}", True)


A, B, C, D = (_chunk(c) for c in ("a", "b", "c", "d"))
S = ScrubbedText


class ByQuery:
    """Retriever palsu: daftar hasil per kueri persis."""

    def __init__(self, table, dense=None):
        self.table = table
        self.dense = dense or {}
        self.queries = []

    def search(self, query, k):
        self.queries.append(query)
        top = self.dense.get(query, 0.5)
        return [ScoredChunk(c, 1.0 / (i + 1), {"dense": i + 1}, {DENSE_TOP1: top})
                for i, c in enumerate(self.table[query][:k])]  # fmt: skip


class FakeRewriter:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def rewrite(self, question, previous, timeout_s):
        self.calls.append((question, previous, timeout_s))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


# --- concat: perilaku lama tidak berubah ---------------------------------------------------


def test_concat_joins_previous_question_like_before():
    r = ByQuery({"Biaya SI berapa? Kalau sore?": [A], "Kalau sore?": [B]})
    out = ConcatFollowup(r).search(S("Kalau sore?"), S("Biaya SI berapa?"), 5)
    assert r.queries == ["Biaya SI berapa? Kalau sore?"] and [h.chunk for h in out.hits] == [A]
    assert ConcatFollowup(r).search(S("Kalau sore?"), None, 5).query == "Kalau sore?"


# --- dual: RRF dua daftar -------------------------------------------------------------------


def test_rrf_fuse_sums_reciprocal_ranks_and_keeps_max_dense_top1():
    plain = [ScoredChunk(A, 0, {"bm25": 1}, {DENSE_TOP1: 0.4}),
             ScoredChunk(B, 0, {"bm25": 2}, {DENSE_TOP1: 0.4})]  # fmt: skip
    joined = [ScoredChunk(C, 0, {}, {DENSE_TOP1: 0.8}), ScoredChunk(B, 0, {}, {DENSE_TOP1: 0.8})]
    fused = rrf_fuse([plain, joined], rrf_k=60, k=3)
    # B: 1/62 + 1/62 > A: 1/61 = C: 1/61 (seri: urutan kemunculan pertama)
    assert [h.chunk.chunk_id for h in fused] == ["b", "a", "c"]
    assert fused[0].score == pytest.approx(2 / 62)
    assert all(h.raw_scores[DENSE_TOP1] == 0.8 for h in fused)
    assert len(rrf_fuse([plain, joined], 60, 1)) == 1


def test_dual_searches_plain_and_concat_then_fuses():
    r = ByQuery({"Biayanya?": [A, B], "Alamat? Biayanya?": [C, A]})
    out = DualFollowup(r, rrf_k=60, pool=20).search(S("Biayanya?"), S("Alamat?"), 2)
    assert r.queries == ["Biayanya?", "Alamat? Biayanya?"]
    assert [h.chunk.chunk_id for h in out.hits] == ["a", "c"]  # a di kedua daftar
    assert out.query == "Biayanya?" and out.rewrite_s is None


def test_dual_without_previous_is_plain_search():
    r = ByQuery({"Biaya?": [A, B]})
    out = DualFollowup(r, 60, 20).search(S("Biaya?"), None, 5)
    assert r.queries == ["Biaya?"] and [h.chunk for h in out.hits] == [A, B]


# --- llm_rewrite --------------------------------------------------------------------------


def test_llm_rewrite_uses_rewritten_query():
    r = ByQuery({"Biaya kuliah SI kelas sore berapa?": [B]})
    rw = FakeRewriter("Biaya kuliah SI kelas sore berapa?")
    out = LlmRewriteFollowup(r, rw, 4.0).search(S("Kalau sore?"), S("Biaya SI berapa?"), 5)
    assert rw.calls == [("Kalau sore?", "Biaya SI berapa?", 4.0)]
    assert out.query == "Biaya kuliah SI kelas sore berapa?" and not out.rewrite_fallback
    assert out.rewrite_s is not None and [h.chunk for h in out.hits] == [B]


@pytest.mark.parametrize("error", [RewriteFailed("timeout 4 detik"), RuntimeError("x")])
def test_llm_rewrite_failure_falls_back_to_question_not_concat(error):
    r = ByQuery({"Biaya kuliah S1?": [A]})
    out = LlmRewriteFollowup(r, FakeRewriter(error), 4.0).search(S("Biaya kuliah S1?"),
                                                                 S("Alamat kampus?"), 5)  # fmt: skip
    assert r.queries == ["Biaya kuliah S1?"] and out.rewrite_fallback


def test_llm_rewrite_without_previous_makes_no_call():
    rw = FakeRewriter("tidak dipakai")
    r = ByQuery({"Biaya?": [A]})
    out = LlmRewriteFollowup(r, rw, 4.0).search(S("Biaya?"), None, 5)
    assert rw.calls == [] and out.rewrite_s is None


def test_llm_rewrite_scrubs_text_before_api():
    rw = FakeRewriter("ok")
    r = ByQuery({"ok": [A]})
    LlmRewriteFollowup(r, rw, 4.0).search(S("nomor saya 081234567890 bisa?"), S("Alamat?"), 5)
    assert "081234567890" not in rw.calls[0][0]


@pytest.mark.parametrize("content", ["bukan json", '{"q": "x"}', '{"query": "  "}',
                                     '{"query": "x", "extra": 1}', '["x"]'])  # fmt: skip
def test_parse_rewrite_rejects_bad_output(content):
    with pytest.raises(RewriteFailed):
        parse_rewrite(content)


def _groq(handler):
    return GroqQueryRewriter("openai/gpt-oss-120b", api_key=SecretStr("k-test"),
                             temperature=0.2, reasoning_effort="low",
                             client=httpx.Client(transport=httpx.MockTransport(handler)))  # fmt: skip


def test_groq_rewriter_sends_strict_json_schema_and_parses():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        content = json.dumps({"query": "Biaya kuliah SI kelas sore berapa?"})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    out = _groq(handler).rewrite(S("Kalau sore?"), S("Biaya SI berapa?"), 4.0)
    assert out == "Biaya kuliah SI kelas sore berapa?"
    fmt = seen["body"]["response_format"]["json_schema"]
    assert fmt["strict"] is True and fmt["schema"] == REWRITE_SCHEMA
    assert "Pertanyaan baru: Kalau sore?" in seen["body"]["messages"][1]["content"]


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(429, json={}),
    lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]}),
    lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("lambat", request=r)),
])  # fmt: skip
def test_groq_rewriter_errors_raise_rewrite_failed(handler):
    with pytest.raises(RewriteFailed):
        _groq(handler).rewrite(S("a"), S("b"), 4.0)


def test_cached_rewriter_calls_api_once(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        content = json.dumps({"query": "utuh"})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    cached = CachedRewriter(_groq(handler), tmp_path)
    assert cached.rewrite(S("a"), S("b"), 4.0) == "utuh" and not cached.last_from_cache
    assert cached.rewrite(S("a"), S("b"), 4.0) == "utuh" and cached.last_from_cache
    assert len(calls) == 1 and cached.last_latency_s is not None


# --- konfigurasi dan pipeline ----------------------------------------------------------------


@pytest.mark.parametrize("mode,cls", [("concat", ConcatFollowup), ("dual", DualFollowup)])
def test_make_followup_by_config(tmp_path, mode, cls):
    assert isinstance(make_followup(_settings(tmp_path, followup_mode=mode), FakeRetriever()), cls)


def test_make_followup_llm_rewrite_needs_groq_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    settings = _settings(tmp_path, followup_mode="llm_rewrite")
    settings = settings.model_copy(update={"api_keys": settings.api_keys.model_copy(
        update={"groq": None})})  # fmt: skip
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        make_followup(settings, FakeRetriever())
    out = make_followup(settings, FakeRetriever(), rewriter=FakeRewriter("x"))
    assert isinstance(out, LlmRewriteFollowup)


def test_pipeline_records_rewrite_timing(tmp_path):
    # rewriter asli butuh GROQ_API_KEY; pipeline dirakit dengan concat lalu followup diganti
    pipeline, _, retriever = _pipeline(tmp_path, ANSWER_SI)
    pipeline.followup = LlmRewriteFollowup(retriever, FakeRewriter("Biaya SI kelas sore?"), 4.0)
    final = pipeline.answer("Kalau sore?", [Turn(S("Biaya SI berapa?"), "Rp14.000.000.")], "s")
    assert retriever.queries == ["Biaya SI kelas sore?"]
    assert "rewrite" in final.timings and final.timings["retrieval"] >= 0


def test_pipeline_concat_default_unchanged(tmp_path):
    pipeline, _, retriever = _pipeline(tmp_path, ANSWER_SI)
    pipeline.answer("Kalau sore?", [Turn(S("Biaya SI berapa?"), "Rp14.000.000.")], "s")
    assert retriever.queries == ["Biaya SI berapa? Kalau sore?"]
