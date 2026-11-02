# PREVIEW-24FPS: pratinjau kamera 24 fps (CV-3)

Status: **HASIL** (CV-3; CV-3b di bagian 7; uji kemampuan CV-3c di bagian 8), 2 Nov 2026, branch `cv/imgsz` (worktree `D:\SKRIPSI\mica-cv`). Target 24 fps
untuk pratinjau di browser berasal dari dosen pembimbing. Ini **nilai coba**, bukan hasil
eksperimen. Laju deteksi YOLO (`vision.fps_idle` 5, `vision.fps_busy` null) dan `vision.imgsz`
640 (keputusan final CV-2) tidak diubah. Kode dan config RAG juga tidak diubah.

## 1. Diagnosis (kode sebelum CV-3, commit `c7a918f`)

| Pertanyaan | Jawaban | Lokasi |
|---|---|---|
| Di proses mana kamera dibaca | Proses anak vision (multiprocessing spawn), di loop tunggal `VisionLoop.run` | `src/mica/core/bus.py:165`; `src/mica/vision/worker.py:452-505` |
| Apakah pembacaan frame menunggu YOLO | **Ya.** Urutan satu iterasi: `camera.read()`, lalu `_detect()` (`detect_and_track`, sinkron, bila jatah deteksi tiba), lalu `_publish_preview()`. Selama inferensi, kamera tidak dibaca dan pratinjau tidak dikirim. | `worker.py:462`, `worker.py:492` → `worker.py:383`, `worker.py:498` |
| Bagaimana frame sampai ke browser | Gambar dikecilkan ke lebar 320 px (INTER_AREA) dan dicerminkan, lalu di-pixelate (mode public) atau diberi overlay (debug), lalu di-JPEG q70 di memori. Hasilnya masuk `put_latest` ke `Queue(maxsize=1)` (frame lama dibuang). Thread pompa membawanya ke WebSocket `/preview` (biner), dan browser mengubahnya menjadi blob → `<img>`. | `livepreview.py:87-95, 111, 144, 154`; `bus.py:130`; `server.py:230`, `app.py:165`; `static/app.js:113-118` |
| Di mana `preview_fps` membatasi | `next_preview += 1/preview_fps`. JPEG hanya dibuat dari frame yang sudah dibaca loop, jadi laju pratinjau ≤ min(preview_fps, laju baca loop). | `worker.py:497-501` |
| fps asli webcam | Logi C270 lewat DSHOW, 640×480 YUY2. `CAP_PROP_FPS` = **−1** (driver tidak melapor). Terukur tanpa YOLO (10 detik, 150 frame): **15,0 fps**, median jarak antar-frame 64 ms. Setelah `CAP_PROP_FPS`=30 atau MJPG diminta, tetap 15,0 fps. Exposure otomatis terbaca −4 (2⁻⁴ s ≈ 62,5 ms). Dengan exposure manual −5 (≈ 31 ms), kamera mencapai **29,8 fps**. | Skrip diagnosis di luar repo (frame langsung dibuang) |

Kesimpulan diagnosis: ada dua batas. (1) Kamera hanya memberi 15 fps pada pencahayaan ruangan
saat itu, karena exposure otomatis sekitar 62,5 ms per frame. Batas ini fisik, bukan kode.
(2) Pembacaan kamera dan pratinjau berbagi loop dengan YOLO, sehingga setiap inferensi yang
lambat langsung menahan pratinjau.

## 2. Perubahan kode (karena median A < 24)

Pola frame terbaru di `src/mica/vision/worker.py`, tanpa library baru:

- `VisionLoop(..., threaded=True)` dipakai proses vision asli (`run_vision_worker`, `worker.py:678`).
- Thread pembaca `_grab_loop` (`worker.py:554`) membaca kamera secepat driver memberi frame dan
  menyimpan **hanya frame terbaru** di slot (`threading.Condition`), jadi frame lama dibuang. Thread
  yang sama mengirim pratinjau pada `ui.preview_fps` (`_maybe_preview`, `worker.py:480`) dengan
  **hasil deteksi terakhir** (`self.last`) sebagai overlay atau kotak target.
