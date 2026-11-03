# E-08 grid area baju (tahap 2a, 2b, 3)

Aturan: docs/AMANDEMEN-2026-11-03.md bagian C. Region keypoint_torso, metode lut_vote (tahap 1).
Tahap 2a/2b: macro-F1 tertinggi -> akurasi -> paling dekat nilai coba -> nilai lebih kecil. Kandidat dipilih pengembang sebelum data, berpusat pada nilai coba.

- tahap 2a: macro-F1 0.4970, akurasi 0.4760
- tahap 2b: macro-F1 0.5026, akurasi 0.4800

Nilai terpilih:

- vision.keypoint_torso.min_kp_conf = 0.3
- vision.keypoint_torso.shrink = 0.2
- vision.keypoint_torso.torso_aspect = 1.2
- vision.box_upper.top = 0.35
- vision.box_upper.bottom = 0.65
- vision.box_upper.side = 0.2

Tahap 3 min_majority (parameter akhir):

| min_majority | disebut | benar | presisi | cakupan |
| --- | --- | --- | --- | --- |
| 0.5 | 221 | 112 | 0.5068 | 0.8840 |
| 0.6 | 193 | 101 | 0.5233 | 0.7720 |
| 0.7 | 160 | 93 | 0.5813 | 0.6400 |

- vision.color.min_majority = 0.7

Untuk E-07 bagian 2: --min-kp-conf 0.3
