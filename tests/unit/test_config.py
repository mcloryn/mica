from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from mica.config import (
    CFG_GEMINI_IN_KIOSK,
    CFG_INVALID,
    ConfigError,
    Settings,
    load_settings,
)

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
KIOSK_YAML = ROOT / "config" / "kiosk.yaml"


@pytest.fixture(autouse=True)
def _no_env_keys(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def _dev_raw() -> dict:
    return yaml.safe_load(DEV_YAML.read_text(encoding="utf-8"))


def _write(tmp_path: Path, raw: dict, name: str = "cfg.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _dummy(key: str):
    # revisi model berupa hash commit; field null lain berupa angka
    return "0" * 40 if key == "revision" else 1


def _fill_nulls(node):
    # Isi semua null dengan nilai dummy supaya bisa diuji di mode kiosk.
    if isinstance(node, dict):
        return {k: (_dummy(k) if v is None else _fill_nulls(v)) for k, v in node.items()}
    return node


def _complete_kiosk_raw() -> dict:
    raw = _fill_nulls(_dev_raw())
    raw["app"]["mode"] = "kiosk"
    raw["kb"]["active_id"] = "official-2026-11-02"
    raw["llm"]["chain"] = ["groq:model-a", "groq:model-b"]
    return raw


def test_dev_yaml_loads():
    settings = load_settings(DEV_YAML)
    assert settings.app.mode == "dev"
    assert settings.rag.top_k == 5


def test_complete_kiosk_config_loads(tmp_path):
    settings = load_settings(_write(tmp_path, _complete_kiosk_raw()))
    assert settings.app.mode == "kiosk"


def test_unknown_field_rejected(tmp_path):
    raw = _dev_raw()
    raw["rag"]["topk"] = 5
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert exc.value.code == CFG_INVALID
    assert "rag.topk" in str(exc.value)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("rag", "top_k", "lima"),
        ("rag", "top_k", "5"),
        ("rag", "retriever", "vector"),
        ("ui", "fullscreen", "ya"),
    ],
)
def test_wrong_type_rejected(tmp_path, section, field, value):
    raw = _dev_raw()
    raw[section][field] = value
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert exc.value.code == CFG_INVALID
    assert f"{section}.{field}" in str(exc.value)


def test_unknown_llm_provider_rejected(tmp_path):
    raw = _dev_raw()
    raw["llm"]["chain"] = ["openai:gpt-x"]
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert exc.value.code == CFG_INVALID
    assert "llm.chain" in str(exc.value)


def test_gemini_rejected_in_kiosk(tmp_path):
    raw = _complete_kiosk_raw()
    raw["llm"]["chain"].append("gemini:gemini-flash")
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert exc.value.code == CFG_GEMINI_IN_KIOSK


def test_gemini_check_runs_before_other_validation(tmp_path):
    raw = _dev_raw()  # masih berisi null dan placeholder
    raw["app"]["mode"] = "kiosk"
    raw["rag"]["top_k"] = "lima"
    raw["llm"]["chain"] = ["gemini:gemini-flash"]
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert exc.value.code == CFG_GEMINI_IN_KIOSK


def test_gemini_accepted_in_dev(tmp_path):
    raw = _dev_raw()
    raw["llm"]["chain"] = ["gemini:gemini-flash"]
    settings = load_settings(_write(tmp_path, raw))
    assert settings.llm.chain == ("gemini:gemini-flash",)


def test_null_rejected_in_kiosk(tmp_path):
    raw = _complete_kiosk_raw()
    raw["rag"]["gate"]["threshold"] = None
    raw["vision"]["dwell_s"] = None
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert exc.value.code == CFG_INVALID
    assert "rag.gate.threshold" in str(exc.value)
    assert "vision.dwell_s" in str(exc.value)


def test_placeholder_model_id_rejected_in_kiosk(tmp_path):
    raw = _complete_kiosk_raw()
    raw["llm"]["chain"] = ["groq:<id gpt-oss-120b>"]
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert exc.value.code == CFG_INVALID
    assert "llm.chain[0]" in str(exc.value)


def test_current_kiosk_yaml_rejected():
    with pytest.raises(ConfigError) as exc:
        load_settings(KIOSK_YAML)
    assert exc.value.code == CFG_INVALID
    message = str(exc.value)
    for field in ("kb.chunk_tokens", "rag.gate.threshold", "llm.timeout_s", "llm.chain[0]"):
        assert field in message


