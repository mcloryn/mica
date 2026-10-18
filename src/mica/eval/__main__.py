"""CLI evaluasi (M-12). Saat ini subperintah annotate, retrieval, gate, dan generation.

python -m mica.eval annotate export --config <yaml> --dataset <jsonl> --out <pool.csv> [--force]
python -m mica.eval annotate import --dataset <jsonl> --pool <pool.csv>
python -m mica.eval retrieval --config <yaml> --dataset <jsonl> --out <folder>
    [--retrievers bm25,dense,hybrid] [--pool <pool.csv>]
python -m mica.eval gate --config <yaml> --dataset <jsonl> --out <folder>
python -m mica.eval generation --config <yaml> --dataset <jsonl> --out <folder> [--gate-off]
    [--no-cache] [--cache-only] [--cache-dir data/cache/llm] [--env-file .env]
    [--model penyedia:id_model] [--experiment E-02]
python -m mica.eval dataset split --input <file resmi> --out-dir data/eval/official/
python -m mica.eval dataset lock --dataset data/eval/official/test.jsonl --reason "<teks>"
python -m mica.eval dataset status          (set resmi, docs/DATASET.md)
python -m mica.eval latency --logs logs/ --label <label> [--resources <csv>] [--from --to]
    [--out results/E-09] [--tool-test]   (E-09, lihat mica/eval/latency.py)
python -m mica.eval vision --config <yaml> --dataset data/eval/vision/<nama>
    [--models yolo26n,yolo26n-pose] [--conf 0.1,0.25,0.5] [--out results/E-07]   (docs/E-07.md)
python -m mica.eval vision-scenarios --config <yaml> --dataset data/eval/vision_scenarios/<nama>
    --model <pemenang> [--conf <terpilih>] [--grid default] [--out results/E-07]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import date
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
    PROMPT_VARIANTS,
    SWEEP_COLUMNS,
    CacheMiss,
    run_generation,
)
from mica.eval.official import (
    DEFAULT_LOCK,
    OFFICIAL_DIR,
    SPLITS,
    OfficialDatasetError,
    SplitRefused,
    check_split,
)
from mica.eval.retrieval import MAIN_GROUP, run_retrieval, sha256_file
from mica.kb.index import DEFAULT_KB_ROOT, KbLoadError, load_kb
from mica.rag.retriever import EmbedderFactory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mica.eval")
    parser.add_argument("--kb-root", type=Path, default=DEFAULT_KB_ROOT)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    ds = sub.add_parser("dataset", help="set resmi: split, lock, status (docs/DATASET.md)")
    ds_sub = ds.add_subparsers(dest="action", required=True)
    ds_split = ds_sub.add_parser("split", help="bagi set resmi 30/70 berstrata (sekali saja)")
    ds_split.add_argument("--input", type=Path, required=True)
    ds_split.add_argument("--out-dir", type=Path, default=OFFICIAL_DIR)
    ds_lock = ds_sub.add_parser("lock", help="kunci set uji (versi baru di data/eval/LOCK)")
    ds_lock.add_argument("--dataset", type=Path, required=True)
    ds_lock.add_argument("--reason", required=True)
    ds_status = ds_sub.add_parser("status", help="versi kunci dan kecocokan hash")
    ds_status.add_argument("--official-dir", type=Path, default=OFFICIAL_DIR)

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
    ret.add_argument("--split", choices=SPLITS, default="dev",
                     help="dev (bawaan) atau test (butuh LOCK cocok dan KB official)")  # fmt: skip

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
    gen.add_argument("--split", choices=SPLITS, default="dev",
                     help="dev (bawaan) atau test (butuh LOCK cocok dan KB official)")  # fmt: skip
    gen.add_argument("--prompt-variant", choices=PROMPT_VARIANTS,
                     help="menimpa rag.prompt_variant untuk run ini (tercatat di run.json)")  # fmt: skip

    cp = sub.add_parser("copy", help="E-03: coverage dan density (Grusky dkk. 2018)")
    cp.add_argument("--config", type=Path, required=True)
    cp.add_argument("--runs", type=Path, nargs="+", required=True, help="folder run generation")
    cp.add_argument("--out", type=Path, default=Path("results/E-03"))
    cp.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    cp.add_argument("--split", choices=SPLITS, default="dev",
                     help="dev (bawaan) atau test (butuh LOCK cocok dan KB official)")  # fmt: skip
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
    stt.add_argument("--groq-model", help="menimpa audio.stt.groq_model (untuk --backend groq)")
    stt.add_argument("--questions", type=Path, default=Path("data/eval/questions.jsonl"),
                     help="gold_chunk_ids untuk Recall@5 (rekaman ber-qid)")  # fmt: skip
    stt.add_argument("--whisper-dir", type=Path, default=Path("models/whisper"))
    stt.add_argument("--env-file", type=Path, default=Path(".env"))
    stt.add_argument("--note", help="catatan di run.json, mis. 'sintetis, bukan hasil E-05'")
    stt.add_argument("--split", choices=SPLITS, default="dev",
                     help="dev (bawaan) atau test (butuh LOCK cocok dan KB official)")  # fmt: skip
    add_trial_args(stt)

    lat = sub.add_parser("latency", help="E-09: latensi per tahap dari log 6.2 dan verdict")
    lat.add_argument("--logs", type=Path, default=Path("logs"))
    lat.add_argument("--label", required=True, help="nama run, mis. kiosk-fps2-t1")
    lat.add_argument("--resources", type=Path, help="resources.csv dari --record-resources")
    lat.add_argument("--from", dest="start", type=date.fromisoformat, help="YYYY-MM-DD")
    lat.add_argument("--to", dest="end", type=date.fromisoformat, help="YYYY-MM-DD")
    lat.add_argument("--out", type=Path, default=Path("results/E-09"))
    lat.add_argument("--split", choices=SPLITS, default="dev",
                     help="dev (bawaan) atau test (butuh LOCK cocok dan KB official)")  # fmt: skip
    lat.add_argument("--config", type=Path, help="wajib untuk --split test (cek KB official)")
    lat.add_argument("--tool-test", action="store_true",
                     help="tandai sebagai uji alat (bukan hasil E-09) di run.json dan verdict")  # fmt: skip

    vis = sub.add_parser("vision", help="E-07: mAP, IoU, FPS deteksi orang (docs/E-07.md)")
    vis.add_argument("--config", type=Path, required=True)
    vis.add_argument("--dataset", type=Path, required=True, help="folder data/eval/vision/<nama>")
    vis.add_argument("--models", type=_name_list, default=["yolo26n", "yolo26n-pose"])
    vis.add_argument("--conf", type=_float_list, default=[0.1, 0.25, 0.5])
    vis.add_argument("--out", type=Path, default=Path("results/E-07"))
    vis.add_argument("--models-dir", type=Path, default=Path("models"))
    vis.add_argument("--note", help="catatan di run.json, mis. 'sintetis, bukan hasil E-07'")

    from mica.eval.vision_scenarios import GRIDS, MIN_KP_CONF

    scen = sub.add_parser("vision-scenarios", help="E-07: grid sapaan pada klip skenario")
    scen.add_argument("--config", type=Path, required=True)
    scen.add_argument("--dataset", type=Path, required=True,
                      help="folder data/eval/vision_scenarios/<nama>")  # fmt: skip
    scen.add_argument("--model", required=True, help="pemenang E-07 deteksi (varian -pose)")
    scen.add_argument("--conf", type=float, help="conf terpilih E-07 (default vision.conf)")
    scen.add_argument("--grid", choices=tuple(GRIDS), default="default")
    scen.add_argument("--min-kp-conf", type=float, default=MIN_KP_CONF,
                      help=f"keypoint_torso.min_kp_conf (default {MIN_KP_CONF}, docs/E-07.md)")  # fmt: skip
    scen.add_argument("--out", type=Path, default=Path("results/E-07"))
    scen.add_argument("--models-dir", type=Path, default=Path("models"))
    scen.add_argument("--note", help="catatan di run.json, mis. 'sintetis, bukan hasil E-07'")
    return parser


def cmd_dataset(args: argparse.Namespace) -> int:
    from mica.eval.official import lock_dataset, lock_status, status_lines, write_split

    if args.action == "split":
        result = write_split(args.input, args.out_dir)
        print(f"seed {result['seed']} (docs/DATASET.md) | {len(result['dev'])} dev-resmi, "
              f"{len(result['test'])} uji -> {args.out_dir.as_posix()}")  # fmt: skip
        print("strata | unit | dev unit | uji unit | dev pertanyaan | uji pertanyaan")
        for name, c in result["strata"].items():
            print(f"{name} | {c['units']} | {c['dev_units']} | {c['test_units']} | "
                  f"{c['dev_questions']} | {c['test_questions']}")  # fmt: skip
        print("langkah berikutnya: python -m mica.eval dataset lock --dataset "
              f"{(args.out_dir / 'test.jsonl').as_posix()} --reason \"<alasan>\"")  # fmt: skip
        return 0
    if args.action == "lock":
        version = lock_dataset(args.dataset, args.reason, args.lock, commit=git_commit(),
                               git_dirty=git_dirty())  # fmt: skip
        print(f"terkunci: {args.lock.as_posix()} versi {version['version']} "
              f"sha256 {version['sha256']} ({version['n_questions']} pertanyaan)")  # fmt: skip
        return 0
    for line in status_lines(lock_status(args.lock), args.official_dir):
        print(line)
    return 0


def cmd_latency(args: argparse.Namespace) -> int:
    from mica.eval.latency import run_latency

    environment = collect_environment()
    warning = dirty_warning(environment)
    if warning:
        print(warning, file=sys.stderr)
    kb_type = None
    if args.config is not None:
        from mica.kb.index import read_manifest

        settings = load_settings(args.config)
        kb_type = read_manifest(Path(args.kb_root) / settings.kb.active_id).get("source_type")
    elif args.split == "test":
        raise SplitRefused("--split test butuh --config (untuk cek KB official)")
    split_info = check_split(args.split, None, kb_type, args.lock)
    run_dir, overall = run_latency(args.logs, args.out, args.label, args.resources, args.start,
                                   args.end, args.tool_test, environment,
                                   split_info=split_info)  # fmt: skip
    print((run_dir / "verdict.md").read_text(encoding="utf-8"))
    print(f"keseluruhan: {overall}")
    print(f"tersimpan: {run_dir.as_posix()}")
    return 0


def _threads_list(value: str) -> list[int]:
    try:
        threads = [int(v) for v in value.split(",") if v.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(f"thread harus bilangan bulat: {value!r}") from None
    if not threads or any(t <= 0 for t in threads):
        raise argparse.ArgumentTypeError(f"thread harus > 0: {value!r}")
    return list(dict.fromkeys(threads))


def _name_list(value: str) -> list[str]:
    names = list(dict.fromkeys(v.strip() for v in value.split(",") if v.strip()))
    if not names:
        raise argparse.ArgumentTypeError(f"daftar kosong: {value!r}")
    return names


def _float_list(value: str) -> list[float]:
    try:
        values = [float(v) for v in value.split(",") if v.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(f"harus angka dipisah koma: {value!r}") from None
    if not values or any(not 0 < v < 1 for v in values):
        raise argparse.ArgumentTypeError(f"nilai harus di antara 0 dan 1: {value!r}")
    return sorted(set(values))


def _run_stamp() -> str:
    from datetime import datetime

    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def _vision_settings(args: argparse.Namespace, command: str) -> Any:
    """Eval vision/warna membaca frame dan klip relawan: hanya mode dev (docs/E-07.md)."""
    from mica.eval.vision import VisionEvalError

    settings = load_settings(args.config)
    if settings.app.mode != "dev":
        raise VisionEvalError(
            f"eval {command} hanya boleh saat app.mode: dev (frame relawan ditolak di mode kiosk)"
        )
    return settings


def _model_info(models_dir: Path, model: str) -> dict[str, Any]:
    from mica.vision.detector import MODEL_SHA256, YOLO_RELEASE_TAG, model_path
    from mica.vision.detector import sha256_file as model_sha

    path = model_path(model, models_dir)
    sha = model_sha(path) if path.is_file() else None
    expected = MODEL_SHA256.get(model)
    if sha is not None and expected is not None and sha != expected:
        print(f"peringatan: sha256 {path.as_posix()} tidak sama dengan rilis "
              f"{YOLO_RELEASE_TAG}", file=sys.stderr)  # fmt: skip
    return {"file": path.as_posix(), "sha256": sha, "sha256_expected": expected,
            "release_tag": YOLO_RELEASE_TAG}  # fmt: skip


def _vision_packages() -> dict[str, str | None]:
    from mica.kb.index import package_version

    return {name: package_version(name) for name in ("ultralytics", "opencv-python", "numpy")}


def cmd_vision(args: argparse.Namespace) -> int:
    from mica.eval import vision as ev
    from mica.vision.detector import model_path

    settings = _vision_settings(args, "vision")
    frames = ev.load_frames(args.dataset)
    imgsz = settings.vision.imgsz
    low = min(args.conf)
    if ev.DEFAULT_CONF not in args.conf:
        print(f"peringatan: conf {ev.DEFAULT_CONF} tidak ada di --conf; aturan model E-07 "
              "tidak bisa diterapkan", file=sys.stderr)  # fmt: skip
    for model in args.models:
        path = model_path(model, args.models_dir)
        if not path.is_file():
            from mica.vision.detector import ModelMissing

            raise ModelMissing(path)
    environment = collect_environment()
    warning = dirty_warning(environment)
    if warning:
        print(warning, file=sys.stderr)
    stamp = _run_stamp()
    run_dir = Path(args.out) / f"vision-{stamp}"
    info = {
        "note": args.note,
        "dataset": {
            "path": args.dataset.as_posix(),
            "manifest_sha256": sha256_file(args.dataset / "manifest.jsonl"),
            "n_frame": len(frames),
            "relawan": sorted({r for f in frames for r in f.relawan.split(",")} - {"-"}),
            "image_sha256": {f.id: sha256_file(f.file) for f in frames},
            "label_sha256": {f.id: sha256_file(f.label_file) for f in frames},
        },
        "models": {m: _model_info(args.models_dir, m) for m in args.models},
        "conf": args.conf,
        "imgsz": imgsz,
        "device": "cpu",
        "packages": _vision_packages(),
        "environment": environment,
        "started_at": stamp,
    }
    predictors = {
        m: (lambda m=m: ev.ultralytics_predictor(model_path(m, args.models_dir), low, imgsz))
        for m in args.models
    }
    ev.run_vision(frames, predictors, args.conf, run_dir, info)
    print((run_dir / "verdict.md").read_text(encoding="utf-8"))
    print(f"tersimpan: {run_dir.as_posix()}")
    return 0


def cmd_vision_scenarios(args: argparse.Namespace) -> int:
    from mica.eval import vision_scenarios as es
    from mica.eval.vision import VisionEvalError
    from mica.vision.detector import ModelMissing, UltralyticsDetector, model_path

    settings = _vision_settings(args, "vision-scenarios")
    if not args.model.endswith("-pose"):
        raise VisionEvalError(
            f"model {args.model} tanpa keypoint: sinyal shoulder_width butuh varian -pose; grid "
            "min_box_height_ratio belum ditetapkan (amandemen docs/E-07.md dulu)"
        )
    path = model_path(args.model, args.models_dir)
    if not path.is_file():
        raise ModelMissing(path)
    clips = es.load_clips(args.dataset)
    appearances = es.load_annotations(args.dataset / "annotations.jsonl", [c.id for c in clips])
    vision = settings.vision
    conf = args.conf if args.conf is not None else vision.conf
    environment = collect_environment()
    warning = dirty_warning(environment)
    if warning:
        print(warning, file=sys.stderr)
    stamp = _run_stamp()
    run_dir = Path(args.out) / f"vision-scenarios-{stamp}"
    info = {
        "note": args.note,
        "model": args.model,
        "conf": conf,
        "imgsz": vision.imgsz,
        "tracker": vision.tracker,
        "presence_signal": "shoulder_width",
        "model_file": _model_info(args.models_dir, args.model),
        "dataset": {
            "path": args.dataset.as_posix(),
            "manifest_sha256": sha256_file(args.dataset / "manifest.jsonl"),
            "annotations_sha256": sha256_file(args.dataset / "annotations.jsonl"),
            "clip_sha256": {c.id: sha256_file(c.file) for c in clips},
            "n_kemunculan": len(appearances),
        },
        "packages": _vision_packages(),
        "environment": environment,
        "started_at": stamp,
    }
    es.run_scenarios(
        clips, appearances,
        lambda: UltralyticsDetector(path, vision.tracker, conf, vision.imgsz),
        es.GRIDS[args.grid], vision.fps_idle, run_dir, info, min_kp_conf=args.min_kp_conf,
    )  # fmt: skip
    print((run_dir / "verdict.md").read_text(encoding="utf-8"))
    print(f"tersimpan: {run_dir.as_posix()}")
    return 0


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
    split_info = check_split(args.split, args.dataset, kb.manifest.get("source_type"), args.lock)
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
        split=args.split,
        split_info=split_info,
    )
    print(f"KB {kb.kb_id} | split {args.split} | {len(runs)} run -> {summary}")
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
    split_info = check_split(args.split, args.dataset, kb.manifest.get("source_type"), args.lock)
    embedder = None
    if embedder_factory is not None:
        info = kb.manifest["embedder"]
        embedder = embedder_factory(info["model"], info["revision"])
    environment = collect_environment()
    warning = dirty_warning(environment)
    if warning:
        print(warning, file=sys.stderr)
    if args.prompt_variant is not None:
        print(f"prompt_variant efektif: {args.prompt_variant} (config: "
              f"{settings.rag.prompt_variant})", flush=True)  # fmt: skip
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
        split=args.split,
        split_info=split_info,
        prompt_variant=args.prompt_variant,
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
        # --groq-model menimpa audio.stt.groq_model
        model = args.groq_model or settings.audio.stt.groq_model
        if not model:
            raise SttEvalError(
                "--backend groq butuh model Groq: isi audio.stt.groq_model di config atau beri "
                "--groq-model (pilihan: whisper-large-v3-turbo, whisper-large-v3)"
            )
        key = settings.api_keys.groq
        if key is None:
            raise SttEvalError("GROQ_API_KEY tidak ada di environment atau .env")
        stt = GroqWhisperStt(key.get_secret_value(), model, no_speech)
        info = {
            "backend": "groq",
            "model": model,
            "model_source": "--groq-model" if args.groq_model else "audio.stt.groq_model",
            "language": "id",
            "response_format": "verbose_json",
        }
        return [SttCandidate(f"groq-{model}", False, stt, info)]
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
    split_info = _stt_split(args, settings, with_qid)
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
        "split": args.split,
        "lock": split_info["lock"],
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


def _copy_split(args: argparse.Namespace, kb: Any) -> dict[str, Any]:
    """Run generation sumber harus ber-split sama dengan --split; test diperiksa ke LOCK."""
    import json

    info: dict[str, Any] = {"split": args.split, "lock": None}
    for run_dir in args.runs:
        run = json.loads((Path(run_dir) / "run.json").read_text(encoding="utf-8"))
        if run.get("split", "dev") != args.split:
            raise SplitRefused(f"{run_dir}: run ber-split {run.get('split', 'dev')}, "
                               f"bukan {args.split}")  # fmt: skip
        dataset = Path(run["dataset"]["path"])
        info = check_split(args.split, dataset if dataset.exists() else None,
                           kb.manifest.get("source_type"), args.lock)  # fmt: skip
        if info["lock"] is not None and run["dataset"]["sha256"] != info["lock"]["sha256"]:
            raise SplitRefused(f"{run_dir}: dataset run tidak sama dengan set uji terkunci")
    return info


def _stt_split(args: argparse.Namespace, settings: Any, with_qid: bool) -> dict[str, Any]:
    """--questions (Recall@5) adalah dataset yang diperiksa; test butuh KB official."""
    from mica.kb.index import read_manifest

    kb_type = None
    if args.split == "test":
        kb_type = read_manifest(Path(args.kb_root) / settings.kb.active_id).get("source_type")
    return check_split(args.split, args.questions if with_qid else None, kb_type, args.lock)


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
    split_info = _copy_split(args, kb)
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
    run_dir = Path(args.out) / f"copy-{args.split}-{stamp}"
    write_outputs(run_dir, scored_all, summaries, {
        "experiment": EXPERIMENT, "metric": "coverage dan density extractive fragments "
        "(Grusky dkk. 2018 [43]; Ladhak dkk. 2022 [42])", "tokenization": TOKENIZATION,
        "counted_llm_status": list(COUNTED_STATUSES),
        "sources": {"kutip": "potongan di citations jawaban",
                    "konteks": "semua potongan yang dikirim ke LLM (top-k retriever)"},
        "boundary": "potongan digabung dengan pemisah yang tidak pernah cocok",
        "kb_id": kb.kb_id, "source_runs": sources, "environment": environment,
        "split": args.split, "lock": split_info["lock"],
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
    from mica.eval.vision import VisionEvalError
    from mica.vision.detector import ModelMissing

    try:
        if args.command == "stt":
            return cmd_stt(args)
        if args.command == "vision":
            return cmd_vision(args)
        if args.command == "vision-scenarios":
            return cmd_vision_scenarios(args)
        if args.command == "latency":
            return cmd_latency(args)
        if args.command == "dataset":
            return cmd_dataset(args)
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
            KeyError, OfficialDatasetError, SplitRefused, VisionEvalError,
            ModelMissing) as exc:  # fmt: skip
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
