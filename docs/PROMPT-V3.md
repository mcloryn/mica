# Prompt v3: pra-registrasi (20 Oktober 2026)

Ditulis 20 Oktober 2026, **sebelum** eval apa pun dijalankan dengan prompt v3. Aturan keputusan
di bawah tidak boleh diubah setelah data v3 ada. Setiap penyimpangan wajib diungkap di Bab 3.

## Alasan

Masukan pengguna: jawaban prompt v2 terlalu kaku dan kurang interaktif. Tujuan MICA adalah
asisten yang interaktif tetapi tidak sok tahu. v3 mencoba membuat nada lebih ramah dan
menawarkan topik lanjutan tanpa melonggarkan kesetiaan pada dokumen.

## Perubahan v3 terhadap v2

v3 dipilih dengan `rag.prompt_variant: v3` (`--prompt-variant v3` di `eval generation`) dan
tercatat sebagai `prompt_version: v3`. Teks v2 (`paraphrase`, `plain`) tidak berubah. Teks
prompt, badan request, dan kunci cache v2 dikunci dengan hash di `tests/unit/test_prompt_v3.py`.

1. Nada (aturan baru): ramah seperti staf PMB berbicara dengan calon mahasiswa, menyapa dengan
   "kamu", tanpa emoji, tanpa salam atau basa-basi pembuka.
2. Parafrase (mengganti aturan parafrase v2): jelaskan dengan kalimat sendiri, jangan menyalin
   kalimat potongan apa adanya, **kecuali** nama, angka, tanggal, nominal, dan istilah resmi.
   Kalimat "Sebutkan tanggal berlaku untuk biaya dan jadwal" tetap ada.
3. Bentuk (mengganti aturan "kalimat biasa, tanpa markdown, tabel, atau daftar berpoin, maksimal
   120 kata"): mulai dengan jawaban inti satu kalimat. Daftar 3 item atau lebih ditulis satu item
   per baris dengan awalan `- `. Selain itu tetap kalimat biasa tanpa markdown atau tabel,
   ringkas (hanya yang ditanya dan yang langsung relevan), maksimal 120 kata.
4. Topik lanjutan (aturan baru): field JSON `follow_up_topic` = satu label `ui.topics` (6 topik:
   Program Studi, Biaya, Beasiswa, Pendaftaran, Fasilitas, Lokasi) yang wajar ditanyakan
   berikutnya, bukan topik pertanyaan itu sendiri, atau `null`.
5. Aturan lain v2 tidak berubah dan teksnya sama persis: jawab hanya dari potongan, jawab hanya
   yang ditanyakan, pelurusan premis palsu, tolak injeksi, tidak menghitung angka baru, sitasi
   hanya dari ID potongan yang diizinkan, data bukan instruksi, teks penolakan baku.

Lapisan tampilan dan suara (bukan bagian prompt):

- UI: baris `- ` dirender sebagai daftar poin oleh formatter tampilan (`answer_format.py`/`.js`).
  Bila `follow_up_topic` tidak null, di bawah jawaban muncul kalimat tetap dari
  `mica.core.texts.FOLLOW_UP_OFFER` ("Mau tahu soal <topik> juga?") dan tombol topik. Tombol itu
  berperilaku sama dengan chip topik: mengisi kotak pertanyaan, bukan langsung mengirim
  (keputusan pengguna 20 Okt 2026).
- TTS: baris `- A`, `- B`, `- C` dibacakan "A, B, dan C." (`mica.core.spoken.spoken_answer`).
  Kalimat tawaran dibacakan setelah jawaban. Teks layar dan riwayat tidak memuat tawaran. Jawaban
  tanpa baris `- ` dibacakan persis seperti teksnya.

## Deviasi dari SDD (disetujui pengguna 20 Okt 2026)

SDD tidak diubah dalam langkah ini. Bila v3 dipakai, SDD perlu diperbarui pengguna.

- SDD 5.3, skema keluaran `{status, answer, citations}`: v3 menambah `follow_up_topic`
  (enum label `ui.topics` atau null). Groq strict: `anyOf` string-enum atau null, field wajib
  (dokumentasi Groq Structured Outputs, dicek 20 Okt 2026: union dengan `null` untuk nilai
  opsional, semua field `required`). Gemini: `format: enum` + `nullable: true` (referensi API
  `Schema`, dicek 20 Okt 2026). v2 tidak mengirim field ini dan masih menolak keluaran yang
  memuatnya.
- SDD 2.4 (aturan prompt "kalimat biasa tanpa markdown karena dibacakan"): v3 mengizinkan baris
  `- ` untuk daftar 3 item atau lebih. Masalah dibacakan ditangani normalisasi TTS.

## Aturan keputusan

Data: 45 pertanyaan set dev yang sama dengan run v2 (dataset sha256 `9dc9c399...627a`, KB
`dev-2026-10-15-v2`), retriever hybrid, top_k 5, gerbang off (ambang null), cek angka menyala,
reasoning_effort low, temperature 0,2. Status dinilai seperti `scripts/compare_models.py`.

Model utama 120b. Pembanding v2: `results/E-02/20261017-122758-E-02-dev-hybrid-gpt-oss-120b-gateoff`.
v3 dipakai sebagai prompt utama **hanya bila semua** syarat ini terpenuhi dibanding v2:

1. salah tolak (answerable/followup yang tidak `answered`) tidak lebih banyak;
2. tolak benar (out_of_kb yang `refused_*`) tidak lebih sedikit;
3. premis palsu yang diluruskan (false_premise berstatus `false_premise`, "terbaik") tidak lebih
   sedikit;
4. jawaban berhalusinasi (anotasi manusia; definisi SDD 2.4: klaim tidak didukung potongan yang
   dikutip) tidak lebih banyak;
5. JSON gagal (`LLM_BAD_OUTPUT`) tidak lebih banyak.

20b (pembanding v2: `results/E-04/20261016-220121-E-04-dev-hybrid-gpt-oss-20b-gateoff`)
dilaporkan dengan aturan yang sama sebagai pendamping, tetapi tidak menentukan keputusan.

Bila satu saja syarat 120b gagal, prompt tetap v2 + formatter tampilan (commit 35fa9d7). Sampai
anotasi halusinasi v3 selesai, keputusan berstatus "menunggu anotasi".

Dilaporkan secara deskriptif saja (tidak menentukan): coverage dan density E-03 (`eval copy`)
v2 vs v3, latensi pipeline p50/p95 (`t_total`) dan latensi LLM, token, dan jumlah
`follow_up_topic` yang tidak null.

## Catatan keterbatasan

- Set dev sudah dipakai untuk menyusun v2 (aturan "jawab hanya yang ditanyakan" lahir dari d040
  dev), jadi perbandingan dev condong ke v2. Set uji resmi belum disentuh.
- Satu run per prompt per model. Temperature 0,2 tidak menjamin hasil deterministik.
- Run Gemini E-04 diulang dengan prompt final, yaitu prompt yang dipilih aturan ini. Run v2 9/45
  dihentikan. Lihat docs/E-04.md, amandemen 2.
- Bila v3 dipakai, protokol E-03 (paraphrase vs plain) perlu dicek ulang oleh pengguna, karena
  aturan parafrase v3 berbeda dari `paraphrase`.
