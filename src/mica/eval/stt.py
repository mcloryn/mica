"""M-12: python -m mica.eval stt (E-05). Aturan E-05 dipra-registrasi di SDD 2.4.

Dataset data/eval/speech/<nama>/manifest.jsonl, satu baris per rekaman: id, file (WAV 16 kHz
mono int16, relatif terhadap folder manifest), jenis (pertanyaan | diam | bising), referensi
(wajib untuk pertanyaan), qid (opsional), penutur (kode anonim), persetujuan (harus true).
Rekaman relawan tidak di-commit (.gitignore). Format ini berbeda dari SDD 6.3 (transcripts.csv),
atas keputusan pengguna 17 Okt 2026, karena E-05 butuh jenis, qid, dan persetujuan.

Per rekaman: SpeechSegmenter + penyaring min_speech -> STT (penyaring no_speech di STT) ->
metrik. Akhir file diberi diam sepanjang min_silence_ms supaya VAD menutup ucapan terakhir,
setara pengunjung berhenti bicara. waktu_sampai_teks = vad_end (akhir bicara -> VAD menutup
ucapan) + stt_s ucapan terakhir yang lolos. transkripsi_palsu (diam/bising) = 1 bila ada
Transcript ok. Bila qid ada: retriever aktif (tanpa LLM) pada transkripsi dan referensi,
hit@5 terhadap gold_chunk_ids. Pemenang tidak dipilih otomatis.

input_mode push_to_talk (amandemen 1 E-05, Langkah 42; bawaan dari audio.input_mode): setiap
rekaman = satu kali tombol ditahan. VAD hanya mengecek ada ucapan dan memangkas hening
(push_to_talk_utterance); tanpa ucapan STT tidak dipanggil. Rekaman lebih panjang dari
max_utterance_s dipotong (dikirim otomatis). vad_end_s = lama cek VAD, sehingga
waktu_sampai_teks = tombol dilepas -> teks. input_mode vad = cara lama di atas.
"""

from __future__ import annotations

import csv
import json
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from mica.audio.stt import SpeechToText, Transcript
from mica.audio.vad import (
    CHUNK_SAMPLES,
    SAMPLE_RATE,
    SpeechSegmenter,
    Utterance,
    is_too_short,
    push_to_talk_utterance,
)
from mica.eval.metrics import hit_at, percentile
from mica.eval.wer import cer, corpus_cer, corpus_wer, normalize_for_wer, wer
from mica.rag.pii import scrub_pii

EXPERIMENT = "E-05"
KINDS = ("pertanyaan", "diam", "bising")
# SDD 2.4 (aturan E-05): p95 waktu sampai transkripsi tampil paling lama 3 detik di laptop PMB
P95_LIMIT_S = 3.0
TOP_K = 5  # Recall@5 (SDD 2.4, metrik tambahan E-05)
E05_RULE = (
    "Aturan E-05 ditetapkan sebelum data: syarat p95 waktu sampai transkripsi tampil paling lama "
    "3 detik di laptop PMB; pemenang WER terkecil; seri dimenangkan STT lokal."
)
CER_NORMALIZATION = "sama dengan WER (normalize_for_wer); lalu jiwer.cer"
ITEM_FIELDS = (
    "id", "jenis", "penutur", "qid", "referensi_norm", "hipotesis_norm", "wer", "cer",
    "audio_s", "n_ucapan", "stt_s", "vad_end_s", "waktu_sampai_teks_s", "transkripsi_palsu",
    "filtered_by", "hit5_transkripsi", "hit5_referensi",
)  # fmt: skip


class ManifestError(Exception):
    pass


@dataclass(frozen=True)
class SpeechItem:
    id: str
    file: Path
    kind: Literal["pertanyaan", "diam", "bising"]
    reference: str | None
    qid: str | None
    speaker: str


def load_manifest(path: Path) -> list[SpeechItem]:
    """Baca manifest; baris tanpa persetujuan true ditolak (seluruh manifest gagal)."""
    path = Path(path)
    items: list[SpeechItem] = []
    seen: set[str] = set()
    errors: list[str] = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"baris {no}: bukan JSON ({exc.msg})")
            continue
        rid = str(row.get("id") or f"baris {no}")
        if row.get("persetujuan") is not True:
            errors.append(f"{rid}: persetujuan bukan true (rekaman tanpa persetujuan ditolak)")
            continue
        kind = row.get("jenis")
        if kind not in KINDS:
            errors.append(f"{rid}: jenis {kind!r} bukan salah satu {KINDS}")
            continue
        reference = row.get("referensi")
        if kind == "pertanyaan" and not (isinstance(reference, str) and reference.strip()):
            errors.append(f"{rid}: referensi wajib untuk jenis pertanyaan")
            continue
        if not row.get("file") or not row.get("penutur") or not row.get("id"):
            errors.append(f"{rid}: id, file, dan penutur wajib")
            continue
        if rid in seen:
            errors.append(f"{rid}: id ganda")
            continue
        seen.add(rid)
        items.append(SpeechItem(rid, path.parent / row["file"], kind, reference,
                                row.get("qid") or None, str(row["penutur"])))  # fmt: skip
    if errors:
        raise ManifestError(f"{path.as_posix()}:\n  " + "\n  ".join(errors))
    if not items:
        raise ManifestError(f"{path.as_posix()}: tidak ada rekaman")
    return items


