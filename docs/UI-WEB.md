# Percobaan UI web vs PySide6 (ADR-19): protokol pra-registrasi

Ditetapkan 17 Oktober 2026, sebelum kode UI web ditulis dan sebelum pengukuran apa pun. Berlaku
di branch `coba-ui-web`; branch ini tidak di-merge ke main kecuali aturan di bawah terpenuhi dan
pemilik proyek memutuskannya. Penyimpangan dari protokol wajib ditulis di hasil.

## Tujuan

Membandingkan UI web (Microsoft Edge + server lokal) dengan UI PySide6 untuk ADR-19, yang masih
berstatus Provisional. Kedua UI memakai KioskController dan ViewModel yang sama; yang dibandingkan
hanya lapisan tampilan.

## Tahap 1: laptop dev, pekerja palsu dan pipeline palsu

UI web LOLOS tahap 1 hanya bila (a) dan (b) terpenuhi.

(a) Fungsional:

- layar penuh lewat Edge kiosk;
- semua tampilan ViewModel muncul: layar awal, percakapan, status, transkripsi, sumber beserta
  tanggal, pemberitahuan kamera/AI, indikator kamera dan mikrofon;
- ketik, tombol topik, dan tombol bicara menghasilkan event controller yang sama dengan PySide6
  (dibuktikan dengan tes);
- tidak ada aset yang dimuat dari internet;
- server hanya mendengarkan di 127.0.0.1.

(b) Kinerja: p95 jeda tampil × 3 ≤ 1,0 detik.

- ×3 adalah perkiraan pemilik proyek bahwa laptop kiosk kira-kira 1/3 kecepatan laptop dev
  (kasus terburuk, asumsi kasar).
- Batas 1 detik: Nielsen, NN/g, "The 3 Response Time Limits in Interaction Design" (2019),
  bukti [52], tingkat D.

Gagal (a) atau (b) -> BATAL: ADR-19 tetap PySide6, dan branch disimpan sebagai catatan.

Dilaporkan, tetapi tidak menentukan di tahap 1: RAM USS, CPU saat diam, dan waktu mulai sampai
layar pertama.

## Tahap 2: E-09, laptop kiosk nyata, kamera dan suara asli

UI web dipakai hanya bila anggaran latensi SDD 3.3 dan K-3 tetap terpenuhi.

- Bila web dan PySide6 sama-sama memenuhi, pilihan adalah keputusan desain pemilik proyek
  (tampilan dan perawatan). Keputusan itu ditulis sebagai keputusan desain, bukan hasil
  eksperimen.
- Bila hanya PySide6 yang memenuhi -> PySide6.

## Keterbatasan

- Faktor ×3 adalah perkiraan, bukan hasil ukur.
- Pengukuran tahap 1 memakai pekerja palsu, jadi perebutan CPU dengan kamera, STT, dan BGE-M3
  baru terlihat di E-09.

## Catatan setelah tahap 1

Ditulis 17 Oktober 2026, setelah tahap 1 LOLOS (results/ADR-19/ui-bench-20261017-192424) dan
UI web di-merge ke master sebagai opsi `ui.backend: web`. Bawaan tetap `pyside6` di dev.yaml
dan kiosk.yaml sampai E-09; pilihan akhir mengikuti aturan tahap 2 di atas. Aturan tahap 1 dan
tahap 2 tidak diubah.

### Server web diganti dari aiohttp ke Flask

- Keputusan pemilik proyek, 17 Okt 2026: lebih terbiasa dengan Flask, supaya bisa menjelaskan
  kodenya. Ini keputusan perawatan, bukan hasil eksperimen.
- Flask 3.1.3 (BSD-3-Clause) + flask-sock 0.7.0 (MIT), yang menarik Werkzeug 3.1.9
  (BSD-3-Clause), simple-websocket 1.1.0 (MIT), dan wsproto 1.3.2 (MIT). Versi dan lisensi dicek
  di PyPI 17 Okt 2026.
- Perilaku sama dengan versi aiohttp: hanya 127.0.0.1, halaman dan static dari paket, Origin asing
  ditolak 403, ViewModel dikirim sebagai JSON saat berubah, ack setelah requestAnimationFrame,
  event input sama dengan PySide6, tanpa frame/audio. Bedanya: controller sekarang dijalankan
  satu thread latar (poll 50 ms); thread koneksi WebSocket hanya mengantre event.
- Pengukuran tahap 1 diulang untuk web (results/ADR-19/ui-bench-flask-20261017-224241): p95 jeda
  tampil × 3 = 0,038 s ≤ 1,0 s, keputusan mekanis LOLOS. Laptop berjalan dengan baterai (71–72%),
  sedangkan run aiohttp dengan listrik AC, jadi angka keduanya tidak sepenuhnya sebanding.
  Jumlah pembaruan per ulangan 59 (aiohttp 40) karena tampilan READY sekarang terkirim
  tersendiri sebelum pertanyaan berikutnya.

### Keterbatasan: server bawaan Werkzeug

