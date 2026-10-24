"""M-02: memotong ParsedDocument menjadi Chunk (ADR-03, Provisional; dipilih lewat kb.chunker).

Teks yang lebih panjang dari chunk_tokens dipecah per paragraf, lalu per baris; pemotongan per
kata hanya untuk satu baris yang sendirian sudah melebihi chunk_tokens. Potongan-potongan itu
lalu digabung lagi sampai chunk_tokens, dengan overlap, sehingga baris baru tetap ada.

Jumlah token sebuah chunk = jumlah token tiap potongan. Untuk tokenizer subword hasilnya mendekati
jumlah token teks utuh; count_tokens sebaiknya tidak menghitung token khusus ([CLS]/[SEP]).

Sejak Langkah 62 (section_prefix): teks setiap chunk diawali jalur bagiannya (section) dan satu
baris kosong, untuk .md maupun PDF. Token jalur bagian terpanjang di dokumen dipotong dari
anggaran chunk_tokens, sehingga chunk tetap <= chunk_tokens. Chunk dari PDF mencatat halaman
awal dan akhir (nomor halaman PDF, mulai 1).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol

from mica.core.types import Chunk, ErrorCode
from mica.kb.parsers import Block, KbBuildError, ParsedDocument

CountTokens = Callable[[str], int]
Table = tuple[tuple[str, ...], ...]

SECTION_PREFIX_SEP = "\n\n"


class Chunker(Protocol):
    def split(self, doc: ParsedDocument) -> list[Chunk]: ...


@dataclass(frozen=True)
class _Unit:
    section: str
    sep: str  # pemisah dari potongan sebelumnya: "\n\n" antarparagraf, "\n" antarbaris
    text: str
    tokens: int
    standalone: bool = False  # hasil potong per kata; sudah berisi overlap sendiri
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class _Piece:
    section: str
    text: str
    is_table: bool
    page_start: int | None = None
    page_end: int | None = None


def _page_range(pages: Iterable[int | None]) -> tuple[int | None, int | None]:
    known = [p for p in pages if p is not None]
    return (min(known), max(known)) if known else (None, None)


def _format_row(row: tuple[str, ...]) -> str:
    return " | ".join(row)


def _format_table(rows: Table) -> str:
    return "\n".join(_format_row(r) for r in rows)


class _BaseChunker:
    def __init__(
        self,
        chunk_tokens: int,
        overlap_tokens: int,
        count_tokens: CountTokens,
        section_prefix: bool = False,
    ) -> None:
        if chunk_tokens <= 0:
            raise ValueError("chunk_tokens harus > 0")
        if not 0 <= overlap_tokens < chunk_tokens:
            raise ValueError("overlap_tokens harus >= 0 dan < chunk_tokens")
        self.chunk_tokens = chunk_tokens
        self.overlap_tokens = overlap_tokens
        self.count_tokens = count_tokens
        self.section_prefix = section_prefix

    def _limit(self, blocks: tuple[Block, ...]) -> int:
        """Anggaran token isi chunk: chunk_tokens dikurangi jalur bagian terpanjang."""
        if not self.section_prefix:
            return self.chunk_tokens
        reserve = max((self.count_tokens(b.section) for b in blocks if b.section), default=0)
        return max(self.chunk_tokens - reserve, self.overlap_tokens + 1)

    def _windows(self, words: list[str], limit: int) -> Iterator[tuple[int, int]]:
        """Jendela [start, end) berisi paling banyak limit token, bertumpang overlap_tokens."""
        counts = [self.count_tokens(w) for w in words]
        start = 0
        while start < len(words):
            end, total = start, 0
            # minimal satu kata per jendela, walau satu kata melebihi limit
            while end < len(words) and (end == start or total + counts[end] <= limit):
                total += counts[end]
                end += 1
            yield start, end
            if end == len(words):
                return
            next_start, overlap = end, 0
            while (
                next_start - 1 > start and overlap + counts[next_start - 1] <= self.overlap_tokens
            ):
                next_start -= 1
                overlap += counts[next_start]
            start = next_start

    def _text_units(
        self, section: str, text: str, pages: tuple[int, ...] | None, limit: int
    ) -> list[_Unit]:
        # paragraf = baris berurutan yang tidak kosong (sama dengan memecah di \n\s*\n)
        lines = text.split("\n")
        line_pages: Iterable[int | None] = pages if pages is not None else [None] * len(lines)
        paragraphs: list[list[tuple[str, int | None]]] = []
        current: list[tuple[str, int | None]] = []
        for line, page in zip(lines, line_pages, strict=True):
            if line.strip():
                current.append((line, page))
            elif current:
                paragraphs.append(current)
                current = []
        if current:
            paragraphs.append(current)

        units: list[_Unit] = []
        for paragraph_lines in paragraphs:
            paragraph = "\n".join(line for line, _ in paragraph_lines).strip()
            tokens = self.count_tokens(paragraph)
            if tokens <= limit:
                start, end = _page_range(page for _, page in paragraph_lines)
                units.append(_Unit(section, "\n\n", paragraph, tokens, False, start, end))
                continue
            sep = "\n\n"
            for line, page in paragraph_lines:
                line = line.strip()
                tokens = self.count_tokens(line)
                if tokens <= limit:
                    units.append(_Unit(section, sep, line, tokens, False, page, page))
                else:
                    words = line.split()
                    for s, e in self._windows(words, limit):
                        units.append(_Unit(section, sep, " ".join(words[s:e]), 0, True, page, page))
                sep = "\n"
        return units

    def _pack(self, units: list[_Unit], limit: int) -> Iterator[_Piece]:
        """Gabung potongan berurutan sampai limit token; chunk berikutnya diawali overlap."""
        current: list[_Unit] = []

        def render() -> _Piece:
            text = current[0].text + "".join(u.sep + u.text for u in current[1:])
            start, _ = _page_range(u.page_start for u in current)
            _, end = _page_range(u.page_end for u in current)
            return _Piece(current[0].section, text, False, start, end)

        for unit in units:
            if unit.standalone:
                if current:
                    yield render()
                    current = []
                yield _Piece(unit.section, unit.text, False, unit.page_start, unit.page_end)
                continue
            total = sum(u.tokens for u in current)
            if current and total + unit.tokens > limit:
                yield render()
                # overlap: potongan terakhir yang totalnya <= overlap_tokens dan masih muat
                tail: list[_Unit] = []
                tail_tokens = 0
                for prev in reversed(current[1:]):
                    if tail_tokens + prev.tokens > self.overlap_tokens:
                        break
                    if tail_tokens + prev.tokens + unit.tokens > limit:
                        break
                    tail.insert(0, prev)
                    tail_tokens += prev.tokens
                current = tail
            current.append(unit)
        if current:
            yield render()

    def _split_table(self, rows: Table, limit: int) -> list[str]:
        text = _format_table(rows)
        if self.count_tokens(text) <= limit or len(rows) <= 1:
            return [text]
        # Tabel besar: baris data dikelompokkan tanpa dipotong, setiap kelompok membawa judul kolom.
        header, body = rows[0], rows[1:]
        header_tokens = self.count_tokens(_format_row(header))
        pieces: list[str] = []
        group: list[tuple[str, ...]] = []
        total = header_tokens
        for row in body:
            row_tokens = self.count_tokens(_format_row(row))
            if group and total + row_tokens > limit:
                pieces.append(_format_table((header, *group)))
                group, total = [], header_tokens
            group.append(row)
            total += row_tokens
        pieces.append(_format_table((header, *group)))
        return pieces

    def _make(self, doc: ParsedDocument, index: int, piece: _Piece) -> Chunk:
        text = piece.text
        if self.section_prefix and piece.section:
            text = piece.section + SECTION_PREFIX_SEP + text
        return Chunk(
            chunk_id=f"{doc.doc_id}#{index}",
            doc_id=doc.doc_id,
            doc_title=doc.doc_title,
            section=piece.section,
            valid_from=doc.valid_from,  # type: ignore[arg-type]  # sudah dicek tidak None
            source_type=doc.source_type,
            text=text,
            is_table=piece.is_table,
            page_start=piece.page_start,
            page_end=piece.page_end,
        )

    def split(self, doc: ParsedDocument) -> list[Chunk]:
        # Chunk.valid_from wajib (SDD 5.1, F-16): dokumen tanpa tanggal tidak bisa dipotong.
        if doc.valid_from is None:
            raise KbBuildError(
                ErrorCode.KB_MISSING_DATE, f"{doc.doc_id}: valid_from kosong, tidak bisa dipotong"
            )
        pieces = list(self._pieces(doc.blocks, self._limit(doc.blocks)))
        return [self._make(doc, i, piece) for i, piece in enumerate(pieces)]

    def _pieces(self, blocks: tuple[Block, ...], limit: int) -> Iterator[_Piece]:
        raise NotImplementedError


class StructureThenFixedChunker(_BaseChunker):
    """Potong per bagian dulu; bagian yang lebih panjang dari chunk_tokens dipecah dengan overlap."""

    def _pieces(self, blocks: tuple[Block, ...], limit: int) -> Iterator[_Piece]:
        for block in blocks:
            if block.table is not None:
                for text in self._split_table(block.table, limit):
                    yield _Piece(block.section, text, True)
            elif block.text:
                if self.count_tokens(block.text) <= limit:
                    start, end = _page_range(block.line_pages or ())
                    yield _Piece(block.section, block.text, False, start, end)
                    continue
                units = self._text_units(block.section, block.text, block.line_pages, limit)
                yield from self._pack(units, limit)


class FixedChunker(_BaseChunker):
    """Potong teks berurutan tanpa memperhatikan bagian; section = bagian tempat chunk dimulai."""

    def _pieces(self, blocks: tuple[Block, ...], limit: int) -> Iterator[_Piece]:
        units: list[_Unit] = []

        def flush() -> Iterator[_Piece]:
            yield from self._pack(units, limit)
            units.clear()

        for block in blocks:
            if block.table is not None:
                # tabel tetap utuh atau dipecah per baris dengan judul kolom
                yield from flush()
                for text in self._split_table(block.table, limit):
                    yield _Piece(block.section, text, True)
            elif block.text:
                units.extend(self._text_units(block.section, block.text, block.line_pages, limit))
        yield from flush()


CHUNKERS: dict[str, type[_BaseChunker]] = {
    "structure_then_fixed": StructureThenFixedChunker,
    "fixed": FixedChunker,
}


def make_chunker(
    kind: str,
    chunk_tokens: int | None,
    overlap_tokens: int | None,
    count_tokens: CountTokens,
    section_prefix: bool = True,
) -> Chunker:
    """Pilih chunker dari kb.chunker; kb.chunk_tokens dan kb.overlap_tokens wajib sudah diisi.

    section_prefix True sejak Langkah 62 (KB resmi v2); False = cara KB sebelumnya.
    """
    if kind not in CHUNKERS:
        raise ValueError(f"kb.chunker tidak dikenal: {kind!r}")
    if chunk_tokens is None or overlap_tokens is None:
        raise ValueError("kb.chunk_tokens dan kb.overlap_tokens belum diisi (E-01)")
    return CHUNKERS[kind](chunk_tokens, overlap_tokens, count_tokens, section_prefix)
