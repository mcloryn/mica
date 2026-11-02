"""Langkah 63: prompt v5 = v2 (paraphrase) + kepala potongan berkelompok + aturan konflik sumber."""

from datetime import date
from pathlib import Path

import pytest
import yaml
from tests.unit.test_pipeline import _pipeline, _settings

from mica.config import load_settings
from mica.core.types import Chunk, ScoredChunk, ScrubbedText
from mica.eval.generation import PROMPT_VARIANTS
from mica.rag.prompts import (
    PROMPT_VERSION_V5,
    SYSTEM_PARAPHRASE,
    build_prompt,
    chunk_group,
    chunk_header_v5,
    prompt_version,
    system_prompt,
)

ROOT = Path(__file__).resolve().parents[2]

PMB = Chunk(
    "pmb/pedoman-pmb-2027#6", "pmb/pedoman-pmb-2027",
    "Pedoman Penerimaan Mahasiswa Baru Universitas Mikroskil Tahun 2027",
    "BAB I › 1.2 Jalur Seleksi", date(2026, 7, 27), "official",
    "a. Jalur PMDK\nb. Jalur Prestasi", False, 5, 6,
)  # fmt: skip
AKADEMIK = Chunk(
    "akademik/peraturan-akademik-2025#14", "akademik/peraturan-akademik-2025",
    "Peraturan Akademik Universitas Mikroskil Tahun 2025", "BAB II › Pasal 4",
    date(2025, 1, 22), "official", "a. jalur seleksi Reguler", False, 9, 9,
)  # fmt: skip
FLAT = Chunk("03_biaya#2", "03_biaya", "Biaya", "Biaya S1", date(2026, 9, 29), "dev", "Rp1", False)


def _hits(*chunks):
    return [ScoredChunk(c, 0.03, {"dense": 1}, {"dense@1": 0.7}) for c in chunks]


def _rules(system: str) -> list[str]:
    return [line.split(". ", 1)[1] for line in system.splitlines() if line[:1].isdigit()]


def test_version_and_variant_registered():
    assert prompt_version("v5") == PROMPT_VERSION_V5 == "v5"
    assert prompt_version("paraphrase") == "v2"
    assert "v5" in PROMPT_VARIANTS


def test_v5_is_v2_plus_two_rules():
    v2, v5 = _rules(SYSTEM_PARAPHRASE), _rules(system_prompt("v5", source_priority=("pmb",)))
    assert [r for r in v5 if r not in v2] == [v5[2], v5[3]]
    assert [r for r in v5 if r in v2] == v2  # urutan aturan v2 tetap
    assert "kepala" in v5[2] and "kelompok" in v5[2]
    assert v5[3] == (
        "Bila potongan dari dokumen berbeda saling bertentangan: (1) untuk pertanyaan tentang "
        "pendaftaran mahasiswa baru, utamakan dokumen kelompok pmb; (2) selain itu, utamakan "
        "dokumen dengan tanggal berlaku terbaru; (3) jangan menggabungkan isi yang saling "
        "bertentangan; (4) sebutkan di jawaban dokumen yang kamu pakai."
    )


def test_v5_priority_order_and_empty():
    two = system_prompt("v5", source_priority=("pmb", "brosur"))
    assert "utamakan dokumen kelompok pmb, lalu brosur;" in two
    none = _rules(system_prompt("v5"))[3]
    assert "pendaftaran" not in none
    assert none.startswith("Bila potongan dari dokumen berbeda saling bertentangan: (1) utamakan")


def test_v2_system_prompt_unchanged():
    assert system_prompt("paraphrase", source_priority=("pmb",)) == SYSTEM_PARAPHRASE


def test_chunk_group_from_doc_id():
    assert chunk_group(PMB) == "pmb"
    assert chunk_group(AKADEMIK) == "akademik"
    assert chunk_group(FLAT) == ""


def test_v5_header():
    assert chunk_header_v5(PMB) == (
        "[ID: pmb/pedoman-pmb-2027#6 | Dokumen: Pedoman Penerimaan Mahasiswa Baru Universitas "
        "Mikroskil Tahun 2027 | Kelompok: pmb | Berlaku sejak: 2026-07-27]"
    )
    assert "Kelompok: - |" in chunk_header_v5(FLAT)


def test_v5_prompt_headers_and_allowed_ids():
    request = build_prompt(
        ScrubbedText("Apa saja jalur pendaftaran?"), [], _hits(PMB, AKADEMIK), "v5", (), ("pmb",)
    )
    assert request.allowed_chunk_ids == (PMB.chunk_id, AKADEMIK.chunk_id)
    for chunk in (PMB, AKADEMIK):
        assert f"{chunk_header_v5(chunk)}\n{chunk.text}" in request.user
    assert "Sumber:" not in request.user
    assert "utamakan dokumen kelompok pmb" in request.system


def test_other_variants_keep_old_label():
    request = build_prompt(ScrubbedText("q"), [], _hits(PMB), "paraphrase", (), ("pmb",))
    assert "[ID: pmb/pedoman-pmb-2027#6 | Sumber: Pedoman" in request.user
    assert "Kelompok:" not in request.user


def test_v5_pipeline_citation_and_fact_check(tmp_path):
    # sitasi tetap divalidasi terhadap allowed_chunk_ids; cek angka tetap memakai teks + judul
    settings = _settings(tmp_path, prompt_variant="v5", source_priority=["pmb"])
    answer = ("answered", "Biaya kuliah S1 Sistem Informasi kelas pagi Rp14.000.000 per tahun.",
              ["03_biaya#2"])  # fmt: skip
    pipeline, llm, _ = _pipeline(tmp_path, answer, settings=settings)
    final, record = pipeline.run("Biaya SI berapa?", [], "s1")
    assert final.status == "answered" and record.prompt_version == "v5"
    assert record.fact_check["passed"] is True
    assert "Kelompok:" in llm.requests[0].user and "utamakan dokumen kelompok pmb" in (
        llm.requests[0].system
    )


def test_v5_pipeline_rejects_citation_outside_allowed(tmp_path):
    settings = _settings(tmp_path, prompt_variant="v5", source_priority=["pmb"])
    pipeline, _, _ = _pipeline(tmp_path, ("answered", "Ada.", ["lain#1"]), settings=settings)
    final, _ = pipeline.run("Biaya SI berapa?", [], "s1")
    assert final.status != "answered"


@pytest.mark.parametrize("name", ["dev.yaml", "prod.yaml"])
def test_configs_activate_v5_with_pmb_priority(name):
    raw = yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))
    assert raw["rag"]["prompt_variant"] == "v5"
    assert raw["rag"]["source_priority"] == ["pmb"]


def test_source_priority_optional(tmp_path):
    raw = yaml.safe_load((ROOT / "config" / "dev.yaml").read_text(encoding="utf-8"))
    del raw["rag"]["source_priority"]
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    assert load_settings(path).rag.source_priority == ()
