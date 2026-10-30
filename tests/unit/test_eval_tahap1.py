"""Langkah 67: Uji RAG Tahap 1 (mica.eval.tahap1). LLM selalu palsu; Groq tidak dipanggil."""

import hashlib
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest
from kb_samples import FakeEmbedder, make_kb_folder

from mica.config import load_settings
from mica.core.types import LlmAnswer
from mica.eval import __main__ as eval_cli
from mica.eval.generation import QuotaExhausted
from mica.eval.tahap1 import (
    ANSWERS_FILE,
    ATTEMPTS_FILE,
    LABELS,
    MANIFEST_FILE,
    N_QUESTIONS,
    QUESTIONS_SHA256,
    QUOTA_MESSAGE,
    SHEET_SEED,
    SHEETS,
    FrozenSystem,
    Tahap1Error,
    load_test_questions,
    read_answers,
    run_tahap1,
    shuffled_ids,
    write_rating_sheets,
)
from mica.kb.index import build_kb, load_kb
from mica.rag.llm import ProviderFailed

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
REAL_CSV = ROOT / "data" / "eval" / "official" / "uji-tahap1-129.csv"
PREREG = ROOT / "docs" / "PRA-REGISTRASI-TAHAP1.md"
MODEL = "groq:openai/gpt-oss-120b"
USAGE = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
# FakeEmbedder (hash teks) tidak memberi cosine yang bermakna: ambang 0 di tes supaya LLM dipanggil
FROZEN_TEST = FrozenSystem(n_chunks=None, gate_threshold=0.0)

CSV_TEXT = (
    "id;no_asal;penanya;topik;pertanyaan\n"
    "t1-001;1;siswa SMA/SMK kelas 12;1;Berapa biaya pendaftaran?\n"
    "t1-002;2;orang tua calon mahasiswa;8;Apa syaratnya? Anak saya lulusan SMK.\n"
    "t1-004;4;siswa SMA/SMK kelas 12;3;Cuaca hari ini?\n"
    "t1-005;5;lulusan S1 yang ingin lanjut S2;11;Ada beasiswa prestasi?\n"
)


class FakeProvider:
    name = MODEL
    model = "openai/gpt-oss-120b"

    def __init__(self, failures=()):
        self.failures = list(failures)
        self.questions: list[str] = []

    def request_body(self, request):
        return {"model": self.model, "system": request.system, "user": request.user}

    def generate(self, request, timeout_s):
        question = re.search(r"<<<PERTANYAAN>>>\n(.*?)\n<<<AKHIR", request.user, re.DOTALL)
        self.questions.append(question.group(1) if question else request.user)
        if self.failures:
            raise self.failures.pop(0)
        if self.questions[-1].startswith("Cuaca"):
            return LlmAnswer("not_found", "", (), self.name, 0.5, dict(USAGE))
        cites = tuple(request.allowed_chunk_ids)
        return LlmAnswer("answered", "Jawaban tanpa angka.", cites, self.name, 0.5, dict(USAGE))


@pytest.fixture
def env(tmp_path):
    settings = load_settings(DEV_YAML)
    rag = settings.rag.model_copy(
        update={"gate": settings.rag.gate.model_copy(update={"threshold": 0.0})}
    )
    settings = settings.model_copy(update={"rag": rag})
    kb_root = tmp_path / "kb"
    build_kb(make_kb_folder(tmp_path / "src"), settings.kb.active_id, "official", settings.kb,
             FakeEmbedder(), kb_root)  # fmt: skip
    kb = load_kb(settings.kb.active_id, kb_root)
    csv_path = tmp_path / "soal.csv"
    csv_path.write_bytes(CSV_TEXT.encode("utf-8"))
    return settings, kb, csv_path, tmp_path / "runs" / "tahap1"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _run(env, provider, **kw):
    settings, kb, csv_path, out = env
    kw.setdefault("frozen", FROZEN_TEST)
    return run_tahap1(settings, kb, csv_path, out, provider=provider, embedder=FakeEmbedder(),
                      sleep=lambda s: None, expected_sha=_sha(csv_path), expected_n=4,
                      environment={"git_dirty": False}, progress=None, **kw)  # fmt: skip


# --- CSV dan SHA ----------------------------------------------------------------------


