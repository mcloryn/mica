"""python -m mica.audio listen (dev saja): mikrofon -> SpeechSegmenter -> STT.

- Mode biasa: cetak "mendengarkan" saat SpeechStarted, lalu teks, audio_s, stt_s, dan RTF tiap
  ucapan, serta diagnosis (prob VAD maks/rata-rata, potongan >= ambang, awal sejak mic resume,
  no_speech_prob dan avg_logprob tiap segmen). Teks hanya dicetak; tidak di-log dan tidak disimpan.
- Penyaring audio.vad.min_speech_ms (sebelum STT) dan audio.stt.no_speech_threshold (sesudah STT);
  null tanpa argumen = mati. Ucapan tersaring tidak diucapkan ulang.
- --echo: MICA mengucapkan "Kamu bertanya: <teks>"; mikrofon di-pause selama bicara (K-6).
- --script --n N --out <folder>: pilot WER E-05 dengan N pertanyaan answerable pertama
  (urutan qid) dari set dev; tulis wer.csv dan run.json saja.
Audio mikrofon tidak pernah ditulis ke disk (N-08).
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mica.audio.stt import (
    WHISPER_REPO,
    WHISPER_REVISION,
    WHISPER_SHA256,
    SegmentStats,
    SpeechToText,
    Transcript,
    whisper_dir,
)
from mica.audio.vad import SpeechSegmenter, SpeechStarted, Utterance, is_too_short, silero_prob
from mica.config import AudioConfig, Settings
from mica.eval.wer import WER_NORMALIZATION, corpus_wer, normalize_for_wer, wer

DEFAULT_DATASET = Path("data/eval/questions.jsonl")  # set dev 45 pertanyaan (E-01)
VAD_ARGS = (
    ("vad.threshold", "--vad-threshold"),
    ("vad.min_silence_ms", "--min-silence-ms"),
    ("max_utterance_s", "--max-utterance-s"),
)
FILTER_ARGS = (
    ("vad.min_speech_ms", "--min-speech-ms"),
    ("stt.no_speech_threshold", "--no-speech-threshold"),
)
WER_FIELDS = (
    "qid", "referensi_norm", "hipotesis_norm", "wer", "audio_s", "stt_s", "rtf", "ulang",
    "cut_by_max",
)  # fmt: skip
ECHO_PREFIX = "Kamu bertanya: "


class ListenError(Exception):
    pass


def _config_value(audio: AudioConfig, key: str) -> Any:
    node: Any = audio
    for part in key.split("."):
        node = getattr(node, part)
    return node


def resolve_vad_values(
    audio: AudioConfig, args: argparse.Namespace
) -> tuple[dict[str, float], dict[str, str]]:
    """Argumen menimpa config; null tanpa argumen -> ListenError yang menyebut argumennya."""
    values: dict[str, float] = {}
    sources: dict[str, str] = {}
    missing = []
    for key, flag in VAD_ARGS:
        arg = getattr(args, flag[2:].replace("-", "_"))
        if arg is not None:
            values[key], sources[key] = float(arg), "nilai coba"
        elif _config_value(audio, key) is not None:
            values[key], sources[key] = float(_config_value(audio, key)), "config"
        else:
            missing.append(f"{flag} (audio.{key} null, TBD E-05)")
    if missing:
        raise ListenError("argumen kurang: " + ", ".join(missing))
    return values, sources


def resolve_filter_values(
    audio: AudioConfig, args: argparse.Namespace
) -> tuple[dict[str, float | None], dict[str, str]]:
    """Seperti resolve_vad_values, tetapi null tanpa argumen berarti penyaring mati."""
    values: dict[str, float | None] = {}
    sources: dict[str, str] = {}
    for key, flag in FILTER_ARGS:
        arg = getattr(args, flag[2:].replace("-", "_"))
        if arg is not None:
            values[key], sources[key] = float(arg), "nilai coba"
        elif _config_value(audio, key) is not None:
            values[key], sources[key] = float(_config_value(audio, key)), "config"
        else:
            values[key], sources[key] = None, "mati, null TBD E-05"
    return values, sources


def load_script_questions(path: Path, n: int) -> list[dict[str, Any]]:
    rows = [
        json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line
    ]
    answerable = sorted((r for r in rows if r["type"] == "answerable"), key=lambda r: r["qid"])
    if len(answerable) < n:
        raise ListenError(f"hanya ada {len(answerable)} pertanyaan answerable di {path}")
    return answerable[:n]


class Listener:
    def __init__(
        self,
        mic: Any,
        segmenter: SpeechSegmenter,
        stt: SpeechToText,
        out: Callable[[str], None] = print,
        min_speech_ms: float | None = None,
    ) -> None:
        self.mic = mic
        self.segmenter = segmenter
        self.stt = stt
        self.out = out
        self.min_speech_ms = min_speech_ms

    def next_utterance(self) -> Utterance | None:
        """Ucapan berikutnya; None bila mikrofon tidak memberi audio lagi."""
        while True:
            chunk = self.mic.read_chunk()
            if chunk is None:
                return None
            for event in self.segmenter.feed(chunk):
                if isinstance(event, SpeechStarted):
                    self.out("mendengarkan ...")
                elif isinstance(event, Utterance):
                    return event

    def restart(self) -> None:
        self.segmenter.reset()
        self.mic.resume()

    def transcribe(self, utterance: Utterance) -> Transcript:
        """STT dengan penyaring; min_speech dicek dulu sehingga STT tidak dipanggil."""
        if is_too_short(utterance, self.min_speech_ms):
            return Transcript("", False, 0.0, utterance.audio_s, filtered_by="min_speech")
        return self.stt.transcribe(utterance.pcm16k)

    def diagnose(self, t: Transcript, u: Utterance) -> list[str]:
        return diagnose_lines(t, u, getattr(self.stt, "last_segments", None))


def diagnose_lines(t: Transcript, u: Utterance, segments: list[SegmentStats] | None) -> list[str]:
    """Baris diagnosis untuk konsol dev saja (tanpa teks, tidak di-log)."""
    lines = [
        (
            f"    vad: prob maks {u.prob_max:.3f} | rata-rata {u.prob_mean:.3f} | "
            f"potongan >= ambang {u.n_above} | bicara_s {u.speech_s:.2f} | "
            f"sejak mic resume {u.start_s:.2f} s"
        )
    ]
    if t.filtered_by == "min_speech":
        lines.append("    whisper: dilewati")
    elif segments is not None:
        stats = "; ".join(
            f"no_speech {s.no_speech_prob:.3f} logprob {s.avg_logprob:.3f}" for s in segments
        )
        lines.append(f"    whisper: {len(segments)} segmen | {stats or '-'}")
    if t.filtered_by is not None:
        lines.append(f"    [tersaring: {t.filtered_by}]")
    return lines


def _rtf(t: Transcript) -> float:
    return t.stt_s / t.audio_s if t.audio_s > 0 else 0.0


def _describe(t: Transcript, u: Utterance) -> str:
    cut = " | dipotong max_utterance_s" if u.cut_by_max else ""
    return f"audio_s {t.audio_s:.2f} | stt_s {t.stt_s:.2f} | RTF {_rtf(t):.3f}{cut}"


def run_listen(
    listener: Listener,
    speak: Callable[[str], None] | None,
    count: int | None = None,
) -> int:
    out = listener.out
    out("siap; silakan bicara (Ctrl+C untuk berhenti)")
    heard = 0
    listener.restart()
    while count is None or heard < count:
        utterance = listener.next_utterance()
        if utterance is None:
            out("tidak ada audio dari mikrofon; berhenti")
            break
        heard += 1
        transcript = listener.transcribe(utterance)
        out(f"teks: {transcript.text if transcript.ok else '(kosong)'}")
        out(f"    {_describe(transcript, utterance)}")
        for line in listener.diagnose(transcript, utterance):
            out(line)
        if speak is not None and transcript.ok:
            listener.mic.pause()
            out("[mic pause]")
            speak(ECHO_PREFIX + transcript.text)
            listener.restart()
            out("[mic resume]")
    return heard


def run_script(
    listener: Listener,
    questions: list[dict[str, Any]],
    ask: Callable[[str], str],
) -> list[dict[str, Any]]:
    out = listener.out
    rows: list[dict[str, Any]] = []
    for i, q in enumerate(questions, start=1):
        retries = 0
        while True:
            out(f"[{i}/{len(questions)}] {q['qid']}: {q['question']}")
            out("bacakan pertanyaan di atas ...")
            listener.restart()
            utterance = listener.next_utterance()
            listener.mic.pause()
            if utterance is None:
                raise ListenError("tidak ada audio dari mikrofon")
            t = listener.transcribe(utterance)
            score = wer(q["question"], t.text)
            out(f"    hipotesis: {t.text if t.ok else '(kosong)'}")
            out(f"    WER {score:.3f} | {_describe(t, utterance)}")
            for line in listener.diagnose(t, utterance):
                out(line)
            if ask("Enter = lanjut, r = ulang > ").strip().lower() == "r":
                retries += 1
                continue
            break
        rows.append(
            {
                "qid": q["qid"],
                "referensi_norm": normalize_for_wer(q["question"]),
                "hipotesis_norm": normalize_for_wer(t.text),
                "wer": f"{score:.4f}",
                "audio_s": f"{t.audio_s:.3f}",
                "stt_s": f"{t.stt_s:.3f}",
                "rtf": f"{_rtf(t):.3f}",
                "ulang": retries,
                "cut_by_max": int(utterance.cut_by_max),
                "_reference": q["question"],
                "_hypothesis": t.text,
            }
        )
    return rows


def script_summary(rows: list[dict[str, Any]]) -> dict[str, float]:
    refs = [r["_reference"] for r in rows]
    hyps = [r["_hypothesis"] for r in rows]
    per = [float(r["wer"]) for r in rows]
    return {
        "wer_total": corpus_wer(refs, hyps),
        "wer_mean": sum(per) / len(per) if per else 0.0,
    }


def write_script_results(out_dir: Path, rows: list[dict[str, Any]], info: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "wer.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=WER_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / "run.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def run_info(
    settings: Settings,
    stt_threads: int,
    vad_values: dict[str, float],
    vad_sources: dict[str, str],
    mic_info: dict[str, Any],
    dataset: Path,
    summary: dict[str, float],
    qids: list[str],
    filter_values: dict[str, float | None] | None = None,
    filter_sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    from mica.audio.__main__ import sha256_file
    from mica.eval.environment import git_commit, git_dirty, power_plan, power_status
    from mica.kb.index import package_version

    model_dir = whisper_dir(settings.audio.stt.model)
    return {
        "experiment": "E-05",
        "component": "stt",
        "git_commit": git_commit(),
        "git_dirty": git_dirty(),
        "packages": {
            name: package_version(name)
            for name in ("faster-whisper", "ctranslate2", "pysilero-vad", "jiwer", "sounddevice")
        },
        "stt": {
            "backend": settings.audio.stt.backend,
            "model": settings.audio.stt.model,
            "compute_type": settings.audio.stt.compute_type,
            "hf_repo": WHISPER_REPO,
            "hf_revision": WHISPER_REVISION,
            "sha256": {
                name: sha256_file(model_dir / name) if (model_dir / name).is_file() else None
                for name in WHISPER_SHA256
            },
            "threads_config": settings.audio.stt.threads,
            "threads_effective": stt_threads,
            "language": "id",
            "condition_on_previous_text": False,
            "vad_filter": False,
            "beam_size": "bawaan library",
        },
        "vad": {
            "silero_model": silero_model_name(),
            "values": vad_values,
            "sources": vad_sources,
        },
        "filters": {"values": filter_values or {}, "sources": filter_sources or {}},
        "mic": mic_info,
        "dataset": {"path": dataset.as_posix(), "sha256": sha256_file(dataset), "qids": qids},
        "wer_normalization": WER_NORMALIZATION,
        **summary,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu": platform.processor(),
        "power": power_status(),
        "power_plan": power_plan(),
    }


def silero_model_name() -> str | None:
    try:
        import pysilero_vad
    except ImportError:
        return None
    return Path(pysilero_vad._DEFAULT_MODEL_PATH).name


def make_segmenter(
    values: dict[str, float], prob_factory: Callable[[], Callable[..., float]] = silero_prob
) -> SpeechSegmenter:
    return SpeechSegmenter(
        threshold=values["vad.threshold"],
        min_silence_ms=values["vad.min_silence_ms"],
        max_utterance_s=values["max_utterance_s"],
        prob=prob_factory(),
    )
