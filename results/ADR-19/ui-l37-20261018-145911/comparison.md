# Langkah 37: ukur ulang UI kiosk

Baseline: results/ADR-19/ui-opt2-combo-20261018-042512/summary.csv baris k1+k2; 10 ulangan per kondisi, selang-seling, daya AC.

## Kondisi 1 (desain baru, pratinjau off) vs baseline

- uss_idle_mb: 177.850 vs baseline median 175.129 / maks 176.484: naik
- cpu_idle_pct: 4.740 vs baseline median 4.102 / maks 5.599: tetap
- startup_s: 2.457 vs baseline median 2.463 / maks 2.492: turun
- lat_p95_ms: 4.585 vs baseline median 3.037 / maks 7.368: tetap

RAM/CPU diam c1 naik di atas maksimum baseline: uss_idle_mb -> cari penyebab di desain baru

## Kondisi 2 (pratinjau public, sumber palsu) vs kondisi 1

- uss_idle_mb: c2 393.027 - c1 177.850 = +215.178
- cpu_idle_pct: c2 13.646 - c1 4.740 = +8.906
- startup_s: c2 2.504 - c1 2.457 = +0.048
- lat_p95_ms: c2 4.681 - c1 4.585 = +0.096

Median per jenis proses (CPU diam %, USS diam MB):

| jenis | c1 CPU | c2 CPU | c1 USS | c2 USS |
| --- | --- | --- | --- | --- |
| edge: browser | 3.24 | 4.61 | 47.3 | 51.0 |
| edge: crashpad-handler | 0.03 | 0.03 | 1.8 | 1.8 |
| edge: gpu-process | 0.53 | 3.65 | 53.9 | 213.8 |
| edge: renderer | 0.03 | 2.67 | 14.4 | 21.7 |
| edge: utility (network.mojom.NetworkService) | 0.30 | 0.55 | 8.4 | 8.7 |
| edge: utility (storage.mojom.StorageService) | 0.00 | 0.00 | 3.0 | 3.0 |
| python: Flask + controller | 0.42 | 0.85 | 48.8 | 49.5 |
| python: pekerja (kamera) | 0.00 | 1.93 | 0.0 | 42.5 |
| python: peluncur venv | 0.00 | 0.00 | 0.6 | 0.6 |

Keputusan akhir pratinjau public ada di E-09 (docs/E-09.md, amandemen 1).
