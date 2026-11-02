# PROD-TBD: peta kunci prod yang belum terisi (PROD-1, 2 Nov 2026)

Dokumen ini hanya mencatat keadaan. Tidak ada config, kode, atau `docs/SDD.md` yang diubah, dan
tidak ada nilai yang diputuskan di sini.

## Sumber

- `python -m mica check --config config/prod.yaml` di commit bc37da4 melaporkan **35 kunci belum
  diisi**. Ini cocok dengan SDD bagian 12: 36 kunci, lalu vision.imgsz diisi di CV-6.
- Nilai dev diambil dari `config/dev.yaml` di bc37da4.
- Nilai Tahap 1 diambil dari `data/eval/official/runs/tahap1/manifest.json` dan `config/dev.yaml`
  di commit run 97b055c (`git_dirty` false). Tag `tahap1-beku` (1a9b537) tidak mengubah config
  sejak 97b055c (`git log 97b055c..tahap1-beku -- config/` kosong).
  - Manifest juga mencatat: `config_hash` 17d5b6e5…, KB official-2026-10-24-v5, prompt v5,
    hybrid, rrf_k 60, top_k 5, gate 0,5, fact_check true.
  - Rantai cadangan LLM **dimatikan**: hanya llm.chain[0] yang dipakai.
- Untuk kunci suara dan vision, nilai di config Tahap 1 sama dengan dev. Kunci itu tidak dipakai
  oleh uji teks Tahap 1, sehingga ditulis "(tidak dipakai)".
- Nilai coba yang disebut di tabel berasal dari SDD bagian 12. Nilai itu bukan isi config.

## Tabel kunci

Keterangan kolom "Sendiri?": apakah pemilik proyek bisa mengerjakannya sendiri di laptopnya tanpa
orang lain.

### A. RAG dan LLM (11 kunci)

| Kunci | Eksperimen (SDD 12) | config/dev.yaml | Config uji Tahap 1 | Protokol pra-registrasi | Data yang dibutuhkan | Sendiri? |
|---|---|---|---|---|---|---|
| kb.chunk_tokens | E-01 | 400 | 400 (KB v5 dibangun dengan 400) | Belum ada docs/E-01.md. Hanya ada tabel hook SDD 9.5 dan aturan di laporan keputusan. Run resmi `results/E-01/official-20261024-203849` ada. | Tidak ada (memakai nilai Tahap 1) | ya, tinggal menyalin nilai Tahap 1 |
| kb.overlap_tokens | E-01 | 50 | 50 (KB v5) | sama dengan baris di atas | Tidak ada | ya |
| kb.embedder.revision | Keputusan rekayasa N-14 | 9a0624b896d81da7492a910ffa53731274b6cf3d | sama (juga tercatat di manifest KB v5) | Tidak perlu protokol (keputusan rekayasa). `mica check` juga gagal di baris "KB aktif" karena kunci ini null. | Tidak ada | ya |
| rag.rrf_k | E-01 | 60 | 60 | sama dengan kb.chunk_tokens | Tidak ada | ya |
| rag.candidates_per_retriever | E-01 | 20 | 20 | sama dengan kb.chunk_tokens | Tidak ada | ya |
| rag.gate.threshold | E-02 | 0.5 | 0.5 | Belum ada docs/E-02.md. Hanya ada SDD 9.5. Aturan seri ditambah setelah melihat data (SDD 12). Run resmi `results/E-02/official-20261024-204004` ada. | Tidak ada | ya |
| llm.chain[0] | E-04 | groq:openai/gpt-oss-120b | groq:openai/gpt-oss-120b | docs/E-04.md (pra-registrasi 1d04e85, 19 Okt 2026; amandemen e23dd81). Isinya pembanding Gemini. | Tidak ada | ya |
| llm.chain[1] | E-04 | groq:openai/gpt-oss-20b | groq:openai/gpt-oss-20b ada di config, tetapi **tidak dipakai** (cadangan dimatikan di Tahap 1) | sama dengan llm.chain[0] | Tidak ada | ya, tetapi nilai ini tidak teruji di Tahap 1 |
| llm.timeout_s | E-04 | 10 | 10 | sama dengan llm.chain[0] | Tidak ada | ya |
| llm.temperature | E-04 | 0.2 | 0.2 | sama dengan llm.chain[0] | Tidak ada | ya |
| llm.reasoning_effort | E-04 | low | low | sama dengan llm.chain[0] | Tidak ada | ya |

