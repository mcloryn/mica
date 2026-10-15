"""M-02: memotong ParsedDocument menjadi Chunk (ADR-03, Provisional; dipilih lewat kb.chunker).

Teks yang lebih panjang dari chunk_tokens dipecah per paragraf, lalu per baris; pemotongan per
kata hanya untuk satu baris yang sendirian sudah melebihi chunk_tokens. Potongan-potongan itu
lalu digabung lagi sampai chunk_tokens, dengan overlap, sehingga baris baru tetap ada.

Jumlah token sebuah chunk = jumlah token tiap potongan. Untuk tokenizer subword hasilnya mendekati
jumlah token teks utuh; count_tokens sebaiknya tidak menghitung token khusus ([CLS]/[SEP]).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Protocol

from mica.core.types import Chunk, ErrorCode
from mica.kb.parsers import Block, KbBuildError, ParsedDocument

CountTokens = Callable[[str], int]
Table = tuple[tuple[str, ...], ...]

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


class Chunker(Protocol):
    def split(self, doc: ParsedDocument) -> list[Chunk]: ...


@dataclass(frozen=True)
class _Unit:
    section: str
    sep: str  # pemisah dari potongan sebelumnya: "\n\n" antarparagraf, "\n" antarbaris
    text: str
    tokens: int
    standalone: bool = False  # hasil potong per kata; sudah berisi overlap sendiri


def _format_row(row: tuple[str, ...]) -> str:
    return " | ".join(row)


def _format_table(rows: Table) -> str:
    return "\n".join(_format_row(r) for r in rows)


class _BaseChunker:
    def __init__(self, chunk_tokens: int, overlap_tokens: int, count_tokens: CountTokens) -> None:
        if chunk_tokens <= 0:
            raise ValueError("chunk_tokens harus > 0")
        if not 0 <= overlap_tokens < chunk_tokens:
            raise ValueError("overlap_tokens harus >= 0 dan < chunk_tokens")
        self.chunk_tokens = chunk_tokens
        self.overlap_tokens = overlap_tokens
        self.count_tokens = count_tokens

    def _windows(self, words: list[str]) -> Iterator[tuple[int, int]]:
        """Jendela [start, end) berisi paling banyak chunk_tokens, bertumpang overlap_tokens."""
        counts = [self.count_tokens(w) for w in words]
        start = 0
        while start < len(words):
            end, total = start, 0
            # minimal satu kata per jendela, walau satu kata melebihi chunk_tokens
            while end < len(words) and (end == start or total + counts[end] <= self.chunk_tokens):
                total += counts[end]
                end += 1
            yield start, end
            if end == len(words):
                return
            next_start, overlap = end, 0
            while next_start - 1 > start and overlap + counts[next_start - 1] <= self.overlap_tokens:
                next_start -= 1
                overlap += counts[next_start]
            start = next_start

    def _text_units(self, section: str, text: str) -> list[_Unit]:
        units: list[_Unit] = []
        for paragraph in _PARAGRAPH_BREAK.split(text):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            tokens = self.count_tokens(paragraph)
            if tokens <= self.chunk_tokens:
                units.append(_Unit(section, "\n\n", paragraph, tokens))
                continue
            sep = "\n\n"
            for line in paragraph.splitlines():
                line = line.strip()
                if not line:
                    continue
                tokens = self.count_tokens(line)
                if tokens <= self.chunk_tokens:
                    units.append(_Unit(section, sep, line, tokens))
                else:
                    words = line.split()
                    for s, e in self._windows(words):
                        units.append(_Unit(section, sep, " ".join(words[s:e]), 0, standalone=True))
                sep = "\n"
        return units

    def _pack(self, units: list[_Unit]) -> Iterator[tuple[str, str]]:
        """Gabung potongan berurutan sampai chunk_tokens; chunk berikutnya diawali overlap."""
        current: list[_Unit] = []

        def render() -> tuple[str, str]:
            text = current[0].text + "".join(u.sep + u.text for u in current[1:])
            return current[0].section, text

        for unit in units:
            if unit.standalone:
                if current:
                    yield render()
                    current = []
                yield unit.section, unit.text
                continue
            total = sum(u.tokens for u in current)
            if current and total + unit.tokens > self.chunk_tokens:
                yield render()
                # overlap: potongan terakhir yang totalnya <= overlap_tokens dan masih muat
                tail: list[_Unit] = []
                tail_tokens = 0
                for prev in reversed(current[1:]):
                    if tail_tokens + prev.tokens > self.overlap_tokens:
                        break
                    if tail_tokens + prev.tokens + unit.tokens > self.chunk_tokens:
                        break
                    tail.insert(0, prev)
                    tail_tokens += prev.tokens
                current = tail
            current.append(unit)
        if current:
            yield render()

    def _split_table(self, rows: Table) -> list[str]:
        text = _format_table(rows)
        if self.count_tokens(text) <= self.chunk_tokens or len(rows) <= 1:
            return [text]
        # Tabel besar: baris data dikelompokkan tanpa dipotong, setiap kelompok membawa judul kolom.
        header, body = rows[0], rows[1:]
        header_tokens = self.count_tokens(_format_row(header))
        pieces: list[str] = []
        group: list[tuple[str, ...]] = []
        total = header_tokens
        for row in body:
            row_tokens = self.count_tokens(_format_row(row))
            if group and total + row_tokens > self.chunk_tokens:
                pieces.append(_format_table((header, *group)))
                group, total = [], header_tokens
            group.append(row)
            total += row_tokens
        pieces.append(_format_table((header, *group)))
        return pieces

    @staticmethod
    def _make(doc: ParsedDocument, index: int, section: str, text: str, is_table: bool) -> Chunk:
        return Chunk(
            chunk_id=f"{doc.doc_id}#{index}",
            doc_id=doc.doc_id,
            doc_title=doc.doc_title,
            section=section,
            valid_from=doc.valid_from,  # type: ignore[arg-type]  # sudah dicek tidak None
            source_type=doc.source_type,
            text=text,
            is_table=is_table,
        )

    def split(self, doc: ParsedDocument) -> list[Chunk]:
        # Chunk.valid_from wajib (SDD 5.1, F-16): dokumen tanpa tanggal tidak bisa dipotong.
        if doc.valid_from is None:
            raise KbBuildError(
                ErrorCode.KB_MISSING_DATE, f"{doc.doc_id}: valid_from kosong, tidak bisa dipotong"
            )
        pieces = list(self._pieces(doc.blocks))
        return [
            self._make(doc, i, section, text, is_table)
            for i, (section, text, is_table) in enumerate(pieces)
        ]

    def _pieces(self, blocks: tuple[Block, ...]) -> Iterator[tuple[str, str, bool]]:
        raise NotImplementedError


class StructureThenFixedChunker(_BaseChunker):
    """Potong per bagian dulu; bagian yang lebih panjang dari chunk_tokens dipecah dengan overlap."""

    def _pieces(self, blocks: tuple[Block, ...]) -> Iterator[tuple[str, str, bool]]:
        for block in blocks:
            if block.table is not None:
                for text in self._split_table(block.table):
                    yield block.section, text, True
            elif block.text:
                if self.count_tokens(block.text) <= self.chunk_tokens:
                    yield block.section, block.text, False
                    continue
                for section, text in self._pack(self._text_units(block.section, block.text)):
                    yield section, text, False


class FixedChunker(_BaseChunker):
    """Potong teks berurutan tanpa memperhatikan bagian; section = bagian tempat chunk dimulai."""

    def _pieces(self, blocks: tuple[Block, ...]) -> Iterator[tuple[str, str, bool]]:
        units: list[_Unit] = []

        def flush() -> Iterator[tuple[str, str, bool]]:
            for section, text in self._pack(units):
                yield section, text, False
            units.clear()

        for block in blocks:
            if block.table is not None:
                # tabel tetap utuh atau dipecah per baris dengan judul kolom
                yield from flush()
                for text in self._split_table(block.table):
                    yield block.section, text, True
            elif block.text:
                units.extend(self._text_units(block.section, block.text))
        yield from flush()


CHUNKERS: dict[str, type[_BaseChunker]] = {
    "structure_then_fixed": StructureThenFixedChunker,
    "fixed": FixedChunker,
}


def make_chunker(
    kind: str, chunk_tokens: int | None, overlap_tokens: int | None, count_tokens: CountTokens
) -> Chunker:
    """Pilih chunker dari kb.chunker; kb.chunk_tokens dan kb.overlap_tokens wajib sudah diisi."""
    if kind not in CHUNKERS:
        raise ValueError(f"kb.chunker tidak dikenal: {kind!r}")
    if chunk_tokens is None or overlap_tokens is None:
        raise ValueError("kb.chunk_tokens dan kb.overlap_tokens belum diisi (E-01)")
    return CHUNKERS[kind](chunk_tokens, overlap_tokens, count_tokens)
