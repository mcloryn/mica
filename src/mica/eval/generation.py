"""M-12 generation: E-02 dev, jawaban per pertanyaan lewat AnswerPipeline (SDD 9.4, 9.5; ADR-06).

Satu run memanggil LLM sekali per pertanyaan dengan gerbang dimatikan (--gate-off) dan cek angka
menyala, lalu status untuk ambang lain dan cek angka mati dihitung offline dari hasil yang sama:
- skor < ambang -> refused_gate (aturan ScoreThresholdGate);
- cek angka mati -> status LLM bila penolakannya hanya karena cek angka (cek angka adalah
  langkah terakhir pipeline, SDD 7.3).

Selama eval rantai cadangan dimatikan: hanya model pertama llm.chain. HTTP 429 ditunggu sesuai
retry-after lalu dicoba lagi ke model yang sama (maksimal 5 kali), supaya hasil tidak tercampur
antarmodel. Laju dijaga <= 6.000 token per menit. Respons LLM disimpan di cache lokal
(data/cache/llm/, di luar git) dengan kunci hash badan request.

Skrip ini hanya mengukur. Ambang tidak dipilih di sini, dan config tidak diubah.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mica.config import LlmConfig, Settings
from mica.core.types import (
    Chunk,
    LlmAnswer,
    LlmRequest,
    LlmUnavailable,
    Turn,
    joined_answer,
)
from mica.eval.dataset import Question, load_questions
from mica.eval.environment import collect_environment
from mica.eval.retrieval import sha256_file
from mica.kb.embedder import Embedder
from mica.kb.index import KnowledgeBase
from mica.rag.checker import NumericFactChecker
from mica.rag.gate import make_gate
from mica.rag.llm import ProviderFailed, make_llm
from mica.rag.pii import scrub_pii
from mica.rag.pipeline import AnswerPipeline
from mica.rag.prompts import prompt_version
from mica.rag.retriever import embedder_for_kb, make_retriever

EXPERIMENT = "E-02"
SPLIT = "dev"
PROMPT_VARIANTS = ("paraphrase", "plain", "v3", "v4")  # RagConfig.prompt_variant (ADR-07, E-03; v3)
DEFAULT_CACHE_DIR = Path("data/cache/llm")
TPM_LIMIT = 6000
FIRST_ESTIMATE_TOKENS = 2500
MAX_429_RETRIES = 5
DEFAULT_RETRY_AFTER_S = 10.0  # bila 429 tanpa header retry-after
MAX_RETRY_DELAY_S = 60.0  # retryDelay lebih lama, atau kuota harian: run dihentikan
SWEEP_THRESHOLDS: tuple[float | None, ...] = (None, 0.45, 0.48, 0.50, 0.52, 0.55)
MAX_FALSE_REJECT = 0.10
REFUSED = ("refused_gate", "refused_llm", "refused_check")
STAGES = ("scrub", "retrieval", "gate", "llm", "check", "total")

PER_QUESTION_COLUMNS = (
    "qid",
    "type",
    "oos_level",
    "question",
    "reference_answer",
    "gate_score",
    "llm_status",
    "answer",
    "citations",
    "check_passed",
    "check_unsupported",
    "final_status_check_on",
    "final_status_check_off",
    "provider",
    "prompt_tokens",
    "completion_tokens",
    *(f"t_{s}" for s in STAGES),
    "error_code",
    "llm_latency_s",
    "from_cache",
    "follow_up_topic",  # prompt v3 (docs/PROMPT-V3.md); kosong untuk v2
    "items",  # prompt v4 (docs/PROMPT-V4.md): items digabung "; "; kosong untuk v2/v3
)
SWEEP_COLUMNS = (
    "threshold",
    "fact_check",
    "answerable_followup_n",
    "false_reject_n",
    "false_reject_rate",
    "out_of_kb_n",
    "correct_reject_n",
    "correct_reject_rate",
    "jauh_n",
    "jauh_reject_n",
    "jauh_reject_rate",
    "dekat_n",
    "dekat_reject_n",
    "dekat_reject_rate",
    "false_premise_n",
    "false_premise_fp",
    "false_premise_refused",
    "false_premise_answered",
    "answered_failed_check",
    "meets_rule",
)
ANNOTATE_COLUMNS = (
    "qid",
    "type",
    "question",
    "reference_answer",
    "answer",
    "status",
    "cited_chunks",
    "benar",
    "halusinasi",
    "catatan",
)


# --- pembatas laju, cache, dan LLM khusus eval ------------------------------------


def print_progress(message: str) -> None:
    print(message, flush=True)  # tetap terlihat saat keluaran dialihkan ke file


class CacheMiss(RuntimeError):
    """--cache-only: respons tidak ada di cache; run dihentikan sebelum memanggil API."""


class QuotaExhausted(RuntimeError):
    """429 kuota harian (quotaId ...PerDay...) atau retryDelay > MAX_RETRY_DELAY_S: run dihentikan.

    Jawaban sebelumnya sudah tersimpan di cache; run berikutnya melanjutkan dari sana.
    done/total diisi answer_questions.
    """

    def __init__(self, provider: str, quota_id: str | None, retry_delay_s: float | None):
        super().__init__(
            f"{provider}: kuota habis (quotaId {quota_id}, retryDelay {retry_delay_s} s)"
        )
        self.provider = provider
        self.quota_id = quota_id
        self.retry_delay_s = retry_delay_s
        self.done = 0
        self.total = 0


def is_hard_quota(exc: ProviderFailed) -> bool:
    """429 yang tidak layak ditunggu: kuota harian, atau retryDelay (Gemini) / header retry-after
    (Groq, mis. batas token per hari) > MAX_RETRY_DELAY_S."""
    if exc.status != 429:
        return False
    if exc.quota_id and "PerDay" in exc.quota_id:
        return True
    if exc.retry_delay_s is not None and exc.retry_delay_s > MAX_RETRY_DELAY_S:
        return True
    try:
        return exc.retry_after is not None and float(exc.retry_after) > MAX_RETRY_DELAY_S
    except ValueError:
        return False


class TokenRateLimiter:
    """Jendela geser 60 detik: tunggu sampai token terpakai + perkiraan <= batas.

    Perkiraan = total_tokens respons sebelumnya (pertama: FIRST_ESTIMATE_TOKENS).
    """

    def __init__(
        self,
        tpm: int = TPM_LIMIT,
        first_estimate: int = FIRST_ESTIMATE_TOKENS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        window_s: float = 60.0,
    ) -> None:
        self.tpm = tpm
        self.first_estimate = first_estimate
        self.clock = clock
        self.sleep = sleep
        self.window_s = window_s
        self.events: deque[tuple[float, int]] = deque()
        self.last: int | None = None
        self.waited_s = 0.0

    def used(self) -> int:
        now = self.clock()
        while self.events and now - self.events[0][0] >= self.window_s:
            self.events.popleft()
        return sum(tokens for _, tokens in self.events)

    def wait(self) -> float:
        estimate = self.last if self.last is not None else self.first_estimate
        waited = 0.0
        while self.events and self.used() + estimate > self.tpm:
            delay = max(self.events[0][0] + self.window_s - self.clock(), 0.01)
            self.sleep(delay)
            waited += delay
        self.waited_s += waited
        return waited

    def record(self, tokens: int) -> None:
        self.events.append((self.clock(), tokens))
        self.last = tokens


class LlmCache:
    """Satu file JSON per kunci; hanya berisi LlmAnswer (pertanyaan di dalamnya sudah disamarkan)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def get(self, key: str) -> LlmAnswer | None:
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return LlmAnswer(
            status=data["status"],
            answer=data["answer"],
            citations=tuple(data["citations"]),
            provider=data["provider"],
            latency_s=data["latency_s"],
            usage=data.get("usage"),
            follow_up_topic=data.get("follow_up_topic"),
            items=tuple(data.get("items", ())),
        )

    def put(self, key: str, answer: LlmAnswer) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        data = {
            "status": answer.status,
            "answer": answer.answer,
            "citations": list(answer.citations),
            "provider": answer.provider,
            "latency_s": answer.latency_s,
            "usage": answer.usage,
        }
        if answer.follow_up_topic is not None:  # v3; berkas cache v2 tetap berformat sama
            data["follow_up_topic"] = answer.follow_up_topic
        if answer.items:  # v4; berkas cache v2/v3 tetap berformat sama
            data["items"] = list(answer.items)
        tmp = self.root / f"{key}.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.root / f"{key}.json")


