"""V2-3: nilai V6/V6G dengan aturan V2-2, terapkan aturan pilih pra-reg bagian 4, tulis laporan.

Label: jawaban V6 yang identik dengan B0 (teks + status) memakai label B0; jawaban V6G yang
identik dengan V6 memakai label V6. Sisanya dari eval/dev/v2_3/nilai_V6.py dan nilai_V6G.py.

Pemakaian: python scripts/v2_3_report.py
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "eval/dev/v2_3"
DOC = ROOT / "docs/V2-HASIL-DEV.md"


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


def graded(runs: list[dict], manual: dict, keys: dict, r20: dict) -> list[dict]:
    out = []
    for r in runs:
        r = {**r, "set": "v2", "gold_rank": r20.get(r["qid"])}
        g = base.grade(r, keys[r["qid"]], manual)
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


def main() -> None:
    keys = {}
    with (ROOT / "data/eval/dev_v2_kunci.csv").open(encoding="utf-8") as f:
        for k in csv.DictReader(f, delimiter=";"):
            keys[k["qid"]] = k
    b0_runs = [r for r in jl(ROOT / "eval/dev/v2_baseline/runs.jsonl") if r["set"] == "v2"]
    b0_manual = {q: v for (s, q), v in load(ROOT / "eval/dev/v2_baseline/nilai_manual.py",
                                            "b0").NILAI.items() if s == "v2"}  # fmt: skip
    b0_by = {r["qid"]: r for r in b0_runs}
    r_by = {r["qid"]: r for r in jl(D / "R.jsonl")}
    b0_r20 = {r["qid"]: r["gold_rank"] for r in b0_runs}
    r_r20 = {q: r["gold_rank"] for q, r in r_by.items()}

    v6 = jl(D / "V6.jsonl")
    v6_nilai = load(D / "nilai_V6.py", "v6").NILAI
    v6_manual = {}
    for r in v6:
        q = r["qid"]
        v6_manual[("v2", q)] = (
            b0_manual[q] if same(r, b0_by[q]) and q in b0_manual else v6_nilai.get(q)
        )
    v6_manual = {k: v for k, v in v6_manual.items() if v is not None}

    b0_rows = graded(b0_runs, {("v2", q): v for q, v in b0_manual.items()}, keys, b0_r20)
    v6_rows = graded(v6, v6_manual, keys, r_r20)
    sums = {"B0": base.summarize(b0_rows), "V6": base.summarize(v6_rows)}
    rows = {"B0": b0_rows, "V6": v6_rows}

    v6g_path = D / "V6G.jsonl"
    v6g = jl(v6g_path) if v6g_path.exists() else []
    complete = len(v6g) == 108
    if complete:
        v6g_nilai = load(D / "nilai_V6G.py", "v6g").NILAI
        v6_by = {r["qid"]: r for r in v6}
        man = {}
        for r in v6g:
            q = r["qid"]
            if same(r, v6_by[q]) and ("v2", q) in v6_manual:
                man[("v2", q)] = v6_manual[("v2", q)]
            elif q in v6g_nilai:
                man[("v2", q)] = v6g_nilai[q]
        rows["V6G"] = graded(v6g, man, keys, r_r20)
        sums["V6G"] = base.summarize(rows["V6G"])
    for name, s in sums.items():
        print(name, {k: s[k] for k in ("dijawab", "tidak_halu", "halusinasi", "halu_A", "halu_B",
                                        "tolak_keliru", "tolak_tepat", "recall5", "recall20")},
              dict(s["penyebab"]), f"{100 * s['tidak_halu_pct']:.1f}%")  # fmt: skip
    if not complete:
        print(f"V6G belum lengkap ({len(v6g)}/108): laporan belum ditulis")
        return
    write_doc(sums, rows)


def write_doc(sums: dict, rows: dict) -> None:
    b0 = sums["B0"]
    verdict = {n: passes(sums[n], b0) for n in ("V6", "V6G")}
    winners = [n for n in ("V6", "V6G") if verdict[n][0]]
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

    names = ["B0", "V6", "V6G"]
    cols = {n: col(n) for n in names}
    labels = ["Dijawab", "Tidak halu [Wilson 95%]", "Halusinasi", ("Tolak keliru (g1 / top5 / "
              "not_found / g3)"), "Tolak tepat", "Recall@5", "Recall@20"]  # fmt: skip
    L = [
        "# V2-3: Hasil penyetelan di set dev v2 (B0 / R / V6 / V6G)\n",
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
            "Recall dihitung untuk soal jenis ada/sebagian dengan chunk gold (n=68). V6 dan V6G memakai "
            "retrieval R (P1); recall@20 V6/V6G = R."
        ),
        "",
        (
            f"**R (P1, retrieval saja):** recall@5 B0 {b0['recall5']}/68 -> R {sums['V6']['recall5']}/68 "
            f"(top-5 V6 = top-5 R), @20 {b0['recall20']}/68 -> {sums['V6']['recall20']}/68. Latensi "
            f"retrieval + reranker di CPU laptop: p50 {p50:.1f} detik, p95 {p95:.1f} detik per kueri "
            "(SDD ADR-01/E-01 mensyaratkan p95 <= 0,5 detik untuk reranker)."
        ),
        "",
        "## 2. Aturan pilih (pra-reg bagian 4)\n",
    ]
    for n in ("V6", "V6G"):
        ok, why = verdict[n]
        L.append(f"- **{n}**: {'LOLOS' if ok else 'tidak lolos'} ({'; '.join(why)}).")
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
        "## 3. Soal yang berubah label\n",
        "| qid | jenis | B0 | V6 | V6G |\n|---|---|---|---|---|",
    ]
    by = {n: {r["qid"]: r for r in rows[n]} for n in names}
    for q in sorted(by["B0"]):
        labs = [label(by[n][q]) for n in names]
        if len(set(labs)) > 1:
            L.append(f"| {q} | {by['B0'][q]['jenis']} | " + " | ".join(labs) + " |")
    L += ["\n## 4. Run yang dilakukan\n"]
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
        "\n## 5. Revisi prompt\n",
        "- Prompt v6: tidak direvisi (0 dari maksimal 1).",
        "- Prompt verifikator: tidak direvisi (0 dari maksimal 1).",
        "\n## 6. Per soal\n",
        (
            "| qid | jenis | V6 status | V6 nilai | V6G status | V6G nilai | catatan V6G |\n"
            "|---|---|---|---|---|---|---|"
        ),
    ]
    for q in sorted(by["V6"]):
        a, g = by["V6"][q], by["V6G"][q]
        note = g["catatan"] or a["catatan"]
        L.append(f"| {q} | {a['jenis']} | {a['final_status']} | {label(a)} | {g['final_status']} | "
                 f"{label(g)} | {note or '-'} |")  # fmt: skip
    L += [
        "\n## 7. Berkas\n",
        (
            "- `eval/dev/v2_3/R.jsonl`, `V6.jsonl` (termasuk keluaran LLM mentah), `V6G.jsonl` "
            "(putusan verifikator per kalimat di `fact_check.sentence_verify`), `logs-*`, `meta.json`."
        ),
        "- Penilaian: `eval/dev/v2_3/nilai_V6.py`, `nilai_V6G.py`, `penilaian_*.csv`.",
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
