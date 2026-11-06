# V2-3/V2-4: Hasil penyetelan di set dev v2 (B0 / R / V6 / V6G)

Mengikuti `docs/PRA-REGISTRASI-V2.md` (commit `v2-3a`). Penilaian oleh Claude di set dev, **bukan penilaian resmi**; aturan sama dengan V2-2 (`docs/V2-BASELINE-DEV.md`). `config/prod.yaml` tidak diubah; semua perubahan default mati.

## 1. Ringkasan

| | B0 | V6 | V6G |
|---|---|---|---|
| Dijawab | 48 | 44 | 41 |
| Tidak halu [Wilson 95%] | 37/48 = 77.1% [63.5; 86.7] | 37/44 = 84.1% [70.6; 92.1] | 37/41 = 90.2% [77.5; 96.1] |
| Halusinasi | 11 (A 4 / B 7) | 7 (A 2 / B 5) | 4 (A 2 / B 2) |
| Tolak keliru (g1 / top5 / not_found / g3) | 26 (1 / 12 / 10 / 3) | 28 (1 / 7 / 14 / 6) | 31 (1 / 7 / 14 / 9) |
| Tolak tepat | 34 | 36 | 36 |
| Recall@5 | 52/68 = 0.76 | 58/68 = 0.85 | 58/68 = 0.85 |
| Recall@20 | 64/68 = 0.94 | 66/68 = 0.97 | 66/68 = 0.97 |

Recall dihitung untuk soal jenis ada/sebagian dengan chunk gold (n=68). Semua kandidat memakai retrieval R (P1). g3 = gerbang 3 (cek angka/kontak atau verifikator P3).

**Run belum lengkap (tidak dinilai):** V6r 0/108, V6Gr 0/108.

**R (P1, retrieval saja):** recall@5 B0 52/68 -> R 58/68 (top-5 V6 = top-5 R), @20 64/68 -> 66/68. Latensi retrieval + reranker di CPU laptop: p50 14.6 detik, p95 15.3 detik per kueri (SDD ADR-01/E-01 mensyaratkan p95 <= 0,5 detik untuk reranker).

## 2. Aturan pilih (pra-reg bagian 4)

| kandidat | halu < 11 | tidak halu >= 77,1% | tolak keliru <= 26 | lolos |
|---|---|---|---|---|
| V6 | halu 7 < 11 (ya) | tidak halu 84.1% >= 77.1% (ya) | tolak keliru 28 <= 26 (tidak) | tidak |
| V6G | halu 4 < 11 (ya) | tidak halu 90.2% >= 77.1% (ya) | tolak keliru 31 <= 26 (tidak) | tidak |

**Tidak ada kandidat yang lolos.** Sesuai pra-reg: v2 = B0 + perubahan yang lolos sendiri-sendiri, atau tidak ada perubahan.

Catatan pra-reg: n kecil (sekitar 50 jawaban), selisih di set dev hanya indikatif; klaim perbaikan yang sah hanya dari Tahap 2. Konfigurasi terpilih **belum** diaktifkan di `config/prod.yaml`.

## 3. Koreksi penilaian

Dibuat setelah laporan V2-3 (commit `v2-3b`), sebelum run V6r/V6Gr.

