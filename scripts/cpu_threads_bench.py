"""Bench thread CPU Piper dan YOLO (docs/CPU-THREADS.md, Langkah 50); dev saja, tanpa orang.

python scripts/cpu_threads_bench.py [--config config/dev.yaml] [--out results/cpu-threads]
    [--stage 1|2|all] [--tts N|null] [--warmup-s 10] [--sentences 8]

Per kandidat: proses MICA baru di proses ini (bus + pekerja asli, kamera asli, pipeline palsu),
Edge dibuka MICA dengan pratinjau, --measure-preview aktif. Setelah halaman tampil dan
pemanasan, Piper menyusun daftar jawaban tetap (run dev E-02 120b v4, bukan set uji) satu per
satu. Hasil hanya angka: results/cpu-threads/<timestamp>/<kandidat>/{summary.json,live.jsonl}
dan bench.json berisi metrik per kandidat dan pilihan menurut aturan pra-registrasi.
Tidak ada frame atau audio yang ditulis (N-08). Ditolak bila app.mode bukan dev.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
# docs/CPU-THREADS.md (pra-registrasi)
CANDIDATES: tuple[int | None, ...] = (None, 1, 2, 4, 7)
PHYSICAL_CORES = 14  # i9-12900H laptop dev; null dihitung 14 untuk pemecah seri
TIE_MS = 17.0  # nilai desain pra-registrasi: satu periode refresh 60 Hz
BUDGET_S = 3.0  # respons pertama (SDD 3.3, K-3) dan sapaan (N-06)
SOURCE_RUN = ROOT / "results/E-02/20261020-130025-E-02-dev-hybrid-gpt-oss-120b-gateoff"
SPEAK_TIMEOUT_S = 120.0
RENDER_TIMEOUT_S = 90.0


class BenchRefused(Exception):
    pass


def label(tts: int | None, vision: int | None) -> str:
    return f"tts-{tts if tts is not None else 'null'}_vision-{vision if vision is not None else 'null'}"


def load_sentences(per_question: Path, n: int = 8) -> list[str]:
    """Teks Speak untuk n pertanyaan pertama (urut qid) berstatus answered, seperti controller."""
    from mica.core.spoken import spoken_with_items
    from mica.core.types import visible_items

    with Path(per_question).open(encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f)
                if r["llm_status"] == "answered" and r["final_status_check_on"] == "answered"]  # fmt: skip
    rows.sort(key=lambda r: r["qid"])
    out = []
    for r in rows[:n]:
        items = [x.strip() for x in r.get("items", "").split(";") if x.strip()]
        out.append(spoken_with_items(r["answer"], visible_items(r["answer"], items)))
    return out


def p95(values: list[float]) -> float | None:
    return float(np.percentile(values, 95)) if values else None


def metrics(rows: list[dict[str, Any]], speaks: list[dict[str, Any]],
            synth: list[tuple[float, float]], fps_idle: float) -> dict[str, Any]:  # fmt: skip
    """Metrik satu kandidat dari baris per detik dan catatan suara (docs/CPU-THREADS.md)."""
    tts_rows = [r for r in rows if r.get("state") == "TTS-menyusun"]
    gaps_tts = [g for r in tts_rows for g in (r.get("browser_gaps_ms") or [])]
    gaps_all = [g for r in rows for g in (r.get("browser_gaps_ms") or [])]
    det_max = [r["detect_ms"]["max"] for r in rows
               if r.get("detect_ms") and r["detect_ms"].get("max") is not None]  # fmt: skip
    first = [s["first_audio_s"] for s in speaks if s.get("first_audio_s") is not None]
    synth_s = [b - a for a, b in synth]

    def cpu(rs: list[dict[str, Any]], group: str) -> float | None:
        v = [r["cpu_pct"][group] for r in rs if r.get("cpu_pct") and r["cpu_pct"].get(group)
             is not None]  # fmt: skip
        return float(np.median(v)) if v else None

    det_p95 = p95(det_max)
    first_p95 = p95(first)
    greet = (1.0 / fps_idle + det_p95 / 1000 + first_p95
             if det_p95 is not None and first_p95 is not None else None)  # fmt: skip
    drawn_tts = [r["browser_drawn_fps"] for r in tts_rows if r.get("browser_drawn_fps") is not None]
    return {
        "n_seconds": len(rows), "n_tts_seconds": len(tts_rows), "n_speaks": len(speaks),
        "gap_p95_tts_ms": p95(gaps_tts), "gap_max_tts_ms": max(gaps_tts) if gaps_tts else None,
        "gap_p95_all_ms": p95(gaps_all), "n_gaps_tts": len(gaps_tts),
        "drawn_fps_tts_median": float(np.median(drawn_tts)) if drawn_tts else None,
        "synth_clip_s_median": float(np.median(synth_s)) if synth_s else None,
        "synth_clip_s_p95": p95(synth_s),
        "first_audio_s_p95": first_p95, "first_audio_s_median":
            float(np.median(first)) if first else None,
        "detect_ms_p95": det_p95, "greeting_est_s": greet,
        "cpu_total_tts_median": cpu(tts_rows, "total_machine"),
        "cpu_total_all_median": cpu(rows, "total_machine"),
        "cpu_vision_tts_median": cpu(tts_rows, "vision"),
        "cpu_suara_tts_median": cpu(tts_rows, "suara"),
        "cpu_vision_all_median": cpu(rows, "vision"),
        "torch_threads_seen": sorted({r["torch_threads"] for r in rows
                                      if r.get("torch_threads") is not None}),
    }  # fmt: skip


def eligible(m: dict[str, Any]) -> bool:
    return (m.get("gap_p95_tts_ms") is not None and m.get("first_audio_s_p95") is not None
            and m["first_audio_s_p95"] <= BUDGET_S and m.get("greeting_est_s") is not None
            and m["greeting_est_s"] <= BUDGET_S)  # fmt: skip


def _count(threads: int | None) -> int:
    return PHYSICAL_CORES if threads is None else threads


def choose(results: dict[int | None, dict[str, Any]]) -> tuple[int | None, str]:
    """Aturan pilih docs/CPU-THREADS.md -> (nilai, alasan)."""
    ok = {k: m for k, m in results.items() if eligible(m)}
    if not ok:
        return None, "tidak ada kandidat yang lolos syarat; nilai tetap null"
    best = min(m["gap_p95_tts_ms"] for m in ok.values())
    tied = [k for k, m in ok.items() if m["gap_p95_tts_ms"] - best < TIE_MS]
    pick = min(tied, key=_count)
    why = (
        f"p95 jeda TTS-menyusun terkecil {best:.0f} ms; seri (<{TIE_MS:.0f} ms): "
        f"{[k if k is not None else 'null' for k in tied]}; dipilih thread paling sedikit"
    )
    return pick, why


def run_candidate(settings: Any, tts: int | None, vision: int | None, folder: Path,
                  sentences: list[str], warmup_s: float) -> dict[str, Any]:  # fmt: skip
    from mica.audio.messages import Speak
    from mica.webui.app import build_controller, make_preview_meter, serve
    from mica.webui.browser import EdgeBrowser
    from mica.webui.server import WebUi

    audio = settings.audio.model_copy(
        update={"tts": settings.audio.tts.model_copy(update={"threads": tts})}
    )
    vis = settings.vision.model_copy(update={"threads": vision})
    s = settings.model_copy(update={"audio": audio, "vision": vis})
    webui = WebUi(s.ui, dev=True, trial=True, input_mode=s.audio.input_mode, measure=True)
    browser = EdgeBrowser(s.ui.fullscreen, camera_preview=s.ui.camera_preview)
    controller = build_controller(s, webui, fake_pipeline=True, measure=True)
    meter = make_preview_meter(s, webui, controller, browser, False, False, label(tts, vision))
    meter.folder = folder
    meter.live_path = folder / "live.jsonl"
    stop = threading.Event()
    server = threading.Thread(target=serve, args=(webui, controller, browser),
                              kwargs={"stop": stop, "on_ready": lambda _u: None}, daemon=True)  # fmt: skip
    meter.start()
    server.start()
    t0 = time.monotonic()
    error = None
    try:
        while webui.first_render_at is None:
            if time.monotonic() - t0 > RENDER_TIMEOUT_S:
                raise TimeoutError("halaman tidak tampil")
            time.sleep(0.5)
        time.sleep(warmup_s)
        for i, text in enumerate(sentences):
            n0 = len(meter.speaks)
            controller.bus.send("audio", Speak("bench", text, f"b{i}"))
            deadline = time.monotonic() + SPEAK_TIMEOUT_S
            while len(meter.speaks) <= n0:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Speak {i} tidak selesai")
                time.sleep(0.2)
        time.sleep(2.0)
    except Exception as exc:  # noqa: BLE001 - dicatat di bench.json, kandidat berikutnya jalan
        error = repr(exc)
    finally:
        stop.set()
        server.join(30)
        meter.stop()
    with meter.lock:
        rows = list(meter.rows)
    m = metrics(rows, meter.speaks, meter.synth, s.vision.fps_idle)
    m.update(
        tts_threads=tts,
        vision_threads=vision,
        error=error,
        tts_session=meter.tts_info,
        wall_s=round(time.monotonic() - t0, 1),
    )
    return m


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts/cpu_threads_bench.py")
    p.add_argument("--config", type=Path, default=ROOT / "config/dev.yaml")
    p.add_argument("--out", type=Path, default=ROOT / "results/cpu-threads")
    p.add_argument("--stage", choices=("1", "2", "all"), default="all")
    p.add_argument("--tts", help="pemenang tahap 1 untuk --stage 2 (angka atau null)")
    p.add_argument("--warmup-s", type=float, default=10.0)
    p.add_argument("--sentences", type=int, default=8)
    args = p.parse_args(argv)
    from mica.trial import load_trial_settings

    settings, _ = load_trial_settings(args.config, ROOT / ".env")
    if settings.app.mode != "dev":
        print("error: bench hanya boleh saat app.mode: dev", file=sys.stderr)
        return 2
    sentences = load_sentences(SOURCE_RUN / "per_question.csv", args.sentences)
    out = args.out / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "protocol": "docs/CPU-THREADS.md", "candidates": [c for c in CANDIDATES],
        "physical_cores": PHYSICAL_CORES, "tie_ms": TIE_MS, "budget_s": BUDGET_S,
        "source_run": SOURCE_RUN.relative_to(ROOT).as_posix(), "n_sentences": len(sentences),
        "sentence_chars": [len(x) for x in sentences], "warmup_s": args.warmup_s,
        "started_at": datetime.now().astimezone().isoformat(), "stage1": {}, "stage2": {},
    }  # fmt: skip

    def save() -> None:
        (out / "bench.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8")  # fmt: skip

    def run(stage: str, tts: int | None, vision: int | None) -> dict[str, Any]:
        name = label(tts, vision)
        print(f"[{datetime.now():%H:%M:%S}] tahap {stage}: {name}", flush=True)
        m = run_candidate(settings, tts, vision, out / name, sentences, args.warmup_s)
        print(
            f"    p95 jeda TTS {m['gap_p95_tts_ms']} ms, suara pertama p95 "
            f"{m['first_audio_s_p95']} s, error {m['error']}",
            flush=True,
        )
        report[f"stage{stage}"][name] = m
        save()
        time.sleep(3.0)  # Edge dan pekerja selesai menutup
        return m

    tts_best: int | None
    if args.stage in ("1", "all"):
        stage1 = {c: run("1", c, None) for c in CANDIDATES}
        tts_best, why = choose(stage1)
        report["stage1_choice"] = {"audio.tts.threads": tts_best, "reason": why}
        save()
    else:
        tts_best = None if args.tts in (None, "null") else int(args.tts)
    if args.stage in ("2", "all"):
        stage2: dict[int | None, dict[str, Any]] = {}
        null_name = label(tts_best, None)
        if null_name in report["stage1"]:
            stage2[None] = report["stage1"][null_name]  # tidak diulang (pra-registrasi)
        else:
            stage2[None] = run("2", tts_best, None)
        for c in CANDIDATES[1:]:
            stage2[c] = run("2", tts_best, c)
        vision_best, why = choose(stage2)
        report["stage2_choice"] = {"audio.tts.threads": tts_best, "vision.threads": vision_best,
                                   "reason": why}  # fmt: skip
    report["finished_at"] = datetime.now().astimezone().isoformat()
    save()
    print(f"selesai: {out / 'bench.json'}", flush=True)
    print(json.dumps({k: report.get(k) for k in ("stage1_choice", "stage2_choice")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
