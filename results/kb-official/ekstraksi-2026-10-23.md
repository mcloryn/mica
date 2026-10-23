# Cek ekstraksi PDF KB resmi, 23 Okt 2026 (Langkah 61)

Parser: `mica.kb.parsers.PdfParser` = `pypdf.PdfReader(path).pages[i].extract_text()` (pypdf 6.20.1),
dipanggil per halaman sebelum build. Build menggabungkan semua halaman menjadi satu blok teks
(section ""), jadi yang terlihat di sini adalah yang masuk ke chunker.
"hlm" = urutan halaman di file PDF (bukan nomor cetak; nomor cetak = hlm PDF dikurangi 4 di
Pedoman PMB, dikurangi 3 di Peraturan Akademik, dikurangi 6 di Panduan Kemahasiswaan).
Isi dokumen tidak diperbaiki; laporan ini hanya untuk dibandingkan hasa dengan PDF.

## Jumlah karakter per halaman

### akademik/peraturan-akademik-2025.pdf (38 halaman, total 108766 karakter)

| hlm | karakter | hlm | karakter | hlm | karakter | hlm | karakter |
|---|---|---|---|---|---|---|---|
| 1 | 35 | 2 | 5750 | 3 | 3892 | 4 | 2423 |
| 5 | 3105 | 6 | 3360 | 7 | 3773 | 8 | 2757 |
| 9 | 2706 | 10 | 2942 | 11 | 2946 | 12 | 2928 |
| 13 | 2806 | 14 | 2799 | 15 | 3596 | 16 | 3188 |
| 17 | 3118 | 18 | 3057 | 19 | 3071 | 20 | 3009 |
| 21 | 2400 | 22 | 2665 | 23 | 3095 | 24 | 2513 |
| 25 | 3066 | 26 | 2770 | 27 | 2910 | 28 | 2748 |
| 29 | 2598 | 30 | 2115 | 31 | 3287 | 32 | 2599 |
| 33 | 2643 | 34 | 2738 | 35 | 2664 | 36 | 2143 |
| 37 | 2524 | 38 | 2027 |  |  |  |  |

### kemahasiswaan/panduan-kemahasiswaan-2021.pdf (47 halaman, total 89849 karakter)

| hlm | karakter | hlm | karakter | hlm | karakter | hlm | karakter |
|---|---|---|---|---|---|---|---|
| 1 | 82 | 2 | 1846 | 3 | 2322 | 4 | 5175 |
| 5 | 5491 | 6 | 268 | 7 | 2427 | 8 | 1979 |
| 9 | 1643 | 10 | 2582 | 11 | 535 | 12 | 2066 |
| 13 | 720 | 14 | 1457 | 15 | 2199 | 16 | 2196 |
| 17 | 1952 | 18 | 1911 | 19 | 2103 | 20 | 1235 |
| 21 | 1996 | 22 | 2559 | 23 | 2182 | 24 | 2115 |
| 25 | 1595 | 26 | 1783 | 27 | 1605 | 28 | 646 |
| 29 | 1505 | 30 | 2388 | 31 | 1918 | 32 | 2445 |
| 33 | 2226 | 34 | 2043 | 35 | 784 | 36 | 2312 |
| 37 | 1958 | 38 | 745 | 39 | 1906 | 40 | 2203 |
| 41 | 2662 | 42 | 2105 | 43 | 1404 | 44 | 1896 |
| 45 | 1867 | 46 | 1749 | 47 | 1063 |  |  |

### pmb/pedoman-pmb-2027.pdf (13 halaman, total 24105 karakter)

| hlm | karakter | hlm | karakter | hlm | karakter | hlm | karakter |
|---|---|---|---|---|---|---|---|
| 1 | 97 | 2 | 2656 | 3 | 1791 | 4 | 2472 |
| 5 | 2825 | 6 | 3349 | 7 | 1337 | 8 | 2063 |
| 9 | 2234 | 10 | 627 | 11 | 2614 | 12 | 1579 |
| 13 | 461 |  |  |  |  |  |  |

## Halaman mencurigakan

### Karakter < 200

| dokumen | hlm | karakter | isi | penilaian |
|---|---|---|---|---|
| pedoman-pmb-2027 | 1 | 97 | sampul (judul, "Bagian Admisi dan Pemasaran Terpadu") | wajar, sampul |
| peraturan-akademik-2025 | 1 | 35 | sampul ("PERATURAN AKADEMIK TAHUN 2025") | wajar, sampul |
| panduan-kemahasiswaan-2021 | 1 | 82 | sampul | wajar, sampul |

Tidak ada halaman 0 karakter; tidak ada tanda PDF hasil pindai.
Halaman pendek lain (200-800 karakter: PMB 10, 13; Kemahasiswaan 6, 11, 13, 28, 35, 38) sudah dibaca:
akhir bab/daftar isi, teks lengkap, bukan kehilangan teks.

