# MICA: Mikroskil Intelligent Campus Assistant

MICA adalah asisten kampus berbasis kios untuk calon mahasiswa Mikroskil. Sistem mendeteksi pengunjung melalui kamera, mengenali warna pakaian pengunjung, lalu menyapanya dengan suara. Pengunjung kemudian dapat mengajukan pertanyaan melalui ketikan atau ucapan. Jawaban direncanakan bersumber dari dokumen resmi Mikroskil dengan pendekatan *Retrieval-Augmented Generation* (RAG) agar informasi yang diberikan dapat dipertanggungjawabkan.

## Komponen Sistem

| Komponen | Teknologi | Status |
| --- | --- | --- |
| Deteksi dan pelacakan orang | YOLO11 Pose dan ByteTrack (Ultralytics) | Berjalan |
| Pengenalan warna pakaian | Ruang warna CIELAB, jarak CIE76, pemungutan suara antar-frame | Berjalan |
| Sintesis suara (TTS) | edge-tts | Berjalan |
| Pengenalan ucapan (STT) | faster-whisper | Berjalan |
| Antarmuka kios | Flask, HTML, CSS, JavaScript | Berjalan |
| Penjawab pertanyaan | RAG dengan LLM | Dalam pengembangan |

## Struktur Direktori

```
mica/
  config/                parameter yang dapat dikalibrasi (mica.yaml) dan konfigurasi ByteTrack
  data/
    raw/                 dokumen sumber (PDF, halaman web)
    documents/           dokumen yang telah dibersihkan, satu berkas per topik
    video/               video uji (tidak disimpan di repositori) dan video_list.csv
    qa_dataset.csv       dataset pertanyaan dan jawaban acuan
  docs/                  log eksperimen dan protokol pengujian
  results/               hasil evaluasi akhir
  scripts/               skrip untuk menjalankan dan mengevaluasi sistem
    check_setup.py       pemeriksaan kesiapan lingkungan kerja
    run_cv.py            menjalankan modul Computer Vision dengan pencatatan log
    record_video.py      merekam video uji
    evaluate_color.py    menghitung akurasi pengenalan warna pakaian
    try_tts.py           mencoba sintesis suara
  src/mica/              kode sumber utama
    config.py            pembaca berkas konfigurasi
    greeting.py          penyusun kalimat sapaan
    chatbot.py           penjawab pertanyaan
    vision/              deteksi, pelacakan, dan pengenalan warna pakaian
    speech/              tts.py (teks ke suara) dan stt.py (ucapan ke teks)
    web/                 aplikasi web kios: app.py, templates/, static/
  tests/                 pengujian unit
  .env.example           contoh pengaturan kunci API
  pyproject.toml         definisi paket dan konfigurasi pytest
  requirements.txt       daftar dependensi
  requirements-lock.txt  versi pasti seluruh dependensi
```

## Persyaratan

- Python 3.13 (minimal 3.11)
- Git
- Webcam, mikrofon, dan pengeras suara untuk penggunaan kios
- Koneksi internet untuk sintesis suara dan untuk mengunduh model pada penggunaan pertama

## Instalasi

1. Unduh repositori:

   ```
   git clone https://github.com/mcloryn/mica.git
   cd mica
   ```

2. Buat dan aktifkan *virtual environment*:

   ```
   python -m venv .venv
   ```

   - Windows: `.venv\Scripts\activate`
   - macOS atau Linux: `source .venv/bin/activate`

3. Pasang dependensi dan paket `mica`:

   ```
   pip install -r requirements.txt
   pip install -e .
   ```

   Perintah kedua memasang `src/mica` sebagai paket dalam mode *editable*, sehingga skrip dan pengujian dapat mengimpor `mica` secara langsung, dan perubahan kode langsung berlaku tanpa pemasangan ulang. Pemasangan pertama memerlukan waktu cukup lama karena turut memasang PyTorch.

4. Salin `.env.example` menjadi `.env`. Kunci API dapat dikosongkan hingga modul penjawab pertanyaan digunakan.

5. Periksa kesiapan lingkungan kerja:

   ```
   python scripts/check_setup.py
   ```

   Lingkungan siap digunakan apabila seluruh baris menampilkan `[OK]`.

## Penggunaan

Seluruh perintah dijalankan dari direktori utama proyek dengan *virtual environment* dalam keadaan aktif.

### Aplikasi kios

