"""UI web saat mulai (Langkah 40): UI tampil sebelum pipeline siap, status "Menyiapkan ...",
ketikan sebelum pipeline/kamera/suara siap tetap dijawab, sapaan tetap jalan, pipeline gagal ->
penolakan baku tanpa macet."""

import logging
import threading
import time
from pathlib import Path

import pytest

from mica.audio.messages import AudioStatus, Speak, SpeechDone
from mica.config import load_settings
from mica.core.session import TextSubmitted, VisitState
from mica.rag.background import BackgroundPipeline, PipelineUnavailable
from mica.rag.prompts import UNAVAILABLE
from mica.ui.devfakes import FakePipeline
from mica.vision.types import CameraStatus, PersonArrived
from mica.webui import state
from mica.webui.app import build_controller
from mica.webui.server import WebUi

DEV_YAML = Path(__file__).resolve().parents[2] / "config" / "dev.yaml"


class ScriptBus:
    """Bus palsu: status pekerja datang hanya saat diminta (seperti pekerja yang masih memuat)."""

    names = ("vision", "audio")

    def __init__(self):
        self.outbox = []
        self.sent = []
        self.stopped = False

    def poll(self):
        out, self.outbox = self.outbox, []
        return out

    def send(self, target, msg):
        self.sent.append((target, msg))
        if isinstance(msg, Speak):
            self.outbox.append(SpeechDone(msg.session_id, msg.utterance_id, None))

    def stop(self):
        self.stopped = True


def _settings(tmp_path):
    s = load_settings(DEV_YAML)
    return s.model_copy(update={"logging": s.logging.model_copy(update={"dir": str(tmp_path)})})


def _build(tmp_path, monkeypatch, make):
    """Controller dengan make_pipeline palsu di thread latar (jalur produksi build_controller)."""
    import mica.rag.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "make_pipeline", make)
    s = _settings(tmp_path)
    webui = WebUi(s.ui, dev=True)
    bus = ScriptBus()
    controller = build_controller(s, webui, bus=bus)
    return webui, controller, bus


def _until(webui, controller, cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        webui.tick()
        if cond():
            return True
        for f in list(controller.pending):
            if f.done():
                f.result()
        time.sleep(0.01)
    return False


def test_ui_usable_and_typed_question_answered_after_pipeline_ready(tmp_path, monkeypatch):
    release = threading.Event()

    def slow_make(settings):
        release.wait(5)  # seperti import sentence_transformers + muat BGE-M3
        return FakePipeline()

    webui, controller, _bus = _build(tmp_path, monkeypatch, slow_make)
    try:
        assert isinstance(controller.pipeline, BackgroundPipeline)
        assert not controller.pipeline.ready  # build_controller tidak menunggu pipeline
        webui.tick()
        v = state.view_json(webui.vm)
        assert v["send_enabled"]  # kotak ketik aktif sebelum pipeline/kamera/suara siap
        webui.events.put(TextSubmitted("pertanyaan sebelum siap"))
        assert _until(webui, controller, lambda: webui.vm.status == VisitState.THINKING)
        v = state.view_json(webui.vm)
        assert [m["role"] for m in v["messages"]] == ["visitor"]  # diterima dan ditampilkan
        assert v["status_line"] == "Menyiapkan jawaban..."
        release.set()
        assert _until(webui, controller, lambda: webui.vm.status == VisitState.READY)
        v = state.view_json(webui.vm)
        assert [m["role"] for m in v["messages"]] == ["visitor", "mica"]
        assert "pertanyaan sebelum siap" in v["messages"][1]["text"]
        assert not webui.vm.answer_preparing
    finally:
        release.set()
        controller.shutdown()


def test_starting_labels_until_first_worker_status(tmp_path, monkeypatch):
    webui, controller, bus = _build(tmp_path, monkeypatch, lambda s: FakePipeline())
    try:
        v = state.view_json(webui.vm)
        assert v["camera_label"] == "Menyiapkan kamera..." and v["camera_starting"]
        assert v["mic_label"] == "Menyiapkan mikrofon..." and not v["talk_enabled"]
        bus.outbox.append(CameraStatus(ok=True, message="kamera 0 terbuka"))
        webui.tick()
        v = state.view_json(webui.vm)
        assert v["camera_label"] == "Kamera: aktif" and not v["camera_starting"]
        assert v["mic_label"] == "Menyiapkan mikrofon..."  # suara belum melapor
        bus.outbox.append(
            AudioStatus(mic_ok=False, speaker_ok=True, ready=True, message="MIC_DOWN")
        )
        webui.tick()
        v = state.view_json(webui.vm)
        assert v["mic_label"] == "Mikrofon: tidak tersedia" and not v["mic_starting"]
    finally:
        controller.shutdown()


def test_greeting_runs_while_pipeline_loading(tmp_path, monkeypatch):
    release = threading.Event()
    webui, controller, bus = _build(tmp_path, monkeypatch,
                                    lambda s: release.wait(5) and FakePipeline())  # fmt: skip
    try:
        bus.outbox.append(PersonArrived(1, (0.0, 0.0, 10.0, 10.0), time.monotonic()))
        assert _until(webui, controller, lambda: any(isinstance(m, Speak) for _, m in bus.sent))
        assert not controller.pipeline.ready  # sapaan tidak butuh RAG
    finally:
        release.set()
        controller.shutdown()


def test_pipeline_load_failure_gives_standard_refusal(tmp_path, monkeypatch, caplog):
    def broken(settings):
        raise FileNotFoundError("KB tidak ada")

    caplog.set_level(logging.ERROR, logger="mica.rag.background")
    webui, controller, _bus = _build(tmp_path, monkeypatch, broken)
    try:
        assert controller.pipeline.wait(5) and controller.pipeline.failed
        assert any("LLM_UNAVAILABLE" in r.getMessage() and "gagal dimuat" in r.getMessage()
                   for r in caplog.records)  # fmt: skip
        webui.events.put(TextSubmitted("pertanyaan saat pipeline rusak"))
        assert _until(webui, controller, lambda: len(webui.vm.messages) == 2)  # tidak macet
        assert webui.vm.messages[1].text == UNAVAILABLE
        assert not webui.vm.answer_preparing
    finally:
        controller.shutdown()


def test_close_releases_waiting_question():
    release = threading.Event()
    bp = BackgroundPipeline(lambda: release.wait(5) and FakePipeline()).start()
    bp.close()
    with pytest.raises(PipelineUnavailable):
        bp.run("q", [], "s")
    release.set()
