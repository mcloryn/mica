# KB resmi (Langkah 61, 23 Okt 2026; v2 Langkah 62, v3 Langkah 63, v4 Langkah 64, 24 Okt 2026)

KB aktif sejak Langkah 64: **`official-2026-10-24-v4`** (`source_type: official`), di
`config/dev.yaml` dan `config/kiosk.yaml` (`kb.active_id`), bersama prompt **v5**
(`rag.prompt_variant: v5`). Yang diarsipkan (tidak dihapus dari `data/kb/`, ID-nya ditulis
sebagai komentar di kedua config):

- `official-2026-10-24-v3`: KB resmi v3 (Langkah 63);
- `official-2026-10-24-v2`: KB resmi v2 (Langkah 62);
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
| `keuangan/panduan-pembayaran-2026-2027` | Panduan Dasar dan Pembayaran Uang Kuliah T.A. 2026/2027 (frontmatter `title` file) | `panduan-pembayaran-2026-2027.md` (versi Langkah 63, byte-identik) | 2026-07-01 | Awal T.A. 2026/2027; cicilan pertama 1-10 Juli 2026. |

Selain itu ada `_overrides/pedoman-pmb-2027-hlm8-9.md` (byte-identik), yaitu halaman pengganti
Pedoman PMB, bukan dokumen tersendiri (lihat "Halaman pengganti").

Ketiga tanggal SK tertulis jelas, jadi aturan "YYYY-01-01, hanya tahun diketahui" tidak dipakai
untuk PDF. Catatan: nomor Peraturan Akademik memuat "/05/" padahal tanggal penetapannya
22 Januari 2025; yang dipakai tanggal tertulis.

### Aturan bila sumber bertentangan

**Bila sumber bertentangan, yang berlaku adalah dokumen resmi terbaru yang masih berlaku. Brosur
hanya dipakai untuk informasi yang tidak ada di Pedoman PMB 2027.**

Langkah 62: aturan ini hanya dijalankan lewat kurasi dokumen (syarat S2 dihapus dari brosur).
Sejak Langkah 63 aturan ini juga diatur di sistem (pilihan hasa), lewat prompt **v5**:

- Setiap potongan di pesan ke LLM diberi kepala
  `[ID: <chunk_id> | Dokumen: <judul> | Kelompok: <subfolder> | Berlaku sejak: <valid_from>]`.
  Kelompok = subfolder teratas `doc_id` (pmb, akademik, kemahasiswaan, brosur, keuangan).
- Aturan prompt baru (aturan 4 v5): bila potongan dari dokumen berbeda saling bertentangan,
  (1) untuk pertanyaan tentang pendaftaran mahasiswa baru utamakan dokumen kelompok
  `rag.source_priority`; (2) selain itu utamakan dokumen dengan tanggal berlaku terbaru;
  (3) jangan menggabungkan isi yang saling bertentangan; (4) sebutkan di jawaban dokumen yang
  dipakai.
- `rag.source_priority: [pmb]` di `config/dev.yaml` dan `config/kiosk.yaml`. Ini nilai
  rancangan, bukan hasil kalibrasi. Bila daftarnya kosong, butir (1) tidak ditulis.
- Retriever, gerbang 1-3, dan cek sitasi/angka tidak diubah. Sitasi tetap berupa enum
  `allowed_chunk_ids`, dan ID tetap ada di awal kepala potongan. Cek angka tetap memakai teks
  chunk + `source_label` (judul dan tanggal berlaku), sama seperti sebelumnya.

Aturan di prompt tidak menjamin LLM mematuhinya: pada uji asap c Langkah 63, jawaban tetap
mencampur jalur dari kedua dokumen (lihat "Uji asap"). Karena itu, sejak Langkah 64 konflik yang
sudah diketahui ditangani sebelum retrieval (kurasi dokumen atau `superseded_sections`); aturan
prompt v5 tinggal menjadi jaring untuk konflik yang belum diketahui.

