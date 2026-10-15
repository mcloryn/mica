import pytest


@pytest.fixture(autouse=True)
def _no_model_download(monkeypatch):
    # Tes tidak boleh mengunduh model; pemanggilan Hugging Face langsung gagal.
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
