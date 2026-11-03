# Amandemen pra-registrasi E-05, E-07, E-08, E-09, dan session.idle_reset_s (3 November 2026)

Ditetapkan 3 November 2026, **sebelum data E-05/E-07/E-08/E-09 resmi diambil**. Saat amandemen
ini ditetapkan, belum ada rekaman relawan, frame berlabel, klip, label warna, atau run E-09
resmi. Yang ada hanya pilot dan uji asap (`results/E-05/pilot-dev-*`, `results/E-05/smoke-*`,
`results/E-09/smoke-*`).

Asal dokumen: draf PROD-3 (commit bab870c), diperiksa pemilik proyek, lalu ditetapkan di PROD-4.
Aturan di bawah tidak diubah setelah data ada. Penyimpangan wajib ditulis di hasil dan diungkap
di Bab 3. Bila amandemen ini bertentangan dengan isi docs/E-05.md, E-07.md, E-08.md, atau
E-09.md, yang berlaku adalah amandemen ini. Bagian lain dari protokol itu tetap berlaku.

## Keputusan pemilik proyek (3 November 2026)

1. `audio.vad.min_silence_ms` = **500**, sebagai nilai keputusan desain (tidak di-sweep).
   Sumbernya anggaran deteksi akhir ucapan 0,5 detik di SDD 3.3. Kunci ini tidak berpengaruh
   saat push-to-talk dan hanya dipakai mode `vad`. Nilai 100 ms bawaan Silero tidak dipilih,
   karena bisa memotong jeda di tengah kalimat bila mode `vad` dipakai.
2. Aturan pilih E-05 dibuat berurutan, tanpa ambang angka baru:
   - (a) pilih kombinasi dengan jumlah pertanyaan asli yang tersaring paling sedikit;
   - (b) bila seri, pilih yang transkripsi palsunya paling sedikit pada rekaman diam/bising;
   - (c) bila masih seri, pilih yang paling dekat dengan nilai bawaan library.

   Jumlah pertanyaan asli yang tersaring pada pemenang selalu dilaporkan, berapa pun nilainya.
3. E-07: `vision.presence_signal` **tidak** di-sweep. Nilainya ditetapkan `shoulder_width`
   berdasarkan bukti kalibrasi yang sudah tercatat (amandemen 1 E-07 dan SDD 2.4: tinggi kotak
   tidak memisahkan orang duduk dekat dari orang berdiri 2 m). `min_box_height_ratio` dikeluarkan
   dari grid. Hanya `min_shoulder_ratio` yang di-sweep, sesuai protokol E-07 yang ada, sehingga
   grid tetap 81 kombinasi.
4. `vision.keypoint_torso.min_kp_conf` di-sweep di E-08. Analisis E-08 dijalankan lebih dulu,
   lalu E-07 bagian 2 memakai nilai pemenang E-08.
5. Jarak langkah grid disetujui. Kandidat dipilih pengembang sebelum data dan berpusat pada nilai
   coba. Pilihan ini diungkap di Bab 3.
6. `session.idle_reset_s` memakai Opsi 2 draf: nilai keputusan desain yang diungkap. Setelah uji
   pengguna Tahap 2, jeda antar-giliran di log dicek **sebagai validasi saja**, tanpa mengubah
   nilainya.
7. Alat sweep (filter E-05, grid `mica.eval color`, analisis jeda log) dibuat di langkah terpisah
   PROD-5. Alat itu harus sudah dites dengan data sintetis sebelum data asli dibuka. Replay
   `box_height` tidak diperlukan lagi.

## 1. Kunci suara di mode prod (audio.input_mode = push_to_talk)

### Jalur kode saat push-to-talk

- `config/prod.yaml:45` berisi `input_mode: push_to_talk`.
- Tombol Bicara ditekan, lalu M-09 mengirim `ListenControl("hold")`
  (`src/mica/core/session.py:416`). Permintaan `auto` diubah menjadi `off` bila push-to-talk
  (`src/mica/core/session.py:285-286`). Akibatnya proses suara di prod hanya pernah berada di
  mode `hold` atau `off`.