### Konflik sumber yang diketahui

| topik | sumber A | sumber B | yang berlaku | cara penanganan | catatan |
|---|---|---|---|---|---|
| TOEFL untuk Magister Manajemen | Brosur 2025 hlm 8: "Skor TOEFL minimal 475 ke atas" | Pedoman PMB 2027 hlm 8-9, 2.1 c: tidak ada TOEFL untuk MM (TOEFL hanya untuk MTI) | Pedoman PMB 2027 | **kurasi ketikan brosur**: syarat S2 tidak diketik di brosur | sejak Langkah 62; aturan prompt v5 tetap aktif |
| Jalur penerimaan mahasiswa baru | Peraturan Akademik 2025 Pasal 4 (hlm 9-10): Reguler, Prestasi, UTBK, Beasiswa, RPL, Pindahan, Program Pendidikan Khusus (7 jalur) | Pedoman PMB 2027 1.2 Jalur Seleksi (hlm 5-6): PMDK, Prestasi, Reguler, KIP Kuliah, Ujian Saring Masuk S2 (5 jalur) | Pedoman PMB 2027 (kelompok pmb, pendaftaran) | **`superseded_sections`**: Pasal 4 tidak masuk indeks | sejak v4 (Langkah 64). v3 dengan prompt v5 saja masih mencampur (uji asap c L63); v4 tidak (uji asap c L64). PDF tidak disunting. |
| konflik yang belum diketahui | - | - | dokumen resmi terbaru (kelompok `rag.source_priority` untuk pendaftaran) | **aturan prompt v5** (aturan 4) | kepatuhan LLM tidak dijamin; konflik baru yang ditemukan dipindah ke salah satu cara di atas |

### Prompt v5

| | lama | baru |
|---|---|---|
| varian aktif (`rag.prompt_variant`) | `paraphrase` (prompt_version `v2`) | `v5` (prompt_version `v5`) |
| aturan sistem | 10 aturan v2 | 10 aturan v2 dengan urutan sama + 2 aturan baru sesudah aturan sumber: penjelasan kepala potongan (3) dan aturan konflik sumber (4) |
| label potongan | `[ID: … \| Sumber: <judul> \| Berlaku: <tanggal>]` | `[ID: … \| Dokumen: <judul> \| Kelompok: <subfolder> \| Berlaku sejak: <tanggal>]` |
| skema keluaran | status, answer, citations | sama |

Varian lama tetap ada dan tidak berubah (`paraphrase`, `plain`, `v3`, `v4`; label potongan lama),
sehingga arsip E-02/E-04 tetap bisa direproduksi dengan `--prompt-variant paraphrase` atau dengan
`rag.prompt_variant: paraphrase` (komentar arsip di kedua config). Prompt v5 belum dievaluasi di
E-02/E-04.

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

SHA-256 file asal `cb6025e4…3db3e`, file di KB v2 `d080b2f4…7b35` (lengkap di tabel build).