def test_real_csv_matches_prereg_sha_and_count():
    assert _sha(REAL_CSV) == QUESTIONS_SHA256
    rows = load_test_questions(REAL_CSV)
    assert len(rows) == N_QUESTIONS == 129
    assert rows[0]["id"] == "t1-001" and all(r["id"].startswith("t1-") for r in rows)
    assert QUESTIONS_SHA256 in PREREG.read_text(encoding="utf-8")


def test_csv_semicolon_parsed(env):
    _, _, csv_path, _ = env
    rows = load_test_questions(csv_path, _sha(csv_path), 4)
    assert rows[1]["pertanyaan"] == "Apa syaratnya? Anak saya lulusan SMK."
    assert rows[1]["penanya"] == "orang tua calon mahasiswa" and rows[1]["topik"] == "8"


def test_csv_sha_mismatch_stops(env):
    _, _, csv_path, _ = env
    with pytest.raises(Tahap1Error, match="SHA-256"):
        load_test_questions(csv_path, "0" * 64, 4)


def test_csv_wrong_count_stops(env):
    _, _, csv_path, _ = env
    with pytest.raises(Tahap1Error, match="baris"):
        load_test_questions(csv_path, _sha(csv_path), 129)


def test_sha_mismatch_stops_before_any_answer(env):
    settings, kb, csv_path, out = env
    provider = FakeProvider()
    with pytest.raises(Tahap1Error):
        run_tahap1(settings, kb, csv_path, out, provider=provider, embedder=FakeEmbedder(),
                   frozen=FROZEN_TEST, expected_n=4, progress=None)  # fmt: skip
    assert provider.questions == [] and not out.exists()


# --- sistem beku ------------------------------------------------------------------------


def test_dev_config_matches_frozen_system():
    settings = load_settings(DEV_YAML)
    rag = settings.rag
    assert settings.kb.active_id == FrozenSystem().kb_id
    assert settings.llm.chain[0] == FrozenSystem().model
    assert rag.gate.threshold == FrozenSystem().gate_threshold == 0.50
    assert (rag.retriever, rag.rrf_k, rag.top_k, rag.prompt_variant) == ("hybrid", 60, 5, "v5")
    assert rag.fact_check.enabled and not rag.reranker.enabled


def test_frozen_mismatch_stops(env):
    provider = FakeProvider()
    with pytest.raises(Tahap1Error, match="gate_threshold"):
        _run(env, provider, frozen=FrozenSystem(n_chunks=None))  # config tes 0.0, pra-reg 0.50
    assert provider.questions == [] and not env[3].exists()


def test_other_provider_stops(env):
    provider = FakeProvider()
    provider.name = "groq:openai/gpt-oss-20b"
    with pytest.raises(Tahap1Error, match="penyedia"):
        _run(env, provider)


# --- jawaban, resume, percobaan ---------------------------------------------------------


