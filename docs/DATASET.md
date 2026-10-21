# Set evaluasi resmi: pembagian, kunci, dan anotasi (pra-registrasi)

Ditetapkan 18 Oktober 2026, sebelum ada satu pun pertanyaan resmi. Aturan di bawah tidak diubah
setelah data resmi datang; penyimpangan wajib ditulis di hasil dan diungkap di Bab 3.

## Sumber

- Set resmi: pertanyaan nyata calon mahasiswa dan staf PMB, beserta dokumen resmi dari
  pembimbing (MS5).
- Set dev lama (`data/eval/questions.jsonl`, d001-d045) tetap menjadi set dev pengembangan.
  Set ini tidak digabung dengan set resmi dan tidak ikut dibagi.
- Format baris sama dengan SDD 6.3 (`mica.eval.dataset.validate_questions`): `qid`, `question`,
  `type`, `oos_level` (khusus `out_of_kb`), `prev_qid` (khusus `followup`), `gold_refs`, dan
  field lain.

## Pembagian (K-5)

- Pertanyaan resmi dibagi 30% dev-resmi dan 70% uji.
- Seed pembagian: `20261018`
- Acak berstrata. Satu unit = satu pertanyaan beserta semua `followup` yang merujuknya lewat
  `prev_qid` (berantai), sehingga followup tidak pernah terpisah dari pertanyaan sebelumnya.
  Strata unit:
  - `followup` bila unit memuat pertanyaan `followup`;
  - selain itu `type` pertanyaan akarnya, dan untuk `out_of_kb` ditambah `oos_level`
    (`out_of_kb:jauh`, `out_of_kb:dekat`).
- Per strata dengan n unit: jumlah unit dev-resmi = 30% dari n, dibulatkan setengah ke atas
  (`(3n + 5) // 10`); sisanya uji. Akibatnya strata berisi 1 unit selalu masuk uji.
- Prosedur acak: unit diurutkan menurut `qid` asli akarnya, strata diproses urut nama, satu
  `random.Random(seed)` dipakai untuk mengocok unit setiap strata, lalu unit pertama sejumlah
  kuota dev menjadi dev-resmi.
- ID baru `o-dev-NNN` dan `o-test-NNN` diberikan berurutan menurut urutan file asli. `prev_qid`
  disesuaikan, dan `qid` asli disimpan di `source_qid`.
- Perintah (dijalankan satu kali saat data resmi datang; menolak berjalan bila hasilnya sudah
  ada):

  ```
  python -m mica.eval dataset split --input <file resmi> --out-dir data/eval/official/
  ```

  Seed dibaca dari dokumen ini, bukan dari argumen.

## Kunci set uji

- Setelah dibagi, set uji langsung dikunci:

  ```
  python -m mica.eval dataset lock --dataset data/eval/official/test.jsonl --reason "<alasan>"
  ```

- `data/eval/LOCK` (JSON) menyimpan riwayat versi. Setiap versi memuat SHA-256 file set uji,
  jumlah per `type` dan per strata, seed, tanggal, commit, status `git_dirty`, dan alasan.
- Set uji yang sudah dikunci hanya boleh diubah lewat versi kunci baru dengan alasan tertulis.
  Semua versi tetap tercatat; versi berlaku adalah versi terakhir. Setiap versi baru adalah
  penyimpangan yang diungkap di Bab 3.
- `python -m mica.eval dataset status` mencetak versi kunci dan apakah hash file cocok.
- Semua perintah eval menerima `--split dev|test` (bawaan `dev`).
  - `test` hanya jalan bila LOCK ada dan hash dataset sama dengan versi berlaku, serta KB aktif
    ber-`source_type` `official`. run.json mencatat versi dan hash LOCK.
  - `dev` menolak dataset yang hash-nya tercatat di LOCK, supaya set uji tidak terpakai diam-diam
    sebagai dev.

## Anotasi set uji

- Dua penilai independen: hasa dan seorang rekan. Kesepakatan dilaporkan dengan Cohen's kappa.
- Penilai tidak melihat saran AI untuk set uji. Ini berbeda dari set dev, tempat saran AI
  terlihat; hal itu dicatat sebagai keterbatasan set dev.

## Larangan bocor

- Pertanyaan set uji tidak boleh muncul di `ui.suggestions`, di prompt (`rag/prompts.py`), atau
  di dokumen KB.
- `python -m mica check` membandingkan setiap pertanyaan set uji (`data/eval/official/test.jsonl`)
  dan set dev (`data/eval/questions.jsonl`, `data/eval/official/dev.jsonl`) dengan semua teks
  yang bisa dikirim UI tanpa diketik: `ui.suggestions`, label `ui.topics`, dan `ui.topics[].question`
  (Langkah 53). Teks dinormalisasi dulu (huruf kecil, tanpa tanda baca, spasi dirapikan). Hasilnya
  GAGAL bila ada yang identik atau bila Jaccard token >= 0,5 (`LEAK_TOKEN_JACCARD`, nilai pengaman
  pengembang, bukan hasil eksperimen).
- Pertanyaan chip `ui.topics[].question` saat ini buatan pengembang (sementara). Nanti diganti
  pertanyaan nyata staf PMB, dan penggantinya harus lolos cek yang sama.

## Item untuk pembimbing

- Isi `data/eval/official/` (dev.jsonl dan test.jsonl) rencananya di-commit, supaya hash di
  LOCK bisa diverifikasi siapa pun dari repo. Bila pembimbing melarang (misalnya karena
  pertanyaan nyata dianggap data sensitif), file tidak di-commit. Hash di LOCK tetap di-commit,
  dan keputusan ini ditulis di Bab 3.
- Persetujuan pemakaian pertanyaan nyata calon mahasiswa dan staf PMB.
