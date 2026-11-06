# V2-2: Baseline sistem v5 di set dev v2 (sebelum perbaikan)

Penilaian oleh Claude di set dev (akan diungkap di Bab 3), **bukan penilaian resmi**. Patokan kebenaran = KB `official-2026-10-24-v5`. Kunci di-commit sebelum sistem dijalankan (commit `v2-2a`). Tidak ada perubahan `src/` atau `config/`; set uji Tahap 1 tidak dibaca.

## 1. Konfigurasi

- KB `official-2026-10-24-v5`, config_hash `073e446b9879` (`config/prod.yaml`), top_k 5, gerbang dense@1 >= 0.5, prompt `v5`, rantai groq:openai/gpt-oss-120b, groq:openai/gpt-oss-20b, followup_mode `dual`.
- Jeda 20 detik per panggilan. **Koreksi (7 Nov 2026):** versi awal laporan ini menulis "tidak ada HTTP 429 ... semua jawaban dari gpt-oss-120b"; itu salah. gpt-oss-120b membalas HTTP 429 (batas token harian) mulai sekitar v2d-067 (`run_stdout.txt`), dan rantai pindah ke cadangan tanpa run berhenti. Penjawab: lama tanpa LLM (gerbang 1) 4, lama groq:openai/gpt-oss-120b 2, lama groq:openai/gpt-oss-20b 32, v2 tanpa LLM (gerbang 1) 9, v2 groq:openai/gpt-oss-120b 64, v2 groq:openai/gpt-oss-20b 35. Analisis utama V2-3/V2-4 karena itu memakai subset S (`docs/V2-HASIL-DEV.md`).
- Set v2: 108 soal (`data/eval/dev-v2-soal.csv`, kunci `data/eval/dev_v2_kunci.csv`). Set lama: 38 soal `data/eval/questions.jsonl` yang bukan luar_topik (kunci `data/eval/dev_lama_kunci_v5.csv`); followup d032/d033 memakai riwayat d001/d011.

## 2. Aturan penilaian

- Menolak (refused_gate/refused_llm/refused_check): KB memuat jawaban (jenis ada/sebagian, atau premis_salah yang bisa dikoreksi KB) -> tolak keliru; selain itu -> tolak tepat.
- Penyebab tolak keliru: gerbang 1 (dense@1 < 0,50) / gold tidak masuk top-5 / gold di top-5 tapi LLM not_found / gerbang 3 (cek angka).
- Menjawab (answered/false_premise): setiap klaim dicek ke KB. Ada klaim di luar KB -> halusinasi (A = pengetahuan umum/penalaran tambahan, B = detail spesifik salah). Semua klaim benar tapi bagian kunci yang menjawab hilang -> tidak lengkap. Selain itu benar. Kalimat sopan/arahan ke staf bukan klaim.
- v2d-068 berstatus false_premise tetapi isinya hanya menyatakan info tidak ada; dinilai sebagai penolakan (tolak tepat).
- Recall dihitung untuk soal jenis ada/sebagian dengan chunk gold; top-5 = chunk yang benar-benar dikirim pipeline, @20 dari peringkat retrieval (kolam 50).

## 3. Rekap set v2

- Soal: 108; dijawab 48, ditolak 60.
- Tidak halu = (benar 28 + tidak lengkap 9) / dijawab 48 = 37/48 = **77.1%** (Wilson 95% 63.5-86.7%).
- Halusinasi: 11 (A 4, B 7).
- Tolak tepat: 34. Tolak keliru: 26 (gerbang 1 1, gold tidak top-5 12, gold di top-5 tapi not_found 10, gerbang 3 3).
- Recall chunk gold (soal ada/sebagian, n=68): @5 52/68 = 0.76; @20 64/68 = 0.94.

## 4. Rekap set lama (label v5)

