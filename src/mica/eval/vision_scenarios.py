"""M-12: python -m mica.eval vision-scenarios (E-07 bagian skenario). Aturan di docs/E-07.md
(pra-registrasi 18 Okt 2026).

Dataset data/eval/vision_scenarios/<nama>/: klip video, manifest.jsonl (id, file, persetujuan),
annotations.jsonl (clip, orang, jenis lewat|berhenti, masuk, berhenti, pergi). Klip tidak
di-commit dan frame hanya ada di memori (N-08).

Per klip: pembaca video menggantikan kamera; detektor M-07 (UltralyticsDetector + ByteTrack)
dijalankan sekali pada jadwal VisionLoop (vision.fps_idle, waktu = indeks frame / fps klip),
lalu track yang sama diputar ulang lewat PresenceTracker (sinyal shoulder_width, carry-over
yang sama) untuk setiap kombinasi dwell_s x leave_s x min_shoulder_ratio. Sapaan dari
PersonArrived dengan aturan cooldown M-09 (M-09 tidak dijalankan), lalu dibandingkan dengan
anotasi. Pemenang dipilih mekanis (verdict.md).
"""

from __future__ import annotations

import csv
import itertools
import json
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from mica.eval.metrics import percentile
from mica.eval.vision import VisionEvalError, read_manifest
from mica.vision.detector import PersonDetector
from mica.vision.presence import PresenceTracker, ShoulderWidthSignal
from mica.vision.types import PersonArrived, PersonLeft, PersonTrack

EXPERIMENT = "E-07"
GRIDS: dict[str, dict[str, tuple[float, ...]]] = {
    "default": {  # docs/E-07.md
        "dwell_s": (1.0, 2.0, 3.0),
        "leave_s": (2.0, 3.0, 5.0),
        "min_shoulder_ratio": (0.18, 0.22, 0.26),
        "regreet_cooldown_s": (0.0, 30.0, 60.0),
    }
}
MIN_KP_CONF = 0.5  # keypoint_torso.min_kp_conf: nilai coba SDD bagian 12, tetap (docs/E-07.md)
TTS_RESERVE_S = 1.0  # dari anggaran "cek fakta dan TTS kalimat pertama" SDD 3.3
GREETING_LIMIT_S = 3.0  # N-06
KINDS = ("lewat", "berhenti")
E07_SCENARIO_RULE = (
    "Aturan E-07 skenario (docs/E-07.md, 18 Okt 2026): lolos bila p95 waktu sapaan + 1 s "
    "cadangan TTS <= 3 s (N-06) dan sapaan ganda = 0 (F-04); dari yang lolos pilih (terlewat + "
    "salah) terkecil; seri -> dwell_s lebih besar, lalu regreet_cooldown_s lebih besar, lalu "
    "leave_s lebih besar, lalu min_shoulder_ratio lebih besar."
)

Detections = list[tuple[float, list[PersonTrack], tuple[int, ...]]]  # (t, track, bentuk frame)


# --- dataset ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Clip:
    id: str
    file: Path


@dataclass(frozen=True)
class Appearance:
    clip: str
    person: str
    kind: str  # lewat | berhenti
    enter: float
    stop: float | None
    leave: float


def load_clips(dataset: Path) -> list[Clip]:
    dataset = Path(dataset)
    clips = []
    for row in read_manifest(dataset / "manifest.jsonl"):
        path = dataset / row["file"]
        if not path.is_file():
            raise VisionEvalError(f"{row['id']}: klip {path.as_posix()} tidak ada")
        clips.append(Clip(str(row["id"]), path))
    return clips


def load_annotations(path: Path, clip_ids: Iterable[str]) -> list[Appearance]:
    path = Path(path)
    if not path.is_file():
        raise VisionEvalError(f"{path.as_posix()} tidak ada")
    ids = set(clip_ids)
    out: list[Appearance] = []
    errors: list[str] = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"baris {no}: bukan JSON ({exc.msg})")
            continue
        where = f"baris {no}"
        kind = row.get("jenis")
        try:
            enter, leave = float(row["masuk"]), float(row["pergi"])
            stop = float(row["berhenti"]) if kind == "berhenti" else None
        except (KeyError, TypeError, ValueError):
            errors.append(f"{where}: masuk, pergi (dan berhenti untuk jenis berhenti) wajib angka")
            continue
        if row.get("clip") not in ids:
            errors.append(f"{where}: clip {row.get('clip')!r} tidak ada di manifest")
        elif kind not in KINDS:
            errors.append(f"{where}: jenis {kind!r} bukan salah satu {KINDS}")
        elif not row.get("orang"):
            errors.append(f"{where}: orang wajib")
        elif not enter <= (stop if stop is not None else enter) <= leave:
            errors.append(f"{where}: harus masuk <= berhenti <= pergi")
        else:
            out.append(Appearance(row["clip"], str(row["orang"]), kind, enter, stop, leave))
    if errors:
        raise VisionEvalError(f"{path.as_posix()}:\n  " + "\n  ".join(errors))
    return out