def test_answers_jsonl_fields(env):
    result = _run(env, FakeProvider(), limit=2)
    rows = read_answers(env[3] / ANSWERS_FILE)
    assert [r["id"] for r in rows] == ["t1-001", "t1-002"] == [r["id"] for r in result.answered_now]
    row = rows[0]
    assert row["status"] == "answered" and row["status_label"] == "dijawab"
    assert row["final_text"].startswith("Jawaban tanpa angka.")
    assert row["citations"] and len(row["sources_shown"]) == len(set(row["citations"]))
    assert len(row["top5"]) == 5
    assert set(row["top5"][0]) >= {"chunk_id", "title", "page_start", "section", "text"}
    assert row["dense_at_1"] is not None
    assert row["kb_id"] == env[1].kb_id and row["prompt_version"] == "v5"
    assert row["model"] == MODEL and row["config_hash"] == env[0].config_hash()
    assert row["usage"] == USAGE and row["api_attempts"] == 1 and row["question_attempts"] == 1
    assert row["asked_at"] and row["latency_s"] >= 0 and "total" in row["timings"]

    manifest = json.loads((env[3] / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["questions_sha256"] == _sha(env[2])
    assert (manifest["n_done"], manifest["n_total"]) == (2, 4)
    assert manifest["kb_id"] == env[1].kb_id and manifest["model"] == MODEL
    assert manifest["started_at"] and manifest["finished_at"] is None
    assert result.sheets == [] and not (env[3] / SHEETS[0]).exists()


def test_refusal_by_llm_is_gate_2(env):
    _run(env, FakeProvider())
    row = next(r for r in read_answers(env[3] / ANSWERS_FILE) if r["id"] == "t1-004")
    assert row["status"] == "refused_llm" and row["refused_by_gate"] == 2
    assert row["llm_status"] == "not_found" and row["sources_shown"] == []


def test_resume_does_not_answer_again(env):
    first = FakeProvider()
    _run(env, first, limit=2)
    second = FakeProvider()
    result = _run(env, second)
    assert second.questions == [
        "Cuaca hari ini?",
        "Ada beasiswa prestasi?",
    ]  # hanya sisa soal
    ids = [r["id"] for r in read_answers(env[3] / ANSWERS_FILE)]
    assert ids == ["t1-001", "t1-002", "t1-004", "t1-005"] and result.n_done == 4
    third = FakeProvider()
    _run(env, third)
    assert third.questions == []
    assert len(read_answers(env[3] / ANSWERS_FILE)) == 4
    manifest = json.loads((env[3] / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["finished_at"] and len(manifest["runs"]) == 3


def test_resume_with_other_system_stops(env, monkeypatch):
    _run(env, FakeProvider(), limit=1)
    settings, kb, csv_path, out = env
    llm = settings.llm.model_copy(update={"temperature": 0.9})
    changed = (settings.model_copy(update={"llm": llm}), kb, csv_path, out)
    with pytest.raises(Tahap1Error, match="config_hash"):
        _run(changed, FakeProvider())


def test_timeout_retried_and_logged(env):
    provider = FakeProvider(failures=[ProviderFailed("timeout 10 detik")])
    _run(env, provider, limit=1)
    rows = read_answers(env[3] / ANSWERS_FILE)
    assert len(rows) == 1 and rows[0]["question_attempts"] == 2 and rows[0]["api_attempts"] == 2
    attempts = read_answers(env[3] / ATTEMPTS_FILE)
    assert [a["outcome"] for a in attempts] == ["unavailable", "ok"]
    assert "timeout" in attempts[0]["reason"]


def test_persistent_api_error_leaves_question_unanswered(env):
    failures = [ProviderFailed("HTTP 500", status=500)] * 3
    result = _run(env, FakeProvider(failures=failures), limit=1)
    assert result.skipped == ["t1-001"] and read_answers(env[3] / ANSWERS_FILE) == []
    assert len(read_answers(env[3] / ATTEMPTS_FILE)) == 3
    # run berikutnya mencoba lagi soal yang belum terjawab
    _run(env, FakeProvider(), limit=1)
    assert [r["id"] for r in read_answers(env[3] / ANSWERS_FILE)] == ["t1-001"]


def test_quota_429_stops_cleanly(env):
    quota = ProviderFailed("HTTP 429", status=429, retry_after="3600")
    provider = FakeProvider()
    _run(env, provider, limit=1)
    provider = FakeProvider(failures=[quota])
    with pytest.raises(QuotaExhausted):
        _run(env, provider)
    assert len(provider.questions) == 1  # kuota harian tidak dicoba ulang
    assert [r["id"] for r in read_answers(env[3] / ANSWERS_FILE)] == ["t1-001"]
    assert read_answers(env[3] / ATTEMPTS_FILE)[-1]["outcome"] == "quota"
    manifest = json.loads((env[3] / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["n_done"] == 1 and manifest["runs"][-1]["stopped"] == "kuota habis"


def test_short_429_waited_then_answered(env):
    provider = FakeProvider(failures=[ProviderFailed("HTTP 429", status=429, retry_after="2")])
    _run(env, provider, limit=1)
    row = read_answers(env[3] / ANSWERS_FILE)[0]
    assert row["status"] == "answered" and row["api_attempts"] == 2


def test_cli_quota_message(monkeypatch, capsys):
    def boom(args, factory):
        raise QuotaExhausted(MODEL, None, None)

    monkeypatch.setattr(eval_cli, "cmd_tahap1", boom)
    code = eval_cli.main(["tahap1", "--questions", "x.csv", "--out", "y"])
    assert code == 3 and QUOTA_MESSAGE in capsys.readouterr().err


def test_cli_parser_tahap1():
    args = eval_cli.build_parser().parse_args(
        ["tahap1", "--questions", "q.csv", "--out", "o", "--limit", "3"]
    )
    assert args.limit == 3 and args.config == Path("config/dev.yaml")


# --- lembar penilaian -------------------------------------------------------------------


def _sheet_xml(path, n):
    with zipfile.ZipFile(path) as zf:
        return zf.read(f"xl/worksheets/sheet{n}.xml").decode("utf-8")


def _cells(xml):
    return [
        re.findall(r'<t xml:space="preserve">(.*?)</t>', row, re.DOTALL)
        for row in re.findall(r"<row [^>]*>(.*?)</row>", xml, re.DOTALL)
    ]


def test_shuffle_deterministic():
    ids = [f"t1-{i:03d}" for i in range(1, 130)]
    assert shuffled_ids(ids) == shuffled_ids(ids, SHEET_SEED) == shuffled_ids(list(ids))
    assert shuffled_ids(ids) != ids and sorted(shuffled_ids(ids)) == ids


def test_sheets_only_after_all_answered(env):
    _run(env, FakeProvider(), limit=3)
    questions = load_test_questions(env[2], _sha(env[2]), 4)
    with pytest.raises(Tahap1Error, match="semua soal"):
        write_rating_sheets(env[3], questions)
    assert not (env[3] / SHEETS[0]).exists()


def test_rating_sheets(env):
    result = _run(env, FakeProvider())
    paths = [env[3] / name for name in SHEETS]
    assert result.sheets == paths
    assert paths[0].read_bytes() == paths[1].read_bytes()  # identik

    with zipfile.ZipFile(paths[0]) as zf:
        workbook = zf.read("xl/workbook.xml").decode("utf-8")
        for name in zf.namelist():  # semua bagian XML terbentuk baik
            ElementTree.fromstring(zf.read(name))
    assert re.findall(r'<sheet name="([^"]+)"', workbook) == ["nilai", "potongan", "petunjuk"]

    nilai = _cells(_sheet_xml(paths[0], 1))
    assert nilai[0] == ["id", "pertanyaan", "jawaban MICA", "sitasi", "label",
                        "klaim yang dikarang", "catatan"]  # fmt: skip
    ids = ["t1-001", "t1-002", "t1-004", "t1-005"]
    assert [r[0] for r in nilai[1:]] == shuffled_ids(ids)
    assert all(r[4:] == ["", "", ""] for r in nilai[1:])  # tanpa kunci jawaban
    header = " ".join(nilai[0]).lower()
    for hidden in ("topik", "penanya", "persona", "skor", "dense", "status", "gerbang"):
        assert hidden not in header
    xml = _sheet_xml(paths[0], 1)
    for hidden in ("orang tua calon mahasiswa", "refused", "dijawab", "gerbang"):
        assert hidden not in xml
    choices = re.search(r"<formula1>(.*?)</formula1>", xml).group(1)
    assert choices == '"benar,tidak lengkap,halusinasi,tolak tepat,tolak keliru"'
    assert 'sqref="E2:E5"' in xml

    potongan = _cells(_sheet_xml(paths[0], 2))
    assert potongan[0] == ["id", "urutan", "sumber", "teks potongan"]
    assert len(potongan) == 1 + 4 * 5
    assert [r[0] for r in potongan[1::5]] == shuffled_ids(ids)

    petunjuk = "\n".join(c for row in _cells(_sheet_xml(paths[0], 3)) for c in row)
    assert "Nilai sendiri, jangan melihat lembar penilai lain, cek ke dokumen resmi." in petunjuk
    for label, definition in LABELS:
        assert f"{label}: {definition}" in petunjuk

    # lembar yang sudah ada (mungkin sudah diisi penilai) tidak ditimpa
    paths[0].write_bytes(b"diisi penilai")
    _run(env, FakeProvider())
    assert paths[0].read_bytes() == b"diisi penilai"


def test_label_definitions_copied_from_prereg():
    text = re.sub(r"\s+", " ", PREREG.read_text(encoding="utf-8"))
    for label, definition in LABELS:
        assert f"**{label}**: {definition}" in text
