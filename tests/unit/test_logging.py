import csv
import dataclasses
import json
from datetime import UTC, date, datetime

import pytest

from mica import logs
from mica.core.logging import EventRecord, InteractionLog, TurnRecord, export
from mica.core.types import ScrubbedText

FORBIDDEN = ("image", "frame", "audio", "color_name", "ip", "embedding")


def _local(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour).astimezone()


def _turn(day: date = date(2026, 10, 15), question=None, **overrides) -> TurnRecord:
    fields = {
        "ts": _local(day),
        "session_id": "s-1",
        "turn_index": 0,
        "input_mode": "text",
        "question": ScrubbedText("Berapa biaya kuliah?") if question is None else question,
        "retrieved": ({"chunk_id": "brosur#1", "score": 0.8, "ranks": {"bm25": 1}},),
        "gate": {"decision": "pass", "top_score": 0.8},
        "llm_provider": "groq:model-a",
        "llm_status": "answered",
        "final_status": "answered",
        "answer": "Biaya pendaftaran Rp300.000.",
        "sources": ("brosur#1",),
        "fact_check": {"checked": ["300.000"], "failed": []},
        "timings": {"retrieval": 0.1, "llm": 1.2, "total": 1.5},
        "kb_id": "dev-2026-10-15",
        "config_hash": "abc",
        "app_version": "0.1.0",
    }
    fields.update(overrides)
    return TurnRecord(**fields)


def _event(day: date = date(2026, 10, 15)) -> EventRecord:
    return EventRecord(
        ts=_local(day), session_id="s-1", event="greeted", greeted_with_color=True, latency_s=2.1
    )


def _read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_turn_written_as_json_to_dated_file(tmp_path):
    log = InteractionLog(tmp_path)
    log.log_turn(_turn(date(2026, 10, 15)))
    log.log_turn(_turn(date(2026, 10, 16), turn_index=1))
    first = _read_lines(tmp_path / "turns-2026-10-15.jsonl")
    second = _read_lines(tmp_path / "turns-2026-10-16.jsonl")
    assert len(first) == 1 and len(second) == 1
    assert first[0]["session_id"] == "s-1"
    assert second[0]["turn_index"] == 1


def test_event_written_as_json_to_dated_file(tmp_path):
    InteractionLog(tmp_path).log_event(_event(date(2026, 10, 15)))
    rows = _read_lines(tmp_path / "events-2026-10-15.jsonl")
    assert rows[0]["event"] == "greeted"
    assert rows[0]["greeted_with_color"] is True


def test_ts_is_iso8601_with_timezone(tmp_path):
    InteractionLog(tmp_path).log_turn(_turn())
    ts = _read_lines(tmp_path / "turns-2026-10-15.jsonl")[0]["ts"]
    assert datetime.fromisoformat(ts).tzinfo is not None


def test_naive_ts_rejected():
    with pytest.raises(ValueError):
        _turn(ts=datetime(2026, 10, 15, 12))


def test_file_date_follows_local_date(tmp_path):
    # ts dalam UTC; nama file harus memakai tanggal lokal hasil konversi
    ts = datetime(2026, 10, 15, 23, 30, tzinfo=UTC)
    InteractionLog(tmp_path).log_turn(_turn(ts=ts))
    expected = ts.astimezone().date().isoformat()
    assert (tmp_path / f"turns-{expected}.jsonl").exists()


def test_plain_str_question_rejected(tmp_path):
    log = InteractionLog(tmp_path)
    with pytest.raises(TypeError):
        log.log_turn(_turn(question="Berapa biaya kuliah?"))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("record_cls", [TurnRecord, EventRecord])
def test_no_forbidden_fields(record_cls):
    for f in dataclasses.fields(record_cls):
        for word in FORBIDDEN:
            assert word not in f.name, f"{record_cls.__name__}.{f.name}"


def test_record_field_types():
    hints = {f.name: f.type for f in dataclasses.fields(TurnRecord)}
    assert hints["question"] in (ScrubbedText, "ScrubbedText")
    event_hints = {f.name: f.type for f in dataclasses.fields(EventRecord)}
    assert event_hints["greeted_with_color"] in (bool, "bool")


def test_records_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _turn().answer = "lain"
    with pytest.raises(dataclasses.FrozenInstanceError):
        _event().greeted_with_color = False


def test_indonesian_text_not_escaped(tmp_path):
    question = ScrubbedText("Apa syarat beasiswa “prestasi” untuk prodi Sistem Informasi—2026?")
    InteractionLog(tmp_path).log_turn(_turn(question=question, answer="Nilai rata-rata ≥ 85."))
    raw = (tmp_path / "turns-2026-10-15.jsonl").read_text(encoding="utf-8")
    assert "“prestasi”" in raw and "≥ 85" in raw
    assert r"\u" not in raw


def _write_days(tmp_path, days):
    log = InteractionLog(tmp_path)
    for i, day in enumerate(days):
        log.log_turn(_turn(day, turn_index=i))


def test_export_filters_by_date_and_splits_timings(tmp_path):
    days = [date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 17)]
    _write_days(tmp_path, days)
    out = tmp_path / "out" / "turns.csv"
    count = export(tmp_path, date(2026, 10, 15), date(2026, 10, 16), out)
    assert count == 2
    with out.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["turn_index"] for r in rows] == ["1", "2"]
    assert "timings" not in rows[0]
    assert rows[0]["timings.llm"] == "1.2"
    assert rows[0]["timings.total"] == "1.5"
    assert json.loads(rows[0]["gate"]) == {"decision": "pass", "top_score": 0.8}
    assert json.loads(rows[0]["sources"]) == ["brosur#1"]


def test_export_keeps_indonesian_text(tmp_path):
    question = ScrubbedText("Bagaimana jalur “undangan”?")
    InteractionLog(tmp_path).log_turn(_turn(question=question))
    out = tmp_path / "t.csv"
    export(tmp_path, date(2026, 10, 15), date(2026, 10, 15), out)
    text = out.read_text(encoding="utf-8-sig")
    assert "“undangan”" in text and r"\u" not in text


def test_export_rejects_reversed_range(tmp_path):
    with pytest.raises(ValueError):
        export(tmp_path, date(2026, 10, 16), date(2026, 10, 15), tmp_path / "x.csv")


def test_cli_export_events(tmp_path, capsys):
    InteractionLog(tmp_path).log_event(_event())
    out = tmp_path / "events.csv"
    code = logs.main(
        [
            "export", "--from", "2026-10-15", "--to", "2026-10-15",
            "--out", str(out), "--kind", "events", "--dir", str(tmp_path),
        ]
    )
    assert code == 0
    with out.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["event"] == "greeted"
    assert "1 baris events" in capsys.readouterr().out


def test_cli_rejects_bad_date(tmp_path):
    with pytest.raises(SystemExit):
        logs.main(["export", "--from", "15-10-2026", "--to", "2026-10-15", "--out", "x.csv"])


def test_export_csv_has_utf8_bom_for_excel(tmp_path):
    InteractionLog(tmp_path).log_turn(_turn())
    out = tmp_path / "t.csv"
    export(tmp_path, date(2026, 10, 15), date(2026, 10, 15), out)
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
