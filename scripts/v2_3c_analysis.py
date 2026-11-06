"""V2-3c C+D: analisis tolak keliru V6 dan token Groq per soal (lokal, tanpa memanggil Groq).

Kelompok pola ditetapkan dari pembacaan log V6 (eval/dev/v2_3/V6.jsonl: keluaran LLM mentah,
fact_check) dan penilaian V6; tabel KELOMPOK di bawah adalah hasil pembacaan itu.

  python scripts/v2_3c_analysis.py
"""

from __future__ import annotations

import csv
import importlib.util
import statistics
from pathlib import Path

from mica.config import read_raw, settings_from_raw
from mica.core.types import ScoredChunk, ScrubbedText
from mica.kb.index import DEFAULT_KB_ROOT, load_kb
from mica.rag.pii import scrub_pii
from mica.rag.prompts import build_prompt
from mica.rag.verifier import VERIFY_SYSTEM, is_courtesy, split_sentences, verify_user

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "eval/dev/v2_3"
DOC = ROOT / "docs/V2-ANALISIS-TOLAK-V6.md"

# qid -> (kelompok, alasan singkat dari log)
KELOMPOK = {
    "v2d-002": ("G1", "not_found; biaya per semester tidak tertulis, biaya per tahun ada di top-5"),
    "v2d-005": (
        "G1",
        "not_found; biaya per bulan tidak tertulis, biaya tahunan + skema cicilan sore ada",
    ),
    "v2d-006": (
        "G1",
        "not_found; 'naik tiap tahun' tidak tertulis, 'ditetapkan Rektor tiap tahun' ada",
    ),
    "v2d-017": ("G1", "not_found; penurunan IP tidak disebut, alasan penghentian beasiswa ada"),
    "v2d-019": ("G1", "not_found; jadwal KIP (ikut Ditjen Dikti) dan 01-30 Mei ada"),
    "v2d-034": ("G1", "not_found; nominal tidak ada, komponen registrasi (Uang Kuliah + DP3) ada"),
    "v2d-061": ("G1", "not_found; isi prodi Manajemen (pemasaran) ada, penilaian 'cocok' tidak"),
    "v2d-065": ("G1", "not_found; daftar mata kuliah tidak ada, keahlian AI-based software ada"),
    "v2d-071": ("G1", "not_found; nama perusahaan tidak ada, MCC bermitra industri ada"),
    "v2d-086": ("G1", "not_found; bulan tidak ada, 'minimal 1x per tahun akademik' ada"),
    "v2d-096": ("G1", "not_found; 'ujian lewat aplikasi pembelajaran' ada"),
    "v2d-024": ("G2", "chunk gold (pmb#5) tidak di top-5"),
    "v2d-053": ("G2", "chunk gold (RPL alih jenjang) tidak di top-5"),
    "v2d-057": ("G2", "chunk gold (brosur#14) tidak di top-5"),
    "v2d-060": ("G2", "chunk gold (pmb#14 daftar prodi) tidak di top-5"),
    "v2d-085": ("G2", "chunk gold (MPT, kemahasiswaan#7/#12) tidak di top-5"),
    "v2d-089": ("G2", "chunk gold (Layanan Fakultas) tidak di top-5"),
    "v2d-091": ("G2", "chunk gold (akademik#32 daring) tidak di top-5"),
    "v2d-013": ("G3", "unsupported 2,3,4 = penomoran '1) 2) 3) 4)' di tengah kalimat"),
    "v2d-028": (
        "G3",
        "unsupported 12,4: jawaban '12 kali'/'4 kali', sumber '12x'/'4x' (angka menempel huruf diabaikan)",
    ),
    "v2d-087": ("G3", "unsupported 3.000: jawaban 'sekitar 3.000', sumber '3k students'"),
    "v2d-046": (
        "G4",
        "unsupported 14 = sitasi '(pmb/pedoman-pmb-2027#14)' ditulis di teks jawaban",
    ),
    "v2d-106": ("G5", "not_found; seharusnya false_premise (B0 mengoreksi)"),
    "v2d-108": ("G5", "not_found; KB hanya kampus Medan (kunci ragu)"),
    "v2d-039": ("G6", "not_found; 'uang pembangunan' tidak dikenali sebagai DP3 (kunci ragu)"),
    "v2d-043": (
        "G7",
        "unsupported 2019 (dari pertanyaan); kesimpulan 'tidak memenuhi syarat' juga keliru (Reguler)",
    ),
    "v2d-056": (
        "G7",
        "unsupported 0811-7070-3992 (tanda hubung U+2011); nomor itu WA Keuangan, disebut PMB",
    ),
    "v2d-092": ("G8", "dense@1 0,462 < 0,50; gold di peringkat 38"),
}
NAMA = {
    "G1": "Soal 'sebagian' ditolak seluruhnya (not_found, gold di top-5): aturan v6 (b) tidak diikuti",
    "G2": "Chunk gold tidak masuk top-5 (retrieval + reranker)",
    "G3": "Angka benar, cek angka (gerbang 3) gagal karena format penulisan",
    "G4": "Sitasi ID chunk ditulis di teks jawaban, nomor ID terbaca sebagai angka",
    "G5": "Premis salah dijawab not_found, bukan dikoreksi",
    "G6": "Jenis 'ada', gold di top-5, istilah pertanyaan beda dengan KB",
    "G7": "Gerbang 3 menahan jawaban yang memang keliru (penolakan menguntungkan)",
    "G8": "Gerbang 1 (dense@1 < 0,50)",
}


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, round(p * len(xs)) - 1))]