def read_wav(path: Path) -> np.ndarray:
    """WAV 16 kHz mono int16 -> int16; format lain ditolak (tanpa resample diam-diam)."""
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            raise ManifestError(
                f"{path.as_posix()}: harus WAV 16 kHz mono 16-bit, didapat "
                f"{w.getframerate()} Hz, {w.getnchannels()} kanal, {8 * w.getsampwidth()} bit"
            )
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).copy()


# --- satu rekaman -----------------------------------------------------------------------


@dataclass
class ItemResult:
    item: SpeechItem
    hypothesis: str
    audio_s: float
    n_utterances: int
    stt_s: float | None  # ucapan terakhir yang lolos
    vad_end_s: float | None
    filtered_by: tuple[str, ...]
    false_transcript: int | None = None  # hanya diam/bising
    wer: float | None = None
    cer: float | None = None
    hit5_hyp: bool | None = None
    hit5_ref: bool | None = None

    @property
    def time_to_text_s(self) -> float | None:
        if self.stt_s is None or self.vad_end_s is None:
            return None
        return self.vad_end_s + self.stt_s


def segment(pcm: np.ndarray, segmenter: SpeechSegmenter) -> list[tuple[Utterance, float]]:
    """Ucapan beserta vad_end_s (akhir bicara -> VAD menutup ucapan)."""
    segmenter.reset()
    tail = np.zeros(segmenter.min_silence + CHUNK_SAMPLES, dtype=np.int16)
    audio = np.concatenate([np.asarray(pcm, dtype=np.int16), tail])
    out: list[tuple[Utterance, float]] = []
    for i in range(0, len(audio) - CHUNK_SAMPLES + 1, CHUNK_SAMPLES):
        for event in segmenter.feed(audio[i : i + CHUNK_SAMPLES]):
            if isinstance(event, Utterance):
                closed_s = segmenter.consumed / segmenter.sample_rate
                out.append((event, max(closed_s - (event.start_s + event.speech_s), 0.0)))
    return out


def push_to_talk(pcm: np.ndarray, segmenter: SpeechSegmenter) -> list[tuple[Utterance, float]]:
    """Satu rekaman = satu kali tombol ditahan: [(ucapan, lama cek VAD)] atau [] tanpa ucapan."""
    import time

    audio = np.asarray(pcm, dtype=np.int16)
    cut = len(audio) > segmenter.max_samples
    t0 = time.perf_counter()
    utt = push_to_talk_utterance(audio[: segmenter.max_samples], segmenter.prob,
                                 segmenter.threshold, cut)  # fmt: skip
    check_s = time.perf_counter() - t0
    return [] if utt is None else [(utt, check_s)]


def evaluate_item(
    item: SpeechItem,
    pcm: np.ndarray,
    segmenter: SpeechSegmenter,
    stt: SpeechToText,
    min_speech_ms: float | None,
    input_mode: str = "vad",
) -> ItemResult:
    texts: list[str] = []
    filtered: list[str] = []
    stt_s = vad_end = None
    if input_mode == "push_to_talk":
        utterances = push_to_talk(pcm, segmenter)
        if not utterances:
            filtered.append("no_voice")
    else:
        utterances = segment(pcm, segmenter)
    for utt, utt_vad_end in utterances:
        if is_too_short(utt, min_speech_ms):
            filtered.append("min_speech")
            continue
        t: Transcript = stt.transcribe(utt.pcm16k)
        if t.filtered_by is not None:
            filtered.append(t.filtered_by)
            continue
        if t.ok:
            texts.append(t.text)
            stt_s, vad_end = t.stt_s, utt_vad_end
    hypothesis = " ".join(texts).strip()
    noise = item.kind != "pertanyaan"
    result = ItemResult(item, hypothesis, len(pcm) / SAMPLE_RATE, len(utterances), stt_s,
                        vad_end, tuple(filtered),
                        int(bool(texts)) if noise else None)  # fmt: skip
    if item.kind == "pertanyaan" and item.reference is not None:
        result.wer = wer(item.reference, hypothesis)
        result.cer = cer(item.reference, hypothesis)
    return result


