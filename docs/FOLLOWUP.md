# FOLLOWUP: penanganan pertanyaan lanjutan (`rag.followup_mode`), Langkah 55

Status: **pra-registrasi**. Ditulis dan di-commit sebelum ada pengukuran. Hasil ditambahkan di
bagian akhir tanpa mengubah aturan.

## Masalah (temuan black-box, 21 Okt 2026)

Mode `concat` (SDD 7.3, F-12) selalu menempelkan pertanyaan sebelumnya ke pertanyaan baru
sebelum retrieval. Kalau pengunjung berganti topik, kuerinya jadi tercampur dan potongan yang
relevan tidak terambil. Contoh yang bisa diulang:

- `python -m mica.ask "Bagaimana rincian biaya kuliah S1 di Mikroskil?" --prev "Di mana alamat
  kampus Universitas Mikroskil?"` -> `refused_llm`. Potongan teratas soal alamat dan kontak;
  tabel biaya tidak terambil.
- Pertanyaan yang sama tanpa `--prev` -> dijawab, dengan sitasi `14_faq_calon_mahasiswa#5`.

## Sumber (diverifikasi dengan membuka halaman ACL Anthology, 21 Okt 2026)

1. Elgohary, A., Peskov, D., Boyd-Graber, J. (2019). *Can You Unpack That? Learning to Rewrite
   Questions-in-Context*. EMNLP-IJCNLP 2019, hlm. 5918-5924. doi:10.18653/v1/D19-1605.
   https://aclanthology.org/D19-1605/ (CANARD: pertanyaan yang bergantung konteks ditulis
   ulang menjadi pertanyaan mandiri dengan jawaban yang sama.)
2. Ma, X., Gong, Y., He, P., Zhao, H., Duan, N. (2023). *Query Rewriting for Retrieval-Augmented
   Large Language Models* (judul di proceedings: *Query Rewriting in Retrieval-Augmented Large
   Language Models*). EMNLP 2023, hlm. 5303-5315. doi:10.18653/v1/2023.emnlp-main.322.
   https://aclanthology.org/2023.emnlp-main.322 (Rewrite-Retrieve-Read: LLM menulis kueri dulu
   sebelum retrieval.)
3. Mo, F., Mao, K., Zhu, Y., Wu, Y., Huang, K., Nie, J.-Y. (2023). *ConvGQR: Generative Query
   Reformulation for Conversational Search*. ACL 2023 (Volume 1: Long Papers), hlm. 4998-5012.
   doi:10.18653/v1/2023.acl-long.274. https://aclanthology.org/2023.acl-long.274/ (Kueri
   percakapan dirumuskan ulang secara generatif untuk retrieval.)

RRF yang dipakai mode `dual` adalah rumus yang sudah ada di SDD 7.3 (Cormack dkk. 2009,
`rag.rrf_k`). Tidak ada parameter baru.

## Kandidat (`mica.rag.followup`, Protocol `FollowupQuery`)

| Mode | Kueri retrieval | Panggilan LLM tambahan |
| --- | --- | --- |
| `concat` | pertanyaan sebelumnya + pertanyaan baru (perilaku lama, pembanding) | tidak |
| `dual` | retrieval pertanyaan apa adanya DAN retrieval concat, digabung RRF (`rag.rrf_k`, kandidat `rag.candidates_per_retriever`) | tidak |
| `llm_rewrite` | LLM `llm.chain[0]` (Groq gpt-oss-120b) menulis ulang pertanyaan baru jadi kalimat utuh hanya bila memang lanjutan; bila ganti topik, pertanyaan dikembalikan apa adanya. JSON ketat `{"query": "..."}`. Gagal/timeout -> pertanyaan apa adanya (bukan concat). Timeout = `llm.timeout_s` | ya, satu panggilan |

Di semua mode, pertanyaan chip topik dijawab tanpa konteks (Langkah 53 opsi A). Teks di-scrub
(`scrub_pii`) sebelum API dan retrieval.