def cache_key(provider: Any, request: LlmRequest) -> str:
    """Hash badan request: model, system dan user prompt, skema, temperature, reasoning_effort."""
    payload = {"provider": provider.name, "body": provider.request_body(request)}
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class LlmStats:
    api_calls: int = 0  # panggilan ke penyedia, termasuk coba ulang 429
    from_cache: int = 0
    retries_429: int = 0
    wait_429_s: float = 0.0
    prompt_tokens: int = 0  # hanya panggilan API di run ini
    completion_tokens: int = 0
    total_tokens: int = 0


class EvalLlm:
    """LLMProvider untuk eval: satu model, cache, pembatas laju, tunggu-ulang pada 429."""

    def __init__(
        self,
        provider: Any,
        limiter: TokenRateLimiter,
        cache: LlmCache | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = MAX_429_RETRIES,
        read_cache: bool = True,
        cache_only: bool = False,
    ) -> None:
        self.provider = provider
        self.read_cache = read_cache
        self.cache_only = cache_only
        self.name = provider.name
        self.limiter = limiter
        self.cache = cache
        self.sleep = sleep
        self.max_retries = max_retries
        self.stats = LlmStats()
        self.last: LlmAnswer | None = None
        self.last_from_cache = False

    def generate(self, request: LlmRequest, timeout_s: float) -> LlmAnswer:
        request = request.for_provider(self.provider.name)  # llm.prompt_variants
        key = cache_key(self.provider, request)
        if self.cache is not None and self.read_cache:
            cached = self.cache.get(key)
            if cached is not None:
                self.stats.from_cache += 1
                self.last, self.last_from_cache = cached, True
                return cached
        if self.cache_only:
            raise CacheMiss(f"{self.name}: respons tidak ada di cache (kunci {key[:12]})")
        self.limiter.wait()
        for attempt in range(self.max_retries + 1):
            self.stats.api_calls += 1
            try:
                answer = self.provider.generate(request, timeout_s)
            except ProviderFailed as exc:
                if is_hard_quota(exc):
                    raise QuotaExhausted(self.name, exc.quota_id, exc.retry_delay_s) from None
                if exc.status == 429 and attempt < self.max_retries:
                    delay = _retry_after_s(exc.retry_after, exc.retry_delay_s)
                    self.stats.retries_429 += 1
                    self.stats.wait_429_s += delay
                    self.sleep(delay)
                    continue
                raise LlmUnavailable(f"{self.name}: {exc.reason}") from None
            break
        usage = answer.usage or {}
        self.limiter.record(usage.get("total_tokens", self.limiter.first_estimate))
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            setattr(self.stats, name, getattr(self.stats, name) + usage.get(name, 0))
        if self.cache is not None:
            self.cache.put(key, answer)
        self.last, self.last_from_cache = answer, False
        return answer


