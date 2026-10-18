# akhir vs off (pembanding)

10 ulangan per kondisi, selang-seling, daya AC. Kondisi:

- off: {'name': 'off', 'static': '21e25ae', 'preview': 'off', 'preview_fps': None, 'edge_extra': []}
- akhir: {'name': 'akhir', 'static': '21e25ae', 'preview': 'public', 'preview_fps': None, 'edge_extra': ['--disable-gpu-compositing']}

| metrik | off median (min-maks) | akhir median (min-maks) |
| --- | --- | --- |
| uss | 178.67 (177.27-179.82) | 217.96 (216.53-219.23) |
| cpu | 4.74 (3.80-5.36) | 13.31 (11.87-14.53) |
| p95 | 6.41 (3.30-7.65) | 3.38 (3.12-4.65) |
| uss inti Python | 48.99 (48.56-50.06) | 49.90 (49.57-50.27) |
| uss kamera | 0.00 (0.00-0.00) | 42.52 (41.64-42.57) |
| uss Edge browser | 49.51 (48.50-50.29) | 51.60 (50.92-52.70) |
| uss Edge GPU | 53.46 (53.34-53.55) | 38.26 (38.17-38.39) |
| uss Edge renderer | 13.47 (13.41-13.50) | 22.24 (22.15-22.32) |
| uss lainnya | 13.11 (13.05-13.32) | 13.40 (13.25-13.46) |
| cpu inti Python | 0.29 (0.13-0.44) | 0.76 (0.42-1.12) |
| cpu kamera | 0.00 (0.00-0.00) | 1.52 (0.36-1.93) |
| cpu Edge browser | 3.62 (2.68-4.09) | 4.31 (3.62-4.69) |
| cpu Edge GPU | 0.51 (0.42-0.57) | 1.98 (1.46-2.40) |
| cpu Edge renderer | 0.00 (0.00-0.05) | 4.43 (3.83-5.26) |
| cpu lainnya | 0.36 (0.23-0.52) | 0.49 (0.23-0.65) |

Info saja (pra-registrasi): tanpa keputusan.
