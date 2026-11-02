"""E-09 eval latency (docs/E-09.md): statistik latensi dari log 6.2 dan verdict mekanis.

python -m mica.eval latency --logs logs/ [--from YYYY-MM-DD --to YYYY-MM-DD]
    [--resources <folder>/resources.csv] --label <label> [--out results/E-09] [--tool-test]

- Masukan: logs/turns-*.jsonl (timings per giliran) dan logs/events-*.jsonl (latency_s greeted).
- Ukuran per giliran: kunci timings 6.2 + first_response, ditambah dua gabungan anggaran SDD 3.3:
  retrieval_gate = retrieval + gate, check_tts = check + tts_first_audio (null bila salah satu
  komponen null).
- Statistik dipisah input suara vs ketik: n, n_null (null diabaikan tetapi dihitung), p50, p95,
  maks. Tahap suara (vad, stt, first_response) hanya dari input suara.
- Persentil: interpolasi linear numpy.percentile bawaan (mica.eval.metrics.percentile), sama
  dengan eval lain di repo.
- Verdict (docs/E-09.md): tahap SDD 3.3 dari input suara -> "lulus" atau "lewat anggaran tahap";
  total (suara), first_response, dan sapaan -> "lulus" atau "gagal"; n = 0 -> "tidak ada data".
  Keseluruhan: GAGAL bila salah satu ukuran utama gagal; TIDAK LENGKAP bila ada ukuran utama
  tanpa data; selain itu LULUS.
- Opsional CSV perekam sumber daya (mica.eval.resources): per kelompok rata-rata dan p95 CPU,
  RAM awal/akhir/kemiringan (MB per jam). Sampel tanpa proses tidak dipakai; sampel pertama tiap
  kelompok tidak dipakai untuk CPU (CPU butuh dua sampel); TOTAL hanya dari sampel saat semua
  kelompok yang pernah aktif punya proses (sebelum pekerja dimulai dan setelah berhenti tidak).
Hasil: <out>/<label>-<cap waktu>/ per_turn.csv, summary.csv, resources_summary.csv, verdict.md,
run.json.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from mica.core.logging import TIMING_KEYS
from mica.eval.metrics import percentile

PERCENTILE_METHOD = "interpolasi linear (numpy.percentile bawaan), mica.eval.metrics.percentile"
VOICE_ONLY = ("vad", "stt", "first_response")
# kunci per giliran: 6.2 + K-3 + gabungan anggaran 3.3 + komponen tambahan
TURN_MEASURES = (*TIMING_KEYS, "first_response", "gate", "retrieval_gate", "check_tts")


@dataclass(frozen=True)
class Rule:
    measure: str  # nama ukuran di summary
    limit_s: float
    source: str
    kind: str  # "tahap" (lewat anggaran tahap) atau "utama" (gagal)
    input_mode: str  # "voice" atau "event"


# docs/E-09.md, "Aturan lulus" (pra-registrasi 18 Okt 2026)
RULES = (
    Rule("vad", 0.5, "SDD 3.3 deteksi akhir ucapan", "tahap", "voice"),
    Rule("stt", 1.5, "SDD 3.3 STT ucapan 5 detik", "tahap", "voice"),
    Rule("retrieval_gate", 0.5, "SDD 3.3 retrieval dan gerbang", "tahap", "voice"),
    Rule("llm", 4.0, "SDD 3.3 LLM sampai jawaban lengkap", "tahap", "voice"),
    Rule("check_tts", 1.0, "SDD 3.3 cek fakta dan TTS kalimat pertama", "tahap", "voice"),
    Rule("total", 10.0, "N-05", "utama", "voice"),
    Rule("first_response", 3.0, "K-3", "utama", "voice"),
    Rule("greeting", 3.0, "N-06 (latency_s event greeted)", "utama", "event"),
)


def _sum(*values: float | None) -> float | None:
    return (
        None if any(v is None for v in values) else float(sum(v for v in values if v is not None))
    )


def _files(log_dir: Path, kind: str, start: date | None, end: date | None) -> list[Path]:
    out = []
    for path in sorted(Path(log_dir).glob(f"{kind}-*.jsonl")):
        try:
            day = date.fromisoformat(path.stem.removeprefix(f"{kind}-"))
        except ValueError:
            continue
        if (start is None or day >= start) and (end is None or day <= end):
            out.append(path)
    return out


def _read(paths: list[Path]) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        with path.open(encoding="utf-8") as f:
            rows += [json.loads(line) for line in f if line.strip()]
    return rows


def turn_rows(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Satu baris per giliran: kunci waktu (null tetap null) + gabungan anggaran 3.3."""
    out = []
    for t in turns:
        timings = t.get("timings") or {}
        get = timings.get
        row: dict[str, Any] = {"ts": t.get("ts"), "session_id": t.get("session_id"),
                               "turn_index": t.get("turn_index"), "input_mode": t.get("input_mode"),
                               "final_status": t.get("final_status")}  # fmt: skip
        for key in (*TIMING_KEYS, "first_response", "gate"):
            value = get(key)
            row[key] = None if value is None else float(value)
        if row["input_mode"] != "voice":  # ketik tidak pernah masuk tahap suara
            for key in VOICE_ONLY:
                row[key] = None
        row["retrieval_gate"] = _sum(row["retrieval"], row["gate"])
        row["check_tts"] = _sum(row["check"], row["tts_first_audio"])
        row["total_without_audio"] = row["tts_first_audio"] is None
        out.append(row)
    return out


