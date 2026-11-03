"""M-12: python -m mica.eval stt-sweep (E-05, docs/AMANDEMEN-2026-11-03.md bagian A).

Sweep penyaring suara push-to-talk pada backend STT pemenang E-05:
- A1: audio.vad.threshold x audio.vad.min_speech_ms x audio.stt.no_speech_threshold (27).
  STT dijalankan sekali per rekaman per vad.threshold (3 kali), karena threshold mengubah audio
  yang dipangkas (push_to_talk_utterance). STT dibuat TANPA penyaring no_speech; min_speech_ms
  dan no_speech_threshold diterapkan offline atas observasi yang disimpan (observations.jsonl:
  speech_s VAD dan no_speech_prob segmen), dengan fungsi yang sama dengan proses suara
  (is_too_short, is_no_speech). Rekaman tidak dipotong max_utterance_s di A1; batas itu dinilai
  terpisah di A2.
- A2: audio.max_utterance_s, jumlah rekaman pertanyaan yang lebih panjang dari kandidat
  (durasi WAV saja, tanpa STT).

Aturan pilih A1 (keputusan 2, leksikografis): pertanyaan asli tersaring paling sedikit ->
transkripsi palsu (diam/bising) paling sedikit -> jarak langkah grid terkecil ke bawaan library
(0,5; 250; 0,6) -> menyaring lebih sedikit (threshold lebih kecil, min_speech lebih kecil,
no_speech lebih besar). A2: terpotong paling sedikit -> paling dekat 15 -> lebih besar.
WER/CER hanya dilaporkan. Teks hipotesis hanya disimpan setelah scrub_pii dan dinormalkan
(N-09); audio tidak pernah ditulis (N-08).
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from mica.audio.stt import SegmentStats, SpeechToText, is_no_speech
from mica.audio.vad import SAMPLE_RATE, Utterance, is_too_short, push_to_talk_utterance
from mica.eval.stt import SpeechItem
from mica.eval.wer import corpus_cer, corpus_wer, normalize_for_wer
from mica.rag.pii import scrub_pii

AMENDMENT = "docs/AMANDEMEN-2026-11-03.md bagian A"
# Grid A1 (kandidat dipilih pengembang sebelum data, berpusat pada bawaan library)
THRESHOLDS = (0.3, 0.5, 0.7)
MIN_SPEECH_MS = (0.0, 250.0, 500.0)
NO_SPEECH = (0.4, 0.6, 0.8)
LIBRARY_DEFAULTS = (0.5, 250.0, 0.6)  # Silero threshold, Silero min_speech, Whisper no_speech
# Grid A2
MAX_UTTERANCE_S = (15.0, 20.0, 30.0)
MAX_UTTERANCE_CENTER = 15.0  # nilai coba SDD 12

GRID_FIELDS = (
    "vad_threshold", "min_speech_ms", "no_speech_threshold", "n_pertanyaan",
    "pertanyaan_tersaring", "tersaring_no_voice", "tersaring_min_speech",
    "tersaring_no_speech", "n_diam_bising", "transkripsi_palsu", "jarak_bawaan",
    "wer_total", "cer_total", "pemenang",
)  # fmt: skip
MAX_FIELDS = ("max_utterance_s", "n_pertanyaan", "terpotong", "jarak_15", "pemenang")


class SweepError(Exception):
    pass


# --- observasi (fase STT) ------------------------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """Satu rekaman pada satu vad.threshold; tanpa audio, hipotesis sudah disamarkan."""

    id: str
    kind: str
    threshold: float
    audio_s: float
    voice: bool  # push_to_talk_utterance menemukan ucapan
    text_ok: bool  # Transcript.ok STT tanpa penyaring (definisi transkripsi palsu E-05)
    speech_s: float | None
    no_speech_probs: tuple[float, ...]
    avg_logprobs: tuple[float, ...]
    hypothesis_norm: str  # normalize_for_wer(scrub_pii(teks STT)), "" bila tidak ada
    stt_s: float | None


def observe(
    items: Sequence[SpeechItem],
    audio: dict[str, np.ndarray],
    stt: SpeechToText,
    prob: Callable[[np.ndarray], float],
    thresholds: Sequence[float] = THRESHOLDS,
    progress: Callable[[str], None] = print,
) -> list[Observation]:
    """VAD push-to-talk + STT (tanpa penyaring no_speech) per threshold dan rekaman."""
    out: list[Observation] = []
    for threshold in thresholds:
        progress(f"--- vad.threshold {threshold} ---")
        for item in items:
            pcm = np.asarray(audio[item.id], dtype=np.int16)
            audio_s = len(pcm) / SAMPLE_RATE
            utt = push_to_talk_utterance(pcm, prob, threshold)
            if utt is None:
                out.append(Observation(item.id, item.kind, threshold, audio_s, False, False,
                                       None, (), (), "", None))  # fmt: skip
                progress(f"  {item.id} ({item.kind}): tanpa ucapan")
                continue
            t = stt.transcribe(utt.pcm16k)
            segments = list(getattr(stt, "last_segments", None) or [])
            text = t.text if t.ok else ""
            out.append(Observation(
                item.id, item.kind, threshold, audio_s, True, bool(t.ok), utt.speech_s,
                tuple(float(s.no_speech_prob) for s in segments),
                tuple(float(s.avg_logprob) for s in segments),
                normalize_for_wer(scrub_pii(text)), t.stt_s,
            ))  # fmt: skip
            progress(f"  {item.id} ({item.kind}): ucapan {utt.speech_s:.2f} s, STT dipanggil")
    return out


def write_observations(path: Path, observations: Sequence[Observation]) -> None:
    with Path(path).open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(asdict(o), ensure_ascii=False) + "\n" for o in observations)


def read_observations(path: Path) -> list[Observation]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            row["no_speech_probs"] = tuple(row["no_speech_probs"])
            row["avg_logprobs"] = tuple(row["avg_logprobs"])
            out.append(Observation(**row))
    return out


# --- A1: grid penyaring (offline) ----------------------------------------------------------


def filter_reason(o: Observation, min_speech_ms: float, no_speech: float) -> str | None:
    """Penyaring yang membuang rekaman ini, urutan sama dengan proses suara push-to-talk
    (worker._transcribe_hold): no_voice -> min_speech (sebelum STT) -> no_speech (di STT)."""
    if not o.voice:
        return "no_voice"
    utt = Utterance(np.zeros(0, dtype=np.int16), o.audio_s, False, speech_s=o.speech_s or 0.0)
    if is_too_short(utt, min_speech_ms):
        return "min_speech"
    segments = [SegmentStats(p, lp) for p, lp in zip(o.no_speech_probs, o.avg_logprobs,
                                                       strict=True)]  # fmt: skip
    if is_no_speech(segments, no_speech):
        return "no_speech"
    return None


def grid_distance(combo: tuple[float, float, float]) -> int:
    """Jumlah jarak langkah grid ke bawaan library (0,5; 250; 0,6)."""
    grids = (THRESHOLDS, MIN_SPEECH_MS, NO_SPEECH)
    return sum(abs(g.index(v) - g.index(d)) for g, v, d in zip(grids, combo, LIBRARY_DEFAULTS,
                                                               strict=True))  # fmt: skip


@dataclass
class GridRow:
    threshold: float
    min_speech_ms: float
    no_speech: float
    n_questions: int
    filtered: dict[str, int]  # per alasan, hanya pertanyaan
    n_noise: int
    false_transcripts: int
    wer_total: float | None
    cer_total: float | None

    @property
    def combo(self) -> tuple[float, float, float]:
        return (self.threshold, self.min_speech_ms, self.no_speech)

    @property
    def questions_filtered(self) -> int:
        return sum(self.filtered.values())

    def sort_key(self) -> tuple[Any, ...]:
        """Aturan A1 leksikografis; nilai terkecil menang."""
        return (self.questions_filtered, self.false_transcripts, grid_distance(self.combo),
                self.threshold, self.min_speech_ms, -self.no_speech)  # fmt: skip


def evaluate_grid(
    observations: Sequence[Observation],
    references: dict[str, str],
) -> list[GridRow]:
    by_threshold: dict[float, list[Observation]] = {}
    for o in observations:
        by_threshold.setdefault(o.threshold, []).append(o)
    missing = [t for t in THRESHOLDS if t not in by_threshold]
    if missing:
        raise SweepError(f"observasi tidak memuat vad.threshold {missing}")
    rows = []
    for threshold in THRESHOLDS:
        obs = by_threshold[threshold]
        questions = [o for o in obs if o.kind == "pertanyaan"]
        noise = [o for o in obs if o.kind != "pertanyaan"]
        for min_speech in MIN_SPEECH_MS:
            for no_speech in NO_SPEECH:
                filtered = {"no_voice": 0, "min_speech": 0, "no_speech": 0}
                hyps = []
                for o in questions:
                    reason = filter_reason(o, min_speech, no_speech)
                    if reason is not None:
                        filtered[reason] += 1
                    hyps.append("" if reason is not None else o.hypothesis_norm)
                false = sum(1 for o in noise
                            if filter_reason(o, min_speech, no_speech) is None
                            and o.text_ok)  # fmt: skip
                refs = [references[o.id] for o in questions]
                rows.append(GridRow(
                    threshold, min_speech, no_speech, len(questions), filtered, len(noise),
                    false, corpus_wer(refs, hyps) if questions else None,
                    corpus_cer(refs, hyps) if questions else None,
                ))  # fmt: skip
    return rows


def choose(rows: Sequence[GridRow]) -> GridRow:
    return min(rows, key=lambda r: r.sort_key())


# --- A2: max_utterance_s -------------------------------------------------------------------


@dataclass
class MaxRow:
    max_utterance_s: float
    n_questions: int
    cut: int

    def sort_key(self) -> tuple[Any, ...]:
        center = MAX_UTTERANCE_S.index(MAX_UTTERANCE_CENTER)
        return (self.cut, abs(MAX_UTTERANCE_S.index(self.max_utterance_s) - center),
                -self.max_utterance_s)  # fmt: skip


def evaluate_max_utterance(durations: dict[str, float], kinds: dict[str, str]) -> list[MaxRow]:
    questions = [durations[i] for i, k in kinds.items() if k == "pertanyaan"]
    return [MaxRow(c, len(questions), sum(d > c for d in questions)) for c in MAX_UTTERANCE_S]


def choose_max(rows: Sequence[MaxRow]) -> MaxRow:
    return min(rows, key=lambda r: r.sort_key())


# --- keluaran -----------------------------------------------------------------------------


def _f(x: float | None) -> str:
    return "" if x is None else f"{x:.4f}"


def grid_row(r: GridRow, winner: GridRow) -> dict[str, Any]:
    return {
        "vad_threshold": r.threshold, "min_speech_ms": r.min_speech_ms,
        "no_speech_threshold": r.no_speech, "n_pertanyaan": r.n_questions,
        "pertanyaan_tersaring": r.questions_filtered,
        "tersaring_no_voice": r.filtered["no_voice"],
        "tersaring_min_speech": r.filtered["min_speech"],
        "tersaring_no_speech": r.filtered["no_speech"], "n_diam_bising": r.n_noise,
        "transkripsi_palsu": r.false_transcripts, "jarak_bawaan": grid_distance(r.combo),
        "wer_total": _f(r.wer_total), "cer_total": _f(r.cer_total),
        "pemenang": int(r is winner),
    }  # fmt: skip


def format_verdict(winner: GridRow, n_grid: int, max_winner: MaxRow) -> str:
    lines = [
        "# E-05 sweep penyaring push-to-talk (verdict)",
        "",
        f"Aturan: {AMENDMENT}. Kombinasi A1: {n_grid}. Pemenang dipilih mekanis.",
        "",
        "## A1",
        "",
        f"- audio.vad.threshold = {winner.threshold}",
        f"- audio.vad.min_speech_ms = {winner.min_speech_ms:g}",
        f"- audio.stt.no_speech_threshold = {winner.no_speech}",
        (
            f"- pertanyaan asli tersaring pada pemenang: {winner.questions_filtered} dari "
            f"{winner.n_questions} (no_voice {winner.filtered['no_voice']}, min_speech "
            f"{winner.filtered['min_speech']}, no_speech {winner.filtered['no_speech']})"
        ),
        f"- transkripsi palsu (diam/bising): {winner.false_transcripts} dari {winner.n_noise}",
        f"- jarak langkah ke bawaan library: {grid_distance(winner.combo)}",
        f"- WER total (dilaporkan, tidak menentukan): {_f(winner.wer_total) or '-'}",
        "",
        "## A2",
        "",
        f"- audio.max_utterance_s = {max_winner.max_utterance_s:g}",
        f"- pertanyaan terpotong pada pemenang: {max_winner.cut} dari {max_winner.n_questions}",
    ]
    return "\n".join(lines) + "\n"


def analyze(
    observations: Sequence[Observation],
    items: Sequence[SpeechItem],
    run_dir: Path,
    info: dict[str, Any],
) -> tuple[GridRow, MaxRow]:
    """Hitung A1 dan A2 dari observasi tersimpan; tulis grid.csv, max_utterance.csv,
    verdict.md, run.json."""
    references = {i.id: i.reference or "" for i in items if i.kind == "pertanyaan"}
    known = {i.id for i in items}
    unknown = sorted({o.id for o in observations} - known)
    if unknown:
        raise SweepError(f"observasi memuat id yang tidak ada di manifest: {unknown}")
    rows = evaluate_grid(observations, references)
    winner = choose(rows)
    first = {o.id: o for o in observations if o.threshold == THRESHOLDS[0]}
    max_rows = evaluate_max_utterance({k: o.audio_s for k, o in first.items()},
                                      {i.id: i.kind for i in items})  # fmt: skip
    max_winner = choose_max(max_rows)
    run_dir = Path(run_dir)
    with (run_dir / "grid.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=GRID_FIELDS)
        writer.writeheader()
        writer.writerows(grid_row(r, winner) for r in rows)
    with (run_dir / "max_utterance.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MAX_FIELDS)
        writer.writeheader()
        center = MAX_UTTERANCE_S.index(MAX_UTTERANCE_CENTER)
        writer.writerows({
            "max_utterance_s": r.max_utterance_s, "n_pertanyaan": r.n_questions,
            "terpotong": r.cut, "jarak_15": abs(MAX_UTTERANCE_S.index(r.max_utterance_s) - center),
            "pemenang": int(r is max_winner)} for r in max_rows)  # fmt: skip
    verdict = format_verdict(winner, len(rows), max_winner)
    (run_dir / "verdict.md").write_text(verdict, encoding="utf-8")
    run_info = {
        **info,
        "amendment": AMENDMENT,
        "grid": {"vad.threshold": THRESHOLDS, "vad.min_speech_ms": MIN_SPEECH_MS,
                 "stt.no_speech_threshold": NO_SPEECH, "max_utterance_s": MAX_UTTERANCE_S},
        "library_defaults": LIBRARY_DEFAULTS,
        "winner": {"vad.threshold": winner.threshold, "vad.min_speech_ms": winner.min_speech_ms,
                   "stt.no_speech_threshold": winner.no_speech,
                   "questions_filtered": winner.questions_filtered,
                   "false_transcripts": winner.false_transcripts,
                   "max_utterance_s": max_winner.max_utterance_s,
                   "questions_cut": max_winner.cut},
    }  # fmt: skip
    (run_dir / "run.json").write_text(json.dumps(run_info, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")  # fmt: skip
    return winner, max_winner


def run_sweep(
    items: Sequence[SpeechItem],
    audio: dict[str, np.ndarray],
    stt: SpeechToText,
    prob: Callable[[np.ndarray], float],
    run_dir: Path,
    info: dict[str, Any] | Callable[[], dict[str, Any]],
    progress: Callable[[str], None] = print,
) -> tuple[GridRow, MaxRow]:
    """Fase STT -> observations.jsonl -> analisis offline dari file itu."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    observations = observe(items, audio, stt, prob, progress=progress)
    path = run_dir / "observations.jsonl"
    write_observations(path, observations)
    return analyze(read_observations(path), items, run_dir, info() if callable(info) else info)
