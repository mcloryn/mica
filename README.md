# MICA: Mikroskil Intelligent Campus Assistant

Asisten kampus untuk calon mahasiswa Mikroskil. Kamera mendeteksi dan menyapa pengunjung berdasarkan warna bajunya, lalu pengunjung bisa bertanya lewat suara atau teks. Jawaban diambil dari dokumen resmi Mikroskil (RAG) agar tidak mengarang.

## Struktur folder

```
mica/
  config/                nilai yang bisa dikalibrasi (mica.yaml) dan pengaturan ByteTrack
  data/
    raw/                 dokumen asli (PDF, halaman web)
    documents/           dokumen bersih, satu file per topik
    video/               video uji (tidak ikut ke GitHub) dan video_list.csv
    qa_dataset.csv       pertanyaan uji dan jawaban benar
  docs/                  log eksperimen dan protokol pengujian
  results/               hasil evaluasi akhir untuk BAB IV
  scripts/               script untuk menjalankan dan mengevaluasi
    check_setup.py       cek kesiapan laptop
    run_cv.py            jalankan CV di terminal, dengan log (untuk pengujian)
    record_video.py      rekam video uji
    evaluate_color.py    hitung akurasi warna baju
    try_tts.py           coba suara MICA
  src/mica/              kode utama MICA
    config.py            membaca config/mica.yaml
    greeting.py          kalimat sapaan
    chatbot.py           menjawab pertanyaan (nanti RAG)
    vision/              Computer Vision: kamera, deteksi, tracking, warna baju
    speech/              suara: tts.py (teks ke suara), stt.py (ucapan ke teks)
    web/                 aplikasi web kios (Flask): app.py, templates/, static/
  tests/                 uji unit
  .env.example           contoh pengaturan kunci API
  pyproject.toml         menjadikan src/mica paket yang bisa diimpor, plus pengaturan pytest
  requirements.txt       daftar paket Python
```

Nama file, fungsi, dan variabel di kode memakai bahasa Inggris; komentar dan teks untuk pengunjung memakai bahasa Indonesia.

## Hari 1: siapkan laptop

Ikuti urutannya. Kalau ada error, salin pesan error lengkapnya ke thread Claude.

### 1. Install program dasar (sekali saja)

- **Python 3.13** (minimal 3.11): https://www.python.org/downloads/
  Di Windows, centang **"Add python.exe to PATH"** saat instalasi.
- **Git**: https://git-scm.com/downloads (pilih pengaturan default).
- **VS Code**: https://code.visualstudio.com/
  Setelah terbuka, install ekstensi **Python** (dari Microsoft).

Cek di terminal (Windows: buka "Command Prompt" atau terminal di VS Code):

```
python --version
git --version
```

Keduanya harus menampilkan nomor versi.

### 2. Taruh folder `mica` di laptop

Unduh folder ini, lalu buka di VS Code lewat **File > Open Folder**.
Buka terminal di VS Code lewat **Terminal > New Terminal**.

### 3. Buat virtual environment

Virtual environment adalah "ruang khusus" untuk paket Python project ini, supaya tidak bercampur dengan project lain.

```
python -m venv .venv
```

Aktifkan:

- Windows: `.venv\Scripts\activate`
- macOS atau Linux: `source .venv/bin/activate`

Kalau berhasil, di awal baris terminal muncul `(.venv)`. Aktifkan lagi setiap kali membuka terminal baru.

### 4. Install paket

```
pip install -r requirements.txt
pip install -e .
```

Perintah kedua memasang folder `src/mica` sebagai paket, supaya `scripts/`, `web/`, dan `tests/` bisa memakai `import mica` tanpa trik apa pun. Cukup sekali; perubahan kode di `src/mica` langsung terpakai tanpa perlu dipasang ulang.

Setelah berhasil, catat versi persis semua paket supaya hasil skripsi bisa diulang (reproducible):

```
pip freeze --exclude-editable > requirements-lock.txt
```

