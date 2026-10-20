"""Format tampilan jawaban UI web (tampilan saja): mica.webui.answer_format dan static/answer_format.js.

Jawaban nyata dari run E-02 120b (per_question.csv, dev), kasus singkatan/angka/enumerasi,
teks TTS dan JSON ViewModel tidak berubah, dan kesetaraan versi JS lewat Edge headless.
"""

import csv
import html
import json
import re
import subprocess
from datetime import date
from pathlib import Path

import pytest

from mica.audio.messages import Speak, SpeechDone, SpeechStarted, Transcript
from mica.core.session import AnswerReady, Session, ShowView, VisitState
from mica.core.types import Chunk, FinalAnswer
from mica.ui.viewmodel import ViewModel
from mica.vision.types import PersonArrived
from mica.webui import state
from mica.webui.answer_format import MAX_SENTENCES_PER_PARAGRAPH, format_answer, split_sentences
from mica.webui.browser import EdgeMissing, find_edge
from mica.webui.server import STATIC_DIR

ROOT = Path(__file__).resolve().parents[2]
RUN_120B = ROOT / "results/E-02/20261017-122758-E-02-dev-hybrid-gpt-oss-120b-gateoff"


def real_answers() -> list[str]:
    with (RUN_120B / "per_question.csv").open(encoding="utf-8-sig", newline="") as f:
        return [r["answer"] for r in csv.DictReader(f) if r["answer"].strip()]


def words(text: str) -> list[str]:
    return text.split()


def block_words(blocks: list[dict]) -> list[str]:
    out: list[str] = []
    for b in blocks:
        for t in [b["text"]] if b["type"] == "p" else b["items"]:
            out += words(t)
    return out


# --- jawaban nyata (120b) ------------------------------------------------------------------


def test_real_answers_at_least_ten():
    assert len(real_answers()) >= 10


@pytest.mark.parametrize("text", real_answers())
def test_real_answer_keeps_every_word_and_max_two_sentences(text):
    blocks = format_answer(text)
    assert block_words(blocks) == words(text)  # tidak ada kata yang hilang/berubah/bertambah
    for b in blocks:
        if b["type"] == "p":
            assert len(split_sentences(b["text"])) <= MAX_SENTENCES_PER_PARAGRAPH


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        # 1-2 kalimat: tetap satu paragraf (sebagian besar jawaban 120b)
        ("Rektornya adalah Hardy", ["Rektornya adalah Hardy, S.Kom., M.Sc., Ph.D."]),
        ("Admisi buka", ["Admisi buka pada hari Sabtu mulai pukul 09.00 sampai 17.00 WIB."]),
        ("Email Bagian Keuangan", [("Email Bagian Keuangan Universitas Mikroskil adalah "
                                   "fin@mikroskil.ac.id.")]),
        ("Untuk masuk Magister Manajemen", None),  # IPK 2,75: dua kalimat, satu paragraf
        ("Tidak ada gelombang tiga", None),
        ("Menurut tracer study 2025", None),  # 88 %
        ("Pendaftaran online di daftar", None),  # "pertama, ... kedua, ..." bukan pola nomor
    ],
)  # fmt: skip
def test_real_answer_single_paragraph(prefix, expected):
    text = next(a for a in real_answers() if a.startswith(prefix))
    assert format_answer(text) == [{"type": "p", "text": text}]
    if expected:
        assert [text] == expected


def test_real_answers_have_no_newline_or_numbered_list():
    # temuan langkah 1: jawaban 120b tanpa baris baru dan tanpa pola "1. / 1) / (1)"
    for text in real_answers():
        assert "\n" not in text
        assert not any(b["type"] == "ol" for b in format_answer(text))


# --- pemecah kalimat: singkatan, angka, URL, email ----------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Biaya Rp. 5.000.000 per semester.",
        "Gedung No. 7 di Jl. Thamrin No. 140.",
        "Ada futsal, basket, dll. Semua gratis.",
        "Berkas: ijazah, KTP, dsb. Bawa aslinya.",
        "Dosennya Prof. Budi dan Dr. Sari.",
        "Lulusan bergelar S.Kom. Untuk Akuntansi S.Ak. dan Manajemen S.E. Semua terakreditasi.",
        "Rektornya Hardy, S.Kom., M.Kom., Ph.D. Beliau mengajar.",
        "Berlaku T.A. 2026/2027 untuk semua.",
        "IPK minimal 3,5 atau 3.5 dari skala 4.",
        "Buka pukul 09.30 WIB.",
        "Kuliah perdana 17.10.2026 di Kampus A.",
        "Situsnya daftar.mikroskil.ac.id atau https://www.mikroskil.ac.id/pmb.",
        "Kirim ke sa.office@mikroskil.ac.id sebelum tenggat.",
    ],
)
def test_abbreviations_and_numbers_do_not_split(sentence):
    # singkatan bertitik dianggap bukan akhir kalimat (aman: paling buruk dua kalimat bergabung)
    assert split_sentences(sentence) == [sentence]


