DRAF, BELUM BERLAKU

# AMANDEMEN-DRAF: usulan amandemen pra-registrasi E-05, E-07, E-08, E-09, dan session.idle_reset_s (PROD-3)

Disusun 3 November 2026, sebelum ada data relawan untuk E-05, E-07, E-08, maupun E-09. Dokumen
ini hanya **usulan**. Belum ada aturan yang berlaku, dan docs/E-0x.md, config, kode, serta
docs/SDD.md tidak diubah. Setelah diperiksa pemilik proyek, isi yang disetujui disalin sebagai
amandemen bertanggal ke docs/E-0x.md masing-masing, lalu di-commit **sebelum** data dibuka.

Prinsip yang dipakai di semua bagian:

- Data sama dengan protokol asli. Tidak ada sesi rekam tambahan.
- Grid kecil (paling banyak 4 nilai per kunci) berpusat pada nilai coba sekarang. Sumber nilai
  coba disebut. Jarak antar-nilai grid adalah **pilihan desain draf ini, bukan hasil ukur**, dan
  diungkap di Bab 3.
- Pemecah seri memilih nilai yang paling dekat dengan nilai coba atau bawaan library. Jarak
  diukur dalam langkah grid, dijumlahkan untuk semua kunci.
- Bila datanya kurang, nilai tidak dipilih dari data. Nilai coba dipakai sebagai nilai keputusan
  desain dan diungkap.

## Langkah 1: kunci suara di mode prod (audio.input_mode = push_to_talk)

### Jalur kode saat push-to-talk

- `config/prod.yaml:45`: `input_mode: push_to_talk`.
- Tombol Bicara ditekan, lalu M-09 mengirim `ListenControl("hold")` (`src/mica/core/session.py:416`).
  Permintaan `auto` diubah menjadi `off` bila push-to-talk (`src/mica/core/session.py:285-286`).
  Jadi proses suara di prod hanya pernah berada di mode `hold` atau `off`.
- Mode `hold`: setiap potongan mikrofon masuk ke `_hold_chunk` dan langsung `continue`
  (`src/mica/audio/worker.py:370-371`, `389-406`). `SpeechSegmenter.feed` tidak pernah dipanggil.
- Setelah tombol dilepas: `_transcribe_hold` memanggil `push_to_talk_utterance`, lalu
  `is_too_short`, lalu STT (`src/mica/audio/worker.py:467-487`).
- `ListenMode` `push_to_talk` (VAD menangkap satu ucapan) hanya dipakai demo CLI
  (`src/mica/audio/__main__.py:416`), bukan oleh M-09.

### Pengaruh tiap kunci

| Kunci | Berpengaruh saat push-to-talk? | Bukti |
| --- | --- | --- |
| `audio.vad.threshold` | **Ya**. Menentukan ada-tidaknya ucapan (`no_voice` berarti STT tidak dipanggil) dan titik pangkas hening awal/akhir | `src/mica/audio/vad.py:83-89`, `src/mica/audio/worker.py:473-477` |
| `audio.vad.min_speech_ms` | **Ya**. Ucapan yang bagian bicaranya lebih pendek dibuang sebelum STT (`min_speech`) | `src/mica/audio/vad.py:63-66`, `src/mica/audio/worker.py:478-479` |
| `audio.stt.no_speech_threshold` | **Ya**. Bila semua segmen Whisper punya `no_speech_prob` ≥ nilai ini, hasilnya tersaring (`no_speech`) | `src/mica/audio/stt.py:65-70`, `148`; dipasang di `src/mica/audio/worker.py:216-217` |
| `audio.max_utterance_s` | **Ya**. Batas lama tombol ditahan; bila tercapai, rekaman dikirim otomatis (`cut_by_max`) | `src/mica/audio/worker.py:292`, `399-402` |
| `audio.vad.min_silence_ms` | **Tidak**. Hanya dipakai `SpeechSegmenter` (akhir ucapan karena diam), dan segmenter tidak diberi audio di mode `hold`. Akhir ucapan ditentukan tombol | `src/mica/audio/vad.py:7`, `77-79`, `117`; `src/mica/audio/worker.py:370-372`; docs/E-05.md amandemen 1 |

