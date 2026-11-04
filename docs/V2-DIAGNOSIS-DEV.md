# V2-1: Diagnosis retrieval set dev (tanpa ubah kode)

Tanggal run: 2026-11-04T15:34:34+07:00. Branch `v2/perbaikan`. Tidak ada kode aplikasi (`src/`, `config/`) yang diubah. Set uji Tahap 1 tidak dibaca dan tidak dipakai.

## 1. Bahan

- **Set dev**: `data/eval/questions.jsonl` (45 soal, d001-d045, split `dev`). File `questions_dev_draft.jsonl` dan `questions_dev_tambahan_oos.jsonl` yang disebut di instruksi tidak ada di repo; `questions.jsonl` berisi 45 soal dengan pola qid yang sama.
- **Komposisi sebenarnya** (berbeda dari instruksi "d001-d033 answerable, d034+ out_of_kb"): answerable d001-d023 (23), out_of_kb d024-d028 dan d034-d045 (17), false_premise d029-d031 (3), followup d032-d033 (2).
- Pemetaan gold dibuat untuk d001-d033. Diagnosis memakai soal bertipe answerable, false_premise, dan followup yang punya chunk gold v5 (status `ada` atau `sebagian`); tipe out_of_kb tidak didiagnosis.
- **KB**: `official-2026-10-24-v5` (202 chunk). **Konfigurasi**: `config/prod.yaml` apa adanya (config_hash `073e446b9879`): retriever `hybrid` (BM25 + BGE-M3, RRF k=60, 20 kandidat per retriever), top_k ke LLM = **5**, followup_mode `dual`, gerbang dense@1 >= 0.5, prompt `v5`, rantai groq:openai/gpt-oss-120b, groq:openai/gpt-oss-20b.
- Konfigurasi prod dimuat dengan `require_complete=False` karena field audio/vision prod masih TBD (null); bagian RAG/LLM tidak terpengaruh.
- Peringkat top-50: hybrid hanya menghasilkan paling banyak 40 kandidat unik (2 x 20), jadi top-50 = seluruh kolam kandidat. Semua chunk gold masuk kolam.
- Followup (d032, d033) diambil lewat `DualFollowup` dengan pertanyaan sebelumnya (d001, d011), sama seperti pipeline; history LLM = jawaban pipeline untuk soal sebelumnya di run ini.
- Bila sebuah soal punya beberapa chunk gold, peringkat = peringkat terbaik di antara chunk gold (hit bila salah satu masuk).

## 2. Pemetaan gold ke KB v5 (`eval/dev/gold_v5_map.csv`)

