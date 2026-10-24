"""Langkah 62: ekstraksi PDF (spasi palsu, tanda hubung, heading, halaman) dan sitasi PDF."""

from datetime import date

import pytest
from kb_samples import lines_stream, split_word_stream, write_pdf_pages
from pypdf import PdfReader

from mica.core.types import Chunk, source_title
from mica.kb.chunker import FixedChunker, StructureThenFixedChunker, make_chunker
from mica.kb.parsers import (
    Block,
    MdParser,
    ParsedDocument,
    PdfParser,
    drop_printed_page_number,
    heading_level,
    join_line_end_hyphens,
    layout_evidence,
    pdf_blocks,
    pdf_lines,
    repair_split_words,
)


def count_words(text: str) -> int:
    return len(text.split())


def _repair(plain: str, layout: str) -> str:
    return repair_split_words(plain, *layout_evidence(layout))


# --- penyebab: geseran TJ tidak dihitung extract_text() biasa ---------------------------------


def test_cause_tj_offsets_insert_space_in_plain_mode(tmp_path):
    # Dua objek teks yang bersambung di tengah kata "dalam". Dengan geseran TJ, mode biasa
    # mengira ada celah dan menyisipkan spasi; tanpa geseran (pembanding) tidak.
    with_kern, without_kern = tmp_path / "kern.pdf", tmp_path / "tanpa.pdf"
    write_pdf_pages(with_kern, [split_word_stream("semester d", "alam")])
    write_pdf_pages(without_kern, [split_word_stream("semester d", "alam", kern=0)])
    page = PdfReader(with_kern).pages[0]
    assert page.extract_text() == "semester d alam"
    assert page.extract_text(extraction_mode="layout").strip() == "semester dalam"
    assert PdfReader(without_kern).pages[0].extract_text() == "semester dalam"


def test_pdf_parser_repairs_split_word(tmp_path):
    path = tmp_path / "kern.pdf"
    write_pdf_pages(path, [split_word_stream("semester d", "alam")])
    doc = PdfParser().parse(path)
    assert doc.blocks[0].text == "semester dalam"


# --- spasi palsu -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("plain", "layout", "expected"),
    [
        ("setiap semester d alam Progam", "setiap  semester  dalam   Progam", "setiap semester dalam Progam"),
        ("Organisasi K em ahasiswaan Intra", "Organisasi Kemahasiswaan Intra", "Organisasi Kemahasiswaan Intra"),
        ("tindakan -tindakan, nilai -nilai,", "tindakan-tindakan,  nilai-nilai,", "tindakan-tindakan, nilai-nilai,"),
        ("kemahasiswaan melak -", "kemahasiswaan   melak-", "kemahasiswaan melak-"),
        # spasi yang juga ada di layout adalah spasi asli, walau gabungannya ada di halaman
        ("dapat dilakukan di mana saja", "di mana saja; dimana", "dapat dilakukan di mana saja"),
        # gabungan tidak ada di layout: dibiarkan (layout juga memisahkannya)
        ("capaian pembelaja ran dapat", "capaian   pembelaja        ran   dapat", "capaian pembelaja ran dapat"),
        # spasi berlebih dirapikan, isi tetap
        ("Lainnya  (pengalaman  kerja ", "", "Lainnya (pengalaman kerja"),
    ],
)  # fmt: skip
def test_repair_split_words(plain, layout, expected):
    assert _repair(plain, layout) == expected


def test_layout_pairs_across_lines_count_as_real_space():
    # "di" di akhir baris layout dan "mana" di awal baris berikutnya: spasi asli
    assert _repair("di mana", "dilakukan di\nmana saja dimana") == "di mana"


def test_reduplicated_words_not_merged_or_broken():
    assert (
        _repair("lain-lain masing-masing", "lain-lain   masing-masing") == "lain-lain masing-masing"
    )


# --- tanda hubung di akhir baris -------------------------------------------------------------


def _join(*lines, pages=None, extra=()):
    pages = pages or [1] * len(lines)
    joined = join_line_end_hyphens([*zip(lines, pages, strict=True), *((t, 9) for t in extra)])
    return [text for text, page in joined if page != 9]


