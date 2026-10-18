# Langkah 37b: A/B gaya UI web (pratinjau off)

Sebelum = static db85a13; sesudah = pohon kerja sekarang; 10 ulangan per kondisi, selang-seling, daya AC. Aturan putaran 2.

| metrik | sebelum median | sebelum maks | sesudah median | hasil |
| --- | --- | --- | --- | --- |
| uss_idle_mb | 179.281 | 180.969 | 176.727 | turun |
| cpu_idle_pct | 5.156 | 6.406 | 4.726 | turun |
| startup_s | 2.478 | 2.547 | 2.484 | tetap |
| lat_p95_ms | 4.877 | 5.199 | 5.574 | naik |

RAM dan CPU diam tidak naik.
