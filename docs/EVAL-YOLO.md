# EVAL-YOLO: evaluasi lapisan deteksi orang (YOLO) pada COCO val2017 (CV-7)

Status: **HASIL**, untuk Bab 4. Hanya `vision.imgsz` = 640 (nilai prod, docs/IMGSZ-HASIL.md).
YOLO tidak dijalankan ulang: semua angka dihitung dari deteksi tersimpan run CV-2b
(`D:\SKRIPSI\cv-hasil\20261030-151542\dets-640.json`). Kode aplikasi, config, dan RAG tidak diubah.

## 1. Tabel untuk Bab 4

Kelas orang (`catIds=[1]`), 5000 gambar COCO val2017, pycocotools `COCOeval`. CI 95% = bootstrap
persentil per gambar, B = 1000, seed 20261030 (cara CV-2b, `scripts/cv_imgsz_sweep.py`).

| Metrik | Jenis | Nilai | CI 95% |
|---|---|---|---|
| AP box, IoU 0,50:0,95, area large (maxDets 100) | **Utama, pra-registrasi** | 0,7415 | [0,7305; 0,7535] ᵃ |
| AP box, IoU 0,50:0,95, area all | Pendukung, pra-registrasi | 0,4263 | [0,4141; 0,4397] ᵇ |
| AP box, IoU 0,50:0,95, area medium | Pendukung, pra-registrasi | 0,5986 | [0,5863; 0,6108] ᵃ |
| AR box, IoU 0,50:0,95, area large (maxDets 100) | Pendukung, pra-registrasi | 0,8264 | - ᶜ |
| AP keypoint, OKS 0,50:0,95, area large (maxDets 20) | Pendukung, pra-registrasi | 0,6826 | [0,6687; 0,6973] ᵃ |
| AP box, IoU 0,50, area all | *Pelengkap, dihitung setelah data (CV-7)* | 0,6015 | [0,5855; 0,6197] ᵇ |
| AP keypoint, OKS 0,50:0,95, area all (maxDets 20) | *Pelengkap, dihitung setelah data (CV-7)* | 0,5602 | - ᶜ |

ᵃ CI dari run CV-2b (`accuracy.json`, `primary_box_ap_large` dan `support`, kolom 640).
ᵇ CI dihitung di CV-7. CI AP box all CV-7 sama persis (selisih ≤ 1e-12) dengan CI CV-2b
[0,4140977; 0,4397477], karena matriks sampel dan data evaluasinya sama. Ini cek bahwa bootstrap
CV-7 mengikuti cara CV-2b.
ᶜ Tidak ada CI: AR tidak dibootstrap di CV-2b, dan CI untuk AP keypoint all tidak diminta di CV-7.

Pembagian jenis metrik: **pra-registrasi** = ditetapkan di docs/IMGSZ.md bagian "Metrik" (commit
`c9a7213`, amandemen `4e1f9f0`) sebelum data diambil. **Pelengkap** = AP@50 box all dan AP
keypoint all ditambahkan di CV-7 setelah hasil CV-2b diketahui, supaya bisa dibandingkan dengan
angka yang lazim dilaporkan; keduanya tidak menentukan keputusan apa pun dan dilabeli demikian di
Bab 4.

## 2. Dataset

- COCO val2017 (Lin dkk., 2014), anotasi `annotations/person_keypoints_val2017.json`, semua
  5000 gambar (id 139 sampai 581781), termasuk gambar tanpa orang (bawaan `COCOeval`).
- Hanya kategori person (`category_id` 1). Area mengikuti definisi COCO: medium 32² sampai 96²
  piksel, large > 96² piksel.
- Dataset disimpan di luar repo (`D:\SKRIPSI\datasets\coco`).

## 3. Bobot dan inferensi (dari run CV-2b)

- Bobot `yolo26n-pose.pt` (`D:\SKRIPSI\mica-cv\models\yolo26n-pose.pt`), SHA-256
  `eb3bb8268828aeaf515cec23a4bfafd793944a86fe9af94ba7823609c14522a9`.
- `model.predict` per gambar, batch 1, CPU, imgsz 640, `conf` 0,001 (supaya kurva PR lengkap),
  bawaan Ultralytics untuk `iou` 0,7 dan `max_det` 300 (docs/IMGSZ.md). Aplikasi memakai `track`
  pada `conf` 0,1; lihat keterbatasan.
