# Anotasi halusinasi: gpt-oss-120b, prompt v4 (set dev)

- Status: **belum dianotasi** (20 Okt 2026). Aturan keputusan: docs/PROMPT-V4.md, syarat 4.
- File: `annotate_generation.csv` (28 baris, dibuat `eval generation`). Kolom `answer` berisi
  answer + items digabung "; " (teks yang sama dengan yang dicek NumericFactChecker). Isi `benar`
  dan `halusinasi` (0/1) dan `catatan`, lalu `python -m mica.eval annotation --run <folder ini>`.
- Definisi halusinasi sama dengan v2 (SDD 2.4): klaim (termasuk tiap item) yang tidak didukung
  potongan yang dikutip (`cited_chunks`). Substitusi pertanyaan dicatat terpisah.
- Tidak ada file saran Claude. Anotasi v2 dev dibuat dengan saran Claude terlihat, jadi perbedaan
  cara anotasi perlu diungkap di Bab 3.