def _reorder(node):
    if isinstance(node, dict):
        return {k: _reorder(node[k]) for k in reversed(list(node))}
    return node


def test_hash_ignores_key_order(tmp_path):
    raw = _dev_raw()
    a = load_settings(_write(tmp_path, raw, "a.yaml"))
    b = load_settings(_write(tmp_path, _reorder(raw), "b.yaml"))
    assert a.config_hash() == b.config_hash()


def test_hash_changes_with_top_k(tmp_path):
    raw = _dev_raw()
    a = load_settings(_write(tmp_path, raw, "a.yaml"))
    raw["rag"]["top_k"] = 7
    b = load_settings(_write(tmp_path, raw, "b.yaml"))
    assert a.config_hash() != b.config_hash()


def test_hash_ignores_api_keys(tmp_path):
    env_a = tmp_path / "a.env"
    env_a.write_text("GROQ_API_KEY=key-satu\n", encoding="utf-8")
    env_b = tmp_path / "b.env"
    env_b.write_text("GROQ_API_KEY=key-dua\nGEMINI_API_KEY=lain\n", encoding="utf-8")
    a = load_settings(DEV_YAML, env_a)
    b = load_settings(DEV_YAML, env_b)
    assert a.api_keys.groq.get_secret_value() == "key-satu"
    assert a.config_hash() == b.config_hash() == load_settings(DEV_YAML).config_hash()


def test_api_keys_from_environment(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "dari-env")
    settings = load_settings(DEV_YAML)
    assert settings.api_keys.groq.get_secret_value() == "dari-env"
    assert settings.api_keys.gemini is None


def test_api_keys_in_yaml_rejected(tmp_path):
    raw = _dev_raw()
    raw["api_keys"] = {"groq": "bocor"}
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert exc.value.code == CFG_INVALID
    assert "bocor" not in str(exc.value)


def test_settings_frozen():
    settings = load_settings(DEV_YAML)
    with pytest.raises(ValidationError):
        settings.rag.top_k = 10
    with pytest.raises(ValidationError):
        settings.app = settings.app
    with pytest.raises(AttributeError):
        settings.ui.topics.append("Lain")  # tuple, bukan list
    assert isinstance(settings, Settings)


def test_api_key_hidden_in_repr_and_str(tmp_path):
    env = tmp_path / ".env"
    env.write_text('GROQ_API_KEY="rahasia-groq"\nGEMINI_API_KEY=rahasia-gemini\n', encoding="utf-8")
    settings = load_settings(DEV_YAML, env)
    for text in (repr(settings), str(settings), repr(settings.api_keys), str(settings.api_keys)):
        assert "rahasia-groq" not in text
        assert "rahasia-gemini" not in text
    assert settings.api_keys.groq.get_secret_value() == "rahasia-groq"


def test_current_kiosk_yaml_reports_active_id_placeholder():
    with pytest.raises(ConfigError) as exc:
        load_settings(KIOSK_YAML)
    assert "kb.active_id" in str(exc.value)


@pytest.mark.parametrize("field", ["rrf_k", "candidates_per_retriever"])
def test_hybrid_params_required_for_hybrid_in_kiosk(tmp_path, field):
    raw = _complete_kiosk_raw()
    raw["rag"]["retriever"] = "hybrid"
    raw["rag"][field] = None
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert exc.value.code == CFG_INVALID
    assert f"rag.{field}" in str(exc.value)


@pytest.mark.parametrize("retriever", ["bm25", "dense"])
def test_hybrid_params_optional_for_other_retrievers_in_kiosk(tmp_path, retriever):
    raw = _complete_kiosk_raw()
    raw["rag"]["retriever"] = retriever
    raw["rag"]["rrf_k"] = None
    raw["rag"]["candidates_per_retriever"] = None
    if retriever == "bm25":
        raw["rag"]["gate"]["threshold"] = None
    settings = load_settings(_write(tmp_path, raw))
    assert settings.rag.rrf_k is None


def test_stt_threads_required_for_faster_whisper_in_kiosk(tmp_path):
    raw = _complete_kiosk_raw()
    raw["audio"]["stt"]["backend"] = "faster_whisper"
    raw["audio"]["stt"]["threads"] = None
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert exc.value.code == CFG_INVALID
    assert "audio.stt.threads" in str(exc.value)


def test_stt_threads_optional_for_groq_whisper_in_kiosk(tmp_path):
    raw = _complete_kiosk_raw()
    raw["audio"]["stt"]["backend"] = "groq_whisper"
    raw["audio"]["stt"]["threads"] = None
    settings = load_settings(_write(tmp_path, raw))
    assert settings.audio.stt.threads is None