## Data (set dev)

- Pertanyaan lanjutan asli di set dev (`data/eval/questions.jsonl`, `type: followup`): **2**
  (d032, d033).
- Pasangan ganti topik: `data/eval/dev_topic_switch.jsonl`, **14 pasangan** buatan Claude Code
  dari KB dev (`dev-2026-10-15-v2`), ditandai "dibuat Claude Code, set dev". Potongan relevan
  topik baru dianotasi oleh Claude Code dengan membaca isi chunk. Pasangan ini sudah dicek tidak
  mirip set dev (Jaccard token maksimum 0,44 dengan `mica.check.token_jaccard`). Set uji resmi
  (`data/eval/official/test.jsonl`) belum ada, jadi tidak ada yang bisa dicek terhadapnya dan
  tidak ada pertanyaan uji yang dipakai.
- Pertanyaan non-followup: pertanyaan dev bertipe `answerable` (gold dari anotasi E-01), tanpa
  pertanyaan sebelumnya.

## Pengukuran

`python -m mica.eval followup --config config/dev.yaml` (`mica.eval.followup`):

- Kueri dibuat dengan `make_followup`, fungsi yang sama dengan `AnswerPipeline`.
- Retriever `rag.retriever` dev (hybrid), kedalaman 10.
- Latensi retrieval = waktu search saja: median 3 ulangan, dengan satu kueri pemanasan (seperti
  E-01). Untuk `dual`, ini mencakup kedua search. Untuk `llm_rewrite`, ini search kueri hasil
  rewrite saja.
- Latensi rewrite = latensi panggilan API asli. Responsnya disimpan di cache
  `data/cache/llm/rewrite/` (hemat kuota Groq); kalau diulang, dipakai latensi yang tersimpan.
- p95 LLM jawaban dan p95 total diambil dari log giliran `logs/turns-*.jsonl` dengan
  `llm_provider = groq:openai/gpt-oss-120b`.

## Aturan keputusan (ditetapkan sebelum data)

1. **Metrik utama:** Recall@5 (hit@5) pada kelompok gabungan = 2 followup dev + 14 ganti topik
   (n = 16).
2. **Syarat lolos** setiap kandidat:
   - (a) Recall@5 non-followup tidak lebih rendah daripada `concat`.
   - (b) Anggaran SDD 3.3:
     - p95 search ≤ 500 ms (retrieval + gerbang 0,5 s; gerbang hanya membaca skor yang ada).
     - Bila ada panggilan LLM tambahan: p95 rewrite + p95 LLM jawaban ≤ 4 s, dan p95 total
       giliran + p95 rewrite ≤ 10 s.
3. **Pilihan:** di antara kandidat yang lolos, pilih Recall@5 utama tertinggi.
4. **Seri:** kandidat yang selisihnya paling banyak satu pertanyaan (≤ 1 hit) dari yang terbaik
   dianggap seri. Di antara yang seri, pilih yang tanpa panggilan LLM tambahan. Kalau masih ada
   lebih dari satu, pilih hit tertinggi. Kalau masih sama, pilih urutan `concat`, `dual`,
   `llm_rewrite` (kerja tambahan paling sedikit).
5. Aturan diterapkan mekanis oleh `mica.eval.followup.decide` dan hasilnya ditulis apa adanya.
   Pemenang dipasang di `rag.followup_mode` (`config/dev.yaml` dan `config/kiosk.yaml`) dengan
   komentar "dipilih FOLLOWUP.md".

## Keterbatasan (diungkap sebelum data)

- Set ini **kecil** (16 + 23 pertanyaan) dan sebagian besar buatan Claude Code. Pertanyaan
  lanjutan asli hanya 2, jadi kemampuan mode memahami lanjutan yang sebenarnya belum teruji
  kuat.
- Keputusan ini **provisional**, berlaku di dev sampai set uji resmi datang (MS5). Setelah itu
  E-02 menguji ulang `rag.followup_mode`.
