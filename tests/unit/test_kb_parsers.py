import logging
from datetime import date

import pytest
from kb_samples import (
    MD,
    TXT,
    make_kb_folder,
    write_blank_pdf,
    write_docx,
    write_text_pdf,
)

from mica.core.types import ErrorCode
from mica.kb.parsers import (
    Block,
    DocxParser,
    KbBuildError,
    MdParser,
    PdfParser,
    TxtParser,
    load_sources,
)


def test_txt_parser(tmp_path):
    path = tmp_path / "brosur.txt"
    path.write_text(TXT, encoding="utf-8")
    doc = TxtParser().parse(path)
    assert doc.doc_id == "brosur"
    assert doc.blocks == (Block(section="", text=TXT.strip()),)


def test_md_parser_sections_and_table(tmp_path):
    path = tmp_path / "biaya.md"
    path.write_text(MD, encoding="utf-8")
    blocks = MdParser().parse(path).blocks
    assert [(b.section, b.table is not None) for b in blocks] == [
        ("", False),
        ("Biaya", False),
        ("Biaya", True),
        ("Beasiswa", False),
    ]
    assert blocks[1].text == "Biaya pendaftaran Rp300.000."
    assert blocks[2].table == (
        ("Prodi", "Biaya per semester"),
        ("Informatika", "Rp7.000.000"),
        ("Sistem Informasi", "Rp6.500.000"),
    )


def test_md_heading_inside_code_fence_ignored(tmp_path):
    path = tmp_path / "x.md"
    path.write_text("# A\n```\n# bukan heading\n```\n", encoding="utf-8")
    blocks = MdParser().parse(path).blocks
    assert len(blocks) == 1 and blocks[0].section == "A"
    assert "# bukan heading" in blocks[0].text


def test_pdf_parser(tmp_path):
    path = tmp_path / "panduan.pdf"
    write_text_pdf(path, ["Panduan pendaftaran online.", "Unggah rapor (PDF)."])
    doc = PdfParser().parse(path)
    assert "Panduan pendaftaran online." in doc.blocks[0].text
    assert "Unggah rapor (PDF)." in doc.blocks[0].text


def test_pdf_without_text_skipped(tmp_path, caplog):
    path = tmp_path / "pindaian.pdf"
    write_blank_pdf(path)
    with caplog.at_level(logging.WARNING):
        assert PdfParser().parse(path) is None
    assert ErrorCode.KB_PDF_NO_TEXT in caplog.text


def test_docx_parser_headings_and_table(tmp_path):
    path = tmp_path / "jalur.docx"
    write_docx(path)
    blocks = DocxParser().parse(path).blocks
    assert [(b.section, b.table is not None) for b in blocks] == [
        ("", False),
        ("Jalur Masuk", False),
        ("Jalur Masuk", True),
        ("Fasilitas", False),
    ]
    assert blocks[2].table[0] == ("Jalur", "Syarat")
    assert blocks[2].table[1:] == (("Undangan", "Rapor"), ("Reguler", "Tes"))


def test_block_requires_exactly_one_of_text_or_table():
    with pytest.raises(ValueError):
        Block(section="x")
    with pytest.raises(ValueError):
        Block(section="x", text="a", table=(("a",),))


def test_load_sources_reads_all_four_formats(tmp_path):
    docs = load_sources(make_kb_folder(tmp_path / "src"), "official")
    by_id = {d.doc_id: d for d in docs}
    assert set(by_id) == {"brosur", "biaya", "panduan", "jalur"}
    assert by_id["biaya"].doc_title == "Rincian Biaya"
    assert by_id["biaya"].valid_from == date(2026, 8, 1)
    assert by_id["panduan"].valid_from == date(2026, 7, 15)  # tanggal sebagai string
    assert all(d.source_type == "official" for d in docs)
    assert all(d.blocks for d in docs)


def test_missing_valid_from_rejected(tmp_path):
    folder = make_kb_folder(tmp_path / "src", 'brosur.txt: {title: "Brosur"}\n')
    with pytest.raises(KbBuildError) as exc:
        load_sources(folder, "dev")
    assert exc.value.code == ErrorCode.KB_MISSING_DATE
    for name in ("brosur.txt", "biaya.md", "panduan.pdf", "jalur.docx"):
        assert name in str(exc.value)


def test_missing_valid_from_allowed(tmp_path):
    folder = make_kb_folder(tmp_path / "src", 'brosur.txt: {title: "Brosur"}\n')
    docs = load_sources(folder, "dev", allow_missing_date=True)
    assert len(docs) == 4
    assert all(d.valid_from is None for d in docs)
    assert {d.doc_id: d.doc_title for d in docs}["biaya"] == "biaya"  # judul default nama file


def test_load_sources_skips_pdf_without_text(tmp_path, caplog):
    folder = make_kb_folder(tmp_path / "src")
    write_blank_pdf(folder / "pindaian.pdf")
    with caplog.at_level(logging.WARNING):
        docs = load_sources(folder, "official")  # tanpa tanggal pun tidak ditolak, karena dilewati
    assert "pindaian" not in {d.doc_id for d in docs}
    assert ErrorCode.KB_PDF_NO_TEXT in caplog.text


def test_duplicate_doc_id_rejected(tmp_path):
    folder = make_kb_folder(tmp_path / "src")
    (folder / "brosur.md").write_text("# x\nisi", encoding="utf-8")
    with pytest.raises(KbBuildError):
        load_sources(folder, "official", allow_missing_date=True)
