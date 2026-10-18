"""UI web (ADR-19, opsi ui.backend: web): server Flask + flask-sock, HTTP + WebSocket di satu port,
hanya 127.0.0.1.

- KioskController dan ViewModel yang sama dengan PySide6; web hanya merender ViewModel.
- Thread latar memanggil tick() setiap 50 ms (setara QTimer di mica.ui.app): event dari browser
  diteruskan ke controller, controller.step(), lalu ViewModel yang berubah disiarkan ke semua
  koneksi aktif. Controller hanya disentuh thread itu; koneksi WebSocket (satu thread per
  koneksi di server Werkzeug) hanya mengantre event. Semua state bersama dijaga satu lock.
- Setiap ViewModel berubah, JSON tampilan dikirim dengan nomor urut (seq). Browser membalas
  {"type": "ack", "seq"} setelah requestAnimationFrame berikutnya; selisih waktunya (diukur di
  Python) dicatat di ack_latencies_s untuk scripts/ui_bench.py.
- WebSocket dengan header Origin selain alamat server ini ditolak (403) sebelum handshake.
- Content-Security-Policy hanya mengizinkan aset dari server ini (tanpa aset internet).

Server WSGI: server bawaan Werkzeug (threaded, reloader dan debugger mati); alasannya di
docs/UI-WEB.md, "Catatan setelah tahap 1".
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from flask import Flask, Response, abort, request, send_from_directory
from flask_sock import ConnectionClosed, Sock
from werkzeug.serving import BaseWSGIServer, WSGIRequestHandler, make_server

from mica.config import UiConfig
from mica.core.controller import DebugInfo, DisplayUpdate
from mica.core.session import ClearScreen, Event, ShowView
from mica.ui.viewmodel import ViewModel
from mica.webui.state import config_json, event_from_message, format_debug, view_json

HOST = "127.0.0.1"  # tidak pernah 0.0.0.0: UI hanya untuk laptop kiosk itu sendiri
POLL_INTERVAL_S = 0.05  # SDD 3.3: setara QTimer 50 ms PySide6
STATIC_DIR = Path(__file__).with_name("static")
CSP = "default-src 'self'; connect-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'"


class WebUi:
    def __init__(self, ui: UiConfig, dev: bool,
                 clock: Callable[[], float] = time.perf_counter,
                 render_clock: Callable[[], float] = time.monotonic) -> None:  # fmt: skip
        self.ui = ui
        self.dev = dev
        self.clock = clock
        # K-3 (E-09): jam yang sama dengan controller dan pekerja (monotonic), bukan perf_counter
        self.render_clock = render_clock
        self.sent_views: dict[int, tuple[str, bool]] = {}  # seq -> (status, ada transkripsi)
        self.vm = ViewModel()
        self.controller: Any = None
        self.port: int | None = None
        self.lock = threading.RLock()  # vm, sockets, seq, sent_at, debug, dan setiap ws.send
        self.sockets: set[Any] = set()
        self.events: queue.Queue[Event] = queue.Queue()  # browser -> thread controller
        self.dirty = True
        self.debug_text: str | None = None
        self.debug_dirty = False
        self.seq = 0
        self.sent_at: dict[int, float] = {}
        self.ack_latencies_s: list[float] = []
        self.first_render_at: float | None = None
        self.on_event: Callable[[Any], None] | None = None  # kait tes/bench

    # --- dipanggil controller (thread poll) ---------------------------------------------

    def show_item(self, item: ShowView | ClearScreen) -> None:
        with self.lock:
            self.vm.apply(item)
            self.dirty = True

    def show_display(self, update: DisplayUpdate) -> None:
        """Info tampilan tambahan (sapaan, target vision) dari controller; tanpa frame."""
        with self.lock:
            self.vm.apply_display(update)
            self.dirty = True

    def show_debug(self, info: DebugInfo) -> None:
        if self.dev:
            with self.lock:
                self.debug_text = format_debug(info)
                self.debug_dirty = True

    # --- Flask --------------------------------------------------------------------------

    def origin_allowed(self, origin: str | None) -> bool:
        return self.port is not None and origin == f"http://{HOST}:{self.port}"

    def make_app(self) -> Flask:
        # static_folder=None: rute static ditulis sendiri supaya hanya STATIC_DIR yang dilayani
        app = Flask(__name__, static_folder=None)
        app.debug = False  # debugger Werkzeug tidak pernah dipasang
        sock = Sock(app)

        @app.before_request
        def _check_origin() -> None:
            if request.path == "/ws" and not self.origin_allowed(request.headers.get("Origin")):
                abort(403, "Origin ditolak")

        @app.after_request
        def _headers(response: Response) -> Response:
            response.headers["Content-Security-Policy"] = CSP
            response.headers["Cache-Control"] = "no-store"
            return response

        @app.get("/")
        def _index() -> Response:
            return send_from_directory(STATIC_DIR, "index.html")

        @app.get("/static/<path:name>")
        def _static(name: str) -> Response:
            return send_from_directory(STATIC_DIR, name)

        @app.get("/logo")
        def _logo() -> Response:
            # ui.logo_path: file lokal yang divalidasi config (bukan URL); null -> 404
            if not self.ui.logo_path:
                abort(404)
            path = Path(self.ui.logo_path).resolve()
            if not path.is_file():
                abort(404)
            return send_from_directory(path.parent, path.name)

        @sock.route("/ws")
        def _ws(ws: Any) -> None:
            self.serve_socket(ws)

        return app

    def serve_socket(self, ws: Any) -> None:
        with self.lock:
            self.sockets.add(ws)
            ws.send(json.dumps({"type": "config", **config_json(self.ui, self.dev)}))
            self._send_view([ws])
            if self.debug_text is not None:
                ws.send(json.dumps({"type": "debug", "text": self.debug_text}))
        try:
            while True:
                data = ws.receive()
                if data is None:
                    break
                if isinstance(data, str):
                    self.handle_message(json.loads(data))
        except ConnectionClosed:
            pass
        finally:
            with self.lock:
                self.sockets.discard(ws)

    def handle_message(self, data: dict[str, Any]) -> None:
        kind = data.get("type")
        now = self.clock()
        with self.lock:
            if kind == "ack":
                seq = int(data.get("seq", -1))
                sent = self.sent_at.pop(seq, None)
                view = self.sent_views.pop(seq, None)
                if sent is not None:
                    self.ack_latencies_s.append(now - sent)
                    if self.first_render_at is None:
                        self.first_render_at = now
                rendered = getattr(self.controller, "view_rendered", None)
                if view is not None and rendered is not None:
                    rendered(view[0], view[1], self.render_clock())  # respons pertama K-3
                return
            event = event_from_message(data, self.vm, self.ui)
        if event is not None and self.controller is not None:
            if self.on_event is not None:
                self.on_event(event)
            self.events.put(event)  # diteruskan ke controller oleh thread poll (tick)

    def _send(self, ws: Any, payload: dict[str, Any]) -> None:
        try:
            ws.send(json.dumps(payload))
        except ConnectionClosed:
            self.sockets.discard(ws)

    def _send_view(self, targets: list[Any]) -> None:
        self.seq += 1
        payload = {"type": "view", "seq": self.seq, "view": view_json(self.vm)}
        self.sent_at[self.seq] = self.clock()
        self.sent_views[self.seq] = (self.vm.status.value, self.vm.last_transcript is not None)
        for ws in targets:
            self._send(ws, payload)

    def flush(self) -> None:
        """Kirim tampilan bila ViewModel berubah sejak pengiriman terakhir."""
        with self.lock:
            if self.dirty and self.sockets:
                self.dirty = False
                self._send_view(list(self.sockets))
            if self.debug_dirty and self.sockets:
                self.debug_dirty = False
                for ws in list(self.sockets):
                    self._send(ws, {"type": "debug", "text": self.debug_text})

    def tick(self) -> None:
        """Satu putaran thread poll: event browser -> controller, step, lalu siarkan."""
        if self.controller is not None:
            while True:
                try:
                    event = self.events.get_nowait()
                except queue.Empty:
                    break
                self.controller.submit(event)
            self.controller.step()
        self.flush()

    def poll_loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self.tick()
            stop.wait(POLL_INTERVAL_S)

    def close_sockets(self) -> None:
        with self.lock:
            targets = list(self.sockets)
        for ws in targets:
            try:
                ws.close()
            except Exception:  # noqa: BLE001, S110 - koneksi bisa sudah putus dari sisi browser
                pass


class _QuietHandler(WSGIRequestHandler):
    """Tanpa log akses per permintaan (setara access_log=None versi aiohttp); error tetap dicatat."""

    def log_request(self, *args: Any, **kwargs: Any) -> None:
        pass


def start_server(webui: WebUi, port: int = 0) -> BaseWSGIServer:
    """Jalankan server di thread latar, hanya 127.0.0.1; port 0 = port acak bebas.

    make_server (bukan app.run/run_simple) tidak pernah memasang reloader maupun debugger.
    Hentikan dengan stop_server(). webui.port diisi setelah bind.
    """
    server = make_server(HOST, port, webui.make_app(), threaded=True,
                         request_handler=_QuietHandler)  # fmt: skip
    host, bound = server.socket.getsockname()[:2]
    if host != HOST:
        server.server_close()
        raise RuntimeError(f"server terikat ke {host}, bukan {HOST}")
    webui.port = int(bound)
    thread = threading.Thread(target=server.serve_forever, name="mica-webui-server", daemon=True)
    thread.start()
    server.mica_thread = thread  # type: ignore[attr-defined]
    return server


def stop_server(server: BaseWSGIServer) -> None:
    server.shutdown()
    server.server_close()
    thread = getattr(server, "mica_thread", None)
    if thread is not None:
        thread.join(timeout=5)
