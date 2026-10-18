"""Pipeline yang dirakit di thread latar (Langkah 40): UI web tampil sebelum BGE-M3 selesai dimuat.

- start() menjalankan build() (mis. make_pipeline) di thread daemon; model, pustaka, dan hasil
  retrieval sama persis, hanya waktunya yang dipindah.
- Thread dipilih, bukan proses: pipeline tetap satu objek di proses utama yang dipanggil
  controller seperti sebelumnya, tanpa IPC atau serialisasi; import dan muat model sebagian besar
  berjalan di kode native sehingga thread UI tetap responsif.
- run()/answer() dipanggil controller di thread pipeline-nya; bila pipeline belum siap, panggilan
  menunggu sampai siap lalu menjawab (pertanyaan yang diketik lebih dulu tetap dijawab).
- build() gagal: galat dicatat sekali (LLM_UNAVAILABLE) dan setiap panggilan melempar
  PipelineUnavailable; controller menjawabnya dengan teks penolakan baku (UNAVAILABLE).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, Self

from mica.core.types import ErrorCode

log = logging.getLogger(__name__)


class PipelineUnavailable(RuntimeError):
    pass


class BackgroundPipeline:
    def __init__(
        self,
        build: Callable[[], Any],
        on_ready: Callable[[], None] | None = None,
        on_failed: Callable[[BaseException], None] | None = None,
    ) -> None:
        self._build = build
        self._on_ready = on_ready
        self._on_failed = on_failed
        self._done = threading.Event()
        self._closed = threading.Event()
        self._pipeline: Any = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._load, name="mica-pipeline-load", daemon=True)

    def start(self) -> Self:
        self._thread.start()
        return self

    def _load(self) -> None:
        try:
            self._pipeline = self._build()
        except Exception as exc:  # noqa: BLE001 - kiosk tetap jalan, jawaban = penolakan baku
            self._error = exc
            log.error("%s: pipeline gagal dimuat (%s: %s)", ErrorCode.LLM_UNAVAILABLE,
                      type(exc).__name__, exc)  # fmt: skip
        finally:
            self._done.set()
        if self._error is None:
            if self._on_ready is not None:
                self._on_ready()
        elif self._on_failed is not None:
            self._on_failed(self._error)

    @property
    def ready(self) -> bool:
        """True bila pipeline sudah dirakit dan siap menjawab."""
        return self._done.is_set() and self._error is None

    @property
    def failed(self) -> bool:
        return self._done.is_set() and self._error is not None

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def close(self) -> None:
        """Aplikasi ditutup: pertanyaan yang masih menunggu pipeline dihentikan."""
        self._closed.set()

    def _get(self) -> Any:
        while not self._done.wait(0.1):
            if self._closed.is_set():
                raise PipelineUnavailable("aplikasi ditutup sebelum pipeline siap")
        if self._error is not None:
            raise PipelineUnavailable("pipeline gagal dimuat") from self._error
        return self._pipeline

    def run(self, question: Any, history: Any, session_id: str, **kwargs: Any) -> tuple[Any, Any]:
        pipeline = self._get()
        run = getattr(pipeline, "run", None)
        if run is not None:
            return run(question, history, session_id, **kwargs)
        return pipeline.answer(question, history, session_id, **kwargs), None

    def answer(self, question: Any, history: Any, session_id: str, **kwargs: Any) -> Any:
        return self._get().answer(question, history, session_id, **kwargs)