- Loop utama `_run_threaded` (`worker.py:588`) mengambil frame terbaru dari slot, menjalankan YOLO
  pada laju `fps_idle`/`fps_busy` (`_detect_if_due`, `worker.py:504`, tidak berubah), dan tetap
  mengurus inbox, CameraStatus, jeda TTS, serta jendela dev OpenCV (dengan salinan frame).
- Error di thread pembaca dinaikkan ulang di loop utama, jadi perilaku restart pekerja (SDD 8.1)
  tetap sama. Saat berhenti, thread dihentikan dulu, lalu kamera dilepas.
- `threaded=False` (bawaan) adalah loop tunggal lama. Mode ini dipakai tes dengan jam palsu dan
  `scripts/camera_rate.py`.
- Frame tetap hanya di memori (N-08); tidak ada yang ditulis ke disk.
- Tes baru: `tests/unit/test_worker_threaded.py` (5 tes). Isinya: pratinjau tidak tertahan
  detektor lambat (0,25 s per deteksi), pembanding loop tunggal yang tertahan, YOLO memakai
  frame terbaru dan membuang yang lama, error kamera diteruskan, dan CameraStatus terkirim.

Config: `ui.preview_fps` di `config/dev.yaml` = **24** (nilai coba CV-3; sebelumnya 15).
`config/prod.yaml` tetap 10. Tiga tes yang mengunci nilai dev 15 disesuaikan ke 24
(dua di `tests/unit/test_livepreview.py`, satu di `tests/unit/test_config.py`).

## 3. Cara ukur

- Perintah (A dan B sama, hanya kodenya berbeda):
  `PYTHONPATH=src python -m mica.webui --config config/dev.yaml --trial-values --port 5001 --no-browser --measure-preview --measure-label CV3-A|CV3-B`
- Pengguna membuka `http://127.0.0.1:5001/` di browser dan berdiri di depan kamera.
- Alat ukur sudah ada sebelumnya (`--measure-preview`, `src/mica/eval/preview_meter.py`); tidak
  ada penghitung baru. Per detik tercatat: `capture_fps` (frame dibaca loop kamera),
  `preview_put_fps`, `server_sent_fps`, `browser_drawn_fps` (event `load` `<img>` yang
  dilaporkan `app.js`), `detect_ms` (median dan jumlah deteksi per detik), serta CPU% per proses
  dan total mesin (psutil). Hanya angka yang disimpan, tanpa frame, JPEG, atau foto.
- Data: `results/preview-fps/20261102-132204/` (A) dan `results/preview-fps/20261102-133003/` (B),
  masing-masing `summary.json` dan `live-*.jsonl`.
- Jendela analisis: 60 detik berturut-turut dengan `browser_drawn_fps` > 0, dimulai dari detik
  kedua setelah browser tersambung (detik pertama dibuang). Statistik dihitung per detik: median,
  p5, p95.
- Kondisi: `ui.camera_preview` debug (config dev), `vision.threads` 7, charger terpasang, mode daya
  Windows **Best power efficiency** (overlay AC `961cc777-…`, skema "ASUS Recommended"). Status
  sesi MELAYANI (pengguna terdeteksi dan disapa). Pipeline RAG gagal dimuat karena `.env`
  (GROQ_API_KEY) tidak ada di worktree. Ini tidak memengaruhi kamera atau pratinjau, dan tidak
  ada pertanyaan yang diajukan.

## 4. Hasil

