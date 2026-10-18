# TIDAK LENGKAP: K2 vs base, proses anak bench berhenti sendiri

Run 18 Okt 2026 18:23-18:38. 13 dari 20 ulangan selesai (console.log). Pada ulangan ke-14 (k2 #7,
`--disable-gpu-compositing`), proses anak bench (aplikasi + Edge) hilang saat masa diam 60 s
(psutil.NoSuchProcess). Bukan karena memori: memori tersedia tetap +-3,4 GB, tidak ada event
low-memory Windows, dan penjaga memori 2 GB tidak terpicu. stderr anak saat itu dibuang (DEVNULL),
jadi penyebab pastinya tidak tercatat; aplikasi berhenti bila jendela Edge tertutup, sehingga
kemungkinan Edge K2 tertutup/crash. Data ini tidak digabung ke hasil resmi; run diulang di
03-k2-vs-base dengan stderr anak disimpan.
