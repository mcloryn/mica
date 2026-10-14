"""Uji alamat-alamat aplikasi web (tanpa kamera, tanpa internet, tanpa model Whisper)."""

import pytest

from mica.web import app as web


@pytest.fixture
def client():
    """Klien uji Flask dengan data bersama yang masih kosong."""
    web.state = web.SharedState()
    return web.app.test_client()


def test_greetings_start_empty(client):
    assert client.get("/greetings").get_json() == []


def test_greetings_start_from_since_index(client):
    web.state.greetings = [{"track_id": 1}, {"track_id": 2}]
    assert client.get("/greetings?since=1").get_json() == [{"track_id": 2}]


def test_empty_question_rejected(client):
    response = client.post("/ask", json={"text": "   "})
    assert response.status_code == 400


def test_question_recorded_in_visitor_session(client, monkeypatch):
    monkeypatch.setattr(web, "answer", lambda question, history: f"jawaban untuk {question}")
    web.state.conversations[3] = [{"role": "mica", "text": "Halo"}]

    response = client.post("/ask", json={"track_id": 3, "text": "Biaya kuliah?"})

    assert response.get_json() == {"answer": "jawaban untuk Biaya kuliah?"}
    assert [m["role"] for m in web.state.conversations[3]] == ["mica", "visitor", "mica"]


def test_failed_tts_gives_503(client, monkeypatch):
    def fail(text):
        raise OSError("internet putus")
    monkeypatch.setattr(web, "synthesize", fail)
    assert client.post("/speak", json={"text": "Halo"}).status_code == 503


def test_empty_recording_rejected(client):
    assert client.post("/transcribe", data=b"").status_code == 400


def test_failed_stt_still_replies_json(client, monkeypatch):
    def fail(audio):
        raise ValueError("format tidak dikenali")
    monkeypatch.setattr(web, "transcribe", fail)

    response = client.post("/transcribe", data=b"bukan audio")

    assert response.status_code == 500
    assert "error" in response.get_json()
