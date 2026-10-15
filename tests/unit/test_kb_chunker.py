import re
from datetime import date

import pytest
from kb_samples import make_kb_folder

from mica.core.types import Chunk, ErrorCode
from mica.kb.chunker import FixedChunker, StructureThenFixedChunker, make_chunker
from mica.kb.parsers import Block, KbBuildError, ParsedDocument, load_sources


def count_words(text: str) -> int:
    return len(text.split())


def _doc(*blocks: Block, valid_from: date | None = date(2026, 8, 1)) -> ParsedDocument:
    return ParsedDocument(
        doc_id="brosur",
        doc_title="Brosur PMB",
        valid_from=valid_from,
        source_type="official",
        blocks=blocks,
    )


WORDS = " ".join(f"w{i}" for i in range(10))
CHUNKERS = [StructureThenFixedChunker, FixedChunker]


@pytest.mark.parametrize("cls", CHUNKERS)
def test_no_default_parameters(cls):
    with pytest.raises(TypeError):
        cls()


@pytest.mark.parametrize("cls", CHUNKERS)
@pytest.mark.parametrize(
    ("overlap", "expected"),
    [
        (0, ["w0 w1 w2 w3", "w4 w5 w6 w7", "w8 w9"]),
        (1, ["w0 w1 w2 w3", "w3 w4 w5 w6", "w6 w7 w8 w9"]),
        (2, ["w0 w1 w2 w3", "w2 w3 w4 w5", "w4 w5 w6 w7", "w6 w7 w8 w9"]),
    ],
)
def test_overlap(cls, overlap, expected):
    chunks = cls(4, overlap, count_words).split(_doc(Block(section="A", text=WORDS)))
    assert [c.text for c in chunks] == expected


@pytest.mark.parametrize("cls", CHUNKERS)
def test_invalid_sizes_rejected(cls):
    with pytest.raises(ValueError):
        cls(4, 4, count_words)
    with pytest.raises(ValueError):
        cls(0, 0, count_words)


def test_short_section_kept_whole_with_newlines():
    text = "Baris satu.\nBaris dua."
    chunks = StructureThenFixedChunker(50, 5, count_words).split(_doc(Block("A", text=text)))
    assert [c.text for c in chunks] == [text]


def test_structure_chunker_keeps_sections_apart():
    doc = _doc(Block("A", text="a1 a2 a3"), Block("B", text="b1 b2 b3"))
    chunks = StructureThenFixedChunker(10, 2, count_words).split(doc)
    assert [(c.section, c.text) for c in chunks] == [("A", "a1 a2 a3"), ("B", "b1 b2 b3")]


def test_fixed_chunker_ignores_sections():
    doc = _doc(Block("A", text="a1 a2 a3"), Block("B", text="b1 b2 b3"))
    chunks = FixedChunker(4, 0, count_words).split(doc)
    assert [(c.section, c.text) for c in chunks] == [("A", "a1 a2 a3 b1"), ("B", "b2 b3")]


SMALL_TABLE = (("Prodi", "Biaya"), ("Informatika", "Rp7.000.000"), ("SI", "Rp6.500.000"))


@pytest.mark.parametrize("cls", CHUNKERS)
def test_small_table_kept_whole(cls):
    chunks = cls(20, 2, count_words).split(_doc(Block("Biaya", table=SMALL_TABLE)))
    assert len(chunks) == 1
    assert chunks[0].is_table
    assert chunks[0].text == "Prodi | Biaya\nInformatika | Rp7.000.000\nSI | Rp6.500.000"


@pytest.mark.parametrize("cls", CHUNKERS)
def test_large_table_rows_carry_header(cls):
    header = ("Prodi", "Biaya")
    rows = tuple((f"Prodi{i}", f"Rp{i}.000") for i in range(6))
    chunk_tokens = 9  # judul (3 kata) + dua baris (3 kata per baris)
    chunks = cls(chunk_tokens, 2, count_words).split(_doc(Block("Biaya", table=(header, *rows))))
    assert len(chunks) == 3
    seen_rows = []
    for chunk in chunks:
        lines = chunk.text.split("\n")
        assert chunk.is_table
        assert lines[0] == "Prodi | Biaya"
        assert count_words(chunk.text) <= chunk_tokens
        seen_rows += lines[1:]
    # setiap baris data muncul tepat sekali dan tidak terpotong
    assert seen_rows == [f"Prodi{i} | Rp{i}.000" for i in range(6)]


def test_table_between_text_keeps_order():
    doc = _doc(
        Block("A", text="sebelum tabel"),
        Block("A", table=SMALL_TABLE),
        Block("A", text="sesudah tabel"),
    )
    for cls in CHUNKERS:
        chunks = cls(20, 2, count_words).split(doc)
        assert [c.is_table for c in chunks] == [False, True, False]
        assert [c.chunk_id for c in chunks] == ["brosur#0", "brosur#1", "brosur#2"]


@pytest.mark.parametrize("cls", CHUNKERS)
def test_missing_valid_from_rejected(cls):
    with pytest.raises(KbBuildError) as exc:
        cls(10, 2, count_words).split(_doc(Block("A", text="x"), valid_from=None))
    assert exc.value.code == ErrorCode.KB_MISSING_DATE


@pytest.mark.parametrize("cls", CHUNKERS)
def test_every_chunk_has_complete_metadata(tmp_path, cls):
    docs = load_sources(make_kb_folder(tmp_path / "src"), "official")
    chunker = cls(6, 2, count_words)
    by_doc = {d.doc_id: d for d in docs}
    chunks = [c for d in docs for c in chunker.split(d)]
    assert {c.doc_id for c in chunks} == set(by_doc)
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    for c in chunks:
        doc = by_doc[c.doc_id]
        assert isinstance(c, Chunk)
        assert re.fullmatch(rf"{re.escape(c.doc_id)}#\d+", c.chunk_id)
        assert c.doc_title == doc.doc_title and c.doc_title
        assert isinstance(c.section, str)
        assert c.valid_from == doc.valid_from and isinstance(c.valid_from, date)
        assert c.source_type == "official"
        assert c.text.strip()
    # judul bagian dari MD dan DOCX terbawa
    sections = {(c.doc_id, c.section) for c in chunks}
    assert ("biaya", "Beasiswa") in sections
    assert ("jalur", "Jalur Masuk") in sections


def test_make_chunker_selects_by_config():
    assert isinstance(make_chunker("fixed", 10, 2, count_words), FixedChunker)
    chunker = make_chunker("structure_then_fixed", 10, 2, count_words)
    assert isinstance(chunker, StructureThenFixedChunker)
    with pytest.raises(ValueError):
        make_chunker("semantic", 10, 2, count_words)
    with pytest.raises(ValueError):
        make_chunker("fixed", None, None, count_words)  # masih TBD di config
