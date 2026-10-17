"""CLI evaluasi (M-12). Saat ini subperintah annotate, retrieval, gate, dan generation.

python -m mica.eval annotate export --config <yaml> --dataset <jsonl> --out <pool.csv> [--force]
python -m mica.eval annotate import --dataset <jsonl> --pool <pool.csv>
python -m mica.eval retrieval --config <yaml> --dataset <jsonl> --out <folder>
    [--retrievers bm25,dense,hybrid] [--pool <pool.csv>]
python -m mica.eval gate --config <yaml> --dataset <jsonl> --out <folder>
python -m mica.eval generation --config <yaml> --dataset <jsonl> --out <folder> [--gate-off]
    [--no-cache] [--cache-only] [--cache-dir data/cache/llm] [--env-file .env]
    [--model penyedia:id_model] [--experiment E-02]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mica.config import ConfigError, load_settings
from mica.eval.annotate import POOL_DEPTH, export_pool, import_pool
from mica.eval.dataset import DatasetError
from mica.eval.environment import collect_environment, dirty_warning, git_commit, git_dirty
from mica.eval.gate import GROUPS, group_stats, run_gate
from mica.eval.generation import (
    DEFAULT_CACHE_DIR,
    EXPERIMENT,
    SWEEP_COLUMNS,
    CacheMiss,
    run_generation,
)
from mica.eval.retrieval import MAIN_GROUP, run_retrieval, sha256_file
from mica.kb.index import DEFAULT_KB_ROOT, KbLoadError, load_kb
from mica.rag.retriever import EmbedderFactory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mica.eval")
    parser.add_argument("--kb-root", type=Path, default=DEFAULT_KB_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    annotate = sub.add_parser("annotate", help="anotasi relevansi chunk")
    annotate_sub = annotate.add_subparsers(dest="action", required=True)

    exp = annotate_sub.add_parser("export", help="buat pool kandidat untuk dianotasi")
    exp.add_argument("--config", type=Path, required=True)
    exp.add_argument("--dataset", type=Path, required=True)
    exp.add_argument("--out", type=Path, required=True)
    exp.add_argument("--force", action="store_true", help="timpa pool yang sudah ada")

    imp = annotate_sub.add_parser("import", help="isi gold_chunk_ids dari pool beranotasi")
    imp.add_argument("--dataset", type=Path, required=True)
    imp.add_argument("--pool", type=Path, required=True)

    ret = sub.add_parser("retrieval", help="E-01: Recall@5, MRR, nDCG@10, latensi")
    ret.add_argument("--config", type=Path, required=True)
    ret.add_argument("--dataset", type=Path, required=True)
    ret.add_argument("--out", type=Path, required=True)
    ret.add_argument(
        "--retrievers",
        type=_retriever_list,
        help="daftar dipisah koma, misalnya bm25,dense,hybrid (default: rag.retriever)",
    )
    ret.add_argument("--pool", type=Path, help="default: pool.csv di folder dataset")

    gate = sub.add_parser("gate", help="E-02: skor gerbang M-04 dan sweep ambang")
    gate.add_argument("--config", type=Path, required=True)
    gate.add_argument("--dataset", type=Path, required=True)
    gate.add_argument("--out", type=Path, required=True)

    gen = sub.add_parser("generation", help="E-02: jawaban per pertanyaan dan sweep offline")
    gen.add_argument("--config", type=Path, required=True)
    gen.add_argument("--dataset", type=Path, required=True)
    gen.add_argument("--out", type=Path, required=True)
    gen.add_argument(
        "--gate-off", action="store_true", help="rag.gate.threshold = null untuk run ini"
    )
    gen.add_argument("--no-cache", action="store_true", help="jangan baca cache; panggil ulang LLM")
    gen.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    gen.add_argument(
        "--cache-only",
        action="store_true",
        help="jangan pernah memanggil API; berhenti bila ada respons yang tidak ada di cache",
    )
    gen.add_argument("--env-file", type=Path, default=Path(".env"))
    gen.add_argument(
        "--model",
        help="ganti llm.chain menjadi satu model ini saja untuk run ini, misalnya "
        "groq:openai/gpt-oss-20b",
    )
    gen.add_argument(
        "--experiment",
        default=EXPERIMENT,
        help="label eksperimen di run.json dan nama folder run (default E-02)",
    )

    cp = sub.add_parser("copy", help="E-03: coverage dan density (Grusky dkk. 2018)")
    cp.add_argument("--config", type=Path, required=True)
    cp.add_argument("--runs", type=Path, nargs="+", required=True, help="folder run generation")
    cp.add_argument("--out", type=Path, default=Path("results/E-03"))
    cp.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    cp.add_argument("--env-file", type=Path, default=Path(".env"))

    from mica.audio.__main__ import add_trial_args

    stt = sub.add_parser("stt", help="E-05: WER, CER, waktu sampai teks, transkripsi palsu")
    stt.add_argument("--config", type=Path, required=True)
    stt.add_argument("--dataset", type=Path, required=True, help="manifest.jsonl rekaman")
    stt.add_argument("--out", type=Path, default=Path("results/E-05"))
    stt.add_argument("--run-name", help="nama folder run (default: cap waktu)")
    stt.add_argument("--backend", choices=("faster_whisper", "groq"), default="faster_whisper")
    stt.add_argument("--threads", type=_threads_list,
                     help="daftar thread dipisah koma, satu konfigurasi per nilai "
                          "(default audio.stt.threads)")  # fmt: skip
    stt.add_argument("--hotwords", type=Path, help="file kosakata, satu istilah per baris")
    stt.add_argument("--groq-model", help="wajib untuk --backend groq (dokumentasi Groq)")
    stt.add_argument("--questions", type=Path, default=Path("data/eval/questions.jsonl"),
                     help="gold_chunk_ids untuk Recall@5 (rekaman ber-qid)")  # fmt: skip
    stt.add_argument("--whisper-dir", type=Path, default=Path("models/whisper"))
    stt.add_argument("--env-file", type=Path, default=Path(".env"))
    stt.add_argument("--note", help="catatan di run.json, mis. 'sintetis, bukan hasil E-05'")
    add_trial_args(stt)
    return parser


def _threads_list(value: str) -> list[int]:
    try:
        threads = [int(v) for v in value.split(",") if v.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(f"thread harus bilangan bulat: {value!r}") from None
    if not threads or any(t <= 0 for t in threads):
        raise argparse.ArgumentTypeError(f"thread harus > 0: {value!r}")
    return list(dict.fromkeys(threads))


def _retriever_list(value: str) -> list[str]:
    kinds = [v.strip() for v in value.split(",") if v.strip()]
    unknown = [k for k in kinds if k not in ("bm25", "dense", "hybrid")]
    if not kinds or unknown:
        raise argparse.ArgumentTypeError(f"retriever tidak dikenal: {unknown or value!r}")
    return list(dict.fromkeys(kinds))


def cmd_export(args: argparse.Namespace, embedder_factory: EmbedderFactory | None) -> int:
    settings = load_settings(args.config)
    kb = load_kb(settings.kb.active_id, args.kb_root)
    result = export_pool(
        settings, kb, args.dataset, args.out, embedder_factory=embedder_factory, force=args.force
    )
    average = result.rows / result.questions if result.questions else 0.0
    print(
        f"KB {kb.kb_id}: {result.questions} pertanyaan, {result.rows} baris pool, "
        f"rata-rata {average:.1f} kandidat per pertanyaan (kedalaman {POOL_DEPTH}) -> {args.out}"
    )
    if result.unmatched_gold_refs:
        print("peringatan: gold_refs tanpa chunk yang cocok:")
        for item in result.unmatched_gold_refs:
            print(f"  {item}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    gold = import_pool(args.dataset, args.pool)
    total = sum(len(ids) for ids in gold.values())
    print(f"{len(gold)} pertanyaan diperbarui, {total} chunk relevan -> {args.dataset}")
    return 0


def cmd_retrieval(args: argparse.Namespace, embedder_factory: EmbedderFactory | None) -> int:
    settings = load_settings(args.config)
    kb = load_kb(settings.kb.active_id, args.kb_root)
    retrievers = args.retrievers or [settings.rag.retriever]
    pool = args.pool or args.dataset.parent / "pool.csv"
    embedder = None
    if embedder_factory is not None:
        info = kb.manifest["embedder"]
        embedder = embedder_factory(info["model"], info["revision"])
    environment = collect_environment()
    warning = dirty_warning(environment)
    if warning:
        print(warning, file=sys.stderr)
    runs, summary = run_retrieval(
        settings,
        kb,
        args.dataset,
        pool,
        args.out,
        retrievers,
        embedder=embedder,
        environment=environment,
    )
    print(f"KB {kb.kb_id} | split dev | {len(runs)} run -> {summary}")
    print("retriever | Recall@5 | MRR | nDCG@10 | p50 ms | p95 ms | unjudged")
    for run in runs:
        m = run.metrics[MAIN_GROUP]
        print(
            f"{run.retriever} | {m['recall@5']:.4f} | {m['mrr@10']:.4f} | {m['ndcg@10']:.4f} | "
            f"{m['latency_p50_ms']:.2f} | {m['latency_p95_ms']:.2f} | {m['unjudged']}"
        )
    return 0


def cmd_gate(args: argparse.Namespace, embedder_factory: EmbedderFactory | None) -> int:
    settings = load_settings(args.config)
    kb = load_kb(settings.kb.active_id, args.kb_root)
    embedder = None
    if embedder_factory is not None:
        info = kb.manifest["embedder"]
        embedder = embedder_factory(info["model"], info["revision"])
    environment = collect_environment()
    warning = dirty_warning(environment)
    if warning:
        print(warning, file=sys.stderr)
    run_dir, scores = run_gate(
        settings, kb, args.dataset, args.out, embedder=embedder, environment=environment
    )
    print(
        f"KB {kb.kb_id} | retriever {settings.rag.retriever} | "
        f"{len(scores)} pertanyaan -> {run_dir}"
    )
    print("kelompok | n | min | median | maks")
    stats = group_stats(scores)
    for group in GROUPS:
        st = stats[group]
        if st["n"]:
            print(f"{group} | {st['n']} | {st['min']:.4f} | {st['median']:.4f} | {st['max']:.4f}")
    return 0


def cmd_generation(args: argparse.Namespace, embedder_factory: EmbedderFactory | None) -> int:
    settings = load_settings(args.config, env_file=args.env_file)
    kb = load_kb(settings.kb.active_id, args.kb_root)
    embedder = None
    if embedder_factory is not None:
        info = kb.manifest["embedder"]
        embedder = embedder_factory(info["model"], info["revision"])
    environment = collect_environment()
    warning = dirty_warning(environment)
    if warning:
        print(warning, file=sys.stderr)
    if args.model is not None:
        print(f"chain efektif: [{args.model}] (llm.chain di config diabaikan)", flush=True)
    run_dir, rows, sweep_rows = run_generation(
        settings,
        kb,
        args.dataset,
        args.out,
        gate_off=args.gate_off,
        use_cache=not args.no_cache,
        cache_dir=args.cache_dir,
        cache_only=args.cache_only,
        embedder=embedder,
        environment=environment,
        model=args.model,
        experiment=args.experiment,
    )
    print(f"KB {kb.kb_id} | {len(rows)} pertanyaan -> {run_dir}")
    print(" | ".join(SWEEP_COLUMNS))
    for row in sweep_rows:
        print(" | ".join(str(row[c]) for c in SWEEP_COLUMNS))
    return 0


class SttEvalError(Exception):
    pass


def _hotwords(path: Path | None) -> tuple[str | None, dict[str, Any] | None]:
    """Satu istilah per baris -> string dipisah koma (parameter hotwords faster-whisper)."""
    if path is None:
        return None, None
    terms = [t.strip() for t in path.read_text(encoding="utf-8").splitlines() if t.strip()]
    if not terms:
        raise SttEvalError(f"{path}: file hotwords kosong")
    return ", ".join(terms), {
        "file": path.as_posix(),
        "sha256": sha256_file(path),
        "n_terms": len(terms),
        "joined_with": ", ",
    }


def stt_candidates(args: argparse.Namespace, settings: Any, no_speech: float | None) -> list[Any]:
    from mica.audio.stt import (
        WHISPER_REPO,
        WHISPER_REVISION,
        FasterWhisperStt,
        GroqWhisperStt,
        whisper_dir,
    )
    from mica.eval.stt import SttCandidate

    hotwords, hot_info = _hotwords(args.hotwords)
    if args.backend == "groq":
        if hotwords is not None:
            raise SttEvalError("--hotwords hanya untuk faster_whisper")
        if not args.groq_model:
            raise SttEvalError("--backend groq butuh --groq-model (lihat dokumentasi Groq)")
        key = settings.api_keys.groq
        if key is None:
            raise SttEvalError("GROQ_API_KEY tidak ada di environment atau .env")
        stt = GroqWhisperStt(key.get_secret_value(), args.groq_model, no_speech)
        info = {
            "backend": "groq",
            "model": args.groq_model,
            "language": "id",
            "response_format": "verbose_json",
        }
        return [SttCandidate(f"groq-{args.groq_model}", False, stt, info)]
    cfg = settings.audio.stt
    root = whisper_dir(cfg.model, args.whisper_dir)
    out = []
    for threads in args.threads or [cfg.threads]:
        stt = FasterWhisperStt(root, cfg.compute_type, threads, no_speech, hotwords=hotwords)
        label = f"faster_whisper-{cfg.model}-t{stt.threads}" + ("-hotwords" if hotwords else "")
        info = {
            "backend": "faster_whisper",
            "model": cfg.model,
            "compute_type": cfg.compute_type,
            "hf_repo": WHISPER_REPO,
            "hf_revision": WHISPER_REVISION,
            "threads_arg": threads,
            "threads_effective": stt.threads,
            "hotwords": hot_info,
            "language": "id",
            "condition_on_previous_text": False,
            "vad_filter": False,
            "beam_size": "bawaan library",
        }
        out.append(SttCandidate(label, True, stt, info))
    return out


def _check_qids(args: argparse.Namespace, items: list[Any]) -> dict[str, Any]:
    """gold_chunk_ids per qid dari set dev; qid yang tidak dikenal ditolak (ringan, tanpa torch)."""
    from mica.eval.dataset import load_questions

    gold = {q["qid"]: q.get("gold_chunk_ids") or [] for q in load_questions(args.questions)}
    unknown = sorted({i.qid for i in items if i.qid} - set(gold))
    if unknown:
        raise SttEvalError(f"qid tidak ada di {args.questions}: {unknown}")
    return gold


def _retrieval(args: argparse.Namespace, settings: Any, items: list[Any]) -> tuple[Any, Any]:
    """Fase 2 eval stt: search(teks) -> chunk_id 5 teratas dengan retriever aktif (tanpa LLM),
    dan gold per qid. Memuat KB dan embedder (torch), jadi dipanggil setelah semua STT."""
    from mica.eval.stt import TOP_K
    from mica.rag.retriever import make_retriever

    if not any(i.qid for i in items):
        return None, None
    gold = _check_qids(args, items)
    kb = load_kb(settings.kb.active_id, args.kb_root)
    retriever = make_retriever(settings, kb)
    return (lambda text: [h.chunk.chunk_id for h in retriever.search(text, TOP_K)]), gold


def cmd_stt(
    args: argparse.Namespace,
    candidates: Callable[..., list[Any]] = stt_candidates,
    retrieval: Callable[..., tuple[Any, Any]] = _retrieval,
    prob_factory: Callable[[], Callable[..., float]] | None = None,
) -> int:
    from datetime import datetime

    from mica.audio.listen import (
        FILTER_ARGS,
        VAD_ARGS,
        make_segmenter,
        resolve_filter_values,
        resolve_vad_values,
        silero_model_name,
    )
    from mica.audio.vad import silero_prob
    from mica.eval.stt import (
        CER_NORMALIZATION,
        E05_RULE,
        EXPERIMENT,
        format_table,
        heavy_modules_loaded,
        load_manifest,
        read_wav,
        run_eval,
    )
    from mica.eval.wer import WER_NORMALIZATION
    from mica.kb.index import package_version

    settings = load_settings(args.config, env_file=args.env_file)
    if settings.app.mode != "dev":
        raise SttEvalError("eval stt hanya boleh saat app.mode: dev (ditolak di kiosk)")
    items = load_manifest(args.dataset)
    audio = {i.id: read_wav(i.file) for i in items}
    values, sources = resolve_vad_values(settings.audio, args)
    filters, filter_sources = resolve_filter_values(settings.audio, args)
    if "nilai coba" in [*sources.values(), *filter_sources.values()]:
        print("SUMBER NILAI: argumen CLI (nilai coba, bukan hasil E-05)")
    for key, _flag in VAD_ARGS:
        print(f"  audio.{key} = {values[key]} ({sources[key]})")
    for key, _flag in FILTER_ARGS:
        print(f"  audio.{key} = {filters[key]} ({filter_sources[key]})")
    cands = candidates(args, settings, filters["stt.no_speech_threshold"])
    with_qid = any(i.qid for i in items)
    if with_qid and retrieval is _retrieval:
        _check_qids(args, items)  # gagal cepat sebelum STT, tanpa memuat retriever
    # cek repo tanpa collect_environment: fungsi itu memuat torch (versi dan thread torch)
    warning = dirty_warning({"git_dirty": git_dirty(), "git_commit": git_commit()})
    if warning:
        print(warning, file=sys.stderr)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.out) / (args.run_name or stamp)
    kinds = {k: sum(i.kind == k for i in items) for k in ("pertanyaan", "diam", "bising")}
    info = {
        "experiment": EXPERIMENT,
        "note": args.note,
        "dataset": {
            "manifest": args.dataset.as_posix(),
            "sha256": sha256_file(args.dataset),
            "audio_sha256": {i.id: sha256_file(i.file) for i in items},
            "counts": kinds,
            "speakers": sorted({i.speaker for i in items}),
        },
        "vad": {"silero_model": silero_model_name(), "values": values, "sources": sources},
        "filters": {"values": filters, "sources": filter_sources},
        "end_of_file": "diam sepanjang min_silence_ms ditambahkan agar VAD menutup ucapan",
        "wer_normalization": WER_NORMALIZATION,
        "cer_normalization": CER_NORMALIZATION,
        "retrieval": None
        if not with_qid
        else {
            "retriever": settings.rag.retriever,
            "kb_id": settings.kb.active_id,
            "embedder": settings.kb.embedder.model,
            "embedder_revision": settings.kb.embedder.revision,
            "k": 5,
            "questions": args.questions.as_posix(),
        },
        "rule": E05_RULE,
        "packages": {
            name: package_version(name)
            for name in (
                "faster-whisper",
                "ctranslate2",
                "pysilero-vad",
                "jiwer",
                "httpx",
                "piper-tts",
            )
        },
        "started_at": stamp,
    }
    summaries = run_eval(
        items,
        audio,
        cands,
        lambda: make_segmenter(values, prob_factory or silero_prob),
        filters["vad.min_speech_ms"],
        run_dir,
        info,
        retrieval=(lambda: retrieval(args, settings, items)) if with_qid else None,
        loaded_modules=heavy_modules_loaded,
        late_info=lambda: {"environment": collect_environment()},
    )
    print(format_table(summaries))
    print(f"tersimpan: {run_dir.as_posix()}")
    return 0


def cmd_copy(args: argparse.Namespace, embedder_factory: EmbedderFactory | None = None) -> int:
    """Tingkat salin per model dari run generation yang sudah ada; tanpa panggilan LLM."""
    from datetime import datetime

    from mica.eval.copy_rate import (
        COUNTED_STATUSES,
        EXPERIMENT,
        TOKENIZATION,
        load_run,
        score_items,
        summary_rows,
        top_density,
        top_density_masked,
        write_outputs,
    )
    from mica.rag.retriever import embedder_for_kb

    settings = load_settings(args.config, env_file=args.env_file)
    kb = load_kb(settings.kb.active_id, args.kb_root)
    info = kb.manifest["embedder"]
    embedder = (embedder_factory(info["model"], info["revision"]) if embedder_factory
                else embedder_for_kb(kb))  # fmt: skip
    texts = {c.chunk_id: c.text for c in kb.chunks}
    environment = collect_environment()
    warning = dirty_warning(environment)
    if warning:
        print(warning, file=sys.stderr)
    scored_all, summaries, sources, examples, examples_masked = [], [], [], {}, {}
    for run_dir in args.runs:
        model, items, run_info = load_run(run_dir, settings, kb, args.cache_dir, embedder)
        scored, excluded = score_items(items, texts)
        run_info["n_excluded"] = excluded
        sources.append(run_info)
        scored_all += scored
        summaries += summary_rows(model, scored, excluded)
        examples[model] = top_density(scored)
        examples_masked[model] = top_density_masked(scored)
        print(f"{model}: {len(scored)} jawaban dihitung, {excluded} dikecualikan "
              f"({run_dir.name}, rekonstruksi konteks cocok dengan cache)")  # fmt: skip
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.out) / f"copy-dev-{stamp}"
    write_outputs(run_dir, scored_all, summaries, {
        "experiment": EXPERIMENT, "metric": "coverage dan density extractive fragments "
        "(Grusky dkk. 2018 [43]; Ladhak dkk. 2022 [42])", "tokenization": TOKENIZATION,
        "counted_llm_status": list(COUNTED_STATUSES),
        "sources": {"kutip": "potongan di citations jawaban",
                    "konteks": "semua potongan yang dikirim ke LLM (top-k retriever)"},
        "boundary": "potongan digabung dengan pemisah yang tidak pernah cocok",
        "kb_id": kb.kb_id, "source_runs": sources, "environment": environment,
        "threshold": "tidak ada ambang bagus/buruk",
        "companion_metric": "coverage/density tanpa entitas (SDD 9.5): token dari span email, "
        "URL (http://, https://, www.), atau kata berdigit tidak boleh masuk fragmen; penyebut "
        "|S| - |E|; |S| - |E| = 0 -> kosong, dikeluarkan dari rata-rata. Nama tidak di-mask.",
    })  # fmt: skip
    print("model | sumber | n | coverage mean/median/p90 | density mean/median/p90")
    for r in summaries:
        print(f"{r['model']} | {r['sumber']} | {r['n']} | {r['coverage_mean']}/"
              f"{r['coverage_median']}/{r['coverage_p90']} | {r['density_mean']}/"
              f"{r['density_median']}/{r['density_p90']}")  # fmt: skip
    for model, lines in examples.items():
        print(f"density kutip tertinggi, {model}:")
        for line in lines:
            print(f"  {line}")
    print("model | sumber | n | kosong | coverage_tanpa_entitas mean | density_tanpa_entitas mean")
    for r in summaries:
        print(f"{r['model']} | {r['sumber']} | {r['n_tanpa_entitas']} | "
              f"{r['n_kosong_tanpa_entitas']} | {r['coverage_tanpa_entitas_mean']} | "
              f"{r['density_tanpa_entitas_mean']}")  # fmt: skip
    for model, lines in examples_masked.items():
        print(f"density_tanpa_entitas kutip tertinggi, {model}:")
        for line in lines:
            print(f"  {line}")
    print(f"tersimpan: {run_dir.as_posix()}")
    return 0


def main(argv: list[str] | None = None, embedder_factory: EmbedderFactory | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    from mica.audio.listen import ListenError
    from mica.audio.stt import SttModelMissing
    from mica.eval.copy_rate import RunMismatch
    from mica.eval.stt import ManifestError

    try:
        if args.command == "stt":
            return cmd_stt(args)
        if args.command == "copy":
            return cmd_copy(args, embedder_factory)
        if args.command == "retrieval":
            return cmd_retrieval(args, embedder_factory)
        if args.command == "gate":
            return cmd_gate(args, embedder_factory)
        if args.command == "generation":
            return cmd_generation(args, embedder_factory)
        if args.action == "export":
            return cmd_export(args, embedder_factory)
        return cmd_import(args)
    except (ConfigError, KbLoadError, DatasetError, FileExistsError, ValueError, CacheMiss,
            SttEvalError, ManifestError, ListenError, SttModelMissing, RunMismatch,
            KeyError) as exc:  # fmt: skip
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
