"""Alat ukur laju pratinjau (--measure-preview, mica.eval.preview_meter): dev saja, angka saja."""

import json
import queue
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from test_audio_worker import VALUES, Harness, _has
from test_audio_worker import _settings as audio_settings
from test_bus import TEST_VALUES, _settings
from test_vision_color import fake_table
from test_worker_preview import CountingCamera
from tests.fakes import FakeDetector

from mica.audio.messages import Speak, SpeechDone
from mica.audio.worker import AudioWorkerConfig, AudioWorkerConfigError
from mica.eval.preview_meter import (
    SUMMARY_NAME,
    MeasureRefused,
    PreviewMeasurement,
    VisionMeter,
    check_allowed,
    label_state,
)
from mica.vision.color import DEFAULT_COLORS_FILE
from mica.vision.worker import VisionLoop, VisionWorkerConfig, WorkerConfigError
from mica.webui.server import WebUi


class StepClock:
    def __init__(self, step=0.05) -> None:
        self.t, self.step = 100.0, step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


def _primitive(value) -> bool:
    if isinstance(value, dict):
        return all(isinstance(k, str) and _primitive(v) for k, v in value.items())
    if isinstance(value, list | tuple):
        return all(_primitive(v) for v in value)
    return value is None or isinstance(value, bool | int | float | str)


def test_refused_in_prod():
    check_allowed("dev")
    with pytest.raises(MeasureRefused, match="prod"):
        check_allowed("prod")


def test_worker_configs_refuse_measure_in_prod(tmp_path):
    vision = VisionWorkerConfig.from_settings(_settings(), TEST_VALUES, models_dir=tmp_path)
    with pytest.raises(WorkerConfigError, match="pengukuran"):
        replace(vision, mode="prod", camera_preview="public", measure=True).validate()
    audio = AudioWorkerConfig.from_settings(audio_settings("prod"), VALUES)
    with pytest.raises(AudioWorkerConfigError, match="pengukuran"):
        replace(audio, measure=True).validate()


def test_run_refuses_measure_in_prod(capsys):
    from mica.webui.app import run

    s = _settings("prod")
    assert run(s, no_browser=True, measure_preview=True) == 2
    assert "prod" in capsys.readouterr().err


