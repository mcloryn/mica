"""V2-3/V2-4: nilai V6/V6G/V6r/V6Gr dengan aturan V2-2, terapkan aturan pilih pra-reg bagian 4,
tulis laporan docs/V2-HASIL-DEV.md.

Label: jawaban yang identik (teks + status) dengan run induknya memakai label induk (V6 <- B0,
V6G <- V6, V6r <- V6/B0, V6Gr <- V6G/V6r). Sisanya dari eval/dev/v2_3/nilai_<run>.py. Modul
nilai boleh memuat PENYEBAB = {qid: penyebab} untuk menimpa penyebab tolak keliru otomatis.

Pemakaian: python scripts/v2_3_report.py
"""

from __future__ import annotations

import csv
import importlib.util
import json
from collections import Counter
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "eval/dev/v2_3"
DOC = ROOT / "docs/V2-HASIL-DEV.md"
N = 108
# run -> induk untuk pewarisan label, berurutan
PARENTS = {"V6": ["B0"], "V6G": ["V6"], "V6r": ["V6", "B0"], "V6Gr": ["V6G", "V6r"]}
CANDIDATES = ["V6", "V6G", "V6r", "V6Gr"]
# koreksi penilaian setelah laporan pertama (V2-4 A), dicatat di laporan
KOREKSI = [
    (
        "v2d-046",
        "V6G",
        "benar -> tidak_lengkap",
        (
            "KB v5 memuat Ujian Saring Masuk S2 (pedoman-pmb-2027#7 butir e, ada di top-5); jawaban "
            "tidak menyebutnya. Bukan halusinasi, jadi persen tidak halu tetap."
        ),
    ),
    (
        "v2d-059",
        "V6G",
        "penyebab llm_not_found -> gerbang_3 (verifikator)",
        (
            "status answered, tetapi verifikator membuang kalimat jawabannya sehingga sisanya hanya "
            "penolakan; label tetap tolak_keliru."
        ),
    ),
]


def load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


base = load(ROOT / "scripts/v2_baseline_report.py", "v2_baseline_report")


def jl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x]


def same(a: dict, b: dict) -> bool:
    return a["answer"] == b["answer"] and a["final_status"] == b["final_status"]


def graded(
    runs: list[dict], manual: dict, keys: dict, r20: dict, cause: dict | None = None
) -> list[dict]:
    out = []
    for r in runs:
        r = {**r, "set": "v2", "gold_rank": r20.get(r["qid"])}
        g = base.grade(r, keys[r["qid"]], manual)
        if cause and r["qid"] in cause and g["nilai"] == "tolak_keliru":
            g["penyebab"] = cause[r["qid"]]
        top5 = [x["chunk_id"] for x in r["top5"]]
        out.append({**r, **g, "gold_in5": any(c in top5 for c in r["gold"])})
    return out


def label(r: dict) -> str:
    return f"{r['nilai']}{'/' + r['golongan'] if r['golongan'] else ''}" + (
        f" ({r['penyebab']})" if r["penyebab"] else ""
    )


def passes(s: dict, b0: dict) -> tuple[bool, list[str]]:
    why = []
    ok1 = s["halusinasi"] < b0["halusinasi"]
    ok2 = s["tidak_halu_pct"] >= round(b0["tidak_halu_pct"], 3)
    ok3 = s["tolak_keliru"] <= b0["tolak_keliru"]
    why.append(f"halu {s['halusinasi']} < {b0['halusinasi']}: {'ya' if ok1 else 'tidak'}")
    why.append(
        f"tidak halu {100 * s['tidak_halu_pct']:.1f}% >= {100 * b0['tidak_halu_pct']:.1f}%: "
        f"{'ya' if ok2 else 'tidak'}"
    )
    why.append(
        f"tolak keliru {s['tolak_keliru']} <= {b0['tolak_keliru']}: {'ya' if ok3 else 'tidak'}"
    )
    return ok1 and ok2 and ok3, why


def provider(r: dict) -> str | None:
    if "llm_provider" in r:  # B0
        return r["llm_provider"]
    if r["final_status"] == "refused_gate" or not r.get("llm_raw"):
        return None
    return r["llm_raw"].get("provider")


