# Run terhenti: tidak dipakai untuk analisis

- Run: E-04 dev, `gemini:gemini-3.8-flash`, gerbang mati, `--timeout-s 60`; mulai 19 Okt 2026
  11:32 WIB.
- Hanya 9/45 pertanyaan terjawab (d001-d007, d014, d015). 36 pertanyaan lain `unavailable`
  karena 429 (150 coba ulang, menunggu 1.500 detik).
- Penyebab: kuota tier gratis harian habis, `GenerateRequestsPerDayPerProjectPerModel-FreeTier`
  = 20 permintaan per hari per model. 6 permintaan hari itu sudah terpakai untuk uji pemilihan
  model (`results/E-04/gemini-model-selection-20261019.json`).
- Sesuai docs/E-04.md amandemen 1:
  - jawaban `unavailable` karena 429/kuota tidak dihitung sebagai salah tolak atau jawaban;
  - run ini disimpan sebagai run terhenti dan tidak dipakai untuk analisis;
  - kesembilan jawaban tetap ada di cache dan dipakai ulang oleh run lengkap.
- `annotate_generation.csv` di folder ini tidak dianotasi.
