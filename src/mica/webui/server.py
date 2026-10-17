"""UI web (percobaan ADR-19): server aiohttp HTTP + WebSocket di satu port, hanya 127.0.0.1.

- KioskController dan ViewModel yang sama dengan PySide6; web hanya merender ViewModel.
- controller.step() dipanggil setiap 50 ms di loop asyncio (setara QTimer di mica.ui.app).
- Setiap ViewModel berubah, JSON tampilan dikirim ke semua browser dengan nomor urut (seq).
  Browser membalas {"type": "ack", "seq"} setelah requestAnimationFrame berikutnya; selisih
  waktunya (diukur di Python) dicatat di ack_latencies_s untuk scripts/ui_bench.py.
- WebSocket dengan header Origin selain alamat server ini ditolak (403).
- Content-Security-Policy hanya mengizinkan aset dari server ini (tanpa aset internet).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from mica.config import UiConfig
from mica.core.controller import DebugInfo
from mica.core.session import ClearScreen, ShowView
from mica.ui.viewmodel import ViewModel
from mica.webui.state import config_json, event_from_message, format_debug, view_json

HOST = "127.0.0.1"  # tidak pernah 0.0.0.0: UI hanya untuk laptop kiosk itu sendiri
POLL_INTERVAL_S = 0.05  # SDD 3.3: setara QTimer 50 ms PySide6
STATIC_DIR = Path(__file__).with_name("static")
CSP = "default-src 'self'; connect-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'"


class WebUi:
    def __init__(self, ui: UiConfig, dev: bool,
                 clock: Callable[[], float] = time.perf_counter) -> None:  # fmt: skip
        self.ui = ui
        self.dev = dev
        self.clock = clock
        self.vm = ViewModel()
        self.controller: Any = None
        self.port: int | None = None
        self.sockets: set[web.WebSocketResponse] = set()
        self.dirty = True
        self.debug_text: str | None = None
        self.debug_dirty = False
        self.seq = 0
        self.sent_at: dict[int, float] = {}
        self.ack_latencies_s: list[float] = []
        self.first_render_at: float | None = None
        self.on_event: Callable[[Any], None] | None = None  # kait tes/bench

    # --- dipanggil controller -----------------------------------------------------------

    def show_item(self, item: ShowView | ClearScreen) -> None:
        self.vm.apply(item)
        self.dirty = True

    def show_debug(self, info: DebugInfo) -> None:
        if self.dev:
            self.debug_text = format_debug(info)
            self.debug_dirty = True

    # --- aiohttp ------------------------------------------------------------------------

    def origin_allowed(self, origin: str | None) -> bool:
        return self.port is not None and origin == f"http://{HOST}:{self.port}"

    def make_app(self) -> web.Application:
        app = web.Application(middlewares=[self._headers])
        app.router.add_get("/", self._index)
        app.router.add_get("/ws", self._ws)
        app.router.add_static("/static/", STATIC_DIR, show_index=False)
        return app

    @web.middleware
    async def _headers(self, request: web.Request, handler: Any) -> web.StreamResponse:
        response = await handler(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["Cache-Control"] = "no-store"
        return response

    async def _index(self, request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "index.html")

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        if not self.origin_allowed(request.headers.get("Origin")):
            raise web.HTTPForbidden(text="Origin ditolak")
        ws = web.WebSocketResponse(heartbeat=None)
        await ws.prepare(request)
        self.sockets.add(ws)
        try:
            await ws.send_json({"type": "config", **config_json(self.ui, self.dev)})
            await self._send_view([ws])
            if self.debug_text is not None:
                await ws.send_json({"type": "debug", "text": self.debug_text})
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    self.handle_message(json.loads(msg.data))
        finally:
            self.sockets.discard(ws)
        return ws

    def handle_message(self, data: dict[str, Any]) -> None:
        kind = data.get("type")
        now = self.clock()
        if kind == "ack":
            sent = self.sent_at.pop(int(data.get("seq", -1)), None)
            if sent is not None:
                self.ack_latencies_s.append(now - sent)
                if self.first_render_at is None:
                    self.first_render_at = now
            return
        event = event_from_message(data, self.vm, self.ui)
        if event is not None and self.controller is not None:
            if self.on_event is not None:
                self.on_event(event)
            self.controller.submit(event)

    async def _send_view(self, targets: list[web.WebSocketResponse]) -> None:
        self.seq += 1
        payload = {"type": "view", "seq": self.seq, "view": view_json(self.vm)}
        self.sent_at[self.seq] = self.clock()
        for ws in targets:
            if not ws.closed:
                await ws.send_json(payload)

    async def flush(self) -> None:
        """Kirim tampilan bila ViewModel berubah sejak pengiriman terakhir."""
        if self.dirty and self.sockets:
            self.dirty = False
            await self._send_view(list(self.sockets))
        if self.debug_dirty and self.sockets:
            self.debug_dirty = False
            for ws in list(self.sockets):
                if not ws.closed:
                    await ws.send_json({"type": "debug", "text": self.debug_text})

    async def poll_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            if self.controller is not None:
                self.controller.step()
            await self.flush()
            try:
                await asyncio.wait_for(stop.wait(), POLL_INTERVAL_S)
            except TimeoutError:
                pass

    async def close_sockets(self) -> None:
        for ws in list(self.sockets):
            await ws.close()


async def start_site(webui: WebUi, port: int = 0) -> web.AppRunner:
    """Jalankan server di 127.0.0.1; port 0 = port acak bebas. webui.port diisi setelah bind."""
    runner = web.AppRunner(webui.make_app(), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, HOST, port)
    await site.start()
    host, bound = runner.addresses[0][:2]
    if host != HOST:
        await runner.cleanup()
        raise RuntimeError(f"server terikat ke {host}, bukan {HOST}")
    webui.port = int(bound)
    return runner
