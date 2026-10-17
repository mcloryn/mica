"""E-09 eval latency: log sintetis dengan nilai diketahui (persentil, null, ketik vs suara, verdict)."""

import csv
import json

import numpy as np
import pytest

from mica.eval.__main__ import main
from mica.eval.latency import RULES, resources_summary, run_latency, summarize, turn_rows, verdict

STAGES = ("vad", "stt", "retrieval", "gate", "llm", "check", "tts_first_audio", "total",
          "first_response")  # fmt: skip


def _turn(i, mode, **timings):
    base = dict.fromkeys(STAGES)
    base.update(timings)
    return {"ts": f"2026-10-18T10:00:{i:02d}+07:00", "session_id": f"s{i}", "turn_index": 0,
            "input_mode": mode, "final_status": "answered", "timings": base}  # fmt: skip


def _voice(i, total, first=1.0, stt=1.0, tts=0.3):
    return _turn(i, "voice", vad=0.3, stt=stt, retrieval=0.2, gate=0.01, llm=1.0, check=0.05,
                 tts_first_audio=tts, total=total, first_response=first)  # fmt: skip


def _write_logs(folder, turns, greetings):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "turns-2026-10-18.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(t) + "\n" for t in turns)
    with (folder / "events-2026-10-18.jsonl").open("w", encoding="utf-8") as f:
        for g in greetings:
            f.write(json.dumps({"ts": "x", "session_id": "s", "event": "greeted",
                                "greeted_with_color": False, "latency_s": g}) + "\n")  # fmt: skip
        f.write(json.dumps({"ts": "x", "session_id": "s", "event": "person_left",
                            "greeted_with_color": False, "latency_s": None}) + "\n")  # fmt: skip


def _by(summary, measure, mode):
    return next(s for s in summary if s["measure"] == measure and s["input_mode"] == mode)


def test_p95_matches_numpy_and_nulls_counted():
    totals = [2.0, 3.0, 4.0, 5.0, 9.5]
    turns = [_voice(i, t) for i, t in enumerate(totals)]
    turns.append(_voice(9, None))  # total null: diabaikan, dihitung di n_null
    s = summarize(turn_rows(turns), [1.0, None, 2.0])
    total = _by(s, "total", "voice")
    assert total["n"] == 5 and total["n_null"] == 1
    assert total["p95"] == pytest.approx(np.percentile(totals, 95))
    assert total["p50"] == pytest.approx(4.0) and total["max"] == 9.5
    greeting = _by(s, "greeting", "event")
    assert (greeting["n"], greeting["n_null"]) == (2, 1)
    assert _by(s, "retrieval_gate", "voice")["p50"] == pytest.approx(0.21)
    assert _by(s, "check_tts", "voice")["p50"] == pytest.approx(0.35)


def test_text_turns_not_in_voice_stages():
    # baris ketik yang (keliru) membawa angka suara tetap tidak masuk tahap suara
    turns = [_voice(0, 4.0), _turn(1, "text", vad=9.0, stt=9.0, first_response=9.0, llm=2.0,
                                   total=3.0, tts_first_audio=None)]  # fmt: skip
    rows = turn_rows(turns)
    assert rows[1]["vad"] is None and rows[1]["check_tts"] is None
    s = summarize(rows, [])
    assert _by(s, "stt", "voice")["n"] == 1 and _by(s, "stt", "voice")["max"] == 1.0
    assert not any(x["input_mode"] == "text" and x["measure"] in ("vad", "stt", "first_response")
                   for x in s)  # fmt: skip
    assert _by(s, "llm", "text")["n"] == 1 and _by(s, "total", "text")["p95"] == 3.0
    assert _by(s, "total_without_audio", "text")["n"] == 1
    assert _by(s, "llm", "text")["limit_s"] is None  # syarat hanya untuk suara


def test_verdict_pass_stage_over_budget_and_fail():
    turns = [_voice(i, 6.0, stt=1.9) for i in range(10)]  # STT lewat 1,5 s, total aman
    overall, items = verdict(summarize(turn_rows(turns), [2.0] * 5))
    status = {i["measure"]: i["status"] for i in items}
    assert overall == "LULUS"
    assert status["stt"] == "lewat anggaran tahap" and status["total"] == "lulus"
    assert status["greeting"] == "lulus" and status["first_response"] == "lulus"

    slow = [_voice(i, 12.0, first=3.5) for i in range(10)]
    overall, items = verdict(summarize(turn_rows(slow), [4.0]))
    status = {i["measure"]: i["status"] for i in items}
    assert overall == "GAGAL"
    assert status["total"] == "gagal" and status["first_response"] == "gagal"
    assert status["greeting"] == "gagal"


