Ditetapkan 3 November 2026, sebelum dataset publik diunduh atau dibuka.

# Amandemen kedua pra-registrasi E-05, E-07, E-08, E-09: sumber data (3 November 2026)

Keputusan pemilik proyek, 3 November 2026:

- E-05 dan E-08 memakai dataset publik.
- E-07 dan E-09 diukur sendiri oleh pengembang (pilot satu orang).
- E-08 tetap dijalankan. PROD-6 dibatalkan.

Saat amandemen ini ditetapkan, folder `D:\SKRIPSI\data-publik\` belum ada. Belum ada data
relawan maupun data publik yang diunduh atau dibuka. Config, kode, dan docs/SDD.md tidak diubah
oleh amandemen ini.

## A. Alasan dan cakupan

- Tidak ada relawan, sehingga sumber data E-05, E-07, E-08, dan E-09 diganti.
- Grid, metrik, dan aturan pilih dari docs/AMANDEMEN-2026-11-03.md (termasuk koreksinya) dan dari
  protokol docs/E-0x.md tetap berlaku, kecuali yang disebut di bawah.
- Aturan privasi dan penghapusan yang ada tetap berlaku untuk rekaman pengembang sendiri.

## B. E-05 (suara)

**Ucapan**

- Sumber: Mozilla Common Voice Scripted Speech 24.0, Indonesian (CC0-1.0).
- Ketentuan unduhan melarang hosting ulang dan identifikasi penutur. Karena itu file audio
  **tidak di-commit** dan disimpan di `D:\SKRIPSI\data-publik\`. Penutur tidak diidentifikasi.
- Hanya klip yang tervalidasi yang dipakai.
- Diambil **300 klip**, maksimal **1 klip per penutur**, diacak dengan **seed 20261103**.
- Daftar ID klip yang terambil di-commit (ID saja, tanpa audio).

**Bising**

- Sumber: korpus MUSAN (Snyder dkk. 2015, OpenSLR 17), subset `noise`.
- Diambil **100 klip**, diacak dengan **seed 20261103**, lalu dipotong menjadi **10 detik**.
- Mengikuti file LICENSE di setiap subfolder. Audio tidak di-commit.

**Diam**

- **20 rekaman** diam, masing-masing **10 detik**, dari mikrofon laptop pengembang.

**Status untuk metrik amandemen 3 November bagian A**

- "Ucapan asli" = klip Common Voice. Klip ini mengisi peran rekaman `pertanyaan`, misalnya
  untuk hitungan "pertanyaan asli tersaring" dan jumlah rekaman yang terpotong
  `max_utterance_s`.
- "Bukan ucapan" = MUSAN noise + diam. Rekaman ini mengisi peran `bising` dan `diam` untuk
  hitungan transkripsi palsu.

**Keterbatasan yang diungkap**

- Kalimat dibacakan, bukan pertanyaan PMB.
- Mikrofon dan ruang rekam berbeda dari laptop PMB.

## C. E-08 (warna baju)

**Data**

- Sumber: PETA (Deng dkk., ACM MM 2014), lisensi akademik.
- Subset i-LIDS dikeluarkan.
- Gambar tidak di-commit.

**Label kebenaran**

- Dipakai atribut warna badan atas PETA. Ada 11 warna, sama dengan 11 nama warna van de Weijer di
  MICA (`COLOR_NAMES`).
- Hanya gambar yang punya **tepat satu** warna badan atas yang dipakai.

**Sampel**

- Paling banyak **60 gambar per warna**, diacak dengan **seed 20261103**. Warna yang gambarnya
  lebih sedikit dipakai semua.
- Sampel dibagi dua dengan seed yang sama:
  - **TUNING**: untuk tahap 1 (region × metode), sweep area baju (tahap 2a/2b), dan
    `min_majority` (tahap 3), sesuai amandemen 3 November bagian C dan docs/E-08.md.
  - **LAPORAN**: untuk akurasi akhir dengan nilai pemenang. Akurasi yang dilaporkan di Bab 4
    **hanya** dari separuh ini.

**Aturan tambahan**

- Gambar yang orangnya tidak terdeteksi YOLO dihitung **gagal** (tidak dibuang). Jumlahnya
  dilaporkan terpisah.
- Aturan "2 penilai" (kappa) dipenuhi oleh label publik PETA.

**Keterbatasan:** gambar PETA adalah gambar CCTV beresolusi rendah dengan sudut pandang beragam,
bukan kamera C270 di meja PMB.

## D. E-07 (kehadiran): pilot pengembang sendiri

- **`vision.presence_signal`** tetap `shoulder_width` (amandemen 3 November, keputusan 3).
- **`vision.min_shoulder_ratio`**: diganti dari grid {0,18; 0,22; 0,26} menjadi kalibrasi
  langsung.
  - Pengembang berdiri menghadap depan kamera C270 pada jarak **1,2 m**, yaitu batas bawah fase
    dekat jarak sosial (Hall, 1966).
  - Rasio lebar bahu direkam selama **10 detik**, sebanyak **3 kali**.
  - Nilai ambang = **median ketiga rekaman**.
  - Orang yang lebih dekat menghasilkan rasio lebih besar dan dianggap hadir.
- **`vision.dwell_s`, `vision.leave_s`, `session.regreet_cooldown_s`**:
  - Klip skenario E-07 bagian 2 direkam oleh pengembang sendiri.
  - Grid dan aturan pilih protokol E-07 bagian 2 tetap berlaku untuk ketiga kunci ini, dengan
    `min_shoulder_ratio` ditetapkan dari kalibrasi di atas.
  - `min_kp_conf` diambil dari pemenang E-08 (amandemen 3 November).
- **`vision.conf`**: tetap nilai provisional sekarang. Nilai ini tidak diukur, karena
  pengukurannya butuh frame berlabel dari kamera itu.
- **Keterbatasan:** hanya satu tubuh dan satu orang. Variasi ukuran badan dan perilaku pengunjung
  tidak terwakili.

## E. E-09 (beban laptop)

- Protokol E-09 (termasuk grid amandemen 3 November bagian D) dijalankan pengembang sendiri
  dengan suaranya sendiri.
- Bila dijalankan di laptop dev, statusnya **indikatif** sampai diulang di laptop PMB.

## Catatan 3 November 2026 (sebelum unduh dibuka)

1. Halaman Common Voice 24.0 tidak tersedia lagi. Sebagai gantinya dipakai **Common Voice
   Scripted Speech 27.0 - Indonesian** (CC0-1.0, 1,43 GB, mozilladatacollective.com). Aturan
   sampel bagian B tidak berubah.
2. Bila penutur tervalidasi kurang dari 300, semua penutur diambil, tetap 1 klip per penutur.
   Jumlah akhir dilaporkan.
3. E-08 tidak memakai jumlah minimum gambar per warna. Akurasi dilaporkan per warna, lengkap
   dengan n dan interval Wilson 95%, ditambah akurasi keseluruhan. Warna dengan n < 10 di separuh
   LAPORAN ditandai "data tidak cukup untuk disimpulkan".

## Catatan kedua 3 November 2026 (sebelum data)

1. MUSAN diambil dari salinan Hugging Face `FluidInference/musan` (repo dataset), dengan revisi
   commit yang dikunci: `3edcfdf89b56dbe6a395ff29f9c29489e03d1321` (terakhir diubah 2 Agustus 2025;
   dibaca lewat API metadata saat alat dibuat). Tarball OpenSLR 11 GB tidak dipakai.
   - Prosedur: daftar nama file folder `noise/` dibaca lebih dulu (metadata), lalu 100 file `.wav`
     diacak dengan seed 20261103, dan hanya file itu yang diunduh.
   - File LICENSE setiap subfolder (`noise/free-sound/LICENSE`, `noise/sound-bible/LICENSE`)
     disimpan bersama hasil.
   - Menurut metadata itu, salinan Hugging Face memuat 774 file `.wav` di `noise/` (730
     `free-sound`, 47 `sound-bible`, termasuk file bukan audio pada hitungan per folder). Jumlah
     dari makalah MUSAN tidak dipakai sebagai acuan.
2. E-08 melaporkan dua angka akurasi di separuh LAPORAN:
   - semua gambar, dengan orang yang tidak terdeteksi dihitung gagal;
   - hanya gambar yang orangnya terdeteksi.

   Karena PETA berupa potongan CCTV beresolusi rendah, akurasinya ditafsirkan sebagai batas bawah
   untuk kamera MICA.

## Catatan ketiga 3 November 2026 (sebelum data)

Pembagian TUNING/LAPORAN PETA dilakukan per orang (ID orang per subset), bukan per gambar, supaya
orang yang sama tidak muncul di kedua bagian. Batas 60 per warna tetap dihitung per gambar.

## Catatan keempat 3 November 2026 (sebelum hasil)

Ditulis sebelum eval E-05 maupun E-08 dijalankan. Belum ada akurasi, WER, atau hasil sweep yang
dilihat.

1. **PETA, subset CUHK.** Di `Label.txt` CUHK, ID ditulis sebagai nama file lengkap (misalnya
   `0606.png`, satu gambar per orang). Subset lain memakai ID orang tanpa ekstensi. Pembaca
   `prep-peta` versi awal tidak mencocokkan pola ini, sehingga 4563 gambar CUHK terbuang sebagai
   "tanpa label". Akibatnya populasi sampel tidak sesuai bagian C, yang hanya mengeluarkan
   i-LIDS.
   - Pembaca diperbaiki: ID berupa nama file lengkap kini ikut cocok.
   - Aturan sampel (seed, batas 60 per warna, split per orang) tidak berubah.
2. **Sampel pertama sempat dibuat dengan bug ini.** Sampel itu (folder keluaran dan
   `sample.csv`) dihapus sebelum eval apa pun dijalankan, lalu `prep-peta` dijalankan ulang
   dengan seed yang sama.
3. **MUSAN.** 57 dari 100 klip MUSAN terpilih aslinya lebih pendek dari 10 detik. Klip itu
   dipakai dengan panjang aslinya, tanpa ditambah diam. Daftarnya tercatat di `musan.json`
   (`shorter_than_clip_s`).

## Catatan kelima 3 November 2026 (hitung ulang diagnostik, tanpa perubahan setelan)

Ditulis sebelum hitung ulang dijalankan.

- **Alasan.** Run LAPORAN E-08 pertama (`results/E-08-publik/color-laporan-20261103-145225`) hanya
  menyimpan jumlah per warna, tanpa tebakan per gambar dan tanpa confusion matrix. Alat diubah
  supaya laporan juga menyimpan `per_item.csv` dan `confusion.csv`.
- **Hitung ulang.** LAPORAN dijalankan sekali lagi dengan run tuning yang sama
  (`color-tuning-20261103-145151`), data yang sama, model yang sama, dan tanpa perubahan setelan
  apa pun.
- **Syarat.** Angka per warna, jumlah terdeteksi, jumlah benar, dan hitungan min_majority run
  kedua harus identik dengan run pertama. Bila ada yang berbeda, proses berhenti dan perbedaannya
  dilaporkan.
- **Status.** Run pertama tetap menjadi angka resmi Bab 4. Run kedua hanya dipakai untuk
  diagnosis: confusion matrix dan tebakan per gambar.
