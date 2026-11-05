# Pra-registrasi MICA v2 (penyetelan di set dev)

Ditulis 4 Nov 2026, SEBELUM perbaikan dijalankan. Baseline resmi Tahap 1 (73,8% tidak halu, Wilson [62,0; 83,0], tag `tahap1-beku`) tidak diubah dan tetap dilaporkan apa adanya. MICA v2 diuji secara independen di Tahap 2.

## 1. Data
- Set penyetelan: set dev v2, berisi 108 soal (`data/eval/dev-v2-soal.csv`). Soal dibuat Claude tanpa melihat KB, lalu 11 soal yang mirip set uji (Jaccard kata >= 0,45) dibuang. Kunci jawaban dibuat Claude dari KB v5 dan di-commit sebelum sistem dijalankan (9ec403b).
- Penilaian jawaban di set dev dilakukan Claude memakai aturan Panduan Penilai Tahap 1. Penilaian ini tidak resmi dan diungkap di Bab 3.
- Set uji Tahap 1 (129 soal) TIDAK dipakai untuk menyetel. Yang dipakai dari Tahap 1 hanya pola kesalahan agregat (6 halu A, 11 halu B, 19 tolak keliru), dan ini diungkap.
- Baseline dev (sistem v5, 1f92d27): dijawab 48, tidak halu 37/48 = 77,1% [63,5; 86,7], halu A 4 / B 7, tolak keliru 26 (g1 1, top-5 12, not_found 10, g3 3), tolak tepat 34. Recall@5 0,76, @20 0,94.

## 2. Perubahan yang diuji (masing-masing bisa dimatikan lewat config)
| Kode | Perubahan | Masalah sasaran | Sumber |
|---|---|---|---|
| P1 | Reranker cross-encoder `BAAI/bge-reranker-v2-m3`: hybrid mengambil 20 kandidat, reranker memilih 5 untuk LLM | tolak keliru karena chunk gold tidak masuk top-5 | Lin, Nogueira, Yates, *Pretrained Transformers for Text Ranking: BERT and Beyond*, Synthesis Lectures on HLT, 2021; Chen dkk., M3-Embedding, Findings ACL 2024 (keluarga BGE) |
| P2 | Prompt v6: (a) larang klaim "biasanya/umumnya/pada umumnya" dan pengetahuan di luar potongan; (b) bila hanya sebagian pertanyaan terjawab, jawab bagian itu dan sebut bagian yang tidak ditemukan (bukan not_found untuk semua); (c) setiap kalimat klaim wajib bersitasi | halu A; tolak keliru not_found | Dhuliawala dkk., Chain-of-Verification, Findings ACL 2024 (prinsip verifikasi); aturan grounded Es dkk. 2024 |
| P3 | Gerbang 3 per kalimat: jawaban dipecah per kalimat, lalu satu panggilan LLM verifikator menilai tiap kalimat klaim "didukung / tidak didukung" oleh potongan. Kalimat tak didukung dibuang. Bila tidak ada kalimat klaim yang tersisa, jawaban ditolak. Cek angka/kontak lama tetap jalan. | halu B | Es dkk., RAGAs (faithfulness = proporsi pernyataan yang dapat disimpulkan dari konteks), EACL 2024 Demo; Dhuliawala dkk. 2024 |

Nilai coba (bukan hasil penyetelan): kandidat reranker 20 (recall@20 baseline 0,94), top-k ke LLM tetap 5, verifikator = model yang sama (gpt-oss-120b), suhu 0. Ambang gerbang 1 tetap 0,50.

## 3. Konfigurasi yang dijalankan (hanya ini, urutan tetap)
- B0 = baseline (sudah ada).
- R = B0 + P1, retrieval saja (recall@5, tanpa LLM).
- V6 = P1 + P2, pipeline penuh.
- V6G = P1 + P2 + P3. Verifikator dijalankan pada jawaban V6 yang sama, supaya selisihnya murni dari P3.
- Maksimal SATU revisi teks prompt v6 dan SATU revisi prompt verifikator. Setiap revisi dicatat beserta alasannya, dan semua run dilaporkan (tidak ada run yang disembunyikan).

## 4. Aturan memilih konfigurasi final (ditetapkan sebelum run)
Kandidat diterima bila, di set dev v2 dibanding B0:
1. jumlah halusinasi turun (< 11), dan
2. tidak halu (%) >= 77,1, dan
3. tolak keliru tidak naik (<= 26).

Bila dua kandidat lolos, yang dipilih adalah yang halusinasinya paling sedikit; bila sama, yang tolak kelirunya paling sedikit. Bila tidak ada yang lolos, v2 = B0 + perubahan yang lolos sendiri-sendiri, atau tidak ada perubahan, dan itu dilaporkan apa adanya.
Catatan: n kecil (sekitar 50 jawaban), sehingga selisih di set dev hanya indikatif. Klaim perbaikan yang sah hanya dari Tahap 2.

## 5. Yang diungkap di Bab 3
Soal dan kunci dev dibuat Claude; penilaian dev oleh Claude; pola agregat Tahap 1 dipakai sebagai arah perbaikan; ada 8 kunci dev bertanda "ragu"; semua revisi prompt dan run yang dilakukan.
