"""M-02: membaca dokumen sumber (TXT, MD, PDF, DOCX) menjadi ParsedDocument."""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol

import yaml

from mica.core.types import ErrorCode

logger = logging.getLogger(__name__)

SourceType = Literal["official", "dev"]
SOURCES_FILE = "sources.yaml"


class KbBuildError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = ErrorCode(code)
        self.message = message


@dataclass(frozen=True)
class Block:
    section: str  # judul bagian; "" bila sebelum heading pertama atau format tanpa heading
    text: str | None = None
    table: tuple[tuple[str, ...], ...] | None = None  # baris pertama = judul kolom

    def __post_init__(self) -> None:
        if (self.text is None) == (self.table is None):
            raise ValueError("Block harus berisi tepat satu dari text atau table")


@dataclass(frozen=True)
class ParsedDocument:
    doc_id: str
    doc_title: str
    valid_from: date | None
    source_type: SourceType
    blocks: tuple[Block, ...]
    group: str = ""  # subfolder teratas di folder sumber; "" bila file langsung di sana
    # metadata frontmatter Markdown (title, url, date) untuk init-sources; tidak dipakai build
    frontmatter: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


class DocumentParser(Protocol):
    def parse(self, path: Path) -> ParsedDocument | None:
        """None bila dokumen dilewati (misalnya PDF tanpa teks)."""
        ...


def _document(path: Path, blocks: list[Block]) -> ParsedDocument:
    # Metadata sementara; load_sources mengisinya dari sources.yaml.
    # source_type "dev" sebagai default supaya dokumen tak pernah dianggap resmi tanpa sengaja.
    return ParsedDocument(
        doc_id=path.stem,
        doc_title=path.stem,
        valid_from=None,
        source_type="dev",
        blocks=tuple(blocks),
    )


def _text_block(section: str, lines: list[str]) -> Block | None:
    text = "\n".join(lines).strip()
    return Block(section=section, text=text) if text else None


class TxtParser:
    def parse(self, path: Path) -> ParsedDocument | None:
        block = _text_block("", path.read_text(encoding="utf-8").splitlines())
        return _document(path, [block] if block else [])


_MD_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
_MD_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


FRONTMATTER_KEYS = ("title", "url", "date")


