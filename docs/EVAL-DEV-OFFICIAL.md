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

Bagian di atas tidak diubah setelah commit pra-registrasi `49b7472`. Kedua run dijalankan dari
commit itu dengan repo bersih (`git_dirty: false` di run.json).

### E-01 (`results/E-01/official-20261024-203849/`)

30 soal terjawab, kedalaman 10, unjudged 0 di ketiga mode.

| mode | Recall@5 | MRR@10 | nDCG@10 | p50 / p95 ms |
|---|---|---|---|---|
| bm25 | 0,8667 (26/30) | 0,6722 | 0,6684 | 1,43 / 1,97 |
| dense | 0,9333 (28/30) | 0,9056 | 0,8885 | 108,77 / 122,60 |
| hybrid | **1,0000 (30/30)** | 0,8083 | 0,8237 | 112,40 / 129,26 |

**Keputusan (aturan 1): hybrid tetap.** Dense punya MRR lebih tinggi, tetapi Recall@5-nya lebih
rendah, jadi tidak unggul di kedua metrik.

Per topik (Recall@5 / MRR):

| topik | n | bm25 | dense | hybrid |
|---|---|---|---|---|
| biaya_kuliah | 2 | 1,00 / 0,75 | 1,00 / 1,00 | 1,00 / 1,00 |
| kelas_pagi_sore | 2 | 1,00 / 1,00 | 1,00 / 1,00 | 1,00 / 1,00 |
| cicilan | 2 | 1,00 / 1,00 | 1,00 / 1,00 | 1,00 / 1,00 |
| cara_bayar | 2 | 1,00 / 0,62 | 1,00 / 1,00 | 1,00 / 0,75 |
| potongan_keringanan | 2 | 1,00 / 0,67 | 1,00 / 1,00 | 1,00 / 1,00 |
| jalur_pendaftaran | 3 | 1,00 / 1,00 | 1,00 / 0,83 | 1,00 / 0,83 |
| syarat_masuk | 3 | 1,00 / 0,83 | 1,00 / 1,00 | 1,00 / 0,83 |
| dokumen_pendaftaran | 2 | 0,50 / 0,17 | 1,00 / 0,75 | 1,00 / 0,42 |
| prosedur_daftar_online | 2 | 1,00 / 0,50 | 0,00 / 0,08 | 1,00 / 0,75 |
| pengunduran_diri | 2 | 1,00 / 0,75 | 1,00 / 1,00 | 1,00 / 1,00 |
| prospek_kerja | 2 | 0,50 / 0,12 | 1,00 / 1,00 | 1,00 / 0,42 |
| peminatan | 2 | 1,00 / 1,00 | 1,00 / 1,00 | 1,00 / 1,00 |
| organisasi_mahasiswa | 2 | 0,50 / 0,25 | 1,00 / 1,00 | 1,00 / 0,67 |
| kontak_jam_operasional | 2 | 0,50 / 0,50 | 1,00 / 1,00 | 1,00 / 0,62 |

Soal tanpa chunk relevan di top-5 (dugaan sebab):

| mode | soal | peringkat relevan pertama | dugaan sebab |
|---|---|---|---|
| bm25 | o017 berkas S1 | > 10 | kosakata santai ("berkas", "disiapin") vs dokumen ("File softcopy", "Pemberkasan"); tanpa stemming |
| bm25 | o023 kerja lulusan SI | > 10 | "kerjanya" vs "Career Path" (bahasa Inggris di brosur) |
| bm25 | o028 himpunan SI | > 10 | singkatan "SI" dan akhiran "-nya" ("himpunannya"); dokumen menulis "Sistem Informasi", "IMSI" |
| bm25 | o029 nomor WA pendaftaran | > 10 | "WA" cocok dengan "WhatsApp" di kontak keuangan; brosur menulis "Online Admission/Consultation" |
| dense | o019 harus ke kampus? | 6 | "daftar" dekat makna dengan "registrasi" (Peraturan Akademik Pasal 23-25) |
| dense | o020 pengumuman lulus | > 10 | "lulus" tertarik ke kelulusan studi/yudisium (Pasal 47-49), bukan lulus seleksi |

### E-02 (`results/E-02/official-20261024-204004/20261024-204009-E-02-dev-hybrid/`)

