# PYVIPS: pra-registrasi uji kecepatan resize OpenCV vs pyvips (CV-4)

Status: **PRA-REGISTRASI**. Ditulis dan di-commit **sebelum** pengukuran (2 Nov 2026, branch
`cv/imgsz`). Hasil akan ditulis di `docs/PYVIPS-HASIL.md`. Ini uji resize saja: kode aplikasi,
config, dan RAG tidak diubah, dan aplikasi tidak memakai pyvips.

## 1. Pertanyaan

Apakah pyvips mempercepat langkah resize pratinjau kamera MICA cukup besar untuk diusulkan masuk
aplikasi? Kasus HD (contoh dari dosen pembimbing) hanya dilaporkan.

## 2. Lingkungan

- `.venv` `D:\SKRIPSI\mica\.venv`. `pip install pyvips pyvips-binary --dry-run` (2 Nov 2026)
  hanya menampilkan "Would install pyvips-3.2.0 pyvips-binary-8.18.7", dan cffi 2.1.1 sudah
  terpasang. numpy, torch, ultralytics, dan opencv tidak berubah. Setelah dipasang, `pip freeze`
  sebelum dan sesudah hanya berbeda pada dua baris itu.
- Versi: **pyvips 3.2.0**, **libvips 8.18.7** (dari `pyvips-binary`), opencv-python 5.0.0.93,
  numpy 2.5.4, Python 3.13.7.
- Thread: bawaan, tidak diatur. `cv2.getNumThreads()` = 20 dan `vips_concurrency_get()` = 20
  (dicek setelah pemasangan). Keduanya dicatat ulang di `results.json`.
- CPU laptop dev, charger wajib terpasang, mode daya Windows dicatat manual. Tidak dijalankan
  bersamaan dengan run lain.
- pyvips tidak disebut di SDD. Pemasangan ini atas instruksi pengguna (CV-4) dan hanya untuk uji.

## 3. Kasus

| Kasus | Masukan | Keluaran | Faktor | Peran |
|---|---|---|---|---|
| A (MICA) | 640×480 BGR uint8 | lebar 320 (320×240) | 2 | **menentukan** |
| B (HD, contoh dospem) | 1920×1080 BGR uint8 | lebar 640 (640×360) | 3 | dilaporkan saja |

Kasus A meniru `PreviewRenderer.base` di `src/mica/vision/livepreview.py:93-94`:
`cv2.resize(frame, (self.width, round(h * scale)), interpolation=cv2.INTER_AREA)` dengan
`PREVIEW_WIDTH = 320` (`livepreview.py:25`). Frame kamera 640×480 diukur di CV-3.

## 4. Metode yang dibandingkan

- **OpenCV**: `cv2.resize(frame, (out_w, round(h * out_w / w)), interpolation=cv2.INTER_AREA)`,
  sama persis dengan aplikasi.
- **pyvips (end-to-end)**: `pyvips.Image.new_from_array(frame).shrink(f, f).numpy()`. Untuk faktor
  bulat, INTER_AREA adalah rata-rata blok, dan padanannya di libvips adalah `shrink` (box filter).
  `vips_resize` bawaan tidak dipakai karena reduce akhirnya memakai Lanczos3, sehingga
  interpolasinya berbeda dari aplikasi.
- **Konversi pyvips, dilaporkan terpisah**:
  - numpy→vips: `pyvips.Image.new_from_array(frame)`.
  - vips→numpy: `.numpy()` pada hasil shrink yang sudah dihitung di memori (`copy_memory()`),
    sehingga yang terukur hanya konversi. Karena libvips malas (demand-driven), perhitungan shrink
    di jalur end-to-end baru terjadi saat `.numpy()`. Waktu end-to-end adalah angka penentu.

## 5. Data

- 220 id COCO val2017 dari `speed_image_ids` (`scripts/cv_imgsz_sweep.py:189-194`,
  `default_rng(20261030).choice(sorted(ids), 220, replace=False)`). 20 id pertama untuk pemanasan,
  200 berikutnya diukur. Daftar ini sama dengan run kecepatan CV-2c, dikunci oleh algoritmenya,
  dan ditulis ke `results.json`.
- Setiap gambar dimuat sekali, di-crop tengah ke rasio 4:3 (A) atau 16:9 (B), lalu di-resize
  **sekali sebelum pengukuran** ke 640×480 atau 1920×1080. Pengecilan memakai INTER_AREA,
  pembesaran memakai INTER_CUBIC. Hampir semua gambar COCO selebar 640 px, jadi Kasus B adalah
  hasil pembesaran: isinya lebih halus daripada video HD asli. Ini keterbatasan. Waktu resize
  tidak bergantung kuat pada isi gambar.
