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
from mica.webui.browser import (
    IDLE_SWITCHES,
    PREVIEW_SWITCHES,
    RENDERING_SWITCHES,
    EdgeBrowser,
    edge_command,
)
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
        {"role": "visitor", "kind": "visitor", "who": "Kamu", "text": "Biaya?", "sources": [],
         "follow_up": None, "items": []},
        {"role": "mica", "kind": "answer", "who": "MICA", "text": "Rp14.000.000.",
         "sources": ["Biaya Kuliah dan Syarat Masuk (berlaku 29 September 2026)"],
         "follow_up": None, "items": []},
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
    ui = _ui(suggestions={"Biaya": ("Biaya S1 berapa?",)})
    c = state.config_json(ui, dev=True)
    biaya = next(t for t in c["topics"] if t["topic"] == "Biaya")
    # Langkah 53: question = ui.topics[].question (bukan saran pertama atau nama topik)
    assert biaya == {"topic": "Biaya", "question": ui.topic_question("Biaya"),
                     "suggestions": ["Biaya S1 berapa?"]}  # fmt: skip
    assert biaya["question"] != "Biaya" and biaya["question"].endswith("?")
    assert [t["topic"] for t in c["topics"]] == list(_ui().topic_labels)
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


PAGE_FILES = {"index.html", "tokens.css", "style.css", "app.js", "answer_format.js"}


def test_static_files_have_no_external_urls():
    files = sorted(f for f in STATIC_DIR.iterdir() if f.is_file())
    assert {f.name for f in files} == PAGE_FILES
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"https?://", text, re.IGNORECASE), f.name
        assert "www." not in text and "@import" not in text and "//cdn" not in text, f.name
        assert not re.search(r"(src|href)=[\"'](?!/static/)", text), f.name
        for url in re.findall(r"url\(\s*[\"']?([^\"')]+)", text):
            assert url.startswith("/static/fonts/"), (f.name, url)


def test_font_is_local_atkinson_with_license():
    # Langkah 37c: Atkinson Hyperlegible (Braille Institute), SIL OFL 1.1, regular + bold
    fonts = {f.name for f in (STATIC_DIR / "fonts").iterdir()}
    assert fonts == {"AtkinsonHyperlegible-Regular.woff2", "AtkinsonHyperlegible-Bold.woff2",
                     "OFL.txt"}  # fmt: skip
    for name in fonts - {"OFL.txt"}:
        assert (STATIC_DIR / "fonts" / name).read_bytes()[:4] == b"wOF2"
    ofl = (STATIC_DIR / "fonts" / "OFL.txt").read_text("utf-8")
    assert "Braille Institute" in ofl and "SIL Open Font License, Version 1.1" in ofl
    tokens = (STATIC_DIR / "tokens.css").read_text("utf-8")
    assert '--font: "Atkinson Hyperlegible", "Segoe UI", system-ui' in tokens
    weights = set(
        re.findall(r"font-weight:\s*(\d+)", tokens + (STATIC_DIR / "style.css").read_text("utf-8"))
    )
    assert weights == {"400", "700"}  # berat 400 dan 700 saja