### Tabel tercampur/berantakan

| dokumen | hlm | masalah |
|---|---|---|
| pedoman-pmb-2027 | 8-9 | Tabel "Persyaratan Khusus" per program studi menjadi teks biasa: sel kolom 1 (prodi) dan kolom 2 (persyaratan) bergantian per baris, batas sel hilang. Judul kolom menyatu ("Program Studi yang didaftar Persyaratan Khusus"). Baris Manajemen (S-1) menyatu dalam satu baris dengan persyaratannya. Tabel terpotong pergantian halaman (S-2 di hlm 8, S-1 di hlm 9). Urutan isi tetap benar. |
| peraturan-akademik-2025 | 29 | Tabel konversi NSM -> NMK -> NAM: judul 3 kolom terpecah jadi 6 baris; baris data utuh satu baris per nilai (mis. "85 ≤ NSM ≤ 100 A 4,00"). Terbaca, tetapi tanpa pemisah kolom. |
| peraturan-akademik-2025 | 30 | Rumus IPS/IPK (Pasal 39) rusak: huruf matematika Unicode dan indeks menyatu ("∑ 𝐾𝑖 𝑁𝐴𝑀𝑖𝑛𝑖=1"). Penjelasan kata di bawah rumus utuh. |
| pedoman-pmb-2027 | 2 | Halaman SK: label "Menimbang : a. b." dan "Mengingat : 1. ... 7." terpisah dari isinya (tata letak dua kolom); nomor butir tidak menempel ke teks butirnya. Juga di Peraturan Akademik hlm 4 dan Panduan Kemahasiswaan hlm 2. |

Tabel di dokumen ini tidak dikenali parser PDF sebagai `Block.table`; seluruh PDF menjadi blok teks
(`is_table` = false di chunk PDF).

### Kata terpotong (spasi di tengah kata)

Dideteksi otomatis: dua token berurutan yang bila digabung menjadi kata yang muncul >= 2 kali di
korpus. Bisa ada positif palsu (mis. "olah raga").

- **panduan-kemahasiswaan-2021: hampir semua halaman isi** (hlm 2, 3, 7-12, 14-33, 36-47), 1-6 kata
  per halaman. Contoh: "Mikr oskil" (2), "dal am", "terka it", "te rsebut", "s egala" (3),
  "K emahasiswaan", "de ngan", "pe ngembangan" (7), "Peng embangan" (9), "progra m" (18),
  "Kem ahasiswaan" (21), "mer upakan", "sen jata" (42), "a pakah", "ter nyata" (46).
  Juga spasi sebelum tanda hubung: "dasar -dasar", "masing -masing", "terus -menerus".
  Dugaan: PDF ini dibuat dengan perataan kanan-kiri yang menyimpan jarak huruf sebagai spasi.
  Dampak: BM25 tidak mencocokkan kata yang terpotong; dense kemungkinan lebih tahan.
- **peraturan-akademik-2025: 1-2 kata di hlm 4, 5, 8, 10, 12, 13, 15, 17, 27, 29, 31, 33**
  ("Mi kroskil", "akhl ak", "u ndangan", "kre dit", "dimak sud", "lang sung", "pembel ajaran",
  "mengi kuti", "basi s", "peny usunan", "pembelaja ran", "peng unduran", "menem puh", "se bagai").
- **pedoman-pmb-2027: tidak terdeteksi.**
  Salah ketik asli dokumen (bukan ekstraksi) terlihat, mis. "Mikrosil" (hlm 11), "Peningkatatan" (hlm 11),
  "senin" (hlm 5), "Nila" (hlm 6); dibiarkan.

## Contoh hasil ekstraksi tabel (10 baris pertama)

### pedoman-pmb-2027 hlm 8 (nomor cetak 4), 2.1 c. Persyaratan Khusus

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
```

### pedoman-pmb-2027 hlm 9 (nomor cetak 5), lanjutan tabel

```
Teknik Informatika (S-1) / 
Undergraduate Program of 
Computer Science 
Lulusan SMA/MA/SMK/Paket C seluruh jurusan 
Sistem Informasi (S-1) / 
Undergraduate Program of 
Information System 
Lulusan SMA/MA/SMK/Paket C seluruh jurusan 
Teknologi Informasi (S-1) / 
Undergraduate Program of 
```

### peraturan-akademik-2025 hlm 29 (nomor cetak 26), Pasal 38 ayat (12)

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
70 ≤ NSM ≤ 74 B 3,00 
```

Panduan Kemahasiswaan 2021: tidak ditemukan tabel dalam teks hasil ekstraksi (daftar bernomor saja).

## Tidak dilakukan

- Isi dokumen tidak disunting; PDF disalin byte-identik (SHA-256 sama dengan file di
  `D:\SKRIPSI\kb-resmi-masuk\`).
- Tidak ada OCR atau parser PDF lain.