def test_reduplication_keeps_hyphen():
    assert _join("pada Program Studi masing-", "masing yang") == [
        "pada Program Studi masing-masing",
        "yang",
    ]
    assert _join("seleksi, dan lain-", "lain) bila") == ["seleksi, dan lain-lain)", "bila"]


def test_hyphenated_form_in_document_keeps_hyphen():
    lines = _join("dalam perundang-", "undangan yang", extra=["peraturan perundang-undangan"])
    assert lines == ["dalam perundang-undangan", "yang"]


def test_syllable_hyphen_removed_when_word_in_document():
    lines = _join("kemahasiswaan melak-", "sanakan pelayanan", extra=["hanya melaksanakan"])
    assert lines == ["kemahasiswaan melaksanakan", "pelayanan"]


def test_unknown_hyphen_left_alone():
    assert _join("dengan tetap mem-", "prioritaskan hal") == [
        "dengan tetap mem-",
        "prioritaskan hal",
    ]


def test_hyphen_not_joined_across_pages():
    lines = join_line_end_hyphens([("Program Studi masing-", 3), ("masing yang", 4)])
    assert lines == [("Program Studi masing-", 3), ("masing yang", 4)]


def test_joined_line_does_not_leave_paragraph_break():
    lines = join_line_end_hyphens([("suatu rambu-", 2), ("rambu", 2), ("kalimat lanjut", 2)])
    assert lines == [("suatu rambu-rambu", 2), ("kalimat lanjut", 2)]


# --- heading ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "level"),
    [
        ("BAB II", 1),
        ("BAB XII ", 1),
        ("Pasal 39", 2),
        ("2.1 Sistem Rekrutmen", 2),
        ("3.3 Pengunduran Diri dan Pengembalian Biaya Pendidikan", 2),
        ("BAB I KETENTUAN UMUM ........................ 2", None),  # daftar isi
        ("2.1 Sistem Rekrutmen ............................ 8", None),
        ("Pasal 25 ayat (8):", None),  # rujukan, bukan judul
        ("2. IPK Sarjana minimal 2.75", None),
        ("2.75 dari skala empat", None),
        ("BAB", None),
        ("3.1 " + "Registrasi " * 12, None),  # terlalu panjang
    ],
)
def test_heading_level(line, level):
    assert heading_level(line) == level


def _lines(*items):
    return [(text, page) for text, page in items]


def test_pdf_blocks_section_path_and_pages():
    lines = _lines(
        ("DAFTAR ISI", 1),
        ("BAB III", 11),
        ("REGISTRASI, PEMBERKASAN", 11),
        ("3.1 Registrasi Administrasi", 11),
        ("a. Bagi peserta seleksi", 11),
        ("membayar uang kuliah.", 12),
        ("3.2 Pemberkasan", 12),
        ("a. Pemberkasan dilakukan.", 12),
    )
    blocks = pdf_blocks(lines)
    assert [(b.section, b.text, b.line_pages) for b in blocks] == [
        ("", "DAFTAR ISI", (1,)),
        (
            "BAB III REGISTRASI, PEMBERKASAN › 3.1 Registrasi Administrasi",
            "a. Bagi peserta seleksi\nmembayar uang kuliah.",
            (11, 12),
        ),
        ("BAB III REGISTRASI, PEMBERKASAN › 3.2 Pemberkasan", "a. Pemberkasan dilakukan.", (12,)),
    ]


def test_pdf_blocks_pasal_title_and_new_chapter():
    lines = _lines(
        ("BAB IV", 27),
        ("SISTEM EVALUASI", 27),
        ("Pasal 39", 30),
        ("Indeks Prestasi", 30),
        ("(1) Hasil penilaian.", 30),
        ("BAB V", 36),
        ("PROGRAM KHUSUS", 36),
        ("Pasal 55", 36),
        ("Fast Track", 36),
        ("(1) Program fast track.", 36),
    )
    sections = [b.section for b in pdf_blocks(lines)]
    assert sections == [
        "BAB IV SISTEM EVALUASI › Pasal 39 Indeks Prestasi",
        "BAB V PROGRAM KHUSUS › Pasal 55 Fast Track",
    ]


