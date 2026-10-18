# Tangkapan layar UI kiosk

Dibuat otomatis dengan `python scripts/ui_screens.py` (Edge headless + Chrome DevTools Protocol).
Data tampilan buatan, tanpa gambar orang sungguhan.

Langkah 37c (warna sesi, Atkinson Hyperlegible, 18 Okt 2026): setiap adegan pada viewport 1366x768
dan 1920x1080 (`<adegan>-<lebar>x<tinggi>.png`). Versi sebelum: `before-37c/` (Langkah 37b) dan
`before-37b/` (Langkah 37).

| adegan | isi |
| --- | --- |
| 01-sambut-tanpa-orang | Layar sambut, belum ada yang terdeteksi |
| 02-sambut-target-biru | Layar sambut, target biru: contoh warna + "Kamu memakai baju biru", grid topik |
| 03-percakapan-jawaban-sumber | Percakapan, gelembung pengunjung biru, jawaban + sumber berikon |
| 04-penolakan | Penolakan: gelembung MICA biasa dengan ikon info |
| 05-mendengarkan | Status "Mendengarkan..." di atas bilah input |
| 06-kamera-mati | Kamera tidak tersedia: pesan N-10 |
| 07-mic-tidak-tersedia | Tombol nonaktif "Mikrofon tidak tersedia, silakan ketik", Kirim jadi tombol utama |
| 08-target-hitam | Warna sesi hitam: tint netral + garis tepi hitam |
| 09-target-putih | Warna sesi putih: tint abu muda + garis tepi abu |
