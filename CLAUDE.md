# MICA: aturan kerja untuk Claude Code

MICA adalah kiosk informasi PMB Universitas Mikroskil untuk skripsi S-1. Rancangannya ada di `docs/SDD.md` (ekspor dari SDD MICA). Ikuti SDD itu. Bila instruksi bertentangan dengan SDD, berhenti dan tanyakan.

## Cara kerja
- Instruksi dan penjelasan datang dari pengguna, yang menyalinnya dari diskusi di luar terminal. Tugasmu menulis kode, bukan menjelaskan.
- Jangan menulis penjelasan panjang di terminal. Kerjakan langsung, lalu tutup setiap tugas HANYA dengan blok ringkasan ini (Bahasa Indonesia):

```
RINGKASAN
- File dibuat/diubah: ...
- Tes: <perintah> -> <lulus/gagal, jumlah>
- Perlu dijalankan pengguna: <perintah, atau "tidak ada">
- Masalah/pertanyaan: <atau "tidak ada">
```

- Bila ada error yang tidak bisa kamu selesaikan dalam dua percobaan, berhenti dan laporkan error-nya di blok ringkasan.

## Aturan kode
- Python 3.11+, kode di `src/mica/`, tes di `tests/` dengan pytest. Setiap modul baru harus punya tes, dan semua tes harus lulus sebelum tugas dianggap selesai.
- Nama kelas, fungsi, field, dan konfigurasi dalam Bahasa Inggris, sama persis dengan SDD (misalnya `Retriever`, `AnswerPipeline`, `rag.gate.threshold`). Komentar boleh Bahasa Indonesia.
- Komponen yang di SDD berstatus Provisional atau Terbuka wajib berada di balik `Protocol` dan dipilih lewat konfigurasi.
- Jangan mengarang angka ambang. Nilai yang di SDD tertulis TBD dibiarkan `null` di konfigurasi.
- Jangan menambah library di luar yang disebut SDD tanpa bertanya dulu.
- Jalankan pytest dan ruff check sebelum setiap commit. Jangan commit bila ada tes yang gagal.

## Privasi dan rahasia
- Jangan pernah menyimpan frame kamera atau audio mikrofon ke disk di mode kiosk.
- API key hanya di `.env`; jangan tulis ke kode, log, atau commit. `.env` ada di `.gitignore`.
- Gemini hanya boleh dipakai saat `app.mode: dev`. Konfigurasi kiosk tidak boleh memuat penyedia `gemini`.
- Teks pertanyaan harus melewati `scrub_pii` sebelum dikirim ke API atau ditulis ke log.
