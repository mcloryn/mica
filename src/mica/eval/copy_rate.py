"""M-12: python -m mica.eval copy (E-03, ADR-07): tingkat salin jawaban terhadap sumber.

Extractive fragments menurut Grusky, Naaman, dan Artzi 2018 (Newsroom) [43], dipakai juga oleh
Ladhak dkk. 2022 [42]: F(A, S) adalah himpunan fragmen bersama hasil algoritma greedy yang, untuk
setiap posisi di S, mengambil potongan terpanjang yang juga muncul berurutan di A, lalu melompat
melewati fragmen itu.

    coverage(A, S) = (1 / |S|) * sum_{f in F(A, S)} |f|
    density(A, S)  = (1 / |S|) * sum_{f in F(A, S)} |f|^2

S = token jawaban, A = token sumber. Tokenisasi sama dengan BM25 M-03 (mica.kb.index.tokenize:
huruf kecil + \\w+). Beberapa potongan sumber digabung berurutan dengan pemisah yang tidak pernah
cocok, sehingga fragmen tidak melintasi batas potongan.

Dua jenis sumber per jawaban: (a) potongan yang dikutip (citations), konsisten dengan definisi
halusinasi; (b) semua potongan konteks yang dikirim ke LLM. Hanya jawaban dengan llm_status
answered atau false_premise yang dihitung; penolakan dikecualikan dan dihitung. Tanpa ambang
"bagus/buruk". Tidak ada panggilan LLM: konteks direkonstruksi dengan pipeline yang sama dalam
mode cache-only, dan setiap request harus cocok dengan cache (kunci = hash badan request).
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mica.core.types import joined_answer
from mica.eval.metrics import percentile
from mica.kb.index import tokenize

EXPERIMENT = "E-03"
COUNTED_STATUSES = ("answered", "false_premise")
TOKENIZATION = "mica.kb.index.tokenize (huruf kecil + \\w+), sama dengan BM25 M-03"
_BOUNDARY = object()  # pemisah antarpotongan, tidak pernah sama dengan token mana pun
ITEM_FIELDS = (
    "qid", "model", "status", "n_token_jawaban", "coverage_kutip", "density_kutip",
    "coverage_konteks", "density_konteks", "n_fragmen", "fragmen_terpanjang",
    "n_fragmen_konteks", "fragmen_terpanjang_konteks",
    # pendamping tanpa entitas (SDD 9.5); n_token = |S|, n_token_entitas = |E|
    "n_token", "n_token_entitas", "coverage_tanpa_entitas_kutip", "density_tanpa_entitas_kutip",
    "coverage_tanpa_entitas_konteks", "density_tanpa_entitas_konteks",
    "fragmen_terpanjang_tanpa_entitas_kutip",
)  # fmt: skip


def fragments(article: Sequence[Any], summary: Sequence[Any]) -> list[list[Any]]:
    """F(A, S), algoritma greedy Grusky dkk. 2018 (indeks mulai 0)."""
    out: list[list[Any]] = []
    i = 0
    while i < len(summary):
        best: list[Any] = []
        j = 0
        while j < len(article):
            if summary[i] == article[j]:
                ii, jj = i, j
                while ii < len(summary) and jj < len(article) and summary[ii] == article[jj]:
                    ii, jj = ii + 1, jj + 1
                if len(best) < ii - i:
                    best = list(summary[i:ii])
                j = jj
            else:
                j += 1
        i += max(len(best), 1)
        if best:
            out.append(best)
    return out


@dataclass(frozen=True)
class CopyScore:
    n_tokens: int
    coverage: float
    density: float
    fragments: tuple[tuple[str, ...], ...]

    @property
    def longest(self) -> tuple[str, ...]:
        return max(self.fragments, key=len, default=())


def copy_score(answer: str, sources: Sequence[str]) -> CopyScore:
    """coverage dan density jawaban terhadap gabungan sumber; jawaban kosong -> 0 dan 0."""
    s = tokenize(answer)
    a: list[Any] = []
    for k, text in enumerate(sources):
        if k:
            a.append(_BOUNDARY)
        a.extend(tokenize(text))
    frags = fragments(a, s) if s else []
    n = len(s)
    total = sum(len(f) for f in frags)
    squares = sum(len(f) ** 2 for f in frags)
    return CopyScore(n, total / n if n else 0.0, squares / n if n else 0.0,
                     tuple(tuple(f) for f in frags))  # fmt: skip


# --- metrik pendamping: tanpa entitas (aturan pra-registrasi E-03, SDD 9.5) -------------
#
# Fungsi Grusky di atas tidak diubah. Span entitas ditandai pada teks jawaban MENTAH:
# (i) email, (ii) URL yang diawali http://, https://, atau www., (iii) setiap kata (dipisah
# spasi) yang memuat minimal satu digit 0-9. Token jawaban yang tumpang tindih dengan span itu
# adalah token entitas (E): tidak boleh masuk fragmen mana pun, dan penyebutnya |S| - |E|.
# Nama orang, prodi, dan istilah tidak di-mask (butuh NER). Teks sumber tidak diubah.

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
WORD_WITH_DIGIT = re.compile(r"\S*[0-9]\S*")
_WORD = re.compile(r"\w+")  # sama dengan mica.kb.index._TOKEN


def tokenize_with_offsets(text: str) -> list[tuple[str, int, int]]:
    """Token persis seperti mica.kb.index.tokenize (huruf kecil + \\w+), beserta offset karakter
    di teks mentah. Huruf yang berubah panjang saat lower() (mis. "İ") dipetakan per karakter."""
    lowered: list[str] = []
    origin: list[int] = []  # indeks karakter mentah untuk setiap karakter hasil lower()
    for i, ch in enumerate(text):
        low = ch.lower()
        lowered.append(low)
        origin.extend([i] * len(low))
    low_text = "".join(lowered)
    return [(m.group(), origin[m.start()], origin[m.end() - 1] + 1)
            for m in _WORD.finditer(low_text)]  # fmt: skip


def entity_spans(text: str) -> list[tuple[int, int]]:
    """Span karakter email, URL, dan kata berdigit di teks mentah."""
    spans = [m.span() for pattern in (EMAIL, URL, WORD_WITH_DIGIT) for m in pattern.finditer(text)]
    return sorted(spans)


def entity_mask(text: str) -> tuple[list[str], list[bool]]:
    """Token jawaban dan penanda entitas per token (tumpang tindih dengan span entitas)."""
    spans = entity_spans(text)
    tokens, mask = [], []
    for token, start, end in tokenize_with_offsets(text):
        tokens.append(token)
        mask.append(any(start < s_end and end > s_start for s_start, s_end in spans))
    return tokens, mask


def fragments_masked(article: Sequence[Any], summary: Sequence[Any],
                     blocked: Sequence[bool]) -> list[list[Any]]:  # fmt: skip
    """Greedy Grusky yang sama, tetapi token summary bertanda blocked tidak pernah masuk
    fragmen: fragmen terputus tepat di token itu, dan token itu sendiri dilewati."""
    out: list[list[Any]] = []
    i = 0
    while i < len(summary):
        if blocked[i]:
            i += 1
            continue
        best: list[Any] = []
        j = 0
        while j < len(article):
            if summary[i] == article[j]:
                ii, jj = i, j
                while (ii < len(summary) and jj < len(article) and not blocked[ii]
                       and summary[ii] == article[jj]):  # fmt: skip
                    ii, jj = ii + 1, jj + 1
                if len(best) < ii - i:
                    best = list(summary[i:ii])
                j = jj
            else:
                j += 1
        i += max(len(best), 1)
        if best:
            out.append(best)
    return out


@dataclass(frozen=True)
class MaskedScore:
    n_tokens: int  # |S|
    n_entity: int  # |E|
    coverage: float | None  # None bila |S| - |E| = 0
    density: float | None
    fragments: tuple[tuple[str, ...], ...]

    @property
    def longest(self) -> tuple[str, ...]:
        return max(self.fragments, key=len, default=())


def copy_score_masked(answer: str, sources: Sequence[str]) -> MaskedScore:
    tokens, mask = entity_mask(answer)
    a: list[Any] = []
    for k, text in enumerate(sources):
        if k:
            a.append(_BOUNDARY)
        a.extend(tokenize(text))
    frags = fragments_masked(a, tokens, mask) if tokens else []
    n_entity = sum(mask)
    denom = len(tokens) - n_entity
    total = sum(len(f) for f in frags)
    squares = sum(len(f) ** 2 for f in frags)
    return MaskedScore(len(tokens), n_entity, total / denom if denom else None,
                       squares / denom if denom else None,
                       tuple(tuple(f) for f in frags))  # fmt: skip


# --- jawaban dari run E-04 ------------------------------------------------------------


@dataclass
class AnswerItem:
    qid: str
    model: str
    status: str  # llm_status
    answer: str
    cited_ids: tuple[str, ...]
    context_ids: tuple[str, ...]


@dataclass
class ItemScore:
    item: AnswerItem
    cited: CopyScore | None  # None bila tidak ada kutipan
    context: CopyScore
    cited_masked: MaskedScore | None = None
    context_masked: MaskedScore | None = None


def score_items(items: list[AnswerItem], texts: dict[str, str]) -> tuple[list[ItemScore], int]:
    """Hitung jawaban berstatus COUNTED_STATUSES; kembalikan juga jumlah yang dikecualikan."""
    scored, excluded = [], 0
    for it in items:
        if it.status not in COUNTED_STATUSES:
            excluded += 1
            continue
        missing = [c for c in (*it.cited_ids, *it.context_ids) if c not in texts]
        if missing:
            raise KeyError(f"{it.model} {it.qid}: chunk tidak ada di KB: {missing}")
        cited_texts = [texts[c] for c in it.cited_ids]
        context_texts = [texts[c] for c in it.context_ids]
        cited = copy_score(it.answer, cited_texts) if it.cited_ids else None
        scored.append(ItemScore(
            it, cited, copy_score(it.answer, context_texts),
            copy_score_masked(it.answer, cited_texts) if it.cited_ids else None,
            copy_score_masked(it.answer, context_texts),
        ))  # fmt: skip
    return scored, excluded


def _fmt(x: float | None) -> str:
    return "" if x is None else f"{x:.4f}"


def item_row(s: ItemScore) -> dict[str, Any]:
    c, k = s.cited, s.context
    cm, km = s.cited_masked, s.context_masked
    return {
        "qid": s.item.qid, "model": s.item.model, "status": s.item.status,
        "n_token_jawaban": k.n_tokens,
        "coverage_kutip": _fmt(c.coverage if c else None),
        "density_kutip": _fmt(c.density if c else None),
        "coverage_konteks": _fmt(k.coverage), "density_konteks": _fmt(k.density),
        "n_fragmen": len(c.fragments) if c else "",
        "fragmen_terpanjang": " ".join(c.longest) if c else "",
        "n_fragmen_konteks": len(k.fragments), "fragmen_terpanjang_konteks": " ".join(k.longest),
        "n_token": km.n_tokens if km else "", "n_token_entitas": km.n_entity if km else "",
        "coverage_tanpa_entitas_kutip": _fmt(cm.coverage if cm else None),
        "density_tanpa_entitas_kutip": _fmt(cm.density if cm else None),
        "coverage_tanpa_entitas_konteks": _fmt(km.coverage if km else None),
        "density_tanpa_entitas_konteks": _fmt(km.density if km else None),
        "fragmen_terpanjang_tanpa_entitas_kutip": " ".join(cm.longest) if cm else "",
    }  # fmt: skip


def _stats(values: list[float]) -> dict[str, str]:
    if not values:
        return {"mean": "", "median": "", "p90": ""}
    return {"mean": _fmt(sum(values) / len(values)), "median": _fmt(percentile(values, 50)),
            "p90": _fmt(percentile(values, 90))}  # fmt: skip


def summary_rows(model: str, scored: list[ItemScore], excluded: int) -> list[dict[str, Any]]:
    rows = []
    for source in ("kutip", "konteks"):
        scores = [s.cited if source == "kutip" else s.context for s in scored]
        present = [x for x in scores if x is not None]
        cov, den = _stats([x.coverage for x in present]), _stats([x.density for x in present])
        masked = [s.cited_masked if source == "kutip" else s.context_masked for s in scored]
        masked = [m for m in masked if m is not None]
        # |S| - |E| = 0: nilai kosong, dikeluarkan dari rata-rata dan dihitung
        valid = [m for m in masked if m.coverage is not None]
        mcov = _stats([m.coverage for m in valid])  # type: ignore[misc]
        mden = _stats([m.density for m in valid])  # type: ignore[misc]
        rows.append({
            "model": model, "sumber": source, "n": len(present),
            "n_tanpa_kutipan": sum(x is None for x in scores) if source == "kutip" else "",
            "n_dikecualikan": excluded,
            **{f"coverage_{k}": v for k, v in cov.items()},
            **{f"density_{k}": v for k, v in den.items()},
            "n_tanpa_entitas": len(valid), "n_kosong_tanpa_entitas": len(masked) - len(valid),
            "n_token_total": sum(m.n_tokens for m in masked),
            "n_token_entitas_total": sum(m.n_entity for m in masked),
            **{f"coverage_tanpa_entitas_{k}": v for k, v in mcov.items()},
            **{f"density_tanpa_entitas_{k}": v for k, v in mden.items()},
        })  # fmt: skip
    return rows


def write_outputs(run_dir: Path, scored: list[ItemScore], summaries: list[dict[str, Any]],
                  info: dict[str, Any]) -> None:  # fmt: skip
    run_dir.mkdir(parents=True, exist_ok=False)
    with (run_dir / "per_item.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ITEM_FIELDS)
        writer.writeheader()
        writer.writerows(item_row(s) for s in scored)
    with (run_dir / "summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    (run_dir / "run.json").write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")  # fmt: skip


def top_density(scored: list[ItemScore], n: int = 3, max_words: int = 25) -> list[str]:
    """n contoh density kutip tertinggi: qid, density, fragmen terpanjang (maks max_words kata)."""
    ranked = sorted((s for s in scored if s.cited is not None),
                    key=lambda s: s.cited.density, reverse=True)  # type: ignore[union-attr]  # fmt: skip
    lines = []
    for s in ranked[:n]:
        assert s.cited is not None
        words = list(s.cited.longest)
        text = " ".join(words[:max_words]) + (" ..." if len(words) > max_words else "")
        lines.append(f"{s.item.qid} density {s.cited.density:.2f} ({len(words)} token): {text}")
    return lines


# --- rekonstruksi dari run E-04 (tanpa panggilan LLM) ------------------------------------


class RunMismatch(Exception):
    """Rekonstruksi konteks tidak cocok dengan run sumber (request, jawaban, atau dataset)."""


def read_per_question(run_dir: Path) -> dict[str, dict[str, str]]:
    with (Path(run_dir) / "per_question.csv").open(encoding="utf-8-sig", newline="") as f:
        return {row["qid"]: row for row in csv.DictReader(f)}


def _split_ids(value: str) -> tuple[str, ...]:
    return tuple(c.strip() for c in value.split(";") if c.strip())


def load_run(run_dir: Path, settings: Any, kb: Any, cache_dir: Path,
             embedder: Any) -> tuple[str, list[AnswerItem], dict[str, Any]]:  # fmt: skip
    """Jawaban dan kutipan dari per_question.csv; potongan konteks dari pipeline yang sama dalam
    mode cache-only. Setiap request harus ada di cache (tanpa panggilan API) dan setiap jawaban
    hasil rekonstruksi harus sama dengan per_question.csv; bila tidak, RunMismatch."""
    from mica.eval.dataset import load_questions
    from mica.eval.generation import (
        CacheMiss,
        EvalLlm,
        LlmCache,
        TokenRateLimiter,
        answer_questions,
        dev_questions,
        effective_settings,
    )
    from mica.eval.retrieval import sha256_file
    from mica.rag.checker import NumericFactChecker
    from mica.rag.gate import make_gate
    from mica.rag.llm import make_llm
    from mica.rag.pipeline import AnswerPipeline
    from mica.rag.retriever import make_retriever

    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    model = run["llm"].get("model_override") or run["llm"]["provider"]
    if run["kb_id"] != kb.kb_id:
        raise RunMismatch(f"{run_dir.name}: kb_id {run['kb_id']} != KB aktif {kb.kb_id}")
    dataset = Path(run["dataset"]["path"])
    if sha256_file(dataset) != run["dataset"]["sha256"]:
        raise RunMismatch(f"{run_dir.name}: {dataset} berubah sejak run (sha256 berbeda)")
    # varian prompt run itu (v3: docs/PROMPT-V3.md); run lama tanpa field = config
    eff = effective_settings(settings, bool(run["gate_off"]), model, run.get("prompt_variant"))
    provider = make_llm(eff).providers[0]
    llm = EvalLlm(provider, TokenRateLimiter(), cache=LlmCache(cache_dir), cache_only=True)
    retriever = make_retriever(eff, kb, embedder_factory=lambda m, r: embedder)
    pipeline = AnswerPipeline(eff, retriever, make_gate(eff), llm, NumericFactChecker(),
                              kb_id=kb.kb_id, log=None)  # fmt: skip
    try:
        rows = answer_questions(pipeline, llm, dev_questions(load_questions(dataset)), None)
    except CacheMiss as exc:
        raise RunMismatch(
            f"{run_dir.name}: request rekonstruksi tidak ada di cache ({exc})"
        ) from None
    if llm.stats.api_calls:
        raise RunMismatch(f"{run_dir.name}: {llm.stats.api_calls} panggilan API (harus 0)")
    saved = read_per_question(run_dir)
    items = []
    for r in rows:
        row = saved.get(r.qid)
        if (row is None or row["answer"] != r.answer or row["llm_status"] != (r.llm_status or "")
                or row.get("items", "") != "; ".join(r.items)):  # fmt: skip
            raise RunMismatch(f"{run_dir.name} {r.qid}: jawaban rekonstruksi beda dengan run")
        # prompt v4: teks yang dinilai = answer + items (joined_answer), sama dengan cek angka
        text = joined_answer(row["answer"], r.items)
        items.append(AnswerItem(r.qid, model, row["llm_status"], text,
                                _split_ids(row["citations"]), tuple(r.retrieved_ids)))  # fmt: skip
    info = {"run": run_dir.as_posix(), "model": model, "gate_off": run["gate_off"],
            "prompt_version": run.get("prompt_version"), "n_questions": len(items),
            "llm_api_calls": llm.stats.api_calls, "from_cache": llm.stats.from_cache,
            "context_source": "rekonstruksi pipeline cache-only; request = kunci cache run"}  # fmt: skip
    return model, items, info


def top_density_masked(scored: list[ItemScore], n: int = 3, max_words: int = 25) -> list[str]:
    """n contoh density_tanpa_entitas kutip tertinggi beserta fragmen terpanjangnya."""
    ranked = sorted(
        (s for s in scored if s.cited_masked is not None and s.cited_masked.density is not None),
        key=lambda s: s.cited_masked.density,  # type: ignore[union-attr]
        reverse=True,
    )
    lines = []
    for s in ranked[:n]:
        m = s.cited_masked
        assert m is not None and m.density is not None
        words = list(m.longest)
        text = " ".join(words[:max_words]) + (" ..." if len(words) > max_words else "")
        lines.append(f"{s.item.qid} density_tanpa_entitas {m.density:.2f} ({len(words)} token): "
                     f"{text}")  # fmt: skip
    return lines