Di `config/prod.yaml`, llm.chain[0] dan llm.chain[1] masih berisi teks pengganti
`groq:<id gpt-oss-120b>` dan `groq:<id gpt-oss-20b>`, jadi `mica check` menghitungnya belum terisi.

### B. Suara, E-05 (6 kunci)

| Kunci | Eksperimen (SDD 12) | config/dev.yaml | Config uji Tahap 1 | Protokol pra-registrasi | Data yang dibutuhkan | Sendiri? |
|---|---|---|---|---|---|---|
| audio.stt.threads | E-05 dan E-09 | null (bawaan library, 4 di laptop dev) | null (tidak dipakai) | docs/E-05.md (cdaede3, 17 Okt 2026; amandemen 1 di 5697a05): kandidat `--threads 2,4`. docs/E-09.md (bfb2580): grid {2, 4}. | Rekaman suara N orang (N masih TBD) dan sesi E-09 | sebagian: alat dan pilot bisa dijalankan sendiri, tetapi angka resmi butuh relawan dan laptop setara laptop PMB |
| audio.stt.no_speech_threshold | E-05 | null (nilai coba 0,6 lewat CLI) | null (tidak dipakai) | docs/E-05.md. Tidak ada aturan pilih atau grid; "Nilai VAD dan penyaring masih TBD". | Rekaman `diam` dan `bising` dari N orang | sebagian: rekaman diam dan bising bisa dibuat sendiri, tetapi aturan pilihnya belum ada |
| audio.vad.threshold | E-05 | null (nilai coba 0,5) | null (tidak dipakai) | docs/E-05.md. Tidak ada aturan pilih atau grid. | Rekaman suara N orang | sebagian: aturan pilih belum ada, data resmi butuh relawan |
| audio.vad.min_silence_ms | E-05 | null (nilai coba 500) | null (tidak dipakai) | docs/E-05.md amandemen 1: hanya dipakai mode `vad`. Prod memakai `push_to_talk`. | Rekaman suara (hanya untuk mode `vad`) | sebagian: tidak berpengaruh di mode prod sekarang |
| audio.vad.min_speech_ms | E-05 | null (nilai coba 250) | null (tidak dipakai) | docs/E-05.md. Tidak ada aturan pilih atau grid. | Rekaman suara N orang | sebagian |
| audio.max_utterance_s | E-05 | null (nilai coba 15, tanpa sumber) | null (tidak dipakai) | docs/E-05.md. Tidak ada aturan pilih atau grid. | Rekaman suara N orang | sebagian |

### C. Vision, E-07 dan E-08 (14 kunci)