def main() -> None:
    rep = load(ROOT / "scripts/v2_3_report.py", "v2_3_report")
    keys = {}
    with (ROOT / "data/eval/dev_v2_kunci.csv").open(encoding="utf-8") as f:
        for k in csv.DictReader(f, delimiter=";"):
            keys[k["qid"]] = k
    b0 = [r for r in rep.jl(ROOT / "eval/dev/v2_baseline/runs.jsonl") if r["set"] == "v2"]
    b0_by = {r["qid"]: r for r in b0}
    b0_m = {q: v for (s, q), v in load(ROOT / "eval/dev/v2_baseline/nilai_manual.py", "b").NILAI.items()
            if s == "v2"}  # fmt: skip
    b0_rows = {
        r["qid"]: r for r in rep.graded(b0, {("v2", q): v for q, v in b0_m.items()}, keys, {})
    }
    v6 = rep.jl(D / "V6.jsonl")
    n6 = load(D / "nilai_V6.py", "v6").NILAI
    man = {}
    for r in v6:
        q = r["qid"]
        v = b0_m[q] if rep.same(r, b0_by[q]) and q in b0_m else n6.get(q)
        if v:
            man[("v2", q)] = v
    v6_rows = {r["qid"]: r for r in rep.graded(v6, man, keys, {})}
    tk = [q for q, r in v6_rows.items() if r["nilai"] == "tolak_keliru"]
    assert set(tk) == set(KELOMPOK), sorted(set(tk) ^ set(KELOMPOK))

    L = [
        "# V2-3c: Analisis tolak keliru V6 dan token Groq per soal\n",
        (
            "Lokal, tanpa memanggil Groq. Sumber: `eval/dev/v2_3/V6.jsonl` (keluaran LLM mentah dan "
            "`fact_check`), penilaian V6 (`eval/dev/v2_3/nilai_V6.py` + aturan V2-2), dan B0 "
            "(`eval/dev/v2_baseline/`). Prompt **tidak** diubah di langkah ini. Penilaian oleh Claude, "
            "bukan penilaian resmi.\n"
        ),
        f"## 1. Ringkasan\n\nTolak keliru V6 = **{len(tk)}** (B0 26). Penyebab per definisi V2-2: "
        + ", ".join(f"{k} {v}" for k, v in sorted(_count(v6_rows, tk).items()))
        + ".\n",
        "| Kelompok | Pola | Jumlah | qid |\n|---|---|---|---|",
    ]
    for g in sorted(NAMA):
        qs = [q for q in sorted(tk) if KELOMPOK[q][0] == g]
        L.append(f"| {g} | {NAMA[g]} | {len(qs)} | {', '.join(qs)} |")
    newly = [q for q in sorted(tk) if b0_rows[q]["keputusan"] == "menjawab"]
    fixed = sorted(q for q, r in b0_rows.items() if r["nilai"] == "tolak_keliru" and q not in tk)
    L += [
        "",
        f"- Tolak keliru V6 yang di B0 **dijawab**: {len(newly)} ({', '.join(newly)}); label B0: "
        + ", ".join(f"{q} {b0_rows[q]['nilai']}" for q in newly)
        + ".",
        f"- Tolak keliru B0 yang di V6 tidak lagi tolak keliru: {len(fixed)} ({', '.join(fixed)}); "
        "label V6: " + ", ".join(f"{q} {v6_rows[q]['nilai']}" for q in fixed) + ".",
        f"- Selisih bersih: {len(tk)} - 26 = {len(tk) - 26:+d}.",
        "\n## 2. Pola\n",
        (
            "- **G1 (11)** terbesar: v6 aturan (b) meminta 'jawab bagian yang ada, sebut bagian yang tidak "
            "ditemukan', tetapi semua soal 'sebagian' dengan gold di top-5 tetap not_found. Sama dengan B0 "
            "(B0 juga menolak 10 dari 11, ditambah v2d-096 yang di B0 dijawab dengan halusinasi A). "
            "Artinya aturan (b) belum efektif; aturan v5 'Jawab hanya hal yang ditanyakan ... bila "
            "potongan hanya memuat informasi yang mirip ... not_found' kemungkinan mengalahkan (b)."
        ),
        (
            "- **G2 (7)**: retrieval. Reranker menaikkan recall@5 (52 -> 58/68), tetapi 7 soal ini tetap "
            "di luar top-5; 5 di antaranya 'sebagian'."
        ),
        (
            "- **G3 + G4 (4)**: keterbatasan `NumericFactChecker` yang sudah tercatat di docstring-nya "
            "(angka menempel huruf '12x' diabaikan, angka kata/singkatan '3k', penomoran di tengah "
            "kalimat). G4 baru muncul di v6: model menulis ID chunk di teks jawaban (efek samping aturan "
            "(c) 'kalimat wajib bersitasi'; aturan sitasi v5 hanya untuk field citations)."
        ),
        "- **G5 + G6 (3)**: premis salah / istilah berbeda dijawab not_found.",
        (
            "- **G7 (2)**: gerbang 3 menolak jawaban yang memang salah (v2d-043 kesimpulan keliru, "
            "v2d-056 nomor Keuangan disebut nomor PMB). Secara definisi tetap tolak keliru (KB punya "
            "jawabannya), tetapi penolakan ini mencegah halusinasi B."
        ),
        "- **G8 (1)**: gerbang 1, sama dengan B0.",
        "\n## 3. Per soal\n",
        (
            "| qid | jenis kunci | gold di top-5 | penyebab (V2-2) | kelompok | alasan (log LLM / gerbang 3) | "
            "B0 |\n|---|---|---|---|---|---|---|"
        ),
    ]
    for q in sorted(tk):
        r, b = v6_rows[q], b0_rows[q]
        bl = f"{b['final_status']} ({b['nilai']}{'/' + b['golongan'] if b['golongan'] else ''})"
        L.append(f"| {q} | {r['jenis']} | {'ya' if r['gold_in5'] else 'tidak'} | {r['penyebab']} | "
                 f"{KELOMPOK[q][0]} | {KELOMPOK[q][1]} | {bl} |")  # fmt: skip

    L += token_section(v6)
    DOC.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("tolak keliru", len(tk), {g: sum(KELOMPOK[q][0] == g for q in tk) for g in sorted(NAMA)})


