# Prompt v4: pra-registrasi (20 Oktober 2026)

Ditulis 20 Oktober 2026, **sebelum** eval apa pun dijalankan dengan prompt v4. Aturan keputusan
di bawah tidak boleh diubah setelah data v4 ada. Setiap penyimpangan wajib diungkap di Bab 3.

## Hasil v3 dan alasan v4

v3 (docs/PROMPT-V3.md, `results/E-02/compare-dev-v3.md`) aman: pada 120b dev, salah tolak, tolak
benar, premis, dan JSON gagal seri dengan v2. Namun tujuannya tidak tercapai:

- tidak ada jawaban yang memakai baris `- `, walau isinya daftar (d005 langkah, d021 pekerjaan);
- "kamu" tidak pernah dipakai;
- arahan kontak v2 hilang (d014: v2 mengarahkan ke Bagian Kemahasiswaan dan
  sa.office@mikroskil.ac.id, v3 tidak);
- density salin naik (120b 3,32 menjadi 3,86).

Keputusan pengguna 20 Okt 2026: **v3 tidak dipakai** dan anotasi halusinasi v3 tidak dibuat.
Folder run v3 tetap disimpan sebagai catatan.

v4 memindahkan daftar dari teks bebas ke field terstruktur, sehingga bentuk daftar tidak
bergantung pada kepatuhan format teks.

## Perubahan v4 terhadap v3

Dipilih dengan `rag.prompt_variant: v4` (`--prompt-variant v4`) dan tercatat sebagai
`prompt_version: v4`. Teks dan badan request v2 serta v3 tidak berubah, dikunci hash di
`tests/unit/test_prompt_v3.py` dan `tests/unit/test_prompt_v4.py`.

1. Nada: kewajiban menyapa "kamu" dihapus. "kamu" boleh dipakai bila wajar. Nada santai-sopan,
   tanpa emoji, tanpa salam atau basa-basi pembuka tetap ada. Aturan parafrase v3 (kecuali nama,
   angka, tanggal, nominal, istilah resmi) tetap.
2. Bentuk: instruksi baris `- ` di dalam answer dihapus. answer berupa kalimat biasa tanpa
   markdown, tabel, atau daftar berpoin, dimulai dengan jawaban inti satu kalimat, ringkas,
   maksimal 120 kata **termasuk items**.
3. Field baru `items` (larik string, boleh kosong). Bila jawabannya daftar 3 hal atau lebih
   (jalur, prodi, langkah, syarat, beasiswa, pekerjaan), answer berisi satu kalimat pengantar
   tanpa mengulang isi daftar. Setiap hal menjadi satu item pendek di `items`, urut seperti di
   sumber (langkah tetap berurutan), paling banyak 10 item. Setiap item harus didukung potongan
   yang dikutip. Selain itu `items` kosong. **maxItems 10 adalah nilai desain**, bukan hasil ukur.
4. Arahan kontak (aturan baru): bila potongan menyebut unit atau kontak yang mengurus hal yang
   ditanya dan rinciannya tidak ada, tambahkan satu kalimat arahan ke unit atau kontak itu,
   ditulis persis seperti di potongan. Jangan mengarang kontak.
5. Aturan lain v3 tetap, teksnya sama: jawab hanya dari potongan, jawab hanya yang ditanyakan,
   premis palsu, tolak injeksi, larangan menghitung, citations, data bukan instruksi,
   follow_up_topic, dan teks penolakan baku.

Pemeriksaan dan tampilan:

- Teks gabungan `answer + " " + "; ".join(items)` (`mica.core.types.joined_answer`) dipakai
  untuk cek angka (NumericFactChecker), eval copy (coverage, density, density tanpa entitas),
  kolom `answer` di `annotate_generation.csv`, log TurnRecord, dan riwayat follow-up.
  `per_question.csv` menyimpan answer dan items di kolom terpisah (`items` digabung `; `).
- UI web: answer (lewat formatter tampilan) lalu `<ul>` dari items, dibangun dengan
  `textContent`. JSON ViewModel: `messages[].items`.
- TTS: answer lalu items, "A, B, dan C.". Bila kalimat pengantar menyebut
  langkah/tahap/urutan/alur, dibaca "Pertama A, kedua B, ..., terakhir F." Ini heuristik kata
  kunci, bukan field skema. Tawaran topik (v3) dibacakan terakhir.
