# Memasang MICA di laptop kiosk

Urutan di bawah dijalankan sekali di laptop kiosk (Windows, Python 3.11 atau lebih baru), dari
PowerShell. Perintah yang mengunduh hanya `pip install` dan `python -m mica setup`; saat kiosk
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

6. Jalankan kiosk:

   ```
   python -m mica
   ```

   MICA menjalankan `check` lagi; bila ada `GAGAL`, jendela tidak dibuka dan tabelnya dicetak.

Catatan:

- Tanpa argumen, ketiga perintah memakai `config/kiosk.yaml`. Untuk mode pengembangan pakai
  `--config config/dev.yaml`.
- `config/kiosk.yaml` baru lolos `check` setelah semua nilai TBD diisi dari hasil eksperimen
  (E-01 sampai E-09). `check` mencetak daftar kunci yang masih kosong.
