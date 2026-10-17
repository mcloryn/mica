# Set evaluasi resmi

Folder ini diisi satu kali saat data resmi dari pembimbing datang (MS5). Aturannya ada di
`docs/DATASET.md`.

- `dev.jsonl` (30%, dev-resmi) dan `test.jsonl` (70%, uji) ditulis oleh
  `python -m mica.eval dataset split --input <file resmi> --out-dir data/eval/official/`.
- Setelah itu `test.jsonl` langsung dikunci lewat `python -m mica.eval dataset lock`
  (`data/eval/LOCK`).
- Kedua file rencananya di-commit, supaya hash di LOCK bisa diverifikasi, kecuali pembimbing
  melarang (item pembimbing di `docs/DATASET.md`).
- Jangan menyunting `test.jsonl` dengan tangan. Perubahan hanya lewat versi kunci baru dengan
  alasan tertulis.
