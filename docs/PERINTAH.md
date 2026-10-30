# Perintah penting MICA

Semua perintah dijalankan dari akar repo (PowerShell) setelah `.venv\Scripts\Activate.ps1`.
Opsi lengkap tiap perintah: tambahkan `--help`. Perintah bertanda **(dev)** ditolak bila
`app.mode: kiosk`.

## 1. Pemasangan (sekali, lihat docs/KIOSK.md)

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.lock
pip install -e . --no-deps
python -m mica setup                      # unduh semua model terkunci (sha256/revisi)
python -m mica setup --only BGE-M3        # ulang satu komponen saja
```

`.env` berisi `GROQ_API_KEY=...` (tidak pernah di-commit).

## 2. Menjalankan

```
python -m mica check                                  # cek kesiapan, kode keluar 1 bila GAGAL
python -m mica                                        # kiosk (config/kiosk.yaml)
python -m mica --config config/dev.yaml               # mode dev, perangkat asli
python -m mica --config config/dev.yaml --trial-values  # isi null dengan nilai coba SDD 12 (dev)
python -m mica.webui --config config/dev.yaml --fake-workers --fake-pipeline   # tanpa kamera/mic/Groq (dev)
python -m mica.webui --config config/dev.yaml --fake-workers --fake-camera     # kamera palsu (dev)
python -m mica.webui --config config/dev.yaml --no-browser                     # server saja, Ctrl+C
python -m mica.webui --config config/dev.yaml --guided-test                    # uji terpandu ~5 menit (dev)
python -m mica.webui --config config/dev.yaml --measure-preview                # ukur fps pratinjau (dev)
python -m mica.ui --config config/dev.yaml                                     # UI PySide6 (cadangan beku)
```

## 3. Knowledge base (M-02) dan RAG

```
python -m mica.kb init-sources --src data/sources/<folder> --source-type dev --date YYYY-MM-DD
python -m mica.kb check-sources --src data/sources/<folder>
python -m mica.kb build --src data/sources/<folder> --kb-id <id> --source-type dev --config config/dev.yaml
python -m mica.kb list
python -m mica.kb inspect --kb-id <id> [--doc <doc_id> --samples 3] [--table-match "<teks>"]   # chunk per dokumen, contoh + halaman + bagian
python -m mica.rag search "<pertanyaan>" --config config/dev.yaml [--retriever bm25|dense|hybrid] [--k 5]
python -m mica.ask "<pertanyaan>" [--prev "<pertanyaan sebelumnya>"]   # satu jawaban lewat AnswerPipeline (dev)
```

KB yang dipakai ditentukan `kb.active_id` di config.

## 4. Audio dan vision (dev)

```
python -m mica.audio fetch-voice
python -m mica.audio fetch-stt-model
python -m mica.audio listen --list-devices
python -m mica.audio listen --vad-threshold X --min-silence-ms X --max-utterance-s X [--echo]
python -m mica.audio say "<teks>"  |  python -m mica.audio say --file data/speech/tts_dev_sentences.txt
python -m mica.vision fetch-model
python -m mica.vision fetch-colors
python -m mica.vision demo [--camera 0] [--video <path>] --dwell-s X --leave-s X --min-ratio X
```

Audio dan gambar tidak pernah ditulis ke disk.

## 5. Evaluasi (M-12)

```
python -m mica.eval dataset status
python -m mica.eval dataset split --input <file resmi> --out-dir data/eval/official/
python -m mica.eval dataset lock --dataset data/eval/official/test.jsonl --reason "<teks>"
python -m mica.eval annotate export --config config/dev.yaml --dataset data/eval/questions.jsonl --out data/eval/pool.csv
python -m mica.eval annotate import --dataset data/eval/questions.jsonl --pool data/eval/pool.csv
python -m mica.eval retrieval  --config config/dev.yaml --dataset data/eval/questions.jsonl --out results/E-01   # E-01
python -m mica.eval gate       --config config/dev.yaml --dataset data/eval/questions.jsonl --out results/E-02-gate
python -m mica.eval generation --config config/dev.yaml --dataset data/eval/questions.jsonl --out results/E-02 --gate-off [--model penyedia:id]  # E-02/E-04
python -m mica.eval annotation --run <folder run generation>                         # tingkat halusinasi
python -m mica.eval tahap1 --questions data/eval/official/uji-tahap1-129.csv --out data/eval/official/runs/tahap1 [--limit N]  # Uji Tahap 1, resume otomatis
python -m mica.eval copy  --config config/dev.yaml --runs <folder run> ...            # E-03
python -m mica.eval stt   --config config/dev.yaml --dataset <manifest.jsonl>         # E-05
python -m mica.eval vision --config config/dev.yaml --dataset data/eval/vision/<nama> # E-07
python -m mica.eval vision-scenarios --config config/dev.yaml --dataset data/eval/vision_scenarios/<nama> --model <pemenang>
python -m mica.eval color  --config config/dev.yaml --dataset data/eval/vision/<nama> # E-08
python -m mica.eval latency --logs logs/ --label <label> [--resources <csv>]          # E-09
python scripts/compare_models.py RUN_A RUN_B --labels 20b 120b --out-dir results/E-04 --prefix <nama>
```

## 6. Log

```
python -m mica.logs export --from YYYY-MM-DD --to YYYY-MM-DD --out turns.csv [--kind turns|events]
```

## 7. Skrip pengukuran (scripts/)

```
python scripts/startup_profile.py --label <nama>        # waktu mulai (atau scripts/l40_startup.ps1)
python scripts/cpu_threads_bench.py --stage all         # thread Piper/YOLO (docs/CPU-THREADS.md)
python scripts/camera_rate.py [--fake]                  # laju kamera vs ui.preview_fps
python scripts/ui_bench.py --ui web                     # CPU/RAM UI web (docs/UI-WEB.md)
python scripts/ui_preview_opt.py grow|ab|decide ...     # biaya pratinjau (docs/UI-PREVIEW-OPT.md)
python scripts/ui_screens.py [--out docs/ui-screens]    # tangkapan layar UI otomatis
python scripts/ui_contrast.py                           # rasio kontras token warna
python scripts/session_table.py                         # tabel transisi M-09
python scripts/e05_smoke_synthetic.py                   # uji asap eval stt tanpa mikrofon
```

## 8. Sebelum commit

```
pytest
ruff check .
ruff format --check .
```
