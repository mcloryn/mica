# k2 vs base (pembanding)

10 ulangan per kondisi, selang-seling, daya AC. Kondisi:

- base: {'name': 'base', 'static': '21e25ae', 'preview': 'public', 'preview_fps': None, 'edge_extra': []}
- k2: {'name': 'k2', 'static': '21e25ae', 'preview': 'public', 'preview_fps': None, 'edge_extra': ['--disable-gpu-compositing']}

| metrik | base median (min-maks) | k2 median (min-maks) |
| --- | --- | --- |
| uss | 391.33 (359.96-396.88) | 218.08 (217.16-219.12) |
| cpu | 15.70 (12.19-16.48) | 13.80 (12.55-14.66) |
| p95 | 4.71 (3.10-7.84) | 3.63 (2.97-4.30) |
| uss inti Python | 50.24 (47.22-50.55) | 49.99 (49.83-50.21) |
| uss kamera | 42.42 (39.26-42.51) | 42.33 (41.53-42.52) |
| uss Edge browser | 51.76 (46.09-52.30) | 51.98 (51.54-52.32) |
| uss Edge GPU | 213.39 (199.16-217.82) | 38.28 (38.11-38.49) |
| uss Edge renderer | 20.96 (17.97-21.14) | 22.28 (22.05-22.43) |
| uss lainnya | 13.43 (10.26-13.62) | 13.41 (13.31-13.75) |
| cpu inti Python | 0.76 (0.49-1.33) | 0.69 (0.39-1.15) |
| cpu kamera | 1.68 (0.31-2.29) | 1.68 (0.81-2.92) |
| cpu Edge browser | 4.28 (3.26-5.18) | 4.44 (3.93-5.49) |
| cpu Edge GPU | 5.74 (5.18-6.54) | 1.98 (1.69-2.14) |
| cpu Edge renderer | 2.57 (1.51-3.33) | 4.13 (3.67-4.69) |
| cpu lainnya | 0.47 (0.44-0.76) | 0.57 (0.36-0.73) |

Aturan (docs/UI-PREVIEW-OPT.md):
- uss: median 218.084 vs pembanding min 359.965 / maks 396.883
- cpu: median 13.802 vs pembanding min 12.187 / maks 16.484
- p95: median 3.633 vs pembanding min 3.101 / maks 7.838

**k2 LEBIH BAIK dari base.**
