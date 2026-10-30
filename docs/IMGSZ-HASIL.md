# IMGSZ-HASIL: hasil sweep `vision.imgsz` (CV-2b)

Status: **HASIL**. Pra-registrasi ada di `docs/IMGSZ.md` (commit `c9a7213`, amandemen `4e1f9f0`).
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

## 7. Kecepatan

**Belum diukur.** Tidak ada `speed.json` di `D:\SKRIPSI\cv-hasil\`. Waktu di `timing.predict_s`
run akurasi bukan pengukuran kecepatan (termasuk `cv2.imread`, `conf` 0,001, dan konversi deteksi
ke JSON). Nilainya per gambar: 640 51,0 ms, 480 70,1 ms, 416 67,2 ms, 320 22,9 ms, 256 18,9 ms.
480 dan 416 lebih lambat daripada 640; penyebabnya belum diketahui, dan angka ini tidak dipakai.

Perintah sesuai bagian 7 pra-registrasi (20 pemanasan, 200 gambar terkunci dari seed 20261030,
threads 7, urutan 640 → 256), dijalankan pengguna dengan charger terpasang dan tanpa run RAG:

```powershell
Add-Type -AssemblyName System.Windows.Forms; if ([System.Windows.Forms.SystemInformation]::PowerStatus.PowerLineStatus -ne 'Online') { Write-Error 'Charger tidak terpasang: run dibatalkan' } else { powercfg /getactivescheme *>&1 | Tee-Object -FilePath D:\SKRIPSI\cv-hasil\sweep-imgsz-speed.log; & D:\SKRIPSI\mica\.venv\Scripts\python.exe D:\SKRIPSI\mica-cv\scripts\cv_imgsz_sweep.py --data-dir D:\SKRIPSI\datasets\coco --out-dir D:\SKRIPSI\cv-hasil --speed --threads 7 --seed 20261030 *>&1 | Tee-Object -FilePath D:\SKRIPSI\cv-hasil\sweep-imgsz-speed.log -Append }
```

Perkiraan lama: 5 ukuran × 220 gambar = 1100 inferensi. Dengan waktu per gambar di atas, sekitar
220 × (51 + 70 + 67 + 23 + 19) ms ≈ 51 detik, ditambah memuat anotasi dan model. Total sekitar
**1-2 menit**.
