"""UI web (percobaan ADR-19): serialisasi ViewModel, kesamaan event dengan PySide6, keamanan
server (Origin, 127.0.0.1, tanpa aset internet), dan siklus hidup Edge. Tanpa browser sungguhan.
"""

import json
import os
import re
import threading
import time
from datetime import date
from pathlib import Path

import httpx
import pytest
from PySide6.QtCore import Qt
from simple_websocket import Client
from simple_websocket import ConnectionError as WsRejected

from mica.config import load_settings
from mica.core.controller import DebugInfo
from mica.core.session import (
    ClearScreen,
    ShowView,
    StopTapped,
    TalkTapped,
    TextSubmitted,
    TopicTapped,
    VisitState,
)
from mica.core.types import Chunk
from mica.ui.main_window import MainWindow
from mica.ui.main_window import format_debug as qt_format_debug
from mica.ui.viewmodel import ViewModel
from mica.webui import state
from mica.webui.app import WebUiError, build_controller, serve
from mica.webui.browser import IDLE_SWITCHES, RENDERING_SWITCHES, EdgeBrowser, edge_command
from mica.webui.server import HOST, STATIC_DIR, WebUi, start_server, stop_server

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
V = VisitState
CHUNK = Chunk("03#2", "03", "Biaya Kuliah dan Syarat Masuk", "Biaya S1", date(2026, 9, 29),
              "dev", "isi", False)  # fmt: skip


def _ui(**changes):
    return load_settings(DEV_YAML).ui.model_copy(update=changes)


SCENES = [
    [ShowView(V.IDLE)],
    [ShowView(V.READY, message="Silakan bertanya")],
    [ShowView(V.LISTENING, message="mendengarkan")],
    [ShowView(V.THINKING, message="berpikir", transcript="Biaya?", send_enabled=False)],
    [ShowView(V.THINKING, message="berpikir", transcript="Biaya?", send_enabled=False),
     ShowView(V.SPEAKING, transcript="Biaya?", answer="Rp14.000.000.", sources=(CHUNK,))],
    [ShowView(V.READY, camera_ok=False, mic_ok=False)],
    [ShowView(V.THINKING, transcript="x", send_enabled=False),
     ShowView(V.SPEAKING, transcript="x", answer="y"), ClearScreen(), ShowView(V.IDLE)],
]  # fmt: skip


# --- serialisasi --------------------------------------------------------------------------


def test_view_json_answer_with_sources():
    vm = ViewModel()
    for item in SCENES[4]:
        vm.apply(item)
    v = state.view_json(vm)
    assert v["status"] == "SPEAKING" and v["status_label"] == "Berbicara" and not v["home"]
    assert v["messages"] == [
        {"role": "visitor", "who": "Kamu", "text": "Biaya?", "sources": []},
        {"role": "mica", "who": "MICA", "text": "Rp14.000.000.",
         "sources": ["Biaya Kuliah dan Syarat Masuk (berlaku 29 September 2026)"]},
    ]  # fmt: skip
    assert v["last_transcript"] == "Biaya?" and v["send_enabled"]
    json.dumps(v)  # hanya teks/angka/bool: bisa dikirim lewat WebSocket


@pytest.mark.parametrize("scene", range(len(SCENES)))
def test_view_json_matches_pyside6_render(qtbot, scene):
    window = MainWindow(_ui(), dev=False)
    qtbot.addWidget(window)
    vm = ViewModel()
    for item in SCENES[scene]:
        window.show_item(item)
        vm.apply(item)
    v = state.view_json(vm)
    assert v["status_label"] == window.status_label.text()
    assert v["camera_label"] == window.camera_label.text()
    assert v["mic_label"] == window.mic_label.text()
    assert v["send_enabled"] == window.send_button.isEnabled()
    assert v["talk_enabled"] == window.talk_button.isEnabled()
    assert v["home"] == (window.stack.currentIndex() == 0)
    assert (v["last_transcript"] is not None) == window.transcript_row.isVisibleTo(window)
    assert len(v["messages"]) == window.rendered


def test_config_json_topics_and_texts():
    c = state.config_json(_ui(suggestions={"Biaya": ("Biaya S1 berapa?",)}), dev=True)
    biaya = next(t for t in c["topics"] if t["topic"] == "Biaya")
    assert biaya == {"topic": "Biaya", "question": "Biaya S1 berapa?",
                     "suggestions": ["Biaya S1 berapa?"]}  # fmt: skip
    assert [t["topic"] for t in c["topics"]] == list(_ui().topics)
    assert "Gambar tidak disimpan" in c["texts"]["notice"] and c["dev"] is True