def test_vision_loop_reports_numbers_only(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    np.save(models / DEFAULT_COLORS_FILE.name, fake_table())
    cfg = replace(VisionWorkerConfig.from_settings(_settings(), TEST_VALUES, models_dir=models),
                  camera_preview="public", preview_fps=10.0, preview_pixel_block=16,
                  measure=True)  # fmt: skip
    inbox, outbox, preview, measure = queue.Queue(), queue.Queue(), queue.Queue(1), queue.Queue()
    loop = VisionLoop(cfg, inbox, outbox, CountingCamera(inbox, 60), FakeDetector((0.0, 99.0)),
                      clock=StepClock(), preview_out=preview, measure_out=measure)  # fmt: skip
    loop.run()
    records = [measure.get_nowait() for _ in range(measure.qsize())]
    assert records and all(r["src"] == "vision" and _primitive(r) for r in records)
    assert records[0]["capture_fps"] > 0 and records[0]["width"] > 0
    assert records[0]["render_encode_ms"]["n"] > 0 and records[0]["detect_ms"]["n"] > 0


def test_vision_loop_without_measure_flag_sends_nothing(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    np.save(models / DEFAULT_COLORS_FILE.name, fake_table())
    cfg = VisionWorkerConfig.from_settings(_settings(), TEST_VALUES, models_dir=models)
    inbox, measure = queue.Queue(), queue.Queue()
    VisionLoop(cfg, inbox, queue.Queue(), CountingCamera(inbox, 30), FakeDetector((0.0, 99.0)),
               clock=StepClock(), measure_out=measure).run()  # fmt: skip
    assert measure.empty()


def test_audio_loop_reports_synth_play_and_speak():
    from tests.unit.test_audio_worker import _cfg

    measure: queue.Queue = queue.Queue()
    with Harness(cfg=replace(_cfg(), measure=True), measure_out=measure) as h:
        h.send(Speak("s1", "Satu dua. Tiga empat.", "u1"))
        h.collect(_has(SpeechDone))
    records = [measure.get_nowait() for _ in range(measure.qsize())]
    kinds = [r["kind"] for r in records]
    assert kinds[0] == "tts_info" and kinds.count("synth") == 2 and kinds.count("play") == 2
    speak = next(r for r in records if r["kind"] == "speak")
    assert speak["n_clips"] == 2 and speak["first_audio_s"] is not None
    assert all(_primitive(r) for r in records)  # tanpa audio, hanya angka


@pytest.mark.parametrize(
    ("states", "synth", "play", "expected"),
    [
        (["IDLE", "IDLE"], 0.0, 0.0, "IDLE"),
        (["READY", "IDLE"], 0.0, 0.0, "MELAYANI-diam"),
        (["THINKING"], 0.0, 0.0, "MELAYANI-lain"),
        (["SPEAKING"], 0.3, 0.7, "TTS-menyusun"),
        (["SPEAKING"], 0.0, 1.0, "TTS-memutar"),
    ],
)
def test_label_state(states, synth, play, expected):
    assert label_state(states, synth, play) == expected


def test_measurement_writes_only_summary_json(tmp_path):
    clock = StepClock(0.125)  # pecahan biner: batas detik tepat
    sent = drawn = 0
    state = {"value": "IDLE"}
    m = PreviewMeasurement(tmp_path / "run", None, sent=lambda: sent, drawn=lambda: drawn,
                           session_state=lambda: state["value"],
                           cpu=lambda: {"utama": 5.0, "total_machine": 10.0},
                           info={"label": "uji"}, clock=clock)  # fmt: skip
    for _ in range(8):  # tepat 1 detik IDLE
        sent += 1
        drawn += 1
        m.step()
    t = clock.t
    m.receive({"src": "audio", "kind": "synth", "t0": t, "t1": t + 0.5})
    m.receive({"src": "vision", "t0": t, "t1": t + 1.0, "capture_fps": 15.0,
               "preview_put_fps": 10.0, "cap_prop_fps": 30.0, "width": 640, "height": 480,
               "read_ms": {"n": 1, "median": 60.0, "max": 60.0},
               "detect_ms": {"n": 1, "median": 80.0, "max": 80.0},
               "render_encode_ms": {"n": 1, "median": 3.0, "max": 3.0}})  # fmt: skip
    state["value"] = "SPEAKING"
    for _ in range(8):
        sent += 1
        m.step()
    path = m.stop()
    assert [p.name for p in (tmp_path / "run").iterdir()] == [SUMMARY_NAME]
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["label"] == "uji" and set(data["by_state"]) == {"IDLE", "TTS-menyusun"}
    tts = data["by_state"]["TTS-menyusun"]
    assert tts["capture_fps"]["median"] == 15.0 and tts["browser_drawn_fps"]["median"] == 0.0
    assert data["by_state"]["IDLE"]["server_sent_fps"]["median"] > 0


def test_vision_meter_window_and_reset():
    out: queue.Queue = queue.Queue()
    clock = StepClock(0.25)
    meter = VisionMeter(out, clock)
    for _ in range(5):
        meter.frame((480, 640, 3), 0.01)
        meter.rendered(0.002, True)
        meter.tick()
    rec = out.get_nowait()
    assert rec["width"] == 640 and rec["height"] == 480 and rec["preview_put_fps"] > 0
    assert rec["cap_prop_fps"] is None  # sumber tanpa get()


def test_server_counts_browser_draws_only_when_measuring():
    s = _settings()
    on = WebUi(s.ui, dev=True, measure=True)
    on.handle_message({"type": "preview_drawn", "n": 7})
    assert on.previews_drawn == 7
    off = WebUi(s.ui, dev=True)
    off.handle_message({"type": "preview_drawn", "n": 7})
    assert off.previews_drawn == 0
    assert not WebUi(s.ui, dev=False, measure=True).measure  # prod: tidak pernah aktif


def test_live_jsonl_one_line_per_second_numbers_only(tmp_path):
    folder = tmp_path / "20261021-130000"
    live = PreviewMeasurement.live_file(folder)
    assert live == tmp_path / "live-20261021-130000.jsonl"
    rows = []
    clock = StepClock(0.125)
    m = PreviewMeasurement(folder, None, sent=lambda: 0, drawn=lambda: 0,
                           session_state=lambda: "READY",
                           cpu=lambda: {"utama": 5.0, "vision": 80.0, "total_machine": 10.0},
                           clock=clock, live_path=live, on_row=rows.append)  # fmt: skip
    for _ in range(24):  # 3 detik
        m.step()
    lines = [json.loads(x) for x in live.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 3 and lines == rows
    first = lines[0]
    assert first["status"] == "MELAYANI" and first["state_detail"] == "MELAYANI-diam"
    assert first["cpu_pct"]["vision"] == 80.0 and first["cpu_pct"]["suara"] is None
    assert all(_primitive(x) for x in lines)
    assert sorted(p.name for p in tmp_path.iterdir()) == [live.name]  # summary hanya saat stop


def test_live_panel_failure_does_not_stop_measurement(tmp_path):
    def broken(_row):
        raise RuntimeError("socket putus")

    m = PreviewMeasurement(tmp_path / "x", None, sent=lambda: 0, drawn=lambda: 0,
                           session_state=lambda: "IDLE", cpu=None, clock=StepClock(0.125),
                           on_row=broken)  # fmt: skip
    for _ in range(16):
        m.step()
    assert len(m.rows) == 2


class _Socket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, data) -> None:
        self.sent.append(data)


def test_measure_panel_rows_sent_only_when_measuring():
    s = _settings()
    on, off = WebUi(s.ui, dev=True, measure=True), WebUi(s.ui, dev=True)
    for ui in (on, off):
        ui.sockets.add(_Socket())
        ui.push_measure({"status": "IDLE", "capture_fps": 15.0})
    (sock_on,), (sock_off,) = on.sockets, off.sockets
    assert json.loads(sock_on.sent[0]) == {
        "type": "measure", "row": {"status": "IDLE", "capture_fps": 15.0}}  # fmt: skip
    assert sock_off.sent == []


def test_measure_panel_markup_hidden_and_dev_only():
    from mica.webui.server import STATIC_DIR

    html = (STATIC_DIR / "index.html").read_text("utf-8")
    js = (STATIC_DIR / "app.js").read_text("utf-8")
    assert '<pre id="measure_panel" hidden></pre>' in html
    assert "if (!config || !config.dev || !config.measure) return;" in js


def test_live_line_carries_gaps_phase_and_flow_flags(tmp_path):
    folder = tmp_path / "20261021-140000"
    live = PreviewMeasurement.live_file(folder)
    m = PreviewMeasurement(folder, None, sent=lambda: 0, drawn=lambda: 0,
                           session_state=lambda: "IDLE", cpu=None, clock=StepClock(0.125),
                           live_path=live, gaps=lambda: [100.4, 350.0],
                           extra=lambda: {"phase": "idle", "view": {"greeting": False}})  # fmt: skip
    for _ in range(8):
        m.step()
    (line,) = [json.loads(x) for x in live.read_text(encoding="utf-8").splitlines()]
    assert line["browser_gaps_ms"] == [100, 350] and line["browser_gap_max_ms"] == 350
    assert line["phase"] == "idle" and line["view"] == {"greeting": False}