- Di mode `hold`, setiap potongan mikrofon masuk ke `_hold_chunk` lalu `continue`
  (`src/mica/audio/worker.py:370-371`, `389-406`). `SpeechSegmenter.feed` tidak pernah
  dipanggil.
- Setelah tombol dilepas, `_transcribe_hold` menjalankan `push_to_talk_utterance`, lalu
  `is_too_short`, lalu STT (`src/mica/audio/worker.py:467-487`).
- `ListenMode` `push_to_talk` (VAD menangkap satu ucapan) hanya dipakai demo CLI
  (`src/mica/audio/__main__.py:416`), bukan oleh M-09.

### Pengaruh tiap kunci

| Kunci | Berpengaruh saat push-to-talk? | Bukti |
| --- | --- | --- |
| `audio.vad.threshold` | **Ya.** Menentukan ada tidaknya ucapan (`no_voice`: STT tidak dipanggil) dan memangkas hening di awal/akhir | `src/mica/audio/vad.py:83-89`, `src/mica/audio/worker.py:473-477` |
| `audio.vad.min_speech_ms` | **Ya.** Ucapan yang bagian bicaranya lebih pendek dibuang sebelum STT (`min_speech`) | `src/mica/audio/vad.py:63-66`, `src/mica/audio/worker.py:478-479` |
| `audio.stt.no_speech_threshold` | **Ya.** Bila semua segmen Whisper punya `no_speech_prob` ≥ nilai ini, hasilnya tersaring (`no_speech`) | `src/mica/audio/stt.py:65-70`, `148`; dipasang di `src/mica/audio/worker.py:216-217` |
| `audio.max_utterance_s` | **Ya.** Batas lama tombol ditahan; bila tercapai, rekaman dikirim otomatis (`cut_by_max`) | `src/mica/audio/worker.py:292`, `399-402` |
| `audio.vad.min_silence_ms` | **Tidak.** Hanya dipakai `SpeechSegmenter` (akhir ucapan karena diam), dan segmenter tidak diberi audio di mode `hold`. Akhir ucapan ditentukan tombol | `src/mica/audio/vad.py:7`, `77-79`, `117`; `src/mica/audio/worker.py:370-372`; docs/E-05.md amandemen 1 |

`min_silence_ms` tetap wajib diisi, karena worker menolak mulai bila salah satu `VAD_KEYS` null
(`src/mica/audio/worker.py:69`, `137-147`).

### `audio.vad.min_silence_ms`: nilai keputusan desain 500

Kunci ini tidak di-sweep (keputusan 1). Nilai 500 bersumber dari anggaran deteksi akhir ucapan
0,5 detik (SDD 3.3) dan sama dengan nilai coba SDD 12. Nilai ini hanya bermakna di mode `vad`.

Pembanding yang tidak dipilih:

