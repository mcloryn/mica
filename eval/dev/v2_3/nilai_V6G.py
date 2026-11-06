"""Penilaian Claude (bukan resmi) untuk jawaban V6G yang tidak ditolak dan berbeda dari V6
(teks atau status), aturan sama dengan V2-2 (eval/dev/v2_baseline/nilai_manual.py). Jawaban V6G
yang identik dengan V6 memakai label V6 lewat scripts/v2_3_report.py. Penolakan V6G
(v2d-041, v2d-047, v2d-088: refused_check) dinilai otomatis.
Format: qid -> (nilai, klaim_halusinasi, golongan, catatan)
"""

NILAI = {
    "v2d-014": (
        "tidak_lengkap",
        "",
        "",
        "verifikator membuang 'berpeluang' dan 'piagam juara provinsi'; PMDK tetap tidak disebut",
    ),
    "v2d-029": (
        "benar",
        "",
        "",
        "kalimat Blibli dibuang verifikator (Blibli bukan bank); kanal VA BCA lengkap",
    ),
    "v2d-040": (
        "tidak_lengkap",
        "",
        "",
        "klaim halu 'Reguler biasanya tes' dibuang; Reguler tanpa tes dan USM S2 tidak disebut",
    ),
    "v2d-042": ("benar", "", "", "hanya baris sitasi yang dibuang; isi sama dengan V6"),
    "v2d-046": (
        "benar",
        "",
        "",
        (
            "V6 refused_check (ID sitasi terbaca angka); baris sitasi dibuang verifikator; "
            "semua klaim ada di KB (P13/P14/P20); USM tidak disebut"
        ),
    ),
    "v2d-054": ("benar", "", "", "beda hanya spasi U+202F; isi sama dengan V6"),
    "v2d-059": (
        "tolak_keliru",
        "",
        "",
        (
            "kalimat tracer study dibuang; sisa hanya 'dokumen tidak menyebutkan data khusus "
            "Akuntansi' = penolakan (seperti v2d-068); penyebab sebenarnya verifikator (P3)"
        ),
    ),
    "v2d-084": (
        "tidak_lengkap",
        "",
        "",
        "kalimat Keluarga Mahasiswa Keagamaan dibuang; sisa (kerukunan beragama) tidak menjawab",
    ),
}