| Kunci | Eksperimen (SDD 12) | config/dev.yaml | Config uji Tahap 1 | Protokol pra-registrasi | Data yang dibutuhkan | Sendiri? |
|---|---|---|---|---|---|---|
| vision.conf | E-07 | 0.1 | 0.1 (tidak dipakai) | docs/E-07.md (126e390, 18 Okt 2026; amandemen 1 di 8341228): conf ∈ {0,1; 0,25; 0,5} pada yolo26n-pose | Frame berlabel YOLO dari relawan (N masih TBD) | sebagian: pelabelan bisa dikerjakan sendiri, tetapi frame resmi butuh beberapa relawan dengan persetujuan |
| vision.presence_signal | E-07 | shoulder_width | shoulder_width (tidak dipakai) | docs/E-07.md amandemen 1 mewajibkan sinyal lebar bahu (yolo26n-pose). Nilainya ditetapkan oleh amandemen, bukan oleh grid. | Tidak ada data baru | ya, tetapi perlu keputusan bahwa amandemen dipakai sebagai sumber nilai |
| vision.min_shoulder_ratio | E-07 | null (nilai coba 0,22) | null (tidak dipakai) | docs/E-07.md bagian 2: grid {0,18; 0,22; 0,26} | Klip video kunjungan N orang dengan anotasi waktu | sebagian: kalibrasi jarak bisa dicoba sendiri, tetapi klip resmi butuh relawan |
| vision.min_box_height_ratio | E-07 | null | null (tidak dipakai) | docs/E-07.md amandemen 1: "grid `min_box_height_ratio` tidak diperlukan" (hanya untuk sinyal box_height) | Tidak ada eksperimen yang akan mengisinya | tidak relevan selama presence_signal = shoulder_width; tetap dihitung oleh `mica check` |
| vision.dwell_s | E-07 | null (nilai coba 2) | null (tidak dipakai) | docs/E-07.md bagian 2: grid {1, 2, 3} | Klip video kunjungan N orang | sebagian |
| vision.leave_s | E-07 | null (nilai coba 3) | null (tidak dipakai) | docs/E-07.md bagian 2: grid {2, 3, 5} | Klip video kunjungan N orang | sebagian |
| session.regreet_cooldown_s | E-07 | null (tanpa jeda) | null (tidak dipakai) | docs/E-07.md bagian 2: grid {0, 30, 60} | Klip video kunjungan N orang (pergi lalu kembali) | sebagian |
| vision.box_upper.top | E-08 | null (nilai coba 0,35) | null (tidak dipakai) | docs/E-08.md (126e390; amandemen 1 di 8341228). **Tidak disweep**: dipakai tetap pada nilai coba SDD 12. | Tidak ada eksperimen yang akan menetapkannya | ya untuk menyalin, tetapi perlu keputusan karena nilai coba tidak punya sumber dari eksperimen |
| vision.box_upper.bottom | E-08 | null (nilai coba 0,65) | null (tidak dipakai) | sama dengan box_upper.top | sama | sama |
| vision.box_upper.side | E-08 | null (nilai coba 0,25) | null (tidak dipakai) | sama dengan box_upper.top | sama | sama |
| vision.keypoint_torso.min_kp_conf | E-08 | null (nilai coba 0,5) | null (tidak dipakai) | docs/E-08.md dan docs/E-07.md bagian 2: tetap 0,5, **tidak disweep** | Tidak ada eksperimen yang akan menetapkannya | sama dengan box_upper |
| vision.keypoint_torso.shrink | E-08 | null (nilai coba 0,15) | null (tidak dipakai) | docs/E-08.md: tetap pada nilai coba, **tidak disweep** | sama | sama |
| vision.keypoint_torso.torso_aspect | E-08 | null (nilai coba 1,2) | null (tidak dipakai) | docs/E-08.md: tetap pada nilai coba, **tidak disweep** | sama | sama |
| vision.color.min_majority | E-08 | null (nilai coba 0,6) | null (tidak dipakai) | docs/E-08.md: {0,5; 0,6; 0,7}, hanya bila `lut_vote` menang | Frame relawan dengan baju beragam warna, diberi label oleh **2 penilai** (kappa) | tidak: butuh penilai kedua dan relawan |

### D. Beban laptop, E-09 (4 kunci)

