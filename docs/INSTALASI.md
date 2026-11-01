# Memasang MICA di laptop PMB

Urutan di bawah dijalankan sekali di laptop PMB (Windows, Python 3.11 atau lebih baru), dari
PowerShell. Perintah yang mengunduh hanya `pip install` dan `python -m mica setup`; saat aplikasi
berjalan MICA tidak mengunduh apa pun.

1. Ambil kode:

   ```
   git clone <url repo MICA> mica
   cd mica
   ```

2. Buat lingkungan Python dan pasang dependensi dengan versi terkunci:

   ```
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.lock
   pip install -e . --no-deps
   ```

3. Buat file `.env` di folder `mica` berisi satu baris kunci Groq. Kuncinya diminta dari
   pengembang; jangan dikirim lewat chat atau ditulis di file lain:

   ```
   GROQ_API_KEY=<kunci dari pengembang>
   ```

   `.env` tidak ikut ke git dan nilainya tidak pernah dicetak oleh MICA.

4. Unduh semua model (YOLO, tabel warna, BGE-M3, faster-whisper, suara Piper). Setiap file
   dicek sha256 atau revisinya; file yang sudah ada dan cocok dilewati:

   ```
   python -m mica setup
   ```

   Bila ada baris `gagal`, jalankan ulang komponennya saja, mis. `python -m mica setup --only BGE-M3`.

5. Periksa kesiapan. Kamera tidak dibuka, mikrofon dan speaker hanya didaftar, Groq tidak
   dipanggil:

   ```
   python -m mica check
   ```

   Semua baris harus `OK` (atau `INFO`). Baris `GAGAL` menjelaskan apa yang harus diperbaiki,
   misalnya kunci config yang belum diisi atau file model yang hilang.

6. Jalankan aplikasi:

   ```
   python -m mica
   ```

   MICA menjalankan `check` lagi; bila ada `GAGAL`, UI tidak dibuka dan tabelnya dicetak.

   MICA menjalankan server lokal di 127.0.0.1 lalu membuka alamatnya di browser default
   laptop dalam jendela biasa. Alamatnya juga dicetak di PowerShell; bila browser tidak
   terbuka sendiri, salin alamat itu ke browser.

   Untuk menutup MICA, tekan Ctrl+C di PowerShell. Server serta proses kamera dan suara
   berhenti dengan rapi. Menutup tab atau jendela browser TIDAK mematikan MICA; buka lagi
   alamatnya untuk kembali ke UI.

Catatan:

- Browser apa pun yang modern cukup (Microsoft Edge bawaan Windows 10/11 sudah memadai).
  `check` tidak lagi memeriksa browser.

- Tanpa argumen, ketiga perintah memakai `config/prod.yaml`. Untuk mode pengembangan pakai
  `--config config/dev.yaml`.
- `config/prod.yaml` baru lolos `check` setelah semua nilai TBD diisi dari hasil eksperimen
  (E-01 sampai E-09). `check` mencetak daftar kunci yang masih kosong.

## Waktu mulai (Langkah 40, 18 Okt 2026)

Saat MICA dimulai, UI web tampil lebih dulu. Kamera, suara, dan mesin jawaban (pipeline RAG)
menyusul di latar.

- Sampai status pertama proses kamera/suara datang, layar menulis "Menyiapkan kamera..." dan
  "Menyiapkan mikrofon..."; tombol Bicara nonaktif selama mikrofon disiapkan.
- Kotak ketik langsung aktif. Pertanyaan yang dikirim sebelum pipeline siap langsung tampil,
  status menjadi "Menyiapkan jawaban...", lalu dijawab begitu pipeline siap.
- Sapaan kamera tidak menunggu pipeline.
- Bila pipeline gagal dimuat (mis. KB rusak), aplikasi tetap berjalan. Setiap pertanyaan dijawab
  dengan teks penolakan baku ("Maaf, layanan sedang tidak tersedia..."), dan galatnya dicatat
  sebagai `LLM_UNAVAILABLE`.
- Pipeline dirakit di thread latar proses utama, bukan di proses terpisah. Pipeline tetap satu
  objek yang dipanggil controller seperti sebelumnya, tanpa IPC. Model, pustaka, versi, dan hasil
  retrieval tidak berubah; hanya waktunya yang dipindah.

Setiap start mencatat waktu tiap tahap (monotonic, sama untuk semua proses) ke
`logs/startup-<tanggal>.jsonl`. Isinya hanya nama proses, nama tahap, dan waktu; tidak ada
gambar, audio, atau teks pengunjung.

Ukur: `powershell -ExecutionPolicy Bypass -File scripts\l40_startup.ps1 -Label <nama>`. Perintah
ini memakai config dev + nilai coba SDD bagian 12, kamera dan suara asli, 1 pemanasan + 5
ulangan, dan wajib AC. Hasilnya di `results/STARTUP/`.

Hasil resmi "sebelum" (kode a6c731c, pipeline dirakit sebelum server;
results/STARTUP/20261018-223108-sebelum; laptop dev; detik sejak perintah, median (min-maks)):

| tonggak | sebelum | sesudah (92bc754) | dingin |
| --- | --- | --- | --- |
| UI tampil | 14,27 (14,13-14,32) | belum diukur resmi | belum diukur |
| pipeline siap | 13,13 (12,98-13,17) | belum diukur resmi | belum diukur |
| kamera siap (dilihat proses utama) | 13,14 (12,99-13,18) | belum diukur resmi | belum diukur |
| kamera siap (proses kamera, deteksi pertama) | 6,35 (6,22-6,40) | belum diukur resmi | belum diukur |
| suara siap (dilihat proses utama) | 13,14 (12,99-13,18) | belum diukur resmi | belum diukur |
| suara siap (proses suara, speaker terbuka) | 6,28 (6,21-6,43) | belum diukur resmi | belum diukur |
| semua siap | 14,27 (14,13-14,32) | belum diukur resmi | belum diukur |

- Sebelum perbaikan, proses utama baru membaca status pekerja setelah server berjalan. Karena
  itu "kamera/suara siap (dilihat proses utama)" sama dengan waktu server, padahal pekerjanya
  sudah siap di ±6,3 s.
- Penyebab terbesar: proses utama merakit pipeline 11,58 s SEBELUM server dan Edge dimulai.
  Rinciannya: import torch 1,24 s, import sentence_transformers 4,40 s, muat BGE-M3 5,55 s.
- Kamera (import torch 1,38 s, inferensi pemanasan 1,52 s, buka DSHOW 1,01 s) dan suara (muat
  Piper 2,20 s, muat Whisper 1,08 s) sudah berjalan paralel dan selesai lebih dulu.
- Uji alat TIDAK RESMI dengan kamera dan suara palsu (results/STARTUP/tidak-resmi-kamera-palsu,
  1 ulangan, tidak sebanding dengan tabel di atas): UI tampil 25,45 s sebelum perbaikan vs
  2,51 s sesudah. Pipeline siap 16,03 s di latar sesudah perbaikan.
- Angka ±210 s pada cek laju kamera Langkah 38 tidak terulang. Kemungkinan penyebabnya memori
  sempit atau mulai dingin; ini belum diukur.

Tidak diubah, dengan alasan:

- Backend kamera (DSHOW) dan resolusi/FOURCC: buka kamera 1,01 s, paralel, bukan penghambat.
- Import/muat model di proses kamera dan suara: sudah paralel dan selesai sebelum pipeline.
- Model, pustaka, dan versinya.
- Kontak ke Hugging Face Hub saat memuat BGE-M3 (peringatan "unauthenticated requests"): ini
  perilaku jaringan, dan sekarang berjalan di latar.
