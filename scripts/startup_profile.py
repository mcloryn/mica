"""Profil waktu mulai aplikasi (Langkah 40): tahap per proses dari logs startup (mica.core.startup).

python scripts/startup_profile.py --label <nama> [--reps 5] [--warmup 1] [--timeout 420]
    [--config config/dev.yaml] [--out results/STARTUP] [--fake-camera] [--min-free-gb 1.0]
    [--dry-run]

Per ulangan:
1. Salinan config di folder hasil: logging.dir ke folder ulangan, dan kunci TBD (null) yang
   dibutuhkan pekerja asli diisi NILAI COBA SDD bagian 12 (dev saja; tercatat di run.json).
2. `python -m mica --config <salinan>` (check, pekerja kamera dan suara asli, pipeline asli, Edge
   kiosk) dengan MICA_STARTUP_LOG ke folder ulangan. --fake-camera: `python -m mica.webui
   --fake-workers --fake-camera` (kamera palsu, suara palsu) bila tidak ada kamera.
3. Menunggu tahap "all_ready" proses utama atau --timeout, lalu menutup jendela Edge sehingga
   aplikasi berhenti rapi (pohon proses dibunuh bila tidak berhenti dalam 30 s).
Waktu tiap tahap = monotonic tahap - monotonic saat perintah diluncurkan (jam yang sama untuk
semua proses). --warmup ulangan pertama dibuang (pemanasan cache berkas), lalu --reps ulangan.
Wajib daya AC. Memori tersedia < --min-free-gb -> ulangan dihentikan, aborted.json, kode 4.
Tidak ada gambar atau audio yang disimpan; log hanya nama tahap dan waktu.
Hasil di <out>/<tanggal-jam>-<label>/: stages.csv (semua tahap), summary.csv (median, min, maks
per tahap), report.md, run.json, rep-*/ (config, startup.jsonl, stdout/stderr aplikasi).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
import yaml

ROOT = Path(__file__).resolve().parents[1]
CLOSE_TIMEOUT_S = 30.0

# NILAI COBA SDD bagian 12 (dev dan demo saja), hanya untuk kunci yang masih null
TRIAL_VALUES: dict[str, float] = {
    "vision.dwell_s": 2.0, "vision.leave_s": 3.0, "vision.min_shoulder_ratio": 0.22,
    "vision.color.min_majority": 0.6, "vision.box_upper.top": 0.35,
    "vision.box_upper.bottom": 0.65, "vision.box_upper.side": 0.25,
    "vision.keypoint_torso.min_kp_conf": 0.5, "vision.keypoint_torso.shrink": 0.15,
    "vision.keypoint_torso.torso_aspect": 1.2, "audio.vad.threshold": 0.5,
    "audio.vad.min_silence_ms": 500, "audio.vad.min_speech_ms": 250,
    "audio.stt.no_speech_threshold": 0.6, "audio.max_utterance_s": 15,
}  # fmt: skip

# tahap tonggak untuk laporan (proses, tahap, label)
MILESTONES = (
    ("main", "check_done", "check selesai"),
    ("main", "server_started", "server Flask jalan"),
    ("main", "edge_launched", "Edge diluncurkan"),
    ("main", "ui_first_render", "UI tampil (render pertama)"),
    ("main", "pipeline_ready", "pipeline siap (jawab ketikan)"),
    ("main", "camera_ready", "kamera siap (CameraStatus ok)"),
    ("main", "audio_ready", "suara siap (AudioStatus ready)"),
    ("main", "all_ready", "semua siap"),
)
# rentang (proses, awal, akhir, label)
SPANS = (
    ("main", "pipeline_build_start", "pipeline_ready", "utama: rakit pipeline"),
    ("main", "kb_load_start", "kb_load_done", "utama: muat KB"),
    ("main", "import_torch_start", "import_torch_done", "utama: import torch"),
    ("main", "import_sentence_transformers_start", "import_sentence_transformers_done",
     "utama: import sentence_transformers"),
    ("main", "embedder_load_start", "embedder_load_done", "utama: muat BGE-M3"),
    ("main", "spawn_vision_start", "spawn_vision_done", "utama: spawn kamera"),
    ("main", "spawn_audio_start", "spawn_audio_done", "utama: spawn suara"),
    ("vision", "import_cv2_start", "import_cv2_done", "kamera: import cv2"),
    ("vision", "import_torch_start", "import_torch_done", "kamera: import torch"),
    ("vision", "import_ultralytics_start", "import_ultralytics_done", "kamera: import ultralytics"),
    ("vision", "model_load_start", "model_load_done", "kamera: muat YOLO"),
    ("vision", "model_load_done", "warmup_inference_done", "kamera: inferensi pemanasan"),
    ("vision", "camera_open_start", "camera_open_done", "kamera: buka VideoCapture"),
    ("vision", "camera_open_done", "camera_first_frame", "kamera: frame pertama"),
    ("vision", "camera_first_frame", "first_detection", "kamera: deteksi pertama"),
    ("audio", "import_faster_whisper_start", "import_faster_whisper_done",
     "suara: import faster_whisper"),
    ("audio", "import_piper_start", "import_piper_done", "suara: import piper"),
    ("audio", "import_pysilero_vad_start", "import_pysilero_vad_done", "suara: import pysilero_vad"),
    ("audio", "import_sounddevice_start", "import_sounddevice_done", "suara: import sounddevice"),
    ("audio", "stt_load_start", "stt_load_done", "suara: muat Whisper"),
    ("audio", "stt_load_done", "tts_load_done", "suara: muat Piper"),
    ("audio", "tts_load_done", "vad_load_done", "suara: muat Silero VAD"),
    ("audio", "vad_load_done", "mic_open_done", "suara: buka mikrofon"),
    ("audio", "mic_open_done", "player_open_done", "suara: buka speaker"),
)  # fmt: skip
# jendela kerja per proses untuk melihat paralel/berurutan
WINDOWS = (
    ("main", "pipeline_build_start", "pipeline_ready", "utama: pipeline"),
    ("main", "server_started", "ui_first_render", "utama: server -> UI tampil"),
    ("vision", "proc_start", "first_detection", "proses kamera"),
    ("audio", "proc_start", "player_open_done", "proses suara"),
)


def _set(raw: dict[str, Any], dotted: str, value: Any) -> bool:
    node = raw
    *parents, last = dotted.split(".")
    for key in parents:
        node = node[key]
    if node.get(last) is None:
        node[last] = value
        return True
    return False


def make_config(src: Path, out: Path) -> tuple[Path, dict[str, Any]]:
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    if raw["app"]["mode"] != "dev":
        raise SystemExit("startup_profile hanya untuk config dev (nilai coba)")
    raw["logging"]["dir"] = (out / "logs").as_posix()
    filled = {k: v for k, v in TRIAL_VALUES.items() if _set(raw, k, v)}
    path = out / "config.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path, filled


def app_command(config: Path, fake_camera: bool) -> list[str]:
    if fake_camera:
        return [sys.executable, "-m", "mica.webui", "--config", str(config), "--fake-workers",
                "--fake-camera"]  # fmt: skip
    return [sys.executable, "-m", "mica", "--config", str(config)]


def read_stages(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # baris yang sedang ditulis
    return rows


def first(rows: list[dict[str, Any]], proc: str, stage: str) -> float | None:
    return next((r["t"] for r in rows if r["proc"] == proc and r["stage"] == stage), None)


def close_app(proc: subprocess.Popen) -> str:
    """Tutup jendela Edge (anak langsung aplikasi) -> aplikasi berhenti rapi; selain itu bunuh."""
    try:
        tree = psutil.Process(proc.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        tree = []
    roots = [p for p in tree if p.name().lower() == "msedge.exe"
             and p.parent() is not None and p.parent().name().lower() != "msedge.exe"]  # fmt: skip
    for p in roots:
        try:
            p.terminate()
        except psutil.Error:
            pass
    try:
        proc.wait(timeout=CLOSE_TIMEOUT_S)
        return "rapi" if roots else "berhenti sendiri"
    except subprocess.TimeoutExpired:
        for p in reversed([psutil.Process(proc.pid), *tree]):
            try:
                p.kill()
            except psutil.Error:
                pass
        proc.wait(timeout=10)
        return "dibunuh"


def run_once(args: argparse.Namespace, out: Path, name: str) -> dict[str, Any]:
    rep_dir = out / name
    rep_dir.mkdir(parents=True)
    config, filled = make_config(args.config, rep_dir)
    log = rep_dir / "startup.jsonl"
    env = {**os.environ, "MICA_STARTUP_LOG": str(log), "MICA_STARTUP_RUN": name,
           "PYTHONIOENCODING": "utf-8"}  # fmt: skip
    cmd = app_command(config, args.fake_camera)
    from mica.eval.environment import power_status

    if (power_status() or {}).get("source") != "ac":
        raise SystemExit("BERHENTI: sumber daya bukan AC; colok charger lalu ulangi")
    with (rep_dir / "stdout.log").open("w", encoding="utf-8") as so, \
            (rep_dir / "stderr.log").open("w", encoding="utf-8") as se:  # fmt: skip
        t0 = time.monotonic()
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=so, stderr=se)
        status, lowest = "timeout", psutil.virtual_memory().available / 2**30
        deadline = t0 + args.timeout
        while time.monotonic() < deadline:
            if first(read_stages(log), "main", "all_ready") is not None:
                status = "all_ready"
                break
            free = psutil.virtual_memory().available / 2**30
            lowest = min(lowest, free)
            if free < args.min_free_gb:
                status = "memori"
                break
            if proc.poll() is not None:
                status = f"aplikasi berhenti (kode {proc.returncode})"
                break
            time.sleep(0.2)
        t_close = time.monotonic()
        closed = close_app(proc) if proc.poll() is None else "sudah berhenti"
        close_s = time.monotonic() - t_close
    rows = read_stages(log)
    for r in rows:
        r["s"] = r["t"] - t0
    with (rep_dir / "stages.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["proc", "stage", "s", "pid"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return {"name": name, "status": status, "closed": closed, "close_s": close_s,
            "lowest_free_gb": lowest,
            "filled_trial_values": filled, "command": cmd, "rows": rows}  # fmt: skip


def _stat(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"median": None, "min": None, "max": None, "n": 0}
    return {"median": statistics.median(values), "min": min(values), "max": max(values),
            "n": len(values)}  # fmt: skip


def _fmt(s: dict[str, Any]) -> str:
    if s["median"] is None:
        return "-"
    return f"{s['median']:.2f} ({s['min']:.2f}-{s['max']:.2f})"


def since(rows: list[dict[str, Any]], proc: str, stage: str) -> float | None:
    """Detik sejak peluncuran untuk tahap pertama (proc, stage)."""
    return next((r["s"] for r in rows if r["proc"] == proc and r["stage"] == stage), None)


def span(rows: list[dict[str, Any]], proc: str, a: str, b: str) -> float | None:
    sa, sb = since(rows, proc, a), since(rows, proc, b)
    return None if sa is None or sb is None else sb - sa


def summarize(runs: list[dict[str, Any]], label: str, n_expected: int) -> tuple[str, list]:
    def stat(fn: Any, *key: str) -> dict[str, Any]:
        return _stat([v for r in runs if (v := fn(r["rows"], *key)) is not None])

    lines = [f"# Waktu mulai: {label}", "",
             (f"{len(runs)} ulangan dihitung (diharapkan {n_expected}); detik sejak perintah "
              "diluncurkan, median (min-maks)."), "",
             "| tonggak | detik |", "| --- | --- |"]  # fmt: skip
    table = []
    for proc, stage, text in MILESTONES:
        s = stat(since, proc, stage)
        table.append({"kind": "tonggak", "label": text, "proc": proc, "stage": stage, **s})
        lines.append(f"| {text} | {_fmt(s)} |")
    lines += ["", "| rentang | durasi detik |", "| --- | --- |"]
    for proc, a, b, text in SPANS:
        s = stat(span, proc, a, b)
        table.append({"kind": "rentang", "label": text, "proc": proc, "stage": f"{a}->{b}", **s})
        lines.append(f"| {text} | {_fmt(s)} |")
    lines += ["", ("Jendela kerja (detik sejak peluncuran) untuk melihat paralel atau "
                   "berurutan:"), "", "| jendela | awal | akhir |", "| --- | --- | --- |"]  # fmt: skip
    for proc, a, b, text in WINDOWS:
        sa, sb = stat(since, proc, a), stat(since, proc, b)
        table.append({"kind": "jendela-awal", "label": text, "proc": proc, "stage": a, **sa})
        table.append({"kind": "jendela-akhir", "label": text, "proc": proc, "stage": b, **sb})
        lines.append(f"| {text} | {_fmt(sa)} | {_fmt(sb)} |")
    return "\n".join(lines) + "\n", table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/startup_profile.py")
    parser.add_argument("--label", required=True)
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=420.0)
    parser.add_argument("--config", type=Path, default=ROOT / "config/dev.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "results/STARTUP")
    parser.add_argument("--fake-camera", action="store_true")
    # batas pengaman, bukan nilai eksperimen: aplikasi lengkap sendiri memakai +-2 GB
    parser.add_argument("--min-free-gb", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    out = args.out / f"{stamp}-{args.label}"
    out.mkdir(parents=True, exist_ok=False)
    if args.dry_run:
        config, filled = make_config(args.config, out)
        from mica.eval.environment import power_status

        print(
            f"[dry-run] perintah: {subprocess.list2cmdline(app_command(config, args.fake_camera))}"
        )
        print(f"[dry-run] nilai coba SDD bagian 12 diisi: {filled}")
        print(f"[dry-run] daya: {(power_status() or {}).get('source')} | memori tersedia "
              f"{psutil.virtual_memory().available / 2**30:.2f} GB (batas {args.min_free_gb:g})")  # fmt: skip
        print(f"[dry-run] folder: {out} | aplikasi TIDAK dijalankan")
        return 0
    runs, aborted = [], None
    for i in range(args.warmup + args.reps):
        name = f"warmup-{i + 1}" if i < args.warmup else f"rep-{i - args.warmup + 1}"
        r = run_once(args, out, name)
        t_all = since(r["rows"], "main", "all_ready")
        print(f"{name}: {r['status']} | semua siap {t_all if t_all is None else round(t_all, 2)} s"
              f" | tutup {r['closed']} | memori terendah {r['lowest_free_gb']:.2f} GB", flush=True)  # fmt: skip
        if r["status"] != "all_ready":
            aborted = {"run": name, "status": r["status"], "closed": r["closed"]}
            break
        if i >= args.warmup:
            runs.append(r)
    with (out / "stages.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "proc", "stage", "s"])
        for r in runs:
            for row in r["rows"]:
                w.writerow([r["name"], row["proc"], row["stage"], f"{row['s']:.4f}"])
    report, table = summarize(runs, args.label, args.reps)
    with (out / "summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["kind", "label", "proc", "stage", "median", "min",
                                          "max", "n"])  # fmt: skip
        w.writeheader()
        w.writerows(table)
    if aborted is not None:
        report += f"\nDIHENTIKAN: {aborted}\n"
        (out / "aborted.json").write_text(json.dumps(aborted, ensure_ascii=False) + "\n",
                                          encoding="utf-8")  # fmt: skip
    (out / "report.md").write_text(report, encoding="utf-8")
    from mica.eval.environment import collect_environment

    info = {"label": args.label, "reps": args.reps, "warmup": args.warmup,
            "timeout_s": args.timeout, "config": args.config.as_posix(),
            "fake_camera": args.fake_camera, "trial_values_sdd_12": TRIAL_VALUES,
            "runs": [{k: v for k, v in r.items() if k != "rows"} for r in runs],
            "aborted": aborted, "environment": collect_environment()}  # fmt: skip
    (out / "run.json").write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8")  # fmt: skip
    print(report)
    print(f"tersimpan: {out}")
    if aborted is not None:
        return 4 if aborted["status"] == "memori" else 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
