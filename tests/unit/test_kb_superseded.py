"""Langkah 64: bagian dokumen yang sudah digantikan dokumen lain (superseded_sections)."""

import pytest
from kb_samples import FakeEmbedder, lines_stream, write_pdf_pages

from mica.config import KbConfig
from mica.kb.index import build_kb, load_kb, read_manifest
from mica.kb.parsers import KbBuildError, SupersededSection, load_sources, section_matches

BAB = "BAB II PENERIMAAN"
SUPERSEDED = (
    "  superseded_sections:\n"
    '    - section: "Pasal 4"\n'
    "      superseded_by: Pedoman PMB 2027, 1.2 Jalur Seleksi\n"
    "      reason: jalur diatur Pedoman PMB 2027\n"
)


@pytest.mark.parametrize(
    ("path", "section", "expected"),
    [
        (f"{BAB} › Pasal 4 Jalur Penerimaan", "Pasal 4", True),
        (f"{BAB} › Pasal 4", "Pasal 4", True),
        (f"{BAB} › Pasal 40 Rekognisi Prestasi", "Pasal 4", False),
        (f"{BAB} › Pasal 41 Evaluasi", "Pasal 4", False),
        (f"{BAB} › Pasal 5 Rekognisi", "Pasal 4", False),
        (f"{BAB} › Pasal 4 Jalur Penerimaan", "Pasal 4 Jalur Penerimaan", True),
        (f"{BAB} › Pasal 4 Jalur Penerimaan", "BAB II › Pasal 4", True),
        (f"{BAB} › Pasal 4 Jalur Penerimaan", "BAB III › Pasal 4", False),
        (f"{BAB} › Pasal 4 Jalur Penerimaan", "Pasal", False),
        (f"{BAB} › Pasal 4 Jalur Penerimaan", "pasal 4", False),
        ("Pasal 4", "Pasal 4", True),
        ("", "Pasal 4", False),
    ],
)
def test_section_matches_exact_per_part(path, section, expected):
    assert section_matches(path, section) is expected


def _pdf(folder):
    write_pdf_pages(
        folder / "akademik" / "peraturan.pdf",
        [
            lines_stream(["BAB II", "PENERIMAAN", "Pasal 4", "Jalur Penerimaan", "Ada 7 jalur."]),
            lines_stream(["Pasal 5", "Rekognisi Pembelajaran Lampau", "RPL diakui."]),
            lines_stream(["BAB IV", "EVALUASI", "Pasal 40", "Rekognisi Prestasi", "Prestasi."]),
            lines_stream(["Pasal 41", "Evaluasi Kemajuan Studi", "IPK minimal."]),
        ],
    )


@pytest.fixture
def src(tmp_path):
    folder = tmp_path / "src"
    (folder / "akademik").mkdir(parents=True)
    _pdf(folder)
    (folder / "sources.yaml").write_text(
        "akademik/peraturan.pdf:\n  title: Peraturan Akademik\n  valid_from: 2025-01-22\n"
        + SUPERSEDED,
        encoding="utf-8",
    )
    return folder


def _config():
    return KbConfig(
        active_id="t",
        chunker="structure_then_fixed",
        chunk_tokens=50,
        overlap_tokens=5,
        embedder={"model": "fake/embedder", "revision": None},
    )


def test_superseded_sections_loaded(src):
    (doc,) = load_sources(src, "official")
    assert doc.superseded_sections == (
        SupersededSection(
            "Pasal 4", "Pedoman PMB 2027, 1.2 Jalur Seleksi", "jalur diatur Pedoman PMB 2027"
        ),
    )


