"""M-11 InteractionLog: satu baris JSON per pertanyaan dan per event kunjungan (SDD 6.2).

Tidak pernah dicatat: gambar, audio, embedding wajah, nama warna pakaian, alamat IP, dan teks
pertanyaan sebelum disamarkan (N-08, N-09). Retensi log masih TBD (SDD 6.4), jadi modul ini
tidak menghapus apa pun.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from mica.core.types import ScrubbedText

LogKind = Literal["turns", "events"]

# Urutan kolom timings di CSV mengikuti SDD 6.2; tahap lain ditaruh setelahnya.
TIMING_KEYS = ("vad", "stt", "retrieval", "llm", "check", "tts_first_audio", "total")


def _require_aware(ts: datetime) -> None:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("ts harus memiliki zona waktu")


@dataclass(frozen=True)
class TurnRecord:
    ts: datetime
    session_id: str
    turn_index: int
    input_mode: Literal["voice", "text"]
    question: ScrubbedText
    retrieved: tuple[dict[str, Any], ...]  # chunk_id, skor, peringkat per retriever
    gate: dict[str, Any]  # keputusan dan skor teratas
    llm_provider: str | None
    llm_status: str | None
    final_status: str
    answer: str
    sources: tuple[str, ...]  # chunk_id sumber
    fact_check: dict[str, Any]  # angka yang dicek dan yang gagal
    timings: dict[str, float]
    kb_id: str
    config_hash: str
    app_version: str

    def __post_init__(self) -> None:
        _require_aware(self.ts)


@dataclass(frozen=True)
class EventRecord:
    ts: datetime
    session_id: str
    event: str  # misalnya person_arrived, greeted, person_left, idle_reset, camera_down
    greeted_with_color: bool  # nama warnanya tidak dicatat
    latency_s: float | None

    def __post_init__(self) -> None:
        _require_aware(self.ts)


def _to_json_line(record: TurnRecord | EventRecord) -> str:
    data = dataclasses.asdict(record)
    data["ts"] = record.ts.isoformat()
    return json.dumps(data, ensure_ascii=False)


def _file_name(kind: LogKind, day: date) -> str:
    return f"{kind}-{day.isoformat()}.jsonl"


class InteractionLog:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = Path(log_dir)
        self._lock = threading.Lock()

    def log_turn(self, record: TurnRecord) -> None:
        if not isinstance(record.question, ScrubbedText):
            raise TypeError("TurnRecord.question harus ScrubbedText (lewati scrub_pii dulu)")
        self._append("turns", record)

    def log_event(self, record: EventRecord) -> None:
        self._append("events", record)

    def _append(self, kind: LogKind, record: TurnRecord | EventRecord) -> None:
        line = _to_json_line(record)
        # tanggal file = tanggal lokal dari ts
        path = self.log_dir / _file_name(kind, record.ts.astimezone().date())
        with self._lock:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
                f.flush()


def _flatten(row: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in row.items():
        if key == "timings" and isinstance(value, dict):
            for stage, seconds in value.items():
                flat[f"timings.{stage}"] = seconds
        elif isinstance(value, (dict, list)):
            flat[key] = json.dumps(value, ensure_ascii=False)
        else:
            flat[key] = value
    return flat


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for row in rows:
        for key in row:
            seen.setdefault(key)
    columns = [c for c in seen if not c.startswith("timings.")]
    timing_cols = [c for c in seen if c.startswith("timings.")]
    known = [f"timings.{k}" for k in TIMING_KEYS if f"timings.{k}" in seen]
    return columns + known + [c for c in timing_cols if c not in known]


def export(
    log_dir: Path, start: date, end: date, out: Path, kind: LogKind = "turns"
) -> int:
    """Ekspor log bertanggal start..end (inklusif) ke CSV. Mengembalikan jumlah baris."""
    if start > end:
        raise ValueError("tanggal --from harus <= --to")
    rows: list[dict[str, Any]] = []
    day = start
    while day <= end:
        path = Path(log_dir) / _file_name(kind, day)
        if path.exists():
            with path.open(encoding="utf-8") as f:
                rows += [_flatten(json.loads(line)) for line in f if line.strip()]
        day += timedelta(days=1)

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_columns(rows), restval="")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
