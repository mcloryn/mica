# V2-3c: Latensi reranker `BAAI/bge-reranker-v2-m3` di CPU laptop

Lokal, tanpa Groq; `config/prod.yaml` tidak diubah. Skrip: `scripts/v2_rerank_bench.py`
(revisi `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, CPU, `local_files_only`).

## Cara ukur

- Latensi = waktu `CrossEncoder.predict` saja (rerank, tanpa retrieval hybrid) untuk 20 kueri
  pertama set dev v2, setelah satu panggilan pemanasan. Kandidat diambil dari retrieval hybrid
  (reranker mati) dan sama untuk semua kondisi. Batch bawaan `predict` = 32.
- Top-5 dan recall@5 dihitung pada 68 soal dev v2 jenis ada/sebagian yang punya chunk gold,
  dibanding run R (`eval/dev/v2_3/R.jsonl`). "Top-5 sama R" = urutan 5 ID chunk identik.
- Mesin: Intel Core generasi 12 (Family 6 Model 154), 14 core fisik / 20 logis; torch bawaan 14
  thread.
- Tiap kondisi 2-4 dijalankan di proses sendiri, berurutan (`--cond N`), supaya model (~2,3 GB)
  tidak menumpuk di memori. Kondisi 1 berasal dari run semua kondisi pada 7 Nov 01.44 yang
  dihentikan Claude Code karena memori sistem rendah setelah kondisi 1 selesai.

## Hasil

| Kondisi | max_length | thread | kandidat | p50 (detik) | p95 (detik) | top-5 sama R | recall@5 |
|---|---|---|---|---|---|---|---|
| 1 (bawaan = kondisi R) | bawaan (8192) | 14 | 20 | 15,98 | 16,78 | 68/68 | 58/68 |
| 2 | 512 | 14 | 20 | 15,54 | 16,16 | 68/68 | 58/68 |
| 3 | 512 | 14 (= core fisik) | 20 | 15,91 | 16,52 | 68/68 | 58/68 |
| 4 | 512 | 14 | 10 | 7,56 | 8,07 | 26/68 | 57/68 |

Kondisi 1 di run pertama (5 Nov, `eval/dev/v2_3/rerank_bench_stdout.txt`): p50 14,46, p95 14,82
detik, top-5 sama R 68/68. Selisih antar run untuk kondisi yang sama (~1,5 detik) lebih besar
daripada selisih kondisi 1-3, jadi kondisi 1-3 praktis sama cepat.

## Catatan

- max_length 512 tidak memotong apa pun: pasangan terpanjang 413 token, 0 pasangan > 512. Karena
  itu top-5 kondisi 1-3 identik.
- Kondisi 3 sama dengan kondisi 2: thread bawaan torch sudah 14 = jumlah core fisik.
- Kandidat 10 (kondisi 4) memangkas latensi kira-kira setengah, tetapi top-5 berubah di 42/68 soal
  dan recall@5 turun 58 -> 57.
- Semua kondisi jauh di atas syarat SDD ADR-01/E-01 (p95 reranker <= 0,5 detik). Tidak ada
  kondisi yang memenuhi.

## Kondisi untuk V6r/V6Gr (V2-4 butir 7)

Aturan: kondisi dengan top-5 sama R dan latensi terkecil. Kondisi 1-3 memberi top-5 identik
dengan R, dan selisih latensinya di bawah variasi antar run. Kondisi 2 tercatat paling cepat di
run ini, tetapi karena top-5-nya identik, hasil V6r/V6Gr sama apa pun pilihannya. V6r tetap
memakai kondisi R (kondisi 1, tanpa override `max_length`), yang juga dipakai 31 soal V6r yang
sudah berjalan, sehingga konfigurasi run tidak berubah di tengah jalan.

## Berkas

- `eval/dev/v2_3/rerank_bench/cond1.json` ... `cond4.json`
- `eval/dev/v2_3/rerank_bench_stdout.txt` (run 5 Nov), `rerank_bench_stdout_run2.txt` (run 7 Nov,
  terhenti setelah kondisi 1), `rerank_bench_cond2/3/4.stdout.txt`
