"""Optimasi biaya pratinjau kamera UI web (Langkah 38; pra-registrasi docs/UI-PREVIEW-OPT.md).

python scripts/ui_preview_opt.py grow --out <folder> [--minutes 15] [--interval 30] [KONDISI]
python scripts/ui_preview_opt.py ab --out <folder> --a NAMA:KONDISI --b NAMA:KONDISI [--reps 10]
python scripts/ui_preview_opt.py decide --summary <folder ab>/summary.json [--name akhir]

KONDISI = daftar kunci=nilai dipisah koma:
  static=<ref git>|now    file statis dari commit itu atau pohon kerja (bawaan now)
  preview=public|off      ui.camera_preview (bawaan public; public/debug memakai --fake-camera)
  fps=<angka>             ui.preview_fps (bawaan nilai config, 5)
  edge=<switch>[+<switch>]  switch Edge tambahan (mis. edge=--disable-gpu-compositing)
Contoh: --a base:static=21e25ae --b k1:static=now

- grow: satu proses anak bench (Edge kiosk, pekerja suara/pipeline palsu, proses kamera dengan
  sumber dan detektor palsu), diam tanpa pertanyaan; RAM USS dan CPU per jenis proses dicatat
  setiap --interval detik. Rata-rata 5 menit pertama vs 5 menit terakhir, kemiringan regresi
  10 menit terakhir (MB/menit), keputusan "naik terus (bocor)" / "mendatar (plafon)" sesuai
  pra-registrasi.
- ab: bench tahap 1 (ui_bench.run_once) selang-seling A, B, A, B, ... --reps ulangan per kondisi,
  AC wajib. Keputusan B vs A menurut aturan pra-registrasi.
Hasil di --out (per_run.csv / samples.csv, by_kind.csv, summary.json, report.md).

Penjaga memori (Langkah 38): bila memori tersedia sistem < --min-free-gb (bawaan 2 GB) sebelum
atau selama ulangan, proses bench dihentikan sendiri, hasil yang sudah ada ditulis ke
aborted.json, dan perintah keluar dengan kode 4 (tidak menunggu dihentikan sistem).

Tambahan (Langkah 38):
- decide: hitung ulang aturan pra-registrasi (decide()) dari summary.json sebuah run ab yang
  lengkap, tulis decision.json di folder itu, cetak baris "FINAL=<NAMA:KONDISI>" (B bila lolos,
  A bila tidak). Run tidak lengkap (aborted.json ada / ulangan kurang) -> kode 6.
- --dry-run (grow, ab): siapkan config dan file statis, cetak perintah anak, daya, dan memori
  tersedia, tanpa menjalankan bench.
- --no-decision (ab): laporan info saja (pra-registrasi: fps 2 vs 5, akhir vs off), tanpa kalimat
  keputusan.
- --log <file> (semua): stdout dan stderr perintah ini juga ditulis ke file.
- --cdp-gc (grow; amandemen 2): Edge dengan --remote-debugging-port (127.0.0.1); setelah sampel
  terakhir GC paksa di halaman MICA (ui_bench.cdp_memory, sama dengan L31), lalu RAM USS renderer
  30 dan 60 s sesudahnya. Turun dari nilai sebelum GC -> "turun lagi setelah GC (sampah GC)",
  selain itu "tidak turun (bocor)".
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Self

import psutil
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_bench

ROOT = Path(__file__).resolve().parents[1]
STATIC = "src/mica/webui/static"
GROUPS = {  # jenis proses ui_bench.process_kind -> kelompok laporan
    "python: Flask + controller": "inti Python",
    "python: peluncur venv": "inti Python",
    "python: pekerja (kamera)": "kamera",
    "edge: browser": "Edge browser",
    "edge: gpu-process": "Edge GPU",
    "edge: renderer": "Edge renderer",
}
GROUP_ORDER = ("inti Python", "kamera", "Edge browser", "Edge GPU", "Edge renderer", "lainnya")


class LowMemory(Exception):
    pass


class MemoryGuard:
    """Thread pengawas: memori tersedia < batas -> catat, matikan pohon proses anak bench."""

    def __init__(self, min_free_gb: float, interval_s: float = 2.0) -> None:
        import threading

        self.min_free = min_free_gb * 2**30
        self.interval_s = interval_s
        self.tripped: dict[str, Any] | None = None
        self.lowest_gb: float | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="memory-guard", daemon=True)

    def free_gb(self) -> float:
        import psutil

        free = psutil.virtual_memory().available / 2**30
        self.lowest_gb = free if self.lowest_gb is None else min(self.lowest_gb, free)
        return free

    def check(self) -> None:
        if self.tripped is not None or self.free_gb() * 2**30 < self.min_free:
            self._trip()
            raise LowMemory(self.tripped)

    def _trip(self) -> None:
        import psutil

        if self.tripped is None:
            self.tripped = {
                "free_gb": self.lowest_gb,
                "at": datetime.now().isoformat(timespec="seconds"),
            }
        for p in psutil.process_iter(["cmdline"]):
            cmd = " ".join(p.info["cmdline"] or [])
            if "ui_bench.py" in cmd and "--child" in cmd:
                for q in reversed([p, *p.children(recursive=True)]):
                    try:
                        q.kill()
                    except psutil.Error:
                        pass

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            if self.free_gb() * 2**30 < self.min_free:
                self._trip()
                return

    def __enter__(self) -> Self:
        self.check()
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()


def group(kind: str) -> str:
    return GROUPS.get(kind, "lainnya")


@dataclass
class Condition:
    name: str
    static: str = "now"
    preview: str = "public"
    fps: float | None = None
    edge: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def parse(cls, text: str) -> Condition:
        name, _, rest = text.partition(":")
        c = cls(name)
        for item in filter(None, rest.split(",")):
            key, _, value = item.partition("=")
            if key == "static":
                c.static = value
            elif key == "preview":
                c.preview = value
            elif key == "fps":
                c.fps = float(value)
            elif key == "edge":
                c.edge = tuple(v for v in value.split("+") if v)
            else:
                raise SystemExit(f"kunci kondisi tidak dikenal: {key}")
        return c

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "static": self.static, "preview": self.preview,
                "preview_fps": self.fps, "edge_extra": list(self.edge)}  # fmt: skip

    @classmethod
    def from_describe(cls, d: dict[str, Any]) -> Condition:
        return cls(d["name"], d["static"], d["preview"], d["preview_fps"], tuple(d["edge_extra"]))

    def spec(self) -> str:
        """Kebalikan parse(): NAMA:KONDISI."""
        parts = [f"static={self.static}", f"preview={self.preview}"]
        if self.fps is not None:
            parts.append(f"fps={self.fps:g}")
        if self.edge:
            parts.append("edge=" + "+".join(self.edge))
        return f"{self.name}:" + ",".join(parts)


def export_static(ref: str, out: Path) -> Path:
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref, STATIC], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()  # fmt: skip
    for name in names:
        data = subprocess.run(["git", "show", f"{ref}:{name}"], cwd=ROOT, capture_output=True,
                              check=True).stdout  # fmt: skip
        target = out / Path(name).relative_to(STATIC)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return out


def prepare(cond: Condition, base_config: Path, out: Path) -> tuple[Path, tuple[str, ...]]:
    """Config dan argumen anak untuk satu kondisi."""
    raw = yaml.safe_load(base_config.read_text(encoding="utf-8"))
    raw["ui"]["camera_preview"] = cond.preview
    if cond.fps is not None:
        raw["ui"]["preview_fps"] = cond.fps
    config = out / f"config-{cond.name}.yaml"
    config.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    extra: list[str] = []
    if cond.preview != "off":
        extra.append("--fake-camera")
    if cond.static != "now":
        static_dir = export_static(cond.static, (out / f"static-{cond.name}").resolve())
        extra += ["--static-dir", str(static_dir)]
    return config, tuple(extra)


# --- grow ---------------------------------------------------------------------------------


def _cpu_times(procs: list[Any]) -> dict[int, float]:
    import psutil

    out = {}
    for p in procs:
        try:
            t = p.cpu_times()
            out[p.pid] = t.user + t.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return out


def _uss_groups(pid: int) -> dict[str, float]:
    uss = dict.fromkeys(GROUP_ORDER, 0.0)
    for kind, (_n, mb) in ui_bench.uss_by_kind(pid).items():
        uss[group(kind)] += mb
    return uss


def gc_verdict(before: float, after_60s: float) -> str:
    """Amandemen 2: turun lagi 60 s setelah GC -> sampah GC; tidak turun -> bocor."""
    return "turun lagi setelah GC (sampah GC)" if after_60s < before else "tidak turun (bocor)"


def _gc_after(port: int, pid: int, before: float, guard: MemoryGuard) -> dict[str, Any]:
    """GC paksa lewat DevTools, lalu RAM USS renderer 30 dan 60 s sesudahnya."""
    t_gc = time.monotonic()
    try:
        info: dict[str, Any] = ui_bench.cdp_memory(port)
    except Exception as exc:  # noqa: BLE001 -- GC gagal (httpx/websocket) dicatat, uji tumbuh tetap dilaporkan
        return {"error": repr(exc), "renderer_before_mb": before}
    for wait in (30, 60):
        time.sleep(max(t_gc + wait - time.monotonic(), 0.0))
        guard.check()
        info[f"renderer_after_{wait}s_mb"] = _uss_groups(pid)["Edge renderer"]
        print(f"GC +{wait} s | renderer {info[f'renderer_after_{wait}s_mb']:.1f} MB", flush=True)
    info["renderer_before_mb"] = before
    info["verdict"] = gc_verdict(before, info["renderer_after_60s_mb"])
    return info


def _slope(xs: list[float], ys: list[float]) -> float:
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den if den else 0.0


def cmd_grow(args: argparse.Namespace) -> int:
    from mica.eval.environment import collect_environment

    cond = Condition.parse(args.condition)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    config, extra = prepare(cond, args.config, out)
    child = _child_cmd(cond, config, extra)
    port = None
    if args.cdp_gc:  # Langkah 38 amandemen 2: GC paksa lewat DevTools seperti L31 (--cdp-gc)
        port = ui_bench._free_port()
        child.append(f"--edge-extra=--remote-debugging-port={port}")  # hanya 127.0.0.1
    if args.dry_run:
        return _dry_run(args, {cond.name: child})
    power = ui_bench.require_ac()
    guard = MemoryGuard(args.min_free_gb).__enter__()
    err = (out / "stderr-grow.log").open("w", encoding="utf-8")  # Langkah 38: stderr anak disimpan
    proc = subprocess.Popen(child, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=err, text=True, encoding="utf-8")  # fmt: skip
    rows: list[dict[str, Any]] = []
    gc_info: dict[str, Any] | None = None
    try:
        ui_bench.read_event(proc, "painted")
        t0 = time.monotonic()
        n = int(args.minutes * 60 // args.interval)
        prev: dict[int, float] | None = None
        prev_t = t0
        for i in range(n + 1):
            target = t0 + i * args.interval
            time.sleep(max(target - time.monotonic(), 0.0))
            guard.check()
            procs = ui_bench.tree(proc.pid)
            kinds = {p.pid: group(ui_bench.process_kind(p, proc.pid)) for p in procs}
            now_t = time.monotonic()
            times = _cpu_times(procs)
            uss = _uss_groups(proc.pid)
            cpu = dict.fromkeys(GROUP_ORDER, 0.0)
            if prev is not None:
                for pid, t in times.items():
                    if pid in prev:
                        cpu[kinds[pid]] += 100.0 * (t - prev[pid]) / (now_t - prev_t)
            prev, prev_t = times, now_t
            row = {"t_s": round(now_t - t0, 1), "uss_total_mb": sum(uss.values()),
                   **{f"uss_{g}": uss[g] for g in GROUP_ORDER},
                   "cpu_total_pct": sum(cpu.values()) if i else None,
                   **{f"cpu_{g}": cpu[g] if i else None for g in GROUP_ORDER}}  # fmt: skip
            rows.append(row)
            print(f"{row['t_s']:>6.0f} s | USS {row['uss_total_mb']:.1f} MB | GPU "
                  f"{uss['Edge GPU']:.1f} | renderer {uss['Edge renderer']:.1f} | CPU "
                  f"{row['cpu_total_pct'] or 0:.2f}%", flush=True)  # fmt: skip
        if port is not None:
            gc_info = _gc_after(port, proc.pid, rows[-1]["uss_Edge renderer"], guard)
        proc.stdin.write("quit\n")  # type: ignore[union-attr]
        proc.stdin.flush()  # type: ignore[union-attr]
        proc.wait(timeout=30)
    except (LowMemory, RuntimeError) as exc:
        guard.__exit__()
        if guard.tripped is None:
            raise
        _abort(out, {"mode": "grow", "condition": cond.describe(), "samples": rows,
                     "memory": guard.tripped, "error": str(exc)})  # fmt: skip
        return 4
    finally:
        guard.__exit__()
        if proc.poll() is None:
            for p in reversed(ui_bench.tree(proc.pid)):
                p.kill()
        err.close()
    report_free = guard.lowest_gb
    with (out / "samples.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    first = [r for r in rows if r["t_s"] <= 300]
    last = [r for r in rows if r["t_s"] >= rows[-1]["t_s"] - 300]
    tail = [r for r in rows if r["t_s"] >= rows[-1]["t_s"] - 600]
    keys = ["uss_total_mb", *(f"uss_{g}" for g in GROUP_ORDER)]
    report: dict[str, Any] = {"condition": cond.describe(), "minutes": args.minutes,
                              "interval_s": args.interval, "power": power, "per_metric": {}}  # fmt: skip
    lines = [f"# Uji tumbuh {args.minutes:g} menit: {cond.name}", "",
             f"Kondisi: {cond.describe()}; sampel tiap {args.interval:g} s.", "",
             ("| metrik | rata-rata 5 menit pertama | rata-rata 5 menit terakhir | selisih | "
             "kemiringan 10 menit terakhir (MB/menit) | keputusan |"),
             "| --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for k in keys:
        a = statistics.fmean(r[k] for r in first)
        b = statistics.fmean(r[k] for r in last)
        slope = _slope([r["t_s"] / 60 for r in tail], [r[k] for r in tail])
        verdict = "naik terus (bocor)" if b > a and slope > 0 else "mendatar (plafon)"
        report["per_metric"][k] = {"first5": a, "last5": b, "slope_mb_per_min": slope,
                                   "verdict": verdict}  # fmt: skip
        lines.append(f"| {k} | {a:.1f} | {b:.1f} | {b - a:+.1f} | {slope:+.3f} | {verdict} |")
    cpu_rows = [r for r in rows if r["cpu_total_pct"] is not None]
    lines += ["", "CPU rata-rata seluruh uji per proses (% satu inti):", ""]
    cpu_mean = {g: statistics.fmean(r[f"cpu_{g}"] for r in cpu_rows) for g in GROUP_ORDER}
    cpu_mean["total"] = statistics.fmean(r["cpu_total_pct"] for r in cpu_rows)
    lines += [f"- {g}: {v:.2f}" for g, v in cpu_mean.items()]
    report["cpu_mean_pct"] = cpu_mean
    if gc_info is not None:
        report["gc"] = gc_info
        lines += ["", ("GC paksa di renderer setelah sampel terakhir (HeapProfiler.collectGarbage, "
                  "seperti L31 --cdp-gc):"), ""]  # fmt: skip
        if "error" in gc_info:
            lines.append(f"- GC gagal: {gc_info['error']}")
        else:
            lines += [f"- renderer sebelum GC: {gc_info['renderer_before_mb']:.1f} MB",
                      f"- renderer 30 s setelah GC: {gc_info['renderer_after_30s_mb']:.1f} MB",
                      f"- renderer 60 s setelah GC: {gc_info['renderer_after_60s_mb']:.1f} MB",
                      (f"- heap JS: {gc_info['js_used_mb_before_gc']:.2f} -> "
                      f"{gc_info['js_used_mb_after_gc']:.2f} MB"),
                      f"- keputusan (amandemen 2): {gc_info['verdict']}"]  # fmt: skip
    report["lowest_free_gb"] = report_free
    report["environment"] = collect_environment()
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")  # fmt: skip
    print("\n".join(lines))
    return 0


# --- ab -----------------------------------------------------------------------------------


def _grouped(per_kind: dict[str, float]) -> dict[str, float]:
    out = dict.fromkeys(GROUP_ORDER, 0.0)
    for kind, v in per_kind.items():
        out[group(kind)] += v
    return out


def stats(values: list[float]) -> dict[str, float]:
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def decide(base: dict[str, Any], cand: dict[str, Any]) -> tuple[bool, list[str]]:
    """Aturan pra-registrasi: salah satu (RAM/CPU total) median < min pembanding, yang lain
    median <= maks pembanding, dan p95 jeda median <= maks pembanding."""
    reasons = []
    lower = {m: cand[m]["median"] < base[m]["min"] for m in ("uss", "cpu")}
    not_higher = {m: cand[m]["median"] <= base[m]["max"] for m in ("uss", "cpu", "p95")}
    for m in ("uss", "cpu", "p95"):
        reasons.append(f"{m}: median {cand[m]['median']:.3f} vs pembanding min "
                       f"{base[m]['min']:.3f} / maks {base[m]['max']:.3f}")  # fmt: skip
    ok = ((lower["uss"] and not_higher["cpu"]) or (lower["cpu"] and not_higher["uss"])) and (
        not_higher["p95"]
    )
    return ok, reasons


def cmd_ab(args: argparse.Namespace) -> int:
    from mica.eval.environment import collect_environment

    a, b = Condition.parse(args.a), Condition.parse(args.b)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    prepared = {c.name: (c, *prepare(c, args.config, out)) for c in (a, b)}
    if args.dry_run:
        return _dry_run(args, {n: _child_cmd(*p) for n, p in prepared.items()})
    ui_bench.require_ac()
    runs: dict[str, list[dict[str, Any]]] = {a.name: [], b.name: []}
    order = 0
    guard = MemoryGuard(args.min_free_gb)
    lowest: float | None = None
    for rep in range(1, args.reps + 1):
        for name in (a.name, b.name):
            cond, config, extra = prepared[name]
            order += 1
            try:
                with guard:
                    r = ui_bench.run_once(
                        "web",
                        rep,
                        config,
                        edge_extra=cond.edge,
                        child_extra=extra,
                        stderr_path=out / f"stderr-{order:02d}-{name}.log",
                    )
            except (LowMemory, RuntimeError, TimeoutError, psutil.NoSuchProcess) as exc:
                done = {n: [{k: v for k, v in x.items() if not k.startswith("_")} for x in rs]
                        for n, rs in runs.items()}  # fmt: skip
                reason = ("memori" if guard.tripped is not None
                          else f"proses anak bench berhenti sendiri pada {name} #{rep}")  # fmt: skip
                _abort(out, {"mode": "ab", "a": a.describe(), "b": b.describe(),
                             "completed_runs": done, "memory": guard.tripped,
                             "reason": reason, "error": repr(exc)})  # fmt: skip
                return 4 if guard.tripped is not None else 5
            lowest = guard.lowest_gb
            guard = MemoryGuard(args.min_free_gb)
            guard.lowest_gb = lowest
            r.update(order=order, condition=name)
            runs[name].append(r)
            g = _grouped(r["_uss_by_kind"])
            print(f"{order:>2} {name} #{rep}: USS {r['uss_idle_mb']:.1f} MB (GPU {g['Edge GPU']:.1f}, "
                  f"renderer {g['Edge renderer']:.1f}) | CPU {r['cpu_idle_pct']:.2f}% | p95 "
                  f"{r['lat_p95_ms']:.2f} ms | {r['power_source']}", flush=True)  # fmt: skip
    all_runs = sorted(runs[a.name] + runs[b.name], key=lambda r: r["order"])
    fields = ["order", "condition", "rep", "startup_s", "uss_idle_mb", "cpu_idle_pct",
              "lat_p50_ms", "lat_p95_ms", "n_updates", "n_unacked", "power_source"]  # fmt: skip
    with (out / "per_run.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_runs)
    with (out / "by_kind.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order", "condition", "group", "uss_idle_mb", "cpu_idle_pct"])
        for r in all_runs:
            gu, gc = _grouped(r["_uss_by_kind"]), _grouped(r["_cpu_by_kind"])
            for g in GROUP_ORDER:
                w.writerow([r["order"], r["condition"], g, gu[g], gc[g]])
    summary: dict[str, Any] = {}
    for name, rs in runs.items():
        s = {"uss": stats([r["uss_idle_mb"] for r in rs]),
             "cpu": stats([r["cpu_idle_pct"] for r in rs]),
             "p95": stats([r["lat_p95_ms"] for r in rs])}  # fmt: skip
        for g in GROUP_ORDER:
            s[f"uss {g}"] = stats([_grouped(r["_uss_by_kind"])[g] for r in rs])
            s[f"cpu {g}"] = stats([_grouped(r["_cpu_by_kind"])[g] for r in rs])
        summary[name] = s
    ok, reasons = decide(summary[a.name], summary[b.name])
    lines = [f"# {b.name} vs {a.name} (pembanding)", "",
             f"{args.reps} ulangan per kondisi, selang-seling, daya AC. Kondisi:", "",
             f"- {a.name}: {a.describe()}", f"- {b.name}: {b.describe()}", "",
             "| metrik | " + " | ".join(f"{n} median (min-maks)" for n in runs) + " |",
             "| --- | --- | --- |"]  # fmt: skip
    for m in [
        "uss",
        "cpu",
        "p95",
        *(f"uss {g}" for g in GROUP_ORDER),
        *(f"cpu {g}" for g in GROUP_ORDER),
    ]:
        cells = [f"{summary[n][m]['median']:.2f} ({summary[n][m]['min']:.2f}-{summary[n][m]['max']:.2f})"
                 for n in runs]  # fmt: skip
        lines.append(f"| {m} | " + " | ".join(cells) + " |")
    if args.no_decision:
        lines += ["", "Info saja (pra-registrasi): tanpa keputusan."]
    else:
        lines += ["", "Aturan (docs/UI-PREVIEW-OPT.md):", *(f"- {r}" for r in reasons), "",
                  f"**{b.name} {'LEBIH BAIK' if ok else 'TIDAK lebih baik'} dari {a.name}.**"]  # fmt: skip
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({
        "a": a.describe(), "b": b.describe(), "reps": args.reps, "summary": summary,
        "better": None if args.no_decision else ok, "reasons": reasons,
        "environment": collect_environment(),
        "lowest_free_gb": lowest, "min_free_gb": args.min_free_gb,
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # fmt: skip
    print("\n".join(lines))
    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    """Keputusan dari run ab lengkap; FINAL = B bila lolos aturan, A bila tidak."""
    path = Path(args.summary)
    if (path.parent / "aborted.json").exists() or not path.exists():
        print(f"TIDAK BISA MEMUTUSKAN: run di {path.parent} tidak lengkap (aborted.json ada atau "
              "summary.json tidak ada)", flush=True)  # fmt: skip
        return 6
    data = json.loads(path.read_text(encoding="utf-8"))
    a, b = Condition.from_describe(data["a"]), Condition.from_describe(data["b"])
    with (path.parent / "per_run.csv").open(encoding="utf-8-sig") as f:
        per_run = list(csv.DictReader(f))
    counts = {n: sum(r["condition"] == n for r in per_run) for n in (a.name, b.name)}
    if any(n != data["reps"] for n in counts.values()):
        print(f"TIDAK BISA MEMUTUSKAN: ulangan {counts}, seharusnya {data['reps']}", flush=True)
        return 6
    ok, reasons = decide(data["summary"][a.name], data["summary"][b.name])
    final = replace(b if ok else a, name=args.name)
    result = {"a": a.describe(), "b": b.describe(), "reps": data["reps"], "better": ok,
              "reasons": reasons, "final": final.spec(), "rule": "docs/UI-PREVIEW-OPT.md"}  # fmt: skip
    text = json.dumps(result, ensure_ascii=False, indent=1) + "\n"
    (path.parent / "decision.json").write_text(text, encoding="utf-8")
    print(*(f"- {r}" for r in reasons), sep="\n")
    print(f"{b.name} {'LOLOS' if ok else 'TIDAK LOLOS'} aturan pra-registrasi vs {a.name}")
    print(f"FINAL={final.spec()}", flush=True)
    return 0


def _child_cmd(cond: Condition, config: Path, extra: tuple[str, ...]) -> list[str]:
    return [sys.executable, str(ROOT / "scripts/ui_bench.py"), "--child", "web", "--config",
            str(config), "--edge-switches", "on", *(f"--edge-extra={x}" for x in cond.edge),
            *extra]  # fmt: skip


def _dry_run(args: argparse.Namespace, children: dict[str, list[str]]) -> int:
    from mica.eval.environment import power_status

    for name, cmd in children.items():
        print(f"[dry-run] anak {name}: {subprocess.list2cmdline(cmd)}")
    for p in sorted(Path(args.out).iterdir()):
        print(f"[dry-run] disiapkan: {p}")
    free = psutil.virtual_memory().available / 2**30
    print(f"[dry-run] daya: {(power_status() or {}).get('source')} | memori tersedia {free:.2f} GB"
          f" (batas {args.min_free_gb:g} GB) | bench TIDAK dijalankan", flush=True)  # fmt: skip
    return 0


class _Tee:
    """--log: tulis ke konsol dan file sekaligus."""

    def __init__(self, *streams: Any) -> None:
        self.streams = streams

    def write(self, s: str) -> int:
        for st in self.streams:
            st.write(s)
            st.flush()
        return len(s)

    def flush(self) -> None:
        for st in self.streams:
            st.flush()


def _abort(out: Path, payload: dict[str, Any]) -> None:
    payload.setdefault("aborted", payload.get("reason") or "memori tersedia di bawah batas")
    (out / "aborted.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                                                 default=str) + "\n", encoding="utf-8")  # fmt: skip
    print(f"DIHENTIKAN: {payload['aborted']} (memori: {payload.get('memory')}); lihat "
          "aborted.json", flush=True)  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/ui_preview_opt.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grow")
    g.add_argument("--out", required=True)
    g.add_argument("--minutes", type=float, default=15.0)
    g.add_argument("--interval", type=float, default=30.0)
    g.add_argument("--condition", default="now:static=now")
    g.add_argument("--config", type=Path, default=ROOT / "config/dev.yaml")
    g.add_argument("--min-free-gb", type=float, default=2.0)
    g.add_argument("--cdp-gc", action="store_true",
                   help="setelah sampel terakhir: GC paksa di renderer, RAM renderer +30/+60 s")  # fmt: skip
    ab = sub.add_parser("ab")
    ab.add_argument("--out", required=True)
    ab.add_argument("--a", required=True)
    ab.add_argument("--b", required=True)
    ab.add_argument("--reps", type=int, default=10)
    ab.add_argument("--config", type=Path, default=ROOT / "config/dev.yaml")
    ab.add_argument("--min-free-gb", type=float, default=2.0)
    ab.add_argument("--no-decision", action="store_true")
    for p in (g, ab):
        p.add_argument("--dry-run", action="store_true")
    d = sub.add_parser("decide")
    d.add_argument("--summary", required=True)
    d.add_argument("--name", default="akhir")
    for p in (g, ab, d):
        p.add_argument("--log", type=Path)
    args = parser.parse_args(argv)
    if args.log is not None:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        log = args.log.open("a", encoding="utf-8")
        sys.stdout = _Tee(sys.__stdout__, log)  # type: ignore[assignment]
        sys.stderr = _Tee(sys.__stderr__, log)  # type: ignore[assignment]
    return {"grow": cmd_grow, "ab": cmd_ab, "decide": cmd_decide}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
