"""M-12: python -m mica.eval prep-peta (E-08 data publik, docs/AMANDEMEN-2026-11-03b.md C).

PETA (Deng dkk., ACM MM 2014), lisensi akademik. Struktur menurut README PETA: satu folder per
subset (3DPeS, CAVIAR4REID, CUHK, GRID, i-LID, MIT, PRID, SARC3D, TownCentre, VIPeR), masing-
masing dengan archive/ berisi gambar potongan pejalan kaki dan Label.txt. Setiap baris Label.txt:
"<id orang> <atribut> <atribut> ...". Gambar milik orang itu bernama "<id orang>_<...>.<ext>"
(atau tepat "<id orang>.<ext>"); di CUHK ID-nya nama file lengkap ("0606.png"), satu gambar per
orang (catatan keempat amandemen kedua). Gambar dan baris yang tidak cocok dihitung dan
dilaporkan.

Aturan sampel:
- subset i-LIDS (nama folder mengandung "i-lid", huruf besar/kecil diabaikan) dibuang;
- hanya gambar yang orangnya punya TEPAT satu atribut warna badan atas dari 11 warna;
- per warna (urutan COLOR_NAMES MICA): gambar diurutkan menurut id, numpy default_rng(seed)
  .permutation, diambil paling banyak max_per_color;
- split dengan rng yang sama, berstrata per warna, PER ORANG (catatan ketiga amandemen kedua):
  orang di gambar terpilih dipermutasi, n_orang // 2 pertama TUNING, sisanya LAPORAN, sehingga
  orang yang sama tidak muncul di kedua split. Batas max_per_color tetap dihitung per gambar.

Keluaran (di luar repo): images/, labels/ (YOLO satu orang sekotak gambar, karena PETA sudah
berupa potongan orang), manifest.jsonl (format E-07 a + split), colors.csv (label PETA). Yang
di-commit hanya sample.csv (id, subset, file asal, warna, split). Zip dibaca per anggota; tidak
ada extractall.
"""

from __future__ import annotations

import csv
import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from mica.eval.public_speech import PublicDataError, check_out_dir, sha256_file
from mica.vision.color import COLOR_NAMES

PETA_SOURCE = "PETA (Deng dkk., ACM MM 2014), lisensi akademik; subset i-LIDS dikeluarkan"
# atribut warna badan atas PETA -> 11 nama warna dasar van de Weijer di MICA (satu-satu)
PETA_UPPER_COLORS = {
    "upperBodyBlack": "hitam",
    "upperBodyBlue": "biru",
    "upperBodyBrown": "cokelat",
    "upperBodyGrey": "abu-abu",
    "upperBodyGreen": "hijau",
    "upperBodyOrange": "oranye",
    "upperBodyPink": "merah muda",
    "upperBodyPurple": "ungu",
    "upperBodyRed": "merah",
    "upperBodyWhite": "putih",
    "upperBodyYellow": "kuning",
}
IMAGE_EXT = (".bmp", ".png", ".jpg", ".jpeg")
EXCLUDED_SUBSET = "i-lid"
SPLITS = ("tuning", "laporan")
DEFAULT_SAMPLE_CSV = Path("data/eval/vision/peta-2026-11/sample.csv")

assert sorted(PETA_UPPER_COLORS.values()) == sorted(COLOR_NAMES)


@dataclass(frozen=True)
class PetaImage:
    id: str
    subset: str
    member: str  # nama anggota di zip
    color: str  # nama warna MICA
    person: str = ""  # "<subset>/<id orang>" (Label.txt); dasar split per orang


def _subset_of(label_member: str) -> str:
    """.../<subset>/archive/Label.txt -> <subset>."""
    parts = PurePosixPath(label_member).parts
    return parts[-3] if len(parts) >= 3 else parts[0]


def read_peta(names: list[str], read: Callable[[str], bytes]) -> tuple[list[PetaImage], dict]:
    """Gambar yang memenuhi syarat + hitungan untuk laporan."""
    labels = sorted(n for n in names if PurePosixPath(n).name == "Label.txt")
    if not labels:
        raise PublicDataError("arsip tidak memuat Label.txt")
    images_by_dir: dict[str, list[str]] = {}
    for n in names:
        if PurePosixPath(n).suffix.lower() in IMAGE_EXT:
            images_by_dir.setdefault(str(PurePosixPath(n).parent), []).append(n)
    out: list[PetaImage] = []
    stats: dict[str, Any] = {"subsets": {}, "excluded_subsets": []}
    for label in labels:
        subset = _subset_of(label)
        if EXCLUDED_SUBSET in subset.lower():
            stats["excluded_subsets"].append(subset)
            continue
        folder = str(PurePosixPath(label).parent)
        imgs = sorted(images_by_dir.get(folder, []))
        attrs: dict[str, set[str]] = {}
        for line in read(label).decode("utf-8", errors="replace").splitlines():
            tokens = line.split()
            if tokens:
                attrs[tokens[0]] = set(tokens[1:])
        s = {"persons": len(attrs), "images": len(imgs), "images_without_label": 0,
             "images_not_one_color": 0, "eligible": 0}  # fmt: skip
        for img in imgs:
            stem = PurePosixPath(img).stem
            name = PurePosixPath(img).name
            # ID Label.txt bisa berupa nama file lengkap (CUHK: "0606.png", satu gambar = satu
            # orang), nama tanpa ekstensi, atau ID orang sebelum "_" (subset lain)
            pid = name if name in attrs else stem if stem in attrs else stem.split("_", 1)[0]
            if pid not in attrs:
                s["images_without_label"] += 1
                continue
            colors = [PETA_UPPER_COLORS[a] for a in sorted(attrs[pid]) if a in PETA_UPPER_COLORS]
            if len(colors) != 1:
                s["images_not_one_color"] += 1
                continue
            s["eligible"] += 1
            safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem)
            out.append(PetaImage(f"{subset}-{safe}", subset, img, colors[0], f"{subset}/{pid}"))
        stats["subsets"][subset] = s
    ids = [i.id for i in out]
    if len(set(ids)) != len(ids):
        raise PublicDataError("ID gambar ganda setelah penamaan ulang")
    return out, stats


