# CPU-THREADS: pra-registrasi pemilihan thread Piper dan YOLO (laptop dev)

Ditulis 21 Oktober 2026, **sebelum** bench dijalankan (Langkah 50). Aturan di bawah diterapkan apa
adanya pada hasil bench; perubahan setelah melihat data wajib dicatat sebagai penyimpangan.

## Latar

Langkah 49 (f5b3e87): pratinjau kamera patah-patah karena CPU direbut. Proses vision (YOLO,
torch) memakai sekitar 720% satu inti terus-menerus untuk 5 deteksi per detik, dan Piper
(onnxruntime, thread bawaan) memakai 755 sampai 1333% saat menyusun suara, sehingga CPU mesin
mencapai 81 sampai 100%.

## Laptop dev

12th Gen Intel Core i9-12900H, **14 inti fisik** (6 P-core + 8 E-core), **20 inti logis**.
Daya dan mode daya dicatat di hasil bench (tidak diatur oleh bench).

## Kunci config

- `audio.tts.threads`: onnxruntime `intra_op_num_threads` untuk sesi Piper; bila diisi,
  `inter_op_num_threads` = 1 (model dijalankan ORT_SEQUENTIAL). null = bawaan onnxruntime.
- `vision.threads`: `torch.set_num_threads` di proses vision sebelum model dimuat. null = bawaan
  torch. Inter-op torch tidak diubah (satu frame per inferensi).

null tidak mengubah perilaku apa pun (dites di `tests/unit/test_cpu_threads.py`).

## Kandidat

Untuk kedua kunci: **null, 1, 2, 4, 7**.

- null: perilaku lama (pembanding).
- 1, 2, 4: deret pangkat dua kecil. Proses suara dan vision berjalan bersamaan dengan proses utama
  dan Edge, jadi angka kecil memberi ruang ke proses lain.
- 7: separuh inti fisik (14 / 2), batas atas yang masih menyisakan separuh mesin.

## Cara uji

Bench otomatis tanpa orang (`scripts/cpu_threads_bench.py`):

- MICA dijalankan dengan config/dev.yaml + nilai coba (`--trial-values`), kamera asli tanpa orang
  di depannya (deteksi tetap berjalan di `vision.fps_idle` = 5), Edge dibuka MICA dengan
  pratinjau `ui.preview_fps` = 10, dan `--measure-preview`. Pipeline jawaban palsu dipakai supaya
  BGE-M3 tidak dimuat (pipeline tidak dipakai bench, dan pemuatannya mengganggu CPU di awal).
- Satu proses MICA baru per kandidat, karena thread ditetapkan saat proses mulai.
- Setelah halaman tampil dan pemanasan 10 detik, Piper menyusun daftar kalimat tetap: jawaban 8
  pertanyaan pertama (urut qid) berstatus answered dari run dev E-02 gpt-oss-120b prompt v4
  (`results/E-02/20261020-130025-...`), set dev, bukan set uji. Teks diucapkan sama seperti
  controller (`mica.core.spoken`). Setiap jawaban dikirim sebagai Speak, berikutnya dikirim
  setelah yang sebelumnya selesai diucapkan.
- **Tahap 1:** `audio.tts.threads` di {null, 1, 2, 4, 7} dengan `vision.threads` null.
- **Tahap 2:** `vision.threads` di {1, 2, 4, 7} dengan `audio.tts.threads` = pemenang tahap 1;
  kandidat null tahap 2 = run tahap 1 pemenang (tidak diulang).

## Metrik

- **Utama:** p95 jeda antar gambar pratinjau di browser (ms) pada detik berstatus TTS-menyusun.
- Pendamping: waktu sintesis Piper per kalimat (clip), waktu suara pertama (Speak diterima sampai
  clip pertama diputar), waktu deteksi YOLO (p95 dari maksimum per detik), CPU total mesin dan per
  proses, fps digambar browser.

## Aturan pilih

1. Syarat lolos kandidat:
   - p95 waktu suara pertama ≤ 3 detik (anggaran respons pertama, SDD 3.3 dan K-3);
   - perkiraan sapaan ≤ 3 detik (N-06): `1 / vision.fps_idle + p95 waktu deteksi + p95 waktu suara
     pertama`. Bench tanpa orang tidak bisa mengukur sapaan langsung, jadi ini perkiraan
     konservatif (suara pertama memakai jawaban panjang, bukan kalimat sapaan).
2. Di antara yang lolos: p95 jeda pratinjau saat TTS-menyusun **terkecil** menang.
3. Seri: selisih p95 jeda < 17 ms (satu periode refresh layar 60 Hz; beda di bawah ini tidak
   terlihat). **Nilai desain pra-registrasi**, bukan hasil ukur. Bila seri, pilih thread lebih
   sedikit; null dihitung sebagai jumlah inti fisik (14) untuk pemecah seri ini.
4. Bila tidak ada kandidat yang lolos syarat, nilai tetap null.

Hasil dicatat apa adanya di `results/cpu-threads/<timestamp>/`; nilai terpilih diisi di
config/dev.yaml dengan komentar "dipilih CPU-THREADS.md, laptop dev".

## Catatan

- Diukur di laptop dev. Nilai kiosk **dipilih ulang dengan aturan yang sama di E-09**. Grid E-09
  yang sudah dipra-registrasi (vision.threads {1, 2}, audio.stt.threads {2, 4}) tetap berlaku untuk
  E-09; dokumen ini hanya untuk laptop dev dan pratinjau.
- Kalau run terpandu B dengan nilai terpilih membuat alur gagal (sapaan, transkripsi, jawaban dan
  sumber, TTS, akhir sesi), config/dev.yaml dikembalikan ke null.
- `ui.preview_fps`, `vision.fps_idle`, dan `vision.fps_busy` tidak diubah.

## Penyimpangan (ditulis setelah bench pertama, 21 Oktober 2026)

- **Tahap 2 bench pertama (`results/cpu-threads/20261021-131908/`) tidak sah dan diulang.**
  Ultralytics 8.4 `select_device` memanggil `torch.set_num_threads(8)` saat inferensi pertama,
  sehingga `vision.threads` yang dipasang sebelum model dimuat tertimpa. Kelima kandidat tahap 2
  sebenarnya berjalan dengan 8 thread yang sama (CPU vision sekitar 720% di semua kandidat, waktu
  deteksi tidak berubah). Diperbaiki di kode (setelan dipasang setelah inferensi pemanasan), lalu
  tahap 2 diulang dengan kandidat dan aturan yang sama, `audio.tts.threads` = 1 (pemenang tahap 1
  yang tidak terpengaruh bug). Alasan pengulangan adalah bug alat, bukan hasil yang tidak disukai.
  Hasil tahap 2 lama tetap disimpan untuk transparansi.
- Tahap 1 sah: `audio.tts.threads` terbukti berlaku (intra_op 1 tercatat di sesi onnxruntime; CPU
  proses suara saat menyusun turun dari 819% ke 36%).
- Arti `vision.threads` null: YOLO berjalan 8 thread (nilai Ultralytics), bukan bawaan torch 14.
  Pemecah seri tetap menghitung null sebagai 14 seperti pra-registrasi.
