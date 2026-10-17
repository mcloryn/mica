"""Set evaluasi resmi (docs/DATASET.md): pembagian berstrata, kunci set uji, dan penjaga --split.

- split_questions(): 30% dev-resmi / 70% uji per strata, seed dari docs/DATASET.md.
- lock_dataset(): menambah versi ke data/eval/LOCK (JSON, riwayat versi).
- lock_status(): versi berlaku dan apakah hash file cocok.
- check_split(): dipanggil setiap perintah eval; test hanya dengan LOCK cocok dan KB official,
  dev menolak dataset yang tercatat di LOCK.
- normalize_question(): normalisasi untuk cek kebocoran (huruf kecil, tanpa tanda baca).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from mica.eval.dataset import Question, load_questions, save_questions

ROOT = Path(__file__).resolve().parents[3]
DATASET_DOC = ROOT / "docs" / "DATASET.md"
DEFAULT_LOCK = Path("data/eval/LOCK")
OFFICIAL_DIR = Path("data/eval/official")
SEED_PATTERN = re.compile(r"^- Seed pembagian: `(\d+)`\s*$", re.MULTILINE)
DEV_SHARE = (3, 10)  # 30% dev-resmi (K-5); pembulatan setengah ke atas
LOCK_FORMAT = 1


class OfficialDatasetError(Exception):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_seed(doc: Path = DATASET_DOC) -> int:
    """Seed pembagian ditulis di docs/DATASET.md (pra-registrasi), bukan argumen bebas."""
    try:
        text = Path(doc).read_text(encoding="utf-8")
    except OSError as exc:
        raise OfficialDatasetError(f"gagal membaca seed dari {doc}: {exc}") from exc
    found = SEED_PATTERN.findall(text)
    if len(found) != 1:
        raise OfficialDatasetError(f"{doc}: harus ada tepat satu baris '- Seed pembagian: `N`'")
    return int(found[0])


def normalize_question(text: str) -> str:
    """Huruf kecil, tanda baca dibuang, spasi dirapikan (cek kebocoran ke ui.suggestions)."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = "".join(" " if unicodedata.category(ch).startswith("P") else ch for ch in text)
    return " ".join(text.split())


# --- pembagian ---------------------------------------------------------------------------


def units(questions: list[Question]) -> list[list[Question]]:
    """Unit = akar + semua followup yang merujuknya lewat prev_qid (berantai), urutan file."""
    by_qid = {q["qid"]: q for q in questions}

    def root(q: Question) -> str:
        seen = set()
        while q.get("prev_qid") in by_qid and q["qid"] not in seen:
            seen.add(q["qid"])
            q = by_qid[q["prev_qid"]]
        return q["qid"]

    groups: dict[str, list[Question]] = {}
    for q in questions:
        groups.setdefault(root(q), []).append(q)
    return list(groups.values())


def stratum(unit: list[Question]) -> str:
    if any(q["type"] == "followup" for q in unit):
        return "followup"
    head = unit[0]
    if head["type"] == "out_of_kb":
        return f"out_of_kb:{head.get('oos_level')}"
    return str(head["type"])


def dev_quota(n_units: int) -> int:
    num, den = DEV_SHARE
    return (num * 2 * n_units + den) // (2 * den)  # 30% dibulatkan setengah ke atas


