# Anotasi halusinasi: gpt-oss-20b (set dev)

- File: `annotate_generation.csv` (28 baris, kolom `benar` dan `halusinasi` bernilai 0/1). Ringkasan: `annotation_summary.json` (`python -m mica.eval annotation --run <folder ini>`).
- Penilai: rekan hasa (penyusun naskah). File anotasi diterima 19 Okt 2026.
- Penilai melihat saran Claude saat menilai. Saran Claude disimpan di `annotate_generation_saran_claude.csv` (kolom `saran_benar`, `saran_halusinasi`, `saran_catatan`). Dicek dengan `python -m mica.eval annotation --run <folder ini> --compare-saran`: identik dengan saran Claude benar 28/28, halusinasi 28/28, catatan 28/28. Jadi hasil ini dilaporkan sebagai **anotasi Claude yang diperiksa rekan tanpa perubahan**, bukan anotasi manusia independen.
- Hanya untuk set dev. Set uji resmi dinilai buta (tanpa saran Claude), idealnya oleh 2 penilai dengan Cohen's kappa.
- Hasil: benar 27/28 (salah: d040), halusinasi 1/28 (d023; tingkat 0,036; CI 95% Wilson 0,006-0,177).
- d023 = halusinasi 1 menurut definisi: klaim harus didukung potongan yang dikutip, dan "tahun akademik 2026/2027" hanya ada di FAQ yang tidak dikutip (tanggal 5 Maret 2027 sendiri benar). Bila d023 dinilai 0, tingkat 20b menjadi 0/28 (sama dengan 120b, 0/28) dan urutan model tidak berubah.