| | Pengukuran A (kode lama), 13:23:59-13:25:00 | Pengukuran B (thread pembaca), 13:34:33-13:35:35 |
|---|---|---|
| fps tampilan browser, median [p5; p95] | **1,0** [0,9; 10,9] | **14,9** [14,5; 15,6] |
| fps dikirim server, median [p5; p95] | 1,0 [0,9; 14,9] | 14,9 [14,5; 15,6] |
| fps baca kamera, median [p5; p95] | 1,5 [0,9; 15,5] (n = 46) | 14,9 [14,9; 15,2] |
| Deteksi YOLO per detik, median [p5; p95] | 2,0 [1,0; 5,75] (n = 46) | 5,0 [5,0; 6,0] |
| Waktu satu deteksi, median dari median per detik (ms) | 680 [96; 1050] | 103 [95; 120] |
| Jeda maksimum antar-gambar di browser per detik, median (ms) | 914 | 82 |
| CPU proses vision, median [p5; p95] (% satu inti) | 377 [297; 569] | 534 [400; 572] |
| CPU proses utama, median (% satu inti) | 18,7 | 6,2 |
| CPU total mesin, median [p5; p95] (% semua inti) | 55,5 [42,1; 65,1] | 44,9 [41,6; 49,9] |

Catatan A: dalam jendela A ada jeda sekitar 38 detik (13:24:12-13:24:50) ketika satu deteksi
YOLO butuh sekitar 0,9-1,1 detik. Karena loopnya tunggal, pembacaan kamera dan pratinjau ikut
turun ke sekitar 1 fps. Di luar jeda (92 detik setelah 13:24:58), tampilan A median 14,8
[13,7; 15,5] fps dan deteksi sekitar 48 ms. Penyebab inferensi melambat sampai 1 detik tidak
diketahui: CPU vision tetap 300-400%, dan dugaan seperti mode Best power efficiency atau beban
browser saat tab dibuka tidak diukur. Di B jeda seperti itu tidak terjadi, jadi B tidak
membuktikan perilaku saat jeda pada kamera asli. Bukti bahwa pratinjau tidak tertahan YOLO yang
lambat berasal dari tes unit.

Catatan B: waktu satu deteksi naik dari sekitar 48 ms (A, di luar jeda) ke sekitar 103 ms.
Kemungkinan penyebabnya thread pembaca (decode, resize, dan JPEG) yang berebut CPU dan GIL
dengan 7 thread torch. CPU vision juga naik. Laju deteksi tetap 5/s sesuai `fps_idle`.

## 5. Keputusan

- Median fps tampilan A = 1,0 (< 24), jadi kode diperbaiki (bagian 2) lalu diukur ulang (B).
- Median B = **14,9 fps, target 24 fps TIDAK tercapai.** Batasnya adalah kamera: `capture_fps`
  14,9 sama dengan laju webcam tanpa YOLO (15,0). Pratinjau sudah meneruskan setiap frame kamera
  (sent = drawn = capture).
- Perbaikan kode dipertahankan: pratinjau tidak lagi tertahan YOLO, dan jarak antar-gambar
  stabil sekitar 67 ms.
- `ui.preview_fps` dev = 24 (nilai coba) dipertahankan. Nilai ini tidak berpengaruh selama kamera
  memberi ≤ 15 fps, tetapi tidak menambah inferensi YOLO. Prod tidak diubah (10).
- Untuk mencapai 24 fps, kamera harus memberi ≥ 24 fps. Uji diagnosis menunjukkan exposure manual
  −5 menghasilkan 29,8 fps, tetapi gambar lebih gelap dan bisa memengaruhi deteksi atau warna.
  Alternatif lain: pencahayaan ruangan lebih terang agar exposure otomatis memendek. Keduanya
  **belum diputuskan dan belum diukur**. Mengubah setelan exposure kamera di kode akan menjadi
  keputusan baru.

## 6. Keterbatasan

- Satu laptop (Intel Family 6 Model 154, 14 inti fisik / 20 logis), satu webcam (Logi C270), satu
  sesi per kondisi, satu orang, satu pencahayaan ruangan, dan 60 detik per kondisi.
- Mode daya Windows Best power efficiency (dicatat). Mode lain tidak diukur.
- A dan B berjalan berurutan (selisih sekitar 10 menit), bukan diacak atau diulang.
- `browser_drawn_fps` menghitung event `load` `<img>`, bukan frame yang benar-benar dipindai
  layar.