- Soal: 38; dijawab 18, ditolak 20.
- Tidak halu = (benar 11 + tidak lengkap 4) / dijawab 18 = 15/18 = **83.3%** (Wilson 95% 60.8-94.2%).
- Halusinasi: 3 (A 0, B 3).
- Tolak tepat: 14. Tolak keliru: 6 (gerbang 1 2, gold tidak top-5 4, gold di top-5 tapi not_found 0, gerbang 3 0).
- Recall chunk gold (soal ada/sebagian, n=22): @5 17/22 = 0.77; @20 22/22 = 1.00.

## 5. Per soal

| set | qid | jenis | status | dense@1 | rank gold | gold@5 | nilai | gol. | penyebab | catatan |
|---|---|---|---|---|---|---|---|---|---|---|
| v2 | v2d-001 | ada | answered | 0.734 | 1 | ya | benar | - | - | - |
| v2 | v2d-002 | sebagian | refused_llm | 0.736 | 1 | ya | tolak_keliru | - | llm_not_found | - |
| v2 | v2d-003 | ada | refused_llm | 0.604 | 7 | - | tolak_keliru | - | gold_tidak_top5 | - |
| v2 | v2d-004 | sebagian | refused_llm | 0.700 | 1 | ya | tolak_keliru | - | llm_not_found | - |
| v2 | v2d-005 | sebagian | refused_llm | 0.689 | 1 | ya | tolak_keliru | - | llm_not_found | - |
| v2 | v2d-006 | sebagian | refused_llm | 0.585 | 10 | - | tolak_keliru | - | gold_tidak_top5 | - |
| v2 | v2d-007 | tidak_ada | refused_llm | 0.563 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-008 | tidak_ada | refused_llm | 0.506 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-009 | ada | answered | 0.580 | 1 | ya | benar | - | - | - |
| v2 | v2d-010 | ada | answered | 0.601 | 4 | ya | tidak_lengkap | - | - | tidak menyebut Jalur Prestasi (nilai rapor) dan ketentuan Rektor |
| v2 | v2d-011 | tidak_ada | refused_llm | 0.619 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-012 | ada | answered | 0.631 | 1 | ya | benar | - | - | - |
| v2 | v2d-013 | ada | answered | 0.658 | 3 | ya | tidak_lengkap | - | - | Beasiswa Karier dan PMDK tidak disebut |
| v2 | v2d-014 | ada | answered | 0.562 | 4 | ya | halusinasi | B | - | klaim: "mengajukan permohonan melalui Wakil Rektor III dengan melampirkan bukti prestasi". ragu: KB hanya menyebut Surat Keterangan WR III (Beasiswa Karier), bukan prosedur pengajuan pendaftar |
| v2 | v2d-015 | ada | answered | 0.669 | 2 | ya | benar | - | - | - |
| v2 | v2d-016 | tidak_ada | answered | 0.632 | - | - | halusinasi | B | - | klaim: "Beasiswa Yayasan terbuka bagi siswa dari seluruh Sumatera Utara maupun nasional". kunci tidak_ada; KB: prestasi yang mengharumkan nama Sumut/nasional, bukan asal daerah |
| v2 | v2d-017 | sebagian | refused_llm | 0.579 | 1 | ya | tolak_keliru | - | llm_not_found | - |
| v2 | v2d-018 | tidak_ada | refused_llm | 0.569 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-019 | sebagian | refused_llm | 0.552 | 6 | - | tolak_keliru | - | gold_tidak_top5 | - |
| v2 | v2d-020 | tidak_ada | refused_gate | 0.415 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-021 | tidak_ada | answered | 0.514 | - | - | halusinasi | A | - | klaim: "mendaftar lebih awal mengamankan tempat dan menghindari keterlambatan pembayaran". kunci tidak_ada; aturan registrasi dibingkai sebagai keuntungan |
| v2 | v2d-022 | tidak_ada | refused_llm | 0.516 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-023 | tidak_ada | refused_llm | 0.520 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-024 | sebagian | refused_llm | 0.545 | 22 | - | tolak_keliru | - | gold_tidak_top5 | - |
| v2 | v2d-025 | tidak_ada | refused_llm | 0.584 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-026 | tidak_ada | refused_llm | 0.572 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-027 | tidak_ada | refused_llm | 0.602 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-028 | ada | answered | 0.661 | 3 | ya | tidak_lengkap | - | - | hanya skema sore; skema pagi 12x tidak disebut |
| v2 | v2d-029 | ada | answered | 0.579 | 1 | ya | benar | - | - | - |
| v2 | v2d-030 | sebagian | answered | 0.614 | 2 | ya | benar | - | - | - |
| v2 | v2d-031 | ada | answered | 0.632 | 6 | - | halusinasi | B | - | klaim: "pembayaran dapat dilakukan secara daring melalui portal akademik Mika". Mika untuk invoice/status, pembayaran lewat Blibli/VA BCA |
| v2 | v2d-032 | sebagian | answered | 0.707 | 1 | ya | benar | - | - | 6x/semester (pagi) dan 2x/semester (sore) diturunkan dari jadwal KB |
| v2 | v2d-033 | tidak_ada | refused_llm | 0.560 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-034 | sebagian | refused_llm | 0.647 | 1 | ya | tolak_keliru | - | llm_not_found | - |
| v2 | v2d-035 | ada | answered | 0.708 | 1 | ya | benar | - | - | 'pada umumnya' melunakkan isi yang ada di KB, bukan klaim baru |
| v2 | v2d-036 | tidak_ada | refused_llm | 0.626 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-037 | ada | answered | 0.632 | 1 | ya | benar | - | - | - |
| v2 | v2d-038 | tidak_ada | refused_gate | 0.499 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-039 | ada | answered | 0.587 | 3 | ya | benar | - | - | - |
| v2 | v2d-040 | ada | answered | 0.646 | 1 | ya | tidak_lengkap | - | - | jalur Prestasi/Reguler tanpa tes dan USM S2 tidak disebut |
| v2 | v2d-041 | ada | answered | 0.523 | 2 | ya | benar | - | - | - |
| v2 | v2d-042 | sebagian | answered | 0.559 | 1 | ya | benar | - | - | akta/KK tercantum sebagai dokumen pemberkasan di KB |
| v2 | v2d-043 | ada | false_premise | 0.596 | 2 | ya | halusinasi | B | - | klaim: "lulusan 2019 tidak dapat mendaftar". Jalur Reguler tanpa batas tahun lulus; batas 1 tahun hanya PMDK/Prestasi (status false_premise) |
| v2 | v2d-044 | ada | refused_check | 0.594 | 1 | ya | tolak_keliru | - | gerbang_3 | unsupported=['1'] |
| v2 | v2d-045 | ada | answered | 0.608 | 1 | ya | benar | - | - | - |
| v2 | v2d-046 | ada | refused_check | 0.595 | 2 | ya | tolak_keliru | - | gerbang_3 | unsupported=['13', '14'] |
| v2 | v2d-047 | ada | answered | 0.589 | 1 | ya | halusinasi | B | - | klaim: "untuk mendaftar harus menyerahkan ijazah dilegalisir". ragu: KB menaruh ijazah dilegalisir di pemberkasan setelah diterima (S1) |
| v2 | v2d-048 | ada | answered | 0.529 | 1 | ya | halusinasi | B | - | klaim: "mahasiswa baru harus sudah menempuh minimal dua semester dengan IPK 3,00". dua aturan (P22 dan A20) digabung keliru |
| v2 | v2d-049 | ada | answered | 0.693 | 1 | ya | benar | - | - | - |
| v2 | v2d-050 | ada | answered | 0.600 | 3 | ya | benar | - | - | - |
| v2 | v2d-051 | ada | answered | 0.656 | 2 | ya | tidak_lengkap | - | - | syarat persetujuan orang tua/dosen wali/kaprodi/dekan tidak disebut |
| v2 | v2d-052 | ada | answered | 0.680 | 1 | ya | benar | - | - | - |
| v2 | v2d-053 | sebagian | refused_llm | 0.546 | 16 | - | tolak_keliru | - | gold_tidak_top5 | - |
| v2 | v2d-054 | ada | answered | 0.662 | 1 | ya | benar | - | - | - |
| v2 | v2d-055 | tidak_ada | refused_llm | 0.621 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-056 | ada | answered | 0.521 | 3 | ya | benar | - | - | - |
| v2 | v2d-057 | sebagian | refused_llm | 0.559 | 7 | - | tolak_keliru | - | gold_tidak_top5 | - |
| v2 | v2d-058 | ada | answered | 0.589 | 3 | ya | benar | - | - | - |
| v2 | v2d-059 | ada | answered | 0.620 | 1 | ya | tidak_lengkap | - | - | career path Akuntansi (brosur#10) tidak disebut |
| v2 | v2d-060 | ada | refused_llm | 0.667 | 6 | - | tolak_keliru | - | gold_tidak_top5 | - |
| v2 | v2d-061 | sebagian | refused_llm | 0.537 | 1 | ya | tolak_keliru | - | llm_not_found | - |
| v2 | v2d-062 | ada | refused_llm | 0.643 | 6 | - | tolak_keliru | - | gold_tidak_top5 | - |
| v2 | v2d-063 | tidak_ada | refused_llm | 0.568 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-064 | sebagian | refused_llm | 0.632 | 19 | - | tolak_keliru | - | gold_tidak_top5 | - |
| v2 | v2d-065 | sebagian | refused_llm | 0.559 | 1 | ya | tolak_keliru | - | llm_not_found | - |
| v2 | v2d-066 | ada | answered | 0.610 | 3 | ya | tidak_lengkap | - | - | menyatakan jumlah semester tidak tercantum padahal A24 memuat 4 semester |
| v2 | v2d-067 | tidak_ada | refused_check | 0.577 | - | - | tolak_tepat | - | - | unsupported=['7'] |
| v2 | v2d-068 | tidak_ada | false_premise | 0.590 | - | - | tolak_tepat | - | - | status false_premise, isinya menyatakan tidak disebut di brosur; dinilai sebagai penolakan |
| v2 | v2d-069 | ada | answered | 0.687 | 1 | ya | benar | - | - | - |
| v2 | v2d-070 | tidak_ada | refused_llm | 0.524 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-071 | sebagian | refused_llm | 0.586 | 1 | ya | tolak_keliru | - | llm_not_found | - |
| v2 | v2d-072 | ada | answered | 0.620 | 5 | ya | benar | - | - | - |
| v2 | v2d-073 | tidak_ada | refused_llm | 0.688 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-074 | tidak_ada | refused_llm | 0.515 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-075 | tidak_ada | refused_llm | 0.523 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-076 | tidak_ada | refused_llm | 0.544 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-077 | tidak_ada | refused_gate | 0.494 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-078 | tidak_ada | refused_llm | 0.547 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-079 | tidak_ada | answered | 0.586 | - | - | halusinasi | A | - | klaim: "Universitas Mikroskil menyediakan fasilitas olahraga". kunci tidak_ada; KB hanya UKM olahraga |
| v2 | v2d-080 | ada | answered | 0.602 | 1 | ya | benar | - | - | - |
| v2 | v2d-081 | ada | answered | 0.666 | 1 | ya | benar | - | - | - |
| v2 | v2d-082 | tidak_ada | refused_llm | 0.508 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-083 | ada | answered | 0.588 | 1 | ya | tidak_lengkap | - | - | 'seragam tidak bebas' menyesatkan (tidak ada seragam); Jas Akademis tidak disebut |
| v2 | v2d-084 | ada | refused_llm | 0.605 | 11 | - | tolak_keliru | - | gold_tidak_top5 | - |
| v2 | v2d-085 | sebagian | refused_llm | 0.516 | 32 | - | tolak_keliru | - | gold_tidak_top5 | - |
| v2 | v2d-086 | sebagian | refused_llm | 0.633 | 1 | ya | tolak_keliru | - | llm_not_found | - |
| v2 | v2d-087 | ada | refused_check | 0.637 | 2 | ya | tolak_keliru | - | gerbang_3 | unsupported=['3.000'] |
| v2 | v2d-088 | ada | answered | 0.607 | 5 | ya | benar | - | - | - |
| v2 | v2d-089 | sebagian | answered | 0.578 | 15 | - | tidak_lengkap | - | - | ragu: surat aktif kuliah (Layanan Fakultas) tidak disebut; A78 'keperluan tertentu' |
| v2 | v2d-090 | tidak_ada | refused_llm | 0.590 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-091 | ada | refused_llm | 0.534 | 29 | - | tolak_keliru | - | gold_tidak_top5 | - |
| v2 | v2d-092 | ada | refused_gate | 0.462 | 38 | - | tolak_keliru | - | gerbang_1 | - |
| v2 | v2d-093 | ada | answered | 0.672 | 9 | - | benar | - | - | - |
| v2 | v2d-094 | sebagian | answered | 0.617 | 1 | ya | halusinasi | A | - | klaim: "perguruan tinggi mitra bisa berada di luar negeri". |
| v2 | v2d-095 | ada | answered | 0.653 | 1 | ya | benar | - | - | - |
| v2 | v2d-096 | sebagian | answered | 0.559 | 1 | ya | halusinasi | A | - | klaim: "mahasiswa biasanya mengerjakan ujian di komputer". klaim 'biasanya' di luar KB |
| v2 | v2d-097 | ada | answered | 0.687 | 1 | ya | benar | - | - | - |
| v2 | v2d-098 | tidak_ada | refused_llm | 0.511 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-099 | luar_topik | refused_gate | 0.477 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-100 | luar_topik | refused_llm | 0.561 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-101 | luar_topik | refused_gate | 0.427 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-102 | luar_topik | refused_gate | 0.398 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-103 | luar_topik | refused_gate | 0.436 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-104 | tidak_ada | refused_gate | 0.486 | - | - | tolak_tepat | - | - | - |
| v2 | v2d-105 | premis_salah | refused_llm | 0.529 | 6 | - | tolak_tepat | - | - | - |
| v2 | v2d-106 | premis_salah | false_premise | 0.517 | 3 | ya | benar | - | - | premis dikoreksi |
| v2 | v2d-107 | premis_salah | false_premise | 0.544 | - | - | halusinasi | B | - | klaim: "kelas sore dapat diikuti mahasiswa baru yang belum punya pengalaman kerja". ragu: kunci koreksi tidak_ada; P19 menyebut mahasiswa baru kelas sore tetapi bukan syarat kerja |
| v2 | v2d-108 | premis_salah | refused_llm | 0.657 | 5 | ya | tolak_keliru | - | llm_not_found | - |
| lama | d001 | ada | answered | 0.723 | 1 | ya | benar | - | - | - |
| lama | d002 | ada | answered | 0.646 | 1 | ya | benar | - | - | - |
| lama | d003 | tidak_ada | refused_llm | 0.558 | - | - | tolak_tepat | - | - | - |
| lama | d004 | ada | refused_gate | 0.478 | 1 | ya | tolak_keliru | - | gerbang_1 | - |
| lama | d005 | ada | refused_llm | 0.560 | 11 | - | tolak_keliru | - | gold_tidak_top5 | - |
| lama | d006 | ada | refused_gate | 0.494 | 19 | - | tolak_keliru | - | gerbang_1 | - |
| lama | d007 | tidak_ada | refused_gate | 0.486 | - | - | tolak_tepat | - | - | - |
| lama | d008 | ada | answered | 0.583 | 1 | ya | benar | - | - | - |
| lama | d009 | ada | answered | 0.612 | 1 | ya | tidak_lengkap | - | - | S2 Magister Manajemen tidak disebut |
| lama | d010 | tidak_ada | refused_llm | 0.643 | - | - | tolak_tepat | - | - | - |
| lama | d011 | ada | answered | 0.666 | 1 | ya | tidak_lengkap | - | - | Ujian Saring Masuk tidak disebut |
| lama | d012 | ada | answered | 0.638 | 1 | ya | benar | - | - | - |
| lama | d013 | tidak_ada | refused_llm | 0.539 | - | - | tolak_tepat | - | - | - |
| lama | d014 | ada | answered | 0.625 | 1 | ya | tidak_lengkap | - | - | KIP Kuliah tidak disebut |
| lama | d015 | sebagian | answered | 0.613 | 1 | ya | halusinasi | B | - | klaim: "Universitas Mikroskil didirikan pada tahun 1997". 1997 = STMIK; universitas 2021 |
| lama | d016 | ada | answered | 0.564 | 2 | ya | benar | - | - | - |
| lama | d017 | ada | answered | 0.550 | 1 | ya | benar | - | - | - |
| lama | d018 | ada | answered | 0.607 | 1 | ya | benar | - | - | - |
| lama | d019 | tidak_ada | refused_gate | 0.460 | - | - | tolak_tepat | - | - | - |
| lama | d020 | sebagian | answered | 0.574 | 4 | ya | halusinasi | B | - | klaim: "peminatan prodi Manajemen = Entrepreneurship & Business Development, dst.". itu expertise Magister Manajemen (brosur#8) |
| lama | d021 | ada | refused_llm | 0.581 | 11 | - | tolak_keliru | - | gold_tidak_top5 | - |
| lama | d022 | ada | answered | 0.538 | 3 | ya | benar | - | - | - |
| lama | d023 | tidak_ada | refused_llm | 0.503 | - | - | tolak_tepat | - | - | - |
| lama | d024 | tidak_ada | refused_llm | 0.504 | - | - | tolak_tepat | - | - | - |
| lama | d025 | ada | answered | 0.696 | 3 | ya | benar | - | - | 'mahasiswa sarjana' seharusnya kelas pagi; isi cicilan benar |
| lama | d026 | tidak_ada | answered | 0.693 | 8 | - | halusinasi | B | - | klaim: "uang pangkal Teknik Informatika = Rp14.000.000". biaya kuliah per tahun disebut uang pangkal |
| lama | d027 | tidak_ada | refused_llm | 0.620 | 1 | ya | tolak_tepat | - | - | - |
| lama | d028 | tidak_ada | refused_llm | 0.557 | 1 | ya | tolak_tepat | - | - | - |
| lama | d029 | premis_salah | refused_llm | 0.607 | 11 | - | tolak_keliru | - | gold_tidak_top5 | - |
| lama | d030 | premis_salah | refused_llm | 0.590 | - | - | tolak_tepat | - | - | - |
| lama | d031 | premis_salah | refused_llm | 0.528 | - | - | tolak_tepat | - | - | - |
| lama | d032 | ada | answered | 0.731 | 17 | - | tidak_lengkap | - | - | menjawab jadwal cicilan sore, bukan biaya kelas sore SI |
| lama | d033 | ada | answered | 0.736 | 1 | ya | benar | - | - | - |
| lama | d041 | tidak_ada | refused_llm | 0.666 | - | - | tolak_tepat | - | - | - |
| lama | d042 | ada | answered | 0.687 | 1 | ya | benar | - | - | - |
| lama | d043 | tidak_ada | refused_llm | 0.590 | 8 | - | tolak_tepat | - | - | - |
| lama | d044 | ada | refused_llm | 0.584 | 11 | - | tolak_keliru | - | gold_tidak_top5 | - |
| lama | d045 | tidak_ada | refused_llm | 0.524 | - | - | tolak_tepat | - | - | - |

## 6. Berkas

- `eval/dev/v2_baseline/runs.jsonl`: per soal (jawaban, status, gerbang, top-5 + skor RRF + peringkat, dense@1, top-20, sitasi, fact_check).
- `eval/dev/v2_baseline/penilaian.csv`: nilai per soal; `nilai_manual.py`: penilaian klaim untuk jawaban yang tidak ditolak.
- `eval/dev/v2_baseline/summary.json`, `meta.json`, `logs/` (turn log M-11), `run_stdout.txt`.
- Skrip: `scripts/v2_baseline_dev.py` (run, bisa dilanjutkan), `scripts/v2_baseline_report.py` (penilaian dan laporan).