Ulangi perintah ini setiap kali menambah paket, lalu commit file `requirements-lock.txt`.

### 5. Buat file pengaturan

Salin `.env.example` menjadi `.env` (di folder yang sama). Kunci API boleh dikosongkan dulu, nanti diisi di hari 6.

### 6. Cek semuanya

```
python scripts/check_setup.py
```

Kalau semua baris `[OK]`, hari 1 selesai.

### 7. Simpan ke GitHub

1. Buat akun di https://github.com (gratis).
2. Buat repository baru bernama `mica` (pilih **Private**, jangan centang "Add a README").
3. Di terminal, dari folder `mica`:

```
git init
git add .
git commit -m "Kerangka awal MICA"
git branch -M main
git remote add origin https://github.com/USERNAME-KAMU/mica.git
git push -u origin main
```

Ganti `USERNAME-KAMU` dengan username GitHub-mu.

4. Hubungkan GitHub ke Claude lewat https://claude.ai/connect-github supaya Claude bisa langsung menulis kode ke repo ini.

## Computer Vision: menjalankan dan menguji

Install paket (sekali, cukup lama karena ikut memasang PyTorch):

```
pip install -r requirements.txt
pip freeze --exclude-editable > requirements-lock.txt
```

Jalankan dengan webcam (model `yolo11n-pose.pt` terunduh otomatis saat pertama kali):

```
python scripts/run_cv.py
```

Setiap orang diberi kotak beserta ID-nya; kotak biru muda adalah area baju yang dibaca. Sapaan muncul di terminal. Tekan `q` untuk berhenti.

Untuk video uji, rekam dulu dengan `scripts/record_video.py`, lalu jalankan `python scripts/run_cv.py --source data/video/<nama>.mp4`.

Logika CV ada di satu tempat, `src/mica/vision/pipeline.py`, dan dipakai bersama oleh `scripts/run_cv.py` (untuk pengujian, dengan log) dan aplikasi web (untuk pengunjung). Nilai kalibrasinya dibaca dari `config/mica.yaml`.

## Aplikasi web (kios)

```
python -m mica.web.app                                   # webcam
python -m mica.web.app --source data/video/<nama>.mp4    # video rekaman
python -m mica.web.app --debug                           # video dengan kotak, kerangka badan, dan conf
```

Buka http://127.0.0.1:5000 lalu tekan "Mulai MICA" sekali (browser baru mengizinkan suara setelah layar disentuh). Suara MICA (edge-tts) butuh internet; pengenal ucapan (faster-whisper) berjalan di laptop dan hanya butuh internet saat model diunduh pertama kali.

Uji unit (tidak butuh kamera, internet, atau GPU; uji yang butuh `yolo11n-pose.pt` dilewati jika file itu belum ada):

```
python -m pytest
```

Untuk pengujian skripsi, ikuti `docs/cv-test-protocol.md`.

## Tugas paralel: kumpulkan dokumen (hari 1 sampai 8)

- Taruh PDF dan halaman web Mikroskil di `data/raw/`.
- Lengkapi `data/qa_dataset.csv` sampai minimal 50 pertanyaan:
  - `question`: utamakan pertanyaan asli dari calon mahasiswa atau bagian admisi.
  - `answer` dan `source_document`: diisi dari dokumen resmi, bukan tebakan, lalu minta bagian admisi memeriksanya.
  - `split`: `dev` untuk memperbaiki prompt, `uji` untuk pengujian akhir. Data `uji` tidak boleh dilihat saat memperbaiki sistem.
  - `source`: siapa yang mengajukan pertanyaan (misalnya `calon-mahasiswa`, `admisi`, `penulis`).
  - `category`: topik pertanyaan (misalnya `biaya`, `pendaftaran`, `prodi`).
  Lima baris yang sudah ada hanya contoh buatan penulis; ganti atau tandai asalnya.

## Catatan eksperimen

Setiap kali mencoba sesuatu, tambahkan satu entri di `docs/experiment-log.md`. Log ini menjadi bahan BAB III dan IV.