| Kunci | Eksperimen (SDD 12) | config/dev.yaml | Config uji Tahap 1 | Protokol pra-registrasi | Data yang dibutuhkan | Sendiri? |
|---|---|---|---|---|---|---|
| vision.fps_busy | E-09 | null (laju tetap fps_idle 5) | null (tidak dipakai) | docs/E-09.md (bfb2580, 18 Okt 2026; amandemen 0ed2f0e, 5697a05, 5befe70): grid {1, 2, 5} | Sesi pemakaian asli (suara + kamera). Jumlah pertanyaan dan pengunjung masih TBD. | ya untuk kalibrasi (pengguna bisa memerankan pengunjung sendiri), tetapi hasilnya hanya indikatif bila bukan di laptop setara laptop PMB |
| vision.threads | E-09 | 7 (CPU-THREADS.md, laptop dev) | 7 (tidak dipakai) | docs/E-09.md: grid {1, 2}. Untuk dev: docs/CPU-THREADS.md (0bdc936). | sama dengan fps_busy | ya, dengan catatan yang sama |
| audio.tts.threads | E-09 (SDD 12) | 1 (CPU-THREADS.md, laptop dev) | 1 (tidak dipakai) | Grid E-09 **tidak memuat** audio.tts.threads. docs/CPU-THREADS.md (0bdc936) menulis nilai prod "dipilih ulang dengan aturan yang sama di E-09". | Bench seperti CPU-THREADS di laptop target | ya, tetapi grid untuk kunci ini di E-09 belum tertulis |
| session.idle_reset_s | E-09 dan uji pengguna | null (tidak pernah timeout) | null (tidak dipakai) | **belum ada** (tidak ada di docs/E-09.md) | Peserta uji pengguna (SUS) | tidak: butuh peserta, dan protokolnya belum ada |

Jumlah: A 11 + B 6 + C 14 + D 4 = **35**.

### Catatan: kunci yang di SDD tertulis TBD tetapi sudah terisi di prod.yaml

Kunci-kunci berikut tidak dilaporkan `mica check` karena prod.yaml sudah berisi nilai. Di SDD
bagian 12 statusnya masih TBD atau Provisional:

- rag.retriever = hybrid
- rag.reranker.enabled = false
- rag.prompt_variant = v5 (SDD: TBD, E-03)
- rag.followup_mode = dual
- audio.stt.backend = faster_whisper (SDD: TBD, E-05)
- vision.region = keypoint_torso (SDD: TBD, E-08)
- vision.color.method = lut_vote (SDD: TBD, E-08)

Nilainya sama dengan dev dan Tahap 1. Dicatat saja; tidak ada yang diputuskan.

## 3. RAG/LLM: dev sekarang vs config Tahap 1

**Tidak ada kunci RAG/LLM yang berbeda.** Kesebelas kunci kelompok A sama persis antara
`config/dev.yaml` (bc37da4) dan config Tahap 1 (97b055c). Begitu juga kb.active_id,
kb.embedder.model, rag.retriever, rag.reranker.enabled, rag.prompt_variant, rag.followup_mode, dan
rag.top_k.

Diff dev.yaml 97b055c..bc37da4 hanya mengubah hal-hal berikut:

- komentar kata kiosk menjadi prod;
- `ui.backend` dan `ui.fullscreen` dihapus (RF-2);
- `ui.preview_fps` 15 menjadi 24 (CV-3).

Satu catatan: llm.chain[1] ada di config Tahap 1, tetapi tidak dipakai karena rantai cadangan
dimatikan. Bukti retrieval sama: banding 10 soal setelah CV-6 identik dengan tag `tahap1-beku`.

## 4. Data E-05

- `data/eval/speech/` hanya berisi `contoh/manifest.jsonl`: 3 baris (1 pertanyaan, 1 diam,
  1 bising) dari 1 penutur (P01). File WAV-nya tidak ada. Ini hanya contoh format.
- **Belum ada dataset E-05 resmi**: 0 rekaman relawan.
- Yang ada hanya dua hal:
  - pilot `results/E-05/pilot-dev-20261017-143739`: 10 kalimat d001-d010, rekaman mikrofon
    langsung, penutur tidak dicatat, bukan manifest, WER total 0,203;
  - dua uji asap sintetis Piper (bukan hasil E-05).
