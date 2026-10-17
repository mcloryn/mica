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