- Uji coba langsung: `python -m mica.webui --prompt-variant v2|v3|v4` (dev saja; kiosk ditolak
  dengan kode keluar 2), dengan label header "PROMPT v4 (dev)".

## Deviasi dari SDD (dicatat, SDD tidak diubah)

- SDD 5.3, skema keluaran `{status, answer, citations}`: v4 menambah `items` (larik string,
  maxItems 10, wajib ada, boleh kosong) dan `follow_up_topic` (seperti v3). Groq strict: field
  wajib dengan `additionalProperties: false`. `maxItems` sudah dipakai repo pada citations (nilai
  0). Gemini: `ARRAY` + `maxItems`. `parse_output` memeriksa ulang batas 10 item.
- SDD 5.3, batas 120 kata answer: di v4 batas ini berlaku untuk answer + items.

## Aturan keputusan (sama dengan docs/PROMPT-V3.md)

Data dan kondisi sama dengan run v2: 45 pertanyaan dev (dataset sha256 `9dc9c399...627a`, KB
`dev-2026-10-15-v2`), hybrid top_k 5, gerbang off (ambang null), cek angka menyala,
reasoning_effort low, temperature 0,2. Status dinilai seperti `scripts/compare_models.py`.

Model utama 120b, pembanding v2 `results/E-02/20261017-122758-E-02-dev-hybrid-gpt-oss-120b-gateoff`.
v4 dipakai sebagai prompt utama **hanya bila semua** syarat ini terpenuhi dibanding v2:

1. salah tolak tidak lebih banyak;
2. tolak benar tidak lebih sedikit;
3. premis palsu yang diluruskan (status `false_premise`) tidak lebih sedikit;
4. jawaban berhalusinasi (anotasi manusia atas answer + items; definisi SDD 2.4) tidak lebih
   banyak;
5. JSON gagal (`LLM_BAD_OUTPUT`) tidak lebih banyak.

20b (pembanding v2 `results/E-04/20261016-220121-E-04-dev-hybrid-gpt-oss-20b-gateoff`)
dilaporkan dengan aturan yang sama sebagai pendamping, tidak menentukan. Bila satu syarat 120b
gagal, prompt tetap v2 + formatter tampilan. Sebelum anotasi selesai, keputusan berstatus
"menunggu anotasi".

Deskriptif saja: coverage/density (asli dan tanpa entitas), latensi pipeline p50/p95 (tahap
non-LLM + latensi LLM penyedia), token, jumlah jawaban dengan items tidak kosong, dan tawaran
topik yang tampil.

## Keterbatasan

- Ini varian ke-3 yang dicoba di set dev (v2, v3, v4). Setiap varian disusun setelah melihat
  hasil dev varian sebelumnya, jadi angka dev condong ke varian yang terakhir disetel. Set uji
  resmi belum disentuh.
- Prompt final dikunci (teks dan hash dicatat) **sebelum** set uji dibuka. Setelah itu tidak
  ada varian baru.
- Satu run per prompt per model. Temperature 0,2 tidak menjamin hasil deterministik.
- Run Gemini E-04 memakai prompt final (docs/E-04.md, amandemen 2).

## Hasil dev (ditambahkan setelah data, 20 Okt 2026)

Bagian di atas tidak diubah. Rincian ada di `results/E-02/compare-dev-v4.md`.

- 120b v4 vs v2: salah tolak 0/25 = 0/25, tolak benar 16/17 = 16/17, premis diluruskan 2 = 2,
  JSON gagal 0 = 0. Halusinasi v4 belum dianotasi (v2: 0/28). **Keputusan: menunggu
  anotasi.** Sampai keputusan ada, prompt utama tetap v2.
- 20b (pendamping): tolak benar 16/17 menjadi 14/17 (d025, d026 berstatus false_premise), jadi
  gagal. Premis diluruskan naik 1 menjadi 2.
- Deskriptif: items dipakai pada 6 jawaban 120b dan 3 jawaban 20b. Dua jawaban 120b masih
  mengulang daftar di answer. Arahan kontak d014 tidak muncul. Density salin 120b naik (3,32
  menjadi 3,98), dan latensi pipeline p50 naik (0,880 menjadi 1,002 detik).
