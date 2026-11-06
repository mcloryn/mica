# Amandemen pra-registrasi v2 (V2-5, jalur gratis)

Ditulis 7 Nov 2026, sebelum run FINAL, sebagai amandemen `docs/PRA-REGISTRASI-V2.md`. Pra-reg
asli tidak diubah dan tetap dilaporkan. Baseline resmi Tahap 1 (`tahap1-beku`) dan set uji 129
soal tidak disentuh; kunci dev tidak diubah.

**Waktu penulisan.** Run V6r (prompt v6r, revisi 1) sedang berjalan saat amandemen ini ditulis:
40 dari 61 soal S sudah punya keluaran, tetapi **belum dinilai dan belum dianalisis**. Aturan di
bawah ditetapkan tanpa melihat hasil V6r. Hasil yang sudah ada sebelum amandemen: B0, R, V6, V6G
(108 soal dan subset S), bench reranker (`docs/V2-RERANK-LATENSI.md`).

## Latar

- Hanya kuota Groq gratis yang tersedia: gpt-oss-120b 200.000 token per 24 jam bergulir. Satu
  jawaban V6 rata-rata ~3.000 token; verifikator P3 menambah ~2.500 token per jawaban.
- Di B0 dan V6, 120b kena HTTP 429 di sepertiga akhir run dan rantai pindah diam-diam ke
  gpt-oss-20b (35/99 jawaban). Karena itu analisis utama memakai subset S = 61 soal yang di B0 dan
  V6 dijawab 120b (`eval/dev/v2_3/subset_S.json`; lihat `docs/V2-HASIL-DEV.md` bagian deviasi).

## a. V6Gr dibatalkan; P3 (verifikator per kalimat) tidak dipakai di v2

V6Gr (verifikator r1 atas V6r) tidak dijalankan. Alasan: (1) kuota gratis; verifikator kira-kira
menggandakan token per jawaban; (2) di V6G, P3 menambah tolak keliru (108 soal: 28 -> 31; S: 16 ->
18) sehingga V6G tidak lolos aturan tolak keliru. Hasil V6G tetap dilaporkan apa adanya.
Prompt verifikator r1 sudah ditulis dan di-commit (`v2-4a`) tetapi tidak pernah dijalankan.

## b. P1 (reranker) dibuang

Reranker `BAAI/bge-reranker-v2-m3` di CPU laptop: p95 sekitar 16 detik per kueri untuk 20
kandidat (`docs/V2-RERANK-LATENSI.md`, kondisi 1-3); kandidat 10 tetap p95 8 detik. Syarat SDD
ADR-01/E-01: p95 reranker <= 0,5 detik. Tidak ada kondisi yang memenuhi, sehingga P1 tidak bisa
dipakai di prod walaupun recall@5 naik (52 -> 58/68).

## c. Pemilihan prompt di S

- Data: subset S (61 soal), label dengan aturan V2-2 (`docs/V2-BASELINE-DEV.md`); jawaban yang
  identik dengan run yang sudah dinilai memakai label lama.
- Patokan = B0 di S: halu < 7, tidak halu >= 77,4%, tolak keliru <= 17.
- Kandidat: V6 dan V6r (keduanya dijalankan dengan reranker kondisi R).
- Bila keduanya lolos: pilih yang halunya lebih sedikit; bila sama, yang tolak kelirunya lebih
  sedikit. Bila hanya satu yang lolos, pakai yang itu. Bila tidak ada yang lolos, pakai V6.

Catatan: pemilihan ini memakai run dengan reranker, sedangkan v2 tidak memakai reranker (b).
Karena itu prompt terpilih diuji ulang tanpa reranker di run FINAL (d), dan hanya FINAL yang
menentukan v2.

## d. Run penentu FINAL

- Konfigurasi: prompt terpilih (c), **tanpa reranker** (retrieval sama dengan B0: hybrid, top-5),
  tanpa verifikator, LLM penjawab hanya gpt-oss-120b (`--primary-only`: bila 120b gagal, run
  berhenti tanpa menulis dan dilanjutkan setelah kuota pulih; tidak ada jawaban dari 20b).
- Data: subset S (61 soal). Penilaian dengan aturan V2-2; jawaban yang identik dengan B0, V6, atau
  V6r memakai label lama.
- Aturan: sama dengan (c) terhadap B0 di S (halu < 7, tidak halu >= 77,4%, tolak keliru <= 17).
- Bila FINAL lolos: v2 = FINAL (diaktifkan di `config/prod.yaml` di commit terpisah, belum merge
  ke `main`). Bila FINAL tidak lolos: v2 = B0 (sistem v5 tetap), dan itu dilaporkan apa adanya.
- Klaim perbaikan yang sah tetap hanya dari Tahap 2 (pra-reg bagian 4). S kecil (sekitar 30
  jawaban) dan tidak memuat soal premis_salah/luar_topik, jadi hasil di S hanya indikatif.

## Yang diungkap di Bab 3

Amandemen ini, alasannya (kuota gratis, latensi reranker), fallback 20b di B0/V6 dan pemakaian
subset S, run yang dibatalkan (V6Gr), serta semua run yang dilakukan (B0, R, V6, V6G, V6r, FINAL).
