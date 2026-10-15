from datetime import date
from pathlib import Path

import pytest
import yaml
from kb_samples import FakeEmbedder, make_kb_folder

from mica.kb.__main__ import main

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"


def _run(capsys, *argv, **kwargs):
    code = main(list(argv), **kwargs)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_init_sources_titles_and_date(tmp_path, capsys):
    src = tmp_path / "src"
    (src / "biaya").mkdir(parents=True)
    (src / "biaya" / "uang-kuliah.md").write_text(
        "---\ntitle: Uang Kuliah 2026\nurl: https://mikroskil.ac.id/biaya\n---\n# Lain\nisi",
        encoding="utf-8",
    )
    (src / "profil.md").write_text("Pembuka.\n\n# Profil Mikroskil\nisi", encoding="utf-8")
    (src / "catatan.txt").write_text("tanpa heading", encoding="utf-8")

    code, out, _ = _run(
        capsys, "init-sources", "--src", str(src), "--source-type", "dev", "--date", "2026-09-29"
    )
    assert code == 0 and "3 dokumen" in out
    sources = yaml.safe_load((src / "sources.yaml").read_text(encoding="utf-8"))
    assert sources["biaya/uang-kuliah.md"] == {
        "title": "Uang Kuliah 2026",
        "valid_from": date(2026, 9, 29),
        "url": "https://mikroskil.ac.id/biaya",
    }
    assert sources["profil.md"]["title"] == "Profil Mikroskil"  # heading pertama
    assert sources["catatan.txt"]["title"] == "catatan"  # nama file
    text = (src / "sources.yaml").read_text(encoding="utf-8")
    assert "&id" not in text and "*id" not in text
    assert text.count("valid_from: 2026-09-29") == 3


def test_init_sources_does_not_overwrite_without_force(tmp_path, capsys):
    src = make_kb_folder(tmp_path / "src")
    original = (src / "sources.yaml").read_text(encoding="utf-8")
    argv = ["init-sources", "--src", str(src), "--source-type", "official", "--date", "2026-09-29"]
    code, _, err = _run(capsys, *argv)
    assert code == 1 and "--force" in err
    assert (src / "sources.yaml").read_text(encoding="utf-8") == original
    code, _, _ = _run(capsys, *argv, "--force")
    assert code == 0
    assert (src / "sources.yaml").read_text(encoding="utf-8") != original


def test_build_list_inspect(tmp_path, capsys):
    src = make_kb_folder(tmp_path / "src")
    kb_root = tmp_path / "kb"
    code, out, err = _run(
        capsys,
        "--kb-root", str(kb_root),
        "build", "--src", str(src), "--kb-id", "dev-2026-10-15",
        "--source-type", "dev", "--config", str(DEV_YAML),
        embedder_factory=lambda m, r: FakeEmbedder(),
    )
    assert code == 0, err
    assert "4 dokumen" in out and "detik" in out
    assert (kb_root / "dev-2026-10-15" / "manifest.json").exists()

    code, out, _ = _run(capsys, "--kb-root", str(kb_root), "list")
    assert code == 0 and "dev-2026-10-15" in out and "4 dokumen" in out

    code, out, _ = _run(capsys, "--kb-root", str(kb_root), "inspect", "--kb-id", "dev-2026-10-15")
    assert code == 0
    assert "dokumen: 4" in out
    assert out.count("--- contoh ") == 4  # 3 contoh chunk + 1 contoh tabel
    assert "Prodi | Biaya per semester" in out


def test_build_existing_kb_id_fails(tmp_path, capsys):
    src = make_kb_folder(tmp_path / "src")
    kb_root = tmp_path / "kb"
    argv = [
        "--kb-root", str(kb_root), "build", "--src", str(src), "--kb-id", "dev-x",
        "--source-type", "dev", "--config", str(DEV_YAML),
    ]
    assert _run(capsys, *argv, embedder_factory=lambda m, r: FakeEmbedder())[0] == 0
    code, _, err = _run(capsys, *argv, embedder_factory=lambda m, r: FakeEmbedder())
    assert code == 2 and "KB_INVALID" in err


def test_build_has_no_allow_missing_date(tmp_path):
    with pytest.raises(SystemExit):
        main([
            "build", "--src", str(tmp_path), "--kb-id", "x", "--source-type", "dev",
            "--config", str(DEV_YAML), "--allow-missing-date",
        ])


def test_check_sources_lists_missing_dates(tmp_path, capsys):
    src = make_kb_folder(tmp_path / "src", "brosur.txt: {valid_from: 2026-08-01}\n")
    code, out, _ = _run(capsys, "check-sources", "--src", str(src))
    assert code == 1
    assert "3 dokumen belum punya valid_from" in out
    assert "biaya" in out and "brosur\n" not in out


def test_check_sources_all_dated(tmp_path, capsys):
    src = make_kb_folder(tmp_path / "src")
    code, out, _ = _run(capsys, "check-sources", "--src", str(src))
    assert code == 0 and "semua dokumen" in out


def test_inspect_missing_kb(tmp_path, capsys):
    code, _, err = _run(capsys, "--kb-root", str(tmp_path), "inspect", "--kb-id", "tidak-ada")
    assert code == 2 and "KB_INVALID" in err