def sample(images: list[PetaImage], max_per_color: int, seed: int) -> list[tuple[PetaImage, str]]:
    """Per warna: acak, ambil maksimal max_per_color GAMBAR, lalu bagi TUNING/LAPORAN PER ORANG
    (catatan ketiga amandemen kedua): orang di gambar terpilih diurutkan, dipermutasi dengan rng
    yang sama, n_orang // 2 pertama TUNING, sisanya LAPORAN. Satu orang punya satu warna badan
    atas (atribut per orang), jadi tidak ada orang yang muncul di dua split."""
    rng = np.random.default_rng(seed)
    out: list[tuple[PetaImage, str]] = []
    for color in COLOR_NAMES:
        pool = sorted((i for i in images if i.color == color), key=lambda i: i.id)
        picked = [pool[int(k)] for k in rng.permutation(len(pool))[:max_per_color]]
        persons = sorted({i.person for i in picked})
        order = [persons[int(k)] for k in rng.permutation(len(persons))]
        tuning = set(order[: len(order) // 2])
        out += [(img, "tuning" if img.person in tuning else "laporan") for img in picked]
    return out


def prep_peta(
    archive: Path,
    out: Path,
    seed: int,
    max_per_color: int,
    sample_csv: Path | None,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    out = check_out_dir(out)
    if (out / "images").exists() and any((out / "images").iterdir()):
        raise PublicDataError(f"{out / 'images'} sudah berisi file; pakai folder --out baru")
    with zipfile.ZipFile(archive) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        images, stats = read_peta(names, z.read)
        chosen = sample(images, max_per_color, seed)
        (out / "images").mkdir(parents=True, exist_ok=True)
        (out / "labels").mkdir(parents=True, exist_ok=True)
        manifest, colors, rows = [], [], []
        for img, split in chosen:
            ext = PurePosixPath(img.member).suffix.lower()
            rel = f"images/{img.id}{ext}"
            (out / rel).write_bytes(z.read(img.member))
            # PETA = potongan satu orang: kotak label = seluruh gambar
            (out / "labels" / f"{img.id}.txt").write_text("0 0.5 0.5 1 1\n", encoding="utf-8")
            manifest.append({"id": img.id, "file": rel, "relawan": "-", "persetujuan": True,
                             "cahaya": "tidak diketahui", "jarak": "tidak diketahui",
                             "split": split, "subset": img.subset, "sumber": PETA_SOURCE})  # fmt: skip
            colors.append({"frame": img.id, "track": 0, "color_label": img.color})
            rows.append({"id": img.id, "subset": img.subset, "orang": img.person,
                         "file_asal": img.member,
                         "color_label": img.color, "split": split})  # fmt: skip
    (out / "manifest.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in manifest), encoding="utf-8"
    )
    _write_csv(out / "colors.csv", colors, ["frame", "track", "color_label"])
    per_color = {c: {s: sum(1 for i, sp in chosen if i.color == c and sp == s) for s in SPLITS}
                 for c in COLOR_NAMES}  # fmt: skip
    eligible = {c: sum(i.color == c for i in images) for c in COLOR_NAMES}
    info = {"source": PETA_SOURCE, "archive": Path(archive).name,
            "archive_sha256": sha256_file(archive), "seed": seed, "max_per_color": max_per_color,
            "eligible_per_color": eligible, "sample_per_color": per_color, **stats,
            "label_mapping": PETA_UPPER_COLORS,
            "split_rule": "per warna: default_rng(seed).permutation gambar, maksimal "
                          "max_per_color gambar; orang dipermutasi, n_orang // 2 pertama tuning, "
                          "sisanya laporan (split per orang)"}  # fmt: skip
    (out / "peta.json").write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n",
                                   encoding="utf-8")  # fmt: skip
    if sample_csv is not None:
        sample_csv.parent.mkdir(parents=True, exist_ok=True)
        _write_csv(sample_csv, rows,
                   ["id", "subset", "orang", "file_asal", "color_label", "split"])  # fmt: skip
    progress(f"{len(chosen)} gambar terpilih dari {len(images)} yang memenuhi syarat")
    return info


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
