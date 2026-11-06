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
# V2-4: V6r/V6Gr hanya dijalankan pada subset S (soal yang di B0 dan V6 dijawab 120b)
SUBSET_RUNS = {"V6r", "V6Gr"}
S_FILE = D / "subset_S.json"
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


def short(p: str | None) -> str:
    return "tanpa LLM" if p is None else p.rsplit("-", 1)[-1]


def verifier(r: dict) -> str | None:
    return ((r.get("fact_check") or {}).get("sentence_verify") or {}).get("provider")


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
    subset = json.loads(S_FILE.read_text("utf-8"))
    s_ids = set(subset["qids"])

    data = {"B0": {r["qid"]: r for r in b0_runs}}
    manual: dict[str, dict] = {"B0": b0_manual}  # qid -> (nilai, klaim, golongan, catatan)
    causes: dict[str, dict] = {"B0": {}}
    rows = {"B0": graded(b0_runs, {("v2", q): v for q, v in b0_manual.items()}, keys, b0_r20)}
    incomplete = []
    for run in CANDIDATES:
        path = D / f"{run}.jsonl"
        runs = jl(path) if path.exists() else []
        expected = s_ids if run in SUBSET_RUNS else set(data["B0"])
        if {r["qid"] for r in runs} != expected:
            incomplete.append(f"{run} {len(runs)}/{len(expected)}")
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
    sums = {n: base.summarize(r) for n, r in rows.items() if n not in SUBSET_RUNS}
    sums_s = {n: base.summarize([x for x in r if x["qid"] in s_ids]) for n, r in rows.items()}
    for tag, ss in (("108", sums), ("S", sums_s)):
        for name, s in ss.items():
            print(tag, name, {k: s[k] for k in ("dijawab", "tidak_halu", "halusinasi", "halu_A",
                                                 "halu_B", "tolak_keliru", "tolak_tepat")},
                  dict(s["penyebab"]), f"{100 * s['tidak_halu_pct']:.1f}%")  # fmt: skip
    if incomplete:
        print("belum lengkap:", ", ".join(incomplete))
    if "V6G" not in rows:
        print("V6G belum lengkap: laporan belum ditulis")
        return
    write_doc(sums, sums_s, rows, data, incomplete, subset, keys)


def col(s: dict) -> list[str]:
    lo, hi = s["wilson95"]
    p = s["penyebab"]
    n_gold = s["n_gold"]
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
        f"{s['recall5']}/{n_gold} = {s['recall5'] / n_gold:.2f}" if n_gold else "-",
    ]


LABELS = ["Dijawab", "Tidak halu [Wilson 95%]", "Halusinasi", ("Tolak keliru (g1 / top5 / "
          "not_found / g3)"), "Tolak tepat", "Recall@5"]  # fmt: skip


def table(sums: dict, names: list[str]) -> list[str]:
    cols = {n: col(sums[n]) for n in names}
    return [
        "| | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
        *[
            f"| {lab} | " + " | ".join(cols[n][i] for n in names) + " |"
            for i, lab in enumerate(LABELS)
        ],
    ]


def rule_table(sums: dict, names: list[str], ref: dict) -> tuple[list[str], list[str]]:
    out = [
        (
            f"| kandidat | halu < {ref['halusinasi']} | tidak halu >= "
            f"{100 * ref['tidak_halu_pct']:.1f}% | tolak keliru <= {ref['tolak_keliru']} | lolos |"
        ),
        "|---|---|---|---|---|",
    ]
    winners = []
    for n in names:
        ok, why = passes(sums[n], ref)
        cells = [w.rsplit(": ", 1) for w in why]
        out.append(f"| {n} | " + " | ".join(f"{a} ({b})" for a, b in cells) +
                   f" | {'LOLOS' if ok else 'tidak'} |")  # fmt: skip
        if ok:
            winners.append(n)
    winners.sort(key=lambda n: (sums[n]["halusinasi"], sums[n]["tolak_keliru"]))
    return out, winners


