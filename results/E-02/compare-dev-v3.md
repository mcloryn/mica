# E-02 dev: prompt v3 vs v2 (20 Oktober 2026)

Aturan keputusan: docs/PROMPT-V3.md (pra-registrasi, commit f3e6818, ditulis sebelum run ini).
Kondisi: 45 pertanyaan dev, KB `dev-2026-10-15-v2`, dataset sha256 `9dc9c399...627a`, hybrid
top_k 5, gerbang off, cek angka menyala, reasoning_effort low, temperature 0,2.

| model | prompt | folder run |
| --- | --- | --- |
| 120b | v2 | results/E-02/20261017-122758-E-02-dev-hybrid-gpt-oss-120b-gateoff |
| 120b | v3 | results/E-02/20261020-113556-E-02-dev-hybrid-gpt-oss-120b-gateoff |
| 20b | v2 | results/E-04/20261016-220121-E-04-dev-hybrid-gpt-oss-20b-gateoff |
| 20b | v3 | results/E-02/20261020-115938-E-02-dev-hybrid-gpt-oss-20b-gateoff |

Berkas: `compare-dev-v3-120b{,-summary}.csv`, `compare-dev-v3-20b{,-summary}.csv`, dan
`*-stdout.txt` (`scripts/compare_models.py`, ambang null + 0,50). Salin E-03:
`results/E-03/copy-dev-20261020-122411` (urutan baris summary.csv: 120b v2, 120b v3, 20b v2,
20b v3; lihat `LABELS.md` di folder itu).

## Aturan keputusan (ambang null)

| syarat (v3 dibanding v2) | 120b v2 | 120b v3 | 120b | 20b v2 | 20b v3 | 20b |
| --- | --- | --- | --- | --- | --- | --- |
| salah tolak tidak lebih banyak | 0/25 | 0/25 | lolos | 0/25 | 0/25 | lolos |
| tolak benar tidak lebih sedikit | 16/17 | 16/17 | lolos | 16/17 | 16/17 | lolos |
| premis diluruskan tidak lebih sedikit | 2 | 2 | lolos | 1 | 0 | **gagal** (d029) |
| halusinasi tidak lebih banyak | 0/28 | belum dianotasi | menunggu anotasi | 1/28 (d023) | belum dianotasi | menunggu anotasi |
| JSON gagal tidak lebih banyak | 0 | 0 | lolos | 0 | 0 | lolos |

Keputusan 120b: **menunggu anotasi** (empat syarat lain lolos, semuanya seri). Karena v2 120b
berhalusinasi 0/28, v3 120b hanya lolos bila halusinasinya juga 0. 20b (pendamping)
sudah gagal syarat premis: d029 (prodi Kedokteran) diluruskan pada v2 tetapi `not_found` pada v3.

## Deskriptif (tidak menentukan)

| ukuran | 120b v2 | 120b v3 | 20b v2 | 20b v3 |
| --- | --- | --- | --- | --- |
| premis terbaik/aman/gagal | 2/1/0 | 2/1/0 | 1/1/1 | 0/2/1 |
| latensi LLM p50 / p95 (s) | 0,817 / 1,204 | 0,838 / 1,277 | 0,764 / 1,398 | 0,746 / 0,914 |
| latensi pipeline p50 / p95 (s) | 0,880 / 1,266 | 0,918 / 1,343 | 0,816 / 1,454 | 0,840 / 0,985 |
| token total | 99.127 | 109.577 | 98.748 | 109.133 |
| follow_up_topic tidak null (dari 45) | 0 | 37 | 0 | 45 |
| tawaran tampil (answered/false_premise) | 0 | 27 | 0 | 27 |
| tawaran tampil = topik pertanyaan | - | 1 (d008) | - | 8 |
| jawaban berisi baris "- " | 0 | 0 | 0 | 0 |
| jawaban memakai "kamu" / "Anda" | 0 / 3 | 0 / 0 | 0 / 0 | 0 / 0 |
| rata-rata kata (jawaban non-tolak) | 17,8 | 14,8 | 20,4 | 16,2 |
| coverage kutip (mean) | 0,8082 | 0,8471 | 0,8385 | 0,9028 |
| density kutip (mean) | 3,3221 | 3,8619 | 4,3602 | 5,2874 |
| density kutip tanpa entitas (mean) | 2,4862 | 2,6124 | 2,9671 | 3,1667 |

Latensi pipeline = t_scrub + t_retrieval + t_gate + t_check + llm_latency_s. `t_total` eval tidak
dipakai karena memuat waktu tunggu pembatas laju (p95 sekitar 60 detik).

Catatan:

- v3 lebih pendek dan tanpa "Anda". Namun v3 tidak pernah memakai "kamu" atau baris "- ", walau
  ada daftar 3 item atau lebih (mis. d004, d021). Sebagian aturan bentuk dan nada tidak diikuti.
- Coverage dan density v3 lebih tinggi pada kedua model, artinya jawaban v3 lebih banyak
  menyalin dari potongan, walau aturan parafrase v3 mengecualikan nama dan istilah resmi.
- Topik lanjutan condong ke "Program Studi" (120b: 19) dan "Biaya" (20b: 23).
- d014 120b v3 menyebut Beasiswa IP4 "disebutkan di brosur", sedangkan v2 menyebut "muncul di
  testimoni". Ini kandidat yang perlu dicek anotator.
