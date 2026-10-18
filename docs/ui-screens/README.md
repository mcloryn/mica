# Tangkapan layar UI kiosk (Langkah 37)

Dibuat otomatis dengan `python scripts/ui_screens.py` (Edge headless + Chrome DevTools Protocol,
18 Okt 2026). Data tampilan buatan; gambar pratinjau dari sumber palsu `mica.vision.fakesource`
(siluet tanpa wajah orang sungguhan) lewat render pratinjau yang sama dengan proses kamera.

| file | isi |
| --- | --- |
| 01-siap-tanpa-orang.png | Siap, tanpa orang: ajakan "Mendekatlah ke layar untuk mulai" |
| 02-sapaan-kartu-topik.png | Sapaan besar berwarna + 6 kartu topik, target terkunci |
| 03-percakapan-jawaban-sumber.png | Pertanyaan, jawaban MICA dengan sumber dan tanggal, chip topik |
| 04-penolakan.png | Penolakan sebagai kartu krem yang sopan |
| 05-mendengarkan.png | Status Mendengarkan (pil dan cincin hijau) |
| 06-kamera-mati.png | Kamera tidak tersedia: pesan ramah (N-10) |
| 07-preview-public.png | Pratinjau public: semua tersamar kecuali kotak target |
| 08-preview-debug.png | Pratinjau debug (dev): tanpa samaran, kotak, area baju, skor |
| 09-layar-sempit.png | Lebar 1000 px: kamera jadi strip kecil di atas |
