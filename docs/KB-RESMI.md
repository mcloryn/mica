# KB resmi (Langkah 61, 23 Okt 2026)

KB aktif sejak Langkah 61: **`official-2026-10-23-v1`** (`source_type: official`), di
`config/dev.yaml` dan `config/kiosk.yaml` (`kb.active_id`). KB dev `dev-2026-10-15-v2`
diarsipkan: tidak dihapus dari `data/kb/`, ID-nya ditulis sebagai komentar di kedua config.

Dokumen sumber dan isi KB tidak di-commit (`.gitignore`: `data/sources/`, `data/kb/*`).

## Sumber

Asal: `D:\SKRIPSI\kb-resmi-masuk\` (dari hasa). Disalin byte-identik (SHA-256 sama) ke
`data/sources/official/<kelompok>/`; nama file diganti agar `doc_id` terbaca.

| doc_id | judul (sources.yaml) | file asal | valid_from | dasar valid_from |
|---|---|---|---|---|
| `pmb/pedoman-pmb-2027` | Pedoman Penerimaan Mahasiswa Baru Universitas Mikroskil Tahun 2027 | `acd40be8…a0d.pdf` (13 hlm) | 2026-07-27 | Keputusan Rektor No. 697/UM.348/01/KM/2026, "Pada tanggal: 27 Juli 2026" (hlm PDF 2) |
| `akademik/peraturan-akademik-2025` | Peraturan Akademik Universitas Mikroskil Tahun 2025 | `Peraturan Akademik Tahun 2025.pdf` (38 hlm) | 2025-01-22 | Peraturan Rektor No. 052/UM.348/05/AK/2025, "Pada tanggal: 22 Januari 2025" (hlm PDF 38) |
| `kemahasiswaan/panduan-kemahasiswaan-2021` | Buku Panduan Peraturan Kemahasiswaan Universitas Mikroskil 2021 | `Buku Panduan Peraturan Kemahasiswaan Universitas Mikroskil 2021.pdf` (47 hlm) | 2021-09-06 | Keputusan Rektor No. 018/UM.348/01/KM/2021, "Pada tanggal: 06 September 2021" (hlm PDF 2). Dokumen lama, pelengkap. |
| `brosur/brosur-pmb-2025` | Brosur Pendaftaran Universitas Mikroskil 2025 | `brosur-pmb-2025.md` (ketikan ulang) | 2025-01-01 | Tahun dari keterangan hasa; tidak tertulis di brosur. |

Ketiga tanggal SK tertulis jelas, jadi aturan "YYYY-01-01, hanya tahun diketahui" tidak dipakai
untuk PDF. Catatan: nomor Peraturan Akademik memuat "/05/" padahal tanggal penetapannya
22 Januari 2025; yang dipakai tanggal tertulis.

## Brosur: kenapa ketikan ulang

Brosur asli ("Brosur Pendaftaran Mikroskil.pdf", 18 halaman) menyimpan sebagian besar teksnya
di dalam gambar (misalnya hlm 4), sehingga parser PDF tanpa OCR (SDD 2.3) tidak mendapat
teksnya. hasa mengetik ulang isinya apa adanya ke Markdown berfrontmatter `title`, dengan
heading per bagian yang menyebut halaman brosur. Hanya dua salah ketik diperbaiki (hlm 4
"terakreditas", hlm 8 "mengingkatkan"; dicatat di file).

Halaman brosur yang tidak dimasukkan:

- alumni/testimoni: hlm 3, 7, 15;
- logo mitra: hlm 10;
- foto, sampul, dan slogan.

## Build

| | |
|---|---|
| kb_id | `official-2026-10-23-v1` |
| perintah | `python -m mica.kb build --src data/sources/official --kb-id official-2026-10-23-v1 --source-type official --config config/dev.yaml` |
| dokumen / chunk | 4 / 143 (tabel: 0) |
| chunk per dokumen | Peraturan Akademik 58, Panduan Kemahasiswaan 55, Brosur 15, Pedoman PMB 15 |
| lama build | 109,3 detik (laptop dev, CPU) |
| ukuran | 1,1 MB |
| chunker | `structure_then_fixed`, `chunk_tokens` 400, `overlap_tokens` 50 (nilai awal dev, sama dengan KB dev) |
| config_hash | `d4ce25f8c3164a6d696cff92da582706aa34fe38e9de5232883729eff65b3dab` (sama dengan KB dev) |
| embedder | BAAI/bge-m3 rev `9a0624b896d81da7492a910ffa53731274b6cf3d` (`model.safetensors`), dim 1024 |
| paket | sentence-transformers 6.1.0, torch 2.14.1+cpu (KB dev mencatat "2.14.1" karena dibangun sebelum commit 68f7a93 yang mencatat akhiran build; versinya sama) |
| built_at | 2026-10-23T16:54:35+07:00 |

SHA-256 dokumen sumber (dari `manifest.json`):

| doc_id | sha256 |
|---|---|
| `akademik/peraturan-akademik-2025` | `ccc065e4750b3179f90ef46f6d913ebfb7e1c2d530be95e2f08cc3b0da9a3ac7` |
| `brosur/brosur-pmb-2025` | `b8a4beab6b883bf04c1c9ce00e39a02c6a828d49ab66f416f7dad818ff6a5b07` |
| `kemahasiswaan/panduan-kemahasiswaan-2021` | `68ccca5d7348cdcec0dbd1b3e8aa989424abe84306caffbc67cb41dca7568b52` |
| `pmb/pedoman-pmb-2027` | `baf0877bb3f01acc416d7d338cdc31c3a79b69c61c5a2c0da1e0aa7db76c89dd` |

SHA-256 file KB:

| file | sha256 |
|---|---|
| `manifest.json` | `aa8524b52664c6e54a448e4cbce5148acb42f0dbf3965ad04edbed45f1ea85bf` |
| `chunks.jsonl` | `85c9ea1b2dd485075c6b6ed44c79658b879e05ffe95c742368b66e92e312bac9` |
| `dense.npy` | `a7b6b82f8fbdf58297ab097b0431a574c7607487ea6ea07d3a02436ade1fa182` |
| `bm25.pkl` | `2c3cf557daac64517e3f24f56d58b934489b766ef26e72bbab6a70b2695ab84a` |

## Cek ekstraksi

Rincian: `results/kb-official/ekstraksi-2026-10-23.md` (parser yang sama dengan build,
pypdf 6.20.1, per halaman). Ringkasnya:

- Tidak ada halaman kosong atau hasil pindai. Halaman < 200 karakter hanya tiga sampul.
- Tabel tidak dikenali sebagai tabel (PDF menjadi blok teks tanpa `section`):
  - Pedoman PMB hlm 8-9, tabel Persyaratan Khusus per prodi: sel prodi dan persyaratan
    bergantian per baris, judul kolom menyatu, baris Manajemen (S-1) menyatu dengan isinya,
    tabel terpotong pergantian halaman. Urutan isi benar.
  - Peraturan Akademik hlm 29, konversi NSM/NMK/NAM: judul kolom terpecah, baris data utuh.
  - Peraturan Akademik hlm 30: rumus IPS/IPK rusak (huruf matematika Unicode).
  - Halaman SK (PMB hlm 2, Akademik hlm 4, Kemahasiswaan hlm 2): nomor butir
    "Menimbang/Mengingat" terpisah dari teksnya.
- Kata terpotong spasi: hampir di setiap halaman Panduan Kemahasiswaan 2021 (mis.
  "Mikr oskil", "de ngan", "Kem ahasiswaan"), 1-2 kata per halaman di 12 halaman Peraturan
  Akademik, tidak ada di Pedoman PMB.
- Isi dokumen tidak diperbaiki; hasa membandingkan dengan PDF.

Akibat lain: chunk PDF tidak punya judul bagian (`section` ""), jadi sitasi PDF hanya
menyebut dokumen dan nomor chunk.

## Dataset eval lama dan KB resmi

`data/eval/questions.jsonl`, `pool.csv`, dan `dev_topic_switch.jsonl` dibuat dan dianotasi
pada KB dev. Sejak Langkah 61, perintah `python -m mica.eval` yang memuat KB (annotate export,
retrieval, gate, generation, followup, stt) memanggil `mica.eval.kb_match.check_dataset_files`
dan menolak (exit 2) dataset yang:

- tercatat di `pool_meta.json` dengan kb_id lain, atau
- memuat `gold_chunk_ids` atau doc_id `gold_refs` yang tidak ada di KB aktif.

Jadi E-01..E-04 tidak bisa diam-diam dijalankan ulang dengan dataset lama pada KB resmi.
Untuk mereproduksi hasil lama, set `kb.active_id` kembali ke `dev-2026-10-15-v2`.
E-01/E-02 belum dijalankan pada KB resmi.

## Uji asap

Lima pertanyaan lewat `python -m mica.ask` (4 panggilan LLM), hanya cek fungsi, bukan evaluasi.
Pertanyaan ini tidak boleh dipakai sebagai set uji. Hasil di `RINGKASAN.md` (tidak di-commit).

## Penyimpangan yang harus diungkap di Bab 3

1. **KB dev diarsipkan.** E-01..E-04 diukur pada `dev-2026-10-15-v2` (dokumen dev, bukan
   dokumen resmi). KB aktif sekarang `official-2026-10-23-v1`; hasil E-01..E-04 belum diukur
   ulang pada KB resmi.
2. **Ambang gerbang 0,50 adalah nilai coba.** Dikalibrasi di KB dev, belum diukur ulang di KB
   resmi (`rag.gate.threshold` di `config/dev.yaml`; di `config/kiosk.yaml` tetap null/TBD).
   Pada uji asap, pertanyaan di luar KB (gelombang 2) ditolak dengan skor 0,487, hanya 0,013 di
   bawah ambang.
3. **Chunking memakai nilai awal dev** (`chunk_tokens` 400, `overlap_tokens` 50), belum
   dikalibrasi untuk dokumen resmi (PDF panjang tanpa heading, berbeda dengan Markdown dev).
4. **Biaya kuliah berasal dari brosur tahun 2025** (tahun dari keterangan hasa, tidak tertulis
   di brosur), sedangkan Pedoman PMB 2027 hanya menyatakan uang kuliah ditetapkan Rektor setiap
   tahun tanpa angka. Brosur juga mencantumkan TOEFL 475 untuk Magister Manajemen, sedangkan
   Pedoman PMB 2027 tidak (TOEFL hanya untuk Magister TI); jawaban uji asap b menggabungkan
   keduanya.
5. **Brosur dari ketikan ulang**, bukan ekstraksi otomatis; halaman alumni/testimoni, logo mitra,
   foto, dan sampul tidak dimasukkan.
6. **Panduan Kemahasiswaan 2021** adalah dokumen lama (pelengkap) dengan banyak kata terpotong
   hasil ekstraksi.
