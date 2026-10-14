# Protokol uji Computer Vision MICA

Dokumen ini menjelaskan cara menguji bagian CV agar hasilnya sah dan bisa diulang. Rencana pengujian perlu disepakati terlebih dahulu sebelum perekaman dimulai.

## 1. Prinsip

- **Uji pada video rekaman, bukan langsung dari webcam.** Video yang sama bisa dijalankan ulang setiap kali kode atau ambang diubah, sehingga perbandingan adil.
- **Pisahkan data `dev` dan `uji`.** Video `dev` boleh dipakai untuk mengatur ambang warna. Video `uji` hanya dijalankan sekali di akhir, setelah semua pengaturan dikunci.
- **Izin peserta.** Minta persetujuan tertulis setiap orang yang direkam. Simpan video di laptop sendiri, jangan diunggah ke GitHub (folder `logs/` sudah diabaikan Git).

## 2. Skenario rekaman

Rekam di lokasi yang mirip tempat MICA akan dipasang, dengan kamera di posisi akhirnya.

| Faktor | Variasi |
| --- | --- |
| Warna baju | Usahakan setiap warna di `reference_colors` (`config/mica.yaml`) muncul minimal 5 kali |
| Pencahayaan | Terang (siang), redup (sore atau lampu ruangan) |
| Jumlah orang | 1, 2, dan 3 orang dalam frame |
| Jarak | Dekat (sekitar 1 m) dan sedang (sekitar 3 m) |
| Gerakan | Diam di depan kamera, berjalan melintas, saling melewati (menguji ID) |

Rekam dengan `scripts/record_video.py`; script itu otomatis mencatat nama file, bagian (`--split dev`/`uji`), cahaya, warna baju sebenarnya, jumlah orang, dan FPS di `data/video/video_list.csv`. Skenario lain (jarak, gerakan) ditulis di `--note`.

## 3. Yang diukur

| Aspek | Metrik | Cara |
| --- | --- | --- |
| Warna baju | Akurasi, precision, recall, F1 per warna, confusion matrix | Isi `true_label` di `predictions.csv`, lalu `evaluate_color.py` (pembuatan `predictions.csv` belum ada di `run_cv.py`) |
| Deteksi orang | Berapa orang yang disapa dibanding jumlah orang sebenarnya | Hitung baris `greeted` di `events.csv` per video |
| Tracking | Jumlah pergantian ID (ID switch) | Bandingkan jumlah ID unik dengan jumlah orang sebenarnya; selisihnya adalah ID baru yang tidak semestinya |
| Waktu nyata | FPS rata-rata | Baris `fps_rata_rata` di `info.txt`; catat juga spesifikasi laptop |
| Waktu sapa | Detik dari orang muncul sampai disapa | Kolom `time_s` di `events.csv` dibanding waktu orang masuk frame |

## 4. Pelabelan warna

- Label diisi berdasarkan warna baju yang terlihat di video asli, bukan hanya dari gambar potongan.
- Idealnya dua orang melabel secara terpisah. Hitung persentase kesepakatan, lalu diskusikan yang berbeda.
- Baju bermotif atau berwarna campuran diberi label warna yang paling luas, dan dicatat sebagai kasus khusus.

## 5. Menyimpan hasil

Salin `predictions.csv` yang sudah dilabel, `events.csv`, `info.txt`, dan `confusion_matrix_color.png` dari video uji ke folder `results/cv/`, lalu commit. Gambar potongan tidak perlu di-commit.

## 6. Kalibrasi warna

Semua nilai yang bisa dikalibrasi (warna referensi, ambang keyakinan, jumlah frame, area baju) ada di `config/mica.yaml`; parameter ByteTrack ada di `config/bytetrack_mica.yaml`. Nilai yang ada sekarang adalah nilai awal. Setiap run menyimpan salinan kedua file itu di folder `logs/<waktu>/`. Ubah hanya berdasarkan kesalahan pada data `dev`, satu perubahan per percobaan, dan catat setiap percobaan di `docs/experiment-log.md`.
