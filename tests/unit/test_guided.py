"""Uji terpandu (--guided-test, mica.webui.guided): dev saja, petunjuk per langkah, menutup sendiri."""

import json
import threading
import time
from itertools import pairwise

import pytest
from test_webui import DEV_YAML, FakeBrowser, FakeController, _ui

from mica.config import load_settings
from mica.webui.app import serve
from mica.webui.guided import (
    PHASES,
    GuidedRefused,
    GuidedTest,
    Phase,
    check_allowed,
    guide_payload,
    phase_at,
    total_s,
)
from mica.webui.server import STATIC_DIR, WebUi


def _prod():
    s = load_settings(DEV_YAML)
    return s.model_copy(update={"app": s.app.model_copy(update={"mode": "prod"})})


def test_refused_in_prod(capsys):
    from mica.webui.app import run

    check_allowed("dev")
    with pytest.raises(GuidedRefused, match="prod"):
        check_allowed("prod")
    assert run(_prod(), no_browser=True, guided_test=True) == 2
    assert "prod" in capsys.readouterr().err
    assert not WebUi(_ui(), dev=False, guided=True).guided


def test_scenario_five_phases_five_minutes():
    assert [p.key for p in PHASES] == ["idle", "disapa", "ketik", "suara", "pergi"]
    assert total_s() == 300
    assert all(a.end_s == b.start_s for a, b in pairwise(PHASES))
    assert phase_at(0).key == "idle" and phase_at(45).key == "disapa"
    assert phase_at(299.9).key == "pergi" and phase_at(300) is None


def test_payload_countdown_and_next_step():
    g = guide_payload(30.2)
    assert (g["step"], g["steps"], g["phase"], g["remaining_s"]) == (1, 5, "idle", 15)
    assert g["next"] == PHASES[1].text and not g["done"]
    assert guide_payload(None)["step"] == 0  # halaman belum tampil
    assert guide_payload(280)["next"] is None
    assert guide_payload(300)["done"]


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_runner_waits_for_page_then_finishes_after_scenario():
    clock, started, pushed = Clock(), {"at": None}, []
    stop = threading.Event()
    g = GuidedTest(lambda: started["at"], pushed.append, stop, clock=clock)
    assert not g.step() and g.phase() is None and pushed[-1]["step"] == 0
    started["at"] = 10.0
    clock.t = 10.0 + 100
    assert not g.step() and g.phase() == "ketik"
    clock.t = 10.0 + 300
    assert not g.step() and pushed[-1]["done"] and g.phase() == "selesai"  # pesan selesai dulu
    clock.t = 10.0 + 300 + 3
    assert g.step() and g.finished


def test_guided_scenario_end_closes_program():
    phases = (Phase("a", 0, 0.2, "langkah satu"), Phase("b", 0.2, 0.4, "langkah dua"))
    webui = WebUi(_ui(), dev=True, guided=True)
    controller = FakeController()
    webui.controller = controller
    browser = FakeBrowser()
    browser.alive = lambda: True  # hanya skenario yang boleh menutup program
    stop = threading.Event()
    start = time.perf_counter()
    g = GuidedTest(lambda: start, webui.push_guide, stop, phases=phases, close_delay_s=0.1)
    g.start()
    task = threading.Thread(target=serve, args=(webui, controller, browser),
                            kwargs={"stop": stop, "on_ready": lambda _u: None}, daemon=True)  # fmt: skip
    task.start()
    task.join(10)
    assert not task.is_alive() and g.finished
    assert controller.closed and browser.closed
    assert webui.last_guide is not None and webui.last_guide["done"]


class _Socket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, data) -> None:
        self.sent.append(data)


def test_guide_sent_only_when_guided_and_flow_flags_have_no_text():
    on, off = WebUi(_ui(), dev=True, guided=True), WebUi(_ui(), dev=True)
    for ui in (on, off):
        ui.sockets.add(_Socket())
        ui.push_guide(guide_payload(5))
    (s_on,), (s_off,) = on.sockets, off.sockets
    assert json.loads(s_on.sent[0])["phase"] == "idle" and s_off.sent == []
    flags = on.flow_flags()
    assert set(flags) == {"status", "greeting", "target", "transcript", "n_visitor", "n_mica",
                          "n_with_sources"}  # fmt: skip
    assert all(isinstance(v, bool | int) for k, v in flags.items() if k != "status")


def test_browser_gaps_collected_only_when_measuring():
    on = WebUi(_ui(), dev=True, measure=True)
    on.handle_message({"type": "preview_drawn", "n": 1, "gap_ms": None})
    on.handle_message({"type": "preview_drawn", "n": 1, "gap_ms": 120})
    assert on.previews_drawn == 2 and on.take_gaps() == [120.0] and on.take_gaps() == []


def test_guide_box_markup_dev_only():
    html = (STATIC_DIR / "index.html").read_text("utf-8")
    js = (STATIC_DIR / "app.js").read_text("utf-8")
    assert '<pre id="guide_box" hidden></pre>' in html
    assert "if (!config || !config.dev || !config.guided) return;" in js