def _retry_after_s(value: str | None, retry_delay_s: float | None = None) -> float:
    """Header retry-after, lalu retryDelay di badan respons (Gemini), lalu bawaan 10 detik."""
    fallback = retry_delay_s if retry_delay_s is not None else DEFAULT_RETRY_AFTER_S
    try:
        return max(float(value), 0.0) if value is not None else fallback
    except ValueError:
        return fallback


# --- per pertanyaan ---------------------------------------------------------------


@dataclass
class GenerationRow:
    qid: str
    type: str
    oos_level: str | None
    question: str  # sudah melewati scrub_pii
    reference_answer: str
    gate_score: float | None
    llm_status: str | None
    answer: str  # jawaban mentah LLM (sebelum cek angka); kosong bila LLM tidak dipanggil
    citations: tuple[str, ...]
    check_passed: bool | None  # None bila cek angka tidak dijalankan
    check_unsupported: tuple[str, ...]
    status_on: str
    status_off: str
    final_text: str  # yang ditampilkan dengan cek angka menyala (untuk riwayat followup)
    provider: str | None
    usage: dict[str, int] | None
    timings: dict[str, float]
    error_code: str | None
    llm_latency_s: float | None
    from_cache: bool
    follow_up_topic: str | None = None  # dari keluaran LLM (v3), sebelum cek angka
    items: tuple[str, ...] = ()  # dari keluaran LLM (v4), sebelum cek angka
    retrieved_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def group(self) -> str:
        return self.oos_level if self.type == "out_of_kb" and self.oos_level else self.type


