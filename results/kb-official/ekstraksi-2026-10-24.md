# Cek ekstraksi PDF KB resmi, 24 Okt 2026 (Langkah 62)

Parser: `mica.kb.parsers.PdfParser` versi Langkah 62 (pypdf 6.20.1), dipanggil per halaman dengan
cara yang sama seperti build `official-2026-10-24-v2`:

1. `extract_text()` biasa memberi urutan teks;
2. `extract_text(extraction_mode="layout")` hanya dipakai sebagai bukti posisi untuk menghapus
   spasi palsu di tengah kata (lihat "Kata terpotong");
3. spasi berlebih dan spasi di akhir baris dirapikan menjadi satu spasi;
4. nomor halaman cetak (baris berisi angka/romawi kecil saja di baris pertama atau terakhir
   halaman) dibuang;
5. kata yang terpenggal tanda hubung di akhir baris disambung bila terbukti (kata ulang, atau
   bentuknya ada di dokumen yang sama);
6. heading "BAB <romawi>", "Pasal <angka>", "<angka>.<angka> Judul" memulai bagian baru.

"hlm" = urutan halaman di file PDF, mulai 1 (bukan nomor cetak; nomor cetak = hlm PDF dikurangi 4
di Pedoman PMB, dikurangi 3 di Peraturan Akademik, dikurangi 6 di Panduan Kemahasiswaan). Nomor
inilah yang disimpan di `Chunk.page_start`/`page_end` dan dipakai di sitasi.
Isi dokumen tidak disunting; PDF tetap byte-identik dengan file di `D:\SKRIPSI\kb-resmi-masuk\`.
Laporan sebelumnya: `ekstraksi-2026-10-23.md` (Langkah 61, parser lama).

## Jumlah karakter per halaman (sesudah perbaikan)

Selisih dengan Langkah 61 hanya spasi (spasi ganda, spasi akhir baris, spasi palsu) dan nomor
halaman cetak; tidak ada teks isi yang dibuang.

### akademik/peraturan-akademik-2025.pdf (38 halaman, total 106848 karakter; sebelum perbaikan 108766)

| hlm | karakter | hlm | karakter | hlm | karakter | hlm | karakter |
|---|---|---|---|---|---|---|---|
| 1 | 32 | 2 | 5687 | 3 | 3851 | 4 | 2333 |
| 5 | 3052 | 6 | 3310 | 7 | 3719 | 8 | 2709 |
| 9 | 2653 | 10 | 2889 | 11 | 2899 | 12 | 2883 |
| 13 | 2758 | 14 | 2752 | 15 | 3544 | 16 | 3137 |
| 17 | 3068 | 18 | 3004 | 19 | 3021 | 20 | 2960 |
| 21 | 2355 | 22 | 2616 | 23 | 3042 | 24 | 2467 |
| 25 | 3014 | 26 | 2719 | 27 | 2857 | 28 | 2697 |
| 29 | 2542 | 30 | 2066 | 31 | 3234 | 32 | 2549 |
| 33 | 2592 | 34 | 2686 | 35 | 2610 | 36 | 2097 |
| 37 | 2472 | 38 | 1972 |  |  |  |  |

Bagian terdeteksi: 60 (+ 1 blok sebelum heading pertama)

### kemahasiswaan/panduan-kemahasiswaan-2021.pdf (47 halaman, total 87750 karakter; sebelum perbaikan 89849)

| hlm | karakter | hlm | karakter | hlm | karakter | hlm | karakter |
|---|---|---|---|---|---|---|---|
| 1 | 76 | 2 | 1756 | 3 | 2272 | 4 | 5134 |
| 5 | 5446 | 6 | 263 | 7 | 2405 | 8 | 1926 |
| 9 | 1594 | 10 | 2518 | 11 | 490 | 12 | 2012 |
| 13 | 673 | 14 | 1408 | 15 | 2150 | 16 | 2140 |
| 17 | 1897 | 18 | 1862 | 19 | 2046 | 20 | 1188 |
| 21 | 1936 | 22 | 2497 | 23 | 2129 | 24 | 2061 |
| 25 | 1545 | 26 | 1732 | 27 | 1555 | 28 | 600 |
| 29 | 1456 | 30 | 2334 | 31 | 1863 | 32 | 2380 |
| 33 | 2175 | 34 | 1995 | 35 | 738 | 36 | 2251 |
| 37 | 1903 | 38 | 697 | 39 | 1854 | 40 | 2153 |
| 41 | 2650 | 42 | 2082 | 43 | 1396 | 44 | 1866 |
| 45 | 1859 | 46 | 1738 | 47 | 1049 |  |  |

Bagian terdeteksi: 12 (+ 1 blok sebelum heading pertama)

### pmb/pedoman-pmb-2027.pdf (13 halaman, total 22943 karakter; sebelum perbaikan 24105)

| hlm | karakter | hlm | karakter | hlm | karakter | hlm | karakter |
|---|---|---|---|---|---|---|---|
| 1 | 84 | 2 | 2432 | 3 | 1687 | 4 | 2435 |
| 5 | 2713 | 6 | 3185 | 7 | 1244 | 8 | 1990 |
| 9 | 2163 | 10 | 609 | 11 | 2474 | 12 | 1500 |
| 13 | 427 |  |  |  |  |  |  |

Bagian terdeteksi: 13 (+ 1 blok sebelum heading pertama)

## Kata terpotong

### Penyebab

Dicek pada content stream PDF (Panduan Kemahasiswaan hlm 16, "semester d alam"):

```
BT /F3 12 Tf 1 0 0 1 224.57 580.42 Tm [(M) -4 (ik) 5 ... (se) 9 (mest) -6 (er) 7 ( ) -83 (d)] TJ ET
BT /F3 12 Tf 1 0 0 1 388.99 580.42 Tm [(alam) 7 ( ) -83 (Pr) 6 (oga) -2 (m)] TJ ET
```

Satu baris rata kanan-kiri ditulis sebagai beberapa objek teks dengan posisi mutlak (`Tm`), dan
batasnya bisa jatuh di tengah kata. `extract_text()` biasa tidak menambahkan geseran angka di dalam
`TJ` ke lebar teks (pypdf `_page.py`, cabang `TJ`), sehingga di objek berikutnya ia mengira ada
celah selebar jumlah geseran dan menyisipkan spasi. Mode layout menghitung posisi huruf termasuk
geseran itu dan menghasilkan "dalam". Penyebab ini direproduksi dengan PDF sintetis di
`tests/unit/test_kb_pdf_text.py::test_cause_tj_offsets_insert_space_in_plain_mode` (dengan
geseran: "semester d alam"; tanpa geseran: "semester dalam").

Tanda hubung di akhir baris: 15 baris (Kemahasiswaan 11, Akademik 3, PMB 1). 4 di antaranya
pemenggalan suku kata yang benar-benar memotong kata ("melak-/sanakan", "memper-/dagangkan",
"mem-/prioritaskan", "ekstra-/kurikuler"); sisanya kata ulang atau kata majemuk ("masing-/masing",
"lain-/lain", "perundang-/undangan", "Strata-/2").

### Perbaikan

- Spasi palsu: spasi di teks biasa dihapus hanya bila gabungan potongannya (2-4 potongan) muncul
  utuh sebagai token di teks layout halaman yang sama dan pasangan terpisahnya tidak muncul di
  layout. Spasi yang juga ada di layout dianggap spasi asli.
- Tanda hubung akhir baris (hanya di halaman yang sama): kata ulang atau bentuk bertanda hubung
  yang ada di dokumen disambung dengan tanda hubung tetap; gabungan tanpa tanda hubung yang ada di
  dokumen disambung tanpa tanda hubung; selain itu dibiarkan.

Jumlah temuan detektor L61 (dua token yang gabungannya muncul >= 2 kali di korpus):

| dokumen | sebelum | sesudah |
|---|---|---|
| panduan-kemahasiswaan-2021 | 114 | 9 (1 di antaranya positif palsu: "di bawah") |
| peraturan-akademik-2025 | 12 | 3 |
| pedoman-pmb-2027 | 0 | 0 |

### 10 contoh sebelum dan sesudah

| # | dokumen | hlm | sebelum (`extract_text()` biasa) | sesudah (parser L62) |
|---|---|---|---|---|
| 1 | panduan-kemahasiswaan-2021 | 2 | `27 Agustus 2021 tentang Pengangkatan Rektor Universitas Mikr oskil` | `27 Agustus 2021 tentang Pengangkatan Rektor Universitas Mikroskil` |
| 2 | panduan-kemahasiswaan-2021 | 7 | `mahasiswa baru de ngan berbagai pelatihan dalam pe ngembangan diri ( softskills),` | `mahasiswa baru dengan berbagai pelatihan dalam pengembangan diri (softskills),` |
| 3 | panduan-kemahasiswaan-2021 | 16 | `Tertinggi) di Universitas Mikroskil pada setiap semester d alam Progam Studi masing- ⏎ masing dengan ketentuan sebagai berikut:` | `Tertinggi) di Universitas Mikroskil pada setiap semester dalam Progam Studi masing-masing` |
| 4 | panduan-kemahasiswaan-2021 | 21 | `1. Organisasi Kem ahasiswaan Universitas Mikroskil tidak menginduk pada organisasi` | `1. Organisasi Kemahasiswaan Universitas Mikroskil tidak menginduk pada organisasi` |
| 5 | panduan-kemahasiswaan-2021 | 32 | `memiliki integritas, dimana konsistensi dalam tindakan -tindakan, nilai -nilai, metode- ⏎ metode, ukuran-ukuran, prinsip-prinsip, ekspektasi-ekspektasi dan berbagai hal yang` | `memiliki integritas, dimana konsistensi dalam tindakan-tindakan, nilai-nilai, metode-metode,` |
| 6 | panduan-kemahasiswaan-2021 | 19 | `2. Dalam rangka meningkatkan kemampuan profesionalisme kemahasiswaan melak - ⏎ sanakan pelayanan pengembangan prestasi & karir berupa kegiatan, pelatihan,` | `2. Dalam rangka meningkatkan kemampuan profesionalisme kemahasiswaan melaksanakan` |
| 7 | panduan-kemahasiswaan-2021 | 7 | `9. Mahasiswa adalah peserta didik yang terdaftar dan aktif pada Program Studi masing- ⏎ masing dilingkungan Universitas MIkroskil baik program Pasca Sarjana (S2), Sarjana` | `9. Mahasiswa adalah peserta didik yang terdaftar dan aktif pada Program Studi masing-masing` |
| 8 | peraturan-akademik-2025 | 4 | `Sekolah Tinggi Ilmu Ekonomi Mi kroskil di Kota Medan menjadi Universitas Mikroskil` | `Sekolah Tinggi Ilmu Ekonomi Mikroskil di Kota Medan menjadi Universitas Mikroskil` |
| 9 | peraturan-akademik-2025 | 10 | `(2) RPL sebagaimana dimaksud pada ayat (1) digunakan untuk permohonan pengakuan kre dit` | `(2) RPL sebagaimana dimaksud pada ayat (1) digunakan untuk permohonan pengakuan kredit` |
| 10 | peraturan-akademik-2025 | 29 | `komponen nilai evaluasi pembelajaran. Asesmen terhadap capaian pembelaja ran dapat` | `komponen nilai evaluasi pembelajaran. Asesmen terhadap capaian pembelaja ran dapat` |

Contoh 7: kata ulang "masing-masing" tetap bertanda hubung. Contoh 10 tetap terpotong karena di
mode layout pun ada celah lebar di antara "pembelaja" dan "ran" (posisi asli di PDF).

### Masih terpotong (tidak bisa dibuktikan dari layout)

- panduan-kemahasiswaan-2021: hlm 3 ("terka it", "te rsebut"), 7 ("u ntuk"), 39 ("sa nksi"),
  41 ("ke pentingan", "berk hasiat"), 44 ("selam a"), 45 ("dirugik an").
- peraturan-akademik-2025: hlm 12 ("dimak sud"), 27 ("basi s"), 29 ("pembelaja ran").
- Tanda hubung yang dibiarkan: Kemahasiswaan hlm 12 "sunguh-/sungguh" (salah ketik asli), hlm 36
  "mem-/prioritaskan"; Akademik hlm 14 "(Strata-/2/S-2)", hlm 38 "membeda-/bedakan".
- Detektor hanya menemukan potongan yang gabungannya ada di korpus; potongan lain bisa masih ada.

## Tabel: extract_text() biasa vs mode layout

### pedoman-pmb-2027 hlm 8 (Persyaratan Khusus, awal tabel)

Biasa:

```
Program Studi yang didaftar Persyaratan Khusus
Magister Teknologi Informasi (S-2)
/ Graduate Program of Information
Technology
1. Lulusan sarjana dengan latar belakang
keilmuan:
a. Komputer, teknik, ekonomi, MIPA, atau
b. Lainnya  (pengalaman  kerja  di  bidang  TI
minimal 3 tahun)
2. IPK Sarjana minimal 2.75
3. Skor TOEFL minimal 475 ke atas
Magister Manajemen (S-2) /
Graduate Program of Management
1. Lulusan sarjana (S1)
```

Layout:

```
    Program Studi yang didaftar                               Persyaratan Khusus
 Magister Teknologi Informasi (S-2)           1.  Lulusan     sarjana     dengan      latar   belakang
 / Graduate Program of Information                keilmuan:
 Technology                                        a.  Komputer, teknik, ekonomi, MIPA, atau
                                                   b.  Lainnya  (pengalaman  kerja  di  bidang  TI
                                                       minimal 3 tahun)
                                              2.  IPK Sarjana minimal 2.75
                                              3.  Skor TOEFL minimal 475 ke atas
 Magister      Manajemen         (S-2)     /  1.  Lulusan sarjana (S1)
 Graduate Program of Management               2.  IPK Sarjana minimal 2.75