| qid | run | koreksi | alasan |
|---|---|---|---|
| v2d-046 | V6G | benar -> tidak_lengkap | KB v5 memuat Ujian Saring Masuk S2 (pedoman-pmb-2027#7 butir e, ada di top-5); jawaban tidak menyebutnya. Bukan halusinasi, jadi persen tidak halu tetap. |
| v2d-059 | V6G | penyebab llm_not_found -> gerbang_3 (verifikator) | status answered, tetapi verifikator membuang kalimat jawabannya sehingga sisanya hanya penolakan; label tetap tolak_keliru. |

## 4. Penyedia LLM penjawab

Rantai `llm.chain` = gpt-oss-120b lalu gpt-oss-20b (config prod). Bila 120b gagal (misalnya HTTP 429 batas token harian), jawaban datang dari 20b.

| run | gpt-oss-120b | gpt-oss-20b | tanpa LLM (gerbang 1) |
|---|---|---|---|
| B0 | 64 | 35 | 9 |
| V6 | 64 | 35 | 9 |
| V6G | 64 | 35 | 9 |

## 5. Soal yang berubah label

| qid | jenis | B0 | V6 | V6G |
|---|---|---|---|---|
| v2d-003 | ada | tolak_keliru (gold_tidak_top5) | tidak_lengkap | tidak_lengkap |
| v2d-004 | sebagian | tolak_keliru (llm_not_found) | tidak_lengkap | tidak_lengkap |
| v2d-006 | sebagian | tolak_keliru (gold_tidak_top5) | tolak_keliru (llm_not_found) | tolak_keliru (llm_not_found) |
| v2d-010 | ada | tidak_lengkap | benar | benar |
| v2d-013 | ada | tidak_lengkap | tolak_keliru (gerbang_3) | tolak_keliru (gerbang_3) |
| v2d-014 | ada | halusinasi/B | tidak_lengkap | tidak_lengkap |
| v2d-016 | tidak_ada | halusinasi/B | tolak_tepat | tolak_tepat |
| v2d-019 | sebagian | tolak_keliru (gold_tidak_top5) | tolak_keliru (llm_not_found) | tolak_keliru (llm_not_found) |
| v2d-028 | ada | tidak_lengkap | tolak_keliru (gerbang_3) | tolak_keliru (gerbang_3) |
| v2d-031 | ada | halusinasi/B | tidak_lengkap | tidak_lengkap |
| v2d-039 | ada | benar | tolak_keliru (llm_not_found) | tolak_keliru (llm_not_found) |
| v2d-040 | ada | tidak_lengkap | halusinasi/B | tidak_lengkap |
| v2d-041 | ada | benar | benar | tolak_keliru (gerbang_3) |
| v2d-043 | ada | halusinasi/B | tolak_keliru (gerbang_3) | tolak_keliru (gerbang_3) |
| v2d-044 | ada | tolak_keliru (gerbang_3) | benar | benar |
| v2d-046 | ada | tolak_keliru (gerbang_3) | tolak_keliru (gerbang_3) | tidak_lengkap |
| v2d-047 | ada | halusinasi/B | halusinasi/B | tolak_keliru (gerbang_3) |
| v2d-048 | ada | halusinasi/B | benar | benar |
| v2d-051 | ada | tidak_lengkap | benar | benar |
| v2d-052 | ada | benar | halusinasi/B | halusinasi/B |
| v2d-056 | ada | benar | tolak_keliru (gerbang_3) | tolak_keliru (gerbang_3) |
| v2d-059 | ada | tidak_lengkap | tidak_lengkap | tolak_keliru (gerbang_3) |
| v2d-062 | ada | tolak_keliru (gold_tidak_top5) | tidak_lengkap | tidak_lengkap |
| v2d-064 | sebagian | tolak_keliru (gold_tidak_top5) | benar | benar |
| v2d-066 | ada | tidak_lengkap | benar | benar |
| v2d-083 | ada | tidak_lengkap | benar | benar |
| v2d-084 | ada | tolak_keliru (gold_tidak_top5) | tidak_lengkap | tidak_lengkap |
| v2d-088 | ada | benar | halusinasi/B | tolak_keliru (gerbang_3) |
| v2d-089 | sebagian | tidak_lengkap | tolak_keliru (gold_tidak_top5) | tolak_keliru (gold_tidak_top5) |
| v2d-094 | sebagian | halusinasi/A | halusinasi/B | halusinasi/B |
| v2d-096 | sebagian | halusinasi/A | tolak_keliru (llm_not_found) | tolak_keliru (llm_not_found) |
| v2d-106 | premis_salah | benar | tolak_keliru (llm_not_found) | tolak_keliru (llm_not_found) |
| v2d-107 | premis_salah | halusinasi/B | tolak_tepat | tolak_tepat |

## 6. Run yang dilakukan

- `default`: override `{}`, config_hash `073e446b9879`.
- `R`: override `{"rag": {"reranker": {"enabled": true, "revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"}}}`, config_hash `d4f838168ce7`.
- `V6`: override `{"rag": {"reranker": {"enabled": true, "revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"}, "prompt_variant": "v6"}}`, config_hash `9a4cc2cb5492`.
- `V6G`: override `{"rag": {"reranker": {"enabled": true, "revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"}, "prompt_variant": "v6", "gate": {"sentence_verify": {"enabled": true, "temperature": 0.0}}}}`, config_hash `29b877ba933a`.
- V6G run 1 (`eval/dev/v2_3/V6G_run1_gagal429.jsonl`) **tidak sah**: verifikator kena HTTP 429 karena batas token harian Groq gpt-oss-120b (200.000 TPD) habis setelah V6; verifikator fail-closed sehingga jawaban ditolak. Dihentikan, diarsipkan, tidak dinilai. Run sah dilanjutkan setelah kuota pulih, dengan V6 yang sama.
- Retrieval config bawaan identik dengan B0 di 10/10 soal (`eval/dev/v2_3/default_check.json`).
- Reranker V6r/V6Gr: kondisi R yang lama (bawaan CrossEncoder, kandidat 20). `docs/V2-RERANK-LATENSI.md` tidak ada; bench `scripts/v2_rerank_bench.py` hanya menyelesaikan kondisi 1 (= kondisi R: top-5 sama dengan R 68/68, p50 14,46 / p95 14,82 detik per kueri, `eval/dev/v2_3/rerank_bench_stdout.txt`). Kondisi 2-4 tidak terukur.

## 7. Revisi prompt

- Prompt v6: 1 dari maksimal 1 -> `v6r` (sasaran G1 dan G4, `docs/PROMPT-V6.md` "Revisi 1").
- Prompt verifikator: 1 dari maksimal 1 -> `r1` (definisi faithfulness RAGAs).

## 8. Per soal

| qid | jenis | V6 status | V6 nilai | V6G status | V6G nilai | catatan |
|---|---|---|---|---|---|---|
| v2d-001 | ada | answered | benar | answered | benar | - |
| v2d-002 | sebagian | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |
| v2d-003 | ada | answered | tidak_lengkap | answered | tidak_lengkap | hanya pasangan 14 jt/15 jt (Informatika); prodi bisnis tidak disebut |
| v2d-004 | sebagian | answered | tidak_lengkap | answered | tidak_lengkap | menyatakan lama studi tidak tercantum padahal A24 memuat 4 semester |
| v2d-005 | sebagian | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |
| v2d-006 | sebagian | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |
| v2d-007 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-008 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-009 | ada | answered | benar | answered | benar | - |
| v2d-010 | ada | answered | benar | answered | benar | - |
| v2d-011 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-012 | ada | answered | benar | answered | benar | - |
| v2d-013 | ada | refused_check | tolak_keliru (gerbang_3) | refused_check | tolak_keliru (gerbang_3) | unsupported=None |
| v2d-014 | ada | answered | tidak_lengkap | answered | tidak_lengkap | verifikator membuang 'berpeluang' dan 'piagam juara provinsi'; PMDK tetap tidak disebut |
| v2d-015 | ada | answered | benar | answered | benar | - |
| v2d-016 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-017 | sebagian | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |
| v2d-018 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-019 | sebagian | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |
| v2d-020 | tidak_ada | refused_gate | tolak_tepat | refused_gate | tolak_tepat | - |
| v2d-021 | tidak_ada | answered | halusinasi/A | answered | halusinasi/A | kunci tidak_ada |
| v2d-022 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-023 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-024 | sebagian | refused_llm | tolak_keliru (gold_tidak_top5) | refused_llm | tolak_keliru (gold_tidak_top5) | - |
| v2d-025 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-026 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-027 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-028 | ada | refused_check | tolak_keliru (gerbang_3) | refused_check | tolak_keliru (gerbang_3) | unsupported=['12', '4'] |
| v2d-029 | ada | answered | benar | answered | benar | kalimat Blibli dibuang verifikator (Blibli bukan bank); kanal VA BCA lengkap |
| v2d-030 | sebagian | answered | benar | answered | benar | - |
| v2d-031 | ada | answered | tidak_lengkap | answered | tidak_lengkap | cara bayar (Blibli/VA BCA) tidak disebut |
| v2d-032 | sebagian | answered | benar | answered | benar | 6x/2x per semester diturunkan dari jadwal KB (sama dengan B0) |
| v2d-033 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-034 | sebagian | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |
| v2d-035 | ada | answered | benar | answered | benar | - |
| v2d-036 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-037 | ada | answered | benar | answered | benar | - |
| v2d-038 | tidak_ada | refused_gate | tolak_tepat | refused_gate | tolak_tepat | - |
| v2d-039 | ada | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |
| v2d-040 | ada | answered | halusinasi/B | answered | tidak_lengkap | klaim halu 'Reguler biasanya tes' dibuang; Reguler tanpa tes dan USM S2 tidak disebut |
| v2d-041 | ada | answered | benar | refused_check | tolak_keliru (gerbang_3) | unsupported=None |
| v2d-042 | sebagian | answered | benar | answered | benar | hanya baris sitasi yang dibuang; isi sama dengan V6 |
| v2d-043 | ada | refused_check | tolak_keliru (gerbang_3) | refused_check | tolak_keliru (gerbang_3) | unsupported=None |
| v2d-044 | ada | answered | benar | answered | benar | - |
| v2d-045 | ada | answered | benar | answered | benar | - |
| v2d-046 | ada | refused_check | tolak_keliru (gerbang_3) | answered | tidak_lengkap | koreksi V2-4: Ujian Saring Masuk S2 ada di KB v5 (pedoman-pmb-2027#7 butir e, di top-5) tetapi tidak disebut; klaim lain benar (P13/P14/P20) |
| v2d-047 | ada | answered | halusinasi/B | refused_check | tolak_keliru (gerbang_3) | unsupported=None |
| v2d-048 | ada | answered | benar | answered | benar | - |
| v2d-049 | ada | answered | benar | answered | benar | - |
| v2d-050 | ada | answered | benar | answered | benar | - |
| v2d-051 | ada | answered | benar | answered | benar | - |
| v2d-052 | ada | answered | halusinasi/B | answered | halusinasi/B | KB: status aktif terakhir maks 2 tahun dari pengajuan |
| v2d-053 | sebagian | refused_llm | tolak_keliru (gold_tidak_top5) | refused_llm | tolak_keliru (gold_tidak_top5) | - |
| v2d-054 | ada | answered | benar | answered | benar | beda hanya spasi U+202F; isi sama dengan V6 |
| v2d-055 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-056 | ada | refused_check | tolak_keliru (gerbang_3) | refused_check | tolak_keliru (gerbang_3) | unsupported=['0811', '7070', '3992'] |
| v2d-057 | sebagian | refused_llm | tolak_keliru (gold_tidak_top5) | refused_llm | tolak_keliru (gold_tidak_top5) | - |
| v2d-058 | ada | answered | benar | answered | benar | - |
| v2d-059 | ada | answered | tidak_lengkap | answered | tolak_keliru (gerbang_3) | kalimat tracer study dibuang; sisa hanya 'dokumen tidak menyebutkan data khusus Akuntansi' = penolakan (seperti v2d-068); penyebab sebenarnya verifikator (P3) |
| v2d-060 | ada | refused_llm | tolak_keliru (gold_tidak_top5) | refused_llm | tolak_keliru (gold_tidak_top5) | - |
| v2d-061 | sebagian | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |
| v2d-062 | ada | answered | tidak_lengkap | answered | tidak_lengkap | Magister Teknologi Informasi tidak disebut |
| v2d-063 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-064 | sebagian | answered | benar | answered | benar | 144 sks berlaku untuk semua program sarjana (A24) |
| v2d-065 | sebagian | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |
| v2d-066 | ada | answered | benar | answered | benar | - |
| v2d-067 | tidak_ada | refused_check | tolak_tepat | refused_check | tolak_tepat | unsupported=None |
| v2d-068 | tidak_ada | false_premise | tolak_tepat | false_premise | tolak_tepat | false_premise, isi = info tidak ada; dinilai penolakan seperti B0 |
| v2d-069 | ada | answered | benar | answered | benar | - |
| v2d-070 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-071 | sebagian | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |
| v2d-072 | ada | answered | benar | answered | benar | - |
| v2d-073 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-074 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-075 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-076 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-077 | tidak_ada | refused_gate | tolak_tepat | refused_gate | tolak_tepat | - |
| v2d-078 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-079 | tidak_ada | answered | halusinasi/A | answered | halusinasi/A | kunci tidak_ada; KB hanya UKM olahraga (sama dengan B0) |
| v2d-080 | ada | answered | benar | answered | benar | - |
| v2d-081 | ada | answered | benar | answered | benar | - |
| v2d-082 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-083 | ada | answered | benar | answered | benar | 'seragam tidak bebas' tetap tidak tepat (ditoleransi seperti B0); Jas Akademis kini disebut |
| v2d-084 | ada | answered | tidak_lengkap | answered | tidak_lengkap | kalimat Keluarga Mahasiswa Keagamaan dibuang; sisa (kerukunan beragama) tidak menjawab |
| v2d-085 | sebagian | refused_llm | tolak_keliru (gold_tidak_top5) | refused_llm | tolak_keliru (gold_tidak_top5) | - |
| v2d-086 | sebagian | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |
| v2d-087 | ada | refused_check | tolak_keliru (gerbang_3) | refused_check | tolak_keliru (gerbang_3) | unsupported=['3.000'] |
| v2d-088 | ada | answered | halusinasi/B | refused_check | tolak_keliru (gerbang_3) | unsupported=None |
| v2d-089 | sebagian | refused_llm | tolak_keliru (gold_tidak_top5) | refused_llm | tolak_keliru (gold_tidak_top5) | - |
| v2d-090 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-091 | ada | refused_llm | tolak_keliru (gold_tidak_top5) | refused_llm | tolak_keliru (gold_tidak_top5) | - |
| v2d-092 | ada | refused_gate | tolak_keliru (gerbang_1) | refused_gate | tolak_keliru (gerbang_1) | - |
| v2d-093 | ada | answered | benar | answered | benar | - |
| v2d-094 | sebagian | answered | halusinasi/B | answered | halusinasi/B | prodi sama = joint degree, satu gelar |
| v2d-095 | ada | answered | benar | answered | benar | - |
| v2d-096 | sebagian | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |
| v2d-097 | ada | answered | benar | answered | benar | - |
| v2d-098 | tidak_ada | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-099 | luar_topik | refused_gate | tolak_tepat | refused_gate | tolak_tepat | - |
| v2d-100 | luar_topik | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-101 | luar_topik | refused_gate | tolak_tepat | refused_gate | tolak_tepat | - |
| v2d-102 | luar_topik | refused_gate | tolak_tepat | refused_gate | tolak_tepat | - |
| v2d-103 | luar_topik | refused_gate | tolak_tepat | refused_gate | tolak_tepat | - |
| v2d-104 | tidak_ada | refused_gate | tolak_tepat | refused_gate | tolak_tepat | - |
| v2d-105 | premis_salah | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-106 | premis_salah | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |
| v2d-107 | premis_salah | refused_llm | tolak_tepat | refused_llm | tolak_tepat | - |
| v2d-108 | premis_salah | refused_llm | tolak_keliru (llm_not_found) | refused_llm | tolak_keliru (llm_not_found) | - |

## 9. Berkas

- `eval/dev/v2_3/R.jsonl`, `V6.jsonl`, `V6r.jsonl` (termasuk keluaran LLM mentah), `V6G.jsonl`, `V6Gr.jsonl` (putusan verifikator per kalimat di `fact_check.sentence_verify`), `logs-*`, `meta.json`.
- Penilaian: `eval/dev/v2_3/nilai_<run>.py`, `penilaian_*.csv`.
- Skrip: `scripts/v2_3_runs.py`, `scripts/v2_3_report.py`. Prompt: `docs/PROMPT-V6.md`.
