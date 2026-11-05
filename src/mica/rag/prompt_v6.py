"""Prompt v6 (V2-3 P2, docs/PRA-REGISTRASI-V2.md bagian 2; teks lengkap di docs/PROMPT-V6.md).

v6 = v5 dengan tiga perubahan:
(a) larangan klaim "biasanya/umumnya/pada umumnya" dan pengetahuan di luar potongan;
(b) pertanyaan yang hanya terjawab sebagian dijawab bagian yang ada, ditambah satu kalimat
    tentang bagian yang tidak ditemukan; not_found hanya bila tidak ada bagian yang terjawab;
(c) setiap kalimat klaim harus didukung potongan yang dikutip di citations (skema keluaran tetap
    SDD 5.3: citations per jawaban, jadi aturan ini berlaku lewat instruksi, bukan field baru).
Kepala potongan, aturan konflik sumber, dan skema keluaran sama dengan v5. Teks v5 tidak berubah.
"""

from __future__ import annotations

from collections.abc import Sequence

PROMPT_VERSION_V6 = "v6"

ONLY_SOURCES_V6 = (
    "Jawab hanya dari potongan dokumen berlabel ID yang diberikan. Bila potongan tidak memuat "
    'jawaban untuk bagian mana pun dari pertanyaan, isi status dengan "not_found".'
)
PARTIAL_V6 = (
    'Bila potongan hanya menjawab sebagian pertanyaan, isi status "answered", jawab bagian '
    "yang ada di potongan, lalu tambahkan satu kalimat yang menyebut bagian mana yang tidak "
    "ditemukan di dokumen resmi. Jangan memakai not_found hanya karena sebagian pertanyaan tidak "
    "terjawab."
)
NO_GENERAL_V6 = (
    "Jangan menambahkan pengetahuan umum, perkiraan, kebiasaan, atau kesimpulan yang tidak "
    'tertulis di potongan, termasuk kalimat dengan kata "biasanya", "umumnya", atau "pada '
    'umumnya".'
)
CLAIM_CITED_V6 = (
    "Setiap kalimat yang memuat informasi harus didukung langsung oleh potongan yang ID-nya kamu "
    "tulis di citations; kalimat yang tidak bisa didukung potongan jangan ditulis. Kalimat sopan "
    "atau arahan untuk bertanya ke staf PMB tidak perlu sumber."
)


def rules_v6(
    *,
    role: str,
    header: str,
    conflict: str,
    only_asked: str,
    false_premise: str,
    exact: str,
    injection: str,
    no_arithmetic: str,
    spoken: str,
    citations: str,
    data_not_instructions: str,
) -> Sequence[str]:
    """Urutan aturan v6; aturan bersama v5 dioper dari mica.rag.prompts supaya teksnya sama."""
    return (
        role,
        ONLY_SOURCES_V6,
        header,
        conflict,
        only_asked,
        PARTIAL_V6,
        false_premise,
        exact,
        NO_GENERAL_V6,
        CLAIM_CITED_V6,
        injection,
        no_arithmetic,
        spoken,
        citations,
        data_not_instructions,
    )