- Pipeline RAG tidak aktif (tanpa `.env`), jadi beban STT/LLM saat bertanya tidak ikut terukur.
  Sapaan TTS ada di awal sesi, sebelum jendela analisis.
- Penyebab jeda inferensi sekitar 1 detik di A tidak diketahui (lihat bagian 4).

## 7. CV-3b: Pengukuran B ulang di ruang lebih terang (2 Nov 2026)

Kode sama dengan B (`7dbab59`). Exposure kamera **tetap otomatis**; tidak ada setelan manual di
kode. Cara ukur sama dengan bagian 3: 60 detik, pengguna di depan kamera, hanya angka, label
`CV3b-B`. Data ada di `results/preview-fps/20261102-135039/` dan
`results/preview-fps/live-20261102-135039.jsonl`. Jendela analisis 13:51:16-13:52:18.

- **Mode daya:** charger terpasang (baterai 99%), skema "ASUS Recommended", overlay AC
  `961cc777-…` = Best power efficiency. Tidak ada proses Python lain sebelum run.
- **fps asli kamera** (tanpa YOLO, sebelum run, skrip diagnosis yang sama): `CAP_PROP_FPS` −1,
  **15,0 fps** (150 frame / 10 s, median jarak 64,1 ms). Exposure otomatis terbaca −4
  (≈ 62,5 ms), gain 93, brightness 128, rata-rata luma satu frame 107,5 (hanya angka). Driver C270
  tidak memendekkan exposure walaupun ruangan lebih terang.

| CV-3b (ruang terang), per detik | median | p5 | p95 |
|---|---|---|---|
| fps tampilan browser | **14,8** | 14,5 | 15,7 |
| fps dikirim server | 14,8 | 14,4 | 15,8 |
| fps baca kamera | 14,9 | 14,9 | 15,1 |
| Deteksi YOLO per detik | 5,0 | 5,0 | 6,0 |
| Waktu satu deteksi (ms) | 106,5 | 96,8 | 119,6 |
| Jeda maksimum antar-gambar (ms) | 81 | 80 | 98 |
| CPU vision (% satu inti) | 532 | 402 | 578 |
| CPU total mesin (%) | 45,8 | 42,2 | 50,2 |

**Keputusan:** median tampilan 14,8 < 24, jadi **`config/prod.yaml` tidak diubah** (tetap 10).
fps tampilan dibatasi fps kamera pada pencahayaan itu. Laju baca kamera (14,9) sama dengan fps asli
webcam (15,0), dan setiap frame kamera sampai ke browser. Pada C270 dengan exposure otomatis,
pencahayaan ruangan ini belum cukup untuk membuat driver memendekkan exposure di bawah sekitar
62,5 ms.

**Waktu deteksi naik.** Waktu satu deteksi di B naik dari sekitar 48 ms (A di luar jeda, loop
tunggal) ke sekitar 103 ms (B) dan 106,5 ms (CV-3b). Ini dicatat sebagai akibat berbagi CPU
dengan thread pembaca di proses yang sama: decode, resize, pixelate atau overlay, dan JPEG sekitar
15 kali per detik, ditambah GIL Python, berebut dengan 7 thread torch. Penyebab ini belum diisolasi
dengan pengukuran terpisah. Laju deteksi tetap 5/s (`fps_idle`), dan median 106,5 ms masih jauh
di bawah jatah 200 ms per deteksi. Waktu sapaan (N-06) belum diukur ulang.

## 8. CV-3c: uji kemampuan fps dengan exposure manual (2 Nov 2026)

**Ini UJI KEMAMPUAN, bukan perubahan aplikasi.** Tujuannya mengukur fps tampilan browser yang
sanggup dicapai program bila kamera tidak membatasi. **Aplikasi tetap memakai exposure
otomatis**: `config/dev.yaml` dan `config/prod.yaml` tidak memuat setelan exposure, dan
`ui.preview_fps` dev kembali ke 24 setelah uji (prod tetap 10).

