# Uji tumbuh 15 menit: fps10

Kondisi: {'name': 'fps10', 'static': '21e25ae', 'preview': 'public', 'preview_fps': 10.0, 'edge_extra': []}; sampel tiap 30 s.

| metrik | rata-rata 5 menit pertama | rata-rata 5 menit terakhir | selisih | kemiringan 10 menit terakhir (MB/menit) | keputusan |
| --- | --- | --- | --- | --- | --- |
| uss_total_mb | 224.4 | 205.8 | -18.6 | +0.442 | mendatar (plafon) |
| uss_inti Python | 49.9 | 47.6 | -2.4 | -0.003 | mendatar (plafon) |
| uss_kamera | 41.5 | 39.7 | -1.8 | +0.009 | mendatar (plafon) |
| uss_Edge browser | 51.1 | 49.4 | -1.7 | +0.030 | mendatar (plafon) |
| uss_Edge GPU | 38.1 | 26.6 | -11.5 | -0.004 | mendatar (plafon) |
| uss_Edge renderer | 26.5 | 31.8 | +5.3 | +0.418 | naik terus (bocor) |
| uss_lainnya | 17.2 | 10.7 | -6.5 | -0.008 | mendatar (plafon) |

CPU rata-rata seluruh uji per proses (% satu inti):

- inti Python: 0.66
- kamera: 1.85
- Edge browser: 1.98
- Edge GPU: 3.27
- Edge renderer: 8.67
- lainnya: 0.09
- total: 16.52

GC paksa di renderer setelah sampel terakhir (HeapProfiler.collectGarbage, seperti L31 --cdp-gc):

- renderer sebelum GC: 33.0 MB
- renderer 30 s setelah GC: 28.3 MB
- renderer 60 s setelah GC: 28.3 MB
- heap JS: 0.67 -> 0.60 MB
- keputusan (amandemen 2): turun lagi setelah GC (sampah GC)
