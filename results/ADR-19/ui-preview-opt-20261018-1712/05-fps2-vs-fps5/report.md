# fps2 vs fps5 (pembanding)

10 ulangan per kondisi, selang-seling, daya AC. Kondisi:

- fps5: {'name': 'fps5', 'static': '21e25ae', 'preview': 'public', 'preview_fps': 5.0, 'edge_extra': ['--disable-gpu-compositing']}
- fps2: {'name': 'fps2', 'static': '21e25ae', 'preview': 'public', 'preview_fps': 2.0, 'edge_extra': ['--disable-gpu-compositing']}

| metrik | fps5 median (min-maks) | fps2 median (min-maks) |
| --- | --- | --- |
| uss | 218.22 (216.87-219.77) | 212.96 (211.45-213.68) |
| cpu | 13.03 (11.90-14.69) | 7.72 (5.21-11.61) |
| p95 | 3.07 (2.85-5.01) | 3.21 (3.01-3.81) |
| uss inti Python | 50.17 (49.55-50.62) | 50.04 (49.81-50.54) |
| uss kamera | 42.44 (41.46-42.70) | 42.40 (42.26-42.48) |
| uss Edge browser | 52.17 (51.40-53.19) | 50.67 (49.39-51.21) |
| uss Edge GPU | 38.20 (38.06-38.36) | 38.25 (38.14-38.30) |
| uss Edge renderer | 22.29 (22.05-22.38) | 18.12 (18.09-18.33) |
| uss lainnya | 13.38 (13.34-13.44) | 13.41 (13.24-13.65) |
| cpu inti Python | 0.85 (0.44-1.15) | 0.46 (0.08-0.83) |
| cpu kamera | 1.42 (0.13-2.29) | 0.81 (0.08-1.69) |
| cpu Edge browser | 4.44 (3.80-5.10) | 4.08 (2.60-4.84) |
| cpu Edge GPU | 2.03 (1.61-2.32) | 0.85 (0.47-1.46) |
| cpu Edge renderer | 4.00 (3.44-4.87) | 0.91 (0.18-3.49) |
| cpu lainnya | 0.47 (0.34-0.70) | 0.48 (0.34-0.81) |

Info saja (pra-registrasi): tanpa keputusan.