def read_video(path: Path) -> Iterator[tuple[float, np.ndarray]]:
    """(detik klip = indeks frame / fps, frame BGR) berurutan; frame hanya di memori (N-08)."""
    import cv2

    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise VisionEvalError(f"{Path(path).as_posix()}: klip tidak bisa dibuka")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not fps > 0:
            raise VisionEvalError(f"{Path(path).as_posix()}: fps klip tidak diketahui")
        index = 0
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                return
            yield index / fps, frame
            index += 1
    finally:
        capture.release()


# --- deteksi dan replay -------------------------------------------------------------------


def detect_clip(
    frames: Iterable[tuple[float, np.ndarray]],
    detector: PersonDetector,
    fps: float,
    clock: Callable[[], float] | None = None,
) -> tuple[Detections, list[float]]:
    """Deteksi dengan jadwal VisionLoop.run pada laju fps. -> (deteksi, waktu dinding/frame)."""
    import time

    clock = clock or time.perf_counter
    out: Detections = []
    times: list[float] = []
    next_detect: float | None = None
    for t, frame in frames:
        if next_detect is None:
            next_detect = t
        if t >= next_detect - 1e-6:
            start = clock()
            tracks = detector.detect_and_track(frame)
            times.append(clock() - start)
            out.append((t, tracks, tuple(frame.shape)))
            next_detect = max(next_detect + 1.0 / fps, t)
        del frame  # N-08
    return out, times


def replay(
    detections: Detections, dwell_s: float, leave_s: float, min_ratio: float, min_kp_conf: float
) -> list[PersonArrived | PersonLeft]:
    """PresenceTracker M-07 yang sama (sinyal shoulder_width), tanpa warna."""
    tracker = PresenceTracker(dwell_s, leave_s, min_ratio, ShoulderWidthSignal(min_kp_conf))
    events: list[PersonArrived | PersonLeft] = []
    for t, tracks, shape in detections:
        for e in tracker.update(tracks, shape, t):
            if isinstance(e, PersonArrived | PersonLeft):
                events.append(e)
    return events


def greetings(events: Sequence[PersonArrived | PersonLeft], cooldown_s: float) -> list[float]:
    """Aturan M-09 (T01/T02): PersonArrived disapa bila t >= PersonLeft terakhir + cooldown."""
    until = float("-inf")
    out = []
    for e in events:
        if isinstance(e, PersonLeft):
            until = e.t + cooldown_s
        elif e.t >= until:
            out.append(e.t)
    return out


# --- skor ---------------------------------------------------------------------------------


@dataclass
class Score:
    correct: int = 0
    missed: int = 0
    false_pass: int = 0  # sapaan di kemunculan lewat
    false_outside: int = 0  # sapaan di luar semua jendela anotasi
    double: int = 0
    latencies: list[float] = field(default_factory=list)

    @property
    def false(self) -> int:
        return self.false_pass + self.false_outside

    def add(self, other: Score) -> None:
        self.correct += other.correct
        self.missed += other.missed
        self.false_pass += other.false_pass
        self.false_outside += other.false_outside
        self.double += other.double
        self.latencies += other.latencies


def expected(appearances: Sequence[Appearance], cooldown_s: float) -> dict[int, bool]:
    """Indeks kemunculan berhenti -> wajib disapa (False = kembali dalam cooldown)."""
    out: dict[int, bool] = {}
    last_leave: dict[str, float] = {}
    order = sorted(range(len(appearances)), key=lambda i: appearances[i].enter)
    for i in order:
        a = appearances[i]
        if a.kind == "berhenti":
            assert a.stop is not None
            prev = last_leave.get(a.person)
            out[i] = prev is None or a.stop - prev > cooldown_s
            last_leave[a.person] = max(a.leave, prev or a.leave)
    return out