def test_format_debug_same_as_pyside6():
    info = DebugInfo(V.SPEAKING, 4.8, "answered", {"passed": True}, (("03#2", 0.61),),
                     "groq:openai/gpt-oss-120b", {"llm": 0.9})  # fmt: skip
    assert state.format_debug(info) == qt_format_debug(info)
    assert state.format_debug(DebugInfo(V.IDLE)) == qt_format_debug(DebugInfo(V.IDLE))


# --- event: web sama dengan PySide6 -------------------------------------------------------


def _qt_events(qtbot, ui, prepare=()):
    window = MainWindow(ui, dev=False)
    qtbot.addWidget(window)
    for item in prepare:
        window.show_item(item)
    events = []
    window.event_emitted.connect(events.append)
    return window, events


def _web_event(msg, ui, prepare=()):
    vm = ViewModel()
    for item in prepare:
        vm.apply(item)
    return state.event_from_message(msg, vm, ui)


def test_typing_same_event(qtbot):
    ui = _ui()
    window, events = _qt_events(qtbot, ui)
    qtbot.keyClicks(window.input_edit, "  Jalur masuk apa saja?  ")
    qtbot.keyClick(window.input_edit, Qt.Key.Key_Return)
    web = _web_event({"type": "text", "text": "  Jalur masuk apa saja?  "}, ui)
    assert events == [web] == [TextSubmitted("Jalur masuk apa saja?")]
    assert _web_event({"type": "text", "text": "   "}, ui) is None


def test_typing_blocked_while_thinking_in_both(qtbot):
    ui = _ui()
    busy = [ShowView(V.THINKING, transcript="x", send_enabled=False)]
    window, events = _qt_events(qtbot, ui, busy)
    qtbot.keyClicks(window.input_edit, "lagi")
    qtbot.keyClick(window.input_edit, Qt.Key.Key_Return)
    assert events == [] and _web_event({"type": "text", "text": "lagi"}, ui, busy) is None


@pytest.mark.parametrize("suggestions", [{}, {"Biaya": ("Biaya S1 berapa?", "Kelas sore?")}])
def test_topic_same_event(qtbot, suggestions):
    ui = _ui(suggestions=suggestions)
    window, events = _qt_events(qtbot, ui)
    qtbot.mouseClick(window.topic_buttons["Biaya"], Qt.MouseButton.LeftButton)
    for hint in window.suggestion_buttons:
        qtbot.mouseClick(hint, Qt.MouseButton.LeftButton)
    c = state.config_json(ui, dev=False)
    biaya = next(t for t in c["topics"] if t["topic"] == "Biaya")
    web = [_web_event({"type": "topic", "topic": "Biaya", "question": biaya["question"]}, ui)]
    web += [_web_event({"type": "topic", "topic": "Biaya", "question": q}, ui)
            for q in biaya["suggestions"]]  # fmt: skip
    assert events == web and all(isinstance(e, TopicTapped) for e in web)


def test_topic_with_unknown_question_rejected():
    ui = _ui()
    assert (
        _web_event({"type": "topic", "topic": "Biaya", "question": "pertanyaan lain"}, ui) is None
    )
    assert _web_event({"type": "topic", "topic": "Tidak ada", "question": "Tidak ada"}, ui) is None


def test_talk_and_stop_same_event(qtbot):
    ui = _ui()
    window, events = _qt_events(qtbot, ui)
    qtbot.mouseClick(window.talk_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.stop_button, Qt.MouseButton.LeftButton)
    web = [_web_event({"type": "talk"}, ui), _web_event({"type": "stop"}, ui)]
    assert events == web == [TalkTapped(), StopTapped()]
    no_mic = [ShowView(V.READY, mic_ok=False)]
    window, events = _qt_events(qtbot, ui, no_mic)
    qtbot.mouseClick(window.talk_button, Qt.MouseButton.LeftButton)
    assert events == [] and _web_event({"type": "talk"}, ui, no_mic) is None


