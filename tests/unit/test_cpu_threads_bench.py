"""scripts/cpu_threads_bench.py: kandidat, metrik, dan aturan pilih docs/CPU-THREADS.md."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("cpu_bench", ROOT / "scripts/cpu_threads_bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def test_candidates_match_preregistration():
    doc = (ROOT / "docs/CPU-THREADS.md").read_text(encoding="utf-8")
    assert bench.CANDIDATES == (None, 1, 2, 4, 7)
    assert "**null, 1, 2, 4, 7**" in doc and "< 17 ms" in doc
    assert bench.TIE_MS == 17.0 and bench.PHYSICAL_CORES == 14 and bench.BUDGET_S == 3.0


def test_load_sentences_answered_only_in_qid_order(tmp_path):
    csv = tmp_path / "per_question.csv"
    csv.write_text(
        "qid,llm_status,final_status_check_on,answer,items\n"
        "d002,answered,answered,Jawaban dua.,\n"
        "d001,answered,answered,Langkahnya:,Daftar online; Bayar\n"
        "d003,refused_gate,refused_gate,-,\n",
        encoding="utf-8",
    )
    out = bench.load_sentences(csv, n=8)
    assert len(out) == 2 and "Daftar online" in out[0] and out[1].startswith("Jawaban dua")


def _row(state, gaps, det_max=60.0, cpu=50.0):
    return {"state": state, "browser_gaps_ms": gaps, "browser_drawn_fps": 10.0,
            "detect_ms": {"median": det_max, "max": det_max},
            "cpu_pct": {"total_machine": cpu, "vision": 700.0, "suara": 0.0}}  # fmt: skip


def test_metrics_p95_on_tts_seconds_only():
    rows = [_row("IDLE", [100] * 10), _row("TTS-menyusun", [100] * 9 + [500], det_max=150)]
    speaks = [{"first_audio_s": 0.3}, {"first_audio_s": 0.5}]
    m = bench.metrics(rows, speaks, [(0.0, 0.2), (1.0, 1.4)], fps_idle=5.0)
    assert m["n_tts_seconds"] == 1 and m["gap_max_tts_ms"] == 500
    assert 300 < m["gap_p95_tts_ms"] <= 500  # p95 hanya dari detik TTS-menyusun
    assert (
        abs(m["greeting_est_s"] - (0.2 + m["detect_ms_p95"] / 1000 + m["first_audio_s_p95"])) < 1e-9
    )
    assert abs(m["synth_clip_s_median"] - 0.3) < 1e-9


def _m(gap, first=0.5, greet=1.0):
    return {"gap_p95_tts_ms": gap, "first_audio_s_p95": first, "greeting_est_s": greet}


def test_choose_smallest_gap_with_budget():
    pick, _ = bench.choose({None: _m(400), 1: _m(300, first=3.5), 2: _m(250), 4: _m(200)})
    assert pick == 4  # 1 gugur karena suara pertama > 3 s


def test_choose_tie_prefers_fewer_threads_null_counts_14():
    pick, why = bench.choose({None: _m(200), 2: _m(210), 4: _m(216.9), 7: _m(230)})
    assert pick == 2 and "seri" in why
    assert bench.choose({None: _m(200), 7: _m(205)})[0] == 7  # null = 14 thread


def test_choose_none_eligible_stays_null():
    pick, why = bench.choose({1: _m(100, greet=3.2), 2: _m(90, first=4.0)})
    assert pick is None and "null" in why


def test_bench_refused_outside_dev(monkeypatch, capsys):
    import mica.trial

    class S:
        class app:
            mode = "prod"

    monkeypatch.setattr(mica.trial, "load_trial_settings", lambda *a: (S, {}))
    assert bench.main(["--stage", "1"]) == 2
    assert "dev" in capsys.readouterr().err