def split_questions(questions: list[Question], seed: int) -> dict[str, Any]:
    """Kembalikan {"dev": [...], "test": [...], "strata": {nama: {...}}}; deterministik."""
    by_stratum: dict[str, list[list[Question]]] = {}
    for unit in units(questions):
        by_stratum.setdefault(stratum(unit), []).append(unit)
    rng = random.Random(seed)
    dev_roots: set[str] = set()
    strata: dict[str, dict[str, int]] = {}
    for name in sorted(by_stratum):
        group = sorted(by_stratum[name], key=lambda u: u[0]["qid"])
        rng.shuffle(group)
        quota = dev_quota(len(group))
        dev_roots |= {u[0]["qid"] for u in group[:quota]}
        strata[name] = {
            "units": len(group), "dev_units": quota, "test_units": len(group) - quota,
            "dev_questions": sum(len(u) for u in group[:quota]),
            "test_questions": sum(len(u) for u in group[quota:]),
        }  # fmt: skip
    root_of = {q["qid"]: u[0]["qid"] for u in units(questions) for q in u}
    out: dict[str, Any] = {"dev": [], "test": [], "strata": strata}
    new_id: dict[str, str] = {}
    for split in ("dev", "test"):
        members = [q for q in questions if (root_of[q["qid"]] in dev_roots) == (split == "dev")]
        for n, q in enumerate(members, start=1):
            new_id[q["qid"]] = f"o-{split}-{n:03d}"
        for q in members:
            row = {**q, "qid": new_id[q["qid"]], "source_qid": q["qid"], "split": split}
            if q.get("prev_qid") is not None:
                row["prev_qid"] = new_id[q["prev_qid"]]
            out[split].append(row)
    return out