def test_resend_edited_transcript_same_event(qtbot):
    ui = _ui()
    turn = [ShowView(V.THINKING, transcript="biaya kulia", send_enabled=False),
            ShowView(V.SPEAKING, transcript="biaya kulia", answer="x")]  # fmt: skip
    window, events = _qt_events(qtbot, ui, turn)
    window.transcript_edit.setText("biaya kuliah")
    qtbot.mouseClick(window.resend_button, Qt.MouseButton.LeftButton)
    assert events == [_web_event({"type": "resend", "text": "biaya kuliah"}, ui, turn)]


# --- statis: tanpa aset internet ----------------------------------------------------------


def test_static_files_have_no_external_urls():
    files = sorted(STATIC_DIR.iterdir())
    assert {f.name for f in files} == {"index.html", "style.css", "app.js"}
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"https?://", text, re.IGNORECASE), f.name
        assert "www." not in text and "@import" not in text and "//cdn" not in text, f.name
        assert not re.search(r"(src|href)=[\"'](?!/static/)", text), f.name


# --- server ---------------------------------------------------------------------------------


class FakeController:
    def __init__(self) -> None:
        self.events: list = []
        self.steps = 0
        self.closed = False

    def submit(self, event) -> None:
        self.events.append(event)

    def step(self) -> None:
        self.steps += 1

    def shutdown(self) -> None:
        self.closed = True


