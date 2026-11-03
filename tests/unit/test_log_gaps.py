"""PROD-5: python -m mica.logs gaps (jeda antar-giliran, validasi session.idle_reset_s).

Log sintetis ditulis lewat InteractionLog yang sama dengan aplikasi. Angka di sini data uji.
"""

import csv
from datetime import date, datetime, timedelta

import pytest

from mica import logs
from mica.core import gaps
from mica.core.logging import InteractionLog, TurnRecord
from mica.core.types import ScrubbedText

DAY = date(2026, 11, 3)
BASE = datetime(2026, 11, 3, 10, 0, 0).astimezone()
SECRET = "Nomor saya [TELEPON], berapa biaya kuliah?"


def _turn(session_id, turn_index, ts):
    return TurnRecord(
        ts=ts, session_id=session_id, turn_index=turn_index, input_mode="text",
        question=ScrubbedText(SECRET), retrieved=(), gate={}, llm_provider=None, llm_status=None,
        final_status="answered", answer="Biaya kuliah Rp15.000.000.", sources=(), fact_check={},
        timings={"total": 1.0}, kb_id="kb", config_hash="abc", app_version="0.1.0",
    )  # fmt: skip


def _write(log_dir, plan):
    """plan: [(session_id, detik sejak BASE)]; giliran ditulis tidak berurutan."""
    log = InteractionLog(log_dir)
    counters: dict[str, int] = {}
    for session, offset in plan:
        index = counters.get(session, 0)
        counters[session] = index + 1
        log.log_turn(_turn(session, index, BASE + timedelta(seconds=offset)))


PLAN = [("s-a", 0), ("s-a", 30), ("s-b", 5), ("s-a", 100), ("s-c", 50), ("s-b", 205)]


def test_gaps_per_session_sorted_by_time(tmp_path):
    _write(tmp_path, PLAN)
    sessions = gaps.session_gaps(gaps.read_turn_times(tmp_path, DAY, DAY))
    by_id = {s.session_id: s for s in sessions}
    assert by_id["s-a"].gaps_s == (30.0, 70.0)
    assert by_id["s-b"].gaps_s == (200.0,)
    assert by_id["s-c"].n_turns == 1 and by_id["s-c"].gaps_s == ()


def test_summary_counts_gaps_over_idle_reset(tmp_path):
    _write(tmp_path, PLAN)
    sessions = gaps.session_gaps(gaps.read_turn_times(tmp_path, DAY, DAY))
    s = gaps.summarize(sessions, 120.0)
    assert (s.n_sessions, s.n_sessions_with_gaps, s.n_gaps) == (3, 2, 3)
    assert s.p50_s == 70.0 and s.max_s == 200.0
    assert s.p95_s == pytest.approx(187.0)  # interpolasi linear 70..200
    assert s.n_over_idle == 1
    assert gaps.summarize(sessions).n_over_idle is None


def test_no_gaps_reported_plainly(tmp_path):
    _write(tmp_path, [("s-a", 0), ("s-b", 10)])
    sessions = gaps.session_gaps(gaps.read_turn_times(tmp_path, DAY, DAY))
    text = gaps.format_report(sessions, gaps.summarize(sessions, 120.0))
    assert "tidak bisa dihitung" in text


def test_date_range_and_reversed_range(tmp_path):
    _write(tmp_path, PLAN)
    assert gaps.read_turn_times(tmp_path, DAY + timedelta(days=1), DAY + timedelta(days=2)) == {}
    with pytest.raises(ValueError, match="--from"):
        gaps.read_turn_times(tmp_path, DAY, DAY - timedelta(days=1))


def test_cli_gaps_prints_only_times(tmp_path, capsys):
    _write(tmp_path, PLAN)
    out_csv = tmp_path / "gaps.csv"
    code = logs.main(["gaps", "--from", "2026-11-03", "--to", "2026-11-03", "--dir",
                      str(tmp_path), "--idle-reset-s", "120", "--out", str(out_csv)])  # fmt: skip
    assert code == 0
    out = capsys.readouterr().out
    assert "Jeda > idle_reset_s (120 s): 1" in out and "maks 200.0" in out
    assert "biaya" not in out and "TELEPON" not in out
    content = out_csv.read_text(encoding="utf-8-sig")
    assert "biaya" not in content and "TELEPON" not in content
    rows = list(csv.DictReader(content.splitlines()))
    assert [r["session_id"] for r in rows] == ["s-a", "s-b", "s-c"]
    assert rows[0]["maks_s"] == "70.000"


def test_cli_gaps_rejects_non_turn_log(tmp_path, capsys):
    (tmp_path / "turns-2026-11-03.jsonl").write_text('{"x": 1}\n', encoding="utf-8")
    code = logs.main(["gaps", "--from", "2026-11-03", "--to", "2026-11-03", "--dir",
                      str(tmp_path)])  # fmt: skip
    assert code == 2 and "bukan log giliran" in capsys.readouterr().err
