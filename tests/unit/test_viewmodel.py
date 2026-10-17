"""M-10 ViewModel tanpa Qt: setiap jenis ShowView/ClearScreen dari M-09."""

import subprocess
import sys
from datetime import date
from pathlib import Path

from mica.core.session import ClearScreen, ShowView, VisitState
from mica.core.types import Chunk
from mica.ui.viewmodel import Message, Source, ViewModel, source_line

ROOT = Path(__file__).resolve().parents[2]
V = VisitState
CHUNK = Chunk("03#2", "03", "Biaya Kuliah dan Syarat Masuk", "Biaya S1", date(2026, 9, 29),
              "dev", "isi", False)  # fmt: skip


def _turn(vm, question="Biaya kuliah berapa?", answer="Rp7.500.000.", sources=(CHUNK,)):
    vm.apply(ShowView(V.THINKING, message="berpikir", transcript=question, send_enabled=False))
    vm.apply(ShowView(V.SPEAKING, transcript=question, answer=answer, sources=sources))
    vm.apply(ShowView(V.READY, transcript=question, answer=answer, sources=sources))


def test_initial_is_home():
    vm = ViewModel()
    assert vm.home and vm.status == V.IDLE and vm.send_enabled and vm.camera_ok and vm.mic_ok


def test_greeting_and_ready_status_without_messages():
    vm = ViewModel()
    vm.apply(ShowView(V.GREETING))
    assert vm.status == V.GREETING and vm.home
    vm.apply(ShowView(V.READY, message="Silakan bertanya"))
    assert vm.status_message == "Silakan bertanya" and vm.home


def test_listening_status():
    vm = ViewModel()
    vm.apply(ShowView(V.LISTENING, message="mendengarkan"))
    assert vm.status == V.LISTENING and vm.messages == []


def test_thinking_adds_question_and_disables_send():
    vm = ViewModel()
    vm.apply(ShowView(V.THINKING, message="berpikir", transcript="Biaya?", send_enabled=False))
    assert vm.messages == [Message("visitor", "Biaya?")]
    assert not vm.send_enabled and vm.last_transcript == "Biaya?" and not vm.home


def test_answer_with_sources_added_once():
    vm = ViewModel()
    _turn(vm)
    assert vm.messages == [
        Message("visitor", "Biaya kuliah berapa?"),
        Message(
            "mica", "Rp7.500.000.", (Source("Biaya Kuliah dan Syarat Masuk", date(2026, 9, 29)),)
        ),
    ]
    assert vm.send_enabled and vm.status == V.READY  # READY membawa jawaban lama: tidak ganda


def test_second_turn_appends():
    vm = ViewModel()
    _turn(vm)
    _turn(vm, "Kelas sore?", "Rp6.000.000.", ())
    assert [m.role for m in vm.messages] == ["visitor", "mica", "visitor", "mica"]
    assert vm.messages[-1].sources == () and vm.last_transcript == "Kelas sore?"


def test_not_heard_message_is_status_only():
    vm = ViewModel()
    vm.apply(ShowView(V.READY, message="Maaf, belum terdengar jelas. Silakan ulangi atau ketik."))
    assert vm.messages == [] and vm.status_message.startswith("Maaf")


def test_device_flags():
    vm = ViewModel()
    vm.apply(ShowView(V.READY, camera_ok=False, mic_ok=False))
    assert not vm.camera_ok and not vm.mic_ok


def test_clear_screen_returns_home():
    vm = ViewModel()
    _turn(vm)
    vm.apply(ClearScreen())
    vm.apply(ShowView(V.IDLE))
    assert vm.home and vm.last_transcript is None and vm.status == V.IDLE


def test_source_line_indonesian_date():
    assert source_line(Source("Biaya", date(2026, 9, 29))) == "Biaya (berlaku 29 September 2026)"


def test_viewmodel_imports_no_qt():
    code = "import sys, mica.ui.viewmodel; print('PySide6' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True, cwd=ROOT)  # fmt: skip
    assert out.stdout.strip() == "False"
