# E-05 sweep penyaring push-to-talk (verdict)

Aturan: docs/AMANDEMEN-2026-11-03.md bagian A. Kombinasi A1: 27. Pemenang dipilih mekanis.

## A1

- audio.vad.threshold = 0.7
- audio.vad.min_speech_ms = 250
- audio.stt.no_speech_threshold = 0.8
- pertanyaan asli tersaring pada pemenang: 1 dari 300 (no_voice 1, min_speech 0, no_speech 0)
- transkripsi palsu (diam/bising): 0 dari 120
- jarak langkah ke bawaan library: 2
- WER total (dilaporkan, tidak menentukan): 0.1893

## A2

- audio.max_utterance_s = 15
- pertanyaan terpotong pada pemenang: 0 dari 300
