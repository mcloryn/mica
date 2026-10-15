"""Pembuat file contoh kecil untuk tes M-02 (TXT, MD, PDF, DOCX)."""

from pathlib import Path

import docx
from pypdf import PdfWriter

TXT = "Universitas Mikroskil membuka pendaftaran mahasiswa baru.\n\nPendaftaran dibuka setiap hari kerja."

MD = """Pengantar sebelum heading.

# Biaya

Biaya pendaftaran Rp300.000.

| Prodi | Biaya per semester |
| --- | --- |
| Informatika | Rp7.000.000 |
| Sistem Informasi | Rp6.500.000 |

## Beasiswa

Beasiswa prestasi tersedia untuk nilai rapor minimal 85.
"""


def write_text_pdf(path: Path, lines: list[str]) -> None:
    """PDF satu halaman berteks, ditulis manual supaya tidak butuh library tambahan."""
    ops = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({escaped}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def write_blank_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as f:
        writer.write(f)


def write_docx(path: Path) -> None:
    document = docx.Document()
    document.add_paragraph("Paragraf pembuka.")
    document.add_heading("Jalur Masuk", level=1)
    document.add_paragraph("Jalur undangan untuk siswa berprestasi.")
    table = document.add_table(rows=3, cols=2)
    for r, row in enumerate([("Jalur", "Syarat"), ("Undangan", "Rapor"), ("Reguler", "Tes")]):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    document.add_heading("Fasilitas", level=2)
    document.add_paragraph("Laboratorium komputer tersedia.")
    document.save(str(path))


SOURCES_YAML = """\
brosur.txt: {title: "Brosur PMB", valid_from: 2026-08-01}
biaya.md: {title: "Rincian Biaya", valid_from: 2026-08-01}
panduan.pdf: {title: "Panduan Pendaftaran", valid_from: "2026-07-15"}
jalur.docx: {title: "Jalur Masuk", valid_from: 2026-09-01}
"""


def make_kb_folder(folder: Path, sources_yaml: str = SOURCES_YAML) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "brosur.txt").write_text(TXT, encoding="utf-8")
    (folder / "biaya.md").write_text(MD, encoding="utf-8")
    write_text_pdf(folder / "panduan.pdf", ["Panduan pendaftaran online.", "Unggah rapor (PDF)."])
    write_docx(folder / "jalur.docx")
    (folder / "sources.yaml").write_text(sources_yaml, encoding="utf-8")
    return folder


class FakeEmbedder:
    """Embedder deterministik untuk tes: vektor dari hash teks, dinormalisasi; token = kata."""

    model_id = "fake/embedder"
    revision = "0" * 40
    weights_file = "fake.safetensors"

    def __init__(self, dim: int = 8, fail_on_call: bool = False) -> None:
        self.dim = dim
        self.fail_on_call = fail_on_call
        self.calls = 0

    def embed(self, texts: list[str]):
        import hashlib

        import numpy as np

        self.calls += 1
        if self.fail_on_call:
            raise RuntimeError("embedder gagal (disengaja)")
        rows = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "little")
            rows.append(np.random.default_rng(seed).standard_normal(self.dim))
        matrix = np.asarray(rows, dtype=np.float32)
        return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)

    def count_tokens(self, text: str) -> int:
        return len(text.split())
