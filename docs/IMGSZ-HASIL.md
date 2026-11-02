# IMGSZ-HASIL: hasil sweep `vision.imgsz` (CV-2b, CV-2c)

Status: **HASIL** (akurasi CV-2b, kecepatan CV-2c). Pra-registrasi ada di `docs/IMGSZ.md` (commit `c9a7213`, amandemen `4e1f9f0`).
Dokumen ini hanya melaporkan hasil. Aturan pilih dan config tidak diubah.

## 1. Run

- Keluaran: `D:\SKRIPSI\cv-hasil\20261030-151542\` (`accuracy.json`, `dets-{640,480,416,320,256}.json`).
  Log: `D:\SKRIPSI\cv-hasil\sweep-imgsz.log` (UTF-16).
- `plan`: `mode` accuracy, `sizes` [640, 480, 416, 320, 256], `bootstrap` 1000, `seed` 20261030,
  `threads` 7, `max_images` null, `trial` false.
- `n_images` 5000 (id 139 sampai 581781). `accumulate_matches_cocoeval` true di kelima ukuran.
  `threads_after` 7 di kelima ukuran.
- Lingkungan (dari file): Python 3.13.7, numpy 2.5.4, torch 2.14.1, ultralytics 8.4.178,
  pycocotools 2.0.11, RAM 16,8 GB, SHA-256 bobot `eb3bb826…c14522a9` (sama dengan kunci).
- Urutan di log: lima blok COCOeval (bbox lalu keypoints) dengan AP box large 0,741, 0,747, 0,747,
  0,721, 0,693. Ini cocok dengan `official_stats` 640, 480, 416, 320, 256 di `accuracy.json`, jadi
  urutannya 640 → 480 → 416 → 320 → 256 sesuai `plan.sizes`.
- Mode daya Windows tidak tercatat di log (keluaran `powercfg` berada di luar `Tee-Object`).

## 2. Metrik utama: AP box person, area large (IoU 0,50:0,95, maxDets 100)

Bootstrap berpasangan per gambar, B = 1000, interval persentil 95%.

| imgsz | AP box large | CI 95% AP | Selisih 640 − imgsz | CI 95% selisih | Mencakup 0? |
|---|---|---|---|---|---|
| 640 | 0,7415 | [0,7305; 0,7535] | 0 | (acuan) | - |
| 480 | 0,7473 | [0,7364; 0,7589] | −0,0059 | [−0,0107; −0,0008] | tidak |
| 416 | 0,7470 | [0,7362; 0,7578] | −0,0056 | [−0,0107; −0,0002] | tidak |
| 320 | 0,7212 | [0,7104; 0,7328] | 0,0203 | [0,0134; 0,0268] | tidak |
| 256 | 0,6929 | [0,6816; 0,7048] | 0,0486 | [0,0414; 0,0559] | tidak |

## 3. Metrik pendukung (tidak menentukan)

Selisih = 640 − imgsz, dengan CI 95% bootstrap berpasangan yang sama.

| imgsz | AP box all | Selisih all [CI] | AP box medium | Selisih medium [CI] | AP keypoint large | Selisih kp large [CI] | AR box large |
|---|---|---|---|---|---|---|---|
| 640 | 0,4263 | - | 0,5986 | - | 0,6826 | - | 0,8264 |
| 480 | 0,3870 | 0,0393 [0,0360; 0,0430] | 0,5409 | 0,0577 [0,0514; 0,0648] | 0,6735 | 0,0090 [0,0033; 0,0156] | 0,8249 |
| 416 | 0,3721 | 0,0542 [0,0506; 0,0582] | 0,5087 | 0,0899 [0,0836; 0,0968] | 0,6577 | 0,0249 [0,0184; 0,0314] | 0,8256 |
| 320 | 0,3286 | 0,0976 [0,0920; 0,1030] | 0,4251 | 0,1735 [0,1643; 0,1824] | 0,6052 | 0,0773 [0,0688; 0,0872] | 0,8047 |
| 256 | 0,2849 | 0,1413 [0,1345; 0,1478] | 0,3354 | 0,2633 [0,2519; 0,2741] | 0,5458 | 0,1368 [0,1272; 0,1469] | 0,7879 |

AR box large hanya nilai titik (`ar_large`); skrip tidak membuat CI untuk AR.

## 4. ATURAN PILIH (docs/IMGSZ.md bagian 6, diterapkan apa adanya)

Dicek dari yang terkecil:

- 256: CI selisih [0,0414; 0,0559], batas bawah > 0. Tidak mencakup 0.
- 320: CI [0,0134; 0,0268], batas bawah > 0. Tidak mencakup 0.
- 416: CI [−0,0107; −0,0002], batas atas < 0. Tidak mencakup 0.
- 480: CI [−0,0107; −0,0008], batas atas < 0. Tidak mencakup 0.

Tidak ada kandidat yang memenuhi, jadi **imgsz terpilih = 640**. Ini sama dengan `chosen_imgsz`
640 yang dihitung `choose_imgsz` di `accuracy.json`.

## 5. Temuan dan keterbatasan (tidak mengubah aturan)

1. **416 dan 480 lebih baik daripada 640 pada AP box large**, dan CI selisihnya seluruhnya di bawah 0
   (sekitar +0,006 AP). Aturan yang dikunci hanya menerima CI yang mencakup 0, jadi ukuran yang
   terbukti *lebih baik* pun tidak terpilih. Ini adalah sifat aturan yang tidak diantisipasi saat
   pra-registrasi. Dicatat sebagai temuan; aturan tidak diubah dan pilihan tetap 640.
2. **AP keypoint large turun lebih cepat daripada AP box large.** Pada 480 dan 416, AP box large
   naik tipis, tetapi AP keypoint large turun 0,0090 [0,0033; 0,0156] dan 0,0249 [0,0184; 0,0314],
   keduanya CI di atas 0. Pada 320 dan 256, penurunan keypoint (0,0773 dan 0,1368) sekitar 3,8 dan
   2,8 kali penurunan box (0,0203 dan 0,0486). MICA memakai keypoint bahu untuk sinyal kehadiran
   (`shoulder_width`, lebar bahu) dan untuk memotong torso, jadi metrik utama yang berbasis box bisa
   melebih-lebihkan seberapa aman imgsz kecil bagi aplikasi. Ini dilaporkan sebagai keterbatasan
   metrik utama; aturan tidak diubah. AP keypoint COCO mencakup 17 keypoint, bukan bahu saja,
   sehingga angka ini juga tidak mengukur bahu secara khusus.
3. Penurunan pada area all dan medium jauh lebih besar daripada pada large (misalnya 320: 0,0976
   dan 0,1735). Orang yang jauh dari kamera (kecil di frame) paling terdampak oleh imgsz kecil.
4. Keterbatasan dari pra-registrasi tetap berlaku: COCO bukan kamera kiosk, AP dihitung pada
   `conf` 0,001 dengan `predict` (bukan `track` pada `conf` 0,1), dan "tidak terbukti berbeda"
   bukan bukti setara.

## 6. Bootstrap

- `plan.bootstrap` = 1000 dan `seed` = 20261030. `accuracy.json` tidak menyimpan larik sampel
  bootstrap, jadi jumlah sampel tidak bisa dihitung langsung dari file.
- Bukti tidak langsung: `timing.bootstrap_s` = 1068,8 detik untuk 1000 × 5 imgsz × 4 set metrik =
  20.000 `accumulate`, yaitu sekitar 53 ms per `accumulate`. Ini sesuai dengan estimasi 20-150 ms di
  pra-registrasi dan 72 ms pada N = 200 ribu di CV-2a. Lebar CI juga tidak nol.
- Di kode, `bootstrap_counts(n_images, args.bootstrap, seed)` membuat tepat B baris, dan
  `paired_bootstrap` menghitung AP untuk tiap baris.

## 7. Kecepatan (CV-2c, dilaporkan, tidak menentukan)

### 7.1 Run

- Keluaran: `D:\SKRIPSI\cv-hasil\20261102-125149\speed.json`. Log:
  `D:\SKRIPSI\cv-hasil\sweep-imgsz-speed.log`.
- Dijalankan 2 Nov 2026 dengan perintah di 7.4 (tidak diubah). Sebelum run: `PowerLineStatus`
  Online (charger terpasang, baterai 55% sedang diisi) dan tidak ada proses Python lain (tidak ada
  run RAG).
- **Mode daya (dicatat manual):** skema `powercfg` "ASUS Recommended"
  (`bac9a61f-7b61-4dac-8c43-8fc6f1e49e6b`). Mode daya Windows untuk AC (registry
  `ActiveOverlayAcPowerScheme`) = `961cc777-2547-4f9d-8174-7d86181b8a7a`, yaitu **Best power
  efficiency**. Jadi angka di bawah diukur pada mode hemat daya; pada mode Best performance
  angkanya kemungkinan lebih kecil. Mode daya run akurasi tidak tercatat (bagian 1).
- `plan.mode` speed, `threads` 7, `torch_threads` 7, seed 20261030, 20 id pemanasan + 200 id
  terukur (tertulis di file), urutan 640 → 256. Lingkungan sama dengan run akurasi (Python
  3.13.7, torch 2.14.1, ultralytics 8.4.178, SHA-256 bobot `eb3bb826…c14522a9`), CPU Intel64
  Family 6 Model 154. Inferensi memakai `conf` 0,001 seperti run akurasi.

### 7.2 Hasil (ms per gambar, `Results.speed` Ultralytics, n = 200)

| imgsz | preprocess median | preprocess p95 | inference median | inference p95 | postprocess median | postprocess p95 | total median | total p95 |
|---|---|---|---|---|---|---|---|---|
| 640 | 1,10 | 1,99 | 43,81 | 61,89 | 0,80 | 1,56 | 45,92 | 65,56 |
| 480 | 1,07 | 1,43 | 29,36 | 37,45 | 0,73 | 1,01 | 31,25 | 39,31 |
| 416 | 0,90 | 1,17 | 25,51 | 31,87 | 0,73 | 1,00 | 27,24 | 33,86 |
| 320 | 0,59 | 0,85 | 18,36 | 23,96 | 0,73 | 1,04 | 19,75 | 25,52 |
| 256 | 0,52 | 0,73 | 14,91 | 18,82 | 0,70 | 1,06 | 16,21 | 20,23 |

`total` = preprocess + inference + postprocess per gambar; median dan p95 dihitung per kolom,
jadi median total tidak harus sama dengan jumlah median tahap. Tidak termasuk `cv2.imread`,
pelacakan, atau langkah aplikasi lain.

Waktu turun monoton terhadap imgsz. Relatif terhadap 640, median total 480 = 0,68×, 416 = 0,59×,
320 = 0,43×, 256 = 0,35×. Inference mendominasi (lebih dari 92% total di semua ukuran);
postprocess hampir konstan (sekitar 0,7 ms).

### 7.3 Kenapa 480/416 lebih lambat di run akurasi

**speed.json tidak menunjukkan hal yang sama**: 480 dan 416 lebih cepat daripada 640 (median
total 31,3 dan 27,2 ms vs 45,9 ms). Jadi kelambatan di `timing.predict_s` run akurasi (per gambar
640 51,0 ms, 480 70,1 ms, 416 67,2 ms, 320 22,9 ms, 256 18,9 ms) bukan sifat model atau ukuran
tensor. Pemeriksaan (tanpa mengubah kode aplikasi; skrip analisis di luar repo yang memakai
`load_model` dan `predict` dari skrip sweep apa adanya):

1. **Ukuran tensor input sebenarnya.** Predict Ultralytics memakai letterbox `rect` (sisi
   terpanjang = imgsz, sisi pendek dibulatkan ke kelipatan stride 32), bukan kotak N×N
   (`docs/IMGSZ.md` bagian 2). Bentuk tensor dicatat dengan membungkus `predictor.preprocess`
   pada 200 gambar terukur, dan cocok 100% dengan `LetterBox(imgsz, auto=True, stride=32)`.
   Rumus yang sama lalu diterapkan ke 5000 gambar dari ukuran di anotasi:

   | imgsz | bentuk (h, w) tersering, 5000 gambar | rata-rata piksel, 5000 | rata-rata piksel, 200 speed | rasio ke 640 | piksel N×N |
   |---|---|---|---|---|---|
   | 640 | (480, 640) 1522; (448, 640) 1509; (640, 480) 530 | 300.655 | 299.622 | 1,00 | 409.600 |
   | 480 | (384, 480) 1541; (320, 480) 1290; (480, 384) 544 | 171.875 | 171.571 | 0,57 | 230.400 |
   | 416 | (320, 416) 1609; (288, 416) 1570; (416, 320) 568 | 128.306 | 127.995 | 0,43 | 173.056 |
   | 320 | (256, 320) 1658; (224, 320) 1621; (320, 256) 585 | 77.533 | 77.005 | 0,26 | 102.400 |
   | 256 | (192, 256) 3092; (256, 192) 1036; (256, 256) 266 | 49.794 | 49.725 | 0,17 | 65.536 |

   Piksel tensor turun monoton, dan sampel 200 gambar mewakili 5000 gambar. Tidak ada imgsz yang
   membuat tensor 480/416 lebih besar daripada 640. Variasi bentuk antar-gambar (rect) ada di
   semua imgsz, bukan khusus 480/416. Waktu inference turun lebih lambat daripada jumlah piksel
   (480: 0,67× waktu untuk 0,57× piksel), wajar karena ada overhead tetap per lapis.
2. **`evaluate_s` juga melonjak di blok 480.** `timing.evaluate_s` (COCOeval, pycocotools murni,
   tanpa model) = 16,0 / **35,0** / 15,2 / 14,5 / 13,7 detik untuk 640 / 480 / 416 / 320 / 256.
   Langkah ini hampir tidak bergantung pada imgsz, tetapi di 480 waktunya 2,2× ukuran lain. Ini
   menunjukkan mesin melambat secara umum selama blok 480 (dan selama predict 416), misalnya karena
   mode daya, pembatasan termal, atau proses latar. Penyebab persisnya tidak bisa dipastikan: run
   akurasi tidak mencatat mode daya, suhu, atau beban CPU per waktu.
3. Faktor yang ada di run akurasi tetapi tidak di speed.json (`cv2.imread`, konversi deteksi ke
   JSON) berlaku di semua imgsz dan tidak menjelaskan mengapa hanya 480/416 yang lambat.

Kesimpulan: kelambatan 480/416 di run akurasi paling mungkin artefak kondisi mesin saat run, bukan
sifat imgsz. Ini inferensi dari data waktu, bukan pengukuran langsung. Angka kecepatan yang
dilaporkan adalah speed.json di 7.2.

### 7.4 Perintah

Sesuai bagian 7 pra-registrasi (20 pemanasan, 200 gambar terkunci dari seed 20261030,
threads 7, urutan 640 → 256), dengan charger terpasang dan tanpa run RAG:

```powershell
Add-Type -AssemblyName System.Windows.Forms; if ([System.Windows.Forms.SystemInformation]::PowerStatus.PowerLineStatus -ne 'Online') { Write-Error 'Charger tidak terpasang: run dibatalkan' } else { powercfg /getactivescheme *>&1 | Tee-Object -FilePath D:\SKRIPSI\cv-hasil\sweep-imgsz-speed.log; & D:\SKRIPSI\mica\.venv\Scripts\python.exe D:\SKRIPSI\mica-cv\scripts\cv_imgsz_sweep.py --data-dir D:\SKRIPSI\datasets\coco --out-dir D:\SKRIPSI\cv-hasil --speed --threads 7 --seed 20261030 *>&1 | Tee-Object -FilePath D:\SKRIPSI\cv-hasil\sweep-imgsz-speed.log -Append }
```

`powercfg /getactivescheme` hanya mencatat skema daya, bukan mode daya Windows (slider). Mode
daya dibaca terpisah dari registry `HKLM:\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes`
(`ActiveOverlayAcPowerScheme`).

## 8. Catatan: rumusan aturan vs tujuan (ANALISIS PASCA-DATA)

**Label: PASCA-DATA.** Bagian ini ditulis setelah hasil akurasi dan kecepatan diketahui. Ia tidak
mengubah aturan pilih, config, atau `docs/IMGSZ.md`.

- **Keputusan resmi tetap mengikuti aturan yang dikunci: imgsz = 640** (bagian 4).
- Rumusan aturan ("pilih imgsz terkecil yang CI 95% selisih 640 − imgsz **mencakup 0**") tidak
  selaras dengan tujuannya, yaitu memilih ukuran terkecil yang **tidak terbukti lebih buruk**
  daripada 640. Aturan itu menolak dua jenis kandidat: yang terbukti lebih buruk (CI > 0, sesuai
  tujuan) dan yang terbukti lebih baik (CI < 0, tidak sesuai tujuan). 480 dan 416 masuk jenis
  kedua. Rumusan yang selaras dengan tujuan adalah "batas bawah CI ≤ 0" (atau, untuk
  non-inferioritas yang sebenarnya, "batas atas CI < margin δ" dengan δ ditetapkan sebelum data).
- Bila rumusan "batas bawah CI ≤ 0" dipakai (**pasca-data, bukan keputusan**), kandidat terkecil
  yang lolos adalah 416 (CI [−0,0107; −0,0002]); 320 dan 256 tetap gagal. Menurut speed.json,
  416 memangkas median total dari 45,9 ke 27,2 ms (0,59×).
- Yang menahan kesimpulan itu, juga pasca-data: AP keypoint large di 416 turun 0,0249
  [0,0184; 0,0314] (bagian 5 butir 2), padahal MICA memakai keypoint bahu. Metrik utama berbasis
  box tidak menangkap ini.
- Perubahan aturan atau imgsz, bila diinginkan, harus lewat keputusan baru yang dicatat terpisah
  (amandemen pra-registrasi untuk run berikutnya), bukan dengan menafsirkan ulang hasil ini.

## 9. CV-6: nilai prod (2 Nov 2026)

- `config/prod.yaml` `vision.imgsz` diubah dari `null` menjadi **640**. Ini **nilai keputusan**,
  bukan nilai coba.
- Sumbernya adalah aturan pilih yang dikunci di pra-registrasi `docs/IMGSZ.md` bagian 6 (commit
  c9a7213). Aturan itu diterapkan apa adanya pada hasil di bagian 4 dokumen ini, dan hasilnya 640.
- Temuan pasca-data di bagian 5 dan 8 tidak dipakai untuk mengubah pilihan ini.
- `vision.conf` prod tetap `null` (TBD, E-07). Kunci lain tidak diubah.
- Tes: `test_prod_yaml_imgsz_decision` di `tests/unit/test_config.py`.
