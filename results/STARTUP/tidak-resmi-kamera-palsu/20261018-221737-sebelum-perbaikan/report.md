# Waktu mulai: plumbing

0 ulangan dihitung (diharapkan 1); detik sejak perintah diluncurkan, median (min-maks).

| tonggak | detik |
| --- | --- |
| check selesai | - |
| server Flask jalan | - |
| Edge diluncurkan | - |
| UI tampil (render pertama) | - |
| pipeline siap (jawab ketikan) | - |
| kamera siap (CameraStatus ok) | - |
| suara siap (AudioStatus ready) | - |
| semua siap | - |

| rentang | durasi detik |
| --- | --- |
| utama: rakit pipeline | - |
| utama: muat KB | - |
| utama: import torch | - |
| utama: import sentence_transformers | - |
| utama: muat BGE-M3 | - |
| utama: spawn kamera | - |
| utama: spawn suara | - |
| kamera: import cv2 | - |
| kamera: import torch | - |
| kamera: import ultralytics | - |
| kamera: muat YOLO | - |
| kamera: inferensi pemanasan | - |
| kamera: buka VideoCapture | - |
| kamera: frame pertama | - |
| kamera: deteksi pertama | - |
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
| utama: pipeline | - | - |
| utama: server -> UI tampil | - | - |
| proses kamera | - | - |
| proses suara | - | - |

DIHENTIKAN: {'run': 'rep-1', 'status': 'memori', 'closed': 'dibunuh'}
