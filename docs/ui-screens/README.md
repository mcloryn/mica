# Tangkapan layar UI kiosk

Dibuat otomatis dengan `python scripts/ui_screens.py` (Edge headless + Chrome DevTools Protocol).
Data tampilan buatan; gambar pratinjau dari sumber palsu `mica.vision.fakesource` (siluet tanpa
wajah orang sungguhan) lewat render pratinjau yang sama dengan proses kamera.

Langkah 37b (gaya web konvensional, 18 Okt 2026): setiap adegan pada viewport 1366x768 dan
1920x1080 (`<adegan>-<lebar>x<tinggi>.png`). Adegan layar sempit pada 1000x700. Versi sebelum
(Langkah 37, 1536x864) ada di `before-37b/`.

| adegan | isi |
| --- | --- |
| 01-siap-tanpa-orang | Siap, tanpa orang: ajakan "Mendekatlah ke layar untuk mulai" |
| 02-sapaan-topik | Sapaan sebagai pesan pertama + tombol topik, target terkunci |
| 03-percakapan-jawaban-sumber | Pertanyaan, jawaban MICA, "Sumber: ..." kecil abu |
| 04-penolakan | Penolakan sebagai pesan biasa dengan ikon info |
| 05-mendengarkan | Status Mendengarkan (titik hijau kecil) |
| 06-kamera-mati | Kamera tidak tersedia: pesan ramah (N-10), badge "Tidak aktif" |
| 07-preview-public | Pratinjau public: semua tersamar kecuali kotak target |
| 08-preview-debug | Pratinjau debug (dev): tanpa samaran, kotak, area baju, skor |
| 09-layar-sempit | Lebar 1000 px: panel kamera jadi strip di atas |