def _count(rows: dict, qs: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for q in qs:
        out[rows[q]["penyebab"]] = out.get(rows[q]["penyebab"], 0) + 1
    return out


def token_section(v6: list[dict]) -> list[str]:
    settings = settings_from_raw(read_raw(ROOT / "config/prod.yaml"), ROOT / ".env",
                                 require_complete=False)  # fmt: skip
    kb = {c.chunk_id: c for c in load_kb(settings.kb.active_id, DEFAULT_KB_ROOT).chunks}
    # refused_gate: LLM tidak dipanggil; llm_raw di baris itu sisa soal sebelumnya (bug CaptureLlm
    # di run V6, diperbaiki di scripts/v2_3_runs.py), jadi diabaikan
    called = [
        r
        for r in v6
        if r["final_status"] != "refused_gate" and (r.get("llm_raw") or {}).get("usage")
    ]
    pin = [r["llm_raw"]["usage"]["prompt_tokens"] for r in called]
    pout = [r["llm_raw"]["usage"]["completion_tokens"] for r in called]
    # rasio karakter/token dari prompt V6 yang dibangun ulang (system + user) vs prompt_tokens Groq
    ratios = []
    est_in, est_out, n_ver = [], [], 0
    for r in called:
        hits = [
            ScoredChunk(kb[h["chunk_id"]], h["score"], h["ranks"], h["raw_scores"])
            for h in r["top5"]
        ]
        req = build_prompt(ScrubbedText(scrub_pii(r["question"])), [], hits, "v6",
                           (), settings.rag.source_priority)  # fmt: skip
        ratios.append((len(req.system) + len(req.user)) / r["llm_raw"]["usage"]["prompt_tokens"])
    ratio = statistics.median(ratios)
    per_soal_v6g = []
    for r in called:
        tot = r["llm_raw"]["usage"]["total_tokens"]
        if r["llm_raw"]["status"] in ("answered", "false_premise"):
            claims = [s for s in split_sentences(r["llm_raw"]["answer"]) if not is_courtesy(s)]
            hits = [ScoredChunk(kb[h["chunk_id"]], 0, {}, {}) for h in r["top5"]]
            vin = (len(VERIFY_SYSTEM) + len(verify_user(claims, hits))) / ratio
            vout = (
                40 * len(claims) + 60
            )  # ASUMSI: ~40 token JSON+alasan per kalimat + ~60 penalaran
            est_in.append(vin)
            est_out.append(vout)
            n_ver += 1
            tot += vin + vout
        per_soal_v6g.append(tot)
    per_soal_v6 = [r["llm_raw"]["usage"]["total_tokens"] for r in called]
    retries = sum(r["attempts"] - 1 for r in v6)
    return [
        "\n## 4. Token Groq per soal (D)\n",
        (
            f"Dari `usage` respons Groq di V6 ({len(called)} soal yang sampai ke LLM; "
            f"{len(v6) - len(called)} soal berhenti di gerbang 1 tanpa panggilan LLM; `llm_raw` di baris "
            "refused_gate V6 adalah sisa soal sebelumnya karena bug pencatatan dan diabaikan). Hanya panggilan "
            f"terakhir yang tercatat; {retries} percobaan ulang (timeout) juga memakai kuota tetapi "
            "tidak tercatat.\n"
        ),
        "| | rata-rata | p95 |\n|---|---|---|",
        f"| V6 input (prompt_tokens) | {statistics.mean(pin):.0f} | {pct(pin, 0.95):.0f} |",
        (
            f"| V6 output (completion_tokens, termasuk penalaran) | {statistics.mean(pout):.0f} | "
            f"{pct(pout, 0.95):.0f} |"
        ),
        f"| V6 total per soal | {statistics.mean(per_soal_v6):.0f} | {pct(per_soal_v6, 0.95):.0f} |",
        (
            f"| Verifikator input, perkiraan ({n_ver} jawaban) | {statistics.mean(est_in):.0f} | "
            f"{pct(est_in, 0.95):.0f} |"
        ),
        f"| Verifikator output, perkiraan | {statistics.mean(est_out):.0f} | {pct(est_out, 0.95):.0f} |",
        (
            f"| **V6G total per soal, perkiraan** | **{statistics.mean(per_soal_v6g):.0f}** | "
            f"**{pct(per_soal_v6g, 0.95):.0f}** |"
        ),
        "",
        (
            f"- Input verifikator diperkirakan dari panjang prompt verifikator (karakter) dibagi rasio "
            f"karakter/token V6 ({ratio:.2f} karakter per token, median dari {len(ratios)} prompt V6 yang "
            "dibangun ulang). Output verifikator adalah **asumsi** (40 token per kalimat klaim + 60), "
            "karena run V6G yang sah belum ada."
        ),
        (
            f"- Total V6 tercatat: {sum(per_soal_v6)} token; perkiraan V6G (V6 + verifikator): "
            f"{sum(per_soal_v6g):.0f} token. Batas Groq gpt-oss-120b: 8.000 token/menit dan 200.000 "
            "token/hari, sehingga satu run 108 soal V6G tidak muat dalam kuota harian satu hari."
        ),
    ]


if __name__ == "__main__":
    main()