def effective_settings(settings: Settings, gate_off: bool, model: str | None = None,
                       prompt_variant: str | None = None,
                       timeout_s: float | None = None) -> Settings:  # fmt: skip
    """Konfigurasi run ini: cek angka selalu menyala (status 'off' dihitung offline).

    model ("penyedia:id_model") mengganti llm.chain menjadi satu model itu saja.
    prompt_variant (--prompt-variant) menimpa rag.prompt_variant.
    timeout_s (--timeout-s) menimpa llm.timeout_s (E-04 Gemini, docs/E-04.md).
    """
    rag = settings.rag
    gate = rag.gate.model_copy(update={"threshold": None}) if gate_off else rag.gate
    fact_check = rag.fact_check.model_copy(update={"enabled": True})
    rag_update: dict[str, Any] = {"gate": gate, "fact_check": fact_check}
    if prompt_variant is not None:
        if prompt_variant not in PROMPT_VARIANTS:
            raise ValueError(f"--prompt-variant harus salah satu dari {PROMPT_VARIANTS}")
        rag_update["prompt_variant"] = prompt_variant
    rag = rag.model_copy(update=rag_update)
    update: dict[str, Any] = {"rag": rag}
    if model is not None or timeout_s is not None or prompt_variant is not None:
        data = settings.llm.model_dump()
        if prompt_variant is not None:  # --prompt-variant menang atas llm.prompt_variants
            data["prompt_variants"] = {}
        if model is not None:
            data["chain"] = [model]
            # llm.prompt_variants hanya untuk model ini (entri lain sudah tidak ada di rantai)
            data["prompt_variants"] = {
                k: v for k, v in data["prompt_variants"].items() if k == model
            }
            if model.partition(":")[0] == "gemini" and settings.app.mode != "dev":
                raise ValueError("--model: penyedia gemini hanya boleh saat app.mode: dev")
        if timeout_s is not None:
            data["timeout_s"] = timeout_s
        # format 'penyedia:id_model' dan timeout > 0 tetap divalidasi
        update["llm"] = LlmConfig.model_validate(data)
    return settings.model_copy(update=update)


def model_slug(model: str) -> str:
    """'groq:openai/gpt-oss-20b' -> 'gpt-oss-20b' (untuk nama folder run)."""
    return model.partition(":")[2].rsplit("/", 1)[-1].replace(":", "-")


def dev_questions(questions: list[Question], split: str = SPLIT) -> list[Question]:
    return sorted((q for q in questions if q.get("split") == split), key=lambda q: q["qid"])


def answer_questions(
    pipeline: AnswerPipeline,
    llm: EvalLlm,
    questions: list[Question],
    progress: Callable[[str], None] | None = print_progress,
) -> list[GenerationRow]:
    """Urut qid; prev_qid dijawab dulu bila perlu, lalu riwayat = pertanyaan + jawaban sistemnya."""
    by_qid = {q["qid"]: q for q in questions}
    done: dict[str, GenerationRow] = {}
    total = len(questions)

    def run(q: Question) -> GenerationRow:
        if q["qid"] in done:
            return done[q["qid"]]
        history: list[Turn] = []
        prev_id = q.get("prev_qid")
        if q.get("type") == "followup" and prev_id:
            if prev_id not in by_qid:
                raise ValueError(f"{q['qid']}: prev_qid {prev_id} tidak ada di split ini")
            prev = run(by_qid[prev_id])
            history = [
                Turn(question=scrub_pii(by_qid[prev_id]["question"]), answer=prev.final_text)
            ]
        llm.last, llm.last_from_cache = None, False
        final, record = pipeline.run(q["question"], history, session_id=f"eval-{q['qid']}")
        out = llm.last
        fact = record.fact_check
        check_passed = fact.get("passed") if "passed" in fact else None
        # cek angka adalah langkah terakhir: tanpa cek angka, status = status LLM
        status_off = record.llm_status if check_passed is False else final.status
        row = GenerationRow(
            qid=q["qid"],
            type=q["type"],
            oos_level=q.get("oos_level"),
            question=str(record.question),
            reference_answer=q.get("reference_answer") or "",
            gate_score=record.gate.get("score"),
            llm_status=record.llm_status,
            answer=out.answer if out else "",
            citations=record.citations,
            check_passed=check_passed,
            check_unsupported=tuple(fact.get("unsupported", ())),
            status_on=final.status,
            status_off=status_off or final.status,
            final_text=joined_answer(final.text, final.items),
            provider=record.llm_provider,
            usage=record.llm_usage,
            timings=dict(final.timings),
            error_code=record.error_code,
            llm_latency_s=out.latency_s if out else None,
            from_cache=llm.last_from_cache,
            follow_up_topic=out.follow_up_topic if out else None,
            items=out.items if out else (),
            retrieved_ids=tuple(r["chunk_id"] for r in record.retrieved),
        )
        done[q["qid"]] = row
        if progress is not None:
            tokens = (row.usage or {}).get("total_tokens", "-")
            source = "cache" if row.from_cache else "API"
            progress(
                f"[{len(done)}/{total}] {row.qid} {row.type} -> {row.status_on} "
                f"(cek off: {row.status_off}) | {tokens} token ({source})"
            )
        return row

    try:
        for q in questions:
            run(q)
    except QuotaExhausted as exc:
        exc.done, exc.total = len(done), total
        raise
    return [done[q["qid"]] for q in questions]