def _css_rules(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", text)


def test_only_animation_is_swatch_fade_and_reduced_motion():
    css = (STATIC_DIR / "style.css").read_text("utf-8")
    animated = [sel.strip() for sel, body in _css_rules(css)
                if re.search(r"(^|;)\s*animation\s*:", body) and "animation: none" not in body]  # fmt: skip
    assert animated == [".swatch-big"]
    assert "animation: fade-in 200ms" in css
    assert "transition:" not in re.sub(r"transition: none !important", "", css)
    assert "prefers-reduced-motion: reduce" in css
    js = (STATIC_DIR / "app.js").read_text("utf-8")
    assert "setInterval" not in js and "setTimeout" not in js  # tanpa timer saat diam


def test_touch_targets_at_least_44px():
    tokens = (STATIC_DIR / "tokens.css").read_text("utf-8")
    assert "--touch-min: 44px;" in tokens
    css = (STATIC_DIR / "style.css").read_text("utf-8")
    for sel in (".btn", "#debug_dock summary", "#transcript_edit, #input"):
        rule = next(b for s_, b in _css_rules(css) if s_.strip() == sel)
        assert "min-height: var(--touch-min)" in rule, sel
    tile = next(b for s_, b in _css_rules(css) if s_.strip() == ".topic-tile")
    assert "min-height: 64px" in tile
    html = (STATIC_DIR / "index.html").read_text("utf-8")
    assert '<button id="talk_button" type="button" class="btn btn-primary btn-icon">' in html
    assert '<button id="send_button" type="button" class="btn">' in html


def test_conventional_style_no_ai_effects():
    tokens = (STATIC_DIR / "tokens.css").read_text("utf-8")
    css = re.sub(r"/\*.*?\*/", "", (STATIC_DIR / "style.css").read_text("utf-8"), flags=re.DOTALL)
    for banned in ("gradient", "blur(", "backdrop-filter", "box-shadow", "text-shadow", "filter:",
                   "text-transform", "uppercase", "monospace"):  # fmt: skip
        assert banned not in css and banned not in tokens, banned
    radii = [int(v) for v in re.findall(r"--radius[\w-]*:\s*(\d+)px", tokens)]
    assert radii and max(radii) <= 10 and "--radius-bubble: 10px;" in tokens
    for value in re.findall(r"border-radius:\s*([^;]+);", css):
        assert value.strip() in ("var(--radius)", "var(--radius-m)", "var(--radius-bubble)"), value
    spaces = sorted(int(v) for v in re.findall(r"--space-\d:\s*(\d+)px", tokens))
    assert spaces == [4, 8, 12, 16, 24]
    sizes = {k: v for k, v in re.findall(r"--fs-([\w-]+):\s*([\d.]+)rem", tokens)}
    assert (sizes["m"], sizes["answer"], sizes["greeting"], sizes["welcome"]) == (
        "1",
        "1.125",
        "1.375",
        "1.75",
    )  # 16 / 18 / 22 / 28 px
    assert "--line: 1.5;" in tokens
    js = (STATIC_DIR / "app.js").read_text("utf-8")
    assert "100 * c.font_scale" in js  # dasar 16 px
    for f in ("index.html", "app.js", "style.css"):
        text = (STATIC_DIR / f).read_text("utf-8")
        assert not re.search(r"[\U0001F300-\U0001FAFF\u2728\u2B50\u2192]", text), f  # emoji, panah


def test_ui_texts_are_plain_sentences():
    from mica.core import texts

    c = state.config_json(_ui(), dev=False)["texts"]
    shown = [*c.values(), texts.NOTICE_SHORT, texts.NOTICE_SHORT_NO_CAMERA,
             *texts.STATUS_LINES.values()]  # fmt: skip
    for t in shown:
        assert " · " not in t and "→" not in t and t != t.upper(), t
    assert texts.STATUS_LINES == {
        "ready": "Silakan bicara atau ketik pertanyaan", "listening": "Mendengarkan...",
        "thinking": "Mencari di dokumen PMB...", "speaking": "Menjawab...",
    }  # fmt: skip
    assert texts.NOTICE_SHORT == (
        "Kamera aktif, gambar tidak disimpan. Jawaban disusun AI dari dokumen resmi PMB dan bisa "
        "keliru; pastikan ke staf PMB untuk hal penting.")  # fmt: skip


def test_all_session_colors_have_tokens_and_rules():
    from mica.vision.color import COLOR_NAMES

    tokens = (STATIC_DIR / "tokens.css").read_text("utf-8")
    css = (STATIC_DIR / "style.css").read_text("utf-8")
    for name in COLOR_NAMES:
        slug = state.color_slug(name)
        assert f"--c-{slug}-swatch:" in tokens and f"--c-{slug}-tint:" in tokens, name
        assert f'body[data-color="{slug}"]' in css, name
    assert "--c-putih-edge:" in tokens  # putih: garis tepi abu


def test_colors_only_in_tokens():
    css = (STATIC_DIR / "style.css").read_text("utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL))


def test_logo_route_serves_local_file_or_404(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG\r\n")
    for ui, expected in ((_ui(logo_path=str(logo)), 200), (_ui(), 404)):
        webui = WebUi(ui, dev=False)
        server = start_server(webui)
        try:
            r = httpx.get(f"http://{HOST}:{webui.port}/logo")
            assert r.status_code == expected
            if expected == 200:
                assert r.content == logo.read_bytes()
        finally:
            stop_server(server)
    assert state.config_json(_ui(logo_path=str(logo)), dev=False)["logo"] == "/logo"
    assert state.config_json(_ui(), dev=False)["logo"] is None


@pytest.mark.parametrize(
    "value", ["https://mikroskil.ac.id/logo.png", "//cdn/logo.png", "logo.gif"]
)
def test_logo_path_must_be_local_image(tmp_path, value):
    import yaml

    from mica.config import ConfigError

    raw = yaml.safe_load(DEV_YAML.read_text(encoding="utf-8"))
    raw["ui"]["logo_path"] = value
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError, match="ui.logo_path"):
        load_settings(path)


def test_view_json_status_notice_session_color_and_refusal_kind():
    from mica.core.controller import DisplayUpdate

    vm = ViewModel()
    v = state.view_json(vm)
    assert (v["pill"], v["pill_label"]) == ("ready", "Siap") and not v["target_present"]
    assert v["status_line"] == "Silakan bicara atau ketik pertanyaan"
    assert v["greeting"].startswith("Halo, selamat datang") and v["session_color"] is None
    assert v["notice"].startswith("Kamera aktif, gambar tidak disimpan.")
    vm.apply_display(DisplayUpdate(target_present=True, target_color="merah muda"))
    vm.apply_display(DisplayUpdate(greeting="Halo, kamu yang berbaju merah muda"))
    for item in (
        ShowView(V.THINKING, transcript="x", send_enabled=False),
        ShowView(V.SPEAKING, transcript="x", answer="Maaf, belum ada infonya."),
    ):
        vm.apply(item)
    v = state.view_json(vm)
    assert v["pill"] == "speaking" and v["status_line"] == "Menjawab..."
    assert v["target_color"] == "merah muda" and v["session_color"] == "merah-muda"
    assert v["messages"][-1]["kind"] == "notice"  # penolakan: tanpa sumber
    vm.apply(ShowView(V.READY, camera_ok=False))
    assert state.view_json(vm)["notice"].startswith("Kamera tidak aktif")
    vm.apply(ShowView(V.READY, mic_ok=False))
    assert state.view_json(vm)["status_line"] == "Silakan ketik pertanyaan"
    vm.apply_display(DisplayUpdate(target_present=False))
    vm.apply(ClearScreen())
    v = state.view_json(vm)
    assert not v["target_present"] and v["session_color"] is None  # kembali netral
    assert v["greeting"].startswith("Halo, selamat datang")


def test_pills_cover_all_states():
    from mica.core import texts

    assert set(texts.PILLS) == {s.value for s in V}
    assert {p for p, _ in texts.PILLS.values()} == {"ready", "listening", "thinking", "speaking"}


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


def test_production_browser_never_opens_devtools_port(tmp_path):
    # Langkah 38: --remote-debugging-port hanya untuk bench (ui_bench --edge-extra), bukan produksi
    import mica.webui.browser as browser_mod

    assert "remote-debugging" not in Path(browser_mod.__file__).read_text(encoding="utf-8")
    url = "http://127.0.0.1:5000/"
    for preview in ("off", "public", "debug"):
        for fullscreen in (True, False):
            for keep in (True, False):
                cmd = edge_command(Path("msedge.exe"), url, tmp_path, fullscreen, keep, preview)
                assert not any("remote-debugging" in part for part in cmd)


def test_preview_switch_only_when_preview_on(tmp_path):
    # Langkah 38: K2 lolos (03-k2-vs-base); hanya kondisi yang diukur (pratinjau bukan off)
    assert PREVIEW_SWITCHES == ("--disable-gpu-compositing",)
    url = "http://127.0.0.1:5000/"
    edge = Path("msedge.exe")
    assert "--disable-gpu-compositing" not in edge_command(edge, url, tmp_path, True)
    for mode in ("public", "debug"):
        cmd = edge_command(edge, url, tmp_path, True, camera_preview=mode)
        assert cmd.count("--disable-gpu-compositing") == 1
        assert cmd.index("--disable-gpu-compositing") < cmd.index("--kiosk")
    started = []
    for mode in ("off", "public"):
        browser = EdgeBrowser(True, edge=edge, camera_preview=mode,
                              popen=lambda cmd: started.append(cmd) or FakeProc())  # fmt: skip
        browser.start(url)
        browser.close()
    assert "--disable-gpu-compositing" not in started[0]
    assert "--disable-gpu-compositing" in started[1]


def test_run_passes_camera_preview_to_browser():
    import inspect

    from mica.webui import app

    src = inspect.getsource(app.run)
    assert "camera_preview=settings.ui.camera_preview" in src


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


def test_token_contrast_at_least_aa():
    import importlib.util

    spec = importlib.util.spec_from_file_location("ui_contrast", ROOT / "scripts/ui_contrast.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = mod.rows()
    assert len(rows) == len(mod.PAIRS) and all(r >= 4.5 for *_, r in rows)
    assert mod.ratio("#ffffff", "#000000") == pytest.approx(21.0)


# --- Langkah 53: chip topik langsung mengirim question -----------------------------------


def test_chip_sends_configured_question_as_visitor_message():
    ui = _ui()
    for item in ui.topics:
        event = _web_event({"type": "topic", "topic": item.label, "question": item.question}, ui)
        assert event == TopicTapped(item.label, item.question)
    # nama topik saja (perilaku lama) atau pertanyaan karangan browser ditolak
    assert _web_event({"type": "topic", "topic": "Biaya", "question": "Biaya"}, ui) is None
    # pertanyaan chip tampil sebagai pesan pengunjung, sama seperti pertanyaan ketik
    from mica.core.session import Session

    def actions(event):
        ids = (f"s{i}" for i in range(10))
        session = Session(5.0, None, None, None, None, new_session_id=lambda: next(ids))
        return session.handle(event, 0.0)

    question = ui.topic_question("Biaya")
    out = actions(TopicTapped("Biaya", question))
    assert out == actions(TextSubmitted(question))
    vm = ViewModel()
    for item in out:
        if isinstance(item, ShowView):
            vm.apply(item)
    msgs = state.view_json(vm)["messages"]
    assert msgs[-1]["kind"] == "visitor" and msgs[-1]["text"] == question


def test_chip_ignored_while_answering():
    ui = _ui()
    busy = [ShowView(V.THINKING, transcript="x", send_enabled=False)]
    question = ui.topic_question("Biaya")
    msg = {"type": "topic", "topic": "Biaya", "question": question}
    assert _web_event(msg, ui, busy) is None
    assert _web_event(msg, ui) == TopicTapped("Biaya", question)


def test_app_js_chip_sends_question_and_follows_send_enabled():
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    send_topic = js[js.index("function sendTopic") : js.index("function topicButton")]
    assert 'type: "topic"' in send_topic and "item.question" in send_topic
    assert "view.send_enabled" in send_topic
    button = js[js.index("function topicButton") : js.index("function applyConfig")]
    assert "sendTopic(topic)" in button and "b.disabled" in button and "fillQuestion" not in js
    # chip (grid, baris chip, tawaran topik lanjut) ikut nonaktif seperti tombol Kirim
    assert 'querySelectorAll("button[data-topic]")) b.disabled = !v.send_enabled' in js
    assert "topicButton(m.follow_up.topic, false)" in js
    assert "innerHTML" not in js
