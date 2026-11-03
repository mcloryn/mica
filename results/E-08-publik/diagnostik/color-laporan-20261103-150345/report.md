# E-08 laporan akhir (split laporan)

Catatan: HITUNG ULANG DIAGNOSTIK (catatan kelima), bukan angka resmi; angka resmi = color-laporan-20261103-145225

Aturan: docs/AMANDEMEN-2026-11-03b.md bagian C dan catatannya. Nilai pemenang dari run tuning results/E-08-publik/color-tuning-20261103-145151: region keypoint_torso, metode lut_vote.
Akurasi PETA (potongan CCTV beresolusi rendah) ditafsirkan sebagai batas bawah untuk kamera MICA.

| warna | n | benar | akurasi | Wilson 95% | catatan |
| --- | --- | --- | --- | --- | --- |
| hitam | 30 | 21 | 0.7000 | 0.5212-0.8334 |  |
| biru | 31 | 15 | 0.4839 | 0.3197-0.6516 |  |
| cokelat | 31 | 9 | 0.2903 | 0.1610-0.4659 |  |
| abu-abu | 33 | 10 | 0.3030 | 0.1738-0.4734 |  |
| hijau | 30 | 9 | 0.3000 | 0.1666-0.4788 |  |
| oranye | 30 | 12 | 0.4000 | 0.2459-0.5768 |  |
| merah muda | 29 | 6 | 0.2069 | 0.0985-0.3839 |  |
| ungu | 23 | 9 | 0.3913 | 0.2216-0.5921 |  |
| merah | 31 | 11 | 0.3548 | 0.2112-0.5305 |  |
| putih | 30 | 1 | 0.0333 | 0.0059-0.1667 |  |
| kuning | 30 | 6 | 0.2000 | 0.0951-0.3731 |  |

- Akurasi semua gambar (tidak terdeteksi = gagal): 109/328 = 0.3323 (Wilson 95% 0.2835-0.3850)
- Akurasi gambar terdeteksi: 109/240 = 0.4542 (Wilson 95% 0.3924-0.5174)
- Tidak terdeteksi YOLO: 88 dari 328
- min_majority 0.7: warna disebut 153, benar 83 (presisi 0.5425), cakupan 0.4665
