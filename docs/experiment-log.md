# Log eksperimen MICA

Satu entri per percobaan, terbaru di atas. Catat juga percobaan yang gagal.

## 2026-10-14: uji jalan pertama suara TTS

- **Tujuan:** memastikan MICA bisa mengucapkan sapaan.
- **Pengaturan:** edge-tts 7.3.1, suara `id-ID-GadisNeural`, pygame 2.6.1, `scripts/coba_suara.py` (sekarang `scripts/try_tts.py`).
- **Data:** satu kalimat sapaan contoh (`buat_sapaan("abu-abu")`). Ini hanya uji jalan, bukan data penelitian.
- **Hasil:** suara terdengar. Waktu membuat suara 1,14 detik, lama suara 9,73 detik.
- **Catatan:** butuh internet; edge-tts bukan API resmi Microsoft. `ucapkan()` masih memblokir sampai suara selesai, jadi belum bisa dipanggil langsung dari loop kamera. Integrasi ke `mica_cv.py` (sekarang `scripts/run_cv.py`) dikerjakan di tahap berikutnya.

## 2026-10-14: uji jalan pertama pipeline CV

- **Tujuan:** memastikan deteksi, tracking, warna baju, dan sapaan berjalan dari awal sampai akhir.
- **Pengaturan:** ultralytics 8.4.177, `yolo11n-pose.pt`, ByteTrack bawaan, conf 0.5, frame_minimum 5, CPU server tanpa GPU.
- **Data:** satu gambar contoh Ultralytics (`bus.jpg`) dijadikan video 40 frame dengan sedikit pergeseran. Ini hanya uji jalan, bukan data penelitian.
- **Hasil:** 3 ID tersapa. Jaket hitam terbaca `hitam` (78%) dengan benar. Mantel krem terbaca `oranye` (60%). Orang yang terpotong di tepi frame terbaca `biru` (52%) karena area badannya diambil dari proporsi kotak dan berisi bus di belakangnya. Sekitar 7 FPS di CPU server.
- **Catatan:** cara cadangan (proporsi kotak) dimatikan secara bawaan; area badan sekarang hanya diambil jika kedua bahu terdeteksi. Setelah perubahan ini orang yang terpotong tidak disapa dengan warna yang salah. Warna krem yang terbaca oranye adalah kasus untuk kalibrasi dengan data `dev`.

## Templat

- **Tanggal:**
- **Tujuan:** apa yang ingin diketahui
- **Pengaturan:** model LLM dan versinya, model embedding, ukuran chunk, top-k, model YOLO, model Whisper, dan sebagainya
- **Data:** bagian dataset yang dipakai (`dev` atau `uji`), jumlah pertanyaan atau percobaan
- **Hasil:** angka metrik
- **Catatan:** apa yang aneh, apa yang akan diubah berikutnya
