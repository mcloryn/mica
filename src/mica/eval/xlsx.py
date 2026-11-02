"""Penulis .xlsx minimal (Office Open XML) dengan pustaka standar saja (Langkah 67).

Dipakai untuk lembar penilaian Uji Tahap 1. Tidak ada library spreadsheet di daftar SDD, jadi
file ditulis langsung: teks inline, satu gaya "wrap", baris judul dibekukan, lebar kolom, dan
dropdown (data validation daftar). Tanggal di zip ditetapkan supaya isi yang sama menghasilkan
byte yang sama (dua lembar penilai identik).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

ZIP_DATE = (1980, 1, 1, 0, 0, 0)
MAX_CELL_CHARS = 32767  # batas Excel per sel
# karakter kontrol yang tidak sah di XML 1.0 (tab, LF, CR tetap boleh)
_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass
class Sheet:
    name: str
    rows: list[list[str]]
    widths: list[float] = field(default_factory=list)  # lebar kolom (satuan karakter Excel)
    # (kolom huruf, daftar pilihan): dropdown untuk baris 2..akhir
    dropdowns: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    freeze_header: bool = True


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _cell_text(value: str) -> str:
    text = _ILLEGAL.sub("", str(value))
    if len(text) > MAX_CELL_CHARS:
        raise ValueError(f"isi sel lebih dari {MAX_CELL_CHARS} karakter")
    return escape(text)


_SHEET_HEAD = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
)


def _sheet_xml(sheet: Sheet) -> str:
    parts = [_SHEET_HEAD]
    if sheet.freeze_header:
        parts.append(
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
            'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        )
    if sheet.widths:
        cols = "".join(
            f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(sheet.widths, start=1)
        )
        parts.append(f"<cols>{cols}</cols>")
    parts.append("<sheetData>")
    for r, row in enumerate(sheet.rows, start=1):
        style = ' s="1"' if r == 1 else ' s="2"'
        cells = "".join(
            f'<c r="{column_letter(c)}{r}" t="inlineStr"{style}>'
            f'<is><t xml:space="preserve">{_cell_text(v)}</t></is></c>'
            for c, v in enumerate(row)
        )
        parts.append(f'<row r="{r}">{cells}</row>')
    parts.append("</sheetData>")
    if sheet.dropdowns and len(sheet.rows) > 1:
        last = len(sheet.rows)
        items = []
        for col, choices in sheet.dropdowns:
            formula = escape('"' + ",".join(choices) + '"')
            items.append(
                f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" '
                f'sqref="{col}2:{col}{last}"><formula1>{formula}</formula1></dataValidation>'
            )
        parts.append(f'<dataValidations count="{len(items)}">{"".join(items)}</dataValidations>')
    parts.append("</worksheet>")
    return "".join(parts)


_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" '
    'applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
    '<alignment vertical="top" wrapText="1"/></xf></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def write_xlsx(path: Path, sheets: list[Sheet]) -> None:
    names = [s.name for s in sheets]
    if len(set(names)) != len(names) or any(len(n) > 31 for n in names):
        raise ValueError("nama sheet harus unik dan paling panjang 31 karakter")
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{overrides}</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<sheets>"
            + "".join(
                f'<sheet name="{escape(s.name)}" sheetId="{i}" r:id="rId{i}"/>'
                for i, s in enumerate(sheets, start=1)
            )
            + "</sheets></workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/'
                f'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                for i in range(1, len(sheets) + 1)
            )
            + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
        ),
        "xl/styles.xml": _STYLES,
    }
    for i, sheet in enumerate(sheets, start=1):
        files[f"xl/worksheets/sheet{i}.xml"] = _sheet_xml(sheet)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, content.encode("utf-8"))
