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
