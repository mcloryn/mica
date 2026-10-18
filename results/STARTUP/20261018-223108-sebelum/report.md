# Waktu mulai: sebelum

5 ulangan dihitung (diharapkan 5); detik sejak perintah diluncurkan, median (min-maks).

| tonggak | detik |
| --- | --- |
| check selesai | 1.19 (1.18-1.22) |
| server Flask jalan | 13.14 (12.99-13.17) |
| Edge diluncurkan | 13.17 (13.03-13.21) |
| UI tampil (render pertama) | 14.27 (14.13-14.32) |
| pipeline siap (jawab ketikan) | 13.13 (12.98-13.17) |
| kamera siap (CameraStatus ok) | 13.14 (12.99-13.18) |
| suara siap (AudioStatus ready) | 13.14 (12.99-13.18) |
| semua siap | 14.27 (14.13-14.32) |

| rentang | durasi detik |
| --- | --- |
| utama: rakit pipeline | 11.58 (11.49-11.66) |
| utama: muat KB | 0.01 (0.01-0.01) |
| utama: import torch | 1.24 (1.24-1.27) |
| utama: import sentence_transformers | 4.40 (4.35-4.47) |
| utama: muat BGE-M3 | 5.55 (5.53-5.63) |
| utama: spawn kamera | 0.02 (0.02-0.03) |
| utama: spawn suara | 0.02 (0.02-0.03) |
| kamera: import cv2 | 0.02 (0.02-0.02) |
| kamera: import torch | 1.38 (1.37-1.42) |
| kamera: import ultralytics | 0.04 (0.04-0.04) |
| kamera: muat YOLO | 0.13 (0.11-0.14) |
| kamera: inferensi pemanasan | 1.52 (1.49-1.61) |
| kamera: buka VideoCapture | 1.01 (1.01-1.06) |
| kamera: frame pertama | 0.31 (0.29-0.39) |
| kamera: deteksi pertama | 0.05 (0.05-0.06) |
| suara: import faster_whisper | 0.19 (0.19-0.20) |
| suara: import piper | 0.89 (0.87-0.90) |
| suara: import pysilero_vad | 0.01 (0.00-0.01) |
| suara: import sounddevice | 0.06 (0.06-0.06) |
| suara: muat Whisper | 1.08 (1.06-1.10) |
| suara: muat Piper | 2.20 (2.11-2.28) |
| suara: muat Silero VAD | 0.01 (0.00-0.01) |
| suara: buka mikrofon | 0.03 (0.03-0.04) |
| suara: buka speaker | 0.00 (0.00-0.00) |

Jendela kerja (detik sejak peluncuran) untuk melihat paralel atau berurutan:

| jendela | awal | akhir |
| --- | --- | --- |
| utama: pipeline | 1.51 (1.49-1.55) | 13.13 (12.98-13.17) |
| utama: server -> UI tampil | 13.14 (12.99-13.17) | 14.27 (14.13-14.32) |
| proses kamera | 1.76 (1.76-1.81) | 6.35 (6.22-6.40) |
| proses suara | 1.82 (1.80-1.86) | 6.28 (6.21-6.43) |
