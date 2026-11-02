"""Uji RAG Tahap 1 (Langkah 67): baseline halusinasi pada 129 soal AI (docs/PRA-REGISTRASI-TAHAP1.md).

Sistem yang diuji dibekukan (pra-reg bagian 3). Sebelum satu soal pun dijawab, run memeriksa
SHA-256 file soal dan setiap nilai sistem beku (FROZEN); bila ada yang tidak cocok, run berhenti
tanpa "memperbaiki" apa pun.

Alurnya sama dengan UI web: AnswerPipeline (scrub_pii -> retrieval -> gerbang 1 skor -> LLM ->
gerbang 2 penolakan LLM -> gerbang 3 cek sitasi/angka -> teks akhir), satu putaran per soal,
tanpa riwayat percakapan. Seperti E-02, rantai cadangan dimatikan (hanya model pertama
llm.chain) dan EvalLlm dipakai ulang (pembatas laju, tunggu-ulang 429, berhenti saat kuota
habis).

Satu jawaban per soal: answers.jsonl ditambah satu baris per soal; id yang sudah ada dilewati
(resume). Soal hanya diulang bila API error/timeout dan belum ada jawaban; setiap percobaan
dicatat di attempts.jsonl. Set uji tidak punya jawaban/chunk emas, jadi tidak ada metrik
retrieval. Lembar penilaian baru dibuat setelah semua soal terjawab.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mica.config import Settings
from mica.core import texts
from mica.core.types import LlmUnavailable, source_title, visible_items
from mica.eval.environment import collect_environment
from mica.eval.generation import (
    EvalLlm,
    LlmCache,
    QuotaExhausted,
    TokenRateLimiter,
    print_progress,
)
from mica.eval.xlsx import Sheet, write_xlsx
from mica.kb.embedder import Embedder
from mica.kb.index import KnowledgeBase
from mica.rag.checker import NumericFactChecker
from mica.rag.gate import make_gate
from mica.rag.llm import make_llm
from mica.rag.pipeline import AnswerPipeline
from mica.rag.prompts import prompt_version
from mica.rag.retriever import embedder_for_kb, make_retriever
from mica.ui.viewmodel import Source, source_line

PREREG = Path("docs/PRA-REGISTRASI-TAHAP1.md")
QUESTIONS_SHA256 = "da7797ffbb733967ae4a2695b0a8b4446651708f8ed57415f43a3ba53456876e"
N_QUESTIONS = 129
COLUMNS = ("id", "no_asal", "penanya", "topik", "pertanyaan")
SHEET_SEED = 20261030
MAX_ATTEMPTS = 3  # percobaan per soal bila API error/timeout (bukan 429; itu ditangani EvalLlm)
RETRY_WAIT_S = 15.0
QUOTA_MESSAGE = "Kuota habis, lanjutkan besok dengan perintah yang sama"

ANSWERS_FILE = "answers.jsonl"
ATTEMPTS_FILE = "attempts.jsonl"
MANIFEST_FILE = "manifest.json"
CACHE_DIR = "llm_cache"
SHEETS = ("lembar-penilai-hasa.xlsx", "lembar-penilai-rekan.xlsx")

# status pipeline -> (label, gerbang yang menolak)
STATUS_LABELS: dict[str, tuple[str, int | None]] = {
    "answered": ("dijawab", None),
    "false_premise": ("false_premise", None),
    "refused_gate": ("ditolak gerbang 1 (skor dense@1 < ambang)", 1),
    "refused_llm": ("not_found: ditolak gerbang 2 (LLM)", 2),
    "refused_check": ("ditolak gerbang 3 (cek sitasi/angka)", 3),
}

# pra-reg bagian 4, disalin apa adanya (tes memastikan teksnya ada di docs/PRA-REGISTRASI-TAHAP1.md)
LABELS: tuple[tuple[str, str], ...] = (
    ("benar", "semua klaim sesuai dokumen."),
    (
        "tidak lengkap",
        (
            "yang disebut benar, tetapi ada bagian pertanyaan yang tidak dijawab padahal ada "
            "di dokumen."
        ),
    ),
    (
        "halusinasi",
        (
            "ada minimal satu klaim yang tidak didukung atau bertentangan dengan dokumen "
            "(definisi mengikuti RAGTruth, Niu dkk., ACL 2024). Untuk soal yang memuat dua "
            "pertanyaan, satu bagian yang dikarang sudah cukup untuk label ini."
        ),
    ),
    ("tolak tepat", "MICA menolak dan informasinya memang tidak ada di dokumen."),
    ("tolak keliru", "MICA menolak padahal jawabannya ada di dokumen."),
)
OFFICIAL_DOCS = (
    "Penilai memeriksa jawaban terhadap dokumen resmi (Pedoman PMB 2027, Peraturan Akademik "
    "2025, Panduan Kemahasiswaan 2021, brosur 2025, panduan pembayaran 2026/2027)."
)
NILAI_COLUMNS = (
    "id", "pertanyaan", "jawaban MICA", "sitasi", "label", "klaim yang dikarang", "catatan",
)  # fmt: skip
POTONGAN_COLUMNS = ("id", "urutan", "sumber", "teks potongan")


class Tahap1Error(ValueError):
    """File soal atau sistem tidak cocok dengan pra-registrasi: run berhenti tanpa menjawab."""


@dataclass(frozen=True)
class FrozenSystem:
    """Sistem yang diuji, pra-reg bagian 3."""

    kb_id: str = "official-2026-10-24-v5"
    n_chunks: int | None = 202
    retriever: str = "hybrid"
    rrf_k: int = 60
    top_k: int = 5
    reranker: bool = False
    prompt_variant: str = "v5"
    model: str = "groq:openai/gpt-oss-120b"
    gate_threshold: float = 0.50
    fact_check: bool = True


FROZEN = FrozenSystem()


# --- soal dan pemeriksaan sistem ----------------------------------------------------


def sha256_bytes(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_test_questions(
    path: Path, expected_sha: str = QUESTIONS_SHA256, expected_n: int = N_QUESTIONS
) -> list[dict[str, str]]:
    """Baca CSV soal (pemisah ';') setelah SHA-256 byte file cocok dengan pra-reg."""
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha:
        raise Tahap1Error(
            f"SHA-256 {Path(path).as_posix()} = {digest}, pra-reg {expected_sha}. "
            "File soal tidak diubah; run dihentikan."
        )
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), delimiter=";")
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise Tahap1Error(f"kolom CSV {reader.fieldnames}, seharusnya {list(COLUMNS)}")
    rows = list(reader)
    ids = [r["id"] for r in rows]
    if len(rows) != expected_n or len(set(ids)) != len(ids):
        raise Tahap1Error(f"{len(rows)} baris ({len(set(ids))} id unik), pra-reg {expected_n}")
    if any(not (r["pertanyaan"] or "").strip() for r in rows):
        raise Tahap1Error("ada baris dengan pertanyaan kosong")
    return rows


def frozen_mismatches(settings: Settings, kb: KnowledgeBase, frozen: FrozenSystem) -> list[str]:
    rag = settings.rag
    model = settings.llm.chain[0]
    variant = settings.llm.prompt_variant_for(model, rag.prompt_variant)
    actual: dict[str, Any] = {
        "kb_id": kb.kb_id,
        "n_chunks": len(kb.chunks) if frozen.n_chunks is not None else None,
        "retriever": rag.retriever,
        "rrf_k": rag.rrf_k,
        "top_k": rag.top_k,
        "reranker": rag.reranker.enabled,
        "prompt_variant": variant,
        "model": model,
        "gate_threshold": rag.gate.threshold,
        "fact_check": rag.fact_check.enabled,
    }
    return [
        f"{key}: sistem {actual[key]!r}, pra-reg {getattr(frozen, key)!r}"
        for key in actual
        if actual[key] != getattr(frozen, key)
    ]


def check_frozen(settings: Settings, kb: KnowledgeBase, frozen: FrozenSystem = FROZEN) -> None:
    problems = frozen_mismatches(settings, kb, frozen)
    if kb.manifest.get("source_type") != "official":
        problems.append(f"source_type KB {kb.manifest.get('source_type')!r}, pra-reg 'official'")
    if problems:
        raise Tahap1Error(
            "sistem tidak cocok dengan pra-registrasi (bagian 3), run dihentikan tanpa perubahan: "
            + "; ".join(problems)
        )


# --- file run -----------------------------------------------------------------------


def read_answers(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def system_identity(settings: Settings, kb: KnowledgeBase, provider: Any) -> dict[str, Any]:
    """Nilai yang harus sama di setiap lanjutan run (manifest)."""
    model = settings.llm.chain[0]
    variant = settings.llm.prompt_variant_for(model, settings.rag.prompt_variant)
    return {
        "kb_id": kb.kb_id,
        "prompt_version": prompt_version(variant),
        "model": provider.name,
        "config_hash": settings.config_hash(),
    }


# --- per soal -----------------------------------------------------------------------


class _RecordingLlm:
    """EvalLlm + alasan galat terakhir (pipeline menelan LlmUnavailable, attempts.jsonl butuh)."""

    def __init__(self, inner: EvalLlm) -> None:
        self.inner = inner
        self.name = inner.name
        self.last_error: str | None = None

    def generate(self, request: Any, timeout_s: float) -> Any:
        try:
            return self.inner.generate(request, timeout_s)
        except LlmUnavailable as exc:
            self.last_error = str(exc)
            raise


def shown_text(final: Any) -> str:
    """Teks jawaban seperti di gelembung UI web: jawaban, butir v4 yang tampil, tawaran topik."""
    lines = [final.text]
    lines += [f"- {item}" for item in visible_items(final.text, final.items)]
    if final.follow_up_topic:
        lines.append(texts.follow_up_offer(final.follow_up_topic))
    return "\n".join(lines)


def answer_row(
    q: dict[str, str],
    final: Any,
    record: Any,
    kb: KnowledgeBase,
    identity: dict[str, Any],
    *,
    asked_at: str,
    wall_s: float,
    api_attempts: int,
    question_attempts: int,
    from_cache: bool,
) -> dict[str, Any]:
    chunks = {c.chunk_id: c for c in kb.chunks}
    label, gate = STATUS_LABELS.get(final.status, (final.status, None))
    top = []
    for rank, hit in enumerate(record.retrieved, start=1):
        c = chunks[hit["chunk_id"]]
        top.append({
            "rank": rank,
            "chunk_id": c.chunk_id,
            "title": c.doc_title,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "section": c.section,
            "source": source_title(c),
            "text": c.text,
        })  # fmt: skip
    return {
        "id": q["id"],
        "no_asal": q["no_asal"],
        "penanya": q["penanya"],
        "topik": q["topik"],
        "question": str(record.question),  # sudah melewati scrub_pii
        "final_text": shown_text(final),
        "sources_shown": [
            source_line(Source(source_title(c), c.valid_from)) for c in final.sources
        ],
        "status": final.status,
        "status_label": label,
        "refused_by_gate": gate,
        "llm_status": record.llm_status,
        "error_code": record.error_code,
        "citations": list(record.citations),
        "fact_check": record.fact_check,
        "top5": top,
        "dense_at_1": record.gate.get("score"),
        "gate_threshold": record.gate.get("threshold"),
        **identity,
        "asked_at": asked_at,
        "latency_s": round(wall_s, 3),
        "timings": {k: round(v, 4) for k, v in final.timings.items()},
        "usage": record.llm_usage,
        "api_attempts": api_attempts,
        "question_attempts": question_attempts,
        "from_cache": from_cache,
    }


@dataclass
class Tahap1Result:
    out_dir: Path
    answered_now: list[dict[str, Any]]
    n_done: int
    n_total: int
    skipped: list[str]  # gagal API/timeout setelah MAX_ATTEMPTS; dicoba lagi pada run berikutnya
    sheets: list[Path]


def run_tahap1(
    settings: Settings,
    kb: KnowledgeBase,
    questions_path: Path,
    out_dir: Path,
    *,
    limit: int | None = None,
    provider: Any = None,
    embedder: Embedder | None = None,
    limiter: TokenRateLimiter | None = None,
    sleep: Callable[[float], None] = time.sleep,
    frozen: FrozenSystem = FROZEN,
    expected_sha: str = QUESTIONS_SHA256,
    expected_n: int = N_QUESTIONS,
    environment: dict[str, Any] | None = None,
    progress: Callable[[str], None] | None = print_progress,
    max_attempts: int = MAX_ATTEMPTS,
    retry_wait_s: float = RETRY_WAIT_S,
) -> Tahap1Result:
    if limit is not None and limit < 1:
        raise ValueError("--limit harus >= 1")
    questions = load_test_questions(questions_path, expected_sha, expected_n)
    check_frozen(settings, kb, frozen)
    if provider is None:
        provider = make_llm(settings).providers[0]  # rantai cadangan dimatikan, seperti E-02
    if provider.name != frozen.model:
        raise Tahap1Error(f"penyedia {provider.name}, pra-reg {frozen.model}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    answers_path = out_dir / ANSWERS_FILE
    attempts_path = out_dir / ATTEMPTS_FILE
    manifest_path = out_dir / MANIFEST_FILE
    identity = system_identity(settings, kb, provider)
    csv_sha = sha256_bytes(questions_path)

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        old = {k: manifest.get(k) for k in (*identity, "questions_sha256")}
        new = {**identity, "questions_sha256": csv_sha}
        if old != new:
            diff = [f"{k}: {old[k]!r} -> {new[k]!r}" for k in new if old[k] != new[k]]
            raise Tahap1Error("run lanjutan memakai sistem lain dari run awal: " + "; ".join(diff))
    else:
        env = environment if environment is not None else collect_environment()
        manifest = {
            "experiment": "Uji RAG Tahap 1",
            "prereg": PREREG.as_posix(),
            "prereg_sha256": sha256_bytes(PREREG) if PREREG.exists() else None,
            "questions": Path(questions_path).as_posix(),
            "questions_sha256": csv_sha,
            **identity,
            "config_hash_note": "Settings.config_hash() config yang dimuat; tanpa override",
            "n_chunks": len(kb.chunks),
            "retriever": settings.rag.retriever,
            "rrf_k": settings.rag.rrf_k,
            "top_k": settings.rag.top_k,
            "gate_threshold": settings.rag.gate.threshold,
            "fact_check": settings.rag.fact_check.enabled,
            "llm": {
                "temperature": settings.llm.temperature,
                "reasoning_effort": settings.llm.reasoning_effort,
                "timeout_s": settings.llm.timeout_s,
                "fallback_chain": "dimatikan; hanya model pertama llm.chain",
            },
            "history": "tanpa riwayat; satu putaran per soal",
            "environment": env,
            "started_at": _now(),
            "finished_at": None,
            "runs": [],
        }

    done = {r["id"] for r in read_answers(answers_path)}
    unknown = done - {q["id"] for q in questions}
    if unknown:
        raise Tahap1Error(f"answers.jsonl memuat id yang tidak ada di file soal: {sorted(unknown)}")
    pending = [q for q in questions if q["id"] not in done]
    if limit is not None:
        pending = pending[:limit]
    run_log: dict[str, Any] = {"started_at": _now(), "limit": limit, "answered": 0}
    manifest["runs"].append(run_log)

    def save_manifest() -> None:
        manifest["n_total"] = len(questions)
        manifest["n_done"] = len(done)
        manifest["updated_at"] = _now()
        if len(done) == len(questions) and not manifest.get("finished_at"):
            manifest["finished_at"] = _now()
        _write_manifest(manifest_path, manifest)

    save_manifest()
    answered_now: list[dict[str, Any]] = []
    skipped: list[str] = []

    if pending:
        if embedder is None and settings.rag.retriever != "bm25":
            embedder = embedder_for_kb(kb)
            load = getattr(embedder, "load", None)
            if load is not None:
                load()
        retriever = make_retriever(settings, kb, embedder_factory=lambda m, r: embedder)
        eval_llm = EvalLlm(
            provider,
            limiter or TokenRateLimiter(sleep=sleep),
            cache=LlmCache(out_dir / CACHE_DIR),  # jawaban API tidak hilang bila run terputus
            sleep=sleep,
        )
        llm = _RecordingLlm(eval_llm)
        pipeline = AnswerPipeline(
            settings, retriever, make_gate(settings), llm, NumericFactChecker(),
            kb_id=kb.kb_id, log=None,
        )  # fmt: skip
        try:
            for q in pending:
                row = _answer_one(
                    q, pipeline, eval_llm, llm, kb, identity, attempts_path, sleep,
                    max_attempts, retry_wait_s, progress,
                )  # fmt: skip
                if row is None:
                    skipped.append(q["id"])
                    continue
                _append_jsonl(answers_path, row)
                done.add(q["id"])
                answered_now.append(row)
                run_log["answered"] += 1
                save_manifest()
                if progress is not None:
                    tokens = (row["usage"] or {}).get("total_tokens", "-")
                    progress(
                        f"[{len(done)}/{len(questions)}] {row['id']} -> {row['status_label']} "
                        f"| dense@1 {row['dense_at_1']} | {tokens} token"
                    )
        except QuotaExhausted:
            run_log["stopped"] = "kuota habis"
            run_log["finished_at"] = _now()
            save_manifest()
            raise
    run_log["finished_at"] = _now()
    if skipped:
        run_log["skipped"] = skipped
    save_manifest()

    sheets: list[Path] = []
    if len(done) == len(questions):
        sheets = write_rating_sheets(out_dir, questions)
    return Tahap1Result(out_dir, answered_now, len(done), len(questions), skipped, sheets)


def _answer_one(
    q: dict[str, str],
    pipeline: AnswerPipeline,
    eval_llm: EvalLlm,
    llm: _RecordingLlm,
    kb: KnowledgeBase,
    identity: dict[str, Any],
    attempts_path: Path,
    sleep: Callable[[float], None],
    max_attempts: int,
    retry_wait_s: float,
    progress: Callable[[str], None] | None,
) -> dict[str, Any] | None:
    """Satu soal; diulang hanya bila API error/timeout (status unavailable). None = belum terjawab."""
    api_before = eval_llm.stats.api_calls
    for attempt in range(1, max_attempts + 1):
        asked_at = _now()
        llm.last_error = None
        eval_llm.last, eval_llm.last_from_cache = None, False
        start = time.perf_counter()
        try:
            final, record = pipeline.run(q["pertanyaan"], [], session_id=f"tahap1-{q['id']}")
        except QuotaExhausted as exc:
            _append_jsonl(attempts_path, {
                "id": q["id"], "attempt": attempt, "ts": asked_at, "outcome": "quota",
                "reason": str(exc),
            })  # fmt: skip
            raise
        wall = time.perf_counter() - start
        entry = {
            "id": q["id"],
            "attempt": attempt,
            "ts": asked_at,
            "outcome": "ok" if final.status != "unavailable" else "unavailable",
            "status": final.status,
            "error_code": record.error_code,
            "reason": llm.last_error,
            "api_calls_total": eval_llm.stats.api_calls - api_before,
        }
        _append_jsonl(attempts_path, entry)
        if final.status != "unavailable":
            return answer_row(
                q, final, record, kb, identity, asked_at=asked_at, wall_s=wall,
                api_attempts=eval_llm.stats.api_calls - api_before, question_attempts=attempt,
                from_cache=eval_llm.last_from_cache,
            )  # fmt: skip
        if progress is not None:
            progress(f"{q['id']}: API gagal ({llm.last_error}), percobaan {attempt}/{max_attempts}")
        if attempt < max_attempts:
            sleep(retry_wait_s)
    return None


# --- lembar penilaian ---------------------------------------------------------------


def shuffled_ids(ids: list[str], seed: int = SHEET_SEED) -> list[str]:
    order = list(ids)
    random.Random(seed).shuffle(order)
    return order


def rating_sheets(
    questions: list[dict[str, str]], answers: list[dict[str, Any]], seed: int = SHEET_SEED
) -> list[Sheet]:
    """Tanpa topik, persona, skor, atau status gerbang; tanpa kunci jawaban."""
    by_id = {a["id"]: a for a in answers}
    order = shuffled_ids([q["id"] for q in questions], seed)
    nilai = [list(NILAI_COLUMNS)]
    potongan = [list(POTONGAN_COLUMNS)]
    for qid in order:
        a = by_id[qid]
        nilai.append(
            [qid, a["question"], a["final_text"], "\n".join(a["sources_shown"]), "", "", ""]
        )
        for chunk in a["top5"]:
            potongan.append([qid, str(chunk["rank"]), chunk["source"], chunk["text"]])
    petunjuk = [["petunjuk"], ["Label per jawaban (pra-registrasi bagian 4):"]]
    petunjuk += [[f"{label}: {definition}"] for label, definition in LABELS]
    petunjuk += [
        [""],
        ["Nilai sendiri, jangan melihat lembar penilai lain, cek ke dokumen resmi."],
        [OFFICIAL_DOCS],
        [
            (
                "Sheet 'nilai': pilih label dari dropdown. Bila label halusinasi, tulis klaim "
                "yang dikarang di kolom 'klaim yang dikarang'."
            )
        ],
        ["Sheet 'potongan': lima potongan KB yang diambil sistem untuk setiap soal."],
    ]
    return [
        Sheet(
            "nilai",
            nilai,
            widths=[9, 45, 70, 40, 16, 40, 30],
            dropdowns=[("E", tuple(label for label, _ in LABELS))],
        ),
        Sheet("potongan", potongan, widths=[9, 8, 45, 100]),
        Sheet("petunjuk", petunjuk, widths=[120]),
    ]


def write_rating_sheets(out_dir: Path, questions: list[dict[str, str]]) -> list[Path]:
    """Dua lembar identik; hanya bila semua soal terjawab. File yang sudah ada tidak ditimpa."""
    out_dir = Path(out_dir)
    answers = read_answers(out_dir / ANSWERS_FILE)
    have = {a["id"] for a in answers}
    missing = [q["id"] for q in questions if q["id"] not in have]
    if missing:
        raise Tahap1Error(
            f"lembar penilaian dibuat setelah semua soal terjawab; sisa {len(missing)}"
        )
    paths = [out_dir / name for name in SHEETS]
    if any(p.exists() for p in paths):
        return [p for p in paths if p.exists()]  # bisa jadi sudah diisi penilai
    sheets = rating_sheets(questions, answers)
    for path in paths:
        write_xlsx(path, sheets)
    return paths
