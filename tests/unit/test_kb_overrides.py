"""Langkah 63: halaman pengganti PDF (page_overrides) dan komentar HTML di Markdown."""

from datetime import date

import pytest
from kb_samples import FakeEmbedder, lines_stream, write_pdf_pages

from mica.config import KbConfig
from mica.kb.chunker import make_chunker
from mica.kb.index import build_kb, load_kb, read_manifest
from mica.kb.parsers import (
    KbBuildError,
    MdParser,
    PdfParser,
    iter_source_files,
    load_sources,
    md_blocks,
    parse_page_range,
    strip_html_comments,
)

OVERRIDE = """---
title: Pedoman (ketikan ulang hlm 2-3)
---

<!-- catatan penyunting:
     tidak boleh masuk KB -->

## BAB II Sistem Rekrutmen

### 2.1 Sistem Rekrutmen

#### c. Persyaratan Khusus

Magister Teknologi Informasi (S-2): Skor TOEFL minimal 475 ke atas

### 2.4 Sistem Pengambilan Keputusan

a. Panitia mengambil keputusan.
"""


def count_words(text: str) -> int:
    return len(text.split())


def _pedoman(folder):
    """PDF 4 halaman: hlm 2-3 diganti; hlm 4 melanjutkan 2.4, lalu BAB III."""
    write_pdf_pages(
        folder / "pmb" / "pedoman.pdf",
        [
            lines_stream(["BAB I", "PENGELOLAAN", "1.1 Perencanaan", "Panitia dibentuk."]),
            lines_stream(["BAB II", "SISTEM REKRUTMEN", "teks tabel berantakan"]),
            lines_stream(["teks tabel berantakan lanjutan"]),
            lines_stream(
                ["b. Keputusan diumumkan.", "BAB III", "REGISTRASI", "3.1 Uang", "Bayar."]
            ),
        ],
    )


@pytest.fixture
def src(tmp_path):
    folder = tmp_path / "src"
    (folder / "pmb").mkdir(parents=True)
    (folder / "_overrides").mkdir()
    _pedoman(folder)
    (folder / "_overrides" / "pedoman-hlm2-3.md").write_text(OVERRIDE, encoding="utf-8")
    (folder / "sources.yaml").write_text(
        "pmb/pedoman.pdf:\n"
        "  title: Pedoman PMB\n"
        "  valid_from: 2026-07-27\n"
        "  page_overrides:\n"
        '    "2-3": _overrides/pedoman-hlm2-3.md\n',
        encoding="utf-8",
    )
    return folder


def test_overrides_folder_not_ingested(src):
    assert [p.name for p in iter_source_files(src)] == ["pedoman.pdf"]


def test_override_replaces_pages_and_keeps_document(src):
    (doc,) = load_sources(src, "official")
    assert (doc.doc_id, doc.doc_title, doc.group) == ("pmb/pedoman", "Pedoman PMB", "pmb")
    rows = [(b.section, b.text, b.line_pages, b.page_range) for b in doc.blocks]
    assert rows == [
        ("BAB I PENGELOLAAN › 1.1 Perencanaan", "Panitia dibentuk.", (1,), None),
        (
            "BAB II Sistem Rekrutmen › 2.1 Sistem Rekrutmen › c. Persyaratan Khusus",
            "Magister Teknologi Informasi (S-2): Skor TOEFL minimal 475 ke atas",
            None,
            (2, 3),
        ),
        (
            "BAB II Sistem Rekrutmen › 2.4 Sistem Pengambilan Keputusan",
            "a. Panitia mengambil keputusan.",
            None,
            (2, 3),
        ),
        # hlm 4 melanjutkan bagian terakhir halaman pengganti
        (
            "BAB II Sistem Rekrutmen › 2.4 Sistem Pengambilan Keputusan",
            "b. Keputusan diumumkan.",
            (4,),
            None,
        ),
        ("BAB III REGISTRASI › 3.1 Uang", "Bayar.", (4,), None),
    ]
    text = "\n".join(b.text or "" for b in doc.blocks)
    assert "berantakan" not in text and "catatan penyunting" not in text and "title:" not in text


def test_override_chunks_have_pdf_pages(src):
    (doc,) = load_sources(src, "official")
    chunks = make_chunker("structure_then_fixed", 50, 5, count_words).split(doc)
    pages = [(c.page_start, c.page_end) for c in chunks]
    assert pages == [(1, 1), (2, 3), (2, 3), (4, 4), (4, 4)]
    assert all(c.doc_id == "pmb/pedoman" and c.valid_from == date(2026, 7, 27) for c in chunks)