def test_environment_variable_wins_over_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=dari-file\nGEMINI_API_KEY=gemini-file\n", encoding="utf-8")
    monkeypatch.setenv("GROQ_API_KEY", "dari-env")
    settings = load_settings(DEV_YAML, env)
    assert settings.api_keys.groq.get_secret_value() == "dari-env"
    # env_file tetap dipakai sebagai cadangan
    assert settings.api_keys.gemini.get_secret_value() == "gemini-file"


def test_embedder_revision_null_allowed_in_dev(tmp_path):
    raw = _dev_raw()
    raw["kb"]["embedder"]["revision"] = None
    assert load_settings(_write(tmp_path, raw)).kb.embedder.revision is None


def test_embedder_revision_required_in_kiosk(tmp_path):
    raw = _complete_kiosk_raw()
    raw["kb"]["embedder"]["revision"] = None
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert exc.value.code == CFG_INVALID
    assert "kb.embedder.revision" in str(exc.value)


@pytest.mark.parametrize(
    "revision", ["main", "9a0624b", "9A0624B896D81DA7492A910FFA53731274B6CF3D"]
)
def test_embedder_revision_must_be_full_hash(tmp_path, revision):
    raw = _dev_raw()
    raw["kb"]["embedder"]["revision"] = revision
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert "kb.embedder.revision" in str(exc.value)


def test_dev_yaml_pins_embedder_revision():
    revision = load_settings(DEV_YAML).kb.embedder.revision
    assert revision is not None and len(revision) == 40


def test_reranker_revision_required_in_kiosk_when_enabled(tmp_path):
    raw = _complete_kiosk_raw()
    raw["rag"]["reranker"]["enabled"] = True
    raw["rag"]["reranker"]["revision"] = None
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert "rag.reranker.revision" in str(exc.value)


def test_reranker_revision_optional_in_kiosk_when_disabled(tmp_path):
    raw = _complete_kiosk_raw()
    raw["rag"]["reranker"]["enabled"] = False
    raw["rag"]["reranker"]["revision"] = None
    assert load_settings(_write(tmp_path, raw)).rag.reranker.revision is None


def test_reranker_revision_must_be_full_hash(tmp_path):
    raw = _dev_raw()
    raw["rag"]["reranker"]["revision"] = "main"
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert "rag.reranker.revision" in str(exc.value)


def test_vision_conf_imgsz_required_in_kiosk(tmp_path):
    raw = _complete_kiosk_raw()
    raw["vision"]["conf"] = None
    raw["vision"]["imgsz"] = None
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert "vision.conf" in str(exc.value) and "vision.imgsz" in str(exc.value)


@pytest.mark.parametrize(
    ("field", "value"), [("conf", 1.5), ("min_box_height_ratio", -0.1), ("imgsz", 0)]
)
def test_vision_values_range_checked(tmp_path, field, value):
    raw = _dev_raw()
    raw["vision"][field] = value
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert f"vision.{field}" in str(exc.value)


def test_dev_yaml_vision_tbd_values_stay_null():
    vision = load_settings(DEV_YAML).vision
    assert (vision.dwell_s, vision.leave_s, vision.min_box_height_ratio, vision.fps_busy) == (
        None,
        None,
        None,
        None,
    )


def test_box_upper_required_in_kiosk_when_used(tmp_path):
    raw = _complete_kiosk_raw()
    raw["vision"]["region"] = "box_upper"
    raw["vision"]["box_upper"]["top"] = None
    with pytest.raises(ConfigError) as exc:
        load_settings(_write(tmp_path, raw))
    assert "vision.box_upper.top" in str(exc.value)


def test_box_upper_optional_in_kiosk_for_keypoint_torso(tmp_path):
    raw = _complete_kiosk_raw()
    raw["vision"]["model"] = "yolo26n-pose"
    raw["vision"]["region"] = "keypoint_torso"
    raw["vision"]["box_upper"] = {"top": None, "bottom": None, "side": None}
    assert load_settings(_write(tmp_path, raw)).vision.region == "keypoint_torso"


def test_dev_yaml_color_values_stay_null():
    vision = load_settings(DEV_YAML).vision
    assert vision.color.min_majority is None
    assert (vision.box_upper.top, vision.box_upper.bottom, vision.box_upper.side) == (
        None,
        None,
        None,
    )
