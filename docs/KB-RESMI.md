# KB resmi (Langkah 61, 23 Okt 2026; v2 Langkah 62, 24 Okt 2026)

KB aktif sejak Langkah 62: **`official-2026-10-24-v2`** (`source_type: official`), di
`config/dev.yaml` dan `config/kiosk.yaml` (`kb.active_id`). Yang diarsipkan (tidak dihapus dari
`data/kb/`, ID-nya ditulis sebagai komentar di kedua config):

- `official-2026-10-23-v1`: KB resmi pertama (Langkah 61);
- `dev-2026-10-15-v2`: KB dev, dipakai E-01..E-04.

Dokumen sumber dan isi KB tidak di-commit (`.gitignore`: `data/sources/`, `data/kb/*`).

## Sumber

Asal: `D:\SKRIPSI\kb-resmi-masuk\` (dari hasa). PDF dan brosur disalin byte-identik (SHA-256 sama)
ke `data/sources/official/<kelompok>/`; nama file diganti agar `doc_id` terbaca.

| doc_id | judul (sources.yaml) | file asal | valid_from | dasar valid_from |
|---|---|---|---|---|
| `pmb/pedoman-pmb-2027` | Pedoman Penerimaan Mahasiswa Baru Universitas Mikroskil Tahun 2027 | `acd40be8…a0d.pdf` (13 hlm) | 2026-07-27 | Keputusan Rektor No. 697/UM.348/01/KM/2026, "Pada tanggal: 27 Juli 2026" (hlm PDF 2) |
| `akademik/peraturan-akademik-2025` | Peraturan Akademik Universitas Mikroskil Tahun 2025 | `Peraturan Akademik Tahun 2025.pdf` (38 hlm) | 2025-01-22 | Peraturan Rektor No. 052/UM.348/05/AK/2025, "Pada tanggal: 22 Januari 2025" (hlm PDF 38) |
| `kemahasiswaan/panduan-kemahasiswaan-2021` | Buku Panduan Peraturan Kemahasiswaan Universitas Mikroskil 2021 | `Buku Panduan Peraturan Kemahasiswaan Universitas Mikroskil 2021.pdf` (47 hlm) | 2021-09-06 | Keputusan Rektor No. 018/UM.348/01/KM/2021, "Pada tanggal: 06 September 2021" (hlm PDF 2). Dokumen lama, pelengkap. |
| `brosur/brosur-pmb-2025` | Brosur Pendaftaran Universitas Mikroskil 2025 | `brosur-pmb-2025.md` (ketikan ulang, versi 24 Okt 2026) | 2025-01-01 | Tahun dari keterangan hasa; tidak tertulis di brosur. |
| `keuangan/panduan-pembayaran-2026-2027` | Panduan Dasar dan Pembayaran Uang Kuliah T.A. 2026/2027 | `panduan_dasar_dan_pembayaran_uang_kuliah.md` (disunting, lihat di bawah) | 2026-07-01 | Awal T.A. 2026/2027; cicilan pertama 1-10 Juli 2026. |

Ketiga tanggal SK tertulis jelas, jadi aturan "YYYY-01-01, hanya tahun diketahui" tidak dipakai
untuk PDF. Catatan: nomor Peraturan Akademik memuat "/05/" padahal tanggal penetapannya
22 Januari 2025; yang dipakai tanggal tertulis.

### Aturan bila sumber bertentangan

**Bila sumber bertentangan, yang berlaku adalah dokumen resmi terbaru yang masih berlaku. Brosur
hanya dipakai untuk informasi yang tidak ada di Pedoman PMB 2027.**

Aturan ini dijalankan lewat kurasi dokumen, bukan oleh logika sistem. Retriever dan LLM tidak
membandingkan `valid_from`; tanggal berlaku hanya ditampilkan di label prompt dan di layar. Contoh
penerapan: syarat masuk S2 dihapus dari brosur (versi 24 Okt), karena Pedoman PMB 2027 yang
berlaku. Konflik lain yang belum dikurasi:

- Jalur penerimaan: Peraturan Akademik 2025 Pasal 4 (Reguler, Prestasi, UTBK, Beasiswa, RPL,
  Pindahan, Program Pendidikan Khusus) berbeda dengan Pedoman PMB 2027 (antara lain PMDK dan KIP
  Kuliah). Uji asap c Langkah 62 menjawab dari Peraturan Akademik.

### Brosur: kenapa ketikan ulang

Brosur asli ("Brosur Pendaftaran Mikroskil.pdf", 18 halaman) menyimpan sebagian besar teksnya
di dalam gambar (misalnya hlm 4), sehingga parser PDF tanpa OCR (SDD 2.3) tidak mendapat
teksnya. hasa mengetik ulang isinya apa adanya ke Markdown berfrontmatter `title`, dengan
heading per bagian yang menyebut halaman brosur.

Halaman brosur yang tidak dimasukkan:

- alumni/testimoni: hlm 3, 7, 15;
- logo mitra: hlm 10;
- foto, sampul, dan slogan;
- sejak versi 24 Okt 2026: syarat masuk S2 (hlm 4 Magister Teknologi Informasi, hlm 8 Magister
  Manajemen). Brosur 2025 menyebut TOEFL 475 untuk Magister Manajemen, Pedoman PMB 2027 tidak.

Salah ketik yang diperbaiki hasa: hlm 8 "mengingkatkan". Versi 23 Okt juga memperbaiki hlm 4
"terakreditas", yang ikut terhapus bersama syarat S2.

### Dokumen pembayaran (portal MIKA)

`keuangan/panduan-pembayaran-2026-2027.md` adalah salinan halaman informasi umum portal MIKA
(portal akademik mahasiswa), disalin rekan hasa. Isinya berlaku untuk T.A. 2026/2027. Dokumen ini
bukan dokumen dari dospem. Isinya meliputi kontak layanan, prosedur KRS, aturan SKS maksimum,
jadwal cicilan kelas pagi dan sore, cara bayar (Blibli, VA BCA), dan FAQ.

Yang dibuang oleh Claude (Langkah 62); sisanya byte-identik dengan file asal:

- tabel ganda: subbagian "a. Skema ... Kelas Pagi" dan "b. Skema Khusus ... Kelas Sore" di
  "Prosedur Registrasi Akademik", butir 1. Isinya sama baris per baris dengan bagian "Jadwal
  Pembayaran Uang Kuliah T.A. 2026/2027" (dicek dengan skrip; hanya nomor a./b. vs 1./2. dan
  kata "Khusus" yang berbeda). Bagian "Jadwal Pembayaran" dipertahankan. Akibatnya kalimat
  "Tabel berikut ini adalah ..." dan butir "c. Potongan Biaya Kuliah" tidak lagi diikuti/didahului
  a. dan b.;
- nama staf: "(sdr. Nanang)" dan "(sdr. Budi)" di nomor WhatsApp fakultas. Nomor kontak tetap.

SHA-256 file asal `cb6025e4…3db3e`, file di KB `d080b2f4…7b35` (lengkap di tabel build).

## Perubahan v1 -> v2

| | v1 (`official-2026-10-23-v1`) | v2 (`official-2026-10-24-v2`) |
|---|---|---|
| dokumen | 4 | 5 (+ panduan pembayaran) |
| brosur | dengan syarat S2 | tanpa syarat S2 |
| teks PDF | `extract_text()` biasa, semua halaman jadi satu blok | `extract_text()` biasa + perbaikan spasi palsu (bukti mode layout) + sambung tanda hubung akhir baris + buang nomor halaman cetak + spasi dirapikan |
| bagian PDF | tidak ada (`section` "") | heading BAB/Pasal/`<n>.<n>`; `section` = jalur bagian, misalnya "BAB III REGISTRASI, … › 3.1 Registrasi Administrasi" |
| halaman | tidak ada | `Chunk.page_start`, `Chunk.page_end` untuk PDF |
| batas chunk PDF | bebas | tidak melewati batas bagian (seperti heading .md) |
| teks chunk | isi saja | jalur bagian + baris kosong + isi, untuk .md dan PDF (`section_prefix`) |
| sitasi PDF di layar | judul dokumen | "<judul dokumen>, hlm <n>[-<m>], <judul bagian terdekat>" |
| chunk | 143 | 199 |

Chunk per dokumen:

| dokumen | v1 | v2 |
|---|---|---|
| Peraturan Akademik 2025 | 58 | 87 |
| Panduan Kemahasiswaan 2021 | 55 | 57 |
| Brosur 2025 | 15 | 15 |
| Pedoman PMB 2027 | 15 | 21 |
| Panduan pembayaran 2026/2027 | - | 19 |
| **jumlah** | **143** | **199** |

### Nomor halaman

Nomor yang disimpan dan dikutip adalah **nomor halaman PDF**: urutan halaman di file, mulai 1.
Ini bukan nomor yang tercetak di kaki/kepala halaman. Selisihnya: nomor cetak = hlm PDF dikurangi
4 (Pedoman PMB), 3 (Peraturan Akademik), atau 6 (Panduan Kemahasiswaan); halaman depan bernomor
romawi. Contoh: "Pedoman PMB …, hlm 12" adalah halaman bernomor cetak 8. Chunk .md (brosur,
pembayaran) tidak punya halaman (`null`); sitasinya tetap judul dokumen saja.

### Perubahan metode chunking (dievaluasi ulang di E-01 KB resmi)

Chunker tetap `structure_then_fixed`, 400/50 token. Yang berubah:

1. PDF dipotong per bagian. Heading dikenali dengan pola sederhana (`mica.kb.parsers.heading_level`,
   dites): baris <= 100 karakter tanpa titik-titik daftar isi yang persis berbentuk "BAB
   <romawi>", "Pasal <angka>", atau "<angka>.<angka> Judul" (huruf besar di awal judul). Baris
   pendek setelah "BAB"/"Pasal" yang bukan kalimat dianggap judulnya. Jalur bagian = BAB terakhir
   › Pasal/sub-bab terakhir. Baris heading masuk ke `section`, tidak ke teks isi.
2. Teks setiap chunk (.md dan PDF) diawali jalur bagiannya dan satu baris kosong. Token jalur
   bagian terpanjang di dokumen dikurangkan dari anggaran 400 token, jadi chunk tetap <= 400
   token. Ini juga mengubah chunk brosur, walau jumlahnya tetap 15.
3. Akibatnya teks yang di-embed dan diindeks BM25 berbeda dari v1. Hasil E-01..E-04 (KB dev) dan
   uji asap v1 tidak bisa dibandingkan langsung.

`config_hash` v2 sama dengan v1 (`d4ce25f8…3dab`) karena perubahan ini bukan field konfigurasi.
Pembedanya dicatat di `manifest.json`: `chunker.section_prefix: true` dan `pdf_extraction`
(cara ekstraksi + versi pypdf). `make_chunker(..., section_prefix=False)` memberi cara lama untuk
perbandingan di E-01.

### Tabel

- **PDF:** aturan yang dipilih untuk semua halaman semua PDF: urutan teks dari `extract_text()`
  biasa, mode layout hanya sebagai bukti posisi untuk perbaikan spasi. Alasannya, di tabel dua
  kolom Pedoman PMB hlm 8-9, mode layout mencampur potongan sel prodi dan sel persyaratan dalam
  satu baris; di Peraturan Akademik hlm 29 baris datanya sama saja di kedua mode. Perbandingan
  lengkap: `results/kb-official/ekstraksi-2026-10-24.md`. Tabel PDF tetap teks biasa (bukan
  `Block.table`).
- **Markdown:** tabel pipa Markdown sudah dibaca `MdParser` sebagai `Block.table`, dan
  `structure_then_fixed` tidak pernah memotongnya di tengah. Tabel <= anggaran token disimpan utuh
  dalam satu chunk. Tabel yang lebih besar dipecah per kelompok baris, dan setiap kelompok membawa
  baris judul kolom. Jadwal cicilan kelas pagi (12 baris) dan kelas sore (4 baris) masing-masing
  menjadi satu chunk utuh, dengan "Cicilan Ke- | Jadwal" di awal. Dites di
  `tests/unit/test_kb_pdf_text.py::test_installment_table_stays_whole_with_header`. Kekurangan:
  kalimat "Bagi mahasiswa kelas pagi …" ada di chunk teks terpisah, sehingga chunk tabel pagi hanya
  memuat jalur bagian "Jadwal Pembayaran Uang Kuliah T.A. 2026/2027", tanpa kata "pagi".

## Build v2

| | |
|---|---|
| kb_id | `official-2026-10-24-v2` |
| perintah | `python -m mica.kb build --src data/sources/official --kb-id official-2026-10-24-v2 --source-type official --config config/dev.yaml` |
| dokumen / chunk | 5 / 199 (tabel: 4, semuanya dari panduan pembayaran) |
| lama build | 221,3 detik (laptop dev, CPU) |
| ukuran | 1,3 MB |
| chunker | `structure_then_fixed`, `chunk_tokens` 400, `overlap_tokens` 50, `section_prefix` true |
| pdf_extraction | "L62: extract_text + perbaikan spasi (bukti layout) + tanda hubung; heading BAB/Pasal/n.n", pypdf 6.20.1 |
| config_hash | `d4ce25f8c3164a6d696cff92da582706aa34fe38e9de5232883729eff65b3dab` (sama dengan v1) |
| embedder | BAAI/bge-m3 rev `9a0624b896d81da7492a910ffa53731274b6cf3d` (`model.safetensors`), dim 1024 |
| built_at | 2026-10-24T11:23:17+07:00 |

Build pertama v2 hari ini (200 chunk) dihapus sebelum dipakai dan diganti dengan build di atas,
karena nomor halaman cetak masih ikut ke bagian sebelumnya dan rentang halaman melebar satu halaman.

SHA-256 dokumen sumber (dari `manifest.json`):

| doc_id | sha256 |
|---|---|
| `akademik/peraturan-akademik-2025` | `ccc065e4750b3179f90ef46f6d913ebfb7e1c2d530be95e2f08cc3b0da9a3ac7` |
| `brosur/brosur-pmb-2025` | `f9dd8945e0445ea010d1d1e502d7fdf5d584a0e1530a4f58c05150a641ce376f` |
| `kemahasiswaan/panduan-kemahasiswaan-2021` | `68ccca5d7348cdcec0dbd1b3e8aa989424abe84306caffbc67cb41dca7568b52` |
| `keuangan/panduan-pembayaran-2026-2027` | `d080b2f48f25677c799d113921245ac681cb45b2bc39b87469d2cd1bee747b35` |
| `pmb/pedoman-pmb-2027` | `baf0877bb3f01acc416d7d338cdc31c3a79b69c61c5a2c0da1e0aa7db76c89dd` |

SHA-256 file KB:

| file | sha256 |
|---|---|
| `manifest.json` | `73b9100051b439555ff277a67314476832248435d3027b52841ab2b5394a2165` |
| `chunks.jsonl` | `3902fab37f24808e4637680f8369a7f4941281fae278c8fcb6f65cc94e651f53` |
| `dense.npy` | `416ed8c09b39670e9e9fca67226034eeebb2316ef01d45561c2e447478b7a5a8` |
| `bm25.pkl` | `65758851ed1fc036e98519179baf6cdada044bdc5e487cdb62dc45a161b1338a` |

## Build v1 (arsip, Langkah 61)

| | |
|---|---|
| kb_id | `official-2026-10-23-v1` |
| dokumen / chunk | 4 / 143 (tabel: 0) |
| lama build / ukuran | 109,3 detik / 1,1 MB |
| chunker | `structure_then_fixed`, 400/50, tanpa prefiks bagian; PDF tanpa bagian dan halaman |
| config_hash | `d4ce25f8c3164a6d696cff92da582706aa34fe38e9de5232883729eff65b3dab` |
| built_at | 2026-10-23T16:54:35+07:00 |
| brosur sha256 | `b8a4beab6b883bf04c1c9ce00e39a02c6a828d49ab66f416f7dad818ff6a5b07` (versi 23 Okt) |
| `manifest.json` / `chunks.jsonl` | `aa8524b5…85bf` / `85c9ea1b…bac9` |
| `dense.npy` / `bm25.pkl` | `a7b6b82f…a1fa182` / `2c3cf557…4ab84a` |

SHA-256 tiga PDF sama dengan v2. Paket: sentence-transformers 6.1.0, torch 2.14.1+cpu.

## Cek ekstraksi

Rincian v2: `results/kb-official/ekstraksi-2026-10-24.md` (v1: `ekstraksi-2026-10-23.md`).
Ringkasnya:

- Penyebab kata terpotong: penulis PDF memecah baris rata kanan-kiri menjadi beberapa objek teks,
  kadang di tengah kata. `extract_text()` biasa tidak menghitung geseran angka di dalam `TJ`, jadi
  menyisipkan spasi di sambungan. Sesudah perbaikan, temuan detektor turun dari 114 menjadi 9
  (Kemahasiswaan) dan dari 12 menjadi 3 (Akademik).
- Masih bermasalah: tabel Persyaratan Khusus PMB hlm 8-9 (teks biasa, terbagi dua chunk), judul
  kolom Akademik hlm 29, rumus Akademik hlm 30, nomor butir halaman SK, sisa kata terpotong di
  Kemahasiswaan hlm 3, 7, 39, 41, 44, 45 dan Akademik hlm 12, 27, 29.

## Dataset eval lama dan KB resmi

`data/eval/questions.jsonl`, `pool.csv`, dan `dev_topic_switch.jsonl` dibuat dan dianotasi
pada KB dev. Sejak Langkah 61, perintah `python -m mica.eval` yang memuat KB (annotate export,
retrieval, gate, generation, followup, stt) memanggil `mica.eval.kb_match.check_dataset_files`
dan menolak (exit 2) dataset yang:

- tercatat di `pool_meta.json` dengan kb_id lain, atau
- memuat `gold_chunk_ids` atau doc_id `gold_refs` yang tidak ada di KB aktif.

Jadi E-01..E-04 tidak bisa diam-diam dijalankan ulang dengan dataset lama pada KB resmi.
Untuk mereproduksi hasil lama, set `kb.active_id` kembali ke `dev-2026-10-15-v2`.
E-01/E-02 belum dijalankan pada KB resmi (v1 maupun v2).

## Uji asap

Langkah 61: lima pertanyaan (a-e), 4 panggilan LLM. Langkah 62: a-e yang sama ditambah f, 6
panggilan LLM, lewat `python -m mica.ask`. Hanya cek fungsi, bukan evaluasi. Pertanyaan ini tidak
boleh dipakai sebagai set uji. Hasil di `RINGKASAN.md` (tidak di-commit).

## Penyimpangan yang harus diungkap di Bab 3

1. **KB dev diarsipkan.** E-01..E-04 diukur pada `dev-2026-10-15-v2` (dokumen dev, bukan
   dokumen resmi). KB aktif sekarang `official-2026-10-24-v2`; hasil E-01..E-04 belum diukur
   ulang pada KB resmi.
2. **Ambang gerbang 0,50 adalah nilai coba.** Dikalibrasi di KB dev, belum diukur ulang di KB
   resmi (`rag.gate.threshold` di `config/dev.yaml`; di `config/kiosk.yaml` tetap null/TBD).
   Skor pertanyaan di luar KB (uji asap e, gelombang 2) berubah dari 0,487 (v1, ditolak gerbang)
   menjadi 0,529 (v2, lolos gerbang, lalu ditolak LLM). Selisih kecil ini menunjukkan ambang
   harus dikalibrasi ulang pada KB yang final.
3. **Chunking memakai nilai awal dev** (`chunk_tokens` 400, `overlap_tokens` 50), belum
   dikalibrasi untuk dokumen resmi.
4. **Metode chunking berubah di v2** (bagian PDF, prefiks jalur bagian di teks chunk untuk .md
   dan PDF, perbaikan teks PDF). Perubahan dibuat setelah melihat hasil ekstraksi dokumen resmi,
   belum diuji di E-01. `config_hash` tidak berubah, jadi pembeda v1/v2 adalah kb_id dan
   `manifest.json`.
5. **Model data `Chunk` ditambah** `page_start` dan `page_end` (tidak ada di SDD 5.1), dan sitasi
   PDF di layar memuat halaman dan bagian. Field `section` PDF berisi jalur bagian (BAB › Pasal),
   bukan satu judul.
6. **Teks PDF diolah sebelum chunking**: spasi palsu dihapus berdasarkan bukti mode layout, kata
   bertanda hubung di akhir baris disambung bila terbukti dari dokumen, nomor halaman cetak
   dibuang, spasi dirapikan. Isi tidak ditulis ulang. Sebagian kata terpotong masih ada (lihat
   laporan ekstraksi).
7. **Tabel PDF tetap teks biasa.** Tabel Persyaratan Khusus Pedoman PMB terbagi dua chunk; label
   prodi Magister Teknologi Informasi dan baris TOEFL-nya ada di chunk yang berbeda.
8. **Biaya kuliah berasal dari brosur tahun 2025** (tahun dari keterangan hasa, tidak tertulis
   di brosur). Pedoman PMB 2027 hanya menyatakan uang kuliah ditetapkan Rektor setiap tahun, tanpa
   angka. Syarat S2 di brosur dihapus sejak v2, sesuai aturan dokumen resmi terbaru.
9. **Brosur dari ketikan ulang**, bukan ekstraksi otomatis; halaman alumni/testimoni, logo mitra,
   foto, sampul, dan (sejak v2) syarat S2 tidak dimasukkan.
10. **Dokumen pembayaran bukan dokumen dari dospem**: salinan halaman informasi umum portal MIKA
    oleh rekan hasa, T.A. 2026/2027. Claude membuang tabel jadwal cicilan ganda dan dua nama staf.
    Judul di `sources.yaml` dibuat dari nama file dan tahun akademik.
11. **Aturan "dokumen resmi terbaru yang berlaku" dijalankan lewat kurasi, bukan oleh sistem.**
    Konflik jalur penerimaan (Peraturan Akademik 2025 vs Pedoman PMB 2027) belum dikurasi.
12. **Panduan Kemahasiswaan 2021** adalah dokumen lama (pelengkap); sebagian kata terpotong masih
    ada setelah perbaikan.