| qid | tipe | status | chunk v5 | catatan |
|---|---|---|---|---|
| d001 | answerable | ada | brosur/brosur-pmb-2025#5 | SI pagi 14.000.000/th, sore 15.000.000/th (brosur, tahun tidak tertulis) |
| d002 | answerable | ada | brosur/brosur-pmb-2025#10 | Akuntansi sore 13.500.000/th |
| d003 | answerable | tidak_ada_di_kb_v5 | - | v5 tidak memuat tanggal gelombang S1 (pmb#5 hanya "September s.d. awal September berikutnya") |
| d004 | answerable | sebagian | pmb/pedoman-pmb-2027#6<br>pmb/pedoman-pmb-2027#7<br>pmb/pedoman-pmb-2027#2 | v5: PMDK (Penelusuran Minat dan Bakat), Prestasi, Reguler, KIP Kuliah (+USM khusus S2); reference_answer (3 jalur) dari KB dev |
| d005 | answerable | ada | pmb/pedoman-pmb-2027#15 | prosedur a-h via daftar.mikroskil.ac.id; jumlah/urutan langkah berbeda dari reference_answer |
| d006 | answerable | ada | brosur/brosur-pmb-2025#14 | "Online Admission/Consultation: 081-160-25-151" = 0811 602 5151 |
| d007 | answerable | tidak_ada_di_kb_v5 | - | jam buka Admisi tidak ada di v5 (keuangan#4 hanya jam layanan kemahasiswaan 09.00-18.00) |
| d008 | answerable | ada | brosur/brosur-pmb-2025#4<br>brosur/brosur-pmb-2025#6<br>akademik/peraturan-akademik-2025#79 | TI: AI/scalable software; TekInfo: cyber security/big data; gelar S.Kom di akademik#79 |
| d009 | answerable | sebagian | brosur/brosur-pmb-2025#7<br>brosur/brosur-pmb-2025#8<br>brosur/brosur-pmb-2025#9<br>brosur/brosur-pmb-2025#10<br>brosur/brosur-pmb-2025#11 | jawaban tersebar: satu chunk per prodi (MM, Manajemen, Akuntansi, Hukum Bisnis); tidak ada chunk tunggal |
| d010 | answerable | tidak_ada_di_kb_v5 | - | akreditasi per prodi tidak ada di v5 |
| d011 | answerable | sebagian | pmb/pedoman-pmb-2027#14<br>pmb/pedoman-pmb-2027#7 | v5: S1, IPK 2.75, akreditasi asal min Baik/B; USM di pmb#7; TOEFL MM sengaja tidak ada (brosur#0), reference_answer usang |
| d012 | answerable | ada | pmb/pedoman-pmb-2027#14 | TOEFL minimal 475 (Magister TI) |
| d013 | answerable | tidak_ada_di_kb_v5 | - | jadwal kelas eksekutif MM tidak ada (brosur#8 hanya biaya) |
| d014 | answerable | sebagian | kemahasiswaan/panduan-kemahasiswaan-2021#18<br>pmb/pedoman-pmb-2027#7<br>kemahasiswaan/panduan-kemahasiswaan-2021#16<br>kemahasiswaan/panduan-kemahasiswaan-2021#17<br>keuangan/panduan-pembayaran-2026-2027#19 | v5: Beasiswa Akademik (kem#18), KIP Kuliah (pmb#7), Yayasan/Dikti (kem#16-17), potongan (keu#19); Minat Bakat dan IP4 tidak ada |
| d015 | answerable | sebagian | brosur/brosur-pmb-2025#1<br>pmb/pedoman-pmb-2027#1 | STMIK 1997, STIE 2008 (brosur#1); izin penggabungan 2021 (pmb#1); IMC 1992 tidak ada |
| d016 | answerable | ada | pmb/pedoman-pmb-2027#1<br>pmb/pedoman-pmb-2027#2<br>pmb/pedoman-pmb-2027#3<br>pmb/pedoman-pmb-2027#4<br>pmb/pedoman-pmb-2027#23 | Rektor Hardy, S.Kom., M.Sc., Ph.D. (penanda tangan Pedoman PMB 2027) |
| d017 | answerable | ada | brosur/brosur-pmb-2025#13 | Mikroskil Futsal Club |
| d018 | answerable | ada | keuangan/panduan-pembayaran-2026-2027#3<br>keuangan/panduan-pembayaran-2026-2027#20 | fin@mikroskil.ac.id; catatan: v5 juga memuat WA 081170703992 (reference_answer bilang tidak tercatat) |
| d019 | answerable | tidak_ada_di_kb_v5 | - | lokasi lab komputer tidak ada di v5 |
| d020 | answerable | sebagian | brosur/brosur-pmb-2025#9 | Expertise International Business / Culinary Business; "mulai semester IV" tidak ada |
| d021 | answerable | ada | brosur/brosur-pmb-2025#5 | career path SI (ERP Consultant, Business Analyst, System Analyst, ...) |
| d022 | answerable | ada | brosur/brosur-pmb-2025#1 | 88% lulusan bekerja < 6 bulan (tracer study 2025); angka situs pendaftaran tidak ada di v5 |
| d023 | answerable | tidak_ada_di_kb_v5 | - | tanggal kuliah perdana S2 tidak ada di v5 |
| d024 | out_of_kb | tidak_ada_di_kb_v5 | - | label out_of_kb; asrama tidak ada di v5 |
| d025 | out_of_kb | ada | keuangan/panduan-pembayaran-2026-2027#8<br>keuangan/panduan-pembayaran-2026-2027#9<br>keuangan/panduan-pembayaran-2026-2027#10<br>keuangan/panduan-pembayaran-2026-2027#11<br>pmb/pedoman-pmb-2027#19 | LABEL USANG: v5 memuat skema cicilan (pagi 12x, sore 4x); di luar diagnosis (tipe out_of_kb) |
| d026 | out_of_kb | tidak_ada_di_kb_v5 | - | label out_of_kb; v5 hanya menyebut DP3 ditetapkan Rektor (pmb#19), tanpa nominal |
| d027 | out_of_kb | tidak_ada_di_kb_v5 | - | label out_of_kb; pmb#7: nilai rapor "sesuai ketentuan panitia PMB", tanpa angka |
| d028 | out_of_kb | tidak_ada_di_kb_v5 | - | label out_of_kb; jadwal USM tidak ada |
| d029 | false_premise | ada | pmb/pedoman-pmb-2027#14<br>akademik/peraturan-akademik-2025#79 | tidak ada prodi kedokteran; daftar prodi di pmb#14 |
| d030 | false_premise | tidak_ada_di_kb_v5 | - | akreditasi TI tidak ada di v5, premis tidak bisa dikoreksi dari KB |
| d031 | false_premise | tidak_ada_di_kb_v5 | - | jumlah/tanggal gelombang S1 tidak ada di v5 |
| d032 | followup | ada | brosur/brosur-pmb-2025#5 | lanjutan d001: SI sore 15.000.000/th |
| d033 | followup | ada | pmb/pedoman-pmb-2027#14 | lanjutan d011: syarat Magister TI |

Rekap (d001-d033 tanpa out_of_kb, 28 soal): ada 14, sebagian 6, tidak_ada_di_kb_v5 8, ragu 0.
- tidak_ada_di_kb_v5: answerable d003, d007, d010, d013, d019, d023; false_premise d030, d031.
- Label out_of_kb yang usang terhadap v5: d025 (cicilan; v5 memuat skema cicilan). Di luar d001-d033 juga terlihat d042 (pindahan/SKS; v5 memuat RPL skema transfer SKS, akademik#16-#20). Keduanya tidak didiagnosis di langkah ini.

## 3. Hasil per soal

Kolom: peringkat gold terbaik di hybrid; hit@k; dense@1 = cosine dense peringkat 1 (sinyal gerbang); status akhir pipeline; sitasi LLM; sebab gagal.

| qid | tipe | rank gold | @5 (=top-k) | @10 | @20 | dense@1 | gerbang 1 | status akhir | llm_status | sitasi | sebab |
|---|---|---|---|---|---|---|---|---|---|---|---|
| d001 | answerable | 1 | ya | ya | ya | 0.723 | lolos | answered | answered | brosur/brosur-pmb-2025#5 | other_answered |
| d002 | answerable | 1 | ya | ya | ya | 0.646 | lolos | answered | answered | brosur/brosur-pmb-2025#10 | other_answered |
| d004 | answerable | 1 | ya | ya | ya | 0.478 | GAGAL | refused_gate | - | - | a_gate |
| d005 | answerable | 11 | tidak | tidak | ya | 0.560 | lolos | answered | answered | akademik/peraturan-akademik-2025#44 | b_not_in_topk |
| d006 | answerable | 19 | tidak | tidak | ya | 0.494 | GAGAL | refused_gate | - | - | a_gate |
| d008 | answerable | 1 | ya | ya | ya | 0.583 | lolos | answered | answered | brosur/brosur-pmb-2025#4<br>brosur/brosur-pmb-2025#6 | other_answered |
| d009 | answerable | 1 | ya | ya | ya | 0.612 | lolos | answered | answered | brosur/brosur-pmb-2025#11<br>brosur/brosur-pmb-2025#9<br>brosur/brosur-pmb-2025#10 | other_answered |
| d011 | answerable | 1 | ya | ya | ya | 0.666 | lolos | answered | answered | pmb/pedoman-pmb-2027#14 | other_answered |
| d012 | answerable | 1 | ya | ya | ya | 0.638 | lolos | answered | answered | pmb/pedoman-pmb-2027#14 | other_answered |
| d014 | answerable | 1 | ya | ya | ya | 0.625 | lolos | answered | answered | kemahasiswaan/panduan-kemahasiswaan-2021#16<br>kemahasiswaan/panduan-kemahasiswaan-2021#18<br>akademik/peraturan-akademik-2025#83 | other_answered |
| d015 | answerable | 1 | ya | ya | ya | 0.613 | lolos | answered | answered | pmb/pedoman-pmb-2027#1 | other_answered |
| d016 | answerable | 2 | ya | ya | ya | 0.564 | lolos | answered | answered | pmb/pedoman-pmb-2027#2 | other_answered |
| d017 | answerable | 1 | ya | ya | ya | 0.550 | lolos | answered | answered | brosur/brosur-pmb-2025#13 | other_answered |
| d018 | answerable | 1 | ya | ya | ya | 0.607 | lolos | answered | answered | keuangan/panduan-pembayaran-2026-2027#20<br>keuangan/panduan-pembayaran-2026-2027#3 | other_answered |
| d020 | answerable | 4 | ya | ya | ya | 0.574 | lolos | answered | answered | brosur/brosur-pmb-2025#8 | other_answered |
| d021 | answerable | 11 | tidak | tidak | ya | 0.581 | lolos | refused_llm | not_found | - | b_not_in_topk |
| d022 | answerable | 3 | ya | ya | ya | 0.538 | lolos | answered | answered | brosur/brosur-pmb-2025#1 | other_answered |
| d029 | false_premise | 11 | tidak | tidak | ya | 0.607 | lolos | refused_llm | not_found | - | b_not_in_topk |
| d032 | followup | 17 | tidak | tidak | ya | 0.731 | lolos | answered | answered | keuangan/panduan-pembayaran-2026-2027#11 | b_not_in_topk |
| d033 | followup | 1 | ya | ya | ya | 0.736 | lolos | answered | answered | pmb/pedoman-pmb-2027#14 | other_answered |

## 4. Rekap angka

- Soal didiagnosis: **20**.
- Recall@top-k (5) = **0.75** (15/20); recall@5 = 0.75; recall@10 = 0.75; recall@20 = 1.00 (20/20).
- Gagal gerbang 1 (dense@1 < 0,50): 2.

| sebab | jumlah | qid |
|---|---|---|
| (a) gagal gerbang 1 | 2 | d004, d006 |
| (b) gold tidak masuk top-k ke LLM | 4 | d005, d021, d029, d032 |
| (c) gold di top-k, LLM not_found | 0 | - |
| dijawab (gold di top-k, gerbang lolos) | 14 | d001, d002, d008, d009, d011, d012, d014, d015, d016, d017, d018, d020, d022, d033 |

Urutan pemeriksaan: (a), lalu (b), lalu (c); satu soal hanya masuk satu sebab.

## 5. Catatan pengamatan (bukan penilaian resmi)

- Tidak ada kasus (c): setiap kali chunk gold masuk top-5 dan gerbang lolos, LLM menjawab (bukan not_found).
- (a) d004 (dense@1 0,478, gold peringkat 1) dan d006 (0,494, gold peringkat 19): keduanya sedikit di bawah ambang 0,50. d004 sudah mendapat gold di peringkat 1, jadi penolakannya murni dari gerbang.
- (b) d005, d021, d029: gold di peringkat 11 (tepat di luar top-10); d032 (followup): gold di peringkat 17. Di d021 dan d029 LLM menjawab not_found (wajar, chunk gold tidak dikirim). Di d005 dan d032 LLM tetap menjawab dari chunk lain: d005 mengutip akademik#44 (registrasi KRS mahasiswa, bukan pendaftaran PMB), d032 mengutip keuangan#11 (skema cicilan kelas sore, bukan biaya kelas sore SI). Keduanya tampak salah sasaran; perlu dinilai manusia.
- d020 tercatat "dijawab" (gold brosur#9 di peringkat 4), tetapi LLM mengutip brosur#8 dan menjawab peminatan Magister Manajemen, bukan S1 Manajemen: salah pilih chunk oleh LLM, bukan kegagalan retrieval.
- Kebenaran isi jawaban lain tidak dinilai di langkah ini; jawaban lengkap ada di `eval/dev/v2_diag/per_item.jsonl`.
- Run pertama kena HTTP 429 Groq di banyak soal dan dibuang; run yang dilaporkan memakai jeda 20 detik per panggilan dan ulang bila `unavailable` (semua soal selesai pada percobaan pertama).

## 6. Berkas

- `eval/dev/gold_v5_map.csv`: pemetaan gold v5.
- `eval/dev/v2_diag/per_item.jsonl`: per soal (peringkat semua chunk gold, top-10, top-k, dense@1, gerbang, jawaban, sitasi, fact_check).
- `eval/dev/v2_diag/summary.json`: rekap dan konfigurasi.
- `eval/dev/v2_diag/logs/`: turn log pipeline (format M-11, pertanyaan sudah lewat scrub_pii).
- `eval/dev/v2_diag/run_stdout.txt`: keluaran mentah run.
- `scripts/v2_diag_dev.py`: skrip diagnosis (hanya membaca kode aplikasi). Ulang: `python scripts/v2_diag_dev.py` (butuh GROQ_API_KEY di `.env`).
