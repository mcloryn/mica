"""M-10 MainWindow dengan pytest-qt (offscreen, lihat tests/conftest.py)."""

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

from mica.config import load_settings
from mica.core import texts
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
from mica.ui.main_window import CONVERSATION, HOME, MainWindow

ROOT = Path(__file__).resolve().parents[2]
V = VisitState
CHUNK = Chunk("03#2", "03", "Biaya Kuliah dan Syarat Masuk", "Biaya S1", date(2026, 9, 29),
              "dev", "isi", False)  # fmt: skip


def _ui(**changes):
    ui = load_settings(ROOT / "config" / "dev.yaml").ui
    return ui.model_copy(update=changes)


@pytest.fixture
def window(qtbot):
    w = MainWindow(_ui(), dev=True)
    qtbot.addWidget(w)
    events = []
    w.event_emitted.connect(events.append)
    w.events = events
    return w


def _answer(w, question="Biaya kuliah berapa?", answer="Rp7.500.000 per tahun."):
    w.show_item(ShowView(V.THINKING, message="berpikir", transcript=question,
                         send_enabled=False))  # fmt: skip
    w.show_item(ShowView(V.SPEAKING, transcript=question, answer=answer, sources=(CHUNK,)))


def test_topic_click_emits_topic_tapped(window, qtbot):
    qtbot.mouseClick(window.topic_buttons["Biaya"], Qt.MouseButton.LeftButton)
    assert window.events == [TopicTapped("Biaya", "Biaya")]  # ui.suggestions kosong