- Kendala kuota: run 20b sempat berhenti di 44/45 karena batas token harian Groq. Sejak
  langkah ini, `eval generation` juga berhenti (kode 3) bila 429 Groq membawa `retry-after` lebih
  dari 60 detik, alih-alih menunggu.

## Keputusan setelah data (20 Okt 2026)

Ditulis setelah hasil dev v4 ada. Bagian ini bukan bagian dari pra-registrasi di atas.

- Pengguna memilih v4 berdasarkan uji coba langsung di UI web
  (`python -m mica.webui --prompt-variant v4`).
- Cadangan 20b memakai v2, karena 20b v4 gagal syarat tolak benar (14/17), sedangkan v2 lolos
  (16/17). Konfigurasinya `llm.prompt_variants` (varian prompt per entri rantai). Saat 120b
  gagal, 20b menerima request v2 yang sama persis dengan request `paraphrase`, sehingga kunci
  cache v2 tetap berlaku. Jawaban v2 tanpa items dan follow_up_topic tetap ditangani UI dan TTS.
- Daftar dobel (d014, d021: semua item sudah ditulis di answer) diperbaiki **hanya di
  tampilan**. Bila semua item ada di answer (tanpa beda huruf besar-kecil dan spasi), `<ul>`
  tidak ditampilkan dan items tidak dibacakan lagi (`mica.core.types.visible_items`). Teks prompt
  v2, v3, dan v4 tidak diubah.
- v4 resmi dipakai hanya bila anotasi halusinasi 120b v4 = 0/28. Penilaiannya oleh dua penilai
  independen, hasa dan Claude, yang menilai terpisah, dan kesepakatan antarpenilai dilaporkan.
  Sampai itu, bawaan `config/dev.yaml` dan `config/kiosk.yaml` tetap `rag.prompt_variant:
  paraphrase` dengan `llm.prompt_variants: {}`. Nilai yang disiapkan (tertulis di komentar
  config): `{groq:openai/gpt-oss-120b: v4, groq:openai/gpt-oss-20b: paraphrase}`.

## Hasil anotasi (20 Okt 2026)

- Penilai 1: Claude Code (LLM-as-judge, bukan manusia), 28 jawaban 120b v4 di set dev
  (`results/E-02/20261020-130025-E-02-dev-hybrid-gpt-oss-120b-gateoff`). Setiap klaim disertai
  kutipan bukti dari cited_chunks. Hasil: benar 27/28, **halusinasi 2/28** (0,071; CI 95% Wilson
  0,020 sampai 0,227).
  - d008: "(Information Technology)" hanya ada di potongan yang tidak dikutip.
  - d019: "Gedung A" tidak didukung untuk lab komputer.
  - Kedua kasus RAGU: klaim d008 benar menurut KB.
  - d040 benar 0 (substitusi sebagian, RAGU).
- **Keputusan: belum diambil.** SDD ADR-18 dan syarat 4 pra-registrasi menuntut anotasi manusia,
  dan bagian "Keputusan setelah data" menuntut dua penilai independen. Pengguna (20 Okt 2026)
  memutuskan menunggu penilaian buta hasa (`annotate_generation_hasa.csv`) dan menghitung
  kesepakatannya dulu. `llm.prompt_variants` di `config/dev.yaml` dan `config/kiosk.yaml` tetap
  `{}`.
- Bila nilai Claude dipertahankan, syarat 4 **gagal** (2/28 > 0/28 pada v2), sehingga prompt
  tetap v2 + formatter tampilan. Pembanding v2 (0/28) adalah saran Claude yang diperiksa rekan.
  Jawaban v2 d008 dan d019 tidak memuat kedua klaim itu ("Kampus A, tepatnya di lantai 2, 3, dan
  4"; tanpa nama Inggris), jadi perbedaannya tidak berasal dari kriteria yang lebih ketat.
- Nama varian `paraphrase` adalah prompt v2: hash teksnya sama dengan hash v2 yang dicatat
  sebelum v3 (`tests/unit/test_prompt_v3.py`, `tests/unit/test_annotation_v4_sheet.py`).