```

### pedoman-pmb-2027 hlm 9 (lanjutan, program sarjana)

Biasa:

```
Teknik Informatika (S-1) /
Undergraduate Program of
Computer Science
Lulusan SMA/MA/SMK/Paket C seluruh jurusan
Sistem Informasi (S-1) /
Undergraduate Program of
Information System
Lulusan SMA/MA/SMK/Paket C seluruh jurusan
```

Layout:

```
 Teknik      Informatika        (S-1)     /
 Undergraduate           Program         of  Lulusan SMA/MA/SMK/Paket C seluruh jurusan
 Computer Science
 Sistem       Informasi        (S-1)      /
 Undergraduate           Program         of  Lulusan SMA/MA/SMK/Paket C seluruh jurusan
 Information System
```

### peraturan-akademik-2025 hlm 29 (konversi NSM/NMK/NAM)

Biasa:

```
Nilai Skor Mata Kuliah
(NSM)
Nilai Mata Kuliah
(NMK)
Nilai Angka Mutu
(NAM)
85 ≤ NSM ≤ 100 A 4,00
80 ≤ NSM ≤ 84 A- 3,75
75 ≤ NSM ≤ 79 B+ 3,50
```

Layout:

```
                  Nilai Skor Mata Kuliah           Nilai Mata Kuliah           Nilai Angka Mutu
                             (NSM)                        (NMK)                       (NAM)
                       85 ≤ NSM ≤ 100                         A                        4,00
                        80 ≤ NSM ≤ 84                        A-                        3,75
                        75 ≤ NSM ≤ 79                        B+                        3,50