- Gambar hanya di memori. Tidak ada frame yang ditulis ke disk; keluarannya hanya angka.

## 6. Prosedur

`python scripts/cv_resize_bench.py --data-dir D:\SKRIPSI\datasets\coco --out-dir D:\SKRIPSI\cv-hasil\resize`

1. Per kasus: siapkan frame (bagian 5).
2. Pemanasan: 20 gambar pemanasan, masing-masing satu panggilan OpenCV dan satu panggilan pyvips
   end-to-end.
3. Untuk setiap 200 gambar terukur, berurutan per gambar: 50 ulangan OpenCV, 50 ulangan pyvips
   end-to-end, 50 ulangan numpy→vips, dan 50 ulangan vips→numpy. Setiap panggilan diukur dengan
   `time.perf_counter`, jadi ada 10.000 sampel per metode per kasus.
4. Statistik: median dan p95 (persentil numpy, interpolasi linear) dalam ms per metode per kasus.
5. Kesetaraan: per gambar dihitung rata-rata selisih absolut piksel antara keluaran OpenCV dan
   pyvips. Dilaporkan rata-rata dan maksimumnya atas 200 gambar, beserta bentuk keluaran.

## 7. ATURAN KEPUTUSAN (dikunci)

- **pyvips diusulkan masuk aplikasi hanya jika di Kasus A
  median(OpenCV) − median(pyvips end-to-end) ≥ 1,0 ms per frame.**
  Angka 1 ms adalah nilai keputusan pengguna, sekitar 2,4% dari jatah 41,7 ms per frame pada
  24 fps. Bila tidak terpenuhi, OpenCV tetap dipakai.
- Kasus B, p95, waktu konversi, dan selisih piksel hanya dilaporkan dan tidak menentukan.
- Bila selisih piksel di A besar (lebih dari 1 tingkat abu-abu rata-rata), hal itu dicatat sebagai
  keterbatasan, tetapi aturan tetap diterapkan apa adanya. "Diusulkan" berarti usulan untuk
  keputusan berikutnya (SDD dan pengguna), bukan perubahan otomatis.

## 8. Sumber (dokumentasi resmi, dibaca 2 Nov 2026; hanya yang tertulis di sana)

- libvips `vips_shrink`, <https://www.libvips.org/API/current/method.Image.shrink.html>:
  "Shrink `in` by a pair of factors with a simple box filter." dan "For non-integer factors,
  [`vips_shrink()`] will first shrink by the integer part with a box filter, then use
  [`vips_reduce()`] to shrink by the remaining fractional part."
- libvips `vips_resize`, <https://www.libvips.org/API/current/method.Image.resize.html>:
  "[`vips_resize()`] normally uses [`VIPS_KERNEL_LANCZOS3`] for the final reduce, you can change
  this with `kernel`." Ini alasan `resize` tidak dipakai (bagian 4).
- pyvips, <https://libvips.github.io/pyvips/intro.html>: "You can use [`new_from_array()`] to
  create a pyvips image from a NumPy array or a PIL image." dan "a conversion from a pyvips image to
  a NumPy array can be obtained with the [`numpy()`] method of the [`pyvips.Image`] class or from
  the numpy side with `numpy.asarray()`." Juga: "Pixels will not be read until you have built a
  pipeline of operations and connected it to an output."
- pyvips `new_from_array`, <https://libvips.github.io/pyvips/vimage.html>: "If the input object is
  an array-like object, a new image is created from the object’s data and shape. The memory is
  shared except in the following cases:" (salah satunya bila memori tidak contiguous; frame di
  uji ini contiguous).
- libvips concurrency, <https://www.libvips.org/API/current/func.concurrency_set.html>: "The special
  value 0 means “default”. In this case, the number of threads is set by the environment variable
  `VIPS_CONCURRENCY`, or if that is not set, the number of threads available on the host machine."
- Tidak ada klaim kecepatan dari dokumentasi yang dipakai sebagai dasar. Kecepatan hanya diambil
  dari pengukuran ini.

## 9. Keterbatasan (diketahui sebelum data)

Satu laptop, satu run, dan mode daya Windows apa adanya (dicatat). Frame sintetis dari COCO, bukan
kamera. Kasus B berasal dari pembesaran. Waktu diukur per panggilan di satu thread Python tanpa
beban YOLO atau thread pembaca, sedangkan di aplikasi resize berjalan bersamaan dengan inferensi
(CV-3). Hasilnya bisa berbeda di bawah beban.