def test_build_drops_superseded_chunks_only(src, tmp_path):
    folder = build_kb(src, "t", "official", _config(), FakeEmbedder(), tmp_path / "kb")
    kb = load_kb("t", tmp_path / "kb")
    sections = [c.section for c in kb.chunks]
    assert not any("Pasal 4 " in s for s in sections)
    # Pasal 40, 41 dan Pasal 5 tetap ada
    assert any("Pasal 40" in s for s in sections)
    assert any("Pasal 41" in s for s in sections)
    assert any("Pasal 5" in s for s in sections)
    assert "7 jalur" not in " ".join(c.text for c in kb.chunks)
    # BM25 dan dense hanya memuat chunk yang tersisa
    assert kb.bm25.corpus_size == len(kb.chunks) == kb.dense.shape[0]

    manifest = read_manifest(folder)
    (entry,) = manifest["documents"]
    (rule,) = entry["superseded_sections"]
    assert rule["section"] == "Pasal 4"
    assert rule["superseded_by"] == "Pedoman PMB 2027, 1.2 Jalur Seleksi"
    assert rule["n_chunks"] == len(rule["chunk_ids"]) == manifest["n_superseded_chunks"] == 1
    assert rule["chunk_ids"][0] not in {c.chunk_id for c in kb.chunks}


def test_unmatched_section_fails_build(src, tmp_path):
    sources = src / "sources.yaml"
    sources.write_text(
        sources.read_text(encoding="utf-8").replace('"Pasal 4"', '"Pasal 9"'), encoding="utf-8"
    )
    with pytest.raises(KbBuildError, match="tidak cocok dengan chunk mana pun.*Pasal 9"):
        build_kb(src, "t", "official", _config(), FakeEmbedder(), tmp_path / "kb")
    assert not (tmp_path / "kb" / "t").exists()


def test_section_prefix_of_other_pasal_is_not_a_match(src, tmp_path):
    # "Pasal 4" pada dokumen tanpa Pasal 4 tidak boleh "cocok" dengan Pasal 40/41
    _pdf_without_pasal_4(src)
    with pytest.raises(KbBuildError, match="Pasal 4"):
        build_kb(src, "t", "official", _config(), FakeEmbedder(), tmp_path / "kb")


def _pdf_without_pasal_4(folder):
    write_pdf_pages(
        folder / "akademik" / "peraturan.pdf",
        [
            lines_stream(["BAB IV", "EVALUASI", "Pasal 40", "Rekognisi Prestasi", "Prestasi."]),
            lines_stream(["Pasal 41", "Evaluasi Kemajuan Studi", "IPK minimal."]),
        ],
    )


@pytest.mark.parametrize(
    ("yaml_block", "message"),
    [
        ("  superseded_sections: Pasal 4\n", "harus daftar"),
        ("  superseded_sections:\n    - Pasal 4\n", "section"),
        ('  superseded_sections:\n    - {section: "Pasal 4", reason: x}\n', "superseded_by"),
        (
            (
                '  superseded_sections:\n    - {section: "Pasal 4", superseded_by: a, reason: x}\n'
                '    - {section: "Pasal 4", superseded_by: b, reason: y}\n'
            ),
            "ganda",
        ),
    ],
)
def test_invalid_superseded_sections_rejected(src, yaml_block, message):
    sources = src / "sources.yaml"
    head = sources.read_text(encoding="utf-8").split("  superseded_sections:\n")[0]
    sources.write_text(head + yaml_block, encoding="utf-8")
    with pytest.raises(KbBuildError, match=message):
        load_sources(src, "official")


def test_superseded_sections_for_markdown(tmp_path):
    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "a.md").write_text("# Jalur\n\nlama\n\n# Biaya\n\nRp1\n", encoding="utf-8")
    (folder / "sources.yaml").write_text(
        "a.md:\n  valid_from: 2026-01-01\n  superseded_sections:\n"
        "    - {section: Jalur, superseded_by: B, reason: r}\n",
        encoding="utf-8",
    )
    build_kb(folder, "t", "official", _config(), FakeEmbedder(), tmp_path / "kb")
    assert [c.section for c in load_kb("t", tmp_path / "kb").chunks] == ["Biaya"]