def write_split(input_path: Path, out_dir: Path, seed: int | None = None) -> dict[str, Any]:
    out_dir = Path(out_dir)
    targets = [out_dir / "dev.jsonl", out_dir / "test.jsonl"]
    existing = [p.as_posix() for p in targets if p.exists()]
    if existing:
        raise OfficialDatasetError(
            f"sudah ada {existing}: pembagian hanya dijalankan satu kali (docs/DATASET.md); "
            "perubahan set uji lewat versi kunci baru"
        )
    seed = read_seed() if seed is None else seed
    questions = load_questions(input_path)
    result = split_questions(questions, seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    save_questions(targets[0], result["dev"])
    save_questions(targets[1], result["test"])
    return {"seed": seed, "input": Path(input_path).as_posix(),
            "input_sha256": sha256_file(input_path), **result}  # fmt: skip


# --- kunci ---------------------------------------------------------------------------------


def read_lock(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any] | None:
    path = Path(lock_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OfficialDatasetError(f"{path}: LOCK tidak terbaca ({exc})") from exc
    if data.get("format") != LOCK_FORMAT or not data.get("versions"):
        raise OfficialDatasetError(f"{path}: format LOCK tidak dikenal")
    return data


def counts(questions: list[Question]) -> dict[str, dict[str, int]]:
    return {
        "per_type": dict(sorted(Counter(q["type"] for q in questions).items())),
        "per_stratum": dict(sorted(Counter(stratum(u) for u in units(questions)).items())),
    }


def lock_dataset(
    dataset: Path,
    reason: str,
    lock_path: Path = DEFAULT_LOCK,
    commit: str | None = None,
    git_dirty: bool | None = None,
    now: datetime | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Tambah versi kunci. Alasan wajib; hash yang sama dengan versi berlaku ditolak."""
    if not reason.strip():
        raise OfficialDatasetError("--reason wajib diisi")
    questions = load_questions(dataset)
    data = read_lock(lock_path) or {"format": LOCK_FORMAT, "versions": []}
    digest = sha256_file(dataset)
    if data["versions"] and data["versions"][-1]["sha256"] == digest:
        raise OfficialDatasetError(
            f"{dataset} sudah terkunci di versi {data['versions'][-1]['version']} (hash sama)"
        )
    version = {
        "version": len(data["versions"]) + 1,
        "dataset": Path(dataset).as_posix(),
        "sha256": digest,
        "n_questions": len(questions),
        **counts(questions),
        "seed": read_seed() if seed is None else seed,
        "date": (now or datetime.now().astimezone()).isoformat(),
        "commit": commit,
        "git_dirty": git_dirty,
        "reason": reason.strip(),
    }
    data["versions"].append(version)
    Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
    Path(lock_path).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")  # fmt: skip
    return version


def lock_status(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    data = read_lock(lock_path)
    if data is None:
        return {"locked": False, "lock_path": Path(lock_path).as_posix()}
    current = data["versions"][-1]
    path = Path(current["dataset"])
    actual = sha256_file(path) if path.exists() else None
    return {"locked": True, "lock_path": Path(lock_path).as_posix(),
            "n_versions": len(data["versions"]), "current": current,
            "file_exists": path.exists(), "file_sha256": actual,
            "hash_ok": actual == current["sha256"]}  # fmt: skip


def status_lines(status: dict[str, Any], official_dir: Path = OFFICIAL_DIR) -> list[str]:
    if not status["locked"]:
        test = Path(official_dir) / "test.jsonl"
        lines = [f"LOCK: belum ada ({status['lock_path']})"]
        lines.append(f"set uji: {'ada, BELUM DIKUNCI' if test.exists() else 'belum ada'} "
                     f"({test.as_posix()})")  # fmt: skip
        return lines
    cur = status["current"]
    return [
        f"LOCK: {status['lock_path']} ({status['n_versions']} versi)",
        f"versi berlaku: {cur['version']} ({cur['date']}, commit {cur['commit']})",
        f"dataset: {cur['dataset']} ({cur['n_questions']} pertanyaan)",
        f"per type: {cur['per_type']}",
        f"alasan: {cur['reason']}",
        f"sha256 terkunci: {cur['sha256']}",
        "hash file: " + ("COCOK" if status["hash_ok"]
                         else "TIDAK COCOK" if status["file_exists"] else "FILE TIDAK ADA"),
    ]  # fmt: skip


# --- penjaga --split ------------------------------------------------------------------------

SPLITS = ("dev", "test")


class SplitRefused(Exception):
    pass


def check_split(
    split: str,
    dataset: Path | None,
    kb_source_type: str | None,
    lock_path: Path = DEFAULT_LOCK,
) -> dict[str, Any]:
    """Info untuk run.json; SplitRefused bila split tidak boleh dijalankan.

    test: LOCK ada, hash dataset (atau file terkunci bila dataset None) = versi berlaku, dan
    KB official. dev: dataset tidak boleh tercatat di LOCK (set uji tidak dipakai sebagai dev).
    """
    if split not in SPLITS:
        raise SplitRefused(f"--split harus salah satu dari {SPLITS}")
    data = read_lock(lock_path)
    if split == "dev":
        if dataset is not None and data is not None:
            digest = sha256_file(dataset)
            hit = [v["version"] for v in data["versions"] if v["sha256"] == digest]
            if hit:
                raise SplitRefused(
                    f"{dataset} adalah set uji terkunci (LOCK versi {hit}); pakai --split test"
                )
        return {"split": "dev", "lock": None}
    if data is None:
        raise SplitRefused(
            f"--split test butuh {Path(lock_path).as_posix()}; set uji belum dikunci"
        )
    current = data["versions"][-1]
    target = Path(dataset) if dataset is not None else Path(current["dataset"])
    if not target.exists():
        raise SplitRefused(f"--split test: {target.as_posix()} tidak ada")
    digest = sha256_file(target)
    if digest != current["sha256"]:
        raise SplitRefused(
            f"--split test: hash {target.as_posix()} ({digest[:12]}) tidak cocok dengan LOCK versi "
            f"{current['version']} ({current['sha256'][:12]}); set uji berubah atau salah file"
        )
    if kb_source_type != "official":
        raise SplitRefused(
            f"--split test butuh KB source_type official (KB aktif: {kb_source_type}); "
            "set uji tidak dinilai dengan KB dev"
        )
    return {"split": "test",
            "lock": {"path": Path(lock_path).as_posix(), "version": current["version"],
                     "sha256": current["sha256"], "date": current["date"],
                     "dataset": target.as_posix()}}  # fmt: skip