Sejak Langkah 63 (v3), file ini diganti versi baru dari `D:\SKRIPSI\kb-resmi-masuk\`
(byte-identik, SHA-256 `5004e98e…74ebcb`). Versi ini berfrontmatter `title` dan memuat catatan
kurasinya sendiri. Bedanya dengan versi v2:

- yang dipertahankan adalah tabel cicilan di "Prosedur Registrasi Akademik", sedangkan bagian
  "Jadwal Pembayaran Uang Kuliah T.A. 2026/2027" yang dihapus (kebalikan dari v2);
- sub-judul tebal a/b/c (skema kelas pagi, skema kelas sore, potongan) dijadikan heading, sehingga
  chunk tabel cicilan pagi kini berjalur bagian "a. Skema Pembayaran Biaya Kuliah Mahasiswa Kelas
  Pagi (Cicilan 12 kali)";
- ada paragraf "Sumber: … Kurasi: …" di bawah judul. Paragraf ini ikut masuk KB sebagai satu chunk
  (seperti catatan di brosur).

Judul di `sources.yaml` diambil dari frontmatter `title` file itu. Isinya sama dengan judul
v2.

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
  Diperbaiki di v3: sub-judul skema kini heading (lihat "Dokumen pembayaran").

## Perubahan v2 -> v3

| | v2 (`official-2026-10-24-v2`) | v3 (`official-2026-10-24-v3`) |
|---|---|---|
| Pedoman PMB hlm 8-9 | teks pypdf; tabel Persyaratan Khusus terbelah 2 chunk | halaman pengganti (ketikan ulang), 6 chunk per sub-bagian |
| panduan pembayaran | versi Langkah 62 (sub-judul skema hanya teks tebal) | versi Langkah 63 (sub-judul skema jadi heading, frontmatter title) |
| `MdParser` | komentar HTML ikut masuk | komentar HTML `<!-- -->` dibuang |
| prompt aktif | `paraphrase` (v2) | `v5` (aturan konflik sumber) |
| chunk | 199 | 203 |

| dokumen | v2 | v3 |
|---|---|---|
| Peraturan Akademik 2025 | 87 | 87 |
| Panduan Kemahasiswaan 2021 | 57 | 57 |
| Brosur 2025 | 15 | 15 |
| Pedoman PMB 2027 | 21 | 23 |
| Panduan pembayaran 2026/2027 | 19 | 21 |
| **jumlah** | **199** | **203** |

### Halaman pengganti (page override)

**Alasan.** Di v2, tabel "Persyaratan Khusus" Pedoman PMB hlm 8-9 dibaca pypdf sebagai teks dua
kolom yang berantakan, dan bagian 2.1 terbelah menjadi dua chunk. Label "Magister Teknologi
Informasi (S-2)" ada di chunk pertama, sedangkan baris "Skor TOEFL minimal 475" ada di awal chunk
kedua, tepat sebelum "Magister Manajemen (S-2)". Ini berisiko membuat TOEFL dikira syarat MM.

**Cara kerja** (`mica.kb.parsers`, tes `tests/unit/test_kb_overrides.py`):

- Di `sources.yaml`, entri PDF boleh punya
  `page_overrides: {"8-9": "_overrides/pedoman-pmb-2027-hlm8-9.md"}` (rentang "n" atau "n-m",
  path relatif terhadap folder sumber, hanya file .md). Rentang di luar jumlah halaman, tumpang
  tindih, file yang tidak ada, atau page_overrides pada non-PDF ditolak (`KB_INVALID`).
- Saat parse, halaman itu tidak dibaca dari PDF. Isinya diganti isi .md (tanpa frontmatter dan
  tanpa komentar HTML). Heading .md bertingkat menjadi jalur bagian, misalnya "BAB II Sistem
  Rekrutmen dan Seleksi Calon Mahasiswa Baru › 2.1 Sistem Rekrutmen › c. Persyaratan Khusus per
  Program Studi yang didaftar". Tabel .md tetap `Block.table`.
- Chunk tetap milik dokumen PDF (doc_id, judul, valid_from, kelompok sama) dengan
  `page_start`/`page_end` = 8/9 untuk semua chunk dari halaman pengganti. Halaman per baris di
  dalam rentang tidak diketahui, jadi sitasinya selalu "hlm 8-9".
- Jalur bagian berlanjut ke halaman PDF sesudahnya. Hlm 10 menjadi bagian "BAB II Sistem
  Rekrutmen dan Seleksi Calon Mahasiswa Baru › 2.4 Sistem Pengambilan Keputusan", lalu hlm 11
  mulai "BAB III …" dari heading PDF.
- Folder `_overrides` dilewati `iter_source_files`, sehingga init-sources, check-sources, dan
  build tidak meng-ingest-nya sebagai dokumen.
- `manifest.json` mencatat path dan SHA-256 setiap halaman pengganti di entri dokumennya.

**Isi file.** Ketikan ulang hlm PDF 8-9 (nomor cetak 4-5) oleh Claude dari `pdftotext -layout`,
dengan catatan di komentar HTML. Teks disalin apa adanya; hanya tata letak tabel yang diubah
menjadi satu daftar per program studi. **Satu tambahan kata oleh Claude:** "Magister Manajemen"
pada baris "Untuk kelas Eksekutif Magister Manajemen, persyaratan tambahan:", karena di PDF baris
itu berada di sel Magister Manajemen. Akibat lain: judul BAB II di jalur bagian hlm 8-10 ditulis
"BAB II Sistem Rekrutmen dan Seleksi Calon Mahasiswa Baru" (huruf kapital biasa), sedangkan judul
BAB lain dari PDF berhuruf besar semua.

## Perubahan v3 -> v4

Satu-satunya perubahan: `superseded_sections` di `sources.yaml` (Peraturan Akademik 2025,
"Pasal 4"). File sumber, chunker, embedder, dan prompt v5 sama dengan v3. Ambang gerbang tidak
diubah.

| dokumen | v3 | v4 |
|---|---|---|
| Peraturan Akademik 2025 | 87 | 85 |
| Panduan Kemahasiswaan 2021 | 57 | 57 |
| Brosur 2025 | 15 | 15 |
| Pedoman PMB 2027 | 23 | 23 |
| Panduan pembayaran 2026/2027 | 21 | 21 |
| **jumlah** | **203** | **201** |

Chunk yang dikeluarkan (dicatat di `manifest.json`):

| chunk_id | hlm | jalur bagian |
|---|---|---|
| `akademik/peraturan-akademik-2025#14` | 9 | BAB II PENYELENGGARAAN PENERIMAAN MAHASISWA BARU › Pasal 4 Jalur Penerimaan Mahasiswa Baru |
| `akademik/peraturan-akademik-2025#15` | 10 | BAB II PENYELENGGARAAN PENERIMAAN MAHASISWA BARU › Pasal 4 Jalur Penerimaan Mahasiswa Baru |

