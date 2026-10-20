"""M-06: AnswerPipeline, satu pertanyaan dari teks sampai FinalAnswer (SDD 7.3, ADR-05/06/07).

Alur tetap: scrub_pii -> kueri (concat dengan pertanyaan sebelumnya bila followup) -> retrieve
top_k -> gerbang -> prompt -> rantai LLM -> validasi sitasi -> cek angka -> FinalAnswer.
Setiap jawaban menghasilkan tepat satu TurnRecord di log M-11.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from mica.config import CFG_INVALID, ConfigError, Settings
from mica.core.logging import InteractionLog, TurnRecord
from mica.core.types import (
    Chunk,
    ErrorCode,
    FinalAnswer,
    GateDecision,
    LlmAnswer,
    LlmBadOutput,
    LlmRequest,
    LlmUnavailable,
    ScoredChunk,
    ScrubbedText,
    Turn,
    joined_answer,
)
from mica.rag.checker import FactChecker
from mica.rag.gate import RelevanceGate
from mica.rag.llm import LLMProvider
from mica.rag.pii import scrub_pii
from mica.rag.prompts import REFUSAL, UNAVAILABLE, build_prompt, prompt_version
from mica.rag.retriever import Retriever

Status = Literal[
    "answered", "refused_gate", "refused_llm", "false_premise", "refused_check", "unavailable"
]


@dataclass
class _Trace:
    """Isi baris log yang dikumpulkan sepanjang alur."""

    started: float
    timings: dict[str, float] = field(default_factory=dict)
    hits: list[ScoredChunk] = field(default_factory=list)
    gate: GateDecision | None = None
    out: LlmAnswer | None = None
    fact_check: dict[str, Any] | None = None
    error_code: str | None = None

    def stage(self, name: str, since: float) -> float:
        now = time.perf_counter()
        self.timings[name] = now - since
        return now


class AnswerPipeline:
    def __init__(
        self,
        settings: Settings,
        retriever: Retriever,
        gate: RelevanceGate,
        llm: LLMProvider,
        checker: FactChecker,
        kb_id: str,
        log: InteractionLog | None = None,
    ) -> None:
        rag = settings.rag
        if rag.followup_mode == "llm_rewrite":
            raise ConfigError(
                CFG_INVALID,
                "rag.followup_mode = llm_rewrite belum diimplementasikan (E-02); pakai concat",
            )
        if settings.llm.timeout_s is None:
            raise ConfigError(CFG_INVALID, "llm.timeout_s wajib diisi untuk AnswerPipeline")
        self.settings = settings
        self.retriever = retriever
        self.gate = gate
        self.llm = llm
        self.checker = checker
        self.kb_id = kb_id
        self.log = log
        self.timeout_s = settings.llm.timeout_s
        self.config_hash = settings.config_hash()

    def answer(
        self,
        question: str,
        history: Sequence[Turn],
        session_id: str,
        *,
        input_mode: Literal["voice", "text"] = "text",
    ) -> FinalAnswer:
        return self.run(question, history, session_id, input_mode=input_mode)[0]

    def run(
        self,
        question: str,
        history: Sequence[Turn],
        session_id: str,
        *,
        input_mode: Literal["voice", "text"] = "text",
    ) -> tuple[FinalAnswer, TurnRecord]:
        """Seperti answer(), tetapi juga mengembalikan baris log (untuk CLI dan eval)."""
        rag = self.settings.rag
        trace = _Trace(started=time.perf_counter())
        t = trace.started

        q = scrub_pii(question)
        t = trace.stage("scrub", t)

        query = q
        if history and rag.followup_mode == "concat":
            query = ScrubbedText(f"{history[-1].question} {q}")  # F-12
        trace.hits = list(self.retriever.search(query, rag.top_k))
        t = trace.stage("retrieval", t)

        trace.gate = self.gate.decide(trace.hits)
        if not trace.hits:
            # tanpa potongan tidak ada yang bisa dijawab, juga saat ambang masih null
            trace.gate = GateDecision(False, trace.gate.score, trace.gate.threshold)
        t = trace.stage("gate", t)
        if not trace.gate.passed:
            trace.error_code = ErrorCode.REFUSED_GATE
            return self._finish(
                trace, "refused_gate", REFUSAL, (), q, history, session_id, input_mode
            )

        recent = list(history[-rag.history_turns :]) if rag.history_turns > 0 else []
        request = self._request(q, recent, trace.hits)
        try:
            trace.out = self.llm.generate(request, self.timeout_s)
        except LlmUnavailable:
            trace.stage("llm", t)
            trace.error_code = ErrorCode.LLM_UNAVAILABLE
            return self._finish(
                trace, "unavailable", UNAVAILABLE, (), q, history, session_id, input_mode
            )
        except LlmBadOutput:
            trace.stage("llm", t)
            trace.error_code = ErrorCode.LLM_BAD_OUTPUT
            return self._finish(
                trace, "refused_check", REFUSAL, (), q, history, session_id, input_mode
            )
        t = trace.stage("llm", t)
        out = trace.out

        if out.status == "not_found":
            return self._finish(
                trace, "refused_llm", REFUSAL, (), q, history, session_id, input_mode
            )

        by_id = {h.chunk.chunk_id: h.chunk for h in trace.hits}
        cited_ok = bool(out.citations) and all(c in by_id for c in out.citations)
        if out.status == "answered" and not cited_ok:
            trace.stage("check", t)
            trace.error_code = ErrorCode.REFUSED_CHECK
            return self._finish(
                trace, "refused_check", REFUSAL, (), q, history, session_id, input_mode
            )
        # urutan sumber mengikuti urutan sitasi; duplikat dibuang
        sources = tuple(by_id[c] for c in dict.fromkeys(out.citations) if c in by_id)

        if rag.fact_check.enabled:  # juga untuk false_premise (SDD 7.3)
            premise = q if out.status == "false_premise" else None
            # prompt v4: angka di items juga dicek
            result = self.checker.check(
                joined_answer(out.answer, out.items), list(sources), premise
            )
            trace.fact_check = {
                "passed": result.passed,
                "checked": result.checked,
                "unsupported": list(result.unsupported),
            }
            trace.stage("check", t)
            if not result.passed:
                trace.error_code = ErrorCode.REFUSED_CHECK
                return self._finish(
                    trace, "refused_check", REFUSAL, (), q, history, session_id, input_mode
                )

        return self._finish(
            trace, out.status, out.answer, sources, q, history, session_id, input_mode,
            follow_up_topic=out.follow_up_topic, items=out.items,
        )  # fmt: skip

    def _variant(self, provider: str | None) -> Any:
        """Varian prompt penyedia ini (llm.prompt_variants), atau penyedia pertama rantai."""
        llm = self.settings.llm
        name = provider if provider is not None else llm.chain[0]
        return llm.prompt_variant_for(name, self.settings.rag.prompt_variant)

    def _request(self, q: ScrubbedText, recent: list[Turn], hits: list[ScoredChunk]) -> LlmRequest:
        """Request penyedia pertama + alternatif untuk penyedia lain yang variannya berbeda."""
        topics = self.settings.ui.topics
        first = self._variant(None)
        request = build_prompt(q, recent, hits, first, topics)
        alternates = []
        for name in self.settings.llm.chain[1:]:
            variant = self._variant(name)
            if variant != first:
                alternates.append((name, build_prompt(q, recent, hits, variant, topics)))
        return replace(request, alternates=tuple(alternates)) if alternates else request

    def _finish(
        self,
        trace: _Trace,
        status: Status,
        text: str,
        sources: tuple[Chunk, ...],
        question: ScrubbedText,
        history: Sequence[Turn],
        session_id: str,
        input_mode: Literal["voice", "text"],
        follow_up_topic: str | None = None,
        items: tuple[str, ...] = (),
    ) -> tuple[FinalAnswer, TurnRecord]:
        trace.timings["total"] = time.perf_counter() - trace.started
        final = FinalAnswer(status=status, text=text, sources=sources, timings=dict(trace.timings),
                            follow_up_topic=follow_up_topic, items=items)  # fmt: skip
        out = trace.out
        gate = trace.gate
        record = TurnRecord(
            ts=datetime.now().astimezone(),
            session_id=session_id,
            turn_index=len(history),
            input_mode=input_mode,
            question=question,
            retrieved=tuple(
                {"chunk_id": h.chunk.chunk_id, "score": h.score, "ranks": dict(h.ranks)}
                for h in trace.hits
            ),
            gate={
                "passed": gate.passed if gate else None,
                "score": gate.score if gate else None,
                "threshold": gate.threshold if gate else None,
            },
            llm_provider=out.provider if out else None,
            llm_status=out.status if out else None,
            final_status=status,
            answer=joined_answer(text, items),  # v4: log memuat items
            sources=tuple(c.chunk_id for c in sources),
            fact_check=trace.fact_check
            if trace.fact_check is not None
            else {"enabled": self.settings.rag.fact_check.enabled, "ran": False},
            timings=dict(trace.timings),
            kb_id=self.kb_id,
            config_hash=self.config_hash,
            app_version=self.settings.app.version,
            llm_usage=out.usage if out else None,
            citations=out.citations if out else (),
            error_code=str(trace.error_code) if trace.error_code else None,
            prompt_version=prompt_version(self._variant(out.provider if out else None)),
        )
        if self.log is not None:
            self.log.log_turn(record)
        return final, record


def make_pipeline(
    settings: Settings,
    kb_root: Path | None = None,
    log: InteractionLog | None = None,
) -> AnswerPipeline:
    """Rakit pipeline dari konfigurasi: KB aktif, retriever, gerbang, rantai LLM, checker."""
    from mica.core import startup
    from mica.kb.index import DEFAULT_KB_ROOT, load_kb
    from mica.rag.checker import make_checker
    from mica.rag.gate import make_gate
    from mica.rag.llm import make_llm
    from mica.rag.retriever import embedder_for_kb, make_retriever

    startup.mark("kb_load_start")
    kb = load_kb(settings.kb.active_id, kb_root or DEFAULT_KB_ROOT)
    startup.mark("kb_load_done")
    embedder = None
    if settings.rag.retriever != "bm25":
        # model dimuat di depan supaya timings.retrieval tidak memuat waktu muat model
        embedder = embedder_for_kb(kb)
        load = getattr(embedder, "load", None)
        if load is not None:
            if startup.active():  # Langkah 40: modul yang memang dimuat BgeM3Embedder.load
                startup.timed_import("torch")
                startup.timed_import("sentence_transformers")
            startup.mark("embedder_load_start")
            load()
            startup.mark("embedder_load_done")
    retriever = make_retriever(settings, kb, embedder_factory=lambda m, r: embedder)
    return AnswerPipeline(
        settings,
        retriever,
        make_gate(settings),
        make_llm(settings),
        make_checker(settings),
        kb_id=kb.kb_id,
        log=log if log is not None else InteractionLog(Path(settings.logging.dir)),
    )
