# E-02 dev: prompt v2 vs v3 vs v4 (20 Oktober 2026)

Aturan keputusan: docs/PROMPT-V4.md (pra-registrasi, commit 5f6432c, ditulis sebelum run v4).
Kondisi sama dengan run v2: 45 pertanyaan dev, KB `dev-2026-10-15-v2`, dataset sha256
`9dc9c399...627a`, hybrid top_k 5, gerbang off, cek angka menyala, reasoning_effort low,
temperature 0,2.

| model | prompt | folder run |
| --- | --- | --- |
| 120b | v2 | results/E-02/20261017-122758-E-02-dev-hybrid-gpt-oss-120b-gateoff |
| 120b | v3 | results/E-02/20261020-113556-E-02-dev-hybrid-gpt-oss-120b-gateoff |
| 120b | v4 | results/E-02/20261020-130025-E-02-dev-hybrid-gpt-oss-120b-gateoff |
| 20b | v2 | results/E-04/20261016-220121-E-04-dev-hybrid-gpt-oss-20b-gateoff |
| 20b | v3 | results/E-02/20261020-115938-E-02-dev-hybrid-gpt-oss-20b-gateoff |
| 20b | v4 | results/E-02/20261020-135657-E-02-dev-hybrid-gpt-oss-20b-gateoff |

Run 20b v4 sempat berhenti di 44/45 karena kuota token harian Groq (kode 3, 13.45 WIB). Run
dilanjutkan pukul 13.56 dengan perintah yang sama: 44 jawaban dari cache, d045 dari API. Jawaban
yang sudah ada tidak dipanggil ulang.

Berkas: `compare-dev-v4-{120b,20b}{,-summary}.csv`, `*-stdout.txt`. Salin E-03:
`results/E-03/copy-dev-20261020-134915` (120b) dan `copy-dev-20261020-135752` (20b); urutan
baris v2, v3, v4 (LABELS.md).

## Aturan keputusan (ambang null), v4 dibanding v2

| syarat | 120b v2 | 120b v4 | 120b | 20b v2 | 20b v4 | 20b |
| --- | --- | --- | --- | --- | --- | --- |
| salah tolak tidak lebih banyak | 0/25 | 0/25 | lolos | 0/25 | 0/25 | lolos |
| tolak benar tidak lebih sedikit | 16/17 | 16/17 | lolos | 16/17 | 14/17 | **gagal** (d025, d026) |
| premis diluruskan tidak lebih sedikit | 2 | 2 | lolos | 1 | 2 | lolos |
| halusinasi tidak lebih banyak | 0/28 | belum dianotasi | menunggu anotasi | 1/28 (d023) | belum dianotasi | menunggu anotasi |
| JSON gagal tidak lebih banyak | 0 | 0 | lolos | 0 | 0 | lolos |

Keputusan 120b: **menunggu anotasi**. Empat syarat lain seri, dan v4 lolos hanya bila
halusinasinya 0/28. 20b (pendamping) gagal syarat tolak benar: d025 (cicilan) dan d026 (uang
pangkal) isinya menolak, tetapi berstatus `false_premise`, bukan `not_found`.

## Deskriptif (tidak menentukan), ambang null

| ukuran | 120b v2 | 120b v3 | 120b v4 | 20b v2 | 20b v3 | 20b v4 |
| --- | --- | --- | --- | --- | --- | --- |
| premis terbaik/aman/gagal | 2/1/0 | 2/1/0 | 2/1/0 | 1/1/1 | 0/2/1 | 2/0/1 |
| JSON gagal | 0 | 0 | 0 | 0 | 0 | 0 |
| latensi pipeline p50 / p95 (s) | 0,880 / 1,266 | 0,918 / 1,343 | 1,002 / 1,535 | 0,816 / 1,454 | 0,840 / 0,985 | 0,855 / 1,497 |
| token total | 99.127 | 109.577 | 119.294 | 98.748 | 109.133 | 118.191 |
| coverage kutip (mean) | 0,8082 | 0,8471 | 0,8742 | 0,8385 | 0,9028 | 0,8624 |
| density kutip (mean) | 3,3221 | 3,8619 | 3,9824 | 4,3602 | 5,2874 | 4,4229 |
| density kutip tanpa entitas (mean) | 2,4862 | 2,6124 | 2,9201 | 2,9671 | 3,1667 | 3,0170 |
| jawaban dengan items tidak kosong | 0 | 0 | 6 | 0 | 0 | 3 |
| tawaran topik tampil | 0 | 27 | 28 | 0 | 27 | 31 |

Latensi pipeline = t_scrub + t_retrieval + t_gate + t_check + llm_latency_s. Coverage/density v4
dihitung atas answer + items.

Catatan:

- 120b v4 memakai items pada d005, d009, d011, d014, d020, d021. Namun d014 dan d021 tetap
  mengulang isi daftar di answer, jadi di UI daftarnya tampil dua kali. d004 (tiga jalur) tidak
  memakai items.
- Arahan kontak d014 (Bagian Kemahasiswaan, sa.office@mikroskil.ac.id) tetap tidak muncul di
  v3 maupun v4.
- "kamu" tidak dipakai di v4 (120b dan 20b). Aturannya sudah tidak wajib.
- Pada 120b, density salin dan latensi naik dari v2 ke v3 ke v4.
