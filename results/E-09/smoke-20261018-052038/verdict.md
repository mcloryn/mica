# E-09 verdict: smoke

**Uji alat, bukan hasil E-09.**

Keseluruhan: **TIDAK LENGKAP**

Aturan: docs/E-09.md (pra-registrasi 18 Okt 2026), diterapkan mekanis pada p95.
Persentil: interpolasi linear (numpy.percentile bawaan), mica.eval.metrics.percentile.

| Ukuran | Input | n | p95 (s) | Syarat (s) | Sumber | Status |
| --- | --- | --- | --- | --- | --- | --- |
| vad | voice | 0 | - | ≤ 0.5 | SDD 3.3 deteksi akhir ucapan | tidak ada data |
| stt | voice | 0 | - | ≤ 1.5 | SDD 3.3 STT ucapan 5 detik | tidak ada data |
| retrieval_gate | voice | 0 | - | ≤ 0.5 | SDD 3.3 retrieval dan gerbang | tidak ada data |
| llm | voice | 0 | - | ≤ 4 | SDD 3.3 LLM sampai jawaban lengkap | tidak ada data |
| check_tts | voice | 0 | - | ≤ 1 | SDD 3.3 cek fakta dan TTS kalimat pertama | tidak ada data |
| total | voice | 0 | - | ≤ 10 | N-05 | tidak ada data |
| first_response | voice | 0 | - | ≤ 3 | K-3 | tidak ada data |
| greeting | event | 0 | - | ≤ 3 | N-06 (latency_s event greeted) | tidak ada data |

Tahap SDD 3.3 yang melewati anggaran sementara total, K-3, dan sapaan aman dilaporkan sebagai "lewat anggaran tahap", bukan gagal.
