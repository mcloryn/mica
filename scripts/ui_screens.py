"""Tangkapan layar otomatis UI web (Langkah 37) lewat Edge headless + Chrome DevTools Protocol.

python scripts/ui_screens.py [--out docs/ui-screens] [--only nama,...]

Setiap adegan: WebUi dengan controller tiruan (tanpa pekerja, tanpa pipeline), ViewModel diisi
ShowView/DisplayUpdate yang sama dengan yang dikirim M-09/controller, lalu halaman difoto di
1366 x 768 dan 1920 x 1080 (Langkah 37b), atau 1000 x 700 untuk adegan layar sempit. Adegan pratinjau memakai sumber
gambar palsu (mica.vision.fakesource: siluet buatan, tanpa wajah orang sungguhan) yang dirender
oleh fungsi pratinjau yang sama dengan proses kamera. Hanya 127.0.0.1; dev saja.
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mica.config import load_settings
from mica.core.controller import DisplayUpdate
from mica.core.session import ShowView, VisitState
from mica.core.types import Chunk
from mica.webui.browser import find_edge
from mica.webui.server import HOST, WebUi, start_server, stop_server

V = VisitState
CDP_PORT = 9333  # hanya 127.0.0.1 (bawaan Edge), selama skrip berjalan
SIZES = ((1366, 768), (1920, 1080))  # Langkah 37b
NARROW = ((1000, 700),)
CHUNK = Chunk("03#2", "03", "Biaya Kuliah dan Syarat Masuk", "Biaya S1", date(2026, 9, 29),
              "dev", "isi", False)  # fmt: skip
ANSWER = ("Biaya kuliah S1 Teknik Informatika adalah Rp7.500.000 per semester, sudah termasuk "
          "biaya praktikum. Pembayaran bisa dicicil tiga kali.")  # fmt: skip
REFUSAL = ("Maaf, informasi itu belum ada di dokumen resmi PMB yang saya punya. Silakan tanyakan "
           "ke bagian PMB di lantai 1.")  # fmt: skip


class NullController:
    def submit(self, event: Any) -> None:
        pass

    def step(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _greeted(w: WebUi, color: str | None = "biru") -> None:
    from mica.core.texts import greeting

    w.show_display(DisplayUpdate(target_present=True, target_color=color))
    w.show_display(DisplayUpdate(greeting=greeting(color)))
    w.show_item(ShowView(V.READY, message="Silakan bertanya"))


def _conversation(w: WebUi, answer: str, sources: tuple[Chunk, ...], color: str = "biru") -> None:
    _greeted(w, color)
    q = "Berapa biaya kuliah Teknik Informatika?"
    w.show_item(ShowView(V.THINKING, message="berpikir", transcript=q, send_enabled=False))
    w.show_item(ShowView(V.SPEAKING, transcript=q, answer=answer, sources=sources))


def _answered(w: WebUi, color: str) -> None:
    _conversation(w, ANSWER, (CHUNK,), color)
    w.show_item(ShowView(V.READY, message="Silakan bertanya", transcript="Berapa biaya kuliah "
                         "Teknik Informatika?", answer=ANSWER, sources=(CHUNK,)))  # fmt: skip


@dataclass
class Scene:
    name: str
    setup: Callable[[WebUi], None]
    sizes: tuple[tuple[int, int], ...] = SIZES
    preview: str | None = None  # None = pratinjau mati; public | debug = sumber palsu


SCENES = [  # Langkah 37c
    Scene("01-sambut-tanpa-orang", lambda w: w.show_item(ShowView(V.IDLE))),
    Scene("02-sambut-target-biru", _greeted),
    Scene("03-percakapan-jawaban-sumber", lambda w: _answered(w, "biru")),
    Scene("04-penolakan", lambda w: _conversation(w, REFUSAL, ())),
    Scene(
        "05-mendengarkan",
        lambda w: (
            _answered(w, "biru"),
            w.show_item(ShowView(V.LISTENING, message="mendengarkan")),
        ),
    ),
    Scene("06-kamera-mati", lambda w: w.show_item(ShowView(V.READY, camera_ok=False))),
    Scene(
        "07-mic-tidak-tersedia",
        lambda w: (_greeted(w), w.show_item(ShowView(V.READY, mic_ok=False))),
    ),
    Scene("08-target-hitam", lambda w: _answered(w, "hitam")),
    Scene("09-target-putih", lambda w: _answered(w, "putih")),
]


def _preview_jpeg(mode: str, settings: Any) -> bytes:
    """Satu JPEG dari sumber palsu, lewat render pratinjau yang sama dengan proses kamera."""
    from mica.vision.fakesource import FakeScene, scripted_tracks
    from mica.vision.livepreview import PreviewRenderer, encode_jpeg

    scene = FakeScene()
    frame = scene.frame(12.0)  # orang berdiri di tengah
    tracks = scripted_tracks(scene, 12.0)
    ui = settings.ui
    renderer = PreviewRenderer(mode, ui.preview_pixel_block, min_kp_conf=0.5)
    target = tracks[0] if tracks else None
    image = renderer.render(frame, tracks, target, None, "biru")
    return encode_jpeg(image)


class Cdp:
    def __init__(self, port: int) -> None:
        import httpx
        from simple_websocket import Client

        deadline = time.monotonic() + 20
        while True:
            try:
                pages = httpx.get(f"http://127.0.0.1:{port}/json/list", timeout=2).json()
                page = next(p for p in pages if p.get("type") == "page")
                break
            except Exception:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        self.ws = Client.connect(page["webSocketDebuggerUrl"])
        self.i = 0

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.receive(timeout=30))
            if msg.get("id") == self.i:
                return msg.get("result", {})

    def wait_for(self, expression: str, timeout_s: float = 10) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            r = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
            if r.get("result", {}).get("value"):
                return
            time.sleep(0.1)
        raise TimeoutError(expression)

    def close(self) -> None:
        self.ws.close()


def shoot(scene: Scene, cdp: Cdp, out: Path, settings: Any, size: tuple[int, int]) -> Path:
    ui = settings.ui.model_copy(update={"camera_preview": scene.preview or "off"})
    webui = WebUi(ui, dev=scene.preview == "debug")
    webui.controller = NullController()
    scene.setup(webui)
    server = start_server(webui)
    try:
        w, h = size
        cdp.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1,
                 mobile=False)  # fmt: skip
        cdp.call("Page.navigate", url=f"http://{HOST}:{webui.port}/")
        cdp.wait_for("document.getElementById('app_title').textContent.length > 0")
        webui.flush()
        if scene.preview:
            cdp.wait_for("window.__micaPreviewReady === true")
            webui.push_preview(_preview_jpeg(scene.preview, settings))
            cdp.wait_for("!document.getElementById('preview_img').hidden")
        cdp.wait_for("document.fonts.status === 'loaded'")
        time.sleep(0.4)
        shot = cdp.call("Page.captureScreenshot", format="png")
        path = out / f"{scene.name}-{w}x{h}.png"
        path.write_bytes(base64.b64decode(shot["data"]))
        return path
    finally:
        webui.close_sockets()
        stop_server(server)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/ui_screens.py")
    parser.add_argument("--config", type=Path, default=ROOT / "config/dev.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "docs/ui-screens")
    parser.add_argument("--only", help="nama adegan dipisah koma")
    args = parser.parse_args(argv)
    settings = load_settings(args.config)
    args.out.mkdir(parents=True, exist_ok=True)
    wanted = set(args.only.split(",")) if args.only else None
    profile = Path(tempfile.mkdtemp(prefix="mica-screens-"))
    edge = subprocess.Popen([str(find_edge()), "--headless=new", f"--remote-debugging-port={CDP_PORT}",
                             f"--user-data-dir={profile}", "--no-first-run", "--hide-scrollbars",
                             "--force-device-scale-factor=1", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
    try:
        cdp = Cdp(CDP_PORT)
        try:
            for scene in SCENES:
                if wanted and scene.name not in wanted:
                    continue
                for size in scene.sizes:
                    print(shoot(scene, cdp, args.out, settings, size).as_posix())
        finally:
            cdp.close()
    finally:
        edge.terminate()
        try:
            edge.wait(timeout=10)
        except subprocess.TimeoutExpired:
            edge.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