def test_suggestion_buttons_from_config(qtbot):
    w = MainWindow(_ui(suggestions={"Biaya": ("Biaya kuliah S1 berapa?",)}), dev=False)
    qtbot.addWidget(w)
    events = []
    w.event_emitted.connect(events.append)
    (hint,) = w.suggestion_buttons
    qtbot.mouseClick(hint, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(w.topic_buttons["Biaya"], Qt.MouseButton.LeftButton)
    assert events == [TopicTapped("Biaya", "Biaya kuliah S1 berapa?")] * 2


def test_type_and_enter_emits_text_submitted(window, qtbot):
    qtbot.keyClicks(window.input_edit, "Jalur masuk apa saja?")
    qtbot.keyClick(window.input_edit, Qt.Key.Key_Return)
    assert window.events == [TextSubmitted("Jalur masuk apa saja?")]
    assert window.input_edit.text() == ""
    qtbot.keyClick(window.input_edit, Qt.Key.Key_Return)  # kosong: tidak dikirim
    assert len(window.events) == 1


def test_send_disabled_while_thinking(window, qtbot):
    window.show_item(ShowView(V.THINKING, transcript="Biaya?", send_enabled=False))
    assert not window.send_button.isEnabled()
    qtbot.keyClicks(window.input_edit, "lagi")
    qtbot.keyClick(window.input_edit, Qt.Key.Key_Return)
    assert window.events == []
    window.show_item(ShowView(V.SPEAKING, transcript="Biaya?", answer="Jawab."))
    assert window.send_button.isEnabled()


def test_edit_transcript_and_resend(window, qtbot):
    _answer(window, question="biaya kulia berapa")
    assert window.transcript_row.isVisibleTo(window)
    assert window.transcript_edit.text() == "biaya kulia berapa"
    window.transcript_edit.clear()
    qtbot.keyClicks(window.transcript_edit, "biaya kuliah berapa")
    window.show_item(ShowView(V.READY, transcript="biaya kulia berapa", answer="x"))
    assert window.transcript_edit.text() == "biaya kuliah berapa"  # suntingan tidak ditimpa
    qtbot.mouseClick(window.resend_button, Qt.MouseButton.LeftButton)
    assert window.events == [TextSubmitted("biaya kuliah berapa")]


def test_stop_and_talk_buttons(window, qtbot):
    qtbot.mouseClick(window.stop_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.talk_button, Qt.MouseButton.LeftButton)
    assert window.events == [StopTapped(), TalkTapped()]


def test_sources_shown_under_answer(window):
    _answer(window)
    assert window.stack.currentIndex() == CONVERSATION
    mica = window.scroll.widget().findChild(QLabel, "sources")
    assert "Biaya Kuliah dan Syarat Masuk (berlaku 29 September 2026)" in mica.text()
    texts_shown = [lbl.text() for lbl in window.scroll.widget().findChildren(QLabel,
                   "message_text")]  # fmt: skip
    assert texts_shown == ["Biaya kuliah berapa?", "Rp7.500.000 per tahun."]


def test_clear_screen_back_to_home(window):
    _answer(window)
    window.show_item(ClearScreen())
    window.show_item(ShowView(V.IDLE))
    assert window.stack.currentIndex() == HOME
    assert window.rendered == 0 and window.messages_layout.count() == 1  # hanya stretch
    assert not window.transcript_row.isVisibleTo(window)


def test_notice_always_visible(window):
    window.show()
    for item in (ShowView(V.GREETING), ShowView(V.THINKING, transcript="x", send_enabled=False),
                 ClearScreen(), ShowView(V.IDLE, camera_ok=False, mic_ok=False)):  # fmt: skip
        window.show_item(item)
        assert window.notice_label.isVisible()
        assert texts.NOTICE_CAMERA in window.notice_label.text()
        assert texts.NOTICE_AI in window.notice_label.text()


def test_device_indicators_follow_show_view(window):
    assert window.camera_label.text() == texts.CAMERA_ON
    window.show_item(ShowView(V.READY, camera_ok=False, mic_ok=False))
    assert window.camera_label.text() == texts.CAMERA_OFF
    assert window.mic_label.text() == texts.MIC_OFF and not window.talk_button.isEnabled()


def test_status_indicator(window):
    window.show_item(ShowView(V.LISTENING, message="mendengarkan"))
    assert window.status_label.text() == "Mendengarkan"
    window.show_item(ShowView(V.THINKING, message="berpikir", transcript="x",
                              send_enabled=False))  # fmt: skip
    assert window.status_label.text() == "Berpikir"
    window.show_item(ShowView(V.SPEAKING, answer="y", transcript="x"))
    assert window.status_label.text() == "Berbicara"


def test_debug_panel_only_in_dev(qtbot):
    dev = MainWindow(_ui(), dev=True)
    kiosk = MainWindow(_ui(), dev=False)
    qtbot.addWidget(dev)
    qtbot.addWidget(kiosk)
    assert dev.debug_panel is not None and dev.findChild(object, "debug_dock") is not None
    assert kiosk.debug_panel is None and kiosk.findChild(object, "debug_dock") is None
    dev.show_debug(DebugInfo(V.SPEAKING, 4.8, "answered", {"passed": True, "score": 0.61},
                             (("03#2", 0.61),), "groq:openai/gpt-oss-120b",
                             {"retrieval": 0.1, "llm": 0.9}))  # fmt: skip
    text = dev.debug_panel.toPlainText()
    assert "SPEAKING" in text and "03#2  0.610" in text and "gpt-oss-120b" in text
    assert "llm: 0.900" in text and "FPS kamera: 4.8" in text
    kiosk.show_debug(DebugInfo(V.IDLE))  # tanpa panel: tidak error


def test_topic_buttons_match_config(window):
    labels = [b.text() for b in window.findChildren(QPushButton, "topic")]
    assert labels == list(_ui().topics)


def test_ui_modules_import_no_heavy_modules():
    code = (
        "import sys, mica.ui.app, mica.ui.main_window, mica.ui.viewmodel, mica.ui.devfakes\n"
        "print([m for m in ('torch', 'ctranslate2', 'onnxruntime') if m in sys.modules])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True, cwd=ROOT)  # fmt: skip
    assert out.stdout.strip() == "[]"