def test_sentence_ends_after_number_url_email():
    text = ("Biaya Rp14.000.000. Situs daftar.mikroskil.ac.id. Email fin@mikroskil.ac.id. "
            "Buka 09.30! Ada pertanyaan? \"Silakan\" datang.")  # fmt: skip
    assert split_sentences(text) == ["Biaya Rp14.000.000.", "Situs daftar.mikroskil.ac.id.",
                                     "Email fin@mikroskil.ac.id.", "Buka 09.30!",
                                     "Ada pertanyaan?", "\"Silakan\" datang."]  # fmt: skip


def test_lowercase_after_period_is_not_a_boundary():
    assert split_sentences("Lihat brosur hlm. 3 dan bagian lain.") == [
        "Lihat brosur hlm. 3 dan bagian lain."
    ]


# --- aturan c: paragraf maks. 2 kalimat ----------------------------------------------------


def test_long_block_split_into_paragraphs_of_two():
    text = "Satu. Dua. Tiga. Empat. Lima."
    assert format_answer(text) == [
        {"type": "p", "text": "Satu. Dua."},
        {"type": "p", "text": "Tiga. Empat."},
        {"type": "p", "text": "Lima."},
    ]


def test_two_sentences_stay_one_paragraph():
    text = "Biaya S1 Rp14.000.000 per tahun. Kelas sore Rp15.000.000."
    assert format_answer(text) == [{"type": "p", "text": text}]


# --- aturan b: enumerasi dalam kalimat ----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Syaratnya: 1) ijazah; 2) KTP; 3) pas foto. Bawa aslinya saat verifikasi.",
        "Syaratnya: 1. ijazah; 2. KTP; 3. pas foto. Bawa aslinya saat verifikasi.",
        "Syaratnya: (1) ijazah; (2) KTP; (3) pas foto. Bawa aslinya saat verifikasi.",
    ],
)
def test_inline_enumeration_styles(text):
    assert format_answer(text) == [
        {"type": "p", "text": "Syaratnya:"},
        {"type": "ol", "start": 1, "items": ["ijazah", "KTP", "pas foto."]},
        {"type": "p", "text": "Bawa aslinya saat verifikasi."},
    ]


def test_inline_enumeration_cached_20b_answer():
    # jawaban 20b nyata (run E-04 20261016-220121, d005); butir berakhir titik
    text = ("Langkah pendaftaran di Universitas Mikroskil adalah: 1. Daftar online menggunakan "
            "akun Google. 2. Registrasi dan isi data diri. 3. Pilih jalur pendaftaran, lengkapi "
            "data pribadi, dan unggah dokumen yang dibutuhkan. 4. Verifikasi berkas (untuk S2, "
            "pendaftar juga wajib mengikuti Ujian Saring Masuk). 5. Daftar ulang dengan membayar "
            "daftar ulang dan melengkapi data lanjutan. 6. Daftar berhasil dan resmi menjadi "
            "mahasiswa baru.")  # fmt: skip
    blocks = format_answer(text)
    assert blocks[0] == {
        "type": "p",
        "text": "Langkah pendaftaran di Universitas Mikroskil adalah:",
    }
    assert blocks[1]["type"] == "ol" and len(blocks[1]["items"]) == 6 and len(blocks) == 2
    assert blocks[1]["items"][3] == ("Verifikasi berkas (untuk S2, pendaftar juga wajib mengikuti "
                                     "Ujian Saring Masuk).")  # fmt: skip


def test_numbers_that_are_not_an_enumeration():
    for text in [
        "Gedung di lantai 2, 3, dan 4. Parkir di lantai 1.",
        "Terbentuk tahun 2021. Kampus ada 2. Semua di Medan.",  # "2." tanpa "1." bukan daftar
        "Kampus 1. Lokasinya di Jl. Thamrin.",  # hanya satu penanda
        "Biaya Rp14.000.000 (1 tahun) dan Rp7.000.000 (2 semester).",
    ]:
        assert not any(b["type"] == "ol" for b in format_answer(text)), text


def test_enumeration_sequence_ignores_out_of_order_numbers():
    text = "Ada 1) gedung A tahun 2021) baru, 2) gedung B."
    assert format_answer(text) == [
        {"type": "p", "text": "Ada"},
        {"type": "ol", "start": 1, "items": ["gedung A tahun 2021) baru", "gedung B."]},
    ]


# --- aturan a: baris baru asli ------------------------------------------------------------


def test_original_newlines_kept_and_numbered_lines_become_list():
    text = "Langkahnya:\n1. Daftar online.\n2. Verifikasi.\n\nSatu. Dua. Tiga.\r\nSelesai."
    assert format_answer(text) == [
        {"type": "p", "text": "Langkahnya:"},
        {"type": "ol", "start": 1, "items": ["Daftar online.", "Verifikasi."]},
        {"type": "p", "text": "Satu. Dua."},
        {"type": "p", "text": "Tiga."},
        {"type": "p", "text": "Selesai."},
    ]


def test_empty_text():
    assert format_answer("") == [] and format_answer("  \n ") == []


# --- TTS dan JSON ViewModel tidak berubah -------------------------------------------------

