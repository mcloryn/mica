import ast
import dataclasses
import re
from datetime import date
from pathlib import Path

import pytest

from mica.config import ConfigError
from mica.core import types
from mica.core.types import (
    Chunk,
    ErrorCode,
    FinalAnswer,
    LlmAnswer,
    LlmRequest,
    ScoredChunk,
    ScrubbedText,
    Turn,
)

ROOT = Path(__file__).resolve().parents[2]


def _chunk() -> Chunk:
    return Chunk(
        chunk_id="brosur#1",
        doc_id="brosur",
        doc_title="Brosur PMB",
        section="Biaya",
        valid_from=date(2026, 1, 1),
        source_type="official",
        text="Biaya pendaftaran Rp300.000.",
        is_table=False,
    )


def _instances() -> list:
    chunk = _chunk()
    return [
        chunk,
        ScoredChunk(chunk=chunk, score=0.9, ranks={"bm25": 1, "dense": 2}),
        Turn(question=ScrubbedText("berapa biaya?"), answer="Rp300.000"),
        LlmRequest(system="sys", user="q", allowed_chunk_ids=("brosur#1",)),
        LlmAnswer(
            status="answered",
            answer="Rp300.000",
            citations=("brosur#1",),
            provider="groq:model-a",
            latency_s=1.2,
        ),
        FinalAnswer(status="answered", text="Rp300.000", sources=(chunk,), timings={"llm": 1.2}),
    ]


@pytest.mark.parametrize("obj", _instances(), ids=lambda o: type(o).__name__)
def test_dataclass_frozen(obj):
    field = dataclasses.fields(obj)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, field, None)


def test_sequence_fields_are_tuples():
    for obj in _instances():
        for f in dataclasses.fields(obj):
            assert not isinstance(getattr(obj, f.name), list), f"{type(obj).__name__}.{f.name}"


def test_all_sdd_dataclasses_present():
    names = {"Chunk", "ScoredChunk", "Turn", "LlmRequest", "LlmAnswer", "FinalAnswer"}
    assert names <= {type(o).__name__ for o in _instances()}
    assert all(dataclasses.is_dataclass(getattr(types, n)) for n in names)


def _sdd_8_1_codes() -> set[str]:
    sdd = (ROOT / "docs" / "SDD.md").read_text(encoding="utf-8")
    section = sdd.split("### 8.1", 1)[1].split("\n### ", 1)[0]
    codes: set[str] = set()
    for line in section.splitlines():
        if line.startswith("|"):
            last_cell = line.rstrip().rstrip("|").rsplit("|", 1)[-1]
            codes |= set(re.findall(r"`([A-Z_]+)`", last_cell))
    return codes


def test_error_code_covers_sdd_8_1():
    codes = _sdd_8_1_codes()
    assert len(codes) >= 12
    assert codes <= {c.value for c in ErrorCode}


def test_error_code_includes_config_codes():
    assert ErrorCode.CFG_INVALID == "CFG_INVALID"
    assert ErrorCode.CFG_GEMINI_IN_PROD == "CFG_GEMINI_IN_PROD"


def test_config_error_uses_error_code():
    err = ConfigError(ErrorCode.CFG_INVALID, "x")
    assert isinstance(err.code, ErrorCode)
    assert err.code == "CFG_INVALID"


def test_types_module_imports_no_mica_module():
    tree = ast.parse(Path(types.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "impor relatif tidak boleh"
            imported.append(node.module or "")
    assert imported
    assert not [m for m in imported if m == "mica" or m.startswith("mica.")]


def test_scrubbed_text_is_str_marker():
    text = ScrubbedText("halo")
    assert isinstance(text, str)
    assert text == "halo"
    assert not isinstance("halo", ScrubbedText)