- Deteksi: `dets-640.json`, SHA-256
  `fdd02fcc9e46c00cb5292395fcf99485978d1b40ff4d13cfba7dfe3281f305b5`.

## 4. Lingkungan

- Inferensi dan COCOeval CV-2b (dari `accuracy.json`): Python 3.13.7, numpy 2.5.4, torch 2.14.1,
  ultralytics 8.4.178, pycocotools 2.0.11, CPU Intel64 Family 6 Model 154 (laptop dev), RAM
  16,8 GB, 7 thread torch.
- Evaluasi ulang CV-7: laptop dan Python yang sama (3.13.7), pycocotools 2.0.11.

## 5. Cara hitung dan pengecekan (CV-7)

Perintah:

```
python scripts/cv7_eval_yolo.py --data-dir D:/SKRIPSI/datasets/coco ^
  --run-dir D:/SKRIPSI/cv-hasil/20261030-151542 --log D:/SKRIPSI/cv-hasil/sweep-imgsz.log ^
  --out D:/SKRIPSI/cv-hasil/cv7-eval-yolo.json
```

- `COCOeval` dijalankan sekali untuk `bbox` dan sekali untuk `keypoints` atas `dets-640.json`.
- **Nilai titik cocok** dengan `official_stats` 640 di `accuracy.json` (ketujuh metrik, selisih
  ≤ 1e-12) dan dengan blok COCOeval pertama (640) di `sweep-imgsz.log` (3 desimal).
- AP@50 untuk bootstrap memakai `accumulate` CV-2b yang dibatasi pada ambang IoU 0,50; nilai
  tanpa bobot sama dengan `stats[1]` COCOeval (selisih ≤ 1e-9).
- Bootstrap: `bootstrap_counts(5000, 1000, 20261030)`, matriks yang sama dengan CV-2b.
- Waktu: mulai 7 November 2026 12.28.47 WIB, selesai 12.33.46 WIB. Muat GT dan deteksi 14,0 detik,
  COCOeval 27,3 detik, bootstrap (2 × 1000 `accumulate`) 256,7 detik.
- Keluaran: `D:\SKRIPSI\cv-hasil\cv7-eval-yolo.json` (SHA-256
  `f12e996c9d855bd1ceb54323195df8f85a721856129e5b160c99e300efe31738`), di luar repo, hanya angka.
- Tes: `tests/unit/test_cv7_eval_yolo.py`.

## 6. Keterbatasan

1. **COCO bukan citra ruang PMB.** COCO berisi foto umum dengan sudut, jarak, pencahayaan, dan
   kepadatan orang yang berbeda dari kamera Logi C270 di ruang PMB. Angka di atas mengukur
   kemampuan model pada orang di foto umum, bukan kinerja di ruang PMB.
2. **Uji domain PMB tidak dilakukan.** Uji itu membutuhkan foto pengunjung yang disimpan dan
   dianotasi. MICA tidak menyimpan frame kamera di mode prod, dan mengumpulkan serta menyimpan foto
   wajah pengunjung untuk anotasi adalah pemrosesan data pribadi yang harus memenuhi UU No. 27 Tahun
   2022 tentang Pelindungan Data Pribadi. Karena itu evaluasi lapisan YOLO dibatasi pada dataset
   publik.
3. AP dihitung pada `conf` 0,001 dengan `predict`, sedangkan aplikasi memakai `track` dengan
   `conf` 0,1 dan logika kehadiran (`shoulder_width`). AP adalah ukuran ranking deteksi, bukan
   akurasi keputusan "ada orang di depan meja".
4. AP keypoint COCO mencakup 17 keypoint dengan OKS, bukan keypoint bahu saja yang dipakai MICA.
5. Metrik pelengkap (AP@50 box all, AP keypoint all) dipilih setelah data dilihat; tidak dipakai
   untuk keputusan dan tidak boleh dibaca sebagai uji hipotesis.

## Rujukan

Lin, T.-Y., Maire, M., Belongie, S., Hays, J., Perona, P., Ramanan, D., Dollár, P., & Zitnick,
C. L. (2014). Microsoft COCO: Common Objects in Context. Dalam *Computer Vision – ECCV 2014*
(LNCS, Vol. 8693, hlm. 740–755). Springer.
