# Diagnosis Langkah 37: RAM diam kondisi 1 di atas maksimum baseline

Bench yang sama (`ui_bench.run_once`, preview off, pekerja/pipeline palsu, AC), 4 ulangan
selang-seling per varian, 18 Okt 2026 siang. Skrip menukar sementara file statis di pohon kerja
lalu mengembalikannya (dicek `git status` setelahnya).

| varian | median USS diam MB | median CPU diam % | renderer Edge MB |
| --- | --- | --- | --- |
| UI lama (static e8c24a2^) | 177,31 | 5,16 | +-11,5 |
| UI baru | 179,47 | 4,60 | +-14,3 |
| UI baru tanpa @font-face | 177,25 | 5,18 | +-12,7 |
| UI baru (run kedua) | 179,08 | 5,12 | +-14,4 |

Baseline putaran 2 (pagi, ui-opt2-combo-20261018-042512, k1+k2): median 175,13, maksimum 176,48.

Kesimpulan: UI lama pada sesi yang sama juga di atas maksimum baseline (pergeseran keadaan laptop
+-1-2 MB); selisih UI baru vs UI lama +-2 MB seluruhnya di renderer Edge, +-1,8 MB di antaranya font
web Plus Jakarta Sans (wajib, Bagian A.3). CPU diam UI baru tidak lebih tinggi. Tidak ada animasi
atau timer saat Siap (dibuktikan tes). Font tidak dihapus.
