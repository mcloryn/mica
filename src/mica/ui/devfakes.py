"""Bus dan pipeline palsu untuk python -m mica.ui --fake-workers/--fake-pipeline (dev saja).

FakeWorkerBus berjalan di dalam proses: tanpa kamera dan mikrofon (CameraStatus ok=False,
AudioStatus mic_ok=False) sehingga UI dipakai lewat teks; Speak langsung dijawab SpeechDone
pada poll berikutnya (tanpa suara). FakePipeline menjawab dengan teks berlabel palsu tanpa
memanggil Groq. Keduanya ditolak di mode kiosk oleh mica.ui.app.
"""

from __future__ import annotations

from typing import Any, Literal

from mica.audio.messages import AudioStatus, Speak, SpeechDone
from mica.core.types import FinalAnswer
from mica.vision.types import CameraStatus

FAKE_ANSWER_PREFIX = "[jawaban palsu dev] "


class FakeWorkerBus:
    names = ("vision", "audio")

    def __init__(self) -> None:
        self.dead: set[str] = set()
        self.outbox: list[Any] = [
            CameraStatus(ok=False, message="kamera palsu (dev): tidak ada kamera"),
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
        return out

    def send(self, target: str, msg: Any) -> None:
        self.sent.append((target, msg))
        if isinstance(msg, Speak):  # StopSpeaking: Speak palsu sudah selesai seketika
            self.outbox.append(SpeechDone(msg.session_id, msg.utterance_id, None))

    def stop(self) -> None:
        self.stopped = True


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
