"""M-10 MainWindow: merender ViewModel dan memancarkan event UI; tanpa logika bisnis (SDD M-10).

Widget hanya membuat objek event (TopicTapped, TextSubmitted, TalkTapped, StopTapped) dan
memancarkannya lewat sinyal event_emitted; KioskController yang memprosesnya. Panel debug
hanya dibuat di mode dev.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mica.config import UiConfig
from mica.core import texts
from mica.core.controller import DebugInfo
from mica.core.session import (
    ClearScreen,
    ShowView,
    StopTapped,
    TalkTapped,
    TextSubmitted,
    TopicTapped,
)
from mica.ui.viewmodel import Message, ViewModel, source_line

HOME, CONVERSATION = 0, 1


class MessageWidget(QFrame):
    def __init__(self, message: Message) -> None:
        super().__init__()
        self.setObjectName(f"message_{message.role}")
        layout = QVBoxLayout(self)
        who = texts.VISITOR if message.role == "visitor" else texts.MICA
        layout.addWidget(QLabel(f"<b>{who}</b>"))
        body = QLabel(message.text)
        body.setObjectName("message_text")
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(body)
        if message.sources:
            lines = [texts.SOURCES_LABEL, *(f"• {source_line(s)}" for s in message.sources)]
            sources = QLabel("\n".join(lines))
            sources.setObjectName("sources")
            sources.setWordWrap(True)
            sources.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(sources)


class MainWindow(QMainWindow):
    event_emitted = Signal(object)
    closed = Signal()

    def closeEvent(self, event: Any) -> None:
        self.closed.emit()
        super().closeEvent(event)

    def __init__(self, ui: UiConfig, dev: bool) -> None:
        super().__init__()
        self.setWindowTitle("MICA")
        self.vm = ViewModel()
        self.rendered = 0  # jumlah pesan yang sudah menjadi widget
        self.shown_transcript: str | None = None

        central = QWidget()
        root = QVBoxLayout(central)
        self.setCentralWidget(central)

        top = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        self.camera_label = QLabel()
        self.camera_label.setObjectName("camera_indicator")
        self.mic_label = QLabel()
        self.mic_label.setObjectName("mic_indicator")
        top.addWidget(self.status_label, 1)
        top.addWidget(self.camera_label)
        top.addWidget(self.mic_label)
        root.addLayout(top)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._home_page(ui))
        self.stack.addWidget(self._conversation_page())
        root.addWidget(self.stack, 1)

        self.transcript_row = QWidget()
        row = QHBoxLayout(self.transcript_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(texts.TRANSCRIPT_LABEL))
        self.transcript_edit = QLineEdit()
        self.transcript_edit.setObjectName("transcript_edit")
        self.resend_button = QPushButton(texts.RESEND)
        self.resend_button.clicked.connect(self._resend)
        row.addWidget(self.transcript_edit, 1)
        row.addWidget(self.resend_button)
        root.addWidget(self.transcript_row)

        inputs = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setObjectName("input")
        self.input_edit.setPlaceholderText(texts.INPUT_PLACEHOLDER)
        self.input_edit.returnPressed.connect(self._send)
        self.send_button = QPushButton(texts.SEND)
        self.send_button.clicked.connect(self._send)
        self.talk_button = QPushButton(texts.TALK)
        self.talk_button.clicked.connect(lambda: self.event_emitted.emit(TalkTapped()))
        self.stop_button = QPushButton(texts.STOP)
        self.stop_button.clicked.connect(lambda: self.event_emitted.emit(StopTapped()))
        inputs.addWidget(self.input_edit, 1)
        for button in (self.send_button, self.talk_button, self.stop_button):
            inputs.addWidget(button)
        root.addLayout(inputs)

        # N-08: pemberitahuan permanen, tidak pernah disembunyikan
        self.notice_label = QLabel(f"{texts.NOTICE_CAMERA}  {texts.NOTICE_AI}")
        self.notice_label.setObjectName("notice")
        self.notice_label.setWordWrap(True)
        root.addWidget(self.notice_label)

        self.debug_panel: QPlainTextEdit | None = None
        if dev:
            self.debug_panel = QPlainTextEdit()
            self.debug_panel.setObjectName("debug_panel")
            self.debug_panel.setReadOnly(True)
            dock = QDockWidget("Debug (dev)")
            dock.setObjectName("debug_dock")
            dock.setWidget(self.debug_panel)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.render()

    # --- halaman ------------------------------------------------------------------------

    def _home_page(self, ui: UiConfig) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(texts.HOME_TITLE))
        grid = QGridLayout()
        self.topic_buttons: dict[str, QPushButton] = {}
        self.suggestion_buttons: list[QPushButton] = []
        for col, topic in enumerate(ui.topics):
            button = QPushButton(topic)
            button.setObjectName("topic")
            suggestions = ui.suggestions.get(topic, ())
            # tanpa saran (ui.suggestions kosong) nama topik dikirim sebagai pertanyaan
            first = suggestions[0] if suggestions else topic
            button.clicked.connect(lambda _=False, t=topic, q=first: self._topic(t, q))
            grid.addWidget(button, 0, col)
            self.topic_buttons[topic] = button
            for r, question in enumerate(suggestions, start=1):
                hint = QPushButton(question)
                hint.setObjectName("suggestion")
                hint.clicked.connect(lambda _=False, t=topic, q=question: self._topic(t, q))
                grid.addWidget(hint, r, col)
                self.suggestion_buttons.append(hint)
        layout.addLayout(grid)
        layout.addStretch(1)
        return page

    def _conversation_page(self) -> QWidget:
        self.scroll = QScrollArea()
        self.scroll.setObjectName("conversation")
        self.scroll.setWidgetResizable(True)
        container = QWidget()
        self.messages_layout = QVBoxLayout(container)
        self.messages_layout.addStretch(1)
        self.scroll.setWidget(container)
        bar = self.scroll.verticalScrollBar()
        bar.rangeChanged.connect(lambda _lo, hi: bar.setValue(hi))  # scroll otomatis ke bawah
        return self.scroll

    # --- event UI -> sinyal ---------------------------------------------------------------

    def _topic(self, topic: str, question: str) -> None:
        self.event_emitted.emit(TopicTapped(topic, question))

    def _send(self) -> None:
        text = self.input_edit.text().strip()
        if text and self.vm.send_enabled:
            self.event_emitted.emit(TextSubmitted(text))
            self.input_edit.clear()

    def _resend(self) -> None:
        text = self.transcript_edit.text().strip()
        if text and self.vm.send_enabled:
            self.event_emitted.emit(TextSubmitted(text))

    # --- tampilan -----------------------------------------------------------------------

    def show_item(self, item: ShowView | ClearScreen) -> None:
        self.vm.apply(item)
        self.render()

    def show_debug(self, info: DebugInfo) -> None:
        if self.debug_panel is not None:
            self.debug_panel.setPlainText(format_debug(info))

    def render(self) -> None:
        vm = self.vm
        status = texts.STATUS_LABELS[vm.status.value]
        extra = vm.status_message
        if extra and extra.lower() != status.lower():  # "mendengarkan" tidak ditulis dua kali
            status = f"{status}: {extra}"
        self.status_label.setText(status)
        self.camera_label.setText(texts.CAMERA_ON if vm.camera_ok else texts.CAMERA_OFF)
        self.mic_label.setText(texts.MIC_ON if vm.mic_ok else texts.MIC_OFF)
        self.talk_button.setEnabled(vm.mic_ok)
        self.send_button.setEnabled(vm.send_enabled)
        self.resend_button.setEnabled(vm.send_enabled)
        if self.rendered > len(vm.messages):  # ClearScreen
            while self.messages_layout.count() > 1:
                widget = self.messages_layout.takeAt(0).widget()
                if widget is not None:
                    widget.deleteLater()
            self.rendered = 0
        for message in vm.messages[self.rendered :]:
            self.messages_layout.insertWidget(self.messages_layout.count() - 1,
                                              MessageWidget(message))  # fmt: skip
        self.rendered = len(vm.messages)
        self.stack.setCurrentIndex(HOME if vm.home else CONVERSATION)
        self.transcript_row.setVisible(vm.last_transcript is not None)
        if vm.last_transcript != self.shown_transcript:  # suntingan pengunjung tidak ditimpa
            self.transcript_edit.setText(vm.last_transcript or "")
            self.shown_transcript = vm.last_transcript
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())


def format_debug(info: DebugInfo) -> str:
    def fmt(value: Any) -> str:
        return "-" if value is None else str(value)

    lines = [f"state M-09: {info.state.value}", f"FPS kamera: {fmt(info.camera_fps)}",
             f"status jawaban: {fmt(info.final_status)}", f"gerbang: {fmt(info.gate)}",
             f"penyedia LLM: {fmt(info.llm_provider)}", "potongan teratas:"]  # fmt: skip
    lines += [f"  {chunk_id}  {score:.3f}" for chunk_id, score in info.top_hits] or ["  -"]
    lines.append("waktu per tahap (s):")
    timings = info.timings or {}
    lines += [f"  {k}: {v:.3f}" for k, v in timings.items()] or ["  -"]
    return "\n".join(lines)