def main() -> None:
    keys = {}
    with (ROOT / "data/eval/dev_v2_kunci.csv").open(encoding="utf-8") as f:
        for k in csv.DictReader(f, delimiter=";"):
            keys[k["qid"]] = k
    b0_runs = [r for r in jl(ROOT / "eval/dev/v2_baseline/runs.jsonl") if r["set"] == "v2"]
    b0_manual = {q: v for (s, q), v in load(ROOT / "eval/dev/v2_baseline/nilai_manual.py",
                                            "b0").NILAI.items() if s == "v2"}  # fmt: skip
    b0_r20 = {r["qid"]: r["gold_rank"] for r in b0_runs}
    r_r20 = {r["qid"]: r["gold_rank"] for r in jl(D / "R.jsonl")}

    data = {"B0": {r["qid"]: r for r in b0_runs}}
    manual: dict[str, dict] = {"B0": b0_manual}  # qid -> (nilai, klaim, golongan, catatan)
    causes: dict[str, dict] = {"B0": {}}
    rows = {"B0": graded(b0_runs, {("v2", q): v for q, v in b0_manual.items()}, keys, b0_r20)}
    incomplete = []
    for run in CANDIDATES:
        path = D / f"{run}.jsonl"
        runs = jl(path) if path.exists() else []
        if len(runs) != N:
            incomplete.append(f"{run} {len(runs)}/{N}")
            continue
        mod = load(D / f"nilai_{run}.py", run.lower())
        own, own_cause = mod.NILAI, getattr(mod, "PENYEBAB", {})
        man, cause = {}, {}
        for r in runs:
            q = r["qid"]
            for p in PARENTS[run]:
                if p in data and same(r, data[p][q]) and q in manual[p]:
                    man[q] = manual[p][q]
                    if q in causes[p]:
                        cause[q] = causes[p][q]
                    break
            else:
                if q in own:
                    man[q] = own[q]
            if q in own_cause:
                cause[q] = own_cause[q]
        data[run], manual[run], causes[run] = {r["qid"]: r for r in runs}, man, cause
        rows[run] = graded(runs, {("v2", q): v for q, v in man.items()}, keys, r_r20, cause)
    sums = {n: base.summarize(r) for n, r in rows.items()}
    for name, s in sums.items():
        print(name, {k: s[k] for k in ("dijawab", "tidak_halu", "halusinasi", "halu_A", "halu_B",
                                        "tolak_keliru", "tolak_tepat", "recall5", "recall20")},
              dict(s["penyebab"]), f"{100 * s['tidak_halu_pct']:.1f}%")  # fmt: skip
    if incomplete:
        print("belum lengkap:", ", ".join(incomplete))
    if "V6G" not in rows:
        print("V6G belum lengkap: laporan belum ditulis")
        return
    write_doc(sums, rows, data, incomplete)


