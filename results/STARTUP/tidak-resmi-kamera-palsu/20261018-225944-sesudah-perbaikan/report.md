# Waktu mulai: cek-sesudah

1 ulangan dihitung (diharapkan 1); detik sejak perintah diluncurkan, median (min-maks).

| tonggak | detik |
| --- | --- |
| check selesai | - |
| server Flask jalan | 0.67 (0.67-0.67) |
| Edge diluncurkan | 0.72 (0.72-0.72) |
| UI tampil (render pertama) | 2.51 (2.51-2.51) |
| pipeline siap (jawab ketikan) | 16.03 (16.03-16.03) |
| kamera siap (CameraStatus ok) | 1.09 (1.09-1.09) |
| suara siap (AudioStatus ready) | 0.67 (0.67-0.67) |
| semua siap | 16.03 (16.03-16.03) |

| rentang | durasi detik |
| --- | --- |
| utama: rakit pipeline | 15.29 (15.29-15.29) |
| utama: muat KB | 0.03 (0.03-0.03) |
| utama: import torch | 1.51 (1.51-1.51) |
| utama: import sentence_transformers | 6.12 (6.12-6.12) |
| utama: muat BGE-M3 | 7.33 (7.33-7.33) |
| utama: spawn kamera | 0.03 (0.03-0.03) |
| utama: spawn suara | - |
| kamera: import cv2 | 0.02 (0.02-0.02) |
| kamera: import torch | - |
| kamera: import ultralytics | - |
| kamera: muat YOLO | 0.01 (0.01-0.01) |
| kamera: inferensi pemanasan | 0.00 (0.00-0.00) |
| kamera: buka VideoCapture | 0.00 (0.00-0.00) |
| kamera: frame pertama | 0.00 (0.00-0.00) |
| kamera: deteksi pertama | 0.00 (0.00-0.00) |
| suara: import faster_whisper | - |
| suara: import piper | - |
| suara: import pysilero_vad | - |
| suara: import sounddevice | - |
| suara: muat Whisper | - |
| suara: muat Piper | - |
| suara: muat Silero VAD | - |
| suara: buka mikrofon | - |
| suara: buka speaker | - |

Jendela kerja (detik sejak peluncuran) untuk melihat paralel atau berurutan:

| jendela | awal | akhir |
| --- | --- | --- |
| utama: pipeline | 0.74 (0.74-0.74) | 16.03 (16.03-16.03) |
| utama: server -> UI tampil | 0.67 (0.67-0.67) | 2.51 (2.51-2.51) |
| proses kamera | 0.96 (0.96-0.96) | 1.05 (1.05-1.05) |
| proses suara | - | - |