def test_pdf_blocks_sentence_after_pasal_is_not_title():
    blocks = pdf_blocks(_lines(("Pasal 7", 5), ("Mahasiswa wajib hadir.", 5)))
    assert [(b.section, b.text) for b in blocks] == [("Pasal 7", "Mahasiswa wajib hadir.")]


def test_pdf_blocks_trim_blank_lines_keep_inner_paragraphs():
    blocks = pdf_blocks(_lines(("", 1), ("satu", 1), ("", 1), ("dua", 2), ("", 2)))
    assert [(b.text, b.line_pages) for b in blocks] == [("satu\n\ndua", (1, 1, 2))]


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["", "5", "", "Teknik Informatika (S-1) /"], ["", "", "Teknik Informatika (S-1) /"]),
        (["BAB I", "isi", "1"], ["BAB I", "isi"]),
        (["ii", "DAFTAR ISI", "iii"], ["DAFTAR ISI"]),
        # angka di tengah halaman atau berisi teks lain tidak dibuang
        (["isi", "7", "isi"], ["isi", "7", "isi"]),
        (["2.", "isi", "Rp300.000"], ["2.", "isi", "Rp300.000"]),
        ([], []),
    ],
)
def test_drop_printed_page_number(lines, expected):
    assert drop_printed_page_number(lines) == expected


def test_page_number_on_next_page_not_counted_in_previous_section():
    pages = [("1.4 Pelaporan\nLaporan PMB.\n3", ""), ("4\nBAB II\nSISTEM\n2.1 Rekrutmen\nisi", "")]
    blocks = pdf_blocks(pdf_lines(pages))
    assert [(b.section, b.text, b.line_pages) for b in blocks] == [
        ("1.4 Pelaporan", "Laporan PMB.", (1,)),
        ("BAB II SISTEM › 2.1 Rekrutmen", "isi", (2,)),
    ]


def test_pdf_lines_numbers_pages_from_one():
    lines = pdf_lines([("hal satu", "hal satu"), ("hal dua\nlanjut", "hal dua\nlanjut")])
    assert lines == [("hal satu", 1), ("hal dua", 2), ("lanjut", 2)]


def test_block_line_pages_must_match_lines():
    with pytest.raises(ValueError):
        Block("A", text="a\nb", line_pages=(1,))


def test_pdf_parser_pages_and_sections(tmp_path):
    path = tmp_path / "pedoman.pdf"
    write_pdf_pages(
        path,
        [
            lines_stream(["Sampul pedoman"]),
            lines_stream(["BAB I", "PENGELOLAAN", "1.1 Perencanaan", "Panitia dibentuk Rektor."]),
            lines_stream(["Panitia bertugas setahun.", "1.2 Jalur Seleksi", "Jalur PMDK."]),
        ],
    )
    doc = PdfParser().parse(path)
    assert [(b.section, b.line_pages) for b in doc.blocks] == [
        ("", (1,)),
        ("BAB I PENGELOLAAN › 1.1 Perencanaan", (2, 3)),
        ("BAB I PENGELOLAAN › 1.2 Jalur Seleksi", (3,)),
    ]


# --- chunker: halaman dan prefiks bagian -----------------------------------------------------


def _doc(*blocks):
    return ParsedDocument("pmb/pedoman", "Pedoman PMB", date(2026, 7, 27), "official", blocks)


def test_chunk_pages_from_pdf_block():
    block = Block("BAB I › 1.1 Perencanaan", text="a b\nc d", line_pages=(4, 5))
    (chunk,) = StructureThenFixedChunker(50, 5, count_words).split(_doc(block))
    assert (chunk.page_start, chunk.page_end) == (4, 5)


@pytest.mark.parametrize("cls", [StructureThenFixedChunker, FixedChunker])
def test_split_chunks_get_their_own_pages(cls):
    text = "a1 a2 a3\n\nb1 b2 b3\n\nc1 c2 c3"
    block = Block("S", text=text, line_pages=(3, 3, 4, 4, 5))
    chunks = cls(6, 0, count_words).split(_doc(block))
    assert [(c.text, c.page_start, c.page_end) for c in chunks] == [
        ("a1 a2 a3\n\nb1 b2 b3", 3, 4),
        ("c1 c2 c3", 5, 5),
    ]