- Jumlah penutur dan jumlah kalimat per penutur masih TBD di docs/E-05.md ("disepakati dengan
  pembimbing").

## 5. Data E-07 dan E-08

- `data/eval/vision/` dan `data/eval/vision_scenarios/` hanya berisi `README.md` dan `.gitkeep`.
- **0 frame berlabel, 0 klip, 0 anotasi, 0 label warna.** Folder `results/E-07/` dan
  `results/E-08/` belum ada.
- `D:\SKRIPSI\datasets\coco` (val2017) dipakai untuk sweep imgsz CV-2. Data itu bukan data relawan
  E-07 atau E-08.
- Jumlah relawan, frame, dan klip masih TBD di docs/E-07.md ("item diskusi dengan pembimbing").

## 6. E-09

- **Belum ada run E-09 resmi.** Isi `results/E-09/` hanya `smoke-20261018-052038`. Verdict-nya
  berbunyi "Uji alat, bukan hasil E-09", dengan status TIDAK LENGKAP dan n = 0 untuk tahap suara.
  Amandemen 3 (1 Nov 2026) menegaskan hal yang sama.
- Grid kalibrasinya **bergantung pada audio.stt.backend**, walaupun ketergantungan ini tidak
  ditulis eksplisit:
  - grid memuat `audio.stt.threads` ∈ {2, 4}, yang hanya bermakna untuk STT lokal
    (faster_whisper);
  - E-09 menuntut "semua proses asli ... RAG konfigurasi C2", padahal C2 belum dibekukan.
    `config/frozen-<tanggal>.yaml` (SDD 9.5) belum ada.
  - Bila E-05 memilih groq_whisper, beban CPU STT hilang dan grid thread STT tidak relevan.
- Jumlah pertanyaan dan pengunjung per kombinasi masih TBD ("disepakati sebelum run").
- audio.tts.threads tidak ada di grid E-09 (lihat tabel D).

## 7. Laptop: harus laptop PMB?

Kutipan apa adanya:

- docs/E-09.md Tujuan 1: "... dengan UI web ... **di laptop kiosk atau laptop yang mirip**."
- docs/E-09.md Keterbatasan: "Spesifikasi laptop kiosk belum diketahui. **Bila E-09 diukur di
  laptop dev, hasilnya hanya indikatif.**"
- docs/E-05.md: "**Syarat p95 hanya sah bila diukur di laptop kiosk.**" Aturan SDD 2.4 yang
  disalin di sana: "p95 waktu sampai transkripsi tampil paling lama 3 detik di laptop kiosk".
- docs/SDD.md 9.4, baris Latensi: "Log 6.2 dari sesi E-09 | **C2 di laptop setara laptop PMB**".
- docs/SDD.md MS4: "**Uji di laptop yang setara laptop PMB** | ... | Anggaran latensi 3.3 diukur;
  `fps_busy` dan jumlah thread ditetapkan".
- docs/SDD.md 2.3: "Laptop PMB: Windows 10/11 64-bit, CPU x86-64 tanpa GPU, minimal 8 GB RAM, ...
  **Spesifikasi sebenarnya belum diketahui** (pertanyaan terbuka PRD), sehingga asumsi ini
  konservatif dan dicek di E-09."
- docs/CPU-THREADS.md: "Diukur di laptop dev. **Nilai kiosk dipilih ulang dengan aturan yang sama
  di E-09.**"
- docs/E-07.md (a): frame "dari kamera kiosk (atau kamera yang sama jenisnya)".

Artinya:

- Untuk ukuran waktu dan CPU (E-09, syarat p95 E-05, thread), laptop pengembang **hanya
  indikatif**. Yang sah adalah laptop PMB atau laptop yang setara/mirip.
- Kata "kiosk" di E-05, E-07, dan E-09 belum diganti menjadi "laptop PMB".
- Untuk ukuran yang tidak bergantung waktu, dokumen tidak mewajibkan laptop PMB. Contohnya WER,
  akurasi deteksi, dan akurasi warna. E-07 hanya meminta kamera yang sama jenisnya.