### 8.1 Opsi uji (bawaan MATI)

- CLI `python -m mica.webui ... --measure-preview --test-exposure -5`. Opsi ini ditolak tanpa
  `--measure-preview` (`WebUiError`) dan ditolak di luar `app.mode: dev` (`WorkerConfigError`;
  `--measure-preview` sendiri juga ditolak di prod). Opsi ini bukan kunci config.
- Jalurnya: `webui/app.py` (`--test-exposure` → `_start_bus`) → `VisionWorkerConfig.test_exposure`
  (bawaan `None`) → `Camera(exposure=...)` → `apply_manual_exposure`
  (`CAP_PROP_AUTO_EXPOSURE` 0,25 lalu `CAP_PROP_EXPOSURE` −5, yaitu 2⁻⁵ s ≈ 31 ms).
  `test_exposure` dicatat di `summary.json`.
- **Temuan:** driver Logi C270 (DSHOW) **menyimpan exposure manual setelah kamera dilepas**.
  Setelah C2 dihentikan (proses dibunuh, jadi `release` tidak sempat berjalan), membuka kamera
  tanpa setelan apa pun masih memberi exposure −5 dan 30 fps. Exposure otomatis dipulihkan manual
  (`CAP_PROP_AUTO_EXPOSURE` 0,75). Setelah itu dicek dengan membuka ulang tanpa setelan apa pun:
  exposure −4, 15,0 fps. Pengaman ditambahkan: `Camera.release()` memanggil
  `restore_auto_exposure` bila `exposure` diisi. Bila proses dibunuh sebelum `release`, exposure
  otomatis harus dipulihkan manual seperti di atas.
- Tes: `tests/unit/test_test_exposure.py` (8 tes). Isinya: bawaan tidak menyentuh exposure, nilai
  manual dipasang, otomatis dipulihkan saat release, ditolak tanpa measure atau di prod, dan
  config dev/prod tidak memuat exposure.

### 8.2 Kondisi dan cara ukur

Cara ukur sama persis dengan B (bagian 3). Satu-satunya perbedaan adalah `--test-exposure -5`,
dengan `ui.preview_fps` 20 (C1) atau 24 (C2) di `config/dev.yaml` selama uji. Pengguna di
depan kamera, ruangan seperti CV-3b, 60 detik per uji, hanya angka. Mode daya: charger terpasang
(baterai 100%), "ASUS Recommended", overlay AC **Best power efficiency**. Tidak ada proses Python
lain sebelum uji.

### 8.3 Kecerahan rata-rata frame (angka saja, frame tidak disimpan)

Diukur sebelum C1 dengan skrip di luar repo: 45 frame pemanasan, lalu 8 detik. Per frame dihitung
rata-rata V (HSV) dan luminans (grayscale), lalu dirata-ratakan. Pengguna ada di depan kamera.

| exposure | fps kamera | V rata-rata (median) | luminans rata-rata | gain |
|---|---|---|---|---|
| otomatis (−4) | 15,0 | 115,2 (115,2) | 97,5 | 101 |
| manual −5 | **29,75** | **71,0** (70,8) | **57,8** | 93 |
| otomatis lagi | 15,0 | 112,9 (114,7) | 95,2 | 101 |

Exposure −5 menurunkan V sekitar 38% (115 → 71) dan luminans sekitar 41%. Ini **risiko bagi
pengenalan warna baju**: nama warna dari tabel w2c bergantung pada kecerahan, sehingga warna
terang bisa terbaca lebih gelap atau abu-abu. Risiko ini belum diukur, dan pengenal warna tidak
diubah.

### 8.4 Hasil C1 dan C2 (per detik: median [p5; p95])