def _wait(cond, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while not cond() and time.monotonic() < deadline:
        time.sleep(0.02)
    return cond()


def _recv(ws):
    return json.loads(ws.receive(timeout=5))


def test_server_binds_localhost_only_and_rejects_foreign_origin():
    webui = WebUi(_ui(), dev=True)
    webui.controller = FakeController()
    server = start_server(webui)
    try:
        assert HOST == "127.0.0.1"
        assert server.socket.getsockname()[0] == "127.0.0.1"
        url = f"http://{HOST}:{webui.port}"
        for origin in ("http://evil.example", f"http://localhost:{webui.port}", None):
            headers = {"Origin": origin} if origin else {}
            with pytest.raises(WsRejected) as err:
                Client.connect(f"ws://{HOST}:{webui.port}/ws", headers=headers)
            assert err.value.status_code == 403
        r = httpx.get(f"{url}/")
        assert r.status_code == 200 and "<html" in r.text.lower()
        assert r.headers["Content-Security-Policy"].startswith("default-src 'self'")
        assert httpx.get(f"{url}/static/app.js").status_code == 200
        assert httpx.get(f"{url}/static/../server.py").status_code == 404
        assert not webui.sockets
    finally:
        stop_server(server)


def test_server_has_no_debugger_or_reloader():
    webui = WebUi(_ui(), dev=True)
    server = start_server(webui)
    try:
        app = server.app
        # app dilayani langsung: tidak dibungkus DebuggedApplication, debug/testing mati
        assert type(app).__name__ == "Flask" and app.debug is False and app.testing is False
        assert server.multithread and not server.multiprocess
        # reloader Werkzeug hanya ada lewat run_simple(use_reloader=True), yang menjalankan
        # proses anak dengan variabel ini; make_server tidak pernah memasangnya
        assert "WERKZEUG_RUN_MAIN" not in os.environ
        r = httpx.get(f"http://{HOST}:{webui.port}/console")
        assert r.status_code == 404 and "Werkzeug" not in r.text  # konsol debugger tidak ada
    finally:
        stop_server(server)


def test_websocket_sends_view_and_maps_events():
    webui = WebUi(_ui(), dev=True)
    controller = FakeController()
    webui.controller = controller
    server = start_server(webui)
    url = f"http://{HOST}:{webui.port}"
    try:
        ws = Client.connect(f"ws://{HOST}:{webui.port}/ws", headers={"Origin": url})
        config = _recv(ws)
        first = _recv(ws)
        assert config["type"] == "config" and first["type"] == "view"
        assert first["view"]["home"] is True
        ws.send(json.dumps({"type": "ack", "seq": first["seq"]}))
        webui.show_item(ShowView(V.THINKING, transcript="Biaya?", send_enabled=False))
        webui.flush()
        second = _recv(ws)
        assert second["view"]["messages"][0]["text"] == "Biaya?"
        assert second["seq"] == first["seq"] + 1
        ws.send(json.dumps({"type": "talk"}))
        ws.send(json.dumps({"type": "ack", "seq": second["seq"]}))
        # event browser baru sampai ke controller lewat thread poll (tick)
        assert _wait(lambda: len(webui.ack_latencies_s) == 2 and not webui.events.empty())
        assert controller.events == []
        webui.tick()
        ws.close()
    finally:
        webui.close_sockets()
        stop_server(server)
    assert controller.events == [TalkTapped()] and controller.steps == 1
    assert len(webui.ack_latencies_s) == 2 and all(x >= 0 for x in webui.ack_latencies_s)
    assert webui.first_render_at is not None


def test_broadcast_to_all_active_connections():
    webui = WebUi(_ui(), dev=False)
    webui.controller = FakeController()
    server = start_server(webui)
    url = f"http://{HOST}:{webui.port}"
    try:
        clients = [Client.connect(f"ws://{HOST}:{webui.port}/ws", headers={"Origin": url})
                   for _ in range(2)]  # fmt: skip
        for ws in clients:
            assert _recv(ws)["type"] == "config" and _recv(ws)["type"] == "view"
        assert _wait(lambda: len(webui.sockets) == 2)
        webui.show_item(ShowView(V.LISTENING, message="mendengarkan"))
        webui.tick()
        views = [_recv(ws) for ws in clients]
        assert {v["seq"] for v in views} == {webui.seq}
        assert all(v["view"]["status"] == "LISTENING" for v in views)
        clients[0].close()
        assert _wait(lambda: len(webui.sockets) == 1)
        clients[1].close()
    finally:
        webui.close_sockets()
        stop_server(server)


# --- Edge dan siklus hidup ------------------------------------------------------------------


def test_edge_command_flags(tmp_path):
    edge = Path("msedge.exe")
    url = "http://127.0.0.1:5000/"
    assert edge_command(edge, url, tmp_path, True) == [
        "msedge.exe", f"--user-data-dir={tmp_path}", "--no-first-run",
        "--disable-component-update", "--disable-component-extensions-with-background-pages",
        "--renderer-process-limit=1", "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "--kiosk", url, "--edge-kiosk-type=fullscreen"]  # fmt: skip
    assert edge_command(edge, url, tmp_path, False)[-1] == url
    plain = edge_command(edge, url, tmp_path, True, keep_rendering=False)
    assert not set(RENDERING_SWITCHES) & set(plain) and "--kiosk" in plain
    assert set(IDLE_SWITCHES) <= set(plain)  # pengurang kerja latar tidak ikut dimatikan


def test_rendering_switches_are_only_verified_ones():
    # hanya switch yang diverifikasi di content_switches.cc (lihat komentar di browser.py)
    assert RENDERING_SWITCHES == ("--disable-backgrounding-occluded-windows",
                                  "--disable-renderer-backgrounding",
                                  "--disable-background-timer-throttling")  # fmt: skip
    started = []
    browser = EdgeBrowser(True, edge=Path("msedge.exe"),
                          popen=lambda cmd: started.append(cmd) or FakeProc())  # fmt: skip
    browser.start("http://127.0.0.1:1/")
    browser.close()
    assert set(RENDERING_SWITCHES) <= set(started[0])
    # Langkah 31: hanya switch yang lolos aturan keputusan (changes.csv)
    assert IDLE_SWITCHES == ("--disable-component-update",
                             "--disable-component-extensions-with-background-pages",
                             "--renderer-process-limit=1")  # fmt: skip
    assert set(IDLE_SWITCHES) <= set(started[0])


class FakeProc:
    def __init__(self) -> None:
        self.pid = 99999999
        self.exit_code = None

    def poll(self):
        return self.exit_code


class FakeBrowser:
    def __init__(self) -> None:
        self.url = None
        self.closed = False
        self.alive_checks = 0

    def start(self, url):
        self.url = url

    def alive(self):
        self.alive_checks += 1
        return self.alive_checks < 3  # jendela "ditutup" setelah beberapa cek

    def close(self):
        self.closed = True


def test_closing_browser_stops_server_and_controller():
    webui = WebUi(_ui(), dev=False)
    controller = FakeController()
    webui.controller = controller
    browser = FakeBrowser()
    urls = []
    done = threading.Thread(target=serve, args=(webui, controller, browser),
                            kwargs={"on_ready": urls.append}, daemon=True)  # fmt: skip
    done.start()
    done.join(10)
    assert not done.is_alive()
    assert urls and urls[0].startswith("http://127.0.0.1:") and browser.url == urls[0]
    assert controller.closed and browser.closed and controller.steps > 0


def test_stopping_server_closes_browser():
    webui = WebUi(_ui(), dev=False)
    controller = FakeController()
    webui.controller = controller
    browser = FakeBrowser()
    browser.alive = lambda: True
    stop = threading.Event()
    task = threading.Thread(target=serve, args=(webui, controller, browser),
                            kwargs={"stop": stop, "on_ready": lambda url: None}, daemon=True)  # fmt: skip
    task.start()
    time.sleep(0.2)
    stop.set()
    task.join(10)
    assert not task.is_alive()
    assert browser.closed and controller.closed
    # port sudah dilepas: server benar-benar berhenti
    with pytest.raises(httpx.TransportError):  # Windows: ditolak atau timeout, tidak dilayani
        httpx.get(f"http://{HOST}:{webui.port}/", timeout=2)


def test_edge_browser_with_fake_popen(tmp_path):
    started = []

    def popen(cmd):
        started.append(cmd)
        return FakeProc()

    browser = EdgeBrowser(True, edge=Path("msedge.exe"), popen=popen)
    browser.start("http://127.0.0.1:1/")
    assert browser.alive() and "--kiosk" in started[0] and browser.profile.is_dir()
    browser.proc.exit_code = 0
    assert not browser.alive()
    browser.close()
    assert browser.profile is None


def test_fakes_refused_in_kiosk():
    s = load_settings(DEV_YAML)
    kiosk = s.model_copy(update={"app": s.app.model_copy(update={"mode": "kiosk"})})
    with pytest.raises(WebUiError, match="kiosk"):
        build_controller(kiosk, WebUi(kiosk.ui, dev=False), fake_workers=True)
    with pytest.raises(WebUiError, match="kiosk"):
        build_controller(kiosk, WebUi(kiosk.ui, dev=False), fake_pipeline=True)


def test_fake_build_in_dev_end_to_end(tmp_path):
    s = load_settings(DEV_YAML)
    s = s.model_copy(update={"logging": s.logging.model_copy(update={"dir": str(tmp_path)})})
    webui = WebUi(s.ui, dev=True)
    controller = build_controller(s, webui, fake_workers=True, fake_pipeline=True)
    controller.step()
    controller.submit(TextSubmitted("pertanyaan uji 1"))
    for _ in range(100):
        controller.step()
        if webui.vm.status == V.READY:
            break
        for f in list(controller.pending):
            f.result(timeout=5)
    controller.shutdown()
    v = state.view_json(webui.vm)
    assert [m["role"] for m in v["messages"]] == ["visitor", "mica"]
    assert v["camera_label"] == "Kamera: tidak tersedia" and webui.debug_text is not None


def test_webui_imports_no_qt_or_heavy_modules():
    import subprocess
    import sys

    code = ("import sys, mica.webui.app, mica.webui.server, mica.webui.state, mica.webui.browser\n"
            "print([m for m in ('PySide6', 'torch', 'ctranslate2', 'onnxruntime') "
            "if m in sys.modules])")  # fmt: skip
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True, cwd=ROOT)  # fmt: skip
    assert out.stdout.strip() == "[]"


def test_run_refuses_fakes_in_kiosk(capsys):
    from mica.webui.app import run

    s = load_settings(DEV_YAML)
    kiosk = s.model_copy(update={"app": s.app.model_copy(update={"mode": "kiosk"})})
    assert run(kiosk, fake_workers=True, no_browser=True) == 2
    assert "kiosk" in capsys.readouterr().err


def test_ack_reports_rendered_view_to_controller_for_k3():
    class Ctrl(FakeController):
        def __init__(self) -> None:
            super().__init__()
            self.rendered: list = []

        def view_rendered(self, status, has_transcript, t) -> None:
            self.rendered.append((status, has_transcript, t))

    webui = WebUi(_ui(), dev=False, render_clock=lambda: 42.0)
    webui.controller = Ctrl()
    webui.show_item(ShowView(V.THINKING, message="berpikir", transcript="Biaya?",
                             send_enabled=False))  # fmt: skip
    webui._send_view([])
    webui.handle_message({"type": "ack", "seq": webui.seq})
    webui.handle_message({"type": "ack", "seq": webui.seq})  # ack ganda: sekali saja
    assert webui.controller.rendered == [("THINKING", True, 42.0)]