chunk_id lain sama dengan v3 (nomor #14 dan #15 kosong, tidak dinomori ulang). Pasal 5
Rekognisi Pembelajaran Lampau (#16-#18) dan Pasal 40/41 (#64-#66) tetap ada. Ikut hilang: ayat
(6) Pasal 4 yang menjelaskan jalur RPL sebagai jalur penerimaan; pengertian RPL tetap ada di
Pasal 1 dan Pasal 5.

### Bagian yang digantikan dokumen lain (superseded_sections)

**Alasan.** Aturan konflik di prompt v5 tidak mencegah LLM mencampur jalur Peraturan Akademik
Pasal 4 dengan jalur Pedoman PMB 2027 (uji asap c L63). PDF resmi tidak boleh disunting, jadi
bagian yang sudah digantikan dikeluarkan dari indeks saat build.

**Cara kerja** (`mica.kb.parsers.section_matches`, `mica.kb.index.drop_superseded`, tes
`tests/unit/test_kb_superseded.py`):

- Entri dokumen apa pun di `sources.yaml` boleh punya
  `superseded_sections: [{section, superseded_by, reason}]`. Ketiga field wajib diisi; section
  ganda dalam satu dokumen ditolak (`KB_INVALID`).
- Saat build, chunk yang jalur bagiannya (`Chunk.section`) memuat bagian itu tidak dimasukkan ke
  `chunks.jsonl`, `dense.npy`, maupun `bm25.pkl`.
- Pencocokan per bagian jalur (dipisah " › "): bagian cocok bila sama persis, atau diawali
  section + spasi **dan** section berakhir dengan nomor ("4", "1.2", "II"). Jadi "Pasal 4" cocok
  dengan "Pasal 4 Jalur Penerimaan Mahasiswa Baru", tetapi tidak dengan "Pasal 40 …", "Pasal
  41 …", atau "Pasal 5 …"; "Pasal" tanpa nomor tidak mencocokkan semua pasal. Huruf besar/kecil
  dibedakan. section boleh berupa jalur ("BAB II › Pasal 4"); bagian-bagiannya harus berurutan
  di jalur chunk.
- Bila satu section tidak cocok dengan chunk mana pun, build gagal (`KB_INVALID`, pesan menyebut
  doc_id dan section) dan tidak ada folder KB yang dibuat.
- `manifest.json`: `n_superseded_chunks` di tingkat atas, dan di entri dokumen
  `superseded_sections: [{section, superseded_by, reason, n_chunks, chunk_ids}]`. build.log hanya
  mencatat jumlahnya (isi dokumen tidak ditulis ke log).
- `sources.yaml` tidak di-commit (`data/sources/`); isi entri Langkah 64:

```yaml
akademik/peraturan-akademik-2025.pdf:
  superseded_sections:
    - section: "Pasal 4"
      superseded_by: "Pedoman Penerimaan Mahasiswa Baru Tahun 2027, 1.2 Jalur Seleksi"
      reason: "jalur seleksi untuk calon mahasiswa 2027 diatur Pedoman PMB 2027; isi berbeda (7 vs 5 jalur)"
```

## Build v4

| | |
|---|---|
| kb_id | `official-2026-10-24-v4` |
| perintah | `python -m mica.kb build --src data/sources/official --kb-id official-2026-10-24-v4 --source-type official --config config/dev.yaml` |
| dokumen / chunk | 5 / 201 (tabel: 4), 2 chunk dikeluarkan (`superseded_sections`) |
| lama build / ukuran | 224,5 detik / 1,3 MB |
| chunker | sama dengan v3 |
| config_hash | `d4ce25f8c3164a6d696cff92da582706aa34fe38e9de5232883729eff65b3dab` (sama dengan v1-v3) |
| built_at | 2026-10-24T19:58:41+07:00 |

SHA-256 file sumber sama dengan v3. `sources.yaml`:
`1b7db24f280441e0d4fa03d643b60c1c85395da0804871122321f4c66e502fd2`.

SHA-256 file KB:

| file | sha256 |
|---|---|
| `manifest.json` | `712bced2459074074da154247c50f4281d0baed3963af9c6d4d048e01f2f425d` |
| `chunks.jsonl` | `1adb22a2b7e365b895fd2490b953c6fffd301a0f38b26c0c94d07a4fc65dc973` |
| `dense.npy` | `116a098798a07c183f35a6dac45f99ceef0331f33150af8f9c91e55cbbc5ea25` |
| `bm25.pkl` | `a558a1f8a619c1509e6dce580dafb84e7e19583375704e168e4e9a0d7324452a` |

## Build v3 (arsip, Langkah 63)

| | |
|---|---|
| kb_id | `official-2026-10-24-v3` |
| perintah | `python -m mica.kb build --src data/sources/official --kb-id official-2026-10-24-v3 --source-type official --config config/dev.yaml` |
| dokumen / chunk | 5 / 203 (tabel: 4, semuanya dari panduan pembayaran) |
| lama build / ukuran | 218,1 detik / 1,3 MB |
| chunker | sama dengan v2 (`structure_then_fixed`, 400/50, `section_prefix` true) |
| config_hash | `d4ce25f8c3164a6d696cff92da582706aa34fe38e9de5232883729eff65b3dab` (sama dengan v1/v2; `rag.*` tidak masuk hash KB) |
| built_at | 2026-10-24T12:05:34+07:00 |

SHA-256 sumber yang berubah dari v2 (lainnya sama):

| file | sha256 |
|---|---|
| `keuangan/panduan-pembayaran-2026-2027.md` | `5004e98e021d15a2ccc29352205255fd2d65cfb981c0ca9779f97615e274ebcb` |
| `_overrides/pedoman-pmb-2027-hlm8-9.md` (page_overrides Pedoman PMB "8-9") | `362a1fa14b6729047a25891cf760db605a22446af25a9ca7f5d200bbe3e693e6` |

SHA-256 file KB:

| file | sha256 |
|---|---|
| `manifest.json` | `6474d03b046ed8fda0e2cc3c644e22e0da2dfbad22e04ec9fb25d57c699975f4` |
| `chunks.jsonl` | `0c392f4ef80dd905deec5faaf72b25693f401f65d1d28d44eeffab8b0f47dd9e` |
| `dense.npy` | `619d4ba77626fcb3bf9b605fe313f0eb58af65623749ab455d6f5116778da899` |
| `bm25.pkl` | `9699ccc2dd9255a6eefc9f2836920e6b0194b4e5f2d8de89f5f41023e7aa5fce` |

## Build v2 (arsip, Langkah 62)

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
- Masih bermasalah (v2): tabel Persyaratan Khusus PMB hlm 8-9 (teks biasa, terbagi dua chunk;
  diganti halaman pengganti di v3), judul
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
E-01/E-02 belum dijalankan pada KB resmi (v1-v4).

## Uji asap

Langkah 61: lima pertanyaan (a-e), 4 panggilan LLM. Langkah 62: a-e yang sama ditambah f, 6
panggilan LLM. Langkah 63 (v3 + prompt v5): a-f ditambah g (syarat MTI) dan h (cicilan kelas
pagi), 8 panggilan LLM. Semuanya lewat `python -m mica.ask`. Hanya cek fungsi, bukan evaluasi.
Pertanyaan ini tidak boleh dipakai sebagai set uji. Hasil lengkap di `RINGKASAN.md` (tidak
di-commit).

Pemeriksaan khusus Langkah 63:

- b: TOEFL tidak disebut untuk MM (lolos).
- g: TOEFL 475 untuk MTI (lolos), dari chunk halaman pengganti.
- h: 12 kali (lolos).
- **c: gagal.** Jalur dari Pedoman PMB 2027 1.2 dan Peraturan Akademik 2025 Pasal 4 ikut terambil,
  dan jawabannya mencampur keduanya, padahal aturan konflik v5 aktif.

Langkah 64 (v4 + prompt v5): c, b, g, i, 4 panggilan LLM.

- c: 5 jalur Pedoman PMB 2027 (PMDK, Prestasi, Reguler, KIP Kuliah, Ujian Saring Masuk S2),
  sumber hanya Pedoman PMB 2027 hlm 5 dan 6, 1.2 Jalur Seleksi (lolos).
- b: tanpa TOEFL (lolos). g: TOEFL 475 (lolos).
- i: terjawab, tetapi sumbernya Pasal 1 Istilah dan Pengertian (hlm 6-7), bukan Pasal 5. Pasal 5
  tetap ada di indeks.

## Penyimpangan yang harus diungkap di Bab 3

1. **KB dev diarsipkan.** E-01..E-04 diukur pada `dev-2026-10-15-v2` (dokumen dev, bukan
   dokumen resmi). KB aktif sekarang `official-2026-10-24-v4`; hasil E-01..E-04 belum diukur
   ulang pada KB resmi.
2. **Ambang gerbang 0,50 adalah nilai coba.** Dikalibrasi di KB dev, belum diukur ulang di KB
   resmi (`rag.gate.threshold` di `config/dev.yaml`; di `config/kiosk.yaml` tetap null/TBD).
   Skor pertanyaan di luar KB (uji asap e, gelombang 2) berubah dari 0,487 (v1, ditolak gerbang)
   menjadi 0,529 (v2 dan v3, lolos gerbang, lalu ditolak LLM). Selisih kecil ini menunjukkan
   ambang harus dikalibrasi ulang pada KB yang final.
3. **Chunking memakai nilai awal dev** (`chunk_tokens` 400, `overlap_tokens` 50), belum
   dikalibrasi untuk dokumen resmi.
4. **Metode chunking berubah di v2** (bagian PDF, prefiks jalur bagian di teks chunk untuk .md
   dan PDF, perbaikan teks PDF). Perubahan dibuat setelah melihat hasil ekstraksi dokumen resmi,
   belum diuji di E-01. `config_hash` tidak berubah, jadi pembeda v1-v4 adalah kb_id dan
   `manifest.json`.
5. **Model data `Chunk` ditambah** `page_start` dan `page_end` (tidak ada di SDD 5.1), dan sitasi
   PDF di layar memuat halaman dan bagian. Field `section` PDF berisi jalur bagian (BAB › Pasal),
   bukan satu judul.
6. **Teks PDF diolah sebelum chunking**: spasi palsu dihapus berdasarkan bukti mode layout, kata
   bertanda hubung di akhir baris disambung bila terbukti dari dokumen, nomor halaman cetak
   dibuang, spasi dirapikan. Isi tidak ditulis ulang. Sebagian kata terpotong masih ada (lihat
   laporan ekstraksi).
7. **Halaman PDF diganti ketikan ulang (v3).** Pedoman PMB hlm 8-9 tidak diambil dari PDF,
   tetapi dari ketikan ulang Claude (`pdftotext -layout`). Tata letak tabel diubah menjadi daftar
   per prodi, dan satu tambahan kata ("Magister Manajemen" pada baris kelas Eksekutif). Semua chunk
   dari halaman itu bersitasi "hlm 8-9" tanpa halaman per baris. Tabel PDF lain (Akademik hlm 29,
   rumus hlm 30) tetap teks pypdf.
8. **Aturan konflik sumber diatur di prompt v5** (pilihan hasa). `rag.source_priority: [pmb]`
   adalah nilai rancangan, bukan hasil kalibrasi. Kepatuhan LLM tidak dijamin: uji asap c
   Langkah 63 masih mencampur jalur dari dua dokumen. Prompt v5 belum dievaluasi di E-02/E-04.
   Prompt v2 tetap ada untuk arsip E-02/E-04.
9. **Biaya kuliah berasal dari brosur tahun 2025** (tahun dari keterangan hasa, tidak tertulis
   di brosur). Pedoman PMB 2027 hanya menyatakan uang kuliah ditetapkan Rektor setiap tahun, tanpa
   angka. Syarat S2 di brosur dihapus sejak v2, sesuai aturan dokumen resmi terbaru.
10. **Brosur dari ketikan ulang**, bukan ekstraksi otomatis; halaman alumni/testimoni, logo
    mitra, foto, sampul, dan (sejak v2) syarat S2 tidak dimasukkan.
11. **Dokumen pembayaran bukan dokumen dari dospem**: salinan halaman informasi umum portal MIKA
    oleh rekan hasa, T.A. 2026/2027. v2: Claude membuang tabel cicilan ganda dan dua nama staf.
    v3: versi kurasi baru dari hasa (bagian yang dihapus berbeda dari v2, sub-judul skema dijadikan
    heading); judul dari frontmatter file.
12. **Komentar HTML di Markdown dibuang** oleh `MdParser` sejak v3 (catatan penyunting, bukan isi).
    Brosur dan panduan pembayaran saat ini tidak memuat komentar HTML.
13. **Panduan Kemahasiswaan 2021** adalah dokumen lama (pelengkap); sebagian kata terpotong masih
    ada setelah perbaikan.
14. **Bagian dokumen resmi dikeluarkan dari indeks (v4).** Peraturan Akademik 2025 Pasal 4
    (2 chunk, hlm 9-10) tidak masuk KB lewat `superseded_sections`, karena jalur seleksi 2027
    diatur Pedoman PMB 2027. Keputusan ini kurasi manual berdasarkan aturan konflik sumber, bukan
    hasil evaluasi. Ayat (6) Pasal 4 tentang jalur RPL ikut hilang dari KB.