Catatan: `min_silence_ms` tetap wajib diisi, karena worker menolak mulai bila salah satu
`VAD_KEYS` null (`src/mica/audio/worker.py:69`, `137-147`). Segmenter juga tetap dibuat
(`src/mica/audio/worker.py:294-299`) dan `mica check` tetap menghitung kunci ini.

### Usulan untuk kunci yang tidak berpengaruh: `audio.vad.min_silence_ms`

Kunci ini tidak di-sweep. Nilai usulan: **100**, sebagai **nilai keputusan desain**.

- Sumber: bawaan `min_silence_duration_ms = 100` pada `get_speech_timestamps` dan `VADIterator`
  di Silero VAD, https://github.com/snakers4/silero-vad/blob/master/src/silero_vad/utils_vad.py.
  MICA memakai model Silero (pysilero-vad 3.4.0). Padding `PAD_MS = 30` juga sudah diambil dari
  file yang sama (`src/mica/audio/vad.py:25-27`), jadi sumbernya konsisten.
- Nilai ini hanya bermakna di mode `vad` (perbandingan), bukan di prod.
- Pembanding yang juga punya sumber (pemilik proyek memilih satu):
  - 500: nilai coba SDD 12, dari anggaran deteksi akhir ucapan 0,5 detik (SDD 3.3). Anggaran
    itu tidak berlaku di push-to-talk (SDD 3.3, docs/E-05.md amandemen 1).
  - 2000: bawaan `VadOptions.min_silence_duration_ms` faster-whisper 1.2.1
    (`.venv/Lib/site-packages/faster_whisper/vad.py:41`). Ini VAD milik faster-whisper, yang di
    MICA dimatikan (`vad_filter=False`, `src/mica/audio/stt.py:143`).

## Langkah 2: usulan per kunci

### A. E-05: penyaring suara push-to-talk

**Kunci.** `audio.vad.threshold`, `audio.vad.min_speech_ms`, `audio.stt.no_speech_threshold`,
`audio.max_utterance_s`.

**Eksperimen.** E-05, setelah backend STT dipilih dengan aturan SDD 2.4 (aturan itu tidak berubah
dan tetap dijalankan dengan nilai coba). Sweep ini dijalankan pada backend pemenang. Bila
pemenangnya `groq_whisper`, sweep tetap berlaku karena backend Groq juga memakai
`no_speech_threshold` (`src/mica/audio/stt.py:194`, `227`).

**Data.** Manifest E-05 yang sama (`pertanyaan`, `diam`, `bising`). Tidak ada rekaman baru.
Setiap rekaman diperlakukan sebagai satu kali tombol ditahan (amandemen 1).

#### A1. `vad.threshold`, `vad.min_speech_ms`, `stt.no_speech_threshold` (sweep bersama)

