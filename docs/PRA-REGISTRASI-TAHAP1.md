# Pra-registrasi Uji RAG Tahap 1 (baseline halusinasi, soal AI)

Ditulis 30 Okt 2026, **sebelum** MICA menjawab satu soal pun. Isi dokumen ini tidak diubah setelah jawaban keluar; perubahan apa pun dicatat di bagian "Penyimpangan" dengan tanggal.

## 1. Tujuan
Mengukur tingkat halusinasi jawaban MICA sebagai **baseline sementara**, sesuai arahan dospem (27 Okt 2026). Uji utama tetap Tahap 2 (3 orang mencoba langsung).

Target dospem: ≥ 80% jawaban **tidak halusinasi**.

## 2. Soal uji
- **Sumber:** 150 soal dibuat Claude Sonnet 5.5 (effort high, akun lain, percakapan baru tanpa dokumen KB) pada 27 Okt 2026. Prompt diarsipkan di `prompt-gemini-tahap1.md` dan disusun hanya dari topik wawancara staf PMB (29 Sep 2026). Model pembuat soal berbeda dari model penjawab MICA (gpt-oss-120b).
- **Penyaringan:** dilakukan oleh seorang teman hasa (bukan anggota tim, belum membaca KB) dengan aturan tertulis: buang hanya soal dobel atau yang tidak masuk akal ditanya ke meja PMB, bukan karena sulit dijawab. Hasilnya: 123 pakai, 21 dobel, 6 tidak wajar (file `soal-ai-150-hasil-saring-teman.xlsx`).
- **Koreksi (diputuskan hasa 30 Okt, sebelum menjalankan MICA):** keenam soal "tidak wajar" (no 6, 17, 56, 58, 106, 138) dikembalikan. Alasannya, semua termasuk topik yang disebut staf PMB sebagai pertanyaan yang sering diajukan, dan alasan penyaring ("tidak penting") di luar aturan. Keputusan dobel tidak diubah.
- **Daftar final:** `uji-tahap1-129.csv`, 129 soal, ID `t1-<nomor asal>`.
  SHA-256: `da7797ffbb733967ae4a2695b0a8b4446651708f8ed57415f43a3ba53456876e`
- Soal ini **tidak boleh** dipakai di KB, prompt, chip saran UI, atau untuk menyetel ambang.

## 3. Sistem yang diuji (dibekukan)
- KB `official-2026-10-24-v5` (202 chunk).
- Retrieval hybrid BM25 + BGE-M3, RRF k=60, top-5.
- Prompt v5.
- LLM Groq `openai/gpt-oss-120b`.
- Gerbang dengan nilai coba yang sama seperti evaluasi dev (gerbang 1: cosine dense@1 ≥ 0,50).
- Satu kali jalan per soal, tanpa riwayat percakapan.
- Tidak ada perubahan KB, prompt, atau ambang setelah jawaban terlihat. Perbaikan sesudahnya dicatat sebagai versi baru dan **tidak** menggantikan angka baseline ini.

## 4. Penilaian
- **Penilai:** 2 orang (hasa dan rekan penulis naskah), menilai **masing-masing tanpa melihat nilai penilai lain**. Claude tidak menilai.
- Penilai memeriksa jawaban terhadap dokumen resmi (Pedoman PMB 2027, Peraturan Akademik 2025, Panduan Kemahasiswaan 2021, brosur 2025, panduan pembayaran 2026/2027).
- **Label per jawaban:**
  - **benar**: semua klaim sesuai dokumen.
  - **tidak lengkap**: yang disebut benar, tetapi ada bagian pertanyaan yang tidak dijawab padahal ada di dokumen.
  - **halusinasi**: ada minimal satu klaim yang tidak didukung atau bertentangan dengan dokumen (definisi mengikuti RAGTruth, Niu dkk., ACL 2024). Untuk soal yang memuat dua pertanyaan, satu bagian yang dikarang sudah cukup untuk label ini.
  - **tolak tepat**: MICA menolak dan informasinya memang tidak ada di dokumen.
  - **tolak keliru**: MICA menolak padahal jawabannya ada di dokumen.
- **Kesepakatan antarpenilai:** Cohen's kappa dihitung dari label awal kedua penilai. Setelah itu perbedaan didiskusikan sampai sepakat, dan label hasil diskusi dipakai untuk angka utama.

## 5. Ukuran hasil
- **Utama:** proporsi jawaban tidak halusinasi = 1 − (halusinasi / semua jawaban yang bukan penolakan), dengan interval Wilson 95%. Target tercapai jika titik estimasinya ≥ 80%. Batas bawah interval juga dilaporkan.
- **Pendukung:**
  - halusinasi / seluruh 129 soal;
  - jumlah tolak tepat dan tolak keliru;
  - rincian per topik dan per persona penanya.

## 6. Penyimpangan
- **30 Okt 2026, klarifikasi setelah 3 soal pertama (commit 97b055c).** Pra-reg belum mengatur ulang saat API gagal. Aturan yang dipakai: soal diulang hanya bila API error/timeout dan **belum ada jawaban sama sekali**; jawaban pertama yang keluar adalah yang dinilai. Semua percobaan tercatat di `attempts.jsonl`. Kasus: t1-003 (percobaan 1 timeout 10 s, percobaan 2 terjawab).
- **Catatan teknis (bukan penyimpangan):** hanya gpt-oss-120b, tanpa cadangan ke 20b, sama seperti E-02 dev. `latency_s` ikut menghitung waktu tunggu pembatas laju Groq, jadi tidak dipakai sebagai latensi sistem (latensi diukur terpisah di E-09).
