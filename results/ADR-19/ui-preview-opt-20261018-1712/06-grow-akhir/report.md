# Uji tumbuh 15 menit: akhir

Kondisi: {'name': 'akhir', 'static': '21e25ae', 'preview': 'public', 'preview_fps': None, 'edge_extra': ['--disable-gpu-compositing']}; sampel tiap 30 s.

| metrik | rata-rata 5 menit pertama | rata-rata 5 menit terakhir | selisih | kemiringan 10 menit terakhir (MB/menit) | keputusan |
| --- | --- | --- | --- | --- | --- |
| uss_total_mb | 219.5 | 204.8 | -14.6 | +0.616 | mendatar (plafon) |
| uss_inti Python | 50.0 | 48.0 | -2.0 | +0.002 | mendatar (plafon) |
| uss_kamera | 41.7 | 40.1 | -1.5 | +0.030 | mendatar (plafon) |
| uss_Edge browser | 49.8 | 48.5 | -1.3 | +0.082 | mendatar (plafon) |
| uss_Edge GPU | 38.0 | 27.3 | -10.8 | +0.075 | mendatar (plafon) |
| uss_Edge renderer | 23.7 | 29.7 | +6.0 | +0.442 | naik terus (bocor) |
| uss_lainnya | 16.3 | 11.2 | -5.1 | -0.016 | mendatar (plafon) |

CPU rata-rata seluruh uji per proses (% satu inti):

- inti Python: 0.51
- kamera: 1.38
- Edge browser: 1.28
- Edge GPU: 1.82
- Edge renderer: 4.64
- lainnya: 0.12
- total: 9.76
