"""M-12: persiapan data suara publik E-05 (docs/AMANDEMEN-2026-11-03b.md bagian B dan catatannya).

- prep-commonvoice: Common Voice Scripted Speech 27.0 - Indonesian (CC0-1.0). Dari arsip tar(.gz)
  hanya validated.tsv dan klip terpilih yang dibaca (tanpa extractall). Maksimal 1 klip per
  penutur, n klip diacak dengan seed. MP3 -> WAV 16 kHz mono int16 (PyAV, sudah ada sebagai
  dependensi faster-whisper). client_id tidak pernah ditulis: penutur diganti kode urut (CV001...).

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