def test_verdict_without_voice_data_is_incomplete():
    overall, items = verdict(summarize(turn_rows([_turn(0, "text", total=1.0)]), []))
    assert overall == "TIDAK LENGKAP"
    assert {i["status"] for i in items} == {"tidak ada data"}
    assert [r.limit_s for r in RULES] == [0.5, 1.5, 0.5, 4.0, 1.0, 10.0, 3.0, 3.0]


def test_resources_summary_slope_and_cpu(tmp_path):
    path = tmp_path / "resources.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "elapsed_s", "group", "n_processes", "cpu_pct", "uss_mb"])
        w.writerow(["x", -60, "utama", 1, 0, 90])
        w.writerow(["x", -60, "edge", 0, 0, 0])  # Edge belum diluncurkan
        w.writerow(["x", -60, "vision", 0, 0, 0])  # pekerja tidak pernah ada
        for i, t in enumerate([0, 1800, 3600]):
            w.writerow(["x", t, "utama", 1, [0, 10, 20][i], 100 + 10 * i])
            w.writerow(["x", t, "edge", 9, [0, 4, 6][i], 200])
            w.writerow(["x", t, "vision", 0, 0, 0])
        w.writerow(["x", 3700, "utama", 1, 5, 125])  # Edge sudah ditutup
        w.writerow(["x", 3700, "edge", 0, 0, 0])
    rows = {r["group"]: r for r in resources_summary(path)}
    assert rows["utama"]["n_samples"] == 5
    assert rows["edge"]["n_samples"] == 3 and rows["edge"]["cpu_mean_pct"] == 5.0
    assert rows["edge"]["uss_start_mb"] == 200.0  # sampel tanpa proses tidak dipakai
    assert rows["edge"]["uss_slope_mb_per_hour"] == pytest.approx(0.0)
    assert rows["vision"]["n_samples"] == 0 and rows["vision"]["uss_start_mb"] is None
    total = rows["TOTAL"]
    # hanya saat Edge ada: tanpa sampel -60 (belum diluncurkan) dan 3700 (sudah ditutup)
    assert total["n_samples"] == 3 and total["uss_start_mb"] == 300.0
    assert total["uss_end_mb"] == 320.0 and total["duration_s"] == 3600.0
    assert total["uss_slope_mb_per_hour"] == pytest.approx(20.0)


def test_run_latency_writes_outputs(tmp_path):
    _write_logs(tmp_path / "logs", [_voice(i, 5.0) for i in range(4)], [1.5, 2.0])
    run_dir, overall = run_latency(tmp_path / "logs", tmp_path / "out", "uji", tool_test=True,
                                   stamp="20261018-000000")  # fmt: skip
    assert overall == "LULUS" and run_dir.name == "uji-20261018-000000"
    for name in ("per_turn.csv", "summary.csv", "resources_summary.csv", "verdict.md",
                 "run.json"):  # fmt: skip
        assert (run_dir / name).is_file()
    info = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert info["tool_test"] is True and info["n_turns_voice"] == 4 and info["n_greetings"] == 2
    assert "Uji alat, bukan hasil E-09" in (run_dir / "verdict.md").read_text(encoding="utf-8")
    with (run_dir / "summary.csv").open(encoding="utf-8-sig") as f:
        assert "numpy.percentile" in next(csv.DictReader(f))["method"]


def test_cli_latency(tmp_path, capsys):
    _write_logs(tmp_path / "logs", [_voice(0, 11.0)], [])
    code = main(["latency", "--logs", str(tmp_path / "logs"), "--label", "cli",
                 "--out", str(tmp_path / "out"), "--from", "2026-10-18", "--to", "2026-10-18"])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0 and "keseluruhan: GAGAL" in out
    _write_logs(tmp_path / "kosong", [], [])
    code = main(["latency", "--logs", str(tmp_path / "logs"), "--label", "lain",
                 "--out", str(tmp_path / "out"), "--from", "2026-10-19"])  # fmt: skip
    assert code == 0 and "TIDAK LENGKAP" in capsys.readouterr().out