def owner(t: float, appearances: Sequence[Appearance]) -> int | None:
    """Kemunculan pemilik sapaan pada detik t (docs/E-07.md)."""
    inside = [i for i, a in enumerate(appearances) if a.enter <= t <= a.leave]
    if not inside:
        return None
    stops = [i for i in inside if appearances[i].kind == "berhenti"]
    if not stops:
        return inside[0]
    before = [i for i in stops if (appearances[i].stop or 0.0) <= t]
    if before:
        return max(before, key=lambda i: appearances[i].stop or 0.0)
    return min(stops, key=lambda i: appearances[i].stop or 0.0)


def score_clip(
    greet_times: Sequence[float], appearances: Sequence[Appearance], cooldown_s: float
) -> Score:
    score = Score()
    must = expected(appearances, cooldown_s)
    got: dict[int, list[float]] = {}
    for t in greet_times:
        i = owner(t, appearances)
        if i is None:
            score.false_outside += 1
        elif appearances[i].kind == "lewat":
            score.false_pass += 1
        else:
            got.setdefault(i, []).append(t)
    for i, required in must.items():
        times = got.get(i, [])
        if not required:
            score.double += len(times)
        elif times:
            score.correct += 1
            score.double += len(times) - 1
            score.latencies.append(times[0] - (appearances[i].stop or 0.0))
        else:
            score.missed += 1
    return score


# --- grid dan aturan ----------------------------------------------------------------------


@dataclass
class GridRow:
    dwell_s: float
    leave_s: float
    min_shoulder_ratio: float
    regreet_cooldown_s: float
    score: Score
    n_required: int

    @property
    def p50(self) -> float | None:
        return percentile(self.score.latencies, 50) if self.score.latencies else None

    @property
    def p95(self) -> float | None:
        return percentile(self.score.latencies, 95) if self.score.latencies else None

    @property
    def passes(self) -> bool:
        return (
            self.p95 is not None
            and self.p95 + TTS_RESERVE_S <= GREETING_LIMIT_S
            and self.score.double == 0
        )

    @property
    def errors(self) -> int:
        return self.score.missed + self.score.false

    def key(self) -> tuple[float, float, float, float]:
        return (self.dwell_s, self.leave_s, self.min_shoulder_ratio, self.regreet_cooldown_s)

    def row(self) -> dict[str, Any]:
        def f(x: float | None) -> str:
            return "" if x is None else f"{x:.3f}"

        s = self.score
        return {
            "dwell_s": self.dwell_s,
            "leave_s": self.leave_s,
            "min_shoulder_ratio": self.min_shoulder_ratio,
            "regreet_cooldown_s": self.regreet_cooldown_s,
            "n_wajib_disapa": self.n_required,
            "sapaan_benar": s.correct,
            "sapaan_terlewat": s.missed,
            "sapaan_salah": s.false,
            "sapaan_salah_lewat": s.false_pass,
            "sapaan_salah_luar_anotasi": s.false_outside,
            "sapaan_ganda": s.double,
            "waktu_sapaan_p50_s": f(self.p50),
            "waktu_sapaan_p95_s": f(self.p95),
            "terlewat_plus_salah": self.errors,
            "lolos": int(self.passes),
        }


def evaluate_grid(
    detections: dict[str, Detections],
    appearances: Sequence[Appearance],
    grid: dict[str, tuple[float, ...]],
    min_kp_conf: float,
) -> list[GridRow]:
    """Replay PresenceTracker per (dwell, leave, rasio); cooldown hanya memengaruhi sapaan."""
    by_clip = {c: [a for a in appearances if a.clip == c] for c in detections}
    rows = []
    for dwell, leave, ratio in itertools.product(
        grid["dwell_s"], grid["leave_s"], grid["min_shoulder_ratio"]
    ):
        events = {c: replay(d, dwell, leave, ratio, min_kp_conf) for c, d in detections.items()}
        for cooldown in grid["regreet_cooldown_s"]:
            total = Score()
            required = 0
            for c, evs in events.items():
                total.add(score_clip(greetings(evs, cooldown), by_clip[c], cooldown))
                required += sum(expected(by_clip[c], cooldown).values())
            rows.append(GridRow(dwell, leave, ratio, cooldown, total, required))
    return rows


def select(rows: Sequence[GridRow]) -> GridRow | None:
    """Aturan E-07 skenario (docs/E-07.md), diterapkan mekanis."""
    passing = [r for r in rows if r.passes]
    if not passing:
        return None
    return min(
        passing,
        key=lambda r: (
            r.errors,
            -r.dwell_s,
            -r.regreet_cooldown_s,
            -r.leave_s,
            -r.min_shoulder_ratio,
        ),
    )


