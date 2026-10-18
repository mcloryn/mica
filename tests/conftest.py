import os

import pytest

# Tes Qt (pytest-qt) tidak pernah membuka jendela sungguhan; diatur di sini, bukan di kode
# aplikasi. Harus sebelum QApplication pertama dibuat.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _no_model_download(monkeypatch):
    # Tes tidak boleh mengunduh model; pemanggilan Hugging Face langsung gagal.
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")


@pytest.fixture(autouse=True)
def _startup_log_isolated(tmp_path_factory):
    # Langkah 40: mica.core.startup.init() memasang variabel lingkungan untuk proses anak; tes
    # tidak boleh mewariskannya ke tes lain, dan run() di tes tidak menulis ke logs/ asli.
    from mica.core import startup

    keys = (startup.ENV_FILE, startup.ENV_RUN)
    saved = {k: os.environ.pop(k, None) for k in keys}
    startup._buffer, startup._proc = None, "main"
    startup.DEFAULT_PATH_OVERRIDE = tmp_path_factory.mktemp("startup") / "startup.jsonl"
    yield
    startup.DEFAULT_PATH_OVERRIDE = None
    for k in keys:
        os.environ.pop(k, None)
        if saved[k] is not None:
            os.environ[k] = saved[k]
    startup._buffer, startup._proc = None, "main"
