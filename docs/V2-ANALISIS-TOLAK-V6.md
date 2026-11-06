# V2-3c: Analisis tolak keliru V6 dan token Groq per soal

Lokal, tanpa memanggil Groq. Sumber: `eval/dev/v2_3/V6.jsonl` (keluaran LLM mentah dan `fact_check`), penilaian V6 (`eval/dev/v2_3/nilai_V6.py` + aturan V2-2), dan B0 (`eval/dev/v2_baseline/`). Prompt **tidak** diubah di langkah ini. Penilaian oleh Claude, bukan penilaian resmi.

## 1. Ringkasan

Tolak keliru V6 = **28** (B0 26). Penyebab per definisi V2-2: gerbang_1 1, gerbang_3 6, gold_tidak_top5 7, llm_not_found 14.

| Kelompok | Pola | Jumlah | qid |
|---|---|---|---|
| G1 | Soal 'sebagian' ditolak seluruhnya (not_found, gold di top-5): aturan v6 (b) tidak diikuti | 11 | v2d-002, v2d-005, v2d-006, v2d-017, v2d-019, v2d-034, v2d-061, v2d-065, v2d-071, v2d-086, v2d-096 |
| G2 | Chunk gold tidak masuk top-5 (retrieval + reranker) | 7 | v2d-024, v2d-053, v2d-057, v2d-060, v2d-085, v2d-089, v2d-091 |
| G3 | Angka benar, cek angka (gerbang 3) gagal karena format penulisan | 3 | v2d-013, v2d-028, v2d-087 |
| G4 | Sitasi ID chunk ditulis di teks jawaban, nomor ID terbaca sebagai angka | 1 | v2d-046 |
| G5 | Premis salah dijawab not_found, bukan dikoreksi | 2 | v2d-106, v2d-108 |
| G6 | Jenis 'ada', gold di top-5, istilah pertanyaan beda dengan KB | 1 | v2d-039 |
| G7 | Gerbang 3 menahan jawaban yang memang keliru (penolakan menguntungkan) | 2 | v2d-043, v2d-056 |
| G8 | Gerbang 1 (dense@1 < 0,50) | 1 | v2d-092 |

- Tolak keliru V6 yang di B0 **dijawab**: 8 (v2d-013, v2d-028, v2d-039, v2d-043, v2d-056, v2d-089, v2d-096, v2d-106); label B0: v2d-013 tidak_lengkap, v2d-028 tidak_lengkap, v2d-039 benar, v2d-043 halusinasi, v2d-056 benar, v2d-089 tidak_lengkap, v2d-096 halusinasi, v2d-106 benar.
- Tolak keliru B0 yang di V6 tidak lagi tolak keliru: 6 (v2d-003, v2d-004, v2d-044, v2d-062, v2d-064, v2d-084); label V6: v2d-003 tidak_lengkap, v2d-004 tidak_lengkap, v2d-044 benar, v2d-062 tidak_lengkap, v2d-064 benar, v2d-084 tidak_lengkap.
- Selisih bersih: 28 - 26 = +2.

## 2. Pola

- **G1 (11)** terbesar: v6 aturan (b) meminta 'jawab bagian yang ada, sebut bagian yang tidak ditemukan', tetapi semua soal 'sebagian' dengan gold di top-5 tetap not_found. Sama dengan B0 (B0 juga menolak 10 dari 11, ditambah v2d-096 yang di B0 dijawab dengan halusinasi A). Artinya aturan (b) belum efektif; aturan v5 'Jawab hanya hal yang ditanyakan ... bila potongan hanya memuat informasi yang mirip ... not_found' kemungkinan mengalahkan (b).
- **G2 (7)**: retrieval. Reranker menaikkan recall@5 (52 -> 58/68), tetapi 7 soal ini tetap di luar top-5; 5 di antaranya 'sebagian'.
- **G3 + G4 (4)**: keterbatasan `NumericFactChecker` yang sudah tercatat di docstring-nya (angka menempel huruf '12x' diabaikan, angka kata/singkatan '3k', penomoran di tengah kalimat). G4 baru muncul di v6: model menulis ID chunk di teks jawaban (efek samping aturan (c) 'kalimat wajib bersitasi'; aturan sitasi v5 hanya untuk field citations).
- **G5 + G6 (3)**: premis salah / istilah berbeda dijawab not_found.
- **G7 (2)**: gerbang 3 menolak jawaban yang memang salah (v2d-043 kesimpulan keliru, v2d-056 nomor Keuangan disebut nomor PMB). Secara definisi tetap tolak keliru (KB punya jawabannya), tetapi penolakan ini mencegah halusinasi B.
- **G8 (1)**: gerbang 1, sama dengan B0.