def verdict_markdown(rows: Sequence[GridRow], winner: GridRow | None, info: dict[str, Any]) -> str:
    lines = ["# E-07 verdict: skenario sapaan", ""]
    if info.get("note"):
        lines += [f"Catatan: {info['note']}", ""]
    setup = (
        f"Model {info.get('model')}, conf {info.get('conf')}, "
        f"min_kp_conf {info.get('min_kp_conf')}, deteksi pada {info.get('fps_detect')} fps; "
        f"{len(rows)} kombinasi, {sum(r.passes for r in rows)} lolos."
    )
    lines += [E07_SCENARIO_RULE, "", setup, ""]
    ranked = sorted(rows, key=lambda r: (not r.passes, r.errors, r.key()))[:10]
    lines += [
        "| dwell_s | leave_s | rasio bahu | cooldown | benar | terlewat | salah | ganda | p95 s | lolos |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in ranked:
        x = r.row()
        lines.append(
            f"| {r.dwell_s:g} | {r.leave_s:g} | {r.min_shoulder_ratio:g} | "
            f"{r.regreet_cooldown_s:g} | {x['sapaan_benar']} | {x['sapaan_terlewat']} | "
            f"{x['sapaan_salah']} | {x['sapaan_ganda']} | {x['waktu_sapaan_p95_s'] or '-'} | "
            f"{'ya' if r.passes else 'tidak'} |"
        )
    lines += ["", "(10 baris teratas; semua kombinasi di grid.csv)", ""]
    if winner is None:
        lines.append("**Tidak ada kombinasi yang lolos; tidak ada pemenang.**")
    else:
        lines.append(
            f"**vision.dwell_s = {winner.dwell_s:g}, vision.leave_s = {winner.leave_s:g}, "
            f"vision.min_shoulder_ratio = {winner.min_shoulder_ratio:g}, "
            f"session.regreet_cooldown_s = {winner.regreet_cooldown_s:g}**"
        )
    return "\n".join(lines) + "\n"


def run_scenarios(
    clips: Sequence[Clip],
    appearances: Sequence[Appearance],
    make_detector: Callable[[], PersonDetector],
    grid: dict[str, tuple[float, ...]],
    fps_detect: float,
    run_dir: Path,
    info: dict[str, Any],
    frames: Callable[[Clip], Iterable[tuple[float, np.ndarray]]] | None = None,
    min_kp_conf: float = MIN_KP_CONF,
    progress: Callable[[str], None] = print,
) -> tuple[list[GridRow], GridRow | None]:
    """Detektor baru per klip (tracker mulai bersih, seperti proses kamera baru). Tulis run_dir."""
    frames = frames or (lambda c: read_video(c.file))
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    detections: dict[str, Detections] = {}
    times: list[float] = []
    per_clip = []
    for clip in clips:
        dets, clip_times = detect_clip(frames(clip), make_detector(), fps_detect)
        detections[clip.id] = dets
        times += clip_times
        per_clip.append(
            {
                "clip": clip.id,
                "n_deteksi": len(dets),
                "durasi_s": f"{dets[-1][0]:.2f}" if dets else "",
                "n_kemunculan": sum(a.clip == clip.id for a in appearances),
            }
        )
        progress(f"  {clip.id}: {len(dets)} frame dideteksi")
    rows = evaluate_grid(detections, appearances, grid, min_kp_conf)
    winner = select(rows)
    meta = {**info, "min_kp_conf": min_kp_conf, "fps_detect": fps_detect}
    with (run_dir / "grid.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].row()))
        writer.writeheader()
        writer.writerows(r.row() for r in rows)
    with (run_dir / "per_clip.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["clip", "n_deteksi", "durasi_s", "n_kemunculan"])
        writer.writeheader()
        writer.writerows(per_clip)
    (run_dir / "verdict.md").write_text(verdict_markdown(rows, winner, meta), encoding="utf-8")
    payload = {
        **meta,
        "experiment": EXPERIMENT,
        "rule": E07_SCENARIO_RULE,
        "grid": {k: list(v) for k, v in grid.items()},
        "tts_reserve_s": TTS_RESERVE_S,
        "greeting_limit_s": GREETING_LIMIT_S,
        "pipeline": "pembaca video -> detektor M-07 (tracker baru per klip) pada jadwal "
        "VisionLoop -> PresenceTracker shoulder_width (carry-over sama); sapaan = PersonArrived "
        "dengan cooldown M-09; waktu = indeks frame / fps klip",
        "detect_time_s": {
            "p50": percentile(times, 50) if times else None,
            "p95": percentile(times, 95) if times else None,
            "n": len(times),
        },
        "winner": winner.row() if winner else None,
    }
    (run_dir / "run.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return rows, winner
