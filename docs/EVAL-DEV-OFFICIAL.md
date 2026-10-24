# Eval dev KB resmi (Langkah 65): set dev, E-01, E-02

Ini evaluasi **dev**, bukan uji resmi. Set uji resmi (data/eval/official/, docs/DATASET.md) tidak
disentuh. Pertanyaan di set ini tidak boleh dipakai di `ui.suggestions`/`ui.topics`, prompt, atau KB.

## Set dev: `data/eval/dev_official.jsonl`

| | |
|---|---|
| SHA-256 | `91c77a436365f1c54527c9311a9551d9e2d381d923d37671f763f4c993e4f26c` |
| KB | `official-2026-10-24-v4` (field `kb_id` di setiap baris; penjaga `kb_match` menolak KB lain) |
| isi | 40 soal: 30 `answerable`, 10 `out_of_kb` (`oos_level: dekat`) |
| penulis | Claude Code (`author: claude-code`), 24 Okt 2026 |
| pool anotasi | `data/eval/dev_official/pool.csv` (522 baris, 48 relevan), SHA-256 `3777c47c35a825987ccc96b00d60f275d081e310ef8f52799d5ebc61eaa89b0a`; `pool_meta.json` di folder yang sama |

**File ini dibekukan sejak SHA-256 di atas dicatat.** Bila harus diubah, buat file versi baru
(mis. `dev_official_v2.jsonl`) dan catat alasannya di sini; file lama tidak disunting.

Format sama dengan `data/eval/questions.jsonl` (`mica.eval.dataset`), ditambah field:
`set` ("dev"), `author`, `answerable` (bool), `kb_id`, `evidence` (dokumen, hlm, bagian, chunk_id;
soal terjawab), `absence_check` (kata kunci yang dicari di `chunks.jsonl` v4 dan jumlah chunk yang
memuatnya; soal tidak terjawab), `conflict_test` (o011, o014). Padanan nama dari instruksi:
id = `qid`, set = `split`/`set`, answerable = `type` (`answerable`/`out_of_kb`), jawaban kunci =
`reference_answer`, bukti = `evidence` + `gold_chunk_ids` + `gold_refs`.

Topik soal terjawab (maksimal 3 per topik): biaya kuliah 2, kelas pagi/sore 2, cicilan 2, cara
bayar 2, potongan/keringanan 2, jalur pendaftaran 3, syarat masuk 3, dokumen pendaftaran 2,
prosedur daftar online 2, pengunduran diri 2, prospek kerja 2, peminatan 2, organisasi mahasiswa
2, kontak 2. Soal konflik sumber: o011 (jalur; Peraturan Akademik Pasal 4 sudah dikeluarkan dari
v4) dan o014 (TOEFL Magister Manajemen; brosur 2025 tidak diketik bagian S2-nya).

**Cara anotasi relevansi (gold).** Bukti awal ditulis Claude dari membaca `chunks.jsonl` v4, lalu
dilengkapi lewat alat yang sama dengan set lama: `python -m mica.eval annotate export` (gabungan
top-10 bm25, dense, hybrid + chunk gold_refs, diurutkan menurut urutan KB, tanpa peringkat), dinilai
Claude, lalu `annotate import`. Dari pool, 3 chunk ditambahkan sebagai relevan: o007 +K#17 (cara
bayar Blibli/VA), o014 +P#19 (pemberkasan Program Magister memuat sertifikat TOEFL, boleh menyusul;
jawaban kunci o014 diperjelas), o015 +P#11 (persyaratan umum: lulusan SMK untuk Sarjana). Pooling
dijalankan sebelum pra-registrasi karena merupakan bagian dari penyusunan gold, bukan evaluasi;
peringkat retriever tidak ditampilkan di pool. Penilai relevansi = Claude, bukan manusia.

**Bukti ketiadaan (soal tidak terjawab)**: kata kunci dan jumlah chunk yang memuatnya ada di
`absence_check` setiap baris. Semua kata kunci yang ditemukan sudah diperiksa
(`hits_reviewed`) dan tidak memuat jawabannya.

## Pra-registrasi (ditulis dan di-commit sebelum E-01/E-02 dijalankan)

### E-01 retrieval

- Perintah: `python -m mica.eval retrieval --config config/dev.yaml --dataset
  data/eval/dev_official.jsonl --pool data/eval/dev_official/pool.csv --retrievers
  bm25,dense,hybrid --out results/E-01/official-<timestamp>`.