# --- sweep offline ----------------------------------------------------------------


def status_at(row: GenerationRow, threshold: float | None, fact_check: str) -> str:
    if threshold is not None and (row.gate_score is None or row.gate_score < threshold):
        return "refused_gate"
    return row.status_on if fact_check == "on" else row.status_off


def _rate(k: int, n: int) -> str:
    return f"{k / n:.4f}" if n else ""


def sweep_generation(rows: list[GenerationRow]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for threshold in SWEEP_THRESHOLDS:
        for fact_check in ("on", "off"):
            statuses = {r.qid: status_at(r, threshold, fact_check) for r in rows}
            wanted = [r for r in rows if r.type in ("answerable", "followup")]
            oos = [r for r in rows if r.type == "out_of_kb"]
            far = [r for r in oos if r.oos_level == "jauh"]
            near = [r for r in oos if r.oos_level == "dekat"]
            fp = [r for r in rows if r.type == "false_premise"]
            fr = sum(statuses[r.qid] != "answered" for r in wanted)
            cr = sum(statuses[r.qid] in REFUSED for r in oos)
            far_k = sum(statuses[r.qid] in REFUSED for r in far)
            near_k = sum(statuses[r.qid] in REFUSED for r in near)
            failed_check = ""
            if fact_check == "on":
                failed_check = str(
                    sum(
                        statuses[r.qid] == "refused_check"
                        and r.llm_status == "answered"
                        and r.check_passed is False
                        for r in rows
                    )
                )
            out.append(
                {
                    "threshold": "null" if threshold is None else f"{threshold:.2f}",
                    "fact_check": fact_check,
                    "answerable_followup_n": len(wanted),
                    "false_reject_n": fr,
                    "false_reject_rate": _rate(fr, len(wanted)),
                    "out_of_kb_n": len(oos),
                    "correct_reject_n": cr,
                    "correct_reject_rate": _rate(cr, len(oos)),
                    "jauh_n": len(far),
                    "jauh_reject_n": far_k,
                    "jauh_reject_rate": _rate(far_k, len(far)),
                    "dekat_n": len(near),
                    "dekat_reject_n": near_k,
                    "dekat_reject_rate": _rate(near_k, len(near)),
                    "false_premise_n": len(fp),
                    "false_premise_fp": sum(statuses[r.qid] == "false_premise" for r in fp),
                    "false_premise_refused": sum(statuses[r.qid] in REFUSED for r in fp),
                    "false_premise_answered": sum(statuses[r.qid] == "answered" for r in fp),
                    "answered_failed_check": failed_check,
                    "meets_rule": "",
                }
            )
    _mark_rule(out)
    return out


def _mark_rule(rows: list[dict[str, Any]]) -> None:
    """Salah tolak <= 10%, lalu penolakan benar tertinggi; seri -> salah tolak terkecil.

    Bila masih seri, semua baris yang seri ditandai.
    """

    def key(r: dict[str, Any]) -> tuple[float, float]:
        return (-float(r["correct_reject_rate"] or 0), float(r["false_reject_rate"] or 0))

    eligible = [
        r
        for r in rows
        if r["false_reject_rate"] != "" and float(r["false_reject_rate"]) <= MAX_FALSE_REJECT
    ]
    if not eligible:
        return
    best = min(key(r) for r in eligible)
    for r in eligible:
        if key(r) == best:
            r["meets_rule"] = "ya"


# --- penulisan hasil ----------------------------------------------------------------


def _fmt(value: float | None, digits: int = 6) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def _per_question_row(r: GenerationRow) -> dict[str, Any]:
    usage = r.usage or {}
    row = {
        "qid": r.qid,
        "type": r.type,
        "oos_level": r.oos_level or "",
        "question": r.question,
        "reference_answer": r.reference_answer,
        "gate_score": _fmt(r.gate_score),
        "llm_status": r.llm_status or "",
        "answer": r.answer,
        "citations": "; ".join(r.citations),
        "check_passed": "" if r.check_passed is None else int(r.check_passed),
        "check_unsupported": "; ".join(r.check_unsupported),
        "final_status_check_on": r.status_on,
        "final_status_check_off": r.status_off,
        "provider": r.provider or "",
        "prompt_tokens": usage.get("prompt_tokens", ""),
        "completion_tokens": usage.get("completion_tokens", ""),
        "error_code": r.error_code or "",
        "llm_latency_s": _fmt(r.llm_latency_s, 3),
        "from_cache": int(r.from_cache),
        "follow_up_topic": r.follow_up_topic or "",
        "items": "; ".join(r.items),
    }
    for stage in STAGES:
        row[f"t_{stage}"] = _fmt(r.timings.get(stage), 4)
    return row


def _cited_text(r: GenerationRow, chunks: dict[str, Chunk]) -> str:
    parts = []
    for cid in r.citations:
        chunk = chunks.get(cid)
        if chunk is None or cid not in r.retrieved_ids:
            parts.append(f"[{cid}] (tidak ada di hasil retrieval)")
        else:
            parts.append(f"[{cid}] {chunk.doc_title}\n{chunk.text}")
    return "\n\n".join(parts)


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def annotation_rows(rows: list[GenerationRow], kb: KnowledgeBase) -> list[dict[str, Any]]:
    """Jawaban berstatus answered atau false_premise dengan cek angka mati, belum dinilai."""
    chunks = {c.chunk_id: c for c in kb.chunks}
    return [
        {
            "qid": r.qid,
            "type": r.type,
            "question": r.question,
            "reference_answer": r.reference_answer,
            "answer": joined_answer(r.answer, r.items),  # v4: items digabung "; "
            "status": r.status_off,
            "cited_chunks": _cited_text(r, chunks),
            "benar": "",
            "halusinasi": "",
            "catatan": "",
        }
        for r in rows
        if r.status_off in ("answered", "false_premise")
    ]


def run_generation(
    settings: Settings,
    kb: KnowledgeBase,
    dataset: Path,
    out_root: Path,
    *,
    gate_off: bool = True,
    use_cache: bool = True,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    provider: Any = None,
    embedder: Embedder | None = None,
    limiter: TokenRateLimiter | None = None,
    sleep: Callable[[float], None] = time.sleep,
    started_at: datetime | None = None,
    environment: dict[str, Any] | None = None,
    progress: Callable[[str], None] | None = print_progress,
    cache_only: bool = False,
    model: str | None = None,
    experiment: str = EXPERIMENT,
    split: str = SPLIT,
    split_info: dict[str, Any] | None = None,
    prompt_variant: str | None = None,
    timeout_s: float | None = None,
) -> tuple[Path, list[GenerationRow], list[dict[str, Any]]]:
    if not re.fullmatch(r"E-\d{2}", experiment):
        raise ValueError(f"--experiment {experiment!r} harus berformat E-NN, misalnya E-04")
    started_at = started_at or datetime.now().astimezone()
    clock_start = time.perf_counter()
    environment = environment if environment is not None else collect_environment()
    eff = effective_settings(settings, gate_off, model, prompt_variant, timeout_s)
    questions = dev_questions(load_questions(dataset), split)

    if provider is None:
        providers = make_llm(eff).providers
        if model is not None and [p.name for p in providers] != [model]:
            # pengaman: --model tidak boleh memanggil model lain
            raise ValueError(f"--model {model}: chain efektif {[p.name for p in providers]}")
        provider = providers[0]  # rantai cadangan dimatikan selama eval
    if embedder is None and eff.rag.retriever != "bm25":
        embedder = embedder_for_kb(kb)
        load = getattr(embedder, "load", None)
        if load is not None:
            load()
    retriever = make_retriever(eff, kb, embedder_factory=lambda m, r: embedder)
    llm = EvalLlm(
        provider,
        limiter or TokenRateLimiter(sleep=sleep),
        cache=LlmCache(cache_dir),
        sleep=sleep,
        # --no-cache: cache tidak dibaca (semua dipanggil ulang), tetapi tetap ditulis
        read_cache=use_cache,
        cache_only=cache_only,
    )
    pipeline = AnswerPipeline(
        eff, retriever, make_gate(eff), llm, NumericFactChecker(), kb_id=kb.kb_id, log=None
    )
    rows = answer_questions(pipeline, llm, questions, progress)
    sweep_rows = sweep_generation(rows)

    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    suffix = (f"-{model_slug(model)}" if model is not None else "") + (
        "-gateoff" if gate_off else ""
    )
    run_dir = Path(out_root) / f"{stamp}-{experiment}-{split}-{eff.rag.retriever}{suffix}"
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_csv(
        run_dir / "per_question.csv", PER_QUESTION_COLUMNS, [_per_question_row(r) for r in rows]
    )
    _write_csv(run_dir / "e02_sweep.csv", SWEEP_COLUMNS, sweep_rows)
    _write_csv(run_dir / "annotate_generation.csv", ANNOTATE_COLUMNS, annotation_rows(rows, kb))

    info = kb.manifest["embedder"]
    stats = llm.stats
    all_usage = [r.usage for r in rows if r.usage]
    run = {
        "experiment": experiment,
        "component": "generation",
        "split": split,
        "lock": (split_info or {}).get("lock"),
        "retriever": eff.rag.retriever,
        "top_k": eff.rag.top_k,
        "gate_off": gate_off,
        "gate_threshold_config": settings.rag.gate.threshold,
        "gate_threshold_effective": eff.rag.gate.threshold,
        "fact_check": "dijalankan; status cek angka mati dihitung offline",
        "followup_mode": eff.rag.followup_mode,
        "history_turns": eff.rag.history_turns,
        "prompt_variant": eff.rag.prompt_variant,
        "prompt_variant_config": settings.rag.prompt_variant,
        "prompt_variant_source": "--prompt-variant" if prompt_variant is not None else "config",
        "prompt_version": prompt_version(eff.rag.prompt_variant),
        "config_hash": eff.config_hash(),
        "config_hash_file": settings.config_hash(),
        "kb_id": kb.kb_id,
        "dataset": {"path": Path(dataset).as_posix(), "sha256": sha256_file(dataset)},
        "embedder": {"model": info["model"], "revision": info["revision"]},
        "llm": {
            "provider": provider.name,
            "model": getattr(provider, "model", None),
            "reasoning_effort": eff.llm.reasoning_effort,
            "temperature": eff.llm.temperature,
            "timeout_s": eff.llm.timeout_s,
            "timeout_s_config": settings.llm.timeout_s,
            "timeout_source": "--timeout-s" if timeout_s is not None else "config",
            "fallback_chain": "dimatikan; hanya model pertama llm.chain",
            "chain_effective": list(eff.llm.chain),
            "chain_config": list(settings.llm.chain),
            "model_override": model,
        },
        "llm_calls": {
            "questions": len(rows),
            "api_calls": stats.api_calls,
            "from_cache": stats.from_cache,
            "retries_429": stats.retries_429,
            "wait_429_s": round(stats.wait_429_s, 1),
            "rate_limit_wait_s": round(llm.limiter.waited_s, 1),
            "cache_read": use_cache,
            "cache_only": cache_only,
        },
        "tokens_api": {
            "prompt_tokens": stats.prompt_tokens,
            "completion_tokens": stats.completion_tokens,
            "total_tokens": stats.total_tokens,
        },
        "tokens_all_answers": {
            k: sum(u.get(k, 0) for u in all_usage)
            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        "rate_limit_tpm": llm.limiter.tpm,
        "sweep": {
            "thresholds": [t for t in SWEEP_THRESHOLDS],
            "rule": "false_reject_rate <= 0.10, lalu correct_reject_rate tertinggi; "
            "seri -> false_reject_rate terkecil",
        },
        "n_questions": {
            g: sum(r.group == g for r in rows)
            for g in ("answerable", "followup", "jauh", "dekat", "false_premise")
        },
        "environment": environment,
        "started_at": started_at.isoformat(),
        "duration_s": round(time.perf_counter() - clock_start, 1),
    }
    (run_dir / "run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return run_dir, rows, sweep_rows
