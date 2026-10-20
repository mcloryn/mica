# Anotasi halusinasi: gpt-oss-20b, prompt v3 (set dev)

- Status: **belum dianotasi** (20 Okt 2026). Aturan keputusan: docs/PROMPT-V3.md, syarat 4.
- File: `annotate_generation.csv` (27 baris, dibuat `eval generation`). Isi kolom `benar` dan
  `halusinasi` dengan 0/1 dan `catatan` bila perlu. Lalu jalankan
  `python -m mica.eval annotation --run <folder ini>` untuk membuat `annotation_summary.json`.
- Definisi halusinasi sama dengan v2 (SDD 2.4): klaim yang tidak didukung potongan yang dikutip
  (`cited_chunks`), bukan seluruh KB. Substitusi pertanyaan dicatat terpisah (benar 0,
  halusinasi 0).
- Tidak ada file saran Claude untuk run ini. Anotasi v2 dev dilakukan dengan saran Claude terlihat
  (lihat ANNOTATION.md run v2), jadi perbedaan cara anotasi v2 dan v3 perlu diungkap di Bab 3.
