"""python -m mica check: pemeriksaan sebelum kiosk dinyalakan, untuk staf.

Tidak membuka kamera, mikrofon, atau speaker dan tidak memanggil Groq. Memeriksa:
config (M-01; di kiosk semua null wajib terisi), file model dan sha256, KB aktif dan
embedder-nya, keberadaan GROQ_API_KEY (nilainya tidak pernah dicetak), daftar perangkat
audio dari sounddevice.query_devices() (tanpa membuka stream), kamera (hanya "diperiksa saat
start"), folder log bisa ditulis, bila ui.backend: web, msedge.exe ditemukan (Edge tidak
dijalankan), dan tidak ada pertanyaan set uji (data/eval/official/test.jsonl) maupun set dev
(data/eval/questions.jsonl, official/dev.jsonl) yang identik atau mirip dengan teks
ui.suggestions/ui.topics (docs/DATASET.md, larangan bocor). Kode keluar 0 bila semua OK, 1 bila ada GAGAL.
"""

from __future__ import annotations

import argparse
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from mica.config import ConfigError, Settings, load_settings, missing_kiosk_fields

DEFAULT_CONFIG = Path("config/kiosk.yaml")
DEFAULT_ENV = Path(".env")
Status = Literal["OK", "GAGAL", "PERINGATAN", "INFO"]  # PERINGATAN tidak menggagalkan check
SETUP_HINT = "jalankan: python -m mica setup"


@dataclass(frozen=True)
class CheckRow:
    item: str
    status: Status
    message: str


def _query_devices() -> Any:
    import sounddevice as sd

    return sd.query_devices()


def _check_config(path: Path, env_file: Path | None) -> tuple[CheckRow, Settings | None]:
    try:
        settings = load_settings(path, env_file)
        return CheckRow("config", "OK", f"{path.as_posix()} valid (mode {settings.app.mode})"), \
            settings  # fmt: skip
    except ConfigError as first:
        try:
            settings = load_settings(path, env_file, require_complete=False)
        except ConfigError:
            return CheckRow("config", "GAGAL", f"{path.as_posix()}: {first}"), None
    missing = missing_kiosk_fields(settings)
    return CheckRow("config", "GAGAL", f"mode kiosk: {len(missing)} kunci belum diisi: "
                    + ", ".join(missing)), settings  # fmt: skip


def _check_models(settings: Settings, models_dir: Path) -> list[CheckRow]:
    from mica.setup import components, verify

    rows = []
    for c in components(settings, models_dir):
        if not c.used:
            continue
        ok, message = verify(c)
        if not ok and not c.blocked:  # blocked = config yang harus diisi, bukan unduhan
            message = f"{message}; {SETUP_HINT}"
        rows.append(CheckRow(f"model {c.name}", "OK" if ok else "GAGAL", message))
    return rows


def _check_kb(settings: Settings, kb_root: Path) -> CheckRow:
    from mica.kb.index import KB_FILES, KbLoadError, read_manifest

    kb_id = settings.kb.active_id
    if "<" in kb_id:
        return CheckRow("KB aktif", "GAGAL", f"kb.active_id belum diisi ({kb_id})")
    folder = Path(kb_root) / kb_id
    missing = [f for f in KB_FILES if not (folder / f).is_file()]
    if missing:
        return CheckRow("KB aktif", "GAGAL", f"{folder.as_posix()}: file hilang {missing}")
    try:
        manifest = read_manifest(folder)
    except KbLoadError as exc:
        return CheckRow("KB aktif", "GAGAL", str(exc))
    emb, want = manifest.get("embedder", {}), settings.kb.embedder
    if emb.get("model") != want.model or emb.get("revision") != want.revision:
        return CheckRow("KB aktif", "GAGAL",
                        f"{kb_id} dibuat dengan {emb.get('model')}@{emb.get('revision')}, "
                        f"config meminta {want.model}@{want.revision}; bangun ulang KB")  # fmt: skip
    return CheckRow("KB aktif", "OK", f"{kb_id} ({manifest.get('n_chunks')} potongan, "
                    f"embedder {want.model}@{str(want.revision)[:8]})")  # fmt: skip