def write_doc(sums, sums_s, rows, data, incomplete, subset, keys) -> None:
    s_ids = set(subset["qids"])
    full = [n for n in CANDIDATES if n in sums]
    cands_s = [n for n in CANDIDATES if n in sums_s]
    meta = json.loads((D / "meta.json").read_text("utf-8"))
    r_rows = jl(D / "R.jsonl")
    lat = sorted(r["latency_s"] for r in r_rows)
    p50, p95 = lat[len(lat) // 2], lat[int(0.95 * len(lat)) - 1]
    jenis_s = Counter(keys[q]["jenis"] for q in s_ids)
    jenis_all = Counter(k["jenis"] for k in keys.values())
    rule_s, win_s = rule_table(sums_s, cands_s, sums_s["B0"])
    rule_full, win_full = rule_table(sums, full, sums["B0"])
    cross = Counter((provider(data["B0"][q]), provider(data["V6"][q])) for q in data["B0"])
    L = [
        "# V2-3/V2-4: Hasil penyetelan di set dev v2\n",
        (
            "Mengikuti `docs/PRA-REGISTRASI-V2.md` (commit `v2-3a`). Penilaian oleh Claude di set dev, "
            "**bukan penilaian resmi**; aturan sama dengan V2-2 (`docs/V2-BASELINE-DEV.md`). "
            "`config/prod.yaml` tidak diubah; semua perubahan default mati.\n"
        ),
        (
            "**Deviasi dari pra-reg:** sebagian jawaban B0 dan V6 berasal dari model "
            "cadangan gpt-oss-20b, bukan gpt-oss-120b. Karena itu analisis utama memakai subset S "
            "(soal yang di B0 dan V6 dijawab 120b); tabel 108 soal disimpan sebagai sekunder.\n"
        ),
        f"## 1. Utama: subset S (n = {len(s_ids)})\n",
        (
            f"{subset['definisi']}. Daftar dan model per soal: `eval/dev/v2_3/subset_S.json`. "
            "Label sama dengan tabel 108 soal (tanpa penilaian ulang). Komposisi jenis S: "
            + ", ".join(f"{k} {jenis_s[k]}/{jenis_all[k]}" for k in sorted(jenis_all))
            + ". S tidak memuat soal premis_salah dan luar_topik (soal di urutan akhir, saat 120b "
            "kena batas harian), jadi S bukan sampel acak dari set dev."
        ),
        "",
        *table(sums_s, ["B0", *cands_s]),
        "",
        (
            "Recall@5 dihitung untuk soal ada/sebagian dengan chunk gold di S. Semua kandidat memakai "
            "retrieval R (P1). g3 = gerbang 3 (cek angka/kontak atau verifikator P3)."
        ),
    ]
    if incomplete:
        L.append(f"\n**Run belum lengkap (tidak dinilai):** {', '.join(incomplete)}.")
    L += [
        "\n### Aturan pilih di S\n",
        (
            "Pra-reg bagian 4 dengan pembanding B0 di S (angka ambang pra-reg 11 / 77,1% / 26 "
            "berlaku untuk 108 soal dan tidak bisa dipakai langsung di S; ini bagian dari deviasi).\n"
        ),
        *rule_s,
        "",
        f"**Terpilih di S: {win_s[0]}**" if win_s else "**Tidak ada kandidat yang lolos di S.**",
        "",
        "## 2. Sekunder: 108 soal (B0 / V6 / V6G)\n",
        *table(sums, ["B0", *full]),
        "",
        (
            f"**R (P1, retrieval saja):** recall@5 B0 {sums['B0']['recall5']}/68 -> R "
            f"{sums['V6']['recall5']}/68 (top-5 V6 = top-5 R), @20 {sums['B0']['recall20']}/68 -> "
            f"{sums['V6']['recall20']}/68. Latensi retrieval + reranker di CPU laptop: p50 {p50:.1f} "
            f"detik, p95 {p95:.1f} detik per kueri (SDD ADR-01/E-01 mensyaratkan p95 <= 0,5 detik)."
        ),
        "",
        "Aturan pilih pra-reg bagian 4 (ambang 108 soal):\n",
        *rule_full,
        "",
        f"**Terpilih (108): {win_full[0]}**"
        if win_full
        else "**Tidak ada kandidat yang lolos (108).**",
        (
            "\nCatatan pra-reg: n kecil, selisih di set dev hanya indikatif; klaim perbaikan yang sah "
            "hanya dari Tahap 2. Konfigurasi terpilih **belum** diaktifkan di `config/prod.yaml`.\n"
        ),
        "## 3. Koreksi penilaian\n",
        "Dibuat setelah laporan V2-3 (commit `v2-3b`), sebelum run V6r/V6Gr.\n",
        "| qid | run | koreksi | alasan |\n|---|---|---|---|",
        *[f"| {q} | {r} | {k} | {a} |" for q, r, k, a in KOREKSI],
        "",
        "## 4. Deviasi: model cadangan gpt-oss-20b\n",
        (
            "Rantai `llm.chain` config prod = gpt-oss-120b lalu gpt-oss-20b. Run B0 (V2-2b) dan V6 "
            "(V2-3) memakai rantai itu. Mulai sekitar v2d-067, 120b membalas HTTP 429 (batas token "
            "harian 200.000 TPD; `eval/dev/v2_baseline/run_stdout.txt` memuat 67 baris 429) dan "
            "jawaban datang dari 20b tanpa run berhenti. `docs/V2-BASELINE-DEV.md` semula menulis "
            '"semua jawaban dari gpt-oss-120b"; klaim itu salah dan sudah dikoreksi. Ditemukan '
            "7 Nov 2026 saat menyiapkan V2-4. Verifikator V6G (52 panggilan) semuanya 120b."
        ),
        "",
        "| run | penjawab 120b | penjawab 20b | tanpa LLM (gerbang 1) | verifikator 120b |",
        "|---|---|---|---|---|",
    ]
    for n in ["B0", *CANDIDATES]:
        if n not in data:
            continue
        c = Counter(provider(r) for r in data[n].values())
        v = Counter(verifier(r) for r in data[n].values())
        L.append(f"| {n} | {c['groq:openai/gpt-oss-120b']} | {c['groq:openai/gpt-oss-20b']} | "
                 f"{c[None]} | {v['groq:openai/gpt-oss-120b'] or '-'} |")  # fmt: skip
    L += [
        "",
        (
            "Penjawab per soal di B0 x V6: "
            + ", ".join(
                f"{short(a) if a == b and a is None else short(a) + '/' + short(b)} {k}"
                for (a, b), k in cross.most_common()
            )
            + " (120b/120b = S). V6r dan V6Gr dijalankan hanya pada S dengan `--primary-only` "
            "(hanya 120b; run berhenti tanpa menulis bila 120b gagal)."
        ),
        (
            "\nUji Tahap 1 (`tahap1-beku`) tidak terdampak: manifest run mencatat `fallback_chain: "
            "dimatikan; hanya model pertama llm.chain`, dan 65 jawaban LLM semuanya gpt-oss-120b."
        ),
        "\n## 5. Soal yang berubah label (108; V6r/V6Gr hanya S)\n",
    ]
    names = ["B0", *CANDIDATES]
    names = [n for n in names if n in rows]
    by = {n: {r["qid"]: r for r in rows[n]} for n in names}
    L.append("| qid | S | jenis | " + " | ".join(names) + " |")
    L.append("|---|---|---|" + "---|" * len(names))
    for q in sorted(by["B0"]):
        labs = [label(by[n][q]) if q in by[n] else "-" for n in names]
        if len({x for x in labs if x != "-"}) > 1:
            L.append(f"| {q} | {'ya' if q in s_ids else ''} | {by['B0'][q]['jenis']} | "
                     + " | ".join(labs) + " |")  # fmt: skip
    L += ["\n## 6. Run yang dilakukan\n"]
    for n, m in meta.items():
        extra = ", primary_only" if m.get("primary_only") else ""
        L.append(f"- `{n}`: override `{json.dumps(m['overrides'])}`, config_hash "
                 f"`{m['config_hash'][:12]}`{extra}.")  # fmt: skip
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
        "| qid | S | jenis | "
        + " | ".join(f"{n} status | {n} nilai" for n in names[1:])
        + " | catatan |",
        "|---|---|---|" + "---|---|" * (len(names) - 1) + "---|",
    ]
    for q in sorted(by["V6"]):
        cells = " | ".join(
            f"{by[n][q]['final_status']} | {label(by[n][q])}" if q in by[n] else "- | -"
            for n in names[1:]
        )
        note = next((by[n][q]["catatan"] for n in reversed(names[1:])
                     if q in by[n] and by[n][q]["catatan"]), "")  # fmt: skip
        L.append(f"| {q} | {'ya' if q in s_ids else ''} | {by['V6'][q]['jenis']} | {cells} | "
                 f"{note or '-'} |")  # fmt: skip
    L += [
        "\n## 9. Berkas\n",
        (
            "- `eval/dev/v2_3/R.jsonl`, `V6.jsonl`, `V6r.jsonl` (termasuk keluaran LLM mentah), "
            "`V6G.jsonl`, `V6Gr.jsonl` (putusan verifikator per kalimat di "
            "`fact_check.sentence_verify`), `subset_S.json`, `logs-*`, `meta.json`."
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
    print("terpilih S:", win_s[0] if win_s else "tidak ada",
          "| terpilih 108:", win_full[0] if win_full else "tidak ada")  # fmt: skip


if __name__ == "__main__":
    main()