| | C1: exposure −5, preview_fps 20 (14:24:33-14:25:40) | C2: exposure −5, preview_fps 24 (14:28:44-14:29:47) |
|---|---|---|
| fps kamera (`capture_fps`) | 29,8 [29,8; 29,8] | 29,8 [29,8; 29,8] |
| JPEG dibuat (`preview_put_fps`) | 20,2 [16,0; 20,2] | 24,0 [23,1; 24,0] |
| fps dikirim server | 19,9 [11,2; 20,8] | 23,9 [23,2; 24,8] |
| **fps tampilan browser** | **19,9** [11,2; 20,6] | **23,9** [23,1; 24,7] |
| Deteksi YOLO per detik | 5,0 [5,0; 6,0] | 5,0 [5,0; 6,0] |
| Waktu satu deteksi (ms) | 107,2 [96,3; 137,1] | 103,8 [95,4; 121,3] |
| Jeda maksimum antar-gambar (ms) | 81 [65; 220] | 66 [65; 90] |
| CPU vision (% satu inti) | 526 [327; 585] | 545 [418; 586] |
| CPU proses utama (% satu inti) | 9,1 [4,6; 99,6] | 7,7 [4,3; 12,3] |
| CPU total mesin (%) | 47,3 [42,9; 52,1] | 45,9 [43,0; 50,8] |

Catatan C1: 6 dari 60 detik jatuh saat sapaan TTS (1 detik menyusun, 5 detik memutar), dan p5
turun ke 11,2. Tanpa 6 detik itu: 19,9 [14,7; 20,7] (n = 54). C2 tidak memuat detik TTS.

### 8.5 Kesimpulan uji kemampuan

- **≥ 20 fps: sanggup.** C1 median 19,9 fps, sama dengan batas `preview_fps` 20. Batasnya penjadwal
  pratinjau, bukan kamera (29,8) atau CPU (total mesin sekitar 47%).
- **24 fps: sanggup secara praktis.** C2 median 23,9 fps (99,6% dari 24), dengan p5 23,1 dan p95
  24,7. Pratinjau dibuat tepat 24,0 per detik; selisih 0,1 berasal dari penghitungan per jendela 1
  detik di browser. Bila syaratnya dibaca ketat (median ≥ 24,0), 23,9 belum memenuhi.
- Laju dan waktu deteksi YOLO tidak berubah oleh fps pratinjau (5/s, sekitar 104-107 ms), dan
  CPU total tetap sekitar 46-47%.
- Jadi batas fps tampilan di aplikasi (sekitar 15 fps, bagian 4 dan 7) adalah **fps kamera pada
  exposure otomatis**, bukan program. Untuk 24 fps di aplikasi dibutuhkan kamera yang memberi
  ≥ 24 fps dengan exposure otomatis (cahaya jauh lebih terang atau webcam lain), atau keputusan
  baru tentang exposure manual beserta uji pengenalan warnanya. Belum ada yang diputuskan.
- Keterbatasan sama dengan bagian 6: satu laptop, satu webcam, satu sesi per uji, 60 detik, dan
  mode Best power efficiency.

## 9. CV-6: nilai prod (2 Nov 2026)

- `config/prod.yaml` `ui.preview_fps` diubah dari 10 menjadi **24**. Ini **nilai coba**, bukan
  hasil eksperimen, dan komentarnya di prod.yaml diberi label "NILAI COBA CV-6".
- Sumber angka 24 adalah target dari dosen pembimbing.
- CV-3c (bagian 8) membuktikan program sanggup menampilkan 23,9 fps [23,1; 24,7] di browser bila
  kamera memberi frame yang cukup.
- Di perangkat uji (Logi C270, exposure otomatis), tampilan tetap dibatasi kamera sekitar 15 fps
  (bagian 4 dan 7). Nilai 24 tidak menaikkan laju ini dan tidak menambah inferensi YOLO.
- Aplikasi tetap memakai exposure otomatis. `--test-exposure` tetap mati secara default.
- `docs/SDD.md` (baris "Nilai keputusan desain": prod 10) belum diperbarui. Atas keputusan
  pengguna, SDD akan diperbarui di Claude Doc lalu diekspor ulang.
- Tes: `test_preview_fps_user_design_decision` di `tests/unit/test_config.py` (prod 24).