`groq:openai/gpt-oss-120b`, prompt v5, KB v4, hybrid, gerbang 0,50, cek angka menyala. 40 soal,
37 panggilan API (3 ditolak gerbang 1 tanpa LLM), 0 retry 429, tidak kena kuota. Token:
prompt 92.772, completion 4.663, **total 97.435**. Durasi 1.258 detik (1.187 detik menunggu
pembatas 6.000 token/menit).

**Penilaian oleh Claude, bukan penilai manusia** (`labels_claude.csv`; ringkasan
`labels_summary.json` dari `python -m mica.eval labels --run <folder>`):

| metrik | hasil | CI 95% Wilson |
|---|---|---|
| % benar (soal terjawab) | 26/30 = 86,7% | 70,3-94,7% |
| % halusinasi (jawaban tidak ditolak) | 1/27 = 3,7% | 0,7-18,3% |
| % halusinasi versi SDD (potongan dikutip) | 1/27 = 3,7% | sama |
| % penolakan tepat (soal tidak terjawab) | 10/10 = 100% | 72,2-100% |
| % penolakan keliru (soal terjawab) | 3/30 = 10,0% | 3,5-25,6% |

Soal konflik: o011 lolos (lima jalur Pedoman PMB 2027, tanpa jalur Pasal 4); o014 lolos (tanpa
TOEFL untuk MM).

Soal yang tidak benar:

| soal | label | sebab |
|---|---|---|
| o017 berkas daftar S1 | halusinasi | ijazah SMA dan sertifikat TOEFL dari daftar pemberkasan Program Magister (pmb#19) disebut sebagai berkas Sarjana |
| o009 potongan bayar lunas | penolakan-keliru (gerbang 2) | keuangan#19 di peringkat 1, tetapi chunk hanya menyebut cara mengajukan lunas lewat menu "Potongan Uang Kuliah", tanpa kalimat "ada potongan"; LLM menolak |
| o028 himpunan SI | penolakan-keliru (gerbang 1) | dense@1 0,417 < 0,50; kueri sangat pendek dengan singkatan "SI" |
| o029 nomor WA pendaftaran | penolakan-keliru (gerbang 2) | brosur#14 di peringkat 4, tetapi nomornya berlabel "Online Admission/Consultation", bukan WA |

Status gerbang: soal terjawab 27 lolos, 1 ditolak gerbang 1, 2 ditolak gerbang 2, 0 gerbang 3;
soal tidak terjawab 2 ditolak gerbang 1 (o033, o035), 8 ditolak gerbang 2, 0 lolos.

Sebaran dense@1 (bahan kalibrasi nanti; **ambang tidak diubah**):

| kelompok | n | min | median | maks |
|---|---|---|---|---|
| terjawab | 30 | 0,417 | 0,623 | 0,758 |
| tidak terjawab (dekat) | 10 | 0,431 | 0,545 | 0,621 |

Sebaran keduanya tumpang tindih lebar (0,43-0,62). Di sweep offline `e02_sweep.csv`, ambang
null/0,45/0,48/0,50 memberi salah tolak 3/30 dan tolak benar 10/10; 0,52 dan 0,55 memberi 4/30.
Penolakan soal tidak terjawab terutama datang dari LLM (8/10), sesuai SDD 2.4 (pertanyaan dekat
ditangani lapis LLM).

### Temuan (aturan 2: tidak diputuskan dari set ini)

- Gerbang 0,50 menolak satu soal terjawab berkueri pendek (o028); sebaran skor dekat dan terjawab
  tumpang tindih. Kalibrasi ambang perlu set yang lebih besar.
- Penolakan keliru gerbang 2 terjadi saat istilah kueri tidak tertulis di chunk ("WA",
  "potongan lunas"), walaupun chunk relevan terambil.
- Halusinasi o017: LLM mencampur dua daftar (Sarjana dan Magister) dalam satu chunk pmb#19.
- BM25 lemah pada bahasa santai, singkatan, dan istilah Inggris; dense lemah pada kata ambigu
  ("daftar", "lulus"); hybrid menutup keduanya di Recall@5.

### Catatan alat

- `python -m mica.eval --help` gagal dengan `ValueError: unsupported format character 'W'`
  (tanda % pada teks bantuan "CI 95% Wilson" subperintah annotation). Bukan dari Langkah 65; belum
  diperbaiki.