## 3. Per soal

| qid | jenis kunci | gold di top-5 | penyebab (V2-2) | kelompok | alasan (log LLM / gerbang 3) | B0 |
|---|---|---|---|---|---|---|
| v2d-002 | sebagian | ya | llm_not_found | G1 | not_found; biaya per semester tidak tertulis, biaya per tahun ada di top-5 | refused_llm (tolak_keliru) |
| v2d-005 | sebagian | ya | llm_not_found | G1 | not_found; biaya per bulan tidak tertulis, biaya tahunan + skema cicilan sore ada | refused_llm (tolak_keliru) |
| v2d-006 | sebagian | ya | llm_not_found | G1 | not_found; 'naik tiap tahun' tidak tertulis, 'ditetapkan Rektor tiap tahun' ada | refused_llm (tolak_keliru) |
| v2d-013 | ada | ya | gerbang_3 | G3 | unsupported 2,3,4 = penomoran '1) 2) 3) 4)' di tengah kalimat | answered (tidak_lengkap) |
| v2d-017 | sebagian | ya | llm_not_found | G1 | not_found; penurunan IP tidak disebut, alasan penghentian beasiswa ada | refused_llm (tolak_keliru) |
| v2d-019 | sebagian | ya | llm_not_found | G1 | not_found; jadwal KIP (ikut Ditjen Dikti) dan 01-30 Mei ada | refused_llm (tolak_keliru) |
| v2d-024 | sebagian | tidak | gold_tidak_top5 | G2 | chunk gold (pmb#5) tidak di top-5 | refused_llm (tolak_keliru) |
| v2d-028 | ada | ya | gerbang_3 | G3 | unsupported 12,4: jawaban '12 kali'/'4 kali', sumber '12x'/'4x' (angka menempel huruf diabaikan) | answered (tidak_lengkap) |
| v2d-034 | sebagian | ya | llm_not_found | G1 | not_found; nominal tidak ada, komponen registrasi (Uang Kuliah + DP3) ada | refused_llm (tolak_keliru) |
| v2d-039 | ada | ya | llm_not_found | G6 | not_found; 'uang pembangunan' tidak dikenali sebagai DP3 (kunci ragu) | answered (benar) |
| v2d-043 | ada | ya | gerbang_3 | G7 | unsupported 2019 (dari pertanyaan); kesimpulan 'tidak memenuhi syarat' juga keliru (Reguler) | false_premise (halusinasi/B) |
| v2d-046 | ada | ya | gerbang_3 | G4 | unsupported 14 = sitasi '(pmb/pedoman-pmb-2027#14)' ditulis di teks jawaban | refused_check (tolak_keliru) |
| v2d-053 | sebagian | tidak | gold_tidak_top5 | G2 | chunk gold (RPL alih jenjang) tidak di top-5 | refused_llm (tolak_keliru) |
| v2d-056 | ada | tidak | gerbang_3 | G7 | unsupported 0811-7070-3992 (tanda hubung U+2011); nomor itu WA Keuangan, disebut PMB | answered (benar) |
| v2d-057 | sebagian | tidak | gold_tidak_top5 | G2 | chunk gold (brosur#14) tidak di top-5 | refused_llm (tolak_keliru) |
| v2d-060 | ada | tidak | gold_tidak_top5 | G2 | chunk gold (pmb#14 daftar prodi) tidak di top-5 | refused_llm (tolak_keliru) |
| v2d-061 | sebagian | ya | llm_not_found | G1 | not_found; isi prodi Manajemen (pemasaran) ada, penilaian 'cocok' tidak | refused_llm (tolak_keliru) |
| v2d-065 | sebagian | ya | llm_not_found | G1 | not_found; daftar mata kuliah tidak ada, keahlian AI-based software ada | refused_llm (tolak_keliru) |
| v2d-071 | sebagian | ya | llm_not_found | G1 | not_found; nama perusahaan tidak ada, MCC bermitra industri ada | refused_llm (tolak_keliru) |
| v2d-085 | sebagian | tidak | gold_tidak_top5 | G2 | chunk gold (MPT, kemahasiswaan#7/#12) tidak di top-5 | refused_llm (tolak_keliru) |
| v2d-086 | sebagian | ya | llm_not_found | G1 | not_found; bulan tidak ada, 'minimal 1x per tahun akademik' ada | refused_llm (tolak_keliru) |
| v2d-087 | ada | ya | gerbang_3 | G3 | unsupported 3.000: jawaban 'sekitar 3.000', sumber '3k students' | refused_check (tolak_keliru) |
| v2d-089 | sebagian | tidak | gold_tidak_top5 | G2 | chunk gold (Layanan Fakultas) tidak di top-5 | answered (tidak_lengkap) |
| v2d-091 | ada | tidak | gold_tidak_top5 | G2 | chunk gold (akademik#32 daring) tidak di top-5 | refused_llm (tolak_keliru) |
| v2d-092 | ada | tidak | gerbang_1 | G8 | dense@1 0,462 < 0,50; gold di peringkat 38 | refused_gate (tolak_keliru) |
| v2d-096 | sebagian | ya | llm_not_found | G1 | not_found; 'ujian lewat aplikasi pembelajaran' ada | answered (halusinasi/A) |
| v2d-106 | premis_salah | ya | llm_not_found | G5 | not_found; seharusnya false_premise (B0 mengoreksi) | false_premise (benar) |
| v2d-108 | premis_salah | ya | llm_not_found | G5 | not_found; KB hanya kampus Medan (kunci ragu) | refused_llm (tolak_keliru) |

## 4. Token Groq per soal (D)

Dari `usage` respons Groq di V6 (99 soal yang sampai ke LLM; 9 soal berhenti di gerbang 1 tanpa panggilan LLM; `llm_raw` di baris refused_gate V6 adalah sisa soal sebelumnya karena bug pencatatan dan diabaikan). Hanya panggilan terakhir yang tercatat; 6 percobaan ulang (timeout) juga memakai kuota tetapi tidak tercatat.

| | rata-rata | p95 |
|---|---|---|
| V6 input (prompt_tokens) | 2992 | 3639 |
| V6 output (completion_tokens, termasuk penalaran) | 113 | 219 |
| V6 total per soal | 3105 | 3739 |
| Verifikator input, perkiraan (52 jawaban) | 2383 | 3076 |
| Verifikator output, perkiraan | 124 | 220 |
| **V6G total per soal, perkiraan** | **4422** | **6646** |

- Input verifikator diperkirakan dari panjang prompt verifikator (karakter) dibagi rasio karakter/token V6 (3.54 karakter per token, median dari 99 prompt V6 yang dibangun ulang). Output verifikator adalah **asumsi** (40 token per kalimat klaim + 60), karena run V6G yang sah belum ada.
- Total V6 tercatat: 307423 token; perkiraan V6G (V6 + verifikator): 437773 token. Batas Groq gpt-oss-120b: 8.000 token/menit dan 200.000 token/hari, sehingga satu run 108 soal V6G tidak muat dalam kuota harian satu hari.
