"""Penanganan pertanyaan lanjutan sebelum retrieval (F-12, ADR-05; Langkah 55, docs/FOLLOWUP.md).

rag.followup_mode memilih implementasi FollowupQuery (Provisional, dipilih lewat konfigurasi):
- concat: kueri = pertanyaan sebelumnya + pertanyaan baru (perilaku lama, SDD 7.3).
- dual: retrieval untuk pertanyaan apa adanya DAN untuk concat, digabung dengan RRF yang sama
  dengan HybridRrfRetriever (score = sum 1 / (rrf_k + rank)). Tanpa panggilan LLM.
- llm_rewrite: LLM menulis ulang pertanyaan baru menjadi kalimat utuh hanya bila memang
  lanjutan (Elgohary dkk. 2019; Ma dkk. 2023). Gagal/timeout/keluaran rusak -> pertanyaan baru
  apa adanya (bukan concat).
Tanpa pertanyaan sebelumnya, atau standalone=True (chip topik, Langkah 53 opsi A), semua mode
mencari pertanyaan apa adanya. Semua teks yang dikirim ke API sudah melewati scrub_pii.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import SecretStr

from mica.config import CFG_INVALID, ConfigError, Settings
from mica.core.types import ScoredChunk, ScrubbedText
from mica.rag.llm import GROQ_URL
from mica.rag.pii import scrub_pii
from mica.rag.retriever import Retriever

logger = logging.getLogger(__name__)

REWRITE_SYSTEM = (
    "Kamu menyiapkan kueri pencarian dokumen PMB Universitas Mikroskil. Kamu menerima pertanyaan "
    "sebelumnya dan pertanyaan baru dari pengunjung kiosk. Bila pertanyaan baru adalah lanjutan "
    "yang tidak bisa dipahami tanpa pertanyaan sebelumnya (misalnya tidak menyebut hal yang "
    "ditanyakan, atau merujuk ke pertanyaan sebelumnya), tulis ulang menjadi satu kalimat "
    "pertanyaan utuh dalam bahasa Indonesia yang bisa dipahami sendiri, memakai hanya kata dari "
    "kedua pertanyaan. Bila pertanyaan baru sudah utuh atau berganti topik, kembalikan pertanyaan "
    "baru persis apa adanya. Jangan menjawab pertanyaan dan jangan menambah informasi. "
    'Balas hanya JSON {"query": "..."}.'
)
REWRITE_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
    "additionalProperties": False,
}


@dataclass
class FollowupResult:
    """Hasil retrieval plus keterangan untuk log/eval (teks kueri tidak dicatat di log M-11)."""

    hits: list[ScoredChunk]
    query: str  # kueri efektif (dual: pertanyaan apa adanya)
    rewrite_s: float | None = None  # durasi panggilan LLM rewrite; None bila tidak dipanggil
    rewrite_fallback: bool = False
    info: dict[str, Any] = field(default_factory=dict)


class FollowupQuery(Protocol):
    name: str

    def search(
        self, question: ScrubbedText, previous: ScrubbedText | None, k: int
    ) -> FollowupResult: ...


def concat_query(question: str, previous: str | None) -> str:
    return f"{previous} {question}" if previous else question  # F-12


class ConcatFollowup:
    name = "concat"

    def __init__(self, retriever: Retriever) -> None:
        self.retriever = retriever

    def search(
        self, question: ScrubbedText, previous: ScrubbedText | None, k: int
    ) -> FollowupResult:
        query = concat_query(question, previous)
        return FollowupResult(list(self.retriever.search(query, k)), query)


def rrf_fuse(lists: list[list[ScoredChunk]], rrf_k: int, k: int) -> list[ScoredChunk]:
    """RRF atas beberapa daftar hasil (rumus SDD 7.3, sama dengan HybridRrfRetriever).

    ranks/raw_scores diambil dari kemunculan pertama; dense@1 diambil maksimum dari semua daftar
    supaya sinyal gerbang (gate_signal) tidak lebih rendah daripada salah satu kueri."""
    scores: dict[str, float] = {}
    first: dict[str, ScoredChunk] = {}
    order_seen: dict[str, int] = {}
    for hits in lists:
        for rank, hit in enumerate(hits, start=1):
            cid = hit.chunk.chunk_id
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)
            if cid not in first:
                first[cid] = hit
                order_seen[cid] = len(order_seen)
    order = sorted(scores, key=lambda c: (-scores[c], order_seen[c]))[:k]
    from mica.rag.retriever import DENSE_TOP1

    tops = [h.raw_scores[DENSE_TOP1] for hs in lists for h in hs if DENSE_TOP1 in h.raw_scores]
    extra = {DENSE_TOP1: max(tops)} if tops else {}
    return [
        ScoredChunk(
            chunk=first[c].chunk,
            score=scores[c],
            ranks=dict(first[c].ranks),
            raw_scores={**first[c].raw_scores, **extra},
        )
        for c in order
    ]


class DualFollowup:
    name = "dual"

    def __init__(self, retriever: Retriever, rrf_k: int, pool: int) -> None:
        self.retriever = retriever
        self.rrf_k = rrf_k
        self.pool = pool

    def search(
        self, question: ScrubbedText, previous: ScrubbedText | None, k: int
    ) -> FollowupResult:
        if not previous:
            return FollowupResult(list(self.retriever.search(question, k)), question)
        n = max(k, self.pool)
        plain = list(self.retriever.search(question, n))
        joined = list(self.retriever.search(concat_query(question, previous), n))
        return FollowupResult(rrf_fuse([plain, joined], self.rrf_k, k), question)


class QueryRewriter(Protocol):
    def rewrite(self, question: ScrubbedText, previous: ScrubbedText, timeout_s: float) -> str:
        """Kueri utuh; melempar exception bila gagal (pemanggil memakai pertanyaan apa adanya)."""
        ...


class RewriteFailed(Exception):
    pass


def rewrite_user(question: str, previous: str) -> str:
    return f"Pertanyaan sebelumnya: {previous}\nPertanyaan baru: {question}"


def parse_rewrite(content: str) -> str:
    try:
        data = json.loads(content)
    except ValueError:
        raise RewriteFailed("keluaran bukan JSON") from None
    query = data.get("query") if isinstance(data, dict) else None
    if not isinstance(query, str) or not query.strip() or set(data) != {"query"}:
        raise RewriteFailed("keluaran tidak sesuai skema {query}")
    return " ".join(query.split())


class GroqQueryRewriter:
    """Satu panggilan Groq, JSON ketat {"query": "..."}; tanpa coba ulang (anggaran latensi)."""

    def __init__(
        self,
        model: str,
        *,
        api_key: SecretStr,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.get_secret_value():
            raise ConfigError(CFG_INVALID, "GROQ_API_KEY belum diisi di .env")
        self.model = model
        self.name = f"groq:{model}"
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self._api_key = api_key
        self._client = client or httpx.Client()

    def body(self, question: str, previous: str) -> dict[str, Any]:
        """Badan request persis seperti dikirim (tanpa key); kunci cache eval."""
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": REWRITE_SYSTEM},
                {"role": "user", "content": rewrite_user(question, previous)},
            ],
            "include_reasoning": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "mica_rewrite", "strict": True, "schema": REWRITE_SCHEMA},
            },
            "stream": False,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def rewrite(self, question: ScrubbedText, previous: ScrubbedText, timeout_s: float) -> str:
        try:
            response = self._client.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                json=self.body(question, previous),
                timeout=httpx.Timeout(timeout_s),
            )
        except httpx.TimeoutException:
            raise RewriteFailed(f"timeout {timeout_s} detik") from None
        except httpx.HTTPError as exc:
            raise RewriteFailed(f"galat koneksi: {type(exc).__name__}") from None
        if response.status_code != 200:
            raise RewriteFailed(f"HTTP {response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise RewriteFailed("respons tanpa choices[0].message.content") from None
        return parse_rewrite(content)


class CachedRewriter:
    """Eval saja (hemat kuota Groq): cache di data/cache/llm/rewrite/<sha256 badan>.json."""

    def __init__(self, inner: GroqQueryRewriter, cache_dir: Path) -> None:
        self.inner = inner
        self.dir = Path(cache_dir)
        self.hits = 0
        self.calls = 0
        # latensi panggilan API asli (dari cache: latensi saat pertama dipanggil)
        self.last_latency_s: float | None = None
        self.last_from_cache = False

    def _path(self, question: str, previous: str) -> Path:
        raw = json.dumps(self.inner.body(question, previous), sort_keys=True, ensure_ascii=False)
        return self.dir / f"{hashlib.sha256(raw.encode('utf-8')).hexdigest()}.json"

    def rewrite(self, question: ScrubbedText, previous: ScrubbedText, timeout_s: float) -> str:
        path = self._path(question, previous)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.hits += 1
            self.last_latency_s, self.last_from_cache = data["latency_s"], True
            return data["query"]
        self.calls += 1
        started = time.perf_counter()
        query = self.inner.rewrite(question, previous, timeout_s)  # gagal: tidak di-cache
        self.last_latency_s, self.last_from_cache = time.perf_counter() - started, False
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"query": query, "latency_s": self.last_latency_s},
                                   ensure_ascii=False), encoding="utf-8")  # fmt: skip
        return query


class LlmRewriteFollowup:
    name = "llm_rewrite"

    def __init__(self, retriever: Retriever, rewriter: QueryRewriter, timeout_s: float) -> None:
        self.retriever = retriever
        self.rewriter = rewriter
        self.timeout_s = timeout_s

    def search(
        self, question: ScrubbedText, previous: ScrubbedText | None, k: int
    ) -> FollowupResult:
        if not previous:
            return FollowupResult(list(self.retriever.search(question, k)), question)
        started = time.perf_counter()
        fallback = False
        try:
            # N-09: kedua teks sudah di-scrub pemanggil; scrub ulang murah dan menjaga API
            query = self.rewriter.rewrite(scrub_pii(question), scrub_pii(previous), self.timeout_s)
        except Exception as exc:  # noqa: BLE001 - rewrite tidak boleh menggagalkan jawaban
            logger.warning("rewrite gagal (%s); pakai pertanyaan apa adanya", type(exc).__name__)
            query, fallback = question, True
        rewrite_s = time.perf_counter() - started
        query = scrub_pii(query)  # keluaran LLM juga di-scrub sebelum masuk retrieval/log
        hits = list(self.retriever.search(query, k))
        return FollowupResult(hits, query, rewrite_s=rewrite_s, rewrite_fallback=fallback)


def make_followup(
    settings: Settings, retriever: Retriever, rewriter: QueryRewriter | None = None
) -> FollowupQuery:
    """Pilih implementasi lewat rag.followup_mode."""
    rag = settings.rag
    mode = rag.followup_mode
    if mode == "concat":
        return ConcatFollowup(retriever)
    if mode == "dual":
        if rag.rrf_k is None:
            raise ConfigError(CFG_INVALID, "rag.followup_mode = dual butuh rag.rrf_k")
        return DualFollowup(retriever, rag.rrf_k, rag.candidates_per_retriever or rag.top_k)
    if settings.llm.timeout_s is None:
        raise ConfigError(CFG_INVALID, "rag.followup_mode = llm_rewrite butuh llm.timeout_s")
    if rewriter is None:
        entry = settings.llm.chain[0]
        kind, _, model = entry.partition(":")
        if kind != "groq":
            raise ConfigError(CFG_INVALID, f"llm_rewrite memakai llm.chain[0] Groq, bukan {entry}")
        rewriter = GroqQueryRewriter(
            model,
            api_key=settings.api_keys.groq or SecretStr(""),
            temperature=settings.llm.temperature,
            reasoning_effort=settings.llm.reasoning_effort,
        )
    return LlmRewriteFollowup(retriever, rewriter, settings.llm.timeout_s)
