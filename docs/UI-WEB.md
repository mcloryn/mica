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
