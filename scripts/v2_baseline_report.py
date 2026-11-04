"""V2-2b: gabungkan run baseline + kunci + penilaian manual -> penilaian.csv dan laporan.

Pemakaian: python scripts/v2_baseline_report.py
"""

from __future__ import annotations

import csv
import importlib.util
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "eval/dev/v2_baseline"
DOC = ROOT / "docs/V2-BASELINE-DEV.md"
REFUSED = {"refused_gate", "refused_llm", "refused_check", "unavailable"}
KB_HAS = {"ada", "sebagian"}


def load_manual() -> dict:
    spec = importlib.util.spec_from_file_location("nilai_manual", BASE / "nilai_manual.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.NILAI


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def premis_can_fix(key: dict) -> bool:
    return not key["jawaban_acuan"].startswith("Koreksi: tidak_ada")


def grade(run: dict, key: dict, manual: dict) -> dict:
    status = run["final_status"]
    top5 = [x["chunk_id"] for x in run["top5"]]
    gold_in5 = any(g in top5 for g in run["gold"])
    out = {"klaim": "", "golongan": "", "penyebab": "", "catatan": ""}
    m = manual.get((run["set"], run["qid"]))
    if status in REFUSED or (m and m[0] in ("tolak_tepat", "tolak_keliru")):
        out["keputusan"] = "menolak"
        should = key["jenis"] in KB_HAS or (key["jenis"] == "premis_salah" and premis_can_fix(key))
        if not should:
            out["nilai"] = "tolak_tepat"
        else:
            out["nilai"] = "tolak_keliru"
            if status == "refused_gate":
                out["penyebab"] = "gerbang_1"
            elif status == "refused_check":
                out["penyebab"] = "gerbang_3"
            elif not gold_in5:
                out["penyebab"] = "gold_tidak_top5"
            else:
                out["penyebab"] = "llm_not_found"
        if m:
            out["catatan"] = m[3]
        if status == "refused_check":
            out["catatan"] = (
                out["catatan"] + f" unsupported={run['fact_check'].get('unsupported')}"
            ).strip()
        return out
    out["keputusan"] = "menjawab"
    if m is None:
        raise SystemExit(f"belum dinilai: {run['set']} {run['qid']}")
    out["nilai"], out["klaim"], out["golongan"], out["catatan"] = m
    return out


def summarize(rows: list[dict]) -> dict:
    ans = [r for r in rows if r["keputusan"] == "menjawab"]
    ref = [r for r in rows if r["keputusan"] == "menolak"]
    ok = sum(r["nilai"] in ("benar", "tidak_lengkap") for r in ans)
    lo, hi = wilson(ok, len(ans))
    gold_items = [r for r in rows if r["gold"] and r["jenis"] in KB_HAS]
    return {
        "n": len(rows),
        "dijawab": len(ans),
        "ditolak": len(ref),
        "benar": sum(r["nilai"] == "benar" for r in ans),
        "tidak_lengkap": sum(r["nilai"] == "tidak_lengkap" for r in ans),
        "halusinasi": sum(r["nilai"] == "halusinasi" for r in ans),
        "halu_A": sum(r["golongan"] == "A" for r in ans),
        "halu_B": sum(r["golongan"] == "B" for r in ans),
        "tidak_halu": ok,
        "tidak_halu_pct": ok / len(ans) if ans else float("nan"),
        "wilson95": (lo, hi),
        "tolak_tepat": sum(r["nilai"] == "tolak_tepat" for r in ref),
        "tolak_keliru": sum(r["nilai"] == "tolak_keliru" for r in ref),
        "penyebab": Counter(r["penyebab"] for r in ref if r["penyebab"]),
        "n_gold": len(gold_items),
        "recall5": sum(r["gold_in5"] for r in gold_items),
        "recall20": sum(r["gold_rank"] is not None and r["gold_rank"] <= 20 for r in gold_items),
    }


def fmt_sum(s: dict) -> list[str]:
    lo, hi = s["wilson95"]
    p = s["penyebab"]
    return [
        f"- Soal: {s['n']}; dijawab {s['dijawab']}, ditolak {s['ditolak']}.",
        (
            f"- Tidak halu = (benar {s['benar']} + tidak lengkap {s['tidak_lengkap']}) / dijawab "
            f"{s['dijawab']} = {s['tidak_halu']}/{s['dijawab']} = **{100 * s['tidak_halu_pct']:.1f}%** "
            f"(Wilson 95% {100 * lo:.1f}-{100 * hi:.1f}%)."
        ),
        f"- Halusinasi: {s['halusinasi']} (A {s['halu_A']}, B {s['halu_B']}).",
        (
            f"- Tolak tepat: {s['tolak_tepat']}. Tolak keliru: {s['tolak_keliru']} (gerbang 1 "
            f"{p['gerbang_1']}, gold tidak top-5 {p['gold_tidak_top5']}, gold di top-5 tapi "
            f"not_found {p['llm_not_found']}, gerbang 3 {p['gerbang_3']})."
        ),
        (
            f"- Recall chunk gold (soal ada/sebagian, n={s['n_gold']}): @5 {s['recall5']}/{s['n_gold']} "
            f"= {s['recall5'] / s['n_gold']:.2f}; @20 {s['recall20']}/{s['n_gold']} = "
            f"{s['recall20'] / s['n_gold']:.2f}."
        ),
    ]


def main() -> None:
    manual = load_manual()
    runs = [json.loads(x) for x in (BASE / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    meta = json.loads((BASE / "meta.json").read_text(encoding="utf-8"))
    keys = {}
    for name, s in (("dev_v2_kunci.csv", "v2"), ("dev_lama_kunci_v5.csv", "lama")):
        with (ROOT / "data/eval" / name).open(encoding="utf-8") as f:
            for k in csv.DictReader(f, delimiter=";"):
                keys[(s, k["qid"])] = k
    rows = []
    for r in runs:
        key = keys[(r["set"], r["qid"])]
        g = grade(r, key, manual)
        top5 = [x["chunk_id"] for x in r["top5"]]
        rows.append({**r, **g, "gold_in5": any(c in top5 for c in r["gold"])})
    with (BASE / "penilaian.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["set", "qid", "jenis", "final_status", "dense_at_1", "gold_rank", "gold_in5",
                    "keputusan", "nilai", "golongan", "klaim_halusinasi", "penyebab_tolak",
                    "catatan"])  # fmt: skip
        for r in rows:
            w.writerow([r["set"], r["qid"], r["jenis"], r["final_status"],
                        f"{r['dense_at_1']:.3f}", r["gold_rank"] or "", r["gold_in5"],
                        r["keputusan"], r["nilai"], r["golongan"], r["klaim"], r["penyebab"],
                        r["catatan"]])  # fmt: skip

    sums = {s: summarize([r for r in rows if r["set"] == s]) for s in ("v2", "lama")}
    (BASE / "summary.json").write_text(
        json.dumps({**meta, "rekap": sums}, ensure_ascii=False, indent=2, default=list) + "\n",
        encoding="utf-8",
    )
    L = [
        "# V2-2: Baseline sistem v5 di set dev v2 (sebelum perbaikan)\n",
        (
            "Penilaian oleh Claude di set dev (akan diungkap di Bab 3), **bukan penilaian resmi**. "
            "Patokan kebenaran = KB `official-2026-10-24-v5`. Kunci di-commit sebelum sistem "
            "dijalankan (commit `v2-2a`). Tidak ada perubahan `src/` atau `config/`; set uji Tahap 1 "
            "tidak dibaca.\n"
        ),
        "## 1. Konfigurasi\n",
        (
            f"- KB `{meta['kb_id']}`, config_hash `{meta['config_hash'][:12]}` (`config/prod.yaml`), "
            f"top_k {meta['top_k']}, gerbang dense@1 >= {meta['gate_threshold']}, prompt "
            f"`{meta['prompt_variant']}`, rantai {', '.join(meta['llm_chain'])}, followup_mode "
            f"`{meta['followup_mode']}`."
        ),
        (
            "- Jeda 20 detik per panggilan; tidak ada HTTP 429 (semua soal selesai pada percobaan "
            "pertama). Semua jawaban dari gpt-oss-120b."
        ),
        (
            "- Set v2: 108 soal (`data/eval/dev-v2-soal.csv`, kunci `data/eval/dev_v2_kunci.csv`). "
            "Set lama: 38 soal `data/eval/questions.jsonl` yang bukan luar_topik (kunci "
            "`data/eval/dev_lama_kunci_v5.csv`); followup d032/d033 memakai riwayat d001/d011.\n"
        ),
        "## 2. Aturan penilaian\n",
        (
            "- Menolak (refused_gate/refused_llm/refused_check): KB memuat jawaban (jenis ada/sebagian, "
            "atau premis_salah yang bisa dikoreksi KB) -> tolak keliru; selain itu -> tolak tepat."
        ),
        (
            "- Penyebab tolak keliru: gerbang 1 (dense@1 < 0,50) / gold tidak masuk top-5 / gold di "
            "top-5 tapi LLM not_found / gerbang 3 (cek angka)."
        ),
        (
            "- Menjawab (answered/false_premise): setiap klaim dicek ke KB. Ada klaim di luar KB -> "
            "halusinasi (A = pengetahuan umum/penalaran tambahan, B = detail spesifik salah). Semua "
            "klaim benar tapi bagian kunci yang menjawab hilang -> tidak lengkap. Selain itu benar. "
            "Kalimat sopan/arahan ke staf bukan klaim."
        ),
        (
            "- v2d-068 berstatus false_premise tetapi isinya hanya menyatakan info tidak ada; "
            "dinilai sebagai penolakan (tolak tepat)."
        ),
        (
            "- Recall dihitung untuk soal jenis ada/sebagian dengan chunk gold; top-5 = chunk yang "
            "benar-benar dikirim pipeline, @20 dari peringkat retrieval (kolam 50).\n"
        ),
        "## 3. Rekap set v2\n",
        *fmt_sum(sums["v2"]),
        "\n## 4. Rekap set lama (label v5)\n",
        *fmt_sum(sums["lama"]),
        "\n## 5. Per soal\n",
        (
            "| set | qid | jenis | status | dense@1 | rank gold | gold@5 | nilai | gol. | "
            "penyebab | catatan |\n|---|---|---|---|---|---|---|---|---|---|---|"
        ),
    ]
    for r in rows:
        note = r["catatan"]
        if r["klaim"]:
            note = f'klaim: "{r["klaim"]}". {note}'.strip()
        L.append(
            f"| {r['set']} | {r['qid']} | {r['jenis']} | {r['final_status']} | "
            f"{r['dense_at_1']:.3f} | {r['gold_rank'] or '-'} | {'ya' if r['gold_in5'] else '-'} | "
            f"{r['nilai']} | {r['golongan'] or '-'} | {r['penyebab'] or '-'} | {note or '-'} |"
        )
    L += [
        "\n## 6. Berkas\n",
        (
            "- `eval/dev/v2_baseline/runs.jsonl`: per soal (jawaban, status, gerbang, top-5 + skor "
            "RRF + peringkat, dense@1, top-20, sitasi, fact_check)."
        ),
        (
            "- `eval/dev/v2_baseline/penilaian.csv`: nilai per soal; `nilai_manual.py`: penilaian "
            "klaim untuk jawaban yang tidak ditolak."
        ),
        (
            "- `eval/dev/v2_baseline/summary.json`, `meta.json`, `logs/` (turn log M-11), "
            "`run_stdout.txt`."
        ),
        (
            "- Skrip: `scripts/v2_baseline_dev.py` (run, bisa dilanjutkan), "
            "`scripts/v2_baseline_report.py` (penilaian dan laporan)."
        ),
    ]
    DOC.write_text("\n".join(L) + "\n", encoding="utf-8")
    for s, v in sums.items():
        print(s, {k: v[k] for k in v if k != "penyebab"}, dict(v["penyebab"]))


if __name__ == "__main__":
    main()
