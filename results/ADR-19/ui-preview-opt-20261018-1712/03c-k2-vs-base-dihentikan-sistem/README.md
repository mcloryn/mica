# DIHENTIKAN: K2 vs base, run ketiga dihentikan Claude Code (memori hampir habis)

Run 18 Okt 2026 (setelah 03b), stderr anak disimpan per ulangan. Dihentikan oleh Claude Code
pada ulangan ke-18 (k2 #9) karena memori sistem hampir habis; penjaga memori 2 GB di skrip belum
terpicu saat itu. 17 ulangan selesai tetapi hasil per ulangan hanya tercetak di konsol (tidak ada
per_run.csv / summary.json). stderr-01 s.d. stderr-18 kosong (tidak ada pesan galat anak).
Data parsial (dari konsol, TIDAK resmi, sebagaimana dicatat pengguna): RAM 388-393 vs 217-219 MB,
CPU 12-17% vs 12,6-16% (RAM 388-393 MB sesuai base di 02-k1-vs-base, jadi 217-219 MB = k2). Data ini tidak digabung ke hasil resmi; run diulang di 03-k2-vs-base lewat
scripts/l38_run_rest.ps1 dengan --min-free-gb 2.5.