- Ini deviasi dari SDD 7.3, karena SDD hanya mengenal `concat` dan `llm_rewrite`; `dual` baru.
  `docs/SDD.md` tidak diubah di sini dan nanti direvisi lewat Claude Doc.

## Hasil (21 Okt 2026, run `results/FOLLOWUP/20261021-212802`)

Diukur setelah commit pra-registrasi `32a441c`. Rewrite: 16 panggilan API Groq, 0 dari cache,
0 fallback.

| Mode | Followup + ganti topik (utama) | Followup dev | Ganti topik | Non-followup | Search p50 / p95 | Rewrite p50 / p95 |
| --- | --- | --- | --- | --- | --- | --- |
| `concat` | 13/16 (0,81) | 2/2 | 11/14 | 23/23 | 156 / 186 ms | - |
| `dual` | **16/16 (1,00)** | 2/2 | 14/14 | 23/23 | 157 / 332 ms | - |
| `llm_rewrite` | 16/16 (1,00) | 2/2 | 14/14 | 23/23 | 149 / 161 ms | 0,62 / 1,02 s |

Anggaran LLM dari log giliran (n = 133, `groq:openai/gpt-oss-120b`): p95 LLM jawaban 4,62 s,
p95 total 7,63 s.

Penerapan aturan (`decide`, apa adanya):

- `concat`: lolos semua syarat (pembanding).
- `dual`: lolos semua syarat: non-followup 23/23 sama, search p95 332 ms ≤ 500 ms, tanpa LLM
  tambahan.
- `llm_rewrite`: **gugur** di syarat anggaran LLM, karena 1,02 + 4,62 > 4 s. p95 LLM jawaban
  saja sudah di atas 4 s, sehingga setiap panggilan LLM tambahan otomatis gugur. Syarat total
  (7,63 + 1,02 ≤ 10 s) lolos.
- Terbaik di antara yang lolos: `dual` 16 hit. **Terpilih: `dual`.**

Yang gagal pada `concat`: ts01 (alamat lalu biaya Akuntansi), ts03 (biaya lalu wakil rektor),
ts05 (ujian saring S2 lalu klub taekwondo). Pada `llm_rewrite`, ke-14 pasangan ganti topik
dikembalikan apa adanya, dan kedua lanjutan ditulis ulang menjadi kalimat utuh (d032: "Biaya
kuliah Sistem Informasi kelas sorenya berapa setahun?").

Uji `python -m mica.ask --prev` dengan `dual` (dev, Groq asli):

| Pertanyaan sebelumnya | Pertanyaan baru | Hasil |
| --- | --- | --- |
| Di mana alamat kampus Universitas Mikroskil? | Bagaimana rincian biaya kuliah S1 di Mikroskil? | dijawab, sitasi `14_faq_calon_mahasiswa#5` (sebelumnya ditolak) |
| Biaya kuliah Teknik Informatika kelas pagi berapa per tahun? | Kalau kelas sorenya? | dijawab: Rp15.000.000 per tahun |
| Apa syarat masuk Magister Teknologi Informasi? | Kalau Magister Manajemen syaratnya apa? | dijawab: IPK 2,75, TOEFL 475, ujian saring |
| Pendaftaran S1 gelombang pertama dibuka kapan? | Kalau gelombang duanya kapan? | dijawab: 2 Juni sampai 4 September 2027 |

Catatan:

- Selisih concat dan dual adalah 3 pertanyaan, dan semuanya berasal dari pasangan buatan Claude
  Code. Pada 2 lanjutan asli, ketiga mode seri.
- `config/kiosk.yaml` ikut `dual`. Mode ini memakai `rag.rrf_k` dan
  `rag.candidates_per_retriever`, yang di kiosk masih `null` (menunggu E-01). Selama keduanya
  belum diisi, kiosk tetap tidak lolos `mica check`, sama seperti sebelumnya.
