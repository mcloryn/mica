# fps10 vs fps5 (pembanding)

10 ulangan per kondisi, selang-seling, daya AC. Kondisi:

- fps5: {'name': 'fps5', 'static': '21e25ae', 'preview': 'public', 'preview_fps': 5.0, 'edge_extra': []}
- fps10: {'name': 'fps10', 'static': '21e25ae', 'preview': 'public', 'preview_fps': 10.0, 'edge_extra': []}

| metrik | fps5 median (min-maks) | fps10 median (min-maks) |
| --- | --- | --- |
| uss | 218.25 (217.87-241.93) | 221.78 (193.43-227.97) |
| cpu | 14.27 (12.40-15.00) | 21.29 (20.36-22.58) |
| p95 | 3.35 (2.80-4.28) | 3.52 (3.01-4.39) |
| uss inti Python | 50.15 (49.77-50.65) | 50.01 (47.59-50.38) |
| uss kamera | 42.33 (41.53-42.62) | 42.38 (39.53-42.75) |
| uss Edge browser | 52.28 (51.46-52.82) | 53.09 (47.38-54.80) |
| uss Edge GPU | 38.25 (38.15-38.40) | 38.30 (27.01-38.48) |
| uss Edge renderer | 22.26 (22.05-22.36) | 24.46 (22.57-29.34) |
| uss lainnya | 13.40 (13.25-36.64) | 13.36 (10.56-13.72) |
| cpu inti Python | 0.57 (0.42-0.91) | 0.95 (0.76-1.56) |
| cpu kamera | 1.77 (0.81-2.66) | 2.45 (1.41-3.23) |
| cpu Edge browser | 4.87 (4.11-5.62) | 5.52 (4.58-6.12) |
| cpu Edge GPU | 2.01 (1.67-2.37) | 3.63 (2.92-4.09) |
| cpu Edge renderer | 4.32 (3.72-5.31) | 8.22 (7.16-9.37) |
| cpu lainnya | 0.44 (0.36-0.68) | 0.53 (0.31-0.83) |

Info saja (pra-registrasi): tanpa keputusan.
