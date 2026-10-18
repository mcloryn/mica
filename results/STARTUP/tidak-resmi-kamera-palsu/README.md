# TIDAK RESMI: uji alat profil dengan kamera dan suara palsu (Langkah 40)

Dua run satu ulangan tanpa pemanasan, dijalankan Claude Code untuk menguji alur
scripts/startup_profile.py (`--fake-camera`: `python -m mica.webui --fake-workers --fake-camera`,
pipeline RAG asli). BUKAN hasil resmi: 1 ulangan, kamera/suara palsu, kondisi memori berbeda,
dan tidak sebanding dengan run resmi `20261018-223108-sebelum` (kamera dan suara asli).

| run | kode | UI tampil (s) | pipeline siap (s) | semua siap (s) | catatan |
| --- | --- | --- | --- | --- | --- |
| 20261018-221737-sebelum-perbaikan | a6c731c (pipeline sebelum server) | 25,45 | 23,49 | 25,45 | dihentikan penjaga memori 2,5 GB tepat setelah semua siap; app dibunuh setelah 30 s; report.md kosong karena run tidak dihitung, angka dari rep-1/stages.csv |
| 20261018-225944-sesudah-perbaikan | 92bc754 (pipeline di thread latar) | 2,51 | 16,03 | 16,03 | ditutup rapi; memori tersedia terendah 1,67 GB |

Pengukuran resmi "sesudah" (5 ulangan + 1 pemanasan, kamera asli) dan "dingin" belum dijalankan.
