"""Pratinjau kamera UI kiosk (Langkah 37): pixelate public dibandingkan piksel dengan sumber palsu,
debug tanpa samaran, antrean membuang frame lama, preview off tanpa JPEG, tanpa file (N-08),
debug ditolak di kiosk, laju pratinjau tidak menambah inferensi, dan jalur /preview server."""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import time
from pathlib import Path

import numpy as np
import pytest
from simple_websocket import Client
from simple_websocket import ConnectionError as WsRejected
from test_bus import TEST_VALUES, _settings
from test_vision_color import fake_table
from tests.fakes import FakeDetector

from mica.core.bus import Shutdown
from mica.vision import livepreview as lp
from mica.vision.color import DEFAULT_COLORS_FILE
from mica.vision.fakesource import FRAME_W, FakeScene, scripted_tracks
from mica.vision.worker import VisionLoop, VisionWorkerConfig, WorkerConfigError

BLOCK = 16
MARGIN = 3  # garis kotak target (tebal 2) dan pembulatan skala


def _scene(t=12.0):
    scene = FakeScene()
    return scene.frame(t), scripted_tracks(scene, t)


def _target_rect(renderer, frame, target):
    _, scale = renderer.base(frame)
    w = renderer.width
    x1, y1, x2, y2 = (v * scale for v in target.box_xyxy)
    return round(w - x2), round(y1), round(w - x1), round(y2)


# --- render --------------------------------------------------------------------------------


def test_public_pixelates_everything_outside_target_box():
    frame, tracks = _scene()
    r = lp.PreviewRenderer("public", BLOCK)
    out = r.render(frame, tracks, tracks[0], None, "biru")
    base, _ = r.base(frame)  # sumber palsu, dikecilkan dan dicerminkan
    blurred = lp.pixelate(base, BLOCK)
    x1, y1, x2, y2 = _target_rect(r, frame, tracks[0])
    outside = np.ones(out.shape[:2], dtype=bool)
    outside[max(y1 - MARGIN, 0) : y2 + MARGIN, max(x1 - MARGIN, 0) : x2 + MARGIN] = False
    assert outside.sum() > 0.5 * outside.size
    assert np.array_equal(out[outside], blurred[outside])  # semua di luar kotak tersamar
    assert not np.array_equal(base[outside], blurred[outside])  # dan memang berubah
    # dalam kotak (di bawah label, di dalam garis): sama dengan sumber tanpa samaran
    inner = (slice(y1 + 30, y2 - MARGIN), slice(x1 + MARGIN, x2 - MARGIN))
    assert np.array_equal(out[inner], base[inner])


def test_public_without_target_pixelates_whole_image():
    frame, tracks = _scene()  # orang ada, tetapi tidak menjadi target (aman-gagal)
    r = lp.PreviewRenderer("public", BLOCK)
    out = r.render(frame, tracks, None, None, None)
    base, _ = r.base(frame)
    assert np.array_equal(out, lp.pixelate(base, BLOCK))
    assert out.shape[1] == lp.PREVIEW_WIDTH


def test_pixelate_blocks_are_uniform():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, (240, 320, 3), dtype=np.uint8)
    px = lp.pixelate(img, BLOCK)
    for y in range(0, 240, BLOCK):
        for x in range(0, 320, BLOCK):
            block = px[y : y + BLOCK, x : x + BLOCK].reshape(-1, 3)
            assert (block == block[0]).all()


def test_image_is_mirrored():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[:, :40] = 255  # kiri sumber putih
    out = lp.PreviewRenderer("debug", BLOCK).render(frame, [], None, None, None)
    assert out[:, -20:].mean() == 255 and out[:, :20].mean() == 0


def test_debug_is_not_pixelated_and_draws_overlays():
    frame, tracks = _scene()
    r = lp.PreviewRenderer("debug", BLOCK, min_kp_conf=0.5)
    out = r.render(frame, tracks, tracks[0], (300, 200, 340, 300), "biru 0.91")
    base, _ = r.base(frame)
    x1 = _target_rect(r, frame, tracks[0])[0]
    far = (slice(0, 40), slice(0, max(x1 - 10, 1)))  # pojok kiri atas, jauh dari kotak
    assert np.array_equal(out[far], base[far])
    assert not np.array_equal(out, base)  # ada overlay
    with pytest.raises(ValueError):
        lp.PreviewRenderer("off", BLOCK)


def test_jpeg_in_memory():
    frame, tracks = _scene()
    jpeg = lp.encode_jpeg(
        lp.PreviewRenderer("public", BLOCK).render(frame, tracks, None, None, None)
    )
    assert jpeg[:2] == b"\xff\xd8" and len(jpeg) < 60_000


# --- antrean ----------------------------------------------------------------------------------


def test_put_latest_drops_old_frame_thread_queue():
    q: queue.Queue = queue.Queue(maxsize=1)
    for i in range(5):
        assert lp.put_latest(q, i)
    assert q.qsize() == 1 and q.get_nowait() == 4


def test_put_latest_drops_old_frame_multiprocessing_queue():
    q = mp.get_context("spawn").Queue(maxsize=1)
    try:
        lp.put_latest(q, b"lama")
        time.sleep(0.2)
        lp.put_latest(q, b"baru")
        assert q.get(timeout=5) == b"baru"
        with pytest.raises(queue.Empty):
            q.get(timeout=0.3)
    finally:
        q.cancel_join_thread()
        q.close()


# --- VisionLoop --------------------------------------------------------------------------------


