# IMGSZ: pra-registrasi sweep `vision.imgsz` (CV-1)

Status: **PRA-REGISTRASI**. Dokumen ini ditulis dan di-commit sebelum dataset diunduh dan
sebelum ada pengukuran. Hash commit dokumen ini adalah buktinya. Perubahan apa pun setelah data
dilihat harus ditulis sebagai amandemen bertanggal di akhir dokumen, dan aturan pilih di bagian 6
tidak boleh diubah.

Skrip: `scripts/cv_imgsz_sweep.py`. Tes: `tests/unit/test_cv_imgsz_sweep.py` (data mainan).

## 1. Tujuan

Memilih `vision.imgsz` terkecil yang akurasi deteksi orang berukuran besar tidak terbukti lebih
buruk dibanding 640, agar deteksi lebih cepat. Ini menindaklanjuti arahan dosen pembimbing:
perkecil citra, deteksi, lalu skalakan hasilnya kembali.

Ultralytics sudah melakukan langkah itu di dalam `predict`. Aplikasi tidak perlu menambah resize
sendiri:

- Citra di-letterbox ke `imgsz`, yaitu diubah ukurannya dengan rasio aspek tetap lalu diberi
  padding. Dokumentasi menyebut `imgsz` sebagai "Letterbox target. An integer gives a square
  `N×N`". Mode predict memakai `rect=True` secara bawaan: "With `rect=True`, the actual tensor
  may be smaller than this target due to minimum-rectangle padding."
  Sumber: <https://docs.ultralytics.com/modes/predict/#inference-arguments> dan
  <https://docs.ultralytics.com/modes/predict/#fixed-shape-vs-minimum-rectangle-rect>
  (dibaca 30 Okt 2026). Kelas `LetterBox`: "Resize image and padding for detection, instance
  segmentation, pose."
  (<https://docs.ultralytics.com/reference/data/augment/#ultralytics.data.augment.LetterBox>).
- Kotak dan keypoint diskalakan kembali ke ukuran citra asli. Halaman dokumentasi tidak memuat
  kalimat eksplisit tentang hal ini. Yang paling dekat adalah atribut `orig_shape` ("The original
  image shape in (height, width) format") dan `xyxyn` ("normalized by original image size"),
  <https://docs.ultralytics.com/modes/predict/#working-with-results>. Karena itu buktinya diambil
  dari kode Ultralytics 8.4.178 yang terpasang:
  - `ultralytics/engine/model.py:540`: predict memakai `"rect": True`.
  - `ultralytics/engine/model.py:611`: `track` memanggil `self.predict`, jadi aplikasi memakai
    jalur letterbox yang sama.
  - `ultralytics/engine/predictor.py:234-243`: `LetterBox(self.imgsz, auto=... self.args.rect ...,
    stride=self.model.stride)`.
  - `ultralytics/models/yolo/detect/predict.py:131`: `ops.scale_boxes(img.shape[2:], ...,
    orig_img.shape)`.
  - `ultralytics/models/yolo/pose/predict.py:64`: `ops.scale_coords(...)` untuk keypoint.

Akibatnya, frame kamera 640×480 pada imgsz 640 masuk sebagai tensor 640×480 tanpa pengecilan
(480 sudah kelipatan 32). Pada imgsz 320, frame dikecilkan ke 320×240 lalu diberi padding ke
320×256.

## 2. Kandidat

640 (acuan, nilai dev sekarang), 480, 416, 320, 256. Semuanya kelipatan 32, sesuai stride YOLO.

## 3. Data dan model

- COCO val2017. Semua gambar di `annotations/person_keypoints_val2017.json` (5000 gambar menurut
  COCO; jumlahnya dicek dan dicatat saat run, termasuk gambar tanpa orang, sesuai bawaan `COCOeval`), hanya kategori person (`category_id`
  1). Dataset disimpan di luar repo, di `D:\SKRIPSI\datasets\coco`. Belum diunduh.
- Bobot `models/yolo26n-pose.pt`, sama dengan aplikasi (SHA-256 terkunci di
  `src/mica/vision/detector.py:30`). Tidak ada pelatihan ulang.
- Inferensi: `model.predict` per gambar dengan batch 1 dan CPU (jalur letterbox sama dengan
  `model.track` di aplikasi), `classes=[0]`, `conf=0.001`, serta nilai bawaan Ultralytics 8.4.178
  untuk `iou` (0,7), `max_det` (300), dan `rect` (True). Gambar dibaca dengan `cv2.imread` (BGR,
  sama dengan frame kamera).
- Alasan `conf=0.001`: AP butuh kurva presisi-recall lengkap, dan 0,001 adalah nilai bawaan val
  Ultralytics (`cfg/default.yaml:55`). Aplikasi sendiri memakai `vision.conf` 0,1, jadi AP di sini
  mengukur kualitas peringkat deteksi, bukan perilaku pada ambang aplikasi.
- Keluaran disimpan di `D:\SKRIPSI\cv-hasil\<waktu>\`, di luar repo, dan hanya berisi angka
  (deteksi JSON dan ringkasan). Tidak ada gambar yang ditulis.

## 4. Metrik

- **Utama (menentukan):** AP box person, IoU 0,50:0,95, area `large` (> 96² piksel, definisi
  COCO, diukur pada citra asli), maxDets 100. Dihitung dengan pycocotools
  `COCOeval(iouType='bbox')`, yaitu `stats[5]`.
- **Pendukung (dilaporkan, tidak menentukan):** AP box `all` dan `medium`, AP keypoint `large`
  (`iouType='keypoints'`, maxDets 20), dan AR box `large` (`stats[11]`). Keypoint ikut
  dilaporkan karena sinyal kehadiran `shoulder_width` memakai keypoint bahu.
- **Cek kebenaran (dikunci):** AP dan AR `large` dari `accumulate` milik skrip harus sama dengan
  `stats[5]` dan `stats[11]` COCOeval (selisih ≤ 1e-9). Bila berbeda, run dihentikan.

## 5. Ketidakpastian: bootstrap berpasangan per gambar

- B = 1000, seed 20261030, interval persentil 95% (persentil 2,5 dan 97,5).
- Satu matriks hitungan `counts` (B × 5000) dibuat sekali dari seed, berisi berapa kali tiap
  gambar terambil. Matriks yang sama dipakai untuk semua imgsz, sehingga sampelnya berpasangan.
- Untuk tiap sampel dihitung AP tiap imgsz dan **selisih AP_640 − AP_imgsz**. Yang dilaporkan:
  nilai titik, CI AP tiap imgsz, dan CI selisih.

Implementasi yang efisien:

1. `COCOeval.evaluate()` dijalankan sekali per imgsz dan per iouType. Pencocokan deteksi-GT per
   gambar (`evalImgs`) tidak bergantung pada sampel bootstrap.
2. `evalImgs` untuk area dan maxDet yang dipakai diratakan sekali menjadi larik terurut skor
   menurun (`argsort(-skor, kind='mergesort')`, sama dengan pycocotools). Isinya: indeks gambar,
   TP/FP per ambang IoU, dan jumlah GT tidak diabaikan per gambar.
3. Tiap sampel bootstrap tidak menggandakan data. Tiap deteksi diberi bobot `counts[b, gambar]`,
   lalu TP dan FP kumulatif dihitung sebagai `cumsum(TP × bobot)`, dan jumlah GT menjadi
   `Σ counts × npig`. Presisi terinterpolasi dihitung dengan `maximum.accumulate` dari kanan dan
   `searchsorted` pada 101 titik recall. Pengurutan tidak diulang.
4. Bobot w setara dengan menggandakan gambar w kali. Titik antara yang hilang tidak mengubah
   amplop presisi. Satu-satunya beda adalah urutan seri skor antar-gambar yang berbeda, dan urutan
   itu juga sembarang di pycocotools. Tes `test_matches_reference_full_and_resampled`
   membandingkan hasilnya dengan salinan loop `COCOeval.accumulate` pada data mainan, baik tanpa
   maupun dengan penggandaan eksplisit.

Estimasi waktu (kasar, belum diukur):

- N (jumlah deteksi setelah dipotong maxDets 100 per gambar) diperkirakan 100 ribu sampai
  500 ribu (batas atas 5000 × 100).
- Satu `accumulate` berisi sekitar 6 operasi vektor pada larik 10 × N, kira-kira 20 sampai 150
  ms.
- Jumlah `accumulate` = 1000 sampel × 5 imgsz × 4 set metrik = 20.000 kali, jadi sekitar 7
  sampai 50 menit.
- Ditambah `evaluate` (10 kali, perkiraan 0,5 sampai 1 menit per kali) dan inferensi (5 × 5000
  gambar; waktunya belum diketahui dan akan dicatat).

Batas atas di bawah 1 jam masih layak di laptop, jadi **B tetap 1000**. Bila run mendadak jauh
lebih lambat dari estimasi ini, B tidak boleh diturunkan setelah data dilihat. Run dihentikan dan
dicatat sebagai penyimpangan.

## 6. ATURAN PILIH (dikunci)

> Pilih imgsz **terkecil** di antara {480, 416, 320, 256} yang CI 95% selisihnya
> (AP_640 − AP_imgsz, AP box person `large`) **mencakup 0** (batas bawah ≤ 0 ≤ batas atas). Bila
> tidak ada yang memenuhi, tetap **640**.

- Kecepatan **tidak** ikut menentukan. Kecepatan hanya dilaporkan.
- Aturan ini berlaku apa adanya walaupun tidak monoton. Contohnya, bila 320 memenuhi tetapi 416
  tidak, yang dipilih tetap 320. Hal seperti itu dicatat sebagai temuan, tanpa mengubah pilihan.
- Diterapkan dalam kode oleh `choose_imgsz` (dites).

Keterbatasan:

- "Tidak terbukti berbeda" bukan bukti setara. CI yang lebar bisa mencakup 0 walaupun penurunan
  akurasinya nyata.
- Tidak ada margin non-inferioritas karena tidak ada dasar angka untuk margin itu. Angka tidak
  dikarang. Akibatnya, aturan ini cenderung memilih ukuran kecil bila ketidakpastiannya besar.
  CI selisih akan dilaporkan lengkap agar pembaca bisa menilai besarnya penurunan.
- COCO bukan kamera kiosk. Pencahayaan, sudut, dan jarak berbeda. Area `large` diukur dalam
  piksel citra asli COCO (sisi terpanjang ≤ 640, mirip frame kamera 640×480), bukan jarak meter.
- AP dihitung pada `conf` 0,001 dengan `predict`, bukan `track` pada `conf` 0,1 seperti di
  aplikasi.

## 7. Pengukuran kecepatan (dilaporkan, tidak menentukan)

- Dijalankan dengan `--speed`, terpisah dari run akurasi, dan **tidak bersamaan dengan run uji
  RAG**.
- CPU laptop dev. Laptop wajib di charger. Mode daya Windows dicatat manual di laporan.
- Jumlah torch threads dicatat (`torch.get_num_threads()`). Untuk relevansi ke aplikasi, run
  memakai `--threads 7` sesuai `vision.threads` di `config/dev.yaml`.
- Gambar: `speed_image_ids` mengambil 220 id dengan seed 20261030
  (`default_rng(seed).choice(sorted(ids), 220, replace=False)`). 20 id pertama dipakai untuk
  pemanasan dan 200 id berikutnya diukur. Daftar ini dikunci oleh algoritmenya dan ditulis ke
  `speed.json`.
- Yang dicatat per imgsz (urutan 640, 480, 416, 320, 256): median dan p95 dari `preprocess`,
  `inference`, dan `postprocess` (dict `Results.speed` Ultralytics, ms), serta `total`, yaitu
  jumlah ketiganya per gambar.

## 8. Lingkungan yang dicatat

Versi Python, torch, ultralytics, pycocotools, CPU (`platform.processor()`), RAM total, dan
SHA-256 bobot model. Semua ditulis otomatis ke `accuracy.json` atau `speed.json`.

Diisi 30 Okt 2026 (CV-2a), `.venv` di `D:\SKRIPSI\mica\.venv`:

- Python 3.13.7 (64 bit), numpy 2.5.4, torch 2.14.1+cpu, ultralytics 8.4.178.
- pycocotools 2.0.11 (wheel `cp312-abi3-win_amd64`). `pip install pycocotools --dry-run` hanya
  akan memasang pycocotools; numpy, torch, dan ultralytics tidak berubah. Modul ini tidak punya
  `__version__`, jadi skrip membaca versi dari `importlib.metadata`.
- CPU 12th Gen Intel Core i9-12900H (20 thread logis), RAM 16,8 GB.
- Threads: `--threads 7`, sama dengan `vision.threads: 7` di `config/dev.yaml:88`.
- Bobot: `models/yolo26n-pose.pt` di worktree adalah salinan dari `D:\SKRIPSI\mica\models`.
  SHA-256 `eb3bb826…c14522a9` sama dengan kunci di `src/mica/vision/detector.py:30`.
- Dataset di `D:\SKRIPSI\datasets\coco`, diunduh 30 Okt 2026 dari images.cocodataset.org:
  - `val2017.zip`: 815.585.330 byte, SHA-256
    `4f7e2ccb2866ec5041993c9cf2a952bbed69647b115d0f74da7ce8f4bef82f05`, MD5
    `442b8da7639aecaf257c1dceb8ba8c80`.
  - `annotations_trainval2017.zip`: 252.907.541 byte, SHA-256
    `113a836d90195ee1f884e704da6304dfaaecff1f023f49b6ca93c4aaae470268`, MD5
    `f4bbac642086de4f52a3fdda2de5fa2c`.
  - MD5 kedua zip sama dengan nilai yang umum dipublikasikan untuk COCO 2017.
  - Hasil verifikasi: 5000 file `.jpg` di `val2017/`. `person_keypoints_val2017.json` memuat 5000
    gambar, 11004 anotasi, dan satu kategori (id 1).

## 9. Ditunda (bukan bagian aturan ini)

- Preview kamera 24 fps (CV-3).
- Pembanding resize pyvips vs OpenCV (CV-4).
- INT8 (cadangan).

## 10. Catatan prasyarat

- `pycocotools` belum terpasang di `.venv` dan belum disebut di SDD. Pemasangannya perlu izin
  pengguna sebelum run (CLAUDE.md: jangan menambah library tanpa bertanya).
- Menurut SDD, `vision.imgsz` ditetapkan di E-07. Hasil sweep ini menjadi masukan untuk E-07.
  Dokumen ini tidak mengubah SDD atau config.

## Amandemen 30 Okt 2026 (CV-2a, sebelum data COCO dilihat)

Bagian 6 (ATURAN PILIH) dan metrik di bagian 4 sampai 5 **tidak berubah**. Yang berubah hanya
implementasi skrip, dan semuanya dicatat di sini:

1. **Perbaikan thread (penyimpangan implementasi dari commit c9a7213).** Di c9a7213, mode
   `--speed` memanggil `torch.set_num_threads` sebelum inferensi pertama. Ultralytics 8.4 menimpa
   setelan itu dengan `min(8, cpu_count - 1)` saat predictor disiapkan (docs/CPU-THREADS.md,
   `src/mica/vision/worker.py:510-522`), jadi `--threads 7` sebenarnya tidak berlaku. Sekarang
   `warm_up_threads` melakukan satu inferensi pemanasan pada frame hitam 640×480, lalu baru
   memasang thread, dengan urutan yang sama seperti aplikasi. Alasannya: tanpa perbaikan ini,
   bagian 7 tidak bisa dipenuhi.
2. **`--threads` juga berlaku di mode akurasi.** Tujuannya agar waktu run sesuai dengan aplikasi.
   Jumlah thread tidak mengubah aturan pemilihan. Thread yang berlaku setelah tiap imgsz dicatat
   di `timing.threads_after`.
3. **`--max-images N` (baru).** Opsi ini mengambil N id pertama untuk uji coba alur. Run dengan
   opsi ini ditandai `"trial": true` dan tidak boleh dipakai untuk memilih. Run resmi tidak
   memakai opsi ini.
4. **Catatan waktu dan lingkungan.** `accuracy.json` sekarang memuat `timing` (prediksi, evaluate,
   dan bootstrap, dalam detik), `torch_threads`, dan versi numpy. Skrip juga berhenti bila ada
   gambar yang gagal dibaca `cv2.imread`.

