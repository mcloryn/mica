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