def add_retrieval(
    results: list[ItemResult],
    search: Callable[[str], list[str]],
    gold: dict[str, Sequence[str]],
) -> None:
    """hit@5 transkripsi vs referensi untuk rekaman ber-qid (retriever tanpa LLM)."""
    for r in results:
        qid = r.item.qid
        if qid is None or r.item.reference is None:
            continue
        relevant = set(gold.get(qid) or ())
        if not relevant:
            continue
        r.hit5_ref = hit_at(search(r.item.reference), relevant, TOP_K)
        r.hit5_hyp = hit_at(search(r.hypothesis), relevant, TOP_K) if r.hypothesis else False


# --- ringkasan --------------------------------------------------------------------------


@dataclass
class Summary:
    config: str
    local: bool
    n_questions: int
    n_noise: int
    wer_total: float | None
    cer_total: float | None
    t2t_p50_s: float | None
    t2t_p95_s: float | None
    n_t2t: int
    false_rate: float | None
    n_false: int
    recall5_hyp: float | None
    recall5_ref: float | None
    n_retrieval: int
    extra: dict[str, Any] = field(default_factory=dict)

    def row(self) -> dict[str, Any]:
        def f(x: float | None) -> str:
            return "" if x is None else f"{x:.4f}"

        return {
            "konfigurasi": self.config, "lokal": int(self.local),
            "n_pertanyaan": self.n_questions, "n_diam_bising": self.n_noise,
            "wer_total": f(self.wer_total), "cer_total": f(self.cer_total),
            "waktu_sampai_teks_p50_s": f(self.t2t_p50_s),
            "waktu_sampai_teks_p95_s": f(self.t2t_p95_s), "n_waktu": self.n_t2t,
            "laju_transkripsi_palsu": f(self.false_rate), "n_palsu": self.n_false,
            "recall5_transkripsi": f(self.recall5_hyp), "recall5_referensi": f(self.recall5_ref),
            "n_retrieval": self.n_retrieval,
        }  # fmt: skip


def summarize(config: str, local: bool, results: list[ItemResult]) -> Summary:
    questions = [r for r in results if r.item.kind == "pertanyaan"]
    noise = [r for r in results if r.item.kind != "pertanyaan"]
    times = [t for r in questions if (t := r.time_to_text_s) is not None]
    retrieval = [r for r in questions if r.hit5_ref is not None]
    n_false = sum(r.false_transcript or 0 for r in noise)
    refs = [r.item.reference or "" for r in questions]
    hyps = [r.hypothesis for r in questions]
    return Summary(
        config, local, len(questions), len(noise),
        corpus_wer(refs, hyps) if questions else None,
        corpus_cer(refs, hyps) if questions else None,
        percentile(times, 50) if times else None, percentile(times, 95) if times else None,
        len(times), n_false / len(noise) if noise else None, n_false,
        sum(bool(r.hit5_hyp) for r in retrieval) / len(retrieval) if retrieval else None,
        sum(bool(r.hit5_ref) for r in retrieval) / len(retrieval) if retrieval else None,
        len(retrieval),
    )  # fmt: skip


def item_row(r: ItemResult) -> dict[str, Any]:
    def f(x: float | None) -> str:
        return "" if x is None else f"{x:.4f}"

    def b(x: bool | None) -> str:
        return "" if x is None else str(int(x))

    hyp = scrub_pii(r.hypothesis)  # N-09: teks ditulis hanya setelah disamarkan
    return {
        "id": r.item.id, "jenis": r.item.kind, "penutur": r.item.speaker, "qid": r.item.qid or "",
        "referensi_norm": normalize_for_wer(r.item.reference or ""),
        "hipotesis_norm": normalize_for_wer(hyp), "wer": f(r.wer), "cer": f(r.cer),
        "audio_s": f(r.audio_s), "n_ucapan": r.n_utterances, "stt_s": f(r.stt_s),
        "vad_end_s": f(r.vad_end_s), "waktu_sampai_teks_s": f(r.time_to_text_s),
        "transkripsi_palsu": "" if r.false_transcript is None else r.false_transcript,
        "filtered_by": ";".join(r.filtered_by), "hit5_transkripsi": b(r.hit5_hyp),
        "hit5_referensi": b(r.hit5_ref),
    }  # fmt: skip