def _check_groq(settings: Settings) -> CheckRow:
    uses_groq = any(e.startswith("groq:") for e in settings.llm.chain)
    if not uses_groq:
        return CheckRow("GROQ_API_KEY", "INFO", "llm.chain tidak memakai Groq")
    if settings.api_keys.groq is None:
        return CheckRow("GROQ_API_KEY", "GAGAL", "tidak ada; isi GROQ_API_KEY di file .env")
    return CheckRow("GROQ_API_KEY", "OK", "ada (nilai tidak ditampilkan)")


def _check_audio(query: Callable[[], Any]) -> CheckRow:
    try:
        devices = list(query())
    except Exception as exc:  # noqa: BLE001 - PortAudio melempar berbagai jenis error
        return CheckRow("perangkat audio", "GAGAL", f"tidak bisa membaca daftar perangkat ({exc})")
    inputs = [d["name"] for d in devices if d.get("max_input_channels", 0) > 0]
    outputs = [d["name"] for d in devices if d.get("max_output_channels", 0) > 0]
    message = f"input {len(inputs)}, output {len(outputs)}"
    if not inputs or not outputs:
        lack = " dan ".join(n for n, xs in (("mikrofon", inputs), ("speaker", outputs)) if not xs)
        return CheckRow("perangkat audio", "PERINGATAN",
                        f"{message}; {lack} tidak ditemukan, kiosk tetap bisa dipakai lewat teks")  # fmt: skip
    return CheckRow("perangkat audio", "OK", message)


def _check_logs(settings: Settings) -> CheckRow:
    folder = Path(settings.logging.dir)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".check-", delete=True):
            pass
    except OSError as exc:
        return CheckRow("folder log", "GAGAL", f"{folder.as_posix()} tidak bisa ditulis ({exc})")
    return CheckRow("folder log", "OK", f"{folder.as_posix()} bisa ditulis")


def _check_browser(edge_paths: tuple[Path, ...]) -> CheckRow:
    """Hanya untuk ui.backend: web; Edge tidak dijalankan, hanya dicari file-nya."""
    from mica.webui.browser import EdgeMissing, find_edge

    try:
        return CheckRow("Microsoft Edge", "OK", f"{find_edge(edge_paths)} (ui.backend: web)")
    except EdgeMissing as exc:
        return CheckRow("Microsoft Edge", "GAGAL", f"{exc}; ui.backend: web butuh Edge")


# Langkah 53: teks UI dianggap mirip bila Jaccard token (setelah normalize_question) >= nilai
# ini. NILAI PENGAMAN PENGEMBANG, bukan hasil eksperimen; pertanyaan chip saat ini <= 0,33.
LEAK_TOKEN_JACCARD = 0.5


def token_jaccard(a: str, b: str) -> float:
    from mica.eval.official import normalize_question

    ta, tb = set(normalize_question(a).split()), set(normalize_question(b).split())
    return len(ta & tb) / len(ta | tb) if ta | tb else 1.0


def ui_texts(settings: Settings) -> list[str]:
    """Teks yang bisa dikirim UI tanpa diketik pengunjung: saran, label, dan question topik."""
    ui = settings.ui
    return ([h for hs in ui.suggestions.values() for h in hs]
            + list(ui.topic_labels) + [t.question for t in ui.topics])  # fmt: skip


def find_leaks(hints: list[str], questions: list[dict[str, Any]]) -> list[tuple[str, str, float]]:
    """(qid, teks UI, skor) untuk setiap pasangan identik setelah normalisasi atau mirip."""
    from mica.eval.official import normalize_question

    found = []
    for q in questions:
        for hint in hints:
            same = normalize_question(hint) == normalize_question(q["question"])
            score = 1.0 if same else token_jaccard(hint, q["question"])
            if score >= LEAK_TOKEN_JACCARD:
                found.append((q["qid"], hint, score))
    return found


