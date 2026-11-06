"""Penilaian Claude (bukan resmi) untuk jawaban V6G yang tidak ditolak dan berbeda dari V6
(teks atau status), aturan sama dengan V2-2 (eval/dev/v2_baseline/nilai_manual.py). Jawaban V6G
yang identik dengan V6 memakai label V6 lewat scripts/v2_3_report.py. Penolakan V6G
(v2d-041, v2d-047, v2d-088: refused_check) dinilai otomatis.
Format: qid -> (nilai, klaim_halusinasi, golongan, catatan)
PENYEBAB: penyebab tolak keliru yang menimpa penyebab otomatis (scripts/v2_3_report.py).
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
        "tidak_lengkap",
        "",
        "",
        (
            "koreksi V2-4: Ujian Saring Masuk S2 ada di KB v5 (pedoman-pmb-2027#7 butir e, di top-5) "
            "tetapi tidak disebut; klaim lain benar (P13/P14/P20)"
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

# koreksi V2-4: v2d-059 berstatus answered tetapi isinya tinggal penolakan karena verifikator (P3)
# membuang kalimat jawabannya; penyebab otomatis llm_not_found diganti gerbang_3 (verifikator)
PENYEBAB = {"v2d-059": "gerbang_3"}