UI web memakai server bawaan Werkzeug (`werkzeug.serving.make_server`, `threaded=True`, hanya
127.0.0.1, tanpa reloader dan debugger; dibuktikan tes). Dokumentasi Flask menyatakan server
ini tidak untuk produksi. Server lain tidak dipakai karena:

- flask-sock hanya mendukung server Werkzeug, Gunicorn, Eventlet, dan Gevent
  (https://flask-sock.readthedocs.io/en/latest/web_servers.html, dicek 17 Okt 2026).
- Gunicorn tidak mendukung Windows, kecuali lewat WSL
  (https://flask.palletsprojects.com/en/stable/deploying/gunicorn/, dicek 17 Okt 2026).
- Waitress mendukung Windows, tetapi tidak ada di daftar flask-sock. simple-websocket hanya
  mengambil soket dari Werkzeug, Gunicorn, Eventlet, atau Gevent (simple_websocket/ws.py,
  `Server.__init__`).
- Gevent butuh `gevent.monkey.patch_all()` di awal program
  (https://flask.palletsprojects.com/en/stable/gevent/, dicek 17 Okt 2026). Patch itu mengubah
  threading dan socket di seluruh proses, termasuk pekerja vision/suara dan executor controller.
  Gevent juga bukan library yang disebut SDD. Flask sendiri menyarankan Gunicorn/uWSGI daripada
  gevent langsung (halaman yang sama).
- Peringatan resmi: "Do not use the development server when deploying to production. It is
  intended for use only during local development. It is not designed to be particularly
  secure, stable, or efficient." (https://flask.palletsprojects.com/en/stable/deploying/,
  dicek 17 Okt 2026; https://werkzeug.palletsprojects.com/en/stable/serving/, dicek 17 Okt
  2026).
- Risiko dibatasi dengan: bind hanya 127.0.0.1, satu pengguna lokal (Edge di laptop kiosk), Origin
  WebSocket diperiksa, CSP 'self', tanpa debugger (`app.debug` False) dan tanpa reloader. Risiko
  "tidak stabil" dicek pada sesi panjang di E-09.

### Edge berhenti menggambar saat jendela tertutup

Konteks: pada run pertama Langkah 29, ulangan web ke-2 mendapat 0 dari 40 ack, kemungkinan karena
jendela Edge tidak di depan.

- Switch yang dipakai (`RENDERING_SWITCHES`, mica/webui/browser.py), semuanya diverifikasi
  17 Okt 2026 di content/public/common/content_switches.cc (source.chromium.org, dibaca lewat
  cermin resmi chromium.googlesource.com): `--disable-backgrounding-occluded-windows`
  (konstanta `kDisableBackgroundingOccludedWindowsForTesting`),
  `--disable-renderer-backgrounding`, `--disable-background-timer-throttling`. Tidak ada
  kandidat yang ditolak.
- Uji `scripts/ui_bench.py --cover-window` (results/ADR-19/ui-bench-cover-20261017-225006/,
  server Flask, pekerja dan pipeline palsu, baterai 62–66%): setelah layar pertama tampil,
  Notepad dibuka, dimaksimalkan, dan dibawa ke depan selama masa diam 60 s dan 20 pertanyaan,
  lalu ditutup.

| ulangan | tanpa switch: ack / pembaruan | p95 | dengan switch: ack / pembaruan | p95 |
| --- | --- | --- | --- | --- |
| 1 | 0 / 59 | - | 59 / 59 | 12,6 ms |
| 2 | 59 / 59 | 10,7 ms | 59 / 59 | 13,9 ms |
| 3 | 59 / 59 | 11,9 ms | 59 / 59 | 14,5 ms |

- Keterbatasan:
  - Notepad yang dimaksimalkan menutup 95% jendela Edge kiosk (1536 × 864). Sisanya, strip
    setinggi taskbar, tertutup taskbar Windows.
  - Pada run tanpa switch, Notepad tidak menjadi jendela aktif setelah `SetForegroundWindow`
    (3 dari 3 ulangan). Urutan tumpukan jendela tidak diukur, jadi tidak diketahui apakah
    Notepad benar-benar di atas Edge. Ack yang tetap masuk di ulangan 2–3 bisa berarti Edge
    tidak tertutup. Pada run dengan switch, Notepad menjadi jendela aktif di 3 dari 3 ulangan.
    Jadi kondisi kedua kelompok tidak identik.
  - Dengan 3 ulangan per kelompok, hasil ini hanya menunjukkan bahwa masalahnya bisa muncul
    tanpa switch (1 dari 3) dan tidak muncul dengan switch (0 dari 3). Hasil ini belum
    membuktikan bahwa switch menghilangkannya. Perlu dicek lagi di E-09.
- Setelah 20 pertanyaan, RAM web naik dari 196 MB ke 250 MB (median USS, run aiohttp; run Flask:
  197 → 255 MB). Perlu dicek pada sesi panjang di E-09, apakah ini kebocoran atau hanya
  pemanasan.

## Keputusan pemilik proyek (17 Okt 2026)

- UI web (Flask + Edge kiosk) dipilih sebagai UI utama MICA sebelum tahap 2. Dasarnya data
  tahap 1 (LOLOS, results/ADR-19/ui-bench-20261017-192424) dan preferensi pemilik proyek. Ini
  penyimpangan dari protokol di atas, yang menetapkan pilihan baru dibuat setelah tahap 2.
  Penyimpangan ini wajib diungkap di Bab 3. `ui.backend: web` di dev.yaml dan kiosk.yaml.
- Peran E-09 berubah menjadi verifikasi: anggaran latensi SDD 3.3 dan K-3 harus tetap
  terpenuhi dengan UI web. Bila gagal, optimasi dulu; PySide6 adalah jalan keluar terakhir.
- PySide6 dibekukan sebagai cadangan. Kode dan tesnya tetap ada dan tetap harus lulus, tetapi
  tidak dikembangkan lagi. Keputusan menghapusnya dibuat setelah E-09.
- Aturan tahap 1 dan tahap 2 di atas tidak diubah.

## Optimasi putaran 2 (ditetapkan 17 Okt 2026 sebelum data)

- Alasan: aturan putaran 1 (3 ulangan, median; results/ADR-19/ui-opt-20261017-232949)
  terlalu peka terhadap variasi CPU diam antar-ulangan. Keputusan putaran 1 tetap berlaku dan
  tidak diubah.
- Kandidat: dua switch yang dibatalkan di putaran 1 karena kenaikan kecil CPU/p95 walau
  menghemat RAM:
  - k1 = `--disable-component-extensions-with-background-pages`;
  - k2 = `--renderer-process-limit=1` (nilai sama dengan putaran 1).
- Baseline: konfigurasi master sekarang (termasuk `--disable-component-update`).
- Pengukuran: 10 ulangan per kondisi (baseline, k1, k2) dengan bench tahap 1 yang sama
  (`scripts/ui_bench.py`, pekerja dan pipeline palsu), daya AC wajib. Urutan kondisi
  diselang-seling (baseline, k1, k2, baseline, k1, k2, ...) supaya perubahan keadaan laptop
  tersebar rata.
- Sebuah metrik dihitung "naik" hanya bila median kandidat > nilai maksimum 10 ulangan
  baseline. Metrik "turun" bila median kandidat < median baseline. Metrik per ulangan: RAM USS
  diam, CPU diam, waktu mulai, p95 jeda tampil ulangan itu.
- Kandidat dipertahankan bila RAM USS diam ATAU CPU diam turun, tidak ada metrik (RAM diam,
  CPU diam, waktu mulai, p95 jeda) yang naik, dan semua tes + aturan (a) tahap 1 lulus.
- Bila kedua kandidat lolos, gabungan keduanya diuji dengan aturan yang sama (10 ulangan,
  selang-seling dengan baseline).
- Hasil putaran 1 dan 2 dilaporkan terpisah di Bab 3.

## Sistem desain UI kiosk (Langkah 37, 18 Okt 2026)

Keputusan desain pemilik proyek, bukan hasil eksperimen. Tata letak: header (logo atau placeholder
"MICA", judul, pil status, indikator kamera/mikrofon, pemberitahuan ringkas permanen), kolom kiri
+-35% (kartu kamera dengan cincin warna status, info target, ajakan atau pesan kamera mati),
kolom kanan (sapaan dan 6 kartu topik, lalu percakapan, chip topik, dan bilah bawah: mikrofon,
kotak ketik, Kirim). Layar < 1100 px (nilai desain): kolom kiri menjadi strip kecil di atas.

- Token: `src/mica/webui/static/tokens.css`, satu-satunya tempat warna, jarak, radius, bayangan,
  dan ukuran huruf. Palet netral sementara dengan satu aksen (`--accent` #1e4fd8), mudah
  diganti warna resmi Mikroskil.
- Kontras (rumus WCAG 2.1, `python scripts/ui_contrast.py`; SC 1.4.3 AA 4,5:1, dicek di
  https://www.w3.org/TR/WCAG21/ versi REC-WCAG21-20250506 pada 18 Okt 2026):

| teks | latar | kegunaan | rasio |
| --- | --- | --- | --- |
| `--text` #1a1d23 | `--surface` #ffffff | teks utama di kartu | 16,88:1 |
| `--text` | `--bg` #f4f5f7 | teks utama di latar | 15,48:1 |
| `--text-muted` #4a5260 | `--surface` | teks sekunder | 7,87:1 |
| `--text-muted` | `--bg` | teks sekunder di latar | 7,22:1 |
| `--text-muted` | `--surface-sunken` #eceef2 | teks di bidang input/kamera | 6,78:1 |
| `--text` | `--surface-sunken` | chip, input | 14,53:1 |
| `--text` | `--accent-soft` #e6edfd | gelembung pengunjung | 14,39:1 |
| `--text` | `--notice-bg` #fff7e8 | kartu penolakan | 15,85:1 |
| putih | `--accent` #1e4fd8 | tombol utama, pil Berbicara | 6,63:1 |
| putih | `--accent-strong` #173fae | tombol ditekan | 8,90:1 |
| putih | `--status-ready` #4a5260 | pil Siap | 7,87:1 |
| putih | `--status-listening` #0f7a4d | pil Mendengarkan | 5,37:1 |
| putih | `--status-thinking` #9a4a00 | pil Berpikir | 6,26:1 |

- Font: Plus Jakarta Sans (SIL Open Font License 1.1), dari repositori resmi
  https://github.com/tokotype/PlusJakartaSans, commit 18d1cd2f7ea10481919d2f05c1f7064b7307fc26
  (2024-01-18), file `fonts/webfonts/PlusJakartaSans[wght].woff2` disimpan sebagai
  `static/fonts/PlusJakartaSans-wght.woff2` (sha256 49c62cf1...c8539d2) beserta `OFL.txt`
  (sha256 995c7199...ab08a99); diunduh dan dicek 18 Okt 2026. Cadangan: Segoe UI, system-ui.
  Ukuran dasar 125% x `ui.font_scale` (20 px pada skala 1) untuk dibaca dari +-1 m.
- Target sentuh minimal 44 x 44 px CSS (`--touch-min`), mengikuti WCAG 2.1 SC 2.5.5 Target Size
  (Level AAA): "The size of the target for pointer inputs is at least 44 by 44 CSS pixels"
  (https://www.w3.org/TR/WCAG21/#target-size, dicek 18 Okt 2026). Tombol utama 64 px, mikrofon
  88 px.
- Logo: `ui.logo_path` (file lokal png/svg/jpg/webp, bukan URL; null = placeholder teks "MICA"),
  dilayani di `/logo`.
- Kartu dan chip topik (`ui.topics`: Program Studi, Biaya, Beasiswa, Pendaftaran, Fasilitas,
  Lokasi) hanya mengisi kotak pertanyaan dengan nama topik; tidak mengirim pertanyaan. `mica check`
  ikut memeriksa `ui.topics` terhadap set uji resmi.
- Gerak: animasi CSS hanya saat status Mendengarkan, Berpikir, dan Berbicara; tidak ada animasi
  atau timer JS saat Siap; `prefers-reduced-motion` mematikan semua animasi.
- Penolakan (jawaban MICA tanpa sumber) tampil sebagai kartu krem yang sopan, bukan galat.

## Pratinjau kamera UI kiosk (Langkah 37, 18 Okt 2026)

- `ui.camera_preview`: `off` | `public` | `debug`. kiosk.yaml `public`, dev.yaml `debug`; config
  menolak `debug` saat `app.mode: kiosk`.
- Proses kamera membuat gambar lebar 320 px yang dicerminkan, di-JPEG di memori
  (`mica/vision/livepreview.py`), dengan laju `ui.preview_fps` dari frame kamera dan hasil
  deteksi TERAKHIR (tidak ada inferensi YOLO tambahan). `public`: seluruh gambar di-pixelate
  (blok `ui.preview_pixel_block` px) kecuali kotak target; tanpa target seluruh gambar
  di-pixelate. Overlay public: kotak target + label warna, tanpa angka. `debug`: tanpa
  pixelate, semua kotak, area baju, label warna, skor, lebar bahu.
- Nilai coba DESAIN (bukan hasil eksperimen): `ui.preview_pixel_block` 16, `ui.preview_fps` 5.
  Sejak Langkah 38 `ui.preview_fps` 10 (keputusan desain pengguna; lihat bagian Langkah 38).
- Jalur: antrean multiprocessing terpisah dari bus event (`Bus.preview`, maxsize 1, frame lama
  dibuang); bus event tetap tanpa frame (SDD M-13). Server memompa antrean ke WebSocket
  `/preview` (pesan biner), hanya 127.0.0.1 dengan cek Origin yang sama dengan `/ws`; CSP
  `img-src 'self' blob:`. Tidak ada endpoint yang menyimpan gambar; tidak ada gambar ke disk.
- Info target di kolom kiri berasal dari event `PersonArrived`/`PersonLeft` lewat hook tampilan
  controller (bukan dari gambar), jadi tetap tampil walau pratinjau `off`.
- Sumber gambar palsu (dev): `python -m mica.webui --fake-workers --fake-camera
  [--fake-pipeline]` menjalankan proses kamera asli dengan adegan buatan (siluet tanpa wajah,
  `mica/vision/fakesource.py`) dan nilai coba SDD bagian 12 untuk dwell/leave/rasio bahu.

## Hasil ukur ulang Langkah 37 (18 Okt 2026)

`python scripts/ui_preview_bench.py --reps 10` -> `results/ADR-19/ui-l37-20261018-145911/`
(bench tahap 1 yang sama, AC, 10 ulangan per kondisi selang-seling; aturan putaran 2).

Kondisi 1 (desain baru, pratinjau off) vs baseline `ui-opt2-combo-20261018-042512` (k1+k2):

| metrik | c1 median | baseline median | baseline maks | hasil |
| --- | --- | --- | --- | --- |
| RAM USS diam (MB) | 177,85 | 175,13 | 176,48 | naik |
| CPU diam (%) | 4,74 | 4,10 | 5,60 | tetap |
| waktu mulai (s) | 2,457 | 2,463 | 2,492 | turun |
| p95 jeda tampil (ms) | 4,59 | 3,04 | 7,37 | tetap |

Penyebab RAM "naik" dicari (`results/ADR-19/ui-l37-diag-20261018/`): UI lama pada sesi yang sama
juga 177,3 MB (pergeseran keadaan laptop sejak pagi); selisih UI baru vs lama +-2 MB seluruhnya di
renderer Edge, +-1,8 MB di antaranya font web (tanpa @font-face 177,25 MB). Font wajib (Bagian
A.3), jadi tidak dihapus; tidak ada animasi atau timer saat Siap. CPU diam tidak naik.

Kondisi 2 (pratinjau public, `ui.preview_fps` 5 dan blok 16 nilai coba, proses kamera asli +
sumber dan detektor palsu) vs kondisi 1, median:

| metrik | c1 | c2 | selisih |
| --- | --- | --- | --- |
| RAM USS diam (MB) | 177,85 | 393,03 | +215,18 |
| CPU diam (%) | 4,74 | 13,65 | +8,91 |
| waktu mulai (s) | 2,457 | 2,504 | +0,048 |
| p95 jeda tampil (ms) | 4,59 | 4,68 | +0,10 |

Per jenis proses (median CPU % / USS MB, c1 -> c2): proses GPU Edge 0,53/53,9 -> 3,65/213,8;
renderer 0,03/14,4 -> 2,67/21,7; browser Edge 3,24/47,3 -> 4,61/51,0; Flask + controller
0,42/48,8 -> 0,85/49,5; proses kamera (sumber palsu, tanpa YOLO) 0 -> 1,93/42,5. Kenaikan RAM
terbesar ada di proses GPU Edge (+160 MB) yang mendekode gambar pratinjau 5 fps. Dilaporkan apa
adanya; keputusan pratinjau public di E-09 (docs/E-09.md, amandemen 1).

Catatan alat: di bench, proses anak membaca perintah dari pipa stdin di thread lain; pekerja
multiprocessing yang di-spawn saat itu tertahan di awal start pada Windows (USS 3 MB, CPU 0).
`ui_bench.detach_stdin` membaca perintah dari salinan fd dan mengarahkan stdin OS ke NUL sebelum
pekerja dimulai. Aplikasi (`python -m mica`) tidak membaca stdin, jadi tidak terdampak.

Tangkapan layar: `docs/ui-screens/` (`python scripts/ui_screens.py`, Edge headless + CDP, sumber
gambar palsu tanpa wajah orang sungguhan).

## Langkah 37b: gaya web konvensional (18 Okt 2026)

Masukan pemilik proyek: padding/margin terlalu besar, terlihat seperti app, terlalu "AI". Tata
letak dua kolom, logika, ViewModel, dan pratinjau tidak diubah; bagian "Sistem desain" di atas
digantikan oleh nilai berikut (riwayat tetap di atas).

- Token (`static/tokens.css`): latar #f6f7f9, panel putih, garis 1 px #d0d7de, teks #1f2328,
  teks sekunder #57606a, aksen biru tua #1f4e8c hanya untuk tombol utama, tombol topik, dan
  tautan. Jarak 4/8/12/16/24 px. Radius 4/6 px, gelembung chat 10 px. Tanpa bayangan.
  Huruf dasar 16 px, sekunder 14 px, percakapan 17 px, judul navbar dan sapaan 18 px,
  line-height 1,5. Lebar isi maksimum 1440 px.
- Font: font sistem (Segoe UI di Windows, lalu system-ui). Plus Jakarta Sans dan OFL.txt dihapus.
  Alasannya: tampilan web/admin biasa memakai font sistem; tidak ada file font dan lisensi
  yang perlu dirawat; dan di Langkah 37 font web terukur menambah +-1,8 MB RAM renderer.
- Header = navbar (placeholder/logo + judul di kiri; status titik + teks, indikator kamera
  dan mikrofon di kanan). Pemberitahuan kamera/AI = baris teks kecil di bawah navbar.
- Sapaan = pesan pertama di percakapan (18 px). Topik = tombol outline biasa di atas bilah
  input. Penolakan = pesan biasa dengan ikon info kecil.
- Kamera = panel biasa berjudul "Kamera" dengan badge Aktif/Tidak aktif dan bingkai 1 px.
- Mikrofon = tombol biasa (ikon + "Bicara"), tinggi sama dengan Kirim (44 px).
- Ikon: SVG garis inline lokal (kamera, mikrofon, info), satu gaya, tanpa pustaka.
- Dihapus: hero sapaan 45 px, kartu topik besar berbayang, pil status besar, cincin kamera 6 px
  berwarna status, tombol mic bulat 88 px dengan bayangan dan denyut, input/tombol pil 64 px,
  radius 10-24 px, bayangan, ukuran dasar 20 px. Gradasi, blur, dan emoji sudah tidak ada sejak
  awal.
- Animasi tersisa: titik status berkedip saat Mendengarkan dan titik tiga saat Berpikir. Keduanya
  berhenti saat Siap; prefers-reduced-motion mematikannya.
- Kontras (`python scripts/ui_contrast.py`): teks 15,80 di panel dan 14,74 di latar; teks sekunder
  6,39 dan 5,96; gelembung MICA 14,35 (teks kecil 5,81); gelembung pengunjung 13,53; tombol utama
  8,31 (hover 10,87); tombol topik/tautan 8,31.
- Ukur ulang (`python scripts/ui_ab_bench.py --before db85a13 --reps 10`,
  results/ADR-19/ui-37b-20261018-155237; AC, pratinjau off, selang-seling, aturan putaran 2):
  median RAM USS diam 179,28 -> 176,73 MB (turun), CPU diam 5,16 -> 4,73% (turun), waktu mulai
  2,478 -> 2,484 s (tetap). p95 jeda tampil 4,88 -> 5,57 ms, di atas maksimum versi sebelum
  (5,20 ms), jadi "naik"; nilainya tetap jauh di bawah batas tahap 1 (x3 = 17 ms <= 1 s).
- Tangkapan layar: `docs/ui-screens/` (1366x768 dan 1920x1080; sebelum di `before-37b/`).

## Langkah 37c: karakter lewat warna sesi (18 Okt 2026)

Masukan pemilik proyek: layout sudah disukai tetapi terlalu polos. Tata letak dua kolom, logika
M-09, event, dan pratinjau tidak diubah (kecuali label overlay debug).

- Font: Atkinson Hyperlegible (Braille Institute), SIL OFL 1.1 (Copyright 2020 Braille Institute
  of America, Inc.). Sumber: repositori upstream resmi
  https://github.com/googlefonts/atkinson-hyperlegible, commit
  1cb311624b2ddf88e9e37873999d165a8cd28b46. google/fonts (ofl/atkinsonhyperlegible,
  upstream_info.md) menyatakan berkasnya diambil dari commit yang sama. Diambil
  `fonts/webfonts/AtkinsonHyperlegible-Regular.woff2` (sha256 2df4ba17...4a1150) dan
  `-Bold.woff2` (sha256 da8fce41...93c075) beserta OFL.txt (sha256 f32d22b3...dc143); dicek
  18 Okt 2026. Tanpa italic. Skala huruf 16/18/22/28 px, berat 400 dan 700, line-height 1,5.
- Warna sesi: 11 nama warna van de Weijer (`COLOR_NAMES`) dipetakan di `tokens.css` ke swatch
  (contoh warna dan garis tepi kiri 4 px) dan tint (latar gelembung pengunjung).
  - Hitam, cokelat, ungu, dan abu-abu memakai tint netral/sangat muda; identitasnya ditunjukkan
    garis tepi. Putih memakai tint abu muda dengan garis tepi abu.
  - `view.session_color` hanya ada saat target terkunci. Setelah PersonLeft atau reset, warna
    kembali netral.
- Kolom kamera: contoh warna 56 px + "Kamu memakai baju <warna>", lalu dua kalimat info. Badge
  "Aktif" dihapus.
- Layar sambut: judul 28 px, sapaan 22 px, grid topik 3x2 berikon garis. Setelah percakapan
  mulai, topik menjadi baris tombol kecil.
- Sumber: baris kecil dengan ikon dokumen. Penolakan: gelembung MICA biasa dengan ikon info.
- Status: kalimat di atas bilah input (Siap/Mendengarkan.../Mencari di dokumen PMB.../
  Menjawab...; tanpa mikrofon: "Silakan ketik pertanyaan"). Ikonnya statis.
  - Header hanya menampilkan indikator kamera dan mikrofon.
  - Bicara menjadi tombol utama bila mikrofon ada. Bila tidak ada, tombolnya nonaktif dengan teks
    "Mikrofon tidak tersedia, silakan ketik", dan Kirim menjadi tombol utama.
- Footer: pemberitahuan berupa kalimat biasa (N-08).
- Satu-satunya animasi otomatis: contoh warna memudar masuk 200 ms saat target terkunci; mati
  dengan prefers-reduced-motion.
  - Indikator mendengar berupa ikon gelombang statis, supaya tetap hanya ada satu animasi
    otomatis.
- Label overlay debug: teks putih di atas kotak gelap semi-pekat (alfa 0,75); mode public tidak
  berubah.
- Ukur ulang (`python scripts/ui_ab_bench.py --before 91327e0 --reps 10`,
  results/ADR-19/ui-37c-20261018-163812; AC, pratinjau off, selang-seling, aturan putaran 2):
  - RAM USS diam: median 177,16 -> 177,78 MB (+0,6 MB, tetap; maksimum sebelum 185,21).
  - CPU diam: 4,26 -> 4,70% (tetap; maksimum sebelum 8,57).
  - Waktu mulai: 2,459 -> 2,464 s (tetap).
  - p95 jeda tampil: 5,20 -> 4,04 ms (turun).
  - Perkiraan +2 MB dari font tidak terlihat sebesar itu pada run ini.
  - Folder hasil semula bernama ui-37b-* karena label langkah di skrip baru ditambahkan
    (`--step`) saat run sudah berjalan; namanya diganti ke ui-37c dan judulnya dikoreksi.

## Langkah 38: biaya pratinjau kamera (18 Okt 2026)

Pra-registrasi: docs/UI-PREVIEW-OPT.md (5ac3e98, amandemen 1 53b0668, amandemen 2 cd8fa10).
Hasil: results/ADR-19/ui-preview-opt-20261018-1712. Bench tahap 1 (Edge kiosk, diam 60 s lalu 20
pertanyaan ketik, pekerja dan pipeline palsu, proses kamera asli dengan sumber dan detektor
palsu), daya AC, 10 + 10 ulangan selang-seling; angka = median (min-maks).

- Diagnosis (01, img + object URL, versi 37c): GPU Edge naik ke +-210 MB dalam menit pertama
  lalu mendatar; renderer +0,3 MB/menit. Biaya ada di sisi tampil Edge, bukan pembuatan JPEG.
- K1 canvas + createImageBitmap (02): TIDAK lolos. RAM 390,4 -> 445,2 MB (GPU 212,1 -> 273,4).
  Kode dikembalikan ke img (tidak pernah di-commit).
- K2 `--disable-gpu-compositing` (03): LOLOS. RAM 391,3 (360,0-396,9) -> 218,1 (217,2-219,1) MB,
  GPU Edge 213,4 -> 38,3 MB; CPU 15,70 (12,19-16,48) -> 13,80 (12,55-14,66) %; p95 jeda 4,71
  (3,10-7,84) -> 3,63 (2,97-4,30) ms. CPU renderer naik 2,57 -> 4,13 %, GPU turun 5,74 -> 1,98 %.
- Diterapkan di `mica/webui/browser.py` `PREVIEW_SWITCHES`, HANYA bila `ui.camera_preview` bukan
  `off`. Alasan: hanya kondisi itu yang diukur. Dengan pratinjau off, GPU Edge 53,5 MB dan CPU
  renderer 0,00 % (04), jadi manfaatnya tidak terbukti, sedangkan switch memindahkan kerja
  komposit ke CPU.
- Konfigurasi akhir vs pratinjau off (04, laporan): RAM 178,7 -> 218,0 MB (+39,3), CPU 4,74 ->
  13,31 %, p95 6,41 -> 3,38 ms. Biaya pratinjau turun dari +215 MB (Langkah 37) ke +39 MB.
- `ui.preview_fps` (info, tanpa keputusan):
  - 2 vs 5 (05): RAM 213,0 vs 218,2 MB, CPU 7,72 vs 13,03 %.
  - 10 vs 5 (07): RAM 221,8 vs 218,3 MB, CPU 21,29 (20,36-22,58) vs 14,27 (12,40-15,00) %
    (renderer 8,22 vs 4,32 %, GPU 3,63 vs 2,01 %), p95 3,52 vs 3,35 ms.
- Keputusan desain pengguna 18 Okt 2026: pratinjau minimal 10 fps, `ui.preview_fps` 10 di
  dev.yaml dan kiosk.yaml (bukan hasil eksperimen). Laju deteksi YOLO tidak diubah.
- Laju kamera (09, `scripts/camera_rate.py`, laptop dev): kamera asli + YOLO asli 14,95 frame/s
  terbaca, JPEG pratinjau 10,01/s, deteksi 5,01/s; sumber palsu 15,00 / 10,00 / 5,00. Jarak
  antar-JPEG kamera asli median 99 ms, p95 192 ms, maks 234 ms (frame tertahan saat deteksi
  berjalan). Kamera laptop kiosk dicek ulang di E-09.
- Uji tumbuh 15 menit (aturan mekanis Diagnosis, tidak diubah):
  - Akhir fps 5 (06): total, GPU, browser, kamera, inti Python "mendatar (plafon)"; renderer
    23,7 -> 29,7 MB, +0,44 MB/menit, "naik terus (bocor)".
  - fps 10 + GC paksa (08, dengan port DevTools 127.0.0.1, bench saja): sama, renderer 26,5 ->
    31,8 MB, +0,42 MB/menit, "naik terus (bocor)". GC paksa (cara L31): renderer 33,0 -> 28,3 MB
    (+30 s) -> 28,3 MB (+60 s), heap JS 0,67 -> 0,60 MB. Aturan amandemen 2: "turun lagi setelah
    GC (sampah GC)". Pola: GC mengembalikan +-4,7 MB, tetapi renderer tetap di atas rata-rata 5
    menit pertama (26,5 MB); sisa kenaikan belum terjelaskan dan perlu uji yang lebih panjang.

### Keterbatasan pratinjau

- Kotak target dan area tanpa pixelate diperbarui sesuai laju DETEKSI, bukan laju video 10 fps:
  5 Hz saat menunggu (`vision.fps_idle`). Saat sesi berlangsung `vision.fps_busy` masih null
  (TBD) dengan nilai coba 2 Hz yang diputuskan di E-09. Di antara deteksi, overlay dan area tanpa
  pixelate memakai deteksi terakhir, jadi bisa tertinggal dari gerak pengunjung.
- Sumber palsu hampir statis, sedangkan kamera asli selalu berubah. Biaya RAM/CPU dengan kamera
  asli di laptop kiosk diukur di E-09.
- K2 diukur di Edge laptop dev. Efeknya di Edge/GPU laptop kiosk perlu dicek ulang di E-09.


## Format jawaban di gelembung percakapan (tampilan saja, 20 Okt 2026)

Masalah: jawaban MICA tampil sebagai satu paragraf panjang. Perbaikan hanya di lapisan tampilan:
prompt, pipeline RAG, JSON ViewModel (`messages[].text`), dan teks TTS (`Speak.text`) tidak
berubah. Browser memecah `text` menjadi blok di `static/answer_format.js`
(`MicaAnswerFormat.formatAnswer`, fungsi murni); `app.js` membangun `<p>`/`<ol>`/`<li>` dengan
`createElement` + `textContent`, tanpa `innerHTML`. Hanya pesan `kind: answer`; gelembung
pengunjung dan penolakan (`notice`) tetap teks biasa.

Temuan awal (run E-02 120b `20261017-122758-E-02-dev-hybrid-gpt-oss-120b-gateoff`): 26 dari 45
jawaban tidak kosong, tidak satu pun berisi baris baru atau pola nomor `1.`/`1)`/`(1)`, dan
semuanya 1-2 kalimat (terpanjang 422 karakter, satu kalimat dengan "pertama, ..., kedua, ...").
Gelembung sudah `white-space: pre-wrap`, jadi baris baru tidak digabung CSS; jawaban panjang
satu blok berasal dari teks LLM itu sendiri. Jawaban panjang/bernomor muncul di run lain
(E-04 20b dan Gemini, dev).

Aturan, berurutan:

1. Baris baru asli dipertahankan: setiap baris jadi blok sendiri; baris kosong dibuang; baris
   berawalan nomor yang berurutan (`1. ...`, `2) ...`, `(3) ...`) digabung jadi satu daftar.
2. Enumerasi dalam kalimat (`1) ... 2) ...`, `1. ... 2. ...`, `(1) ... (2) ...`) jadi daftar
   bernomor bila ada minimal dua penanda berurutan mulai 1 dengan gaya yang sama, diawali awal
   teks atau spasi. Teks sebelum nomor 1 jadi paragraf pembuka; kalimat setelah kalimat pertama
   butir terakhir jadi paragraf penutup. Pada akhir butir hanya spasi, `;`, dan `,` yang dibuang;
   kata (termasuk "dan") tidak dibuang.
3. Blok yang masih lebih dari 2 kalimat dipecah jadi paragraf berisi paling banyak 2 kalimat.
   **Angka 2 adalah nilai desain tampilan, bukan hasil ukur** (`MAX_SENTENCES_PER_PARAGRAPH`).

Pemecah kalimat: akhir kalimat = `.`/`!`/`?` (+ kutip/kurung penutup), spasi, lalu huruf besar,
angka, atau pembuka kutip/kurung. Titik setelah singkatan (Rp., No., dll., dsb., dst., Jl.,
Prof., Dr., hlm., ...) atau gelar bersusun (S.Kom., S.E., S.Ak., M.Kom., M.Sc., Ph.D., T.A.)
bukan akhir kalimat. Angka desimal (3,5 / 3.5), jam (09.30), tanggal (17.10.2026), URL, dan email
tidak punya spasi setelah titik, jadi tidak pernah dipecah. Keterbatasan: kalimat yang memang
berakhir dengan singkatan (mis. "... Ph.D. Beliau ...") tidak dipecah; akibatnya paling buruk dua
kalimat bergabung, tidak ada kata yang terpotong.

Uji: `tests/unit/test_answer_format.py`. Versi acuan Python `mica.webui.answer_format` diuji
pytest (26 jawaban nyata 120b, singkatan, angka, enumerasi, baris baru); kesetaraan JS = Python
dicek dengan menjalankan `answer_format.js` di Edge headless (`--dump-dom`, file lokal; dilewati
bila Edge tidak ada). Repo belum punya runner JS, jadi tidak ada library baru. Teks TTS dan JSON
ViewModel dicek identik dengan teks jawaban. Tangkapan layar sebelum/sesudah:
`docs/ui-screens/answer-format/` (`python scripts/ui_screens.py --answer-format --out ...`).