class SceneCamera:
    """Kamera palsu 25 fps (waktu dari jam palsu), Shutdown setelah n frame."""

    def __init__(self, inbox, clock, n):
        self.scene, self.inbox, self.clock, self.n, self.reads = FakeScene(), inbox, clock, n, 0

    def read(self):
        self.reads += 1
        self.clock.t = self.reads * 0.04
        if self.reads == self.n:
            self.inbox.put(Shutdown())
        return self.scene.frame(10.0 + self.clock.t), None

    def release(self):
        pass


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def _cfg(tmp_path, mode, **changes):
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    np.save(models / DEFAULT_COLORS_FILE.name, fake_table())
    s = _settings()
    s = s.model_copy(update={"ui": s.ui.model_copy(update={"camera_preview": mode, **changes})})
    return VisionWorkerConfig.from_settings(s, TEST_VALUES, models_dir=Path(models))


def _loop(tmp_path, mode, out=None, n=100):
    cfg = _cfg(tmp_path, mode)
    inbox, outbox, clock = queue.Queue(), queue.Queue(), Clock()
    detector = FakeDetector((0.0, 99.0))
    loop = VisionLoop(cfg, inbox, outbox, SceneCamera(inbox, clock, n), detector, clock=clock,
                      sleep=lambda s: None, preview_out=out)  # fmt: skip
    return loop, detector


def test_preview_off_creates_no_jpeg(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(lp, "encode_jpeg", lambda *a, **k: calls.append(1) or b"")
    out: queue.Queue = queue.Queue(maxsize=1)
    loop, _ = _loop(tmp_path, "off", out)
    loop.run()
    assert loop.renderer is None and loop.previews == 0 and calls == [] and out.empty()
    loop, _ = _loop(tmp_path, "public", None)  # tanpa antrean: juga tanpa JPEG
    loop.run()
    assert loop.renderer is None and calls == []


def test_public_preview_jpeg_rate_and_no_extra_inference(tmp_path):
    out: queue.Queue = queue.Queue(maxsize=1)
    loop, detector = _loop(tmp_path, "public", out)
    loop.run()
    ref, ref_detector = _loop(tmp_path, "off", None)
    ref.run()
    assert detector.calls == ref_detector.calls  # pratinjau tidak menambah inferensi
    # 100 frame x 0,04 s = 4 s pada preview_fps 5 -> +-20 JPEG
    assert 15 <= loop.previews <= 21
    assert out.qsize() == 1 and out.get_nowait()[:2] == b"\xff\xd8"


def test_preview_writes_no_files(tmp_path, monkeypatch):
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    out: queue.Queue = queue.Queue(maxsize=1)
    loop, _ = _loop(tmp_path, "public", out)
    loop.run()
    loop, _ = _loop(tmp_path, "debug", out)
    loop.run()
    assert os.listdir(work) == []
    assert sorted(p.name for p in (tmp_path / "models").iterdir()) == [DEFAULT_COLORS_FILE.name]


def test_debug_preview_rejected_outside_dev(tmp_path):
    cfg = _cfg(tmp_path, "debug")
    from dataclasses import replace

    with pytest.raises(WorkerConfigError, match="debug"):
        replace(cfg, mode="kiosk").validate()
    replace(cfg, mode="kiosk", camera_preview="public").validate()


def test_bus_preview_queue_only_when_not_off(tmp_path):
    from mica.core.bus import Bus

    for mode, expected in (("off", False), ("public", True)):
        bus = Bus(_settings(), _cfg(tmp_path, mode))
        try:
            assert (bus.preview is not None) is expected
        finally:
            bus.stop()


# --- sumber palsu ------------------------------------------------------------------------------


def test_fake_scene_cycle_and_shoulder_signal():
    scene = FakeScene()
    assert scripted_tracks(scene, 1.0) == []
    (t,) = scripted_tracks(scene, 12.0)
    ratio = abs(float(t.keypoints[5][0]) - float(t.keypoints[6][0])) / FRAME_W
    assert ratio >= 0.22  # memenuhi nilai coba min_shoulder_ratio
    assert scene.frame(1.0).shape == (480, 640, 3)


# --- server /preview --------------------------------------------------------------------------


def test_preview_socket_origin_checked_and_receives_jpeg():
    from mica.config import load_settings
    from mica.webui.server import HOST, WebUi, start_server, stop_server

    ui = load_settings(Path(__file__).resolve().parents[2] / "config/dev.yaml").ui
    webui = WebUi(ui.model_copy(update={"camera_preview": "public"}), dev=False)
    server = start_server(webui)
    try:
        url = f"ws://{HOST}:{webui.port}/preview"
        for origin in ("http://evil.example", f"http://localhost:{webui.port}"):
            with pytest.raises(WsRejected):
                Client.connect(url, headers={"Origin": origin})
        client = Client.connect(url, headers={"Origin": f"http://{HOST}:{webui.port}"})
        deadline = time.monotonic() + 5
        while not webui.preview_sockets and time.monotonic() < deadline:
            time.sleep(0.02)
        source: queue.Queue = queue.Queue(maxsize=1)
        webui.preview_source = source
        import threading

        stop = threading.Event()
        pump = threading.Thread(target=webui.preview_loop, args=(stop,), daemon=True)
        pump.start()
        source.put(b"\xff\xd8jpeg-palsu")
        assert client.receive(timeout=5) == b"\xff\xd8jpeg-palsu"
        stop.set()
        pump.join(timeout=3)
        client.close()
    finally:
        webui.close_sockets()
        stop_server(server)


def test_debug_label_white_on_dark_box_public_unchanged():
    img = np.full((60, 120, 3), 200, dtype=np.uint8)
    lp.debug_label(img, "biru 0.91", (5, 5))
    box = img[5:20, 5:60]
    assert (box < 200).any() and (box.max(axis=2) > 230).any()  # latar digelapkan + teks putih
    assert box.min() <= int(200 * (1 - lp.LABEL_BG_ALPHA)) + 1
    assert (img[40:, :] == 200).all()  # di luar kotak label tidak berubah
