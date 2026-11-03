"""M-12: persiapan data suara publik E-05 (docs/AMANDEMEN-2026-11-03b.md bagian B dan catatannya).

- prep-commonvoice: Common Voice Scripted Speech 27.0 - Indonesian (CC0-1.0). Dari arsip tar(.gz)
  hanya validated.tsv dan klip terpilih yang dibaca (tanpa extractall). Maksimal 1 klip per
  penutur, n klip diacak dengan seed. MP3 -> WAV 16 kHz mono int16 (PyAV, sudah ada sebagai
  dependensi faster-whisper). client_id tidak pernah ditulis: penutur diganti kode urut (CV001...).
- prep-musan: salinan Hugging Face MUSAN (revisi dikunci), n file noise diacak, hanya file itu
  yang diunduh, dipotong clip_s detik; LICENSE per subfolder disimpan.
- prep-silence: rekaman diam dari mikrofon laptop pengembang (hanya mode dev).
- prep-manifest: gabungan ketiga manifest sumber -> manifest.jsonl untuk eval stt / stt-sweep.

Format manifest = SDD 6.3 (id, file, jenis, referensi, penutur, persetujuan) ditambah status
("ucapan" | "bukan ucapan", amandemen kedua) dan sumber. Klip Common Voice berperan sebagai jenis
"pertanyaan" (ucapan asli); MUSAN = "bising", diam = "diam" (bukan ucapan).
Audio hanya ditulis ke folder di luar repo dan tidak pernah di-commit.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import tarfile
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

SAMPLE_RATE = 16000
REPO_ROOT = Path(__file__).resolve().parents[3]
CV_SOURCE = "Common Voice Scripted Speech 27.0 - Indonesian (CC0-1.0)"
CV_REQUIRED = ("client_id", "path", "sentence")
DEFAULT_CLIP_IDS = Path("data/eval/speech/publik-2026-11/clip_ids.txt")


class PublicDataError(Exception):
    pass


# --- umum ---------------------------------------------------------------------------------


def check_out_dir(out: Path) -> Path:
    """Folder keluaran wajib di luar repo (audio dataset tidak boleh masuk git)."""
    out = Path(out).resolve()
    if out == REPO_ROOT or REPO_ROOT in out.parents:
        raise PublicDataError(f"--out harus di luar repo ({REPO_ROOT.as_posix()}): {out}")
    return out


def decode_to_16k(data: bytes | Path) -> np.ndarray:
    """Audio apa pun yang dibaca FFmpeg (PyAV) -> int16 mono 16 kHz."""
    import av

    source = io.BytesIO(data) if isinstance(data, bytes) else str(data)
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    parts: list[np.ndarray] = []
    with av.open(source, mode="r") as container:
        for frame in container.decode(audio=0):
            parts += [f.to_ndarray().reshape(-1) for f in resampler.resample(frame)]
        parts += [f.to_ndarray().reshape(-1) for f in resampler.resample(None)]
    return (np.concatenate(parts) if parts else np.zeros(0)).astype(np.int16)


def write_wav(path: Path, pcm: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(np.asarray(pcm, dtype=np.int16).tobytes())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with Path(path).open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


# --- 1. Common Voice ----------------------------------------------------------------------


@dataclass(frozen=True)
class CvClip:
    path: str  # nama file klip di clips/, mis. common_voice_id_123.mp3
    speaker: str  # client_id (hanya di memori)
    sentence: str

    @property
    def clip_id(self) -> str:
        return PurePosixPath(self.path).stem


def read_validated(tar: tarfile.TarFile) -> tuple[str, list[CvClip]]:
    """(folder locale di arsip, baris validated.tsv). Tepat satu validated.tsv wajib ada."""
    found = [m for m in tar if m.isfile() and PurePosixPath(m.name).name == "validated.tsv"]
    if len(found) != 1:
        raise PublicDataError(
            f"arsip harus memuat tepat satu validated.tsv, ditemukan {len(found)}"
        )
    member = found[0]
    f = tar.extractfile(member)
    assert f is not None
    reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t",
                            quoting=csv.QUOTE_NONE)  # fmt: skip
    missing = [c for c in CV_REQUIRED if c not in (reader.fieldnames or ())]
    if missing:
        raise PublicDataError(f"validated.tsv tanpa kolom {missing}")
    clips = [CvClip(r["path"].strip(), r["client_id"].strip(), r["sentence"].strip())
             for r in reader if r["path"] and r["client_id"] and (r["sentence"] or "").strip()]  # fmt: skip
    return str(PurePosixPath(member.name).parent), clips


def select_clips(clips: Sequence[CvClip], n: int, seed: int) -> list[CvClip]:
    """Maksimal 1 klip per penutur; n penutur diacak (semua bila kurang dari n).

    Urutan deterministik: penutur diurutkan menurut client_id lalu dipermutasi dengan
    numpy default_rng(seed); untuk tiap penutur terpilih (urutan permutasi) satu klip dipilih
    rng.integers dari klipnya yang diurutkan menurut path."""
    by_speaker: dict[str, list[CvClip]] = {}
    for c in clips:
        by_speaker.setdefault(c.speaker, []).append(c)
    speakers = sorted(by_speaker)
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(speakers))[:n]
    out = []
    for i in order:
        own = sorted(by_speaker[speakers[int(i)]], key=lambda c: c.path)
        out.append(own[int(rng.integers(len(own)))])
    return out


def prep_commonvoice(
    archive: Path,
    out: Path,
    n: int,
    seed: int,
    ids_out: Path | None,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    out = check_out_dir(out)
    clip_dir = out / "commonvoice"
    if clip_dir.exists() and any(clip_dir.iterdir()):
        raise PublicDataError(f"{clip_dir} sudah berisi file; pakai folder --out baru")
    with tarfile.open(archive, "r:*") as tar:
        locale_dir, clips = read_validated(tar)
    selected = select_clips(clips, n, seed)
    wanted = {f"{locale_dir}/clips/{c.path}": c for c in selected}
    progress(f"validated.tsv: {len(clips)} klip, {len({c.speaker for c in clips})} penutur; "
             f"terpilih {len(selected)}")  # fmt: skip
    audio: dict[str, np.ndarray] = {}
    with tarfile.open(archive, "r:*") as tar:  # lintasan kedua: hanya klip terpilih
        for m in tar:
            clip = wanted.get(m.name)
            if clip is None or not m.isfile():
                continue
            f = tar.extractfile(m)
            assert f is not None
            audio[clip.clip_id] = decode_to_16k(f.read())
    missing = sorted(c.clip_id for c in selected if c.clip_id not in audio)
    if missing:
        raise PublicDataError(f"klip terpilih tidak ada di arsip: {missing[:5]}")
    rows = []
    for no, clip in enumerate(selected, start=1):
        rel = f"commonvoice/{clip.clip_id}.wav"
        write_wav(out / rel, audio[clip.clip_id])
        rows.append({"id": clip.clip_id, "file": rel, "jenis": "pertanyaan",
                     "referensi": clip.sentence, "penutur": f"CV{no:03d}", "persetujuan": True,
                     "status": "ucapan", "sumber": CV_SOURCE,
                     "audio_s": round(len(audio[clip.clip_id]) / SAMPLE_RATE, 3)})  # fmt: skip
    write_jsonl(out / "commonvoice.jsonl", rows)
    info = {
        "source": CV_SOURCE, "archive": Path(archive).name,
        "archive_sha256": sha256_file(archive), "seed": seed, "n_requested": n,
        "n_validated_clips": len(clips), "n_speakers": len({c.speaker for c in clips}),
        "n_selected": len(selected), "max_per_speaker": 1,
        "selection": "speakers sorted by client_id, numpy default_rng(seed).permutation; "
                     "one clip per speaker via rng.integers over clips sorted by path",
    }  # fmt: skip
    (out / "commonvoice.json").write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8")
    if ids_out is not None:
        ids_out.parent.mkdir(parents=True, exist_ok=True)
        ids_out.write_text("".join(f"{c.clip_id}\n" for c in selected), encoding="utf-8")
    return info


# --- 2. MUSAN (salinan Hugging Face, revisi dikunci) ---------------------------------------

MUSAN_REPO = "FluidInference/musan"
# revisi commit dikunci (docs/AMANDEMEN-2026-11-03b.md, catatan kedua); dibaca lewat API metadata
MUSAN_REVISION = "3edcfdf89b56dbe6a395ff29f9c29489e03d1321"
MUSAN_SOURCE = (
    "MUSAN noise (Snyder dkk. 2015, OpenSLR 17), salinan Hugging Face; lisensi per subfolder"
)


def _hf_list(repo: str, revision: str) -> list[str]:
    from huggingface_hub import list_repo_files

    return list(list_repo_files(repo, repo_type="dataset", revision=revision))


def _hf_download(repo: str, revision: str, filename: str, local_dir: Path) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo, filename, repo_type="dataset", revision=revision,
                                local_dir=str(local_dir)))  # fmt: skip


def select_musan(files: Sequence[str], n: int, seed: int) -> list[str]:
    """File .wav di noise/ diurutkan, lalu n dipilih tanpa pengembalian dengan default_rng(seed)."""
    wavs = sorted(f for f in files if f.startswith("noise/") and f.endswith(".wav"))
    if not wavs:
        raise PublicDataError("tidak ada file noise/*.wav di daftar repo")
    rng = np.random.default_rng(seed)
    return [wavs[int(i)] for i in rng.choice(len(wavs), size=min(n, len(wavs)), replace=False)]


def prep_musan(
    out: Path,
    n: int,
    seed: int,
    clip_s: float,
    repo: str = MUSAN_REPO,
    revision: str = MUSAN_REVISION,
    list_files: Callable[[str, str], list[str]] = _hf_list,
    download: Callable[[str, str, str, Path], Path] = _hf_download,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Daftar file (metadata) -> n file diacak -> hanya file itu diunduh -> WAV 16 kHz mono
    clip_s detik pertama. File unduhan mentah dihapus setelah dikonversi; sha256-nya dicatat."""
    import re
    import shutil

    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise PublicDataError("--revision harus hash commit 40 karakter (revisi dikunci)")
    out = check_out_dir(out)
    clip_dir = out / "musan"
    if clip_dir.exists() and any(clip_dir.iterdir()):
        raise PublicDataError(f"{clip_dir} sudah berisi file; pakai folder --out baru")
    files = list_files(repo, revision)
    chosen = select_musan(files, n, seed)
    licenses = sorted(f for f in files if f.startswith("noise/") and f.endswith("/LICENSE"))
    raw = out / "musan-raw"
    rows: list[dict[str, Any]] = []
    raw_sha: dict[str, str] = {}
    short: list[str] = []
    limit = int(clip_s * SAMPLE_RATE)
    for no, name in enumerate(chosen, start=1):
        path = download(repo, revision, name, raw)
        raw_sha[name] = sha256_file(path)
        pcm = decode_to_16k(path)[:limit]
        if len(pcm) < limit:
            short.append(name)
        sub = PurePosixPath(name).parent.name
        clip_id = f"musan-{sub}-{PurePosixPath(name).stem}"
        rel = f"musan/{clip_id}.wav"
        write_wav(out / rel, pcm)
        rows.append({"id": clip_id, "file": rel, "jenis": "bising", "penutur": "MUSAN",
                     "persetujuan": True, "status": "bukan ucapan", "sumber": MUSAN_SOURCE,
                     "asal": name, "audio_s": round(len(pcm) / SAMPLE_RATE, 3)})  # fmt: skip
        progress(f"  [{no}/{len(chosen)}] {name}")
    clip_dir.mkdir(parents=True, exist_ok=True)
    for name in licenses:
        path = download(repo, revision, name, raw)
        shutil.copyfile(path, clip_dir / f"LICENSE-{PurePosixPath(name).parent.name}")
    shutil.rmtree(raw, ignore_errors=True)
    write_jsonl(out / "musan.jsonl", rows)
    n_noise = sum(f.startswith("noise/") and f.endswith(".wav") for f in files)
    info = {
        "source": MUSAN_SOURCE, "repo": repo, "revision": revision, "seed": seed,
        "n_requested": n, "n_noise_wav": n_noise, "n_selected": len(chosen), "clip_s": clip_s,
        "shorter_than_clip_s": short,
        "licenses": [f"LICENSE-{PurePosixPath(x).parent.name}" for x in licenses],
        "raw_sha256": raw_sha,
        "selection": "noise/*.wav sorted, numpy default_rng(seed).choice(replace=False)",
    }  # fmt: skip
    (out / "musan.json").write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8")
    return info