LONG = ("Langkahnya: 1) daftar online; 2) verifikasi berkas. Biaya Rp14.000.000. Bawa KTP. "
        "Hubungi Admisi.")  # fmt: skip


def test_tts_text_identical_to_answer_text():
    # Speak (TTS) memakai answer.text apa adanya; format hanya di browser
    s = Session(fps_idle=5.0, fps_busy=2.0, min_majority=0.5, idle_reset_s=30.0,
                regreet_cooldown_s=10.0, new_session_id=lambda: "s0")  # fmt: skip
    s.handle(PersonArrived(1, (0.0, 0.0, 10.0, 10.0), 0.0, "biru", 0.9), 0.0)
    s.handle(SpeechDone(s.session_id, s.greeting_uid, 0.2), 1.0)
    s.handle(SpeechStarted(s.session_id, 2.0), 2.0)
    s.handle(Transcript(s.session_id, "langkah daftar", True, 0.5, 1.5), 3.0)
    actions = s.handle(AnswerReady(s.session_id, FinalAnswer("answered", LONG, (), {})), 4.0)
    speaks = [a for a in actions if isinstance(a, Speak)]
    assert [a.text for a in speaks] == [LONG]
    show = next(a for a in actions if isinstance(a, ShowView))
    assert show.answer == LONG


def test_view_json_answer_text_unformatted():
    chunk = Chunk("03#2", "03", "Biaya", "Biaya S1", date(2026, 9, 29), "dev", "isi", False)
    vm = ViewModel()
    vm.apply(ShowView(VisitState.THINKING, transcript="langkah?", send_enabled=False))
    vm.apply(ShowView(VisitState.SPEAKING, transcript="langkah?", answer=LONG, sources=(chunk,)))
    msg = state.view_json(vm)["messages"][-1]
    assert msg["text"] == LONG and msg["kind"] == "answer"
    assert set(msg) == {"role", "kind", "who", "text", "sources"}  # skema JSON tetap


def test_app_js_builds_dom_without_inner_html():
    for name in ("app.js", "answer_format.js"):
        js = (STATIC_DIR / name).read_text("utf-8")
        assert "innerHTML" not in js and "outerHTML" not in js and "insertAdjacentHTML" not in js
    app = (STATIC_DIR / "app.js").read_text("utf-8")
    assert "MicaAnswerFormat.formatAnswer(text)" in app
    assert re.search(r'el\("p", "", b\.text\)', app) and re.search(r'el\("li", "", x\)', app)
    html = (STATIC_DIR / "index.html").read_text("utf-8")
    assert html.index("/static/answer_format.js") < html.index("/static/app.js")


def test_max_sentences_is_design_value_in_both_versions():
    assert MAX_SENTENCES_PER_PARAGRAPH == 2
    js = (STATIC_DIR / "answer_format.js").read_text("utf-8")
    assert "const MAX_SENTENCES_PER_PARAGRAPH = 2;" in js and "nilai desain" in js.lower()


# --- kesetaraan JS = Python (Edge headless, file lokal) -----------------------------------


def parity_cases() -> list[str]:
    extra = [
        "Satu. Dua. Tiga. Empat. Lima.",
        "Syaratnya: (1) ijazah; (2) KTP; (3) pas foto. Bawa aslinya saat verifikasi.",
        "Syaratnya: 1. ijazah; 2. KTP. Bawa aslinya. Lalu daftar. Selesai.",
        "Langkahnya:\n1. Daftar online.\n2. Verifikasi.\n\nSatu. Dua. Tiga.\r\nSelesai.",
        "Rektornya Hardy, S.Kom., M.Kom., Ph.D. Beliau mengajar. Buka 09.30! Ada? Ya.",
        "Biaya Rp. 5.000 di Jl. Thamrin No. 1. Situs daftar.mikroskil.ac.id. Email a@b.id. Oke.",
        "Ada 1) gedung A tahun 2021) baru, 2) gedung B.",
        "",
        LONG,
    ]
    return real_answers() + extra


def test_js_formatter_matches_python(tmp_path):
    try:
        edge = find_edge()
    except EdgeMissing:
        pytest.skip("Microsoft Edge tidak ada")
    cases = parity_cases()
    page = tmp_path / "parity.html"
    js = (STATIC_DIR / "answer_format.js").read_text("utf-8")
    page.write_text(
        "<!doctype html><meta charset='utf-8'><body><pre id='out'></pre><script>"
        + js
        + "\nconst cases = " + json.dumps(cases) + ";\n"
        "document.getElementById('out').textContent = JSON.stringify(cases.map("
        "(c) => window.MicaAnswerFormat.formatAnswer(c)));</script></body>",
        encoding="utf-8",
    )  # fmt: skip
    profile = tmp_path / "profile"
    run = subprocess.run(
        [str(edge), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
         "--disable-gpu", "--dump-dom", page.as_uri()],
        check=False, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )  # fmt: skip
    m = re.search(r'<pre id="out">(.*?)</pre>', run.stdout, re.DOTALL)
    assert m, run.stdout[-500:] + run.stderr[-500:]
    got = json.loads(html.unescape(m.group(1)))
    assert got == [format_answer(c) for c in cases]
