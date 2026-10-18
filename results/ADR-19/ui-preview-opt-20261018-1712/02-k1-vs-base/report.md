# k1 vs base (pembanding)

10 ulangan per kondisi, selang-seling, daya AC. Kondisi:

- base: {'name': 'base', 'static': '21e25ae', 'preview': 'public', 'preview_fps': None, 'edge_extra': []}
- k1: {'name': 'k1', 'static': 'now', 'preview': 'public', 'preview_fps': None, 'edge_extra': []}

| metrik | base median (min-maks) | k1 median (min-maks) |
| --- | --- | --- |
| uss | 390.44 (388.95-392.60) | 445.23 (444.64-446.26) |
| cpu | 12.60 (9.74-16.22) | 10.00 (8.65-11.22) |
| p95 | 4.31 (3.30-5.69) | 4.14 (3.23-5.19) |
| uss inti Python | 50.43 (49.87-50.69) | 50.20 (49.99-50.38) |
| uss kamera | 42.45 (41.44-42.68) | 42.35 (41.54-42.66) |
| uss Edge browser | 51.26 (49.61-52.57) | 49.92 (49.32-50.82) |
| uss Edge GPU | 212.07 (211.14-213.96) | 273.37 (272.98-273.94) |
| uss Edge renderer | 20.96 (20.86-21.32) | 16.31 (15.84-16.44) |
| uss lainnya | 13.48 (13.32-13.58) | 13.46 (13.32-13.65) |
| cpu inti Python | 0.83 (0.47-1.07) | 0.94 (0.42-1.22) |
| cpu kamera | 1.78 (0.62-2.86) | 1.82 (0.42-2.60) |
| cpu Edge browser | 4.80 (3.57-5.60) | 3.23 (2.55-3.80) |
| cpu Edge GPU | 3.01 (2.14-3.72) | 2.36 (1.93-3.05) |
| cpu Edge renderer | 2.40 (1.48-3.91) | 1.29 (0.96-2.14) |
| cpu lainnya | 0.48 (0.39-0.65) | 0.46 (0.39-0.60) |

Aturan (docs/UI-PREVIEW-OPT.md):
- uss: median 445.234 vs pembanding min 388.949 / maks 392.602
- cpu: median 10.000 vs pembanding min 9.739 / maks 16.224
- p95: median 4.136 vs pembanding min 3.300 / maks 5.686

**k1 TIDAK lebih baik dari base.**