| Kunci | Kandidat | Nilai pusat (sumber) |
| --- | --- | --- |
| `vad.threshold` | 0,3; **0,5**; 0,7 | 0,5: bawaan `threshold` Silero (`utils_vad.py`, tautan di atas) dan `faster_whisper/vad.py:37` |
| `vad.min_speech_ms` | 0; **250**; 500 | 250: bawaan `min_speech_duration_ms` Silero (`utils_vad.py`). 0: bawaan faster-whisper (`faster_whisper/vad.py:39`), berarti penyaring mati |
| `stt.no_speech_threshold` | 0,4; **0,6**; 0,8 | 0,6: bawaan `no_speech_threshold` Whisper (https://github.com/openai/whisper/blob/main/whisper/transcribe.py) dan faster-whisper (`faster_whisper/transcribe.py:276`) |

Langkahnya ±0,2 dan ±250 ms (pilihan desain). Grid ini 3 × 3 × 3 = **27 kombinasi**. STT
dijalankan hanya **3 kali per rekaman** (satu per `vad.threshold`), karena threshold mengubah
audio yang dipangkas. `min_speech_ms` dan `no_speech_threshold` diterapkan setelahnya pada
`speech_s` VAD dan `no_speech_prob` segmen yang sudah dihitung.

**Metrik per kombinasi.**

- (a) Pertanyaan tersaring: jumlah rekaman `pertanyaan` dengan `filtered_by` ≠ null
  (`no_voice`, `min_speech`, atau `no_speech`).
- (b) Laju transkripsi palsu pada `diam` + `bising`, dengan definisi amandemen 1.
- (c) WER total atas semua `pertanyaan` (normalisasi E-05). Pertanyaan yang tersaring dihitung
  sebagai hipotesis kosong.
- CER dan Recall@5 dilaporkan, tetapi tidak menentukan pilihan.

**Aturan pilih.**

1. Lolos bila (a) = 0, yaitu tidak ada pertanyaan asli yang dibuang.
2. Dari yang lolos, pilih (b) terkecil.
3. Seri: pilih (c) terkecil.
4. Masih seri: pilih jarak langkah grid terkecil ke (0,5; 250; 0,6).
5. Masih seri: pilih yang menyaring lebih sedikit, yaitu `vad.threshold` lebih kecil, lalu
   `min_speech_ms` lebih kecil, lalu `no_speech_threshold` lebih besar.
6. Tidak ada yang lolos: pilih (a) terkecil, lalu langkah 2 sampai 5. Hasil ini ditandai "tidak
   memenuhi syarat 1" dan menjadi item pembimbing.

**Bila data kurang.**

- Tidak ada rekaman `diam`/`bising`: (b) tidak bisa diukur, sehingga ketiga kunci memakai nilai
  pusat (0,5; 250; 0,6) sebagai nilai keputusan desain bersumber library, dan ini diungkap.
- Semua kombinasi sama di (a), (b), dan (c): langkah 4 memilih nilai pusat.

#### A2. `audio.max_utterance_s`

| Kandidat | Sumber |
| --- | --- |
| **15** | Nilai coba SDD 12 (tanpa sumber) |
| 20 | Langkah antara (pilihan desain) |
| 30 | Panjang jendela Whisper 30 detik (`CHUNK_LENGTH = 30`, https://github.com/openai/whisper/blob/main/whisper/audio.py; `faster_whisper/feature_extractor.py:10`). Ucapan yang lebih panjang dipecah oleh Whisper |

- **Metrik:** jumlah rekaman `pertanyaan` yang durasinya melebihi kandidat (akan terpotong
  `cut_by_max`). Hanya dibutuhkan durasi WAV, tanpa STT.
- **Aturan pilih:** lolos bila jumlahnya 0. Dari yang lolos, pilih yang paling dekat dengan 15.
  Seri: pilih yang lebih besar.
- **Tidak ada yang lolos:** pilih 30, laporkan jumlah yang terpotong, dan jadikan item
  pembimbing.
- **Bila data kurang:** tanpa rekaman `pertanyaan`, E-05 memang tidak berjalan. Bila durasi
  rekaman tidak mewakili lama tombol ditahan (misalnya rekaman dipotong manual), pakai 15 sebagai
  nilai keputusan desain dan ungkapkan.

### B. E-07: `vision.presence_signal` dan ambangnya

**Kunci.** `vision.presence_signal` ∈ {`shoulder_width`, `box_height`},
`vision.min_shoulder_ratio`, `vision.min_box_height_ratio`.

**Eksperimen.** E-07 bagian 2 (skenario sapaan). Usulan ini menggantikan paragraf amandemen 1
yang berbunyi "grid `min_box_height_ratio` tidak diperlukan". Model tetap `yolo26n-pose`
(amandemen 1). Sinyal `box_height` memakai kotak dari model yang sama, sehingga deteksi dan
pelacakan tidak perlu diulang.

**Data.** Klip skenario E-07 (b) dan anotasinya, sama dengan protokol asli. Kandidat
`min_box_height_ratio` diturunkan dari frame E-07 (a) dengan aturan di bawah. Tidak ada data baru.

**Kandidat.**

- `shoulder_width`: grid E-07 bagian 2 tidak berubah, yaitu `min_shoulder_ratio` {0,18; 0,22;
  0,26}. Nilai 0,22 adalah nilai coba hasil kalibrasi dev 16 Okt (SDD 7.3: duduk sekitar 0,29,
  berdiri 2 m sekitar 0,16-0,19).
- `box_height`: belum ada nilai coba yang bersumber. Kandidatnya **diturunkan secara mekanis**
  supaya setara jarak dengan grid bahu:
  - Dari frame E-07 (a), ambil pasangan kotak label dan deteksi (IoU ≥ 0,5) yang kedua bahunya
    yakin (conf ≥ `min_kp_conf`).
  - Untuk setiap pasangan, hitung r = (tinggi box / tinggi frame) / (lebar bahu / lebar frame).
  - Kandidat `min_box_height_ratio` = median(r) × {0,18; 0,22; 0,26}, dibulatkan ke 0,01.
  - Kandidat dihitung dan ditulis ke `run.json` **sebelum** klip skenario dibuka.
- Grid: (1 sinyal × 3 rasio) × `dwell_s` {1, 2, 3} × `leave_s` {2, 3, 5} × `regreet_cooldown_s`
  {0, 30, 60}, untuk tiap sinyal. Jadi 81 + 81 = **162 kombinasi**.

**Metrik.** Sama dengan E-07 bagian 2: sapaan benar, terlewat, salah, dan ganda, serta p95 waktu
sapaan.

**Aturan pilih.**

- Langkah 1, 2, dan 4 E-07 bagian 2 berlaku apa adanya untuk ke-162 kombinasi.
- Langkah 3 (seri) diberi satu pemecah di depan: **`shoulder_width` didahulukan** (nilai
  amandemen 1). Bila masih seri, berlaku urutan lama: `dwell_s` lebih besar, `regreet_cooldown_s`
  lebih besar, `leave_s` lebih besar, lalu rasio lebih besar.
- Untuk `box_height`, pemecah "rasio lebih besar" diganti dengan "paling dekat dengan
  median(r) × 0,22".

**Bila data kurang.**

- Tidak ada pasangan dengan bahu yakin di E-07 (a): kandidat `box_height` tidak bisa diturunkan.
  Sinyal itu tidak di-sweep, `presence_signal` = `shoulder_width`, dan ini diungkap.
- Bila `shoulder_width` terpilih, `min_box_height_ratio` tetap null. `mica check` tidak
  mewajibkannya untuk sinyal itu (`src/mica/config.py:455-456`).

**Alat.** `replay` saat ini hanya untuk sinyal bahu (`src/mica/eval/vision_scenarios.py:176-180`).
Dukungan `box_height` dan penurunan median(r) harus dibuat dan dites sebelum klip dibuka. Ini di
luar PROD-3.

### C. E-08: parameter area baju

**Kunci.** `vision.box_upper.top`, `.bottom`, `.side`; `vision.keypoint_torso.min_kp_conf`,
`.shrink`, `.torso_aspect`.

**Eksperimen.** E-08, offline, atas frame berlabel yang sama (E-07 (a), `colors.csv` dan
`colors_rater2.csv`, hanya pasangan yang disepakati kedua penilai). Deteksi `yolo26n-pose`
dijalankan sekali per frame dan dipakai ulang oleh semua kombinasi.

**Kandidat.** Nilai pusat adalah nilai coba SDD 12 (`src/mica/trial.py:26-31`), tanpa sumber
eksperimen. Langkahnya pilihan desain.

| Kunci | Kandidat |
| --- | --- |
| `box_upper.top` | 0,30; **0,35**; 0,40 |
| `box_upper.bottom` | 0,60; **0,65**; 0,70 |
| `box_upper.side` | 0,20; **0,25**; 0,30 |
| `keypoint_torso.min_kp_conf` | 0,3; **0,5**; 0,7 |
| `keypoint_torso.shrink` | 0,10; **0,15**; 0,20 |
| `keypoint_torso.torso_aspect` | 1,0; **1,2**; 1,4 |

**Urutan.**

1. **Tahap 1** E-08 tidak berubah: 4 kombinasi region × metode pada nilai pusat, untuk memilih
   `vision.region` dan `vision.color.method`.
2. **Tahap 2a**, hanya bila region pemenang `keypoint_torso`: sweep `min_kp_conf` × `shrink` ×
   `torso_aspect` (27 kombinasi), dengan `box_upper` pada nilai pusat.
3. **Tahap 2b**: sweep `top` × `bottom` × `side` (27 kombinasi), dengan parameter keypoint dari
   2a (atau nilai pusat bila region `box_upper`). Pada `keypoint_torso`, tahap ini hanya mengubah
   item yang jatuh ke cadangan (`fallback`).
4. **Tahap 3**: sweep `min_majority` (E-08 aturan 2) pada parameter akhir.

**Metrik.** Sama dengan E-08: macro-F1, akurasi, akurasi per warna, dan confusion matrix,
dengan prediksi tahap 1 (`ColorResult.top`, tanpa `min_majority`).

**Aturan pilih (tahap 2a dan 2b).**

1. Macro-F1 tertinggi.
2. Seri: akurasi lebih tinggi.
3. Seri: jarak langkah grid terkecil ke nilai pusat.
4. Seri: nilai lebih kecil, menurut urutan kunci di tabel.

**Bila data kurang.** Di setiap tahap, hitung item menurut sumber area (`keypoint`,
`keypoint+box`, `fallback`; `src/mica/vision/region.py:3-8`).

- `shrink` hanya memengaruhi `keypoint`, `torso_aspect` hanya `keypoint+box`, dan `box_upper.*`
  hanya `fallback` atau region `box_upper`.
- Bila sumber yang dipengaruhi suatu kunci punya 0 item pada **semua** kombinasi tahap itu, kunci
  itu tidak di-sweep. Nilai pusat dipakai sebagai nilai keputusan desain dan diungkap.

**Hubungan dengan E-07.** `keypoint_torso.min_kp_conf` juga dipakai sinyal `shoulder_width`.
E-07 bagian 2 saat ini mengunci 0,5. Usulan:

- Tahap 2a E-08 dijalankan **sebelum** E-07 bagian 2. Frame E-07 (a) memang tersedia lebih dulu
  daripada klip.
- E-07 bagian 2 memakai `min_kp_conf` hasil E-08 sebagai pengganti 0,5. Kalimat itu ikut diubah
  di amandemen E-07.
- Alternatif: `min_kp_conf` tidak di-sweep dan tetap 0,5 untuk keduanya.

**Alat.** `mica.eval color` saat ini memakai parameter area tetap (`src/mica/eval/color.py:40-44`).
Opsi grid harus dibuat dan dites sebelum label warna dibuka. Ini di luar PROD-3.

### D. E-09: `audio.tts.threads`

**Kunci.** `audio.tts.threads`, ditambahkan ke grid kalibrasi E-09.

**Kandidat.** {1, 2}.

- 1: pemenang CPU-THREADS tahap 1 di laptop dev (docs/CPU-THREADS.md; intra_op 1, CPU proses
  suara saat menyusun turun dari 819% ke 36%).
- 2: nilai berikutnya di deret pangkat dua CPU-THREADS ({1, 2, 4}). Nilai ini sama dengan batas
  atas grid `vision.threads` {1, 2} yang sudah dipra-registrasi di E-09.
- Laptop dev punya 14 inti fisik dan 20 logis (i9-12900H). Laptop PMB belum diketahui, dan SDD 2.3
  hanya mengasumsikan CPU x86-64 tanpa GPU. Dengan proses vision dan STT yang ikut berebut CPU,
  4 atau lebih thread tidak diusulkan.
- null (bawaan onnxruntime) tidak dimasukkan, karena CPU-THREADS menunjukkan null merebut CPU
  755-1333%.

**Data.** Sesi kalibrasi E-09 yang sama. Kunci ini cukup menjadi faktor tambahan di grid.

**Grid.** `vision.fps_busy` {1, 2, 5} × `vision.threads` {1, 2} × `audio.stt.threads` {2, 4} ×
`audio.tts.threads` {1, 2} = **24 kombinasi** (sebelumnya 12).

**Aturan pilih.** Aturan E-09 tidak berubah (lulus semua aturan, p95 `total` terendah, seri
berarti CPU rata-rata lebih rendah). Pemecah terakhir ditambahkan: `audio.tts.threads` lebih
kecil (lebih dekat ke nilai dev 1).

**Bila data kurang.**

- Bila E-05 memilih `groq_whisper`, `audio.stt.threads` tidak bermakna. Faktor itu dikunci pada
  null dan grid menjadi 12 kombinasi. Ini sudah tercatat di docs/PROD-TBD.md bagian 6.
- Bila tidak ada kombinasi yang lulus, berlaku aturan E-09 yang lama (optimasi dulu).

### E. `session.idle_reset_s`

**Fungsi.** `IdleTimeout` mereset sesi bila tidak ada interaksi selama `idle_reset_s`
(`src/mica/core/session.py:361-367`). Kepergian normal ditangani `PersonLeft`. Timeout ini
adalah jaring pengaman, misalnya saat kamera mati atau baru restart (SDD 7.1, paragraf restart
proses pekerja).

**Opsi 1 (usulan): diukur saat uji pengguna.**

- **Data:** log giliran (`logs/turns-*.jsonl`) dari sesi uji pengguna (SUS) yang sudah
  direncanakan. Selama uji, `idle_reset_s` = null (tidak pernah timeout), supaya jeda tidak
  terpotong.
- **Metrik:** untuk setiap `session_id` dengan ≥ 2 giliran, hitung jeda = `ts` giliran ke-(i+1)
  dikurangi `ts` giliran ke-i. Angka ini batas atas jeda pikir pengunjung, karena masih memuat
  waktu proses giliran berikutnya. Akibatnya nilainya condong ke timeout yang lebih panjang,
  artinya lebih jarang memotong pengunjung.
- **Aturan:** `idle_reset_s` = jeda terlama yang teramati, dibulatkan ke atas ke detik bulat.
  Tidak ada margin tambahan, karena margin akan menjadi angka karangan. Jumlah sesi, jumlah jeda,
  serta p50/p95/maksimum dilaporkan.
- **Bila data kurang:** tidak ada sesi dengan ≥ 2 giliran, maka pakai Opsi 2.
- **Keterbatasan:** peserta uji mengikuti skenario tugas, sehingga jedanya bisa berbeda dari
  pengunjung PMB asli. Log pengunjung asli baru ada setelah MICA dipakai di ruang PMB, setelah
  config prod dibekukan.
- **Alat:** perintah analisis jeda belum ada. Perintah itu harus dibuat dan dites sebelum uji
  pengguna. Ini di luar PROD-3.

**Opsi 2: nilai keputusan desain + diungkap.** Pemilik proyek menetapkan satu nilai dan
menuliskan alasannya, lalu nilai itu diungkap di Bab 3 sebagai bukan hasil ukur. Alasannya sah
karena timeout ini hanya cadangan untuk `PersonLeft`, sehingga kesalahannya kecil: nilai terlalu
panjang hanya membuat layar sesi lama bertahan, sedangkan nilai terlalu pendek mereset pengunjung
yang sedang berpikir. Draf ini tidak mengusulkan angka, karena belum ada sumber.

## Langkah 3: jumlah kombinasi dan perkiraan waktu (laptop dev)

Laptop dev: i9-12900H, 14 inti fisik dan 20 logis. Waktu satuan diambil dari run yang sudah ada.
Jumlah data E-05, E-07, E-08, dan E-09 masih TBD (pembimbing), jadi waktu ditulis sebagai rumus.
Contoh N di bawah **hanya ilustrasi untuk ukuran waktu**, bukan usulan jumlah data.

| Sweep | Kombinasi | Kerja berat | Waktu satuan (sumber) | Rumus waktu | Contoh |
| --- | --- | --- | --- | --- | --- |
| E-05 A1 | 27 | STT 3× per rekaman | stt_s rata-rata 1,86 s per rekaman 3,3 s (pilot `results/E-05/pilot-dev-20261017-143739/wer.csv`, n = 10) | 3 × N_rekaman × ~1,9 s (+ VAD, kecil) | 140 rekaman → ~13 menit |
| E-05 A2 | 3 | Durasi WAV saja | - | detik | - |
| E-07 B | 162 (sebelumnya 81) | YOLO sekali per frame klip pada 5 fps, lalu replay grid di memori | 45,9 ms per gambar, median, imgsz 640 (docs/IMGSZ-HASIL.md 7.2) | detik_klip × 5 × ~0,05 s + 162 × replay | 20 menit klip → ~5 menit YOLO. Replay belum diukur (logika Python murni; perkiraan detik sampai beberapa menit) |
| E-08 C | 4 + 27 + 27 + 3 = 61 (region `keypoint_torso`) atau 4 + 27 + 3 = 34 (`box_upper`) | YOLO sekali per frame, lalu crop + LUT per kombinasi | 45,9 ms per gambar (sama) | N_frame × ~0,05 s + 61 × N_item × (crop + LUT) | 300 frame → ~15 s YOLO. Crop + LUT belum diukur (perkiraan menit) |
| E-09 D | 24 (sebelumnya 12; 12 bila `groq_whisper`) | Sesi nyata dengan orang. Satu proses MICA per kombinasi | p95 total giliran 7,63 s (docs/FOLLOWUP.md, n = 133). Waktu bicara dan dengar belum diukur | 24 × (mulai ulang + N_pertanyaan × waktu giliran) | 10 pertanyaan × ~30 s per giliran → ~5 menit per kombinasi → ~2 jam + mulai ulang |
| idle_reset_s E | 0 (tanpa sweep) | Analisis log | - | detik | - |

## Butuh keputusan pemilik proyek

1. `audio.vad.min_silence_ms`: pakai 100 (Silero, usulan), 500 (anggaran SDD 3.3), atau 2000
   (faster-whisper)?
2. E-05 A1, syarat 1: setuju "tidak ada pertanyaan asli yang tersaring" menjadi syarat lolos,
   dengan transkripsi palsu sebagai kriteria kedua?
3. E-07: setuju menurunkan kandidat `min_box_height_ratio` dari median(r) frame E-07 (a)? Ingat,
   amandemen 1 menulis bahwa tinggi kotak tidak memisahkan orang duduk dekat dari orang berdiri
   2 m.
4. `min_kp_conf`: di-sweep di E-08 lalu dipakai E-07, atau dikunci 0,5 untuk keduanya?
5. Jarak langkah grid (±0,05 pada `box_upper`, ±0,2 pada threshold, dan seterusnya) adalah
   pilihan desain draf ini. Perlu disetujui atau diganti.
6. `session.idle_reset_s`: Opsi 1 (diukur saat uji pengguna) atau Opsi 2 (nilai desain)?
7. Pengembangan alat (replay `box_height`, grid `mica.eval color`, filter E-05 setelah STT,
   analisis jeda log) harus dibuat dan dites sebelum data dibuka. Setuju dikerjakan sebagai
   langkah terpisah?
