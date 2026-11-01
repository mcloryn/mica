# MICA

Aplikasi informasi Penerimaan Mahasiswa Baru (PMB) Universitas Mikroskil, dibuat untuk skripsi S-1.
Kamera mendeteksi pengunjung yang mendekat, lalu MICA menyapa. Pengunjung bisa bertanya lewat
suara atau ketikan. Jawaban disusun dengan RAG dari dokumen PMB resmi, lengkap dengan sumbernya.

- Rancangan: [`docs/SDD.md`](docs/SDD.md)
- Pemasangan di laptop PMB: [`docs/INSTALASI.md`](docs/INSTALASI.md)
- Daftar perintah: [`docs/PERINTAH.md`](docs/PERINTAH.md)

## Kebutuhan

- Windows 10/11 dan Microsoft Edge. UI kiosk berjalan di Edge mode kiosk.
- Python 3.11 atau lebih baru.
- Ruang disk sekitar 5 GB: sekitar 2 GB untuk `.venv` dan 2,7 GB untuk model.
- Webcam, mikrofon, dan speaker. Bisa diganti perangkat palsu, lihat bagian "Mencoba tanpa
  perangkat".
- Kunci API Groq.

## Setup

Jalankan dari PowerShell:

```
git clone https://github.com/mcloryn/mica.git
cd mica
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.lock
pip install -e . --no-deps
```

Salin `.env.example` menjadi `.env`, lalu isi kuncinya. File `.env` tidak ikut ter-commit.

```
copy .env.example .env
```

Unduh semua model: YOLO, tabel warna, BGE-M3, faster-whisper, dan suara Piper. Setiap file dicek
revisi atau sha256-nya.

```
python -m mica setup --config config/dev.yaml
```

### Knowledge base

Dokumen sumber (`data/sources/`) dan indeks KB (`data/kb/`) tidak ada di repo, jadi KB perlu
dibangun sendiri dari dokumen PMB:

```
python -m mica.kb init-sources --src data/sources/<folder> --source-type dev --date YYYY-MM-DD
python -m mica.kb build --src data/sources/<folder> --kb-id <id> --source-type dev --config config/dev.yaml
```

Setelah itu isi `kb.active_id` di `config/dev.yaml` dengan `<id>` tadi.

## Menjalankan

```
python -m mica check --config config/dev.yaml     # cek kesiapan; semua baris harus OK
python -m mica --config config/dev.yaml           # mode pengembangan
python -m mica                                    # mode prod (config/prod.yaml)
```

Mode prod baru lolos `check` kalau semua nilai TBD (`null`) di `config/prod.yaml` sudah diisi
dari hasil eksperimen E-01 sampai E-09.

Untuk menutup MICA, tekan Alt+F4 di jendela Edge atau Ctrl+C di PowerShell.

### Mencoba tanpa perangkat

```
python -m mica.webui --config config/dev.yaml --fake-workers --fake-pipeline
```

Perintah ini berjalan tanpa kamera, mikrofon, maupun Groq, dan hanya boleh dipakai di mode dev.

## Konfigurasi

- `config/dev.yaml`: untuk pengembangan. Boleh memakai Gemini dan opsi `--fake-*`.
- `config/prod.yaml`: untuk laptop PMB (mode prod). Tanpa Gemini, dan nilai TBD wajib diisi sebelum dipakai.

## Tes

```
pytest
ruff check .
ruff format --check .
```

## Struktur

```
config/     konfigurasi dev dan prod
data/       dataset evaluasi (data/eval); KB dan sumber dokumen dibuat lokal
docs/       SDD, catatan eksperimen (E-xx), panduan instalasi, tangkapan layar UI
scripts/    skrip pengukuran dan utilitas
src/mica/   kode program
  audio/    mikrofon, VAD, STT (faster-whisper), TTS (Piper)
  vision/   kamera, deteksi orang (YOLO), kehadiran, warna pakaian
  kb/       parser dokumen, chunker, embedder, indeks
  rag/      retriever, gerbang, LLM, prompt, scrub_pii
  core/     controller aplikasi, sesi, bus antarproses, logging
  webui/    UI web (Flask + Edge), UI utama
  ui/       UI PySide6 (cadangan, dibekukan)
  eval/     alat evaluasi E-01 sampai E-09
tests/      tes unit dan integrasi (pytest)
results/    hasil eksperimen
```

## Privasi

- Di mode prod, frame kamera dan audio mikrofon tidak pernah disimpan ke disk.
- Teks pertanyaan disamarkan dengan `scrub_pii` sebelum dikirim ke API atau ditulis ke log.
- Kunci API hanya disimpan di `.env`.

## Catatan istilah

Sejak refactor RF-2 (1 November 2026) MICA adalah web app di satu laptop PMB, bukan kiosk lagi: mode
`kiosk` menjadi `prod`, `config/kiosk.yaml` menjadi `config/prod.yaml`, dan `KioskController` menjadi
`AppController`. Catatan eksperimen dan pra-registrasi di `docs/` (E-xx, UI-WEB, PROMPT-Vx, dan lainnya)
sengaja tetap memakai istilah lama karena menggambarkan kondisi saat itu. Sistem yang diuji di Uji RAG
Tahap 1 tersimpan di tag `tahap1-beku`.