def stats(values: list[float | None]) -> dict[str, Any]:
    xs = [float(v) for v in values if v is not None]
    return {"n": len(xs), "n_null": len(values) - len(xs),
            "p50": percentile(xs, 50) if xs else None,
            "p95": percentile(xs, 95) if xs else None,
            "max": max(xs) if xs else None}  # fmt: skip


def summarize(rows: list[dict[str, Any]], greetings: list[float | None]) -> list[dict[str, Any]]:
    limits = {r.measure: r.limit_s for r in RULES}
    out = []
    for mode in ("voice", "text"):
        sub = [r for r in rows if r["input_mode"] == mode]
        for measure in TURN_MEASURES:
            if mode == "text" and measure in VOICE_ONLY:
                continue
            out.append({"measure": measure, "input_mode": mode,
                        **stats([r[measure] for r in sub]),
                        "limit_s": limits.get(measure) if mode == "voice" else None,
                        "method": PERCENTILE_METHOD})  # fmt: skip
        if sub:
            out.append({"measure": "total_without_audio", "input_mode": mode,
                        "n": sum(r["total_without_audio"] for r in sub), "n_null": 0,
                        "p50": None, "p95": None, "max": None, "limit_s": None,
                        "method": "jumlah giliran yang total-nya berakhir tanpa audio"})  # fmt: skip
    out.append({"measure": "greeting", "input_mode": "event", **stats(greetings),
                "limit_s": limits["greeting"], "method": PERCENTILE_METHOD})  # fmt: skip
    return out


