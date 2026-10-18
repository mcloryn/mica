# Optimasi biaya pratinjau kamera UI web (Langkah 38): pra-registrasi

Ditetapkan 18 Oktober 2026, sebelum diagnosis dan pengukuran Langkah 38. Aturan di bawah tidak
diubah setelah data ada. Perubahan karena hasil diagnosis hanya boleh lewat amandemen bertanggal
di akhir dokumen ini, SEBELUM kandidat yang bersangkutan diukur. Penyimpangan ditulis di hasil.

## Latar

Langkah 37 (results/ADR-19/ui-l37-20261018-145911) mengukur pratinjau `public` dengan sumber dan
detektor palsu. Dibanding pratinjau `off`, pratinjau menambah RAM USS diam +215,18 MB (proses GPU
Edge 53,9 -> 213,8 MB) dan CPU diam +8,91 poin. Laptop kiosk lebih lemah dari laptop dev, jadi
biaya ini harus ditekan sebelum E-09.

Privasi tidak boleh dilemahkan:
- pixelate public tetap aman-gagal;
- tidak ada gambar ke disk;
- server hanya 127.0.0.1, dengan cek Origin pada `/ws` dan `/preview`.

## Kondisi sekarang (pembanding, versi 37c, commit 21e25ae)

- Proses kamera membuat JPEG 320 px di memori setiap 1/`ui.preview_fps` detik (5), lalu
  memasukkannya ke antrean maxsize 1.
- Server memompa JPEG ke WebSocket `/preview` sebagai pesan biner (bukan base64).
- Browser menerima `Blob`, membuat `URL.createObjectURL`, mengganti `img.src`, lalu me-revoke URL
  lama tepat setelah `src` diganti.

## Kandidat (urutan uji)

- K1: tetap pesan biner WebSocket; tampil lewat `createImageBitmap(blob)` ke satu `<canvas>`,
  lalu `bitmap.close()` setelah digambar.
  - Tidak ada pergantian `img src` dan tidak ada object URL.
  - Frame dibuang bila frame sebelumnya belum selesai di-decode atau digambar (maksimal satu
    frame dalam proses).
  - Pembanding: kondisi sekarang.
- K2: switch Edge `--disable-gpu-compositing`, hanya bila setelah K1 biaya di proses GPU masih
  besar.
  - Sebelum diukur, keberadaan switch dicek di sumber Chromium dan URL-nya dicatat.
  - Pembanding: konfigurasi terbaik sebelum K2.
- K3: perbaikan lain bila diagnosis menunjukkan penyebab lain (mis. JPEG dibuat ulang padahal
  frame sama). Ditulis sebagai amandemen sebelum diukur.
- Bila beberapa kandidat lolos sendiri-sendiri dan bisa digabung, gabungannya diuji lagi dengan
  aturan yang sama (seperti putaran 2 Langkah 32).
- Info saja (bukan kandidat, tanpa keputusan): `ui.preview_fps` 2 vs 5 dengan cara tampil
  terbaik. Nilai config tidak diubah; keputusan laju ada di pemilik proyek.
- Laporan (bukan kandidat): konfigurasi akhir vs pratinjau `off`, diukur selang-seling.

## Metrik

Bench tahap 1 yang sama (`scripts/ui_bench.py` `run_once`): Edge kiosk, diam 60 s, lalu 20
pertanyaan ketik; pekerja suara dan pipeline palsu; proses kamera asli dengan sumber dan
detektor palsu (`--fake-camera`); `ui.camera_preview` `public`, `ui.preview_fps` 5 kecuali
disebut lain.

- RAM USS diam total (pohon proses), dirinci per proses: inti Python (Flask + controller),
  proses kamera, Edge browser, GPU, renderer, dan lainnya.
- CPU diam total (persen satu inti, rata-rata 60 s), dirinci per proses yang sama.
- p95 jeda render per ulangan (ack setelah `requestAnimationFrame`, sama dengan tahap 1).

## Prosedur

- Daya AC wajib (bench berhenti bila baterai).
- 10 ulangan per kondisi.
- Kondisi diukur BERSELANG-SELING dalam sesi yang sama dengan pembandingnya (A, B, A, B, ...).
  Alasannya: pelajaran Langkah 37, baseline bergeser antar-sesi.
- Versi file statis pembanding dilayani dari salinan commit pembanding (`--static-dir`); server
  dan logika sama.
- Hasil: `results/ADR-19/ui-preview-opt-<tanggal-jam>/`.

## Aturan keputusan

Kandidat "lebih baik" dari pembanding bila ketiga syarat ini terpenuhi:

1. median salah satu metrik (RAM total ATAU CPU total) berada DI BAWAH minimum pembanding;
2. median metrik yang lain TIDAK di atas maksimum pembanding;
3. median p95 jeda TIDAK di atas maksimum pembanding.

Kandidat yang lolos menjadi pembanding untuk kandidat berikutnya. Bila tidak ada yang lolos,
kondisi sekarang tetap dan dilaporkan apa adanya.

## Diagnosis (sebelum kandidat, tanpa mengubah kode)

1. Cara kirim dan tampil sekarang (lihat "Kondisi sekarang").
2. Uji tumbuh 15 menit pratinjau `public` (diam, tanpa pertanyaan): RAM USS dan CPU per proses
   setiap 30 detik. Rata-rata 5 menit pertama dibandingkan dengan 5 menit terakhir.
   - Disebut "naik terus (bocor)" bila rata-rata 5 menit terakhir lebih tinggi dan kemiringan
     regresi 10 menit terakhir positif.
   - Selain itu disebut "mendatar (plafon)". Angkanya dilaporkan apa adanya.
3. CPU tambahan per proses (kamera, server, Edge GPU/renderer/browser) dari uji tumbuh dan dari
   ulangan pembanding.

Uji tumbuh 15 menit diulang untuk konfigurasi akhir.

## Amandemen

### Amandemen 1 (18 Okt 2026, setelah diagnosis, sebelum mengukur K1)

Diagnosis uji tumbuh 15 menit kondisi sekarang
(`results/ADR-19/ui-preview-opt-20261018-1712/01-diagnosis-grow`):

- GPU Edge naik dari 55,6 ke +-210 MB dalam 60 s pertama (puncak 233,6 MB pada 120 s), lalu
  bertahan di 197-208 MB sampai menit 15. Aturan mekanis tetap menamainya "naik terus"
  (rata-rata 5 menit terakhir 207,4 > 5 menit pertama 194,8 karena kenaikan awal; kemiringan 10
  menit terakhir +0,77 MB/menit).
- Renderer naik pelan dari 21 ke 30 MB (+0,3 MB/menit).
- CPU rata-rata per proses: kamera 1,28%, Edge GPU 2,83%, renderer 2,46%, browser 1,31%, inti
  Python 0,87%.

Biaya utama ada di sisi tampil Edge (GPU + renderer), bukan di pembuatan JPEG. Sumber palsu hampir
selalu statis, sedangkan kamera asli selalu berubah, jadi "JPEG sama dibuat ulang" bukan penyebab
yang relevan untuk kiosk. Kandidat K1 dan K2 tidak diubah; K3 tidak ada.

Switch K2 dicek: `kDisableGpuCompositing[] = "disable-gpu-compositing"` ("Prevent the compositor
from using its GPU implementation") di
https://chromium.googlesource.com/chromium/src/+/HEAD/content/public/common/content_switches.cc,
dicek 18 Okt 2026.
