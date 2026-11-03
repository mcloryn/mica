"""PROD-8: pembaca PETA untuk E-08 (docs/AMANDEMEN-2026-11-03b.md C).

Zip sintetis meniru struktur README PETA: <subset>/archive/{Label.txt, gambar}. Gambar persegi
warna dibuat di tes dengan OpenCV. Tidak ada file dataset asli yang dibuka.
"""

import csv
import io
import json
import zipfile
from collections import Counter

import cv2
import numpy as np
import pytest

import mica.eval.__main__ as cli
from mica.eval import public_peta as pp
from mica.eval import public_speech as ps
from mica.eval import vision as ev
from mica.eval.color import load_color_labels
from mica.vision.color import COLOR_NAMES

ROOT = "PETA dataset"


def _png(bgr=(0, 0, 255)):
    img = np.zeros((128, 48, 3), np.uint8)
    img[:] = bgr
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def make_zip(path, subsets):
    """subsets: {nama: [(id orang, [atribut], jumlah gambar), ...]}"""
    with zipfile.ZipFile(path, "w") as z:
        for subset, persons in subsets.items():
            lines = []
            for pid, attrs, n_img in persons:
                lines.append(" ".join([pid, *attrs]))
                for k in range(n_img):
                    z.writestr(f"{ROOT}/{subset}/archive/{pid}_{k}_cam.png", _png())
            z.writestr(f"{ROOT}/{subset}/archive/Label.txt", "\n".join(lines) + "\n")
        z.writestr(f"{ROOT}/README.txt", "PETA sintetis")
    return path


SUBSETS = {
    "VIPeR": [("1", ["personalMale", "upperBodyRed", "lowerBodyBlack"], 3),
              ("2", ["upperBodyBlue"], 2),
              ("3", ["upperBodyRed", "upperBodyWhite"], 2),  # dua warna: dibuang
              ("4", ["personalFemale"], 1)],  # tanpa warna: dibuang
    "CUHK": [("0007", ["upperBodyGreen", "upperBodyLogo"], 5)],
    "i-LID": [("5", ["upperBodyRed"], 4)],  # subset i-LIDS dikeluarkan
}  # fmt: skip


def _names_reader(path):
    z = zipfile.ZipFile(path)
    return [i.filename for i in z.infolist() if not i.is_dir()], z.read


def test_mapping_is_one_to_one_with_mica_colors():
    assert len(pp.PETA_UPPER_COLORS) == 11
    assert sorted(pp.PETA_UPPER_COLORS.values()) == sorted(COLOR_NAMES)


def test_read_peta_filters_subset_and_exactly_one_color(tmp_path):
    names, read = _names_reader(make_zip(tmp_path / "peta.zip", SUBSETS))
    images, stats = pp.read_peta(names, read)
    assert Counter(i.color for i in images) == {"merah": 3, "biru": 2, "hijau": 5}
    assert stats["excluded_subsets"] == ["i-LID"]
    assert stats["subsets"]["VIPeR"]["images_not_one_color"] == 3
    assert all(not i.subset.lower().startswith("i-lid") for i in images)


def test_images_without_label_are_counted(tmp_path):
    path = make_zip(tmp_path / "peta.zip", {"GRID": [("1", ["upperBodyBlack"], 1)]})
    with zipfile.ZipFile(path, "a") as z:
        z.writestr(f"{ROOT}/GRID/archive/99_0.png", _png())
    images, stats = pp.read_peta(*_names_reader(path))
    assert len(images) == 1 and stats["subsets"]["GRID"]["images_without_label"] == 1


def test_label_id_as_full_file_name_cuhk_style(tmp_path):
    # CUHK: Label.txt memakai nama file lengkap sebagai ID, satu gambar per orang
    path = tmp_path / "peta.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{ROOT}/CUHK/archive/0606.png", _png())
        z.writestr(f"{ROOT}/CUHK/archive/1020.png", _png())
        z.writestr(f"{ROOT}/CUHK/archive/0002.png", _png())  # tanpa baris label
        z.writestr(f"{ROOT}/CUHK/archive/Label.txt",
                   "0606.png upperBodyRed lowerBodyBlack\n1020.png upperBodyBlue upperBodyWhite\n")  # fmt: skip
    images, stats = pp.read_peta(*_names_reader(path))
    assert [(i.id, i.color, i.person) for i in images] == [("CUHK-0606", "merah", "CUHK/0606.png")]
    s = stats["subsets"]["CUHK"]
    assert (s["images_without_label"], s["images_not_one_color"], s["eligible"]) == (1, 1, 1)