def _check_leak(settings: Settings, item: str, sets: tuple[Path, ...]) -> CheckRow | None:
    """Pertanyaan set evaluasi tidak boleh identik atau mirip dengan teks yang dikirim UI
    (ui.suggestions, label dan question ui.topics), docs/DATASET.md larangan bocor."""
    present = [p for p in sets if p.is_file()]
    if not present:
        return None
    from mica.eval.dataset import DatasetError, load_questions

    questions: list[dict[str, Any]] = []
    for path in present:
        try:
            questions += load_questions(path)
        except DatasetError as exc:
            return CheckRow(item, "GAGAL", f"{path.as_posix()} tidak terbaca ({exc})")
    leaks = find_leaks(ui_texts(settings), questions)
    if leaks:
        detail = "; ".join(f"{qid} ~ {hint!r} ({score:.2f})" for qid, hint, score in leaks)
        return CheckRow(item, "GAGAL", f"{len(leaks)} teks ui.suggestions/ui.topics identik atau "
                        f"mirip pertanyaan evaluasi: {detail} (tulis ulang di config)")  # fmt: skip
    return CheckRow(item, "OK", f"{len(questions)} pertanyaan tidak identik/mirip dengan "
                    f"ui.suggestions/ui.topics (Jaccard < {LEAK_TOKEN_JACCARD})")  # fmt: skip


def _check_test_leak(settings: Settings, test_set: Path) -> CheckRow | None:
    return _check_leak(settings, "kebocoran set uji", (test_set,))


def run_check(
    config: Path = DEFAULT_CONFIG,
    env_file: Path | None = DEFAULT_ENV,
    models_dir: Path = Path("models"),
    kb_root: Path = Path("data/kb"),
    query_devices: Callable[[], Any] = _query_devices,
    edge_paths: tuple[Path, ...] | None = None,
    test_set: Path = Path("data/eval/official/test.jsonl"),
    dev_sets: tuple[Path, ...] = (
        Path("data/eval/questions.jsonl"),
        Path("data/eval/official/dev.jsonl"),
    ),
) -> tuple[list[CheckRow], Settings | None]:
    """Settings dikembalikan bila semua OK (dipakai python -m mica), selain itu tetap
    dikembalikan bila terbaca supaya pemanggil bisa menampilkan detail."""
    config_row, settings = _check_config(Path(config), env_file)
    rows = [config_row]
    if settings is None:
        skipped = "dilewati (config tidak terbaca)"
        rows += [CheckRow(i, "GAGAL", skipped) for i in ("model", "KB aktif", "GROQ_API_KEY")]
    else:
        rows += _check_models(settings, Path(models_dir))
        rows.append(_check_kb(settings, Path(kb_root)))
        rows.append(_check_groq(settings))
    rows.append(_check_audio(query_devices))
    rows.append(CheckRow("kamera", "INFO", "diperiksa saat start (tidak dibuka oleh check)"))
    if settings is not None:
        rows.append(_check_logs(settings))
        if settings.ui.backend == "web":
            from mica.webui.browser import EDGE_PATHS

            rows.append(_check_browser(EDGE_PATHS if edge_paths is None else edge_paths))
        for leak in (_check_test_leak(settings, Path(test_set)),
                     _check_leak(settings, "kebocoran set dev", tuple(map(Path, dev_sets)))):  # fmt: skip
            if leak is not None:
                rows.append(leak)
    return rows, settings


def failed(rows: list[CheckRow]) -> bool:
    return any(r.status == "GAGAL" for r in rows)


def format_table(rows: list[CheckRow]) -> str:
    width = max(len(r.item) for r in rows)
    lines = [f"{'pemeriksaan'.ljust(width)}  {'status'.ljust(10)}  keterangan"]
    lines += [f"{r.item.ljust(width)}  {r.status.ljust(10)}  {r.message}" for r in rows]
    if failed(rows):
        verdict = "ADA GAGAL: perbaiki baris GAGAL sebelum menjalankan kiosk"
    elif any(r.status == "PERINGATAN" for r in rows):
        verdict = "SIAP DENGAN PERINGATAN: kiosk bisa dijalankan (python -m mica); baca PERINGATAN"
    else:
        verdict = "SEMUA OK: kiosk siap dijalankan (python -m mica)"
    return "\n".join([*lines, "", verdict])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mica check")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    args = parser.parse_args(argv)
    rows, _settings = run_check(args.config, args.env_file)
    print(format_table(rows))
    return 1 if failed(rows) else 0