def test_md_chunks_have_no_pages():
    (chunk,) = StructureThenFixedChunker(50, 5, count_words).split(_doc(Block("A", text="x y")))
    assert (chunk.page_start, chunk.page_end) == (None, None)


def test_section_prefix_in_text_for_text_and_table():
    blocks = (
        Block("", text="pengantar"),
        Block("Jadwal Pembayaran", text="Bagi kelas pagi."),
        Block("Jadwal Pembayaran", table=(("Cicilan Ke-", "Jadwal"), ("1", "1 s.d. 10 JUL 2026"))),
    )
    chunker = make_chunker("structure_then_fixed", 50, 5, count_words)
    assert [c.text for c in chunker.split(_doc(*blocks))] == [
        "pengantar",
        "Jadwal Pembayaran\n\nBagi kelas pagi.",
        "Jadwal Pembayaran\n\nCicilan Ke- | Jadwal\n1 | 1 s.d. 10 JUL 2026",
    ]


def test_section_prefix_counts_toward_chunk_tokens():
    section = "BAB III REGISTRASI › 3.1 Registrasi"  # 5 kata
    block = Block(section, text=" ".join(f"w{i}" for i in range(20)))
    chunks = make_chunker("structure_then_fixed", 10, 0, count_words).split(_doc(block))
    assert all(count_words(c.text) <= 10 for c in chunks)
    assert all(c.text.startswith(section + "\n\n") for c in chunks)
    assert " ".join(c.text.split("\n\n", 1)[1] for c in chunks) == block.text


def test_without_section_prefix_text_unchanged():
    chunker = make_chunker("structure_then_fixed", 50, 5, count_words, section_prefix=False)
    (chunk,) = chunker.split(_doc(Block("Biaya", text="isi")))
    assert chunk.text == "isi"


def test_installment_table_stays_whole_with_header(tmp_path):
    rows = "\n".join(f"| **{i}** | **Tanggal 1 s.d. 10 BLN {i}** |" for i in range(1, 13))
    path = tmp_path / "panduan-pembayaran.md"
    path.write_text(
        "### Jadwal Pembayaran Uang Kuliah T.A. 2026/2027\n\n"
        "**1. Skema Pembayaran Kelas Pagi (Cicilan 12 kali)**\n\n"
        "Bagi mahasiswa kelas pagi, pembayaran dilakukan tanggal 1 s.d. 10.\n\n"
        "| **Cicilan Ke-** | **Jadwal** |\n| :---: | :---: |\n" + rows + "\n",
        encoding="utf-8",
    )
    doc = MdParser().parse(path)
    doc = ParsedDocument("keuangan/p", "Panduan", date(2026, 7, 1), "official", doc.blocks)
    chunks = make_chunker("structure_then_fixed", 400, 50, count_words).split(doc)
    (table,) = [c for c in chunks if c.is_table]
    assert table.text.startswith(
        "Jadwal Pembayaran Uang Kuliah T.A. 2026/2027\n\n**Cicilan Ke-** | **Jadwal**\n**1** |"
    )
    assert "**12** | **Tanggal 1 s.d. 10 BLN 12**" in table.text


# --- sitasi ----------------------------------------------------------------------------------


def _chunk(section="", page_start=None, page_end=None):
    return Chunk("d#0", "d", "Pedoman PMB 2027", section, date(2026, 7, 27), "official", "isi",
                 False, page_start, page_end)  # fmt: skip


@pytest.mark.parametrize(
    ("chunk", "expected"),
    [
        (_chunk("BAB II X › 2.1 Sistem Rekrutmen", 8, 9), "Pedoman PMB 2027, hlm 8-9, 2.1 Sistem Rekrutmen"),
        (_chunk("BAB IV PENUTUP", 13, 13), "Pedoman PMB 2027, hlm 13, BAB IV PENUTUP"),
        (_chunk("", 3, 3), "Pedoman PMB 2027, hlm 3"),
        (_chunk("Biaya S1"), "Pedoman PMB 2027"),  # bukan PDF: seperti sebelumnya
    ],
)  # fmt: skip
def test_source_title(chunk, expected):
    assert source_title(chunk) == expected