```
python -m mica.web.app                                   # menggunakan webcam
python -m mica.web.app --source data/video/<nama>.mp4    # menggunakan video rekaman
python -m mica.web.app --debug                           # menampilkan kotak deteksi, kerangka tubuh, dan skor keyakinan
```

Buka http://127.0.0.1:5000 pada peramban, kemudian tekan tombol **Mulai MICA** satu kali. Langkah ini diperlukan karena peramban hanya mengizinkan pemutaran suara setelah terdapat interaksi pengguna. Model pengenalan ucapan berjalan secara lokal dan hanya memerlukan internet saat diunduh pertama kali.

### Modul Computer Vision

```
python scripts/run_cv.py                                        # menggunakan webcam
python scripts/run_cv.py --source data/video/<nama>.mp4         # menggunakan video rekaman
python scripts/run_cv.py --source data/video/<nama>.mp4 --no-display
```

Model `yolo11n-pose.pt` diunduh secara otomatis pada penggunaan pertama. Setiap orang yang terdeteksi ditandai dengan kotak dan ID; kotak biru muda menunjukkan area pakaian yang dibaca warnanya. Tekan `q` untuk berhenti. Setiap eksekusi menghasilkan direktori `logs/<waktu>/` yang berisi:

- `events.csv`: waktu setiap orang terlihat (`seen`), disapa (`greeted`), dan meninggalkan area (`left`)
- `info.txt`: sumber video, jumlah frame, dan rata-rata FPS
- salinan `mica.yaml` dan `bytetrack_mica.yaml` yang digunakan pada eksekusi tersebut

Logika Computer Vision terpusat pada `src/mica/vision/pipeline.py` dan digunakan bersama oleh `scripts/run_cv.py` serta aplikasi kios.

### Perekaman video uji

```
python scripts/record_video.py --shirt putih --light terang --split dev
```

Video disimpan di `data/video/` dan keterangannya dicatat di `data/video/video_list.csv`. Video tidak disimpan di repositori karena memuat wajah relawan.

## Pengujian

Pengujian unit tidak memerlukan kamera, internet, maupun GPU. Pengujian yang memerlukan `yolo11n-pose.pt` akan dilewati apabila berkas tersebut belum tersedia.

```
python -m pytest
```

Prosedur pengujian Computer Vision dijelaskan pada `docs/cv-test-protocol.md`.

## Dataset

Dokumen sumber Mikroskil (PDF dan halaman web) disimpan di `data/raw/`, sedangkan versi yang telah dibersihkan disimpan di `data/documents/`.

`data/qa_dataset.csv` ditargetkan berisi minimal 50 pertanyaan dengan kolom berikut:

| Kolom | Keterangan |
| --- | --- |
| `id` | Nomor urut pertanyaan |
| `split` | `dev` untuk penyempurnaan sistem, `uji` untuk pengujian akhir. Data `uji` tidak boleh digunakan selama penyempurnaan sistem. |
| `source` | Pihak yang mengajukan pertanyaan, misalnya `calon-mahasiswa`, `admisi`, atau `penulis` (pengembang) |
| `category` | Topik pertanyaan, misalnya `biaya`, `pendaftaran`, atau `prodi` |
| `question` | Pertanyaan; diutamakan pertanyaan asli dari calon mahasiswa atau bagian admisi |
| `answer` | Jawaban acuan yang bersumber dari dokumen resmi dan telah diverifikasi oleh bagian admisi |
| `source_document` | Dokumen sumber jawaban |

Lima baris yang tersedia saat ini merupakan contoh awal dan perlu diganti dengan pertanyaan asli atau ditandai asalnya.

## Reproduksibilitas

- Versi pasti seluruh dependensi dicatat di `requirements-lock.txt`. Setiap kali dependensi ditambahkan, perbarui berkas tersebut dengan perintah berikut, lalu lakukan *commit*:

  ```
  pip freeze --exclude-editable > requirements-lock.txt
  ```

- Seluruh parameter yang dapat dikalibrasi berada di `config/mica.yaml` dan `config/bytetrack_mica.yaml`, dan salinannya disimpan pada setiap eksekusi `run_cv.py`.
- Setiap percobaan, termasuk percobaan yang gagal, dicatat di `docs/experiment-log.md`.

## Konvensi Kode

Nama berkas, fungsi, variabel, dan kunci konfigurasi menggunakan bahasa Inggris. Komentar, dokumentasi, dan teks yang ditampilkan kepada pengunjung menggunakan bahasa Indonesia.