def verdict(summary: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    index = {(s["measure"], s["input_mode"]): s for s in summary}
    items = []
    for rule in RULES:
        s = index.get((rule.measure, rule.input_mode), {"n": 0, "p95": None})
        if s["n"] == 0 or s["p95"] is None:
            status = "tidak ada data"
        elif s["p95"] <= rule.limit_s:
            status = "lulus"
        else:
            status = "lewat anggaran tahap" if rule.kind == "tahap" else "gagal"
        items.append({"measure": rule.measure, "input_mode": rule.input_mode, "n": s["n"],
                      "p95": s["p95"], "limit_s": rule.limit_s, "source": rule.source,
                      "kind": rule.kind, "status": status})  # fmt: skip
    main = [i for i in items if i["kind"] == "utama"]
    if any(i["status"] == "gagal" for i in main):
        overall = "GAGAL"
    elif any(i["status"] == "tidak ada data" for i in main):
        overall = "TIDAK LENGKAP"
    else:
        overall = "LULUS"
    return overall, items


def resources_summary(path: Path) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, float]]] = defaultdict(list)
    with Path(path).open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by[row["group"]].append({"t": float(row["elapsed_s"]), "cpu": float(row["cpu_pct"]),
                                     "uss": float(row["uss_mb"]),
                                     "n": float(row["n_processes"])})  # fmt: skip
    # sampel tanpa proses (mis. pekerja belum atau tidak dimulai) tidak dipakai;
    # TOTAL dimulai saat semua kelompok yang pernah aktif sudah punya proses
    active = {g for g, samples in by.items() if any(s["n"] > 0 for s in samples)}
    present: dict[float, set[str]] = defaultdict(set)
    totals: dict[float, dict[str, float]] = defaultdict(lambda: {"cpu": 0.0, "uss": 0.0, "n": 0.0})
    for group, samples in by.items():
        for s in samples:
            if s["n"] > 0:
                present[s["t"]].add(group)
            for k in ("cpu", "uss", "n"):
                totals[s["t"]][k] += s[k]
    complete = {t for t in totals if active and present[t] >= active}
    groups = {g: [s for s in samples if s["n"] > 0] for g, samples in by.items()}
    groups["TOTAL"] = [{"t": t, **v} for t, v in sorted(totals.items()) if t in complete]
    out = []
    for group, samples in groups.items():
        samples = sorted(samples, key=lambda s: s["t"])
        if not samples:
            out.append({"group": group, "n_samples": 0, "duration_s": None,
                        "cpu_mean_pct": None, "cpu_p95_pct": None, "uss_start_mb": None,
                        "uss_end_mb": None, "uss_slope_mb_per_hour": None})  # fmt: skip
            continue
        cpu = [s["cpu"] for s in samples[1:]]  # sampel pertama: CPU belum terukur
        xs, ys = [s["t"] / 3600 for s in samples], [s["uss"] for s in samples]
        slope = statistics.linear_regression(xs, ys).slope if len(set(xs)) > 1 else None
        out.append({"group": group, "n_samples": len(samples),
                    "duration_s": samples[-1]["t"] - samples[0]["t"],
                    "cpu_mean_pct": statistics.fmean(cpu) if cpu else None,
                    "cpu_p95_pct": percentile(cpu, 95) if cpu else None,
                    "uss_start_mb": ys[0], "uss_end_mb": ys[-1],
                    "uss_slope_mb_per_hour": slope})  # fmt: skip
    return out


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def verdict_markdown(label: str, overall: str, items: list[dict[str, Any]], tool_test: bool) -> str:
    lines = [f"# E-09 verdict: {label}", ""]
    if tool_test:
        lines += ["**Uji alat, bukan hasil E-09.**", ""]
    lines += [f"Keseluruhan: **{overall}**", "",
              "Aturan: docs/E-09.md (pra-registrasi 18 Okt 2026), diterapkan mekanis pada p95.",
              f"Persentil: {PERCENTILE_METHOD}.", "",
              "| Ukuran | Input | n | p95 (s) | Syarat (s) | Sumber | Status |",
              "| --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for i in items:
        lines.append(f"| {i['measure']} | {i['input_mode']} | {i['n']} | {_fmt(i['p95'])} | "
                     f"≤ {i['limit_s']:g} | {i['source']} | {i['status']} |")  # fmt: skip
    lines += ["", ("Tahap SDD 3.3 yang melewati anggaran sementara total, K-3, dan sapaan aman "
              "dilaporkan sebagai \"lewat anggaran tahap\", bukan gagal.")]  # fmt: skip
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    fields = fields or (list(rows[0]) if rows else [])
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_latency(
    log_dir: Path,
    out_root: Path,
    label: str,
    resources: Path | None = None,
    start: date | None = None,
    end: date | None = None,
    tool_test: bool = False,
    environment: dict[str, Any] | None = None,
    stamp: str | None = None,
    split_info: dict[str, Any] | None = None,
) -> tuple[Path, str]:
    turn_files = _files(log_dir, "turns", start, end)
    event_files = _files(log_dir, "events", start, end)
    rows = turn_rows(_read(turn_files))
    events = _read(event_files)
    greetings = [e.get("latency_s") for e in events if e.get("event") == "greeted"]
    summary = summarize(rows, greetings)
    overall, items = verdict(summary)
    stamp = stamp or datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(out_root) / f"{label}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    fields = ["ts", "session_id", "turn_index", "input_mode", "final_status",
              *TURN_MEASURES, "total_without_audio"]  # fmt: skip
    _write_csv(run_dir / "per_turn.csv", rows, fields)
    _write_csv(run_dir / "summary.csv", summary)
    res_rows = resources_summary(resources) if resources is not None else []
    _write_csv(run_dir / "resources_summary.csv", res_rows,
               ["group", "n_samples", "duration_s", "cpu_mean_pct", "cpu_p95_pct",
                "uss_start_mb", "uss_end_mb", "uss_slope_mb_per_hour"])  # fmt: skip
    (run_dir / "verdict.md").write_text(verdict_markdown(label, overall, items, tool_test),
                                        encoding="utf-8")  # fmt: skip
    info = {
        "experiment": "E-09 latency", "protocol": "docs/E-09.md (pra-registrasi 18 Okt 2026)",
        "label": label,
        "tool_test": tool_test,
        "split": (split_info or {}).get("split", "dev"),
        "lock": (split_info or {}).get("lock"),
        "note": "uji alat, bukan hasil E-09" if tool_test else None,
        "log_dir": Path(log_dir).as_posix(),
        "date_range": [start.isoformat() if start else None, end.isoformat() if end else None],
        "inputs": {p.name: _sha256(p) for p in [*turn_files, *event_files]},
        "resources": None if resources is None else {"path": Path(resources).as_posix(),
                                                     "sha256": _sha256(resources)},
        "n_turns": len(rows), "n_turns_voice": sum(r["input_mode"] == "voice" for r in rows),
        "n_turns_text": sum(r["input_mode"] == "text" for r in rows),
        "n_greetings": len(greetings), "percentile_method": PERCENTILE_METHOD,
        "verdict": {"overall": overall, "items": items},
        "environment": environment,
    }  # fmt: skip
    (run_dir / "run.json").write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")  # fmt: skip
    return run_dir, overall