# --- 3. Rekaman diam dari mikrofon laptop --------------------------------------------------


def _record(seconds: float, device: int | str | None) -> np.ndarray:
    import sounddevice as sd

    pcm = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                 device=device)  # fmt: skip
    sd.wait()
    return np.asarray(pcm, dtype=np.int16).reshape(-1)


def prep_silence(
    out: Path,
    n: int,
    seconds: float,
    device: int | str | None = None,
    record: Callable[[float, int | str | None], np.ndarray] = _record,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    """n rekaman diam berturut-turut. Hanya untuk eval di mode dev (dicek pemanggil)."""
    out = check_out_dir(out)
    clip_dir = out / "diam"
    if clip_dir.exists() and any(clip_dir.iterdir()):
        raise PublicDataError(f"{clip_dir} sudah berisi file; pakai folder --out baru")
    rows = []
    for no in range(1, n + 1):
        progress(f"  rekaman diam {no}/{n} ({seconds:g} s): jangan bicara")
        pcm = record(seconds, device)
        clip_id = f"diam-{no:02d}"
        rel = f"diam/{clip_id}.wav"
        write_wav(out / rel, pcm)
        rows.append({"id": clip_id, "file": rel, "jenis": "diam", "penutur": "DEV",
                     "persetujuan": True, "status": "bukan ucapan",
                     "sumber": "mikrofon laptop pengembang",
                     "audio_s": round(len(pcm) / SAMPLE_RATE, 3)})  # fmt: skip
    write_jsonl(out / "silence.jsonl", rows)
    info = {"n": n, "seconds": seconds, "device": device}
    (out / "silence.json").write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8")
    return info


# --- 4. Manifest gabungan -----------------------------------------------------------------

SOURCE_MANIFESTS = ("commonvoice.jsonl", "musan.jsonl", "silence.jsonl")


def prep_manifest(out: Path) -> dict[str, int]:
    """Gabungkan manifest sumber di out/ menjadi out/manifest.jsonl (ketiganya wajib ada)."""
    out = check_out_dir(out)
    missing = [m for m in SOURCE_MANIFESTS if not (out / m).is_file()]
    if missing:
        raise PublicDataError(f"manifest sumber belum ada di {out}: {missing}")
    rows: list[dict[str, Any]] = []
    for name in SOURCE_MANIFESTS:
        rows += [json.loads(line) for line in (out / name).read_text("utf-8").splitlines()
                 if line.strip()]  # fmt: skip
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise PublicDataError("ID ganda di antara manifest sumber")
    write_jsonl(out / "manifest.jsonl", rows)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["jenis"]] = counts.get(r["jenis"], 0) + 1
    return counts
