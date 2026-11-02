# PREVIEW-24FPS: pratinjau kamera 24 fps (CV-3)

Status: **HASIL** (CV-3 dan CV-3b di bagian 7), 2 Nov 2026, branch `cv/imgsz` (worktree `D:\SKRIPSI\mica-cv`). Target 24 fps
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