```

### peraturan-akademik-2025 hlm 30 (rumus IPS/IPK, Pasal 39)

Biasa:

```
IPS =
∑(𝐾 𝑁𝐴𝑀)
∑ 𝐾
dimana:
K = Besaran sks mata kuliah
...
IPK =
∑ 𝐾𝑖 𝑁𝐴𝑀𝑖𝑛𝑖=1
∑ 𝐾𝑖𝑛𝑖=1
```

Layout:

```
                                                  IPS = ∑(𝐾 𝑁𝐴𝑀)
                                                                 ∑  𝐾
     dimana:
      K          =    Besaran sks mata kuliah
...
                                                          ∑𝑛     𝐾𝑖 𝑁𝐴𝑀𝑖
                                               IPK =        𝑖=1
                                                              ∑𝑛     𝐾𝑖
                                                                 𝑖=1
```

### Aturan yang dipilih (berlaku untuk semua halaman semua PDF)

**Teks = `extract_text()` biasa di semua halaman; mode layout hanya dipakai sebagai bukti
posisi untuk perbaikan spasi, tidak untuk urutan teks.** Alasan:

- Di tabel dua kolom PMB hlm 8-9, mode layout menaruh potongan sel kiri dan sel kanan di baris
  yang sama ("Undergraduate Program of  Lulusan SMA/..."), sehingga nama prodi bercampur dengan
  persyaratan. Mode biasa menjaga isi satu sel tetap berurutan, dan prodi selalu mendahului
  persyaratannya.
- Di tabel Akademik hlm 29, baris data sama-sama satu baris per nilai di kedua mode setelah spasi
  dirapikan; yang lebih baik di layout hanya judul kolom (2 baris vs 6 baris).
- Rumus hlm 30 tetap tidak terbaca dengan baik di kedua mode.
- Aturan "layout hanya untuk halaman bertabel" butuh deteksi tabel yang belum ada dan akan
  merusak PMB hlm 8-9, satu-satunya tabel yang isinya penting untuk PMB.

Spasi berlebih dirapikan menjadi satu spasi per baris; tidak ada isi tabel yang ditulis ulang.

### Hasil akhir pedoman-pmb-2027 hlm 8 (masuk ke chunker)

```
Program Studi yang didaftar Persyaratan Khusus
Magister Teknologi Informasi (S-2)
/ Graduate Program of Information
Technology
1. Lulusan sarjana dengan latar belakang
keilmuan:
a. Komputer, teknik, ekonomi, MIPA, atau
b. Lainnya (pengalaman kerja di bidang TI
minimal 3 tahun)
2. IPK Sarjana minimal 2.75
3. Skor TOEFL minimal 475 ke atas
Magister Manajemen (S-2) /
```

## Halaman yang masih bermasalah

### Karakter < 200

| dokumen | hlm | karakter | isi | penilaian |
|---|---|---|---|---|
| pedoman-pmb-2027 | 1 | 84 | sampul | wajar, sampul |
| peraturan-akademik-2025 | 1 | 32 | sampul | wajar, sampul |
| panduan-kemahasiswaan-2021 | 1 | 76 | sampul | wajar, sampul |

Tidak ada halaman 0 karakter; tidak ada tanda PDF hasil pindai.

### Tabel dan tata letak

| dokumen | hlm | masalah |
|---|---|---|
| pedoman-pmb-2027 | 8-9 | Tabel Persyaratan Khusus tetap teks biasa (bukan `Block.table`): judul kolom menyatu, baris "Manajemen (S-1) / Undergraduate Program of Management Lulusan SMA/..." menyatu. Bagian 2.1 lebih panjang dari 400 token, jadi terbagi dua chunk (`#11` hlm 8, `#12` hlm 8-9); label "Magister Teknologi Informasi (S-2)" hanya ada di `#11`, sedangkan baris "3. Skor TOEFL minimal 475" ada di awal `#12` sebelum "Magister Manajemen (S-2)". |
| peraturan-akademik-2025 | 29 | Judul 3 kolom NSM/NMK/NAM terpecah jadi 6 baris; baris data utuh. |
| peraturan-akademik-2025 | 30 | Rumus IPS/IPK (Pasal 39) rusak (huruf matematika Unicode). |
| pedoman-pmb-2027 / peraturan-akademik-2025 / panduan-kemahasiswaan-2021 | 2 / 4 / 2 | Halaman SK: nomor butir "Menimbang/Mengingat" terpisah dari teksnya. |
| semua PDF | halaman sebelum heading pertama | Sampul, SK, kata pengantar, daftar isi tidak punya `section`; sitasinya hanya "<judul>, hlm <n>". |

### Kata terpotong

Lihat "Masih terpotong" di atas.

### Salah ketik asli dokumen (bukan ekstraksi, dibiarkan)

"Mikrosil" (PMB hlm 11), "Peningkatatan" (PMB hlm 11), "senin" (PMB hlm 5), "Nila" (PMB hlm 6),
"sunguh-sungguh" (Kemahasiswaan hlm 12), "menrima", "mendatarkan" (Kemahasiswaan).

## Tidak dilakukan

- Isi dokumen tidak disunting; PDF disalin byte-identik.
- Tidak ada OCR, parser PDF lain, atau ekstraksi tabel PDF menjadi `Block.table`.