def test_override_table_gets_page_range(tmp_path):
    folder = tmp_path / "src"
    folder.mkdir()
    write_pdf_pages(folder / "d.pdf", [lines_stream(["isi"]), lines_stream(["tabel rusak"])])
    md = folder / "t.md"
    md.write_text("## Tabel\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n", encoding="utf-8")
    doc = PdfParser().parse(folder / "d.pdf", {(2, 2): md})
    chunks = make_chunker("structure_then_fixed", 50, 5, count_words).split(
        type(doc)("d", "D", date(2026, 1, 1), "official", doc.blocks)
    )
    table = next(c for c in chunks if c.is_table)
    assert (table.page_start, table.page_end) == (2, 2)


def test_manifest_records_override_sha(src, tmp_path):
    kb = KbConfig(
        active_id="t",
        chunker="structure_then_fixed",
        chunk_tokens=50,
        overlap_tokens=5,
        embedder={"model": "fake/embedder", "revision": None},
    )
    folder = build_kb(src, "t", "official", kb, FakeEmbedder(), tmp_path / "kb")
    (entry,) = read_manifest(folder)["documents"]
    override = entry["page_overrides"]["2-3"]
    assert override["path"] == "_overrides/pedoman-hlm2-3.md"
    assert len(override["sha256"]) == 64
    assert {c.doc_id for c in load_kb("t", tmp_path / "kb").chunks} == {"pmb/pedoman"}


@pytest.mark.parametrize(
    ("yaml_overrides", "message"),
    [
        ('    "5-6": _overrides/pedoman-hlm2-3.md\n', "halaman"),  # di luar jumlah halaman
        ('    "3-2": _overrides/pedoman-hlm2-3.md\n', "tidak valid"),
        ('    "2-3": _overrides/tidak-ada.md\n', "tidak ada"),
        ('    "2": _overrides/pedoman-hlm2-3.md\n    "2-3": _overrides/pedoman-hlm2-3.md\n',
         "tumpang tindih"),
        ('    "2-3": _overrides/x.pdf\n', ".md"),
    ],
)  # fmt: skip
def test_invalid_overrides_rejected(src, yaml_overrides, message):
    sources = src / "sources.yaml"
    head = sources.read_text(encoding="utf-8").split("  page_overrides:\n")[0]
    sources.write_text(head + "  page_overrides:\n" + yaml_overrides, encoding="utf-8")
    with pytest.raises(KbBuildError, match=message):
        load_sources(src, "official")


def test_overrides_only_for_pdf(tmp_path):
    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "a.md").write_text("isi", encoding="utf-8")
    (folder / "sources.yaml").write_text(
        'a.md: {valid_from: 2026-01-01, page_overrides: {"1": x.md}}\n', encoding="utf-8"
    )
    with pytest.raises(KbBuildError, match="hanya untuk PDF"):
        load_sources(folder, "official")


@pytest.mark.parametrize(("key", "pages"), [("8-9", (8, 9)), ("8", (8, 8)), (" 8 - 9 ", (8, 9))])
def test_parse_page_range(key, pages):
    assert parse_page_range(key) == pages


@pytest.mark.parametrize("key", ["0-1", "9-8", "a", "8-", ""])
def test_parse_page_range_invalid(key):
    with pytest.raises(ValueError):
        parse_page_range(key)


# --- komentar HTML di MdParser umum ---------------------------------------------------------


def test_strip_html_comments():
    assert strip_html_comments("a <!-- x --> b\n<!--\nc\n-->\nd") == "a  b\n\nd"


def test_md_parser_drops_html_comments(tmp_path):
    path = tmp_path / "a.md"
    path.write_text(
        "---\ntitle: A\n---\n<!-- catatan -->\n# Biaya\n\nRp300.000 <!-- cek lagi -->\n",
        encoding="utf-8",
    )
    doc = MdParser().parse(path)
    assert [(b.section, b.text) for b in doc.blocks] == [("Biaya", "Rp300.000")]
    assert doc.frontmatter["title"] == "A"


def test_md_blocks_nested_paths():
    lines = ["## A", "x", "### B", "y", "#### C", "z", "### D", "w", "## E", "v"]
    assert [b.section for b in md_blocks(lines, nested=True)] == [
        "A",
        "A › B",
        "A › B › C",
        "A › D",
        "E",
    ]
    assert [b.section for b in md_blocks(lines)] == ["A", "B", "C", "D", "E"]
