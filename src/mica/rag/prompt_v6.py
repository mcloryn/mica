"""Prompt v6 (V2-3 P2, docs/PRA-REGISTRASI-V2.md bagian 2; teks lengkap di docs/PROMPT-V6.md).

v6 = v5 dengan tiga perubahan:
(a) larangan klaim "biasanya/umumnya/pada umumnya" dan pengetahuan di luar potongan;
(b) pertanyaan yang hanya terjawab sebagian dijawab bagian yang ada, ditambah satu kalimat
    tentang bagian yang tidak ditemukan; not_found hanya bila tidak ada bagian yang terjawab;
(c) setiap kalimat klaim harus didukung potongan yang dikutip di citations (skema keluaran tetap
    SDD 5.3: citations per jawaban, jadi aturan ini berlaku lewat instruksi, bukan field baru).
Kepala potongan, aturan konflik sumber, dan skema keluaran sama dengan v5. Teks v5 tidak berubah.

v6r (V2-4, satu-satunya revisi v6 yang diizinkan pra-reg bagian 3; docs/PROMPT-V6.md "Revisi 1")
= v6 dengan tiga teks diganti, sasaran kelompok G1 dan G4 di docs/V2-ANALISIS-TOLAK-V6.md:
aturan "jawab hanya hal yang ditanyakan" dibatasi ke kasus tanpa satu pun bagian yang terjawab,
aturan jawaban sebagian dijadikan wajib dengan pola yang lebih jelas, dan ID potongan dilarang
ditulis di teks answer. Larangan klaim umum (a) dan aturan sitasi (c) tidak dilonggarkan.
"""

from __future__ import annotations

from collections.abc import Sequence

PROMPT_VERSION_V6 = "v6"
PROMPT_VERSION_V6R = "v6r"

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

# --- v6r (V2-4) ---------------------------------------------------------------------------------
# G1: pengganti aturan v5 "Jawab hanya hal yang ditanyakan ..." (posisi 5)
ONLY_ASKED_V6R = (
    "Jawab hanya hal yang ditanyakan. Bila potongan sama sekali tidak memuat hal yang ditanyakan "
    "dan hanya memuat informasi yang mirip (misalnya pertanyaan tentang biaya barang atau layanan "
    "lain, atau tentang kampus lain, sedangkan potongan hanya memuat biaya kuliah Universitas "
    "Mikroskil), isi status not_found. Jangan mengganti pertanyaan pengguna dengan pertanyaan lain "
    "yang bisa dijawab. Aturan ini tidak berlaku bila potongan memuat sebagian dari hal yang "
    "ditanyakan; untuk itu pakai aturan jawaban sebagian."
)
# G1: pengganti PARTIAL_V6 (posisi 6)
PARTIAL_V6R = (
    "Jawaban sebagian wajib dipakai bila potongan memuat informasi tentang hal yang ditanyakan "
    "tetapi tidak memuat semua rincian yang diminta, misalnya pertanyaan meminta angka untuk "
    "periode tertentu, nama, daftar, waktu, atau penilaian yang tidak tertulis, sedangkan potongan "
    "memuat ketentuan, angka, atau keterangan lain tentang hal yang sama. Dalam hal itu isi status "
    '"answered", tulis dulu apa yang ada di potongan tentang hal yang ditanyakan, lalu tambahkan '
    "satu kalimat yang menyebut rincian mana yang tidak ditemukan di dokumen resmi. Jangan "
    "menghitung, memperkirakan, atau menyimpulkan rincian yang tidak tertulis. Pakai not_found "
    "hanya bila tidak ada satu pun bagian pertanyaan yang dijawab potongan."
)
# G4: CLAIM_CITED_V6 + larangan menulis ID potongan di teks answer (posisi 10)
CLAIM_CITED_V6R = (
    CLAIM_CITED_V6 + " Tulis ID potongan hanya di field citations, jangan di dalam teks answer."
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
    revised: bool = False,
) -> Sequence[str]:
    """Urutan aturan v6 (revised=True: v6r); aturan bersama v5 dioper dari mica.rag.prompts."""
    return (
        role,
        ONLY_SOURCES_V6,
        header,
        conflict,
        ONLY_ASKED_V6R if revised else only_asked,
        PARTIAL_V6R if revised else PARTIAL_V6,
        false_premise,
        exact,
        NO_GENERAL_V6,
        CLAIM_CITED_V6R if revised else CLAIM_CITED_V6,
        injection,
        no_arithmetic,
        spoken,
        citations,
        data_not_instructions,
    )
