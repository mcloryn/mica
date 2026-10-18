"""Bus dan pipeline palsu untuk python -m mica.ui --fake-workers/--fake-pipeline (dev saja).

FakeWorkerBus berjalan di dalam proses: tanpa kamera dan mikrofon (CameraStatus ok=False,
AudioStatus mic_ok=False) sehingga UI dipakai lewat teks; Speak langsung dijawab SpeechDone
pada poll berikutnya (tanpa suara). Dengan vision (start_fake_camera), proses kamera asli
berjalan dengan sumber gambar palsu (mica.vision.fakesource): event kamera dan antrean
pratinjau datang dari proses itu. FakePipeline menjawab dengan teks berlabel palsu tanpa
memanggil Groq. Keduanya ditolak di mode kiosk oleh mica.ui.app.
"""

from __future__ import annotations

from typing import Any, Literal

from mica.audio.messages import AudioStatus, Speak, SpeechDone
from mica.core.types import FinalAnswer
from mica.trial import TRIAL_VALUES
from mica.vision.types import CameraStatus

FAKE_ANSWER_PREFIX = "[jawaban palsu dev] "
# nilai coba SDD bagian 12 untuk sumber gambar palsu (dev saja, bukan hasil E-07/E-08); sumber
# tunggal mica.trial.TRIAL_VALUES, kunci tanpa awalan "vision."
FAKE_CAMERA_VALUES = {k.removeprefix("vision."): v for k, v in TRIAL_VALUES.items()
                      if k.startswith("vision.")}  # fmt: skip


def fake_camera_config(settings: Any) -> Any:
    """VisionWorkerConfig proses kamera asli dengan sumber gambar dan detektor palsu (dev)."""
    from mica.vision.worker import VisionWorkerConfig

    return VisionWorkerConfig.from_settings(
        settings, FAKE_CAMERA_VALUES,
        camera_factory="mica.vision.fakesource:make_camera",
        detector_factory="mica.vision.fakesource:make_detector",
    )  # fmt: skip


def start_fake_camera(settings: Any) -> Any:
    """Bus vision saja: proses kamera asli + sumber gambar dan detektor palsu (dev saja)."""
    from mica.core.bus import start_workers

    return start_workers(settings, vision=fake_camera_config(settings))


class FakeWorkerBus:
    names = ("vision", "audio")

    def __init__(self, vision: Any = None) -> None:
        self.vision = vision  # Bus vision asli (sumber gambar palsu) atau None
        self.preview = getattr(vision, "preview", None)
        self.dead: set[str] = set()
        camera = [] if vision is not None else [
            CameraStatus(ok=False, message="kamera palsu (dev): tidak ada kamera")]  # fmt: skip
        self.outbox: list[Any] = [
            *camera,
            AudioStatus(
                mic_ok=False,
                speaker_ok=False,
                ready=True,
                message="suara palsu (dev): tanpa mikrofon dan speaker",
            ),
        ]
        self.sent: list[tuple[str, Any]] = []
        self.stopped = False

    def poll(self) -> list[Any]:
        out, self.outbox = self.outbox, []
        if self.vision is not None:
            out += self.vision.poll()
        return out

    def send(self, target: str, msg: Any) -> None:
        self.sent.append((target, msg))
        if target == "vision" and self.vision is not None:
            self.vision.send(target, msg)
        if isinstance(msg, Speak):  # StopSpeaking: Speak palsu sudah selesai seketika
            self.outbox.append(SpeechDone(msg.session_id, msg.utterance_id, None))

    def stop(self) -> None:
        self.stopped = True
        if self.vision is not None:
            self.vision.stop()


class FakePipeline:
    def __init__(self) -> None:
        self.calls = 0

    def answer(
        self,
        question: str,
        history: Any,
        session_id: str,
        *,
        input_mode: Literal["voice", "text"] = "text",
    ) -> FinalAnswer:
        self.calls += 1
        return FinalAnswer("answered", f"{FAKE_ANSWER_PREFIX}Pertanyaan diterima: {question}",
                           (), {"total": 0.0})  # fmt: skip