def write_config(config_dir: Path, results: list[ItemResult], summary: Summary,
                 info: dict[str, Any]) -> None:  # fmt: skip
    """<run>/<konfigurasi>/per_item.csv (tanpa audio) dan run.json."""
    config_dir.mkdir(parents=True, exist_ok=False)
    with (config_dir / "per_item.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ITEM_FIELDS)
        writer.writeheader()
        writer.writerows(item_row(r) for r in results)
    (config_dir / "run.json").write_text(
        json.dumps({**info, "summary": summary.row()}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


def write_summary(run_dir: Path, summaries: list[Summary]) -> None:
    """<run>/summary.csv, satu baris per konfigurasi."""
    rows = [s.row() for s in summaries]
    with (run_dir / "summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def format_table(summaries: list[Summary]) -> str:
    """Tabel sesuai aturan E-05; pemenang tidak dipilih otomatis."""

    def f(x: float | None, digits: int = 3) -> str:
        return "-" if x is None else f"{x:.{digits}f}"

    lines = [
        E05_RULE,
        (
            "konfigurasi | lokal | WER total | CER total | p50 s | p95 s | p95 <= 3 s | "
            "palsu | R@5 transkripsi | R@5 referensi"
        ),
    ]
    for s in summaries:
        meets = "-" if s.t2t_p95_s is None else ("ya" if s.t2t_p95_s <= P95_LIMIT_S else "tidak")
        palsu = "-" if s.false_rate is None else f"{s.n_false}/{s.n_noise} ({s.false_rate:.2f})"
        lines.append(
            f"{s.config} | {'ya' if s.local else 'tidak'} | {f(s.wer_total, 4)} | "
            f"{f(s.cer_total, 4)} | {f(s.t2t_p50_s)} | {f(s.t2t_p95_s)} | {meets} | {palsu} | "
            f"{f(s.recall5_hyp)} | {f(s.recall5_ref)}"
        )
    lines.append("Pemenang tidak dipilih otomatis. p95 <= 3 s hanya sah bila diukur di laptop "
                 "PMB (SDD 2.4).")  # fmt: skip
    return "\n".join(lines)


# --- satu run (beberapa konfigurasi) ------------------------------------------------------


@dataclass
class SttCandidate:
    """Satu konfigurasi E-05: label, lokal/remote, objek SpeechToText, dan info run.json."""

    label: str
    local: bool
    stt: SpeechToText
    info: dict[str, Any]


def run_eval(
    items: list[SpeechItem],
    audio: dict[str, np.ndarray],
    candidates: list[SttCandidate],
    make_segmenter: Callable[[], SpeechSegmenter],
    min_speech_ms: float | None,
    run_dir: Path,
    info: dict[str, Any],
    retrieval: Callable[
        [], tuple[Callable[[str], list[str]] | None, dict[str, Sequence[str]] | None]
    ]
    | None = None,
    progress: Callable[[str], None] = print,
    loaded_modules: Callable[[], list[str]] | None = None,
    late_info: Callable[[], dict[str, Any]] | None = None,
    input_mode: str = "vad",
) -> list[Summary]:
    """Dua fase supaya waktu STT tidak terganggu retriever (Langkah 27):
    fase 1 = VAD + STT semua kandidat dan rekaman (waktu diukur, retriever/torch belum dimuat);
    fase 2 = retrieval() baru dipanggil (memuat retriever) untuk Recall@5.
    late_info: info run.json yang baru dikumpulkan setelah fase 1, misalnya lingkungan
    (collect_environment memuat torch untuk versi dan jumlah thread-nya).
    Tulis <run_dir>/<label>/ dan summary.csv."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    phase1: list[tuple[SttCandidate, list[ItemResult]]] = []
    for cand in candidates:
        progress(f"--- fase 1 (VAD + STT): {cand.label} ---")
        segmenter = make_segmenter()
        results = []
        for item in items:
            r = evaluate_item(item, audio[item.id], segmenter, cand.stt, min_speech_ms,
                              input_mode)  # fmt: skip
            results.append(r)
            progress(f"  {item.id} ({item.kind}): ucapan {r.n_utterances}, "
                     f"tersaring {list(r.filtered_by) or '-'}")  # fmt: skip
        phase1.append((cand, results))
    timing = {
        "phases": "fase 1 VAD + STT (waktu diukur) lalu fase 2 retriever untuk Recall@5",
        "retriever_loaded_during_stt": False,
        "heavy_modules_loaded_after_stt": loaded_modules() if loaded_modules else None,
    }
    if late_info is not None:
        info = {**info, **late_info()}
    search = gold = None
    if retrieval is not None:
        progress("--- fase 2: memuat retriever untuk Recall@5 ---")
        search, gold = retrieval()
    summaries: list[Summary] = []
    for cand, results in phase1:
        if search is not None and gold:
            add_retrieval(results, search, gold)
        summary = summarize(cand.label, cand.local, results)
        write_config(run_dir / cand.label, results, summary,
                     {**info, "timing": timing, "stt": cand.info})  # fmt: skip
        summaries.append(summary)
    write_summary(run_dir, summaries)
    return summaries


HEAVY_MODULES = ("torch", "sentence_transformers", "transformers")


def heavy_modules_loaded() -> list[str]:
    """Modul berat yang sudah dimuat di proses ini (bukti fase 1 tanpa torch)."""
    import sys

    return [m for m in HEAVY_MODULES if m in sys.modules]
