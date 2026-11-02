# PYVIPS-HASIL: resize OpenCV vs pyvips (CV-4)

Status: **HASIL**. Pra-registrasi ada di `docs/PYVIPS.md` (commit `406da7e`, dibuat sebelum
pengukuran). Aturan tidak diubah. Kode aplikasi, config, dan RAG juga tidak diubah.

## 1. Run

- Keluaran: `D:\SKRIPSI\cv-hasil\resize\20261102-145420\results.json` (hanya angka).
- Perintah sesuai pra-registrasi bagian 6, dijalankan 2 Nov 2026 pukul 14:54.
- Sebelum run: charger terpasang (`PowerLineStatus` Online, baterai 100%), skema
  "ASUS Recommended", **mode daya Windows Best power efficiency** (overlay AC `961cc777-…`), dan
  tidak ada proses Python lain.
- Versi dari file: pyvips 3.2.0, libvips 8.18.7, OpenCV 5.0.0, numpy 2.5.4.
- Thread bawaan: `cv2.getNumThreads()` 20, `vips_concurrency` 20.
- Data: 20 id pemanasan (dimulai 537802, 574425, 88970, …) dan 200 id terukur (dimulai 320664,
  415536, 326462, …), sama dengan `speed.json` CV-2c. 50 ulangan per gambar, jadi n = 10.000 per
  metode per kasus.

## 2. Hasil (ms per frame)

| Kasus | Metode | median | p95 |
|---|---|---|---|
| A: 640×480 → 320×240 | OpenCV `INTER_AREA` | **0,083** | 0,099 |
| A | pyvips end-to-end (`new_from_array` → `shrink(2,2)` → `numpy()`) | **0,673** | 0,801 |
| A | numpy→vips (`new_from_array`) | 0,014 | 0,019 |
| A | vips→numpy (`numpy()` dari hasil di memori) | 0,168 | 0,234 |
| B: 1920×1080 → 640×360 | OpenCV `INTER_AREA` | **0,699** | 1,070 |
| B | pyvips end-to-end (`shrink(3,3)`) | **1,322** | 1,599 |
| B | numpy→vips | 0,014 | 0,017 |
| B | vips→numpy | 0,332 | 0,437 |

- Kasus A: pyvips end-to-end sekitar 8,1 kali lebih lambat daripada OpenCV (0,59 ms per frame
  lebih lama).
- Kasus B: pyvips sekitar 1,9 kali lebih lambat (0,62 ms lebih lama).
- Konversi numpy→vips hampir nol (memori dibagi, sesuai dokumentasi yang dikutip di
  pra-registrasi). Konversi vips→numpy saja (0,17 ms di A) sudah lebih lama daripada seluruh
  resize OpenCV (0,08 ms). Sisa waktu end-to-end berasal dari menjalankan pipeline libvips
  (shrink yang dijalankan saat `numpy()`).

## 3. Kesetaraan hasil

| Kasus | Bentuk keluaran (keduanya) | Rata-rata selisih absolut piksel, rata-rata [maks] atas 200 gambar |
|---|---|---|
| A | 240×320×3 | 0,360 [0,378] |
| B | 360×640×3 | 0,599 [0,667] |

Selisihnya di bawah 1 tingkat abu-abu. Keduanya sama-sama rata-rata blok; selisih yang tersisa
diduga berasal dari pembulatan, dan ini belum diperiksa lebih lanjut.

## 4. ATURAN (docs/PYVIPS.md bagian 7, diterapkan apa adanya)

Kasus A: median(OpenCV) − median(pyvips end-to-end) = 0,083 − 0,673 = **−0,590 ms**. Syaratnya
≥ 1,0 ms, jadi **tidak terpenuhi**. **pyvips TIDAK diusulkan; OpenCV tetap dipakai.** Nilai
`decision_A` di file juga `propose_pyvips: false`.

Kasus B hanya dilaporkan: OpenCV juga lebih cepat.

## 5. Catatan dan keterbatasan

- Resize OpenCV di aplikasi (Kasus A) hanya sekitar 0,08 ms per frame, sekitar 0,2% dari jatah
  41,7 ms pada 24 fps. Di jalur pratinjau, resize bukan hambatan. CV-3 mengukur
  `render_encode_ms` sekitar 1,2-1,3 ms untuk resize + pixelate/overlay + JPEG.
- Keterbatasan dari pra-registrasi tetap berlaku: satu laptop, satu run, mode Best power
  efficiency, frame sintetis dari COCO (Kasus B berasal dari pembesaran), dan pengukuran tanpa
  beban YOLO atau thread pembaca.
- pyvips 3.2.0 dan pyvips-binary 8.18.7 masih terpasang di `D:\SKRIPSI\mica\.venv`. Keduanya tidak
  dipakai aplikasi dan tidak ada di `requirements.lock`. Mencopotnya adalah keputusan pengguna.