def write_doc(sums: dict, rows: dict, data: dict, incomplete: list[str]) -> None:
    b0 = sums["B0"]
    cands = [n for n in CANDIDATES if n in sums]
    verdict = {n: passes(sums[n], b0) for n in cands}
    winners = [n for n in cands if verdict[n][0]]
    winners.sort(key=lambda n: (sums[n]["halusinasi"], sums[n]["tolak_keliru"]))
    meta = json.loads((D / "meta.json").read_text("utf-8"))
    r_rows = jl(D / "R.jsonl")
    lat = sorted(r["latency_s"] for r in r_rows)
    p50, p95 = lat[len(lat) // 2], lat[int(0.95 * len(lat)) - 1]

    def col(n: str) -> list[str]:
        s = sums[n]
        lo, hi = s["wilson95"]
        p = s["penyebab"]
        return [
            str(s["dijawab"]),
            (
                f"{s['tidak_halu']}/{s['dijawab']} = {100 * s['tidak_halu_pct']:.1f}% "
                f"[{100 * lo:.1f}; {100 * hi:.1f}]"
            ),
            f"{s['halusinasi']} (A {s['halu_A']} / B {s['halu_B']})",
            (
                f"{s['tolak_keliru']} ({p['gerbang_1']} / {p['gold_tidak_top5']} / "
                f"{p['llm_not_found']} / {p['gerbang_3']})"
            ),
            str(s["tolak_tepat"]),
            f"{s['recall5']}/{s['n_gold']} = {s['recall5'] / s['n_gold']:.2f}",
            f"{s['recall20']}/{s['n_gold']} = {s['recall20'] / s['n_gold']:.2f}",
        ]

    names = ["B0", *cands]
    cols = {n: col(n) for n in names}
    labels = ["Dijawab", "Tidak halu [Wilson 95%]", "Halusinasi", ("Tolak keliru (g1 / top5 / "
              "not_found / g3)"), "Tolak tepat", "Recall@5", "Recall@20"]  # fmt: skip
    L = [
        "# V2-3/V2-4: Hasil penyetelan di set dev v2 (B0 / R / " + " / ".join(cands) + ")\n",
        (
            "Mengikuti `docs/PRA-REGISTRASI-V2.md` (commit `v2-3a`). Penilaian oleh Claude di set dev, "
            "**bukan penilaian resmi**; aturan sama dengan V2-2 (`docs/V2-BASELINE-DEV.md`). "
            "`config/prod.yaml` tidak diubah; semua perubahan default mati.\n"
        ),
        "## 1. Ringkasan\n",
        "| | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
        *[
            f"| {lab} | " + " | ".join(cols[n][i] for n in names) + " |"
            for i, lab in enumerate(labels)
        ],
        "",
        (
            "Recall dihitung untuk soal jenis ada/sebagian dengan chunk gold (n=68). Semua kandidat "
            "memakai retrieval R (P1). g3 = gerbang 3 (cek angka/kontak atau verifikator P3)."
        ),
    ]
    if incomplete:
        L.append(f"\n**Run belum lengkap (tidak dinilai):** {', '.join(incomplete)}.")
    L += [
        "",
        (
            f"**R (P1, retrieval saja):** recall@5 B0 {b0['recall5']}/68 -> R {sums['V6']['recall5']}/68 "
            f"(top-5 V6 = top-5 R), @20 {b0['recall20']}/68 -> {sums['V6']['recall20']}/68. Latensi "
            f"retrieval + reranker di CPU laptop: p50 {p50:.1f} detik, p95 {p95:.1f} detik per kueri "
            "(SDD ADR-01/E-01 mensyaratkan p95 <= 0,5 detik untuk reranker)."
        ),
        "",
        "## 2. Aturan pilih (pra-reg bagian 4)\n",
        "| kandidat | halu < 11 | tidak halu >= 77,1% | tolak keliru <= 26 | lolos |",
        "|---|---|---|---|---|",
    ]
    for n in cands:
        ok, why = verdict[n]
        cells = [w.rsplit(": ", 1) for w in why]
        L.append(f"| {n} | " + " | ".join(f"{a} ({b})" for a, b in cells) +
                 f" | {'LOLOS' if ok else 'tidak'} |")  # fmt: skip
    if winners:
        L.append(f"\n**Terpilih: {winners[0]}** (halusinasi paling sedikit, lalu tolak keliru).")
    else:
        L.append("\n**Tidak ada kandidat yang lolos.** Sesuai pra-reg: v2 = B0 + perubahan yang lolos "
                 "sendiri-sendiri, atau tidak ada perubahan.")  # fmt: skip
    L += [
        (
            "\nCatatan pra-reg: n kecil (sekitar 50 jawaban), selisih di set dev hanya indikatif; klaim "
            "perbaikan yang sah hanya dari Tahap 2. Konfigurasi terpilih **belum** diaktifkan di "
            "`config/prod.yaml`.\n"
        ),
        "## 3. Koreksi penilaian\n",
        "Dibuat setelah laporan V2-3 (commit `v2-3b`), sebelum run V6r/V6Gr.\n",
        "| qid | run | koreksi | alasan |\n|---|---|---|---|",
        *[f"| {q} | {r} | {k} | {a} |" for q, r, k, a in KOREKSI],
        "",
        "## 4. Penyedia LLM penjawab\n",
        (
            "Rantai `llm.chain` = gpt-oss-120b lalu gpt-oss-20b (config prod). Bila 120b gagal "
            "(misalnya HTTP 429 batas token harian), jawaban datang dari 20b."
        ),
        "",
        "| run | gpt-oss-120b | gpt-oss-20b | tanpa LLM (gerbang 1) |\n|---|---|---|---|",
    ]
    for n in names:
        c = Counter(provider(r) for r in data[n].values())
        L.append(f"| {n} | {c['groq:openai/gpt-oss-120b']} | {c['groq:openai/gpt-oss-20b']} | "
                 f"{c[None]} |")  # fmt: skip
    L += ["\n## 5. Soal yang berubah label\n",
          "| qid | jenis | " + " | ".join(names) + " |\n|---|---|" + "---|" * len(names)]  # fmt: skip
    by = {n: {r["qid"]: r for r in rows[n]} for n in names}
    for q in sorted(by["B0"]):
        labs = [label(by[n][q]) for n in names]
        if len(set(labs)) > 1:
            L.append(f"| {q} | {by['B0'][q]['jenis']} | " + " | ".join(labs) + " |")
    L += ["\n## 6. Run yang dilakukan\n"]
    for n, m in meta.items():
        L.append(
            f"- `{n}`: override `{json.dumps(m['overrides'])}`, config_hash `{m['config_hash'][:12]}`."
        )
    L += [
        (
            "- V6G run 1 (`eval/dev/v2_3/V6G_run1_gagal429.jsonl`) **tidak sah**: verifikator kena "
            "HTTP 429 karena batas token harian Groq gpt-oss-120b (200.000 TPD) habis setelah V6; "
            "verifikator fail-closed sehingga jawaban ditolak. Dihentikan, diarsipkan, tidak dinilai. "
            "Run sah dilanjutkan setelah kuota pulih, dengan V6 yang sama."
        ),
        "- Retrieval config bawaan identik dengan B0 di 10/10 soal (`eval/dev/v2_3/default_check.json`).",
        (
            "- Reranker V6r/V6Gr: kondisi R yang lama (bawaan CrossEncoder, kandidat 20). "
            "`docs/V2-RERANK-LATENSI.md` tidak ada; bench `scripts/v2_rerank_bench.py` hanya "
            "menyelesaikan kondisi 1 (= kondisi R: top-5 sama dengan R 68/68, p50 14,46 / p95 14,82 "
            "detik per kueri, `eval/dev/v2_3/rerank_bench_stdout.txt`). Kondisi 2-4 tidak terukur."
        ),
        "\n## 7. Revisi prompt\n",
        (
            "- Prompt v6: 1 dari maksimal 1 -> `v6r` (sasaran G1 dan G4, `docs/PROMPT-V6.md` "
            '"Revisi 1").'
        ),
        "- Prompt verifikator: 1 dari maksimal 1 -> `r1` (definisi faithfulness RAGAs).",
        "\n## 8. Per soal\n",
        "| qid | jenis | " + " | ".join(f"{n} status | {n} nilai" for n in cands) + " | catatan |",
        "|---|---|" + "---|---|" * len(cands) + "---|",
    ]
    for q in sorted(by["V6"]):
        cells = " | ".join(f"{by[n][q]['final_status']} | {label(by[n][q])}" for n in cands)
        note = next((by[n][q]["catatan"] for n in reversed(cands) if by[n][q]["catatan"]), "")
        L.append(f"| {q} | {by['V6'][q]['jenis']} | {cells} | {note or '-'} |")
    L += [
        "\n## 9. Berkas\n",
        (
            "- `eval/dev/v2_3/R.jsonl`, `V6.jsonl`, `V6r.jsonl` (termasuk keluaran LLM mentah), "
            "`V6G.jsonl`, `V6Gr.jsonl` (putusan verifikator per kalimat di "
            "`fact_check.sentence_verify`), `logs-*`, `meta.json`."
        ),
        "- Penilaian: `eval/dev/v2_3/nilai_<run>.py`, `penilaian_*.csv`.",
        "- Skrip: `scripts/v2_3_runs.py`, `scripts/v2_3_report.py`. Prompt: `docs/PROMPT-V6.md`.",
    ]
    DOC.write_text("\n".join(L) + "\n", encoding="utf-8")
    for n in names:
        with (D / f"penilaian_{n}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(
                [
                    "qid",
                    "jenis",
                    "final_status",
                    "nilai",
                    "golongan",
                    "penyebab",
                    "klaim",
                    "catatan",
                ]
            )
            for r in rows[n]:
                w.writerow([r["qid"], r["jenis"], r["final_status"], r["nilai"], r["golongan"],
                            r["penyebab"], r["klaim"], r["catatan"]])  # fmt: skip
    print("terpilih:", winners[0] if winners else "tidak ada")


if __name__ == "__main__":
    main()