- Soal: 30 `answerable` (soal `out_of_kb` tidak masuk E-01).
- Mode: bm25, dense, hybrid; reranker mati; RRF k = 60; 20 kandidat per retriever; seperti E-01
  lama (`mica.eval.retrieval`, kedalaman 10).
- Metrik: **Recall@5** (proporsi soal dengan minimal satu chunk relevan di top-5) dan **MRR**
  (MRR@10, alat yang sama dengan E-01 lama), per mode dan per topik. nDCG@10 dan latensi dicatat
  tetapi tidak dipakai untuk keputusan.
- Dilaporkan: soal yang tidak punya chunk relevan di top-5, beserta dugaan sebabnya.

### E-02 generation

- Perintah: `python -m mica.eval generation --config config/dev.yaml --dataset
  data/eval/dev_official.jsonl --out results/E-02/official-<timestamp>` dengan config aktif:
  `groq:openai/gpt-oss-120b` (model pertama `llm.chain`; tanpa cadangan selama eval), prompt v5,
  KB v4, retriever hybrid, gerbang skor 0,50 menyala (tanpa `--gate-off`), cek angka menyala.
- 40 soal, satu panggilan LLM per soal yang lolos gerbang 1. Token dicatat (run.json).
- Bila kuota Groq habis (`QuotaExhausted`): berhenti, simpan yang sudah jadi (cache), laporkan sisa
  soal untuk dilanjutkan; **tidak pindah penyedia**.
- Per soal dicatat: skor dense@1 dan status gerbang: lolos semua, ditolak gerbang 1 (skor <
  ambang, `refused_gate`), gerbang 2 (LLM menolak, `refused_llm`), atau gerbang 3 (cek angka,
  `refused_check`). Sebaran dense@1 soal terjawab vs tidak terjawab dilaporkan sebagai bahan
  kalibrasi nanti; **ambang tidak diubah**.

**Label per jawaban** (penilaian Claude, bukan penilai manusia; satu kalimat alasan yang merujuk
potongan sumber):

| label | soal | aturan |
|---|---|---|
| benar | terjawab | menjawab inti jawaban kunci, tanpa klaim yang tidak didukung |
| salah | terjawab atau tidak terjawab | dijawab, semua klaim didukung potongan, tetapi tidak menjawab inti jawaban kunci (keliru, tidak lengkap pada inti, atau soal tidak terjawab tidak ditolak) |
| halusinasi | terjawab atau tidak terjawab | ada minimal satu klaim yang tidak didukung atau bertentangan dengan potongan yang diambil (top-5 yang dikirim ke LLM); didahulukan atas benar/salah |
| penolakan-tepat | tidak terjawab | ditolak (gerbang 1, 2, atau 3) |
| penolakan-keliru | terjawab | ditolak (gerbang 1, 2, atau 3) |

Definisi halusinasi di sini mengikuti instruksi Langkah 65 (potongan yang **diambil**). SDD 2.4
memakai potongan yang **dikutip**; karena itu kolom tambahan `hanya_di_potongan_tak_dikutip`
menandai jawaban yang klaimnya hanya didukung potongan yang diambil tetapi tidak dikutip, sehingga
hitungan versi SDD bisa diturunkan.

**Metrik E-02** (dengan interval Wilson 95%):

- % benar = benar / 30 soal terjawab;
- % halusinasi = halusinasi / jumlah jawaban yang tidak ditolak (40 soal);
- % penolakan tepat = penolakan-tepat / 10 soal tidak terjawab;
- % penolakan keliru = penolakan-keliru / 30 soal terjawab.

Soal konflik o011 dan o014 dilaporkan terpisah: o011 salah bila memuat jalur dari Peraturan
Akademik Pasal 4 (mis. UTBK, Pindahan, RPL sebagai jalur); o014 salah bila menyebut MM wajib
TOEFL minimal 475.

### Aturan keputusan

1. Mode retrieval tetap **hybrid**, kecuali ada mode lain yang **Recall@5 dan MRR-nya sama-sama
   lebih tinggi** dari hybrid. Seri pada salah satu metrik = hybrid tetap.
2. Perubahan lain (ambang gerbang, prompt, chunking, model) **tidak diputuskan** dari set dev 40
   soal ini. Hasilnya hanya dicatat sebagai temuan.

## Hasil

(diisi setelah run; bagian di atas tidak diubah)
