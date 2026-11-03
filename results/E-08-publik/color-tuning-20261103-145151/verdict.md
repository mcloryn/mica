# E-08 verdict: warna pakaian atas

Catatan: PETA publik, split tuning (amandemen kedua C)

Aturan E-08 (docs/E-08.md, 18 Okt 2026, amandemen 1): kombinasi region x {lut_vote, lut_mean} dengan macro-F1 tertinggi (tanpa min_majority; seri -> akurasi, lalu keypoint_torso + lut_vote); lalu, hanya bila pemenang lut_vote, min_majority {0,5; 0,6; 0,7}: presisi (benar / disebut warna) tertinggi, seri -> nilai lebih kecil. lut_mean: sweep dilewati, cakupan 100 %. Cakupan selalu dilaporkan.

Kappa Cohen = 1.000 atas 332 pasangan; 332 sepakat, 0 tidak sepakat (dikeluarkan), 0 hanya penilai 1, 0 hanya penilai 2, 82 sepakat tetapi tidak terdeteksi (dikeluarkan).

| region | metode | n | akurasi | macro-F1 | tanpa prediksi |
| --- | --- | --- | --- | --- | --- |
| keypoint_torso | lut_vote | 250 | 0.4640 | 0.4828 | 0 |
| keypoint_torso | lut_mean | 250 | 0.4560 | 0.4777 | 0 |
| box_upper | lut_vote | 250 | 0.3480 | 0.3694 | 0 |
| box_upper | lut_mean | 250 | 0.3400 | 0.3531 | 0 |

## Keputusan

- macro-F1 tertinggi: keypoint_torso_lut_vote (0.4828)

min_majority pada keypoint_torso_lut_vote:

| min_majority | disebut | benar | presisi | cakupan |
| --- | --- | --- | --- | --- |
| 0.5 | 216 | 111 | 0.5139 | 0.8640 |
| 0.6 | 185 | 101 | 0.5459 | 0.7400 |
| 0.7 | 160 | 90 | 0.5625 | 0.6400 |

**vision.region = keypoint_torso, vision.color.method = lut_vote, vision.color.min_majority = 0.7**