def _split_frontmatter(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    """Pisahkan frontmatter YAML (--- di baris pertama) dari isi Markdown."""
    if not lines or lines[0].strip() != "---":
        return {}, lines
    for end in range(1, len(lines)):
        if lines[end].strip() in ("---", "..."):
            break
    else:
        return {}, lines  # tanpa penutup: bukan frontmatter
    try:
        raw = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError:
        raw = {}
    meta = {}
    if isinstance(raw, dict):
        for key in FRONTMATTER_KEYS:
            value = raw.get(key)
            if value is not None and str(value).strip():
                meta[key] = value.isoformat() if isinstance(value, date) else str(value).strip()
    return meta, lines[end + 1 :]


def _md_row(line: str) -> tuple[str, ...]:
    return tuple(cell.strip() for cell in line.strip().strip("|").split("|"))


class MdParser:
    def parse(self, path: Path) -> ParsedDocument | None:
        frontmatter, lines = _split_frontmatter(path.read_text(encoding="utf-8").splitlines())
        blocks: list[Block] = []
        section = ""
        buffer: list[str] = []
        in_fence = False

        def flush() -> None:
            block = _text_block(section, buffer)
            if block:
                blocks.append(block)
            buffer.clear()

        i = 0
        while i < len(lines):
            line = lines[i]
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
            elif not in_fence and (heading := _MD_HEADING.match(line)):
                flush()
                section = heading.group(1)
                i += 1
                continue
            elif (
                not in_fence
                and line.lstrip().startswith("|")
                and i + 1 < len(lines)
                and _MD_TABLE_SEP.match(lines[i + 1])
            ):
                # tabel pipa Markdown: baris judul, baris pemisah, lalu baris data
                flush()
                rows = [_md_row(line)]
                i += 2
                while i < len(lines) and lines[i].lstrip().startswith("|"):
                    rows.append(_md_row(lines[i]))
                    i += 1
                blocks.append(Block(section=section, table=tuple(rows)))
                continue
            buffer.append(line)
            i += 1
        flush()
        return dataclasses.replace(
            _document(path, blocks), frontmatter=MappingProxyType(frontmatter)
        )


class PdfParser:
    def parse(self, path: Path) -> ParsedDocument | None:
        from pypdf import PdfReader

        pages = [(page.extract_text() or "") for page in PdfReader(path).pages]
        block = _text_block("", "\n".join(pages).splitlines())
        if block is None:
            # PDF hasil pindai butuh OCR, di luar cakupan (SDD 2.3)
            logger.warning("%s: %s tidak berisi teks, dilewati", ErrorCode.KB_PDF_NO_TEXT, path)
            return None
        return _document(path, [block])


class DocxParser:
    def parse(self, path: Path) -> ParsedDocument | None:
        import docx
        from docx.text.paragraph import Paragraph

        document = docx.Document(str(path))
        blocks: list[Block] = []
        section = ""
        buffer: list[str] = []

        def flush() -> None:
            block = _text_block(section, buffer)
            if block:
                blocks.append(block)
            buffer.clear()

        # Paragraf dan tabel dibaca berurutan dari body supaya tabel tetap di bagiannya.
        tables = {t._tbl: t for t in document.tables}
        for child in document.element.body.iterchildren():
            if child in tables:
                flush()
                rows = tuple(
                    tuple(cell.text.strip() for cell in row.cells) for row in tables[child].rows
                )
                if rows:
                    blocks.append(Block(section=section, table=rows))
            elif child.tag.endswith("}p"):
                paragraph = Paragraph(child, document)
                style = paragraph.style.name if paragraph.style is not None else ""
                if style.startswith("Heading") and paragraph.text.strip():
                    flush()
                    section = paragraph.text.strip()
                else:
                    buffer.append(paragraph.text)
        flush()
        return _document(path, blocks)


PARSERS: dict[str, DocumentParser] = {
    ".txt": TxtParser(),
    ".md": MdParser(),
    ".pdf": PdfParser(),
    ".docx": DocxParser(),
}


def _read_sources(folder: Path) -> dict[str, dict[str, Any]]:
    path = folder / SOURCES_FILE
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise KbBuildError(ErrorCode.KB_INVALID, f"{path}: isi harus mapping nama-file -> metadata")
    return {str(name): (meta or {}) for name, meta in raw.items()}


def _parse_date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def iter_source_files(folder: Path) -> list[Path]:
    """Semua file berformat didukung di folder sumber dan subfoldernya, terurut.

    File dan folder yang namanya diawali titik dilewati.
    """
    folder = Path(folder)
    files = []
    for path in folder.rglob("*"):
        rel = path.relative_to(folder)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if path.is_file() and path.suffix.lower() in PARSERS:
            files.append(path)
    return sorted(files, key=lambda p: p.relative_to(folder).as_posix())


def source_key(folder: Path, path: Path) -> str:
    """Kunci di sources.yaml: path relatif dengan "/", misalnya biaya/uang-kuliah.md."""
    return path.relative_to(folder).as_posix()


def doc_id_for(folder: Path, path: Path) -> str:
    return path.relative_to(folder).with_suffix("").as_posix()


def parse_file(folder: Path, path: Path) -> ParsedDocument | None:
    """Parse satu file dengan doc_id dan group sesuai posisinya di folder sumber."""
    parsed = PARSERS[path.suffix.lower()].parse(path)
    if parsed is None:
        return None
    parts = path.relative_to(folder).parts
    return dataclasses.replace(
        parsed, doc_id=doc_id_for(folder, path), group=parts[0] if len(parts) > 1 else ""
    )


def load_sources(
    folder: Path, source_type: SourceType, allow_missing_date: bool = False
) -> list[ParsedDocument]:
    folder = Path(folder)
    if source_type not in ("official", "dev"):
        raise ValueError(f"source_type tidak dikenal: {source_type!r}")
    sources = _read_sources(folder)

    documents: list[ParsedDocument] = []
    missing_date: list[str] = []
    seen_ids: dict[str, str] = {}
    for path in iter_source_files(folder):
        key = source_key(folder, path)
        doc_id = doc_id_for(folder, path)
        if doc_id in seen_ids:
            raise KbBuildError(
                ErrorCode.KB_INVALID, f"doc_id {doc_id!r} ganda: {seen_ids[doc_id]} dan {key}"
            )
        seen_ids[doc_id] = key

        parsed = parse_file(folder, path)
        if parsed is None:
            continue
        meta = sources.get(key, {})
        valid_from = _parse_date(meta.get("valid_from"))
        if valid_from is None:
            missing_date.append(key)
        documents.append(
            dataclasses.replace(
                parsed,
                doc_title=str(meta.get("title") or path.stem),
                valid_from=valid_from,
                source_type=source_type,
            )
        )

    if missing_date and not allow_missing_date:
        raise KbBuildError(
            ErrorCode.KB_MISSING_DATE,
            f"valid_from belum diisi di {SOURCES_FILE} untuk: {', '.join(missing_date)}",
        )
    return documents
