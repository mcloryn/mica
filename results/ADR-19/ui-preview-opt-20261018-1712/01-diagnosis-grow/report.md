# Uji tumbuh 15 menit: base

Kondisi: {'name': 'base', 'static': 'now', 'preview': 'public', 'preview_fps': None, 'edge_extra': []}; sampel tiap 30 s.

| metrik | rata-rata 5 menit pertama | rata-rata 5 menit terakhir | selisih | kemiringan 10 menit terakhir (MB/menit) | keputusan |
| --- | --- | --- | --- | --- | --- |
| uss_total_mb | 375.7 | 381.2 | +5.5 | +0.944 | naik terus (bocor) |
| uss_inti Python | 50.0 | 47.6 | -2.4 | -0.049 | mendatar (plafon) |
| uss_kamera | 42.1 | 38.2 | -3.9 | -0.066 | mendatar (plafon) |
| uss_Edge browser | 49.9 | 48.5 | -1.4 | +0.002 | mendatar (plafon) |
| uss_Edge GPU | 194.8 | 207.4 | +12.6 | +0.771 | naik terus (bocor) |
| uss_Edge renderer | 22.4 | 28.3 | +5.9 | +0.315 | naik terus (bocor) |
| uss_lainnya | 16.6 | 11.3 | -5.3 | -0.030 | mendatar (plafon) |

CPU rata-rata seluruh uji per proses (% satu inti):

- inti Python: 0.87
- kamera: 1.28
- Edge browser: 1.31
- Edge GPU: 2.83
- Edge renderer: 2.46
- lainnya: 0.19
- total: 8.94
