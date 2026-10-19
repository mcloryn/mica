# Anotasi halusinasi: gpt-oss-120b (set dev)

- File: `annotate_generation.csv` (28 baris, kolom `benar` dan `halusinasi` bernilai 0/1). Ringkasan: `annotation_summary.json` (`python -m mica.eval annotation --run <folder ini>`).
- Penilai: rekan hasa (penyusun naskah). File anotasi diterima 19 Okt 2026.
- Penilai melihat saran Claude saat menilai. 28/28 nilai dan 28/28 catatan identik dengan saran Claude, jadi hasil ini dilaporkan sebagai **anotasi Claude yang diperiksa rekan tanpa perubahan**, bukan anotasi manusia independen.
- Hanya untuk set dev. Set uji resmi dinilai buta (tanpa saran Claude), idealnya oleh 2 penilai dengan Cohen's kappa.
- Hasil: benar 28/28, halusinasi 0/28 (tingkat 0,000; CI 95% Wilson 0,000-0,121). File yang sama dipakai di results/E-02/20261017-122758-E-02-dev-hybrid-gpt-oss-120b-gateoff (jawaban 28 qid identik).