def test_sample_caps_per_color_by_image_and_splits_by_person():
    # merah: 70 gambar dari 14 orang (5 gambar/orang); biru: 5 gambar dari 5 orang
    images = [pp.PetaImage(f"s-{c}-{k}", "s", f"m{k}", c, f"s/{c}{k // (5 if c == 'merah' else 1)}")
              for c in ("merah", "biru") for k in range(70 if c == "merah" else 5)]  # fmt: skip
    chosen = pp.sample(images, 60, 20261103)
    assert chosen == pp.sample(images, 60, 20261103)
    count = Counter(i.color for i, _ in chosen)
    assert count == {"merah": 60, "biru": 5}  # batas 60 dihitung per gambar
    split_of: dict[str, set[str]] = {}
    for img, split in chosen:
        split_of.setdefault(img.person, set()).add(split)
    assert all(len(s) == 1 for s in split_of.values())  # tidak ada orang di kedua split
    blue = Counter(s for i, s in chosen if i.color == "biru")
    assert blue == {"tuning": 2, "laporan": 3}  # 5 orang: 5 // 2 tuning
    assert {s for i, s in chosen if i.color == "merah"} == {"tuning", "laporan"}
    assert len({i.id for i, _ in chosen}) == len(chosen)


def test_prep_peta_no_person_in_both_splits(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path / "repo")
    subsets = {"PRID": [(str(p), ["upperBodyBlack"], 4) for p in range(1, 9)]}
    archive = make_zip(tmp_path / "peta.zip", subsets)
    sample_csv = tmp_path / "repo" / "sample.csv"
    pp.prep_peta(archive, tmp_path / "o", 20261103, 60, sample_csv, progress=lambda s: None)
    rows = list(csv.DictReader(io.StringIO(sample_csv.read_text("utf-8-sig"))))
    by_person: dict[str, set[str]] = {}
    for r in rows:
        by_person.setdefault(r["orang"], set()).add(r["split"])
    assert len(by_person) == 8 and all(len(s) == 1 for s in by_person.values())
    assert Counter(next(iter(s)) for s in by_person.values()) == {"tuning": 4, "laporan": 4}


def test_prep_peta_outputs_eval_color_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path / "repo")
    archive = make_zip(tmp_path / "peta.zip", SUBSETS)
    out = tmp_path / "publik" / "peta"
    sample_csv = tmp_path / "repo" / "sample.csv"
    info = pp.prep_peta(archive, out, 20261103, 60, sample_csv, progress=lambda s: None)
    # merah: orang 1 (3 gambar) saja -> 1 // 2 = 0 orang tuning; semua gambar ke laporan
    assert info["sample_per_color"]["merah"] == {"tuning": 0, "laporan": 3}
    frames = ev.load_frames(out)  # format E-07 (a) yang dibaca eval color
    assert len(frames) == 10
    labels = load_color_labels(out / "colors.csv")
    assert Counter(labels.values()) == {"merah": 3, "biru": 2, "hijau": 5}
    rows = list(csv.DictReader(io.StringIO(sample_csv.read_text("utf-8-sig"))))
    assert {r["split"] for r in rows} == {"laporan"} and len(rows) == 10  # tiap warna 1 orang
    assert all(r["file_asal"].startswith(ROOT) for r in rows)
    manifest = [json.loads(x) for x in (out / "manifest.jsonl").read_text("utf-8").splitlines()]
    assert all(m["split"] in pp.SPLITS for m in manifest)
    assert (out / "labels" / f"{manifest[0]['id']}.txt").read_text("utf-8") == "0 0.5 0.5 1 1\n"


def test_prep_peta_refuses_out_in_repo_and_missing_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path)
    archive = make_zip(tmp_path / "peta.zip", SUBSETS)
    with pytest.raises(ps.PublicDataError, match="di luar repo"):
        pp.prep_peta(archive, tmp_path / "out", 1, 60, None)
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path / "repo")
    empty = tmp_path / "kosong.zip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("x/archive/a_1.png", _png())
    with pytest.raises(ps.PublicDataError, match="Label.txt"):
        pp.prep_peta(empty, tmp_path / "out2", 1, 60, None)


def test_cli_prep_peta(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ps, "REPO_ROOT", tmp_path / "repo")
    archive = make_zip(tmp_path / "peta.zip", SUBSETS)
    code = cli.main(["prep-peta", "--archive", str(archive), "--out", str(tmp_path / "o"),
                     "--sample-csv", str(tmp_path / "s.csv")])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0 and "hijau: tuning 0, laporan 5" in out and "i-LID" in out
