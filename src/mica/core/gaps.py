"""Jeda antar-giliran dari log giliran M-11 (validasi session.idle_reset_s, PROD-5).

docs/AMANDEMEN-2026-11-03.md bagian E: untuk setiap session_id dengan >= 2 giliran, jeda =
ts giliran ke-(i+1) dikurangi ts giliran ke-i (batas atas jeda pikir pengunjung, karena masih
memuat waktu proses giliran berikutnya). Hanya validasi: nilai idle_reset_s tidak diubah.

Hanya ts, session_id, dan turn_index yang dibaca; isi pertanyaan dan jawaban tidak pernah
disalin ke hasil.
"""

from __future__ import annotations

import csv
import itertools
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from mica.core.logging import _file_name


@dataclass(frozen=True)
class SessionGaps:
    session_id: str
    n_turns: int
    gaps_s: tuple[float, ...]


def _percentile(values: list[float] | tuple[float, ...], q: float) -> float | None:
    """Interpolasi linear (bawaan numpy), sama dengan mica.eval.metrics.percentile."""
    return float(np.percentile(np.asarray(values, dtype=np.float64), q)) if values else None


def read_turn_times(log_dir: Path, start: date, end: date) -> dict[str, list[tuple[datetime, int]]]:
    """session_id -> [(ts, turn_index)] dari turns-<tanggal>.jsonl start..end (inklusif)."""
    if start > end:
        raise ValueError("tanggal --from harus <= --to")
    out: dict[str, list[tuple[datetime, int]]] = {}
    day = start
    while day <= end:
        path = Path(log_dir) / _file_name("turns", day)
        if path.exists():
            for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    ts = datetime.fromisoformat(row["ts"])
                    session = str(row["session_id"])
                    index = int(row.get("turn_index") or 0)
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f"{path.as_posix()} baris {no}: bukan log giliran ({exc})")
                if ts.tzinfo is None:
                    raise ValueError(f"{path.as_posix()} baris {no}: ts tanpa zona waktu")
                out.setdefault(session, []).append((ts, index))
        day += timedelta(days=1)
    return out


def session_gaps(times: dict[str, list[tuple[datetime, int]]]) -> list[SessionGaps]:
    """Jeda per sesi, giliran diurutkan menurut ts (lalu turn_index)."""
    out = []
    for session in sorted(times):
        turns = sorted(times[session])
        gaps = tuple((b[0] - a[0]).total_seconds() for a, b in itertools.pairwise(turns))
        out.append(SessionGaps(session, len(turns), gaps))
    return out


@dataclass(frozen=True)
class GapSummary:
    n_sessions: int
    n_sessions_with_gaps: int
    n_gaps: int
    p50_s: float | None
    p95_s: float | None
    max_s: float | None
    idle_reset_s: float | None
    n_over_idle: int | None  # jeda > idle_reset_s (akan mereset sesi)


def summarize(sessions: list[SessionGaps], idle_reset_s: float | None = None) -> GapSummary:
    gaps = [g for s in sessions for g in s.gaps_s]
    return GapSummary(
        len(sessions), sum(bool(s.gaps_s) for s in sessions), len(gaps),
        _percentile(gaps, 50), _percentile(gaps, 95), max(gaps) if gaps else None,
        idle_reset_s, None if idle_reset_s is None else sum(g > idle_reset_s for g in gaps),
    )  # fmt: skip


def _f(x: float | None) -> str:
    return "-" if x is None else f"{x:.1f}"


def format_report(sessions: list[SessionGaps], summary: GapSummary) -> str:
    lines = [
        "Jeda antar-giliran (detik; batas atas jeda pikir, docs/AMANDEMEN-2026-11-03.md E)",
        "session_id | giliran | jeda | median | p95 | maks",
    ]
    for s in sessions:
        lines.append(f"{s.session_id} | {s.n_turns} | {len(s.gaps_s)} | "
                     f"{_f(_percentile(s.gaps_s, 50))} | {_f(_percentile(s.gaps_s, 95))} | "
                     f"{_f(max(s.gaps_s) if s.gaps_s else None)}")  # fmt: skip
    lines += [
        "",
        (
            f"Sesi: {summary.n_sessions} ({summary.n_sessions_with_gaps} dengan >= 2 giliran); "
            f"jeda: {summary.n_gaps}; median {_f(summary.p50_s)}, p95 {_f(summary.p95_s)}, "
            f"maks {_f(summary.max_s)}"
        ),
    ]
    if summary.idle_reset_s is not None:
        lines.append(f"Jeda > idle_reset_s ({summary.idle_reset_s:g} s): {summary.n_over_idle}"
                     " (validasi saja; nilai tidak diubah)")  # fmt: skip
    if summary.n_gaps == 0:
        lines.append("Tidak ada sesi dengan >= 2 giliran: jeda tidak bisa dihitung.")
    return "\n".join(lines)


def write_csv(path: Path, sessions: list[SessionGaps]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["session_id", "giliran", "jeda", "median_s", "p95_s", "maks_s"])
        for s in sessions:
            p50, p95 = _percentile(s.gaps_s, 50), _percentile(s.gaps_s, 95)
            writer.writerow([s.session_id, s.n_turns, len(s.gaps_s),
                             "" if p50 is None else f"{p50:.3f}",
                             "" if p95 is None else f"{p95:.3f}",
                             f"{max(s.gaps_s):.3f}" if s.gaps_s else ""])  # fmt: skip
