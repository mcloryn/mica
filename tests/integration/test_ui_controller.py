"""M-10 + KioskController lewat QTimer (offscreen): alur ketik lengkap sampai jawaban dan sumber.

Bus palsu dari mica.ui.devfakes, pipeline palsu dengan sumber; tanpa perangkat dan tanpa Groq.
"""

from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from mica.config import load_settings
from mica.core.session import TextSubmitted, VisitState
from mica.core.types import Chunk, FinalAnswer
from mica.ui.app import UiError, build
from mica.ui.devfakes import FAKE_ANSWER_PREFIX, FakePipeline, FakeWorkerBus

ROOT = Path(__file__).resolve().parents[2]
CHUNK = Chunk("03#2", "03", "Biaya Kuliah dan Syarat Masuk", "Biaya S1", date(2026, 9, 29),
              "dev", "isi", False)  # fmt: skip


class SourcedPipeline:
    def __init__(self) -> None:
        self.questions: list[str] = []

    def answer(self, question, history, session_id, *, input_mode="text"):
        self.questions.append(str(question))
        return FinalAnswer("answered", "Biaya Sistem Informasi Rp7.500.000 per tahun.", (CHUNK,),
                           {"total": 0.1})  # fmt: skip


def _settings(tmp_path, mode="dev"):
    s = load_settings(ROOT / "config" / "dev.yaml")
    return s.model_copy(update={
        "app": s.app.model_copy(update={"mode": mode}),
        "logging": s.logging.model_copy(update={"dir": str(tmp_path / "logs")}),
    })  # fmt: skip


def test_typed_question_flows_to_answer_and_sources(qtbot, tmp_path):
    bus, pipeline = FakeWorkerBus(), SourcedPipeline()
    kiosk = build(_settings(tmp_path), bus=bus, pipeline=pipeline)
    w = kiosk.window
    qtbot.addWidget(w)
    kiosk.timer.start()
    qtbot.waitUntil(lambda: not w.vm.camera_ok and not w.vm.mic_ok, timeout=3000)
    qtbot.keyClicks(w.input_edit, "Nomor saya 081234567890, biaya kuliah berapa?")
    qtbot.keyClick(w.input_edit, Qt.Key.Key_Return)

    def answered():
        return w.scroll.widget().findChild(QLabel, "sources") is not None

    qtbot.waitUntil(answered, timeout=5000)
    sources = w.scroll.widget().findChild(QLabel, "sources").text()
    assert "Biaya Kuliah dan Syarat Masuk (berlaku 29 September 2026)" in sources
    assert pipeline.questions == ["Nomor saya [TELEPON], biaya kuliah berapa?"]
    # SpeechDone palsu datang pada poll berikutnya -> READY dan kirim aktif lagi
    qtbot.waitUntil(lambda: kiosk.controller.session.state == VisitState.READY, timeout=3000)
    assert w.send_button.isEnabled() and w.debug_panel is not None
    assert "answered" in w.debug_panel.toPlainText()
    w.close()
    assert bus.stopped and not kiosk.timer.isActive()


def test_fake_flags_build_in_dev(qtbot, tmp_path):
    kiosk = build(_settings(tmp_path), fake_workers=True, fake_pipeline=True)
    qtbot.addWidget(kiosk.window)
    kiosk.timer.start()
    kiosk.window.event_emitted.emit(TextSubmitted("Akreditasi apa?"))
    qtbot.waitUntil(lambda: any(m.text.startswith(FAKE_ANSWER_PREFIX)
                                for m in kiosk.window.vm.messages), timeout=5000)  # fmt: skip
    assert isinstance(kiosk.controller.pipeline, FakePipeline)
    kiosk.window.close()


def test_fakes_refused_in_kiosk(tmp_path):
    settings = _settings(tmp_path, mode="kiosk")
    with pytest.raises(UiError, match="kiosk"):
        build(settings, fake_workers=True)
    with pytest.raises(UiError, match="kiosk"):
        build(settings, fake_pipeline=True)
