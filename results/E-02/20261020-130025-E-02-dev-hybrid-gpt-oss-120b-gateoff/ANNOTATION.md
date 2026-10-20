# Anotasi halusinasi: gpt-oss-120b, prompt v4 (set dev)

## Penilai 1: Claude Code (LLM-as-judge, bukan manusia), 20 Okt 2026

- File: `annotate_generation.csv` (28 baris answered/false_premise). Salinan identik:
  `annotate_generation_llm_judge.csv`. Ringkasan: `annotation_summary.json`
  (`python -m mica.eval annotation --run <folder ini>`).
- Hanya set dev. Menurut SDD ADR-18 penilai LLM hanya pelengkap. Hasil ini **belum** dipakai
  untuk keputusan prompt (keputusan pengguna 20 Okt 2026: menunggu penilai manusia).
- Kolom `answer` = answer + items digabung "; " (joined_answer), sama dengan yang dicek
  NumericFactChecker.
- Aturan:
  - halusinasi = 1 bila ada klaim di answer atau items yang tidak didukung `cited_chunks` baris
    itu. Klaim yang hanya ada di potongan yang tidak dikutip tetap dihitung halusinasi.
  - benar = 1 bila menjawab pertanyaan dengan tepat sesuai `reference_answer` (boleh lebih
    ringkas, tidak boleh salah atau mengganti pertanyaan).
- Setiap klaim di `catatan` disertai kutipan bukti persis dari `cited_chunks`, dengan ID potongan
  disingkat (mis. [03#2] = 03_biaya_kuliah_dan_syarat_masuk#2).
- Hasil: benar 27/28, halusinasi 2/28 (tingkat 0,071; CI 95% Wilson 0,020 sampai 0,227).

Kasus RAGU:

| qid | nilai | alasan |
| --- | --- | --- |
| d008 | halusinasi 1 | "(Information Technology)" sebagai nama Inggris Teknologi Informasi hanya ada di potongan yang tidak dikutip (14_faq#1). Klaimnya benar menurut KB, tetapi tidak ada di cited_chunks. |
| d019 | halusinasi 1 | "Gedung A" untuk lab komputer: di potongan yang dikutip, Gedung A hanya disebut untuk laboratorium akuntansi. Lab komputer tercatat di "Kampus A lantai 2, 3, dan 4". |
| d040 | benar 0 | Status false_premise. Answer menyatakan tidak ada biaya USU, tetapi menambahkan biaya Mikroskil sebagai pengganti (substitusi sebagian), sedangkan reference = di luar cakupan. Angkanya didukung potongan (halusinasi 0). |

## Penilai 2: hasa (manusia), belum

- Lembar kosong: `annotate_generation_hasa.csv` (qid, pertanyaan, reference, answer, dan
  cited_chunks sama, tanpa nilai). hasa menilai **buta**: tidak membuka
  `annotate_generation.csv`, `annotate_generation_llm_judge.csv`, `annotation_summary.json`,
  atau berkas ini sebelum selesai.
- Setelah selesai, kesepakatan antarpenilai (persentase dan Cohen's kappa untuk `halusinasi` dan
  `benar`) dihitung dan dilaporkan. Keputusan prompt memakai aturan docs/PROMPT-V4.md.
- Set uji resmi wajib dinilai manusia secara buta (tanpa saran atau nilai Claude).

Catatan pembanding: anotasi v2 120b (0/28) adalah saran Claude yang diperiksa rekan tanpa
perubahan (ANNOTATION.md run v2). Kriteria "klaim harus ada di cited_chunks" di sini diterapkan
dengan ketat, termasuk untuk nama Inggris dan nama gedung.