- 100: bawaan `min_silence_duration_ms` Silero
  (https://github.com/snakers4/silero-vad/blob/master/src/silero_vad/utils_vad.py). Ditolak
  karena berisiko memotong jeda di tengah kalimat di mode `vad`.
- 2000: bawaan `VadOptions` faster-whisper 1.2.1
  (`.venv/Lib/site-packages/faster_whisper/vad.py:41`). VAD ini dimatikan di MICA
  (`vad_filter=False`, `src/mica/audio/stt.py:143`).

## 2. Aturan per kunci

**Kandidat grid (berlaku untuk semua bagian).**

- Kandidat dipilih pengembang sebelum data dan berpusat pada nilai coba sekarang.
- Jarak antar-nilai adalah pilihan desain, bukan hasil ukur. Hal ini diungkap di Bab 3
  (keputusan 5).
- "Paling dekat dengan nilai pusat" berarti jumlah jarak langkah grid terkecil, dihitung untuk
  semua kunci yang di-sweep.

### A. E-05: penyaring suara push-to-talk

**Kunci.** `audio.vad.threshold`, `audio.vad.min_speech_ms`, `audio.stt.no_speech_threshold`,
`audio.max_utterance_s`.

**Urutan.**

- Backend STT tetap dipilih dulu dengan aturan SDD 2.4, menggunakan nilai coba. Aturan itu tidak
  berubah.
- Sweep ini dijalankan pada backend pemenang. Backend Groq juga memakai `no_speech_threshold`
  (`src/mica/audio/stt.py:194`, `227`).

**Data.** Manifest E-05 yang sama (`pertanyaan`, `diam`, `bising`), tanpa rekaman tambahan.
Setiap rekaman diperlakukan sebagai satu kali tombol ditahan (amandemen 1 E-05).

#### A1. `vad.threshold`, `vad.min_speech_ms`, `stt.no_speech_threshold` (sweep bersama)

| Kunci | Kandidat | Nilai pusat (sumber bawaan library) |
| --- | --- | --- |
| `vad.threshold` | 0,3; **0,5**; 0,7 | 0,5: bawaan `threshold` Silero (`utils_vad.py`, tautan di atas) dan `faster_whisper/vad.py:37` |
| `vad.min_speech_ms` | 0; **250**; 500 | 250: bawaan `min_speech_duration_ms` Silero (`utils_vad.py`). 0 = penyaring mati (bawaan faster-whisper, `faster_whisper/vad.py:39`) |
| `stt.no_speech_threshold` | 0,4; **0,6**; 0,8 | 0,6: bawaan Whisper (https://github.com/openai/whisper/blob/main/whisper/transcribe.py) dan faster-whisper (`faster_whisper/transcribe.py:276`) |

Ada 3 × 3 × 3 = **27 kombinasi**. STT dijalankan 3 kali per rekaman, satu kali untuk setiap
`vad.threshold`, karena nilai threshold mengubah audio yang dipangkas. `min_speech_ms` dan
`no_speech_threshold` diterapkan setelahnya pada `speech_s` VAD dan `no_speech_prob` segmen yang
sudah dihitung.

**Metrik per kombinasi.**

- (a) Pertanyaan asli tersaring: jumlah rekaman `pertanyaan` dengan `filtered_by` ≠ null
  (`no_voice`, `min_speech`, atau `no_speech`).
- (b) Transkripsi palsu pada rekaman `diam` + `bising`, dengan definisi amandemen 1 E-05.
- WER, CER, dan Recall@5 hanya dilaporkan, tidak menentukan pilihan. WER dihitung atas semua
  `pertanyaan`; pertanyaan yang tersaring dihitung sebagai hipotesis kosong.

**Aturan pilih (keputusan 2, mekanis, tanpa ambang angka).**

1. Pilih (a) paling sedikit.
2. Seri: pilih (b) paling sedikit.
3. Seri: pilih yang paling dekat dengan bawaan library (0,5; 250; 0,6).
4. Masih seri (jaraknya sama): pilih yang menyaring lebih sedikit, yaitu `vad.threshold` lebih
   kecil, lalu `min_speech_ms` lebih kecil, lalu `no_speech_threshold` lebih besar. Langkah ini
   hanya pemecah seri mekanis supaya hasilnya tunggal, bukan ambang baru.

Laporan wajib: nilai (a) pada pemenang, berapa pun nilainya, beserta (b), WER, CER, dan Recall@5.

**Bila data kurang.** Bila tidak ada rekaman `diam`/`bising`, (b) bernilai 0 di semua kombinasi
dan aturan berlanjut ke langkah 3. Hal ini diungkap.

#### A2. `audio.max_utterance_s`

| Kandidat | Sumber |
| --- | --- |
| **15** | Nilai coba SDD 12 (tanpa sumber) |
| 20 | Langkah antara (pilihan pengembang) |
| 30 | Panjang jendela Whisper 30 detik (`CHUNK_LENGTH = 30`, https://github.com/openai/whisper/blob/main/whisper/audio.py; `faster_whisper/feature_extractor.py:10`) |

- **Metrik:** jumlah rekaman `pertanyaan` yang durasinya melebihi kandidat, yaitu yang akan
  terpotong `cut_by_max`. Hanya butuh durasi WAV, tanpa STT.
- **Aturan pilih:** pilih jumlah terpotong paling sedikit. Seri: pilih yang paling dekat dengan
  15. Seri: pilih yang lebih besar.
- **Laporan wajib:** jumlah terpotong pada pemenang.
- **Bila data kurang:** bila durasi rekaman tidak mewakili lama tombol ditahan (misalnya rekaman
  dipotong manual), pakai 15 sebagai nilai keputusan desain dan ungkapkan.

### B. E-07: kehadiran

**Kunci.**

- `vision.presence_signal` = **`shoulder_width`**: nilai keputusan desain, tidak di-sweep
  (keputusan 3).
- `vision.min_box_height_ratio`: tidak di-sweep dan tetap null. `mica check` tidak mewajibkannya
  bila sinyalnya `shoulder_width` (`src/mica/config.py:455-456`).
- `vision.min_shoulder_ratio`, `vision.dwell_s`, `vision.leave_s`, dan
  `session.regreet_cooldown_s` di-sweep dengan grid dan aturan E-07 bagian 2 yang ada, tanpa
  perubahan: **81 kombinasi**.

**Perubahan pada E-07 bagian 2.** Kalimat "`keypoint_torso.min_kp_conf` = 0,5 (nilai coba SDD
bagian 12) tetap untuk semua kombinasi" diganti menjadi: `keypoint_torso.min_kp_conf` = nilai
pemenang E-08 tahap 2a (bagian C) untuk semua kombinasi. Bila tahap 2a tidak dijalankan atau
`min_kp_conf` tidak di-sweep (bagian C, "bila data kurang"), nilainya tetap 0,5.

**Urutan (keputusan 4).** E-07 bagian 1 (deteksi, `vision.conf`) dijalankan, lalu E-08 sampai
tahap 2a, lalu E-07 bagian 2. Bagian 1 harus lebih dulu, karena E-08 memakai `vision.conf` hasil
bagian 1.

### C. E-08: parameter area baju

**Kunci.** `vision.box_upper.top`, `.bottom`, `.side`; `vision.keypoint_torso.min_kp_conf`,
`.shrink`, `.torso_aspect`.

**Data.** Offline, atas frame berlabel yang sama: E-07 (a), `colors.csv`, dan
`colors_rater2.csv`, hanya pasangan yang disepakati kedua penilai. Deteksi `yolo26n-pose`
dijalankan sekali per frame dan dipakai ulang oleh semua kombinasi.

**Kandidat.** Nilai pusat adalah nilai coba SDD 12 (`src/mica/trial.py:26-31`, tanpa sumber
eksperimen).

| Kunci | Kandidat |
| --- | --- |
| `box_upper.top` | 0,30; **0,35**; 0,40 |
| `box_upper.bottom` | 0,60; **0,65**; 0,70 |
| `box_upper.side` | 0,20; **0,25**; 0,30 |
| `keypoint_torso.min_kp_conf` | 0,3; **0,5**; 0,7 |
| `keypoint_torso.shrink` | 0,10; **0,15**; 0,20 |
| `keypoint_torso.torso_aspect` | 1,0; **1,2**; 1,4 |

**Urutan.**

1. **Tahap 1** E-08 tidak berubah: 4 kombinasi region × metode pada nilai pusat. Tahap ini
   memilih `vision.region` dan `vision.color.method`.
2. **Tahap 2a**, hanya bila region pemenang `keypoint_torso`: sweep `min_kp_conf` × `shrink` ×
   `torso_aspect` (27 kombinasi), dengan `box_upper` pada nilai pusat.
3. **Tahap 2b**: sweep `top` × `bottom` × `side` (27 kombinasi), dengan parameter keypoint dari
   tahap 2a (atau nilai pusat bila region `box_upper`). Pada `keypoint_torso`, tahap ini hanya
   mengubah item cadangan (`fallback`).
4. **Tahap 3**: sweep `min_majority` (E-08 aturan 2) pada parameter akhir.

Bila region pemenang `box_upper`, tahap 2a tidak dijalankan. Akibatnya `min_kp_conf` = 0,5
(dipakai sinyal bahu E-07), sedangkan `shrink` dan `torso_aspect` tidak dipakai di prod.

**Metrik.** Sama dengan E-08: macro-F1, akurasi, akurasi per warna, dan confusion matrix, dengan
prediksi tahap 1 (`ColorResult.top`, tanpa `min_majority`).

**Aturan pilih (tahap 2a dan 2b).**

1. Macro-F1 tertinggi.
2. Seri: akurasi lebih tinggi.
3. Seri: paling dekat dengan nilai pusat.
4. Seri: nilai lebih kecil, menurut urutan kunci di tabel.

**Bila data kurang.** Item dihitung menurut sumber area (`keypoint`, `keypoint+box`,
`fallback`; `src/mica/vision/region.py:3-8`).

- `shrink` hanya memengaruhi `keypoint`.
- `torso_aspect` hanya memengaruhi `keypoint+box`.
- `box_upper.*` hanya memengaruhi `fallback` atau region `box_upper`.

Bila sumber yang dipengaruhi suatu kunci punya 0 item di **semua** kombinasi tahap itu, kunci itu
tidak di-sweep. Nilai pusat dipakai sebagai nilai keputusan desain dan diungkap.

### D. E-09: `audio.tts.threads`

**Kunci.** `audio.tts.threads`, ditambahkan ke grid kalibrasi E-09.

**Kandidat.** {1, 2}.

- 1: pemenang CPU-THREADS tahap 1 di laptop dev (docs/CPU-THREADS.md).
- 2: nilai berikutnya di deret CPU-THREADS, sama dengan batas atas grid `vision.threads` {1, 2}
  E-09.
- Tidak dimasukkan:
  - 4 thread atau lebih: laptop PMB belum diketahui (SDD 2.3), sementara proses vision dan STT
    ikut berebut CPU.
  - null: CPU-THREADS menunjukkan bawaan onnxruntime merebut CPU 755-1333%.
- Laptop dev: i9-12900H, 14 inti fisik, 20 inti logis.

**Grid.** `vision.fps_busy` {1, 2, 5} × `vision.threads` {1, 2} × `audio.stt.threads` {2, 4} ×
`audio.tts.threads` {1, 2} = **24 kombinasi**.

**Aturan pilih.** Aturan E-09 tidak berubah. Pemecah seri terakhir ditambahkan:
`audio.tts.threads` lebih kecil.

**Bila data kurang.**

- Bila E-05 memilih `groq_whisper`, `audio.stt.threads` dikunci null dan grid menjadi
  12 kombinasi.
- Bila tidak ada kombinasi yang lulus, berlaku aturan E-09 yang lama.

### E. `session.idle_reset_s`: nilai keputusan desain (keputusan 6)

**Fungsi.** `IdleTimeout` mereset sesi bila tidak ada interaksi selama `idle_reset_s`
(`src/mica/core/session.py:361-367`). Kepergian normal ditangani `PersonLeft`. Timeout ini jaring
pengaman, misalnya saat kamera mati atau baru restart (SDD 7.1, paragraf restart proses pekerja).

**Nilai.** Nilai keputusan desain pemilik proyek, tidak di-sweep, dan diungkap di Bab 3 sebagai
bukan hasil ukur.

idle_reset_s = 120 detik (nilai keputusan desain pemilik proyek, 3 November 2026, ditetapkan
sebelum log uji Tahap 2 dibuka). Dasar: sesi normal sudah berakhir lewat PersonLeft +
vision.leave_s, jadi idle_reset_s hanya jaring pengaman ketika kamera tidak melihat pengunjung
pergi. Nilainya harus cukup panjang untuk membaca jawaban dan mengetik pertanyaan berikutnya
(kecepatan baca senyap orang dewasa rata-rata sekitar 238 kata per menit, Brysbaert 2019, Journal
of Memory and Language 109:104047, sehingga jawaban 100 kata dibaca sekitar 25 detik), tetapi
cukup pendek supaya percakapan pengunjung sebelumnya tidak lama tampil untuk pengunjung berikutnya
(privasi). Log uji Tahap 2 hanya dipakai untuk validasi: jeda antar-giliran terpanjang
dilaporkan, dan nilainya tidak diubah.

**Validasi setelah uji pengguna Tahap 2.** Validasi ini tidak mengubah nilai.

- Data: `logs/turns-*.jsonl`.
- Untuk setiap `session_id` dengan ≥ 2 giliran, hitung jeda = `ts` giliran ke-(i+1) dikurangi
  `ts` giliran ke-i. Angka ini batas atas jeda pikir pengunjung, karena masih memuat waktu proses
  giliran berikutnya.
- Dilaporkan: jumlah sesi, jumlah jeda, p50, p95, maksimum, dan jumlah jeda yang lebih panjang
  dari `idle_reset_s`, yaitu yang akan mereset sesi.
- Bila ada jeda yang lebih panjang, hal itu dilaporkan sebagai keterbatasan. Nilai tidak diubah.
- Keterbatasan: peserta uji mengikuti skenario tugas, sehingga jedanya bisa berbeda dari
  pengunjung PMB asli.

## 3. Jumlah kombinasi dan perkiraan waktu (laptop dev)

Jumlah data masih TBD (pembimbing). Contoh N di bawah hanya ilustrasi ukuran waktu, bukan usulan
jumlah data.

| Sweep | Kombinasi | Kerja berat | Waktu satuan (sumber) | Contoh |
| --- | --- | --- | --- | --- |
| E-05 A1 | 27 | STT 3 kali per rekaman | stt_s rata-rata 1,86 s per rekaman 3,3 s (pilot `results/E-05/pilot-dev-20261017-143739/wer.csv`, n = 10) | 140 rekaman, sekitar 13 menit |
| E-05 A2 | 3 | Durasi WAV saja | - | hitungan detik |
| E-07 bagian 2 | 81 (grid lama) | YOLO sekali per frame klip pada 5 fps, lalu replay grid | 45,9 ms per gambar, median imgsz 640 (docs/IMGSZ-HASIL.md 7.2) | 20 menit klip, sekitar 5 menit YOLO; replay belum diukur |
| E-08 | 4 + 27 + 27 + 3 = 61 (`keypoint_torso`) atau 4 + 27 + 3 = 34 (`box_upper`) | YOLO sekali per frame, lalu crop + LUT per kombinasi | 45,9 ms per gambar | 300 frame, sekitar 15 detik YOLO; crop + LUT belum diukur |
| E-09 | 24 (12 bila `groq_whisper`) | Sesi nyata, satu proses MICA per kombinasi | p95 total giliran 7,63 s (docs/FOLLOWUP.md, n = 133) | 10 pertanyaan × sekitar 30 s per giliran, sekitar 2 jam ditambah mulai ulang |
| `session.idle_reset_s` | 0 | Validasi log saja | - | hitungan detik |

## 4. Alat yang dibuat di PROD-5 (keputusan 7)

Semua alat harus dites dengan data sintetis sebelum data asli dibuka.

1. **Filter E-05:**
   - STT sekali per `vad.threshold`;
   - penerapan `min_speech_ms` dan `no_speech_threshold` setelah STT untuk 27 kombinasi;
   - hitungan (a) dan (b);
   - aturan pilih A1;
   - hitungan terpotong A2 untuk `max_utterance_s`.
2. **Grid `mica.eval color`:** tahap 2a dan 2b dengan parameter area dari grid (saat ini tetap,
   `src/mica/eval/color.py:40-44`), aturan pilih bagian C, dan hitungan item per sumber area.
3. **Analisis jeda log:** validasi `session.idle_reset_s` (bagian E).

Tidak diperlukan:

- replay `box_height`;
- perubahan alat E-07, karena `vision-scenarios` sudah menerima `--min-kp-conf`
  (`src/mica/eval/__main__.py:223`).
