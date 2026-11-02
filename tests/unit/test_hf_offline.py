"""RF-5 (audit temuan 39): model Hugging Face dimuat offline di mode prod, dev tidak berubah."""

from pathlib import Path

import pytest
from test_retriever import make_kb

from mica import check
from mica.config import load_settings
from mica.kb.embedder import (
    HF_OFFLINE_ENV,
    BgeM3Embedder,
    ModelNotCached,
    force_hf_offline,
    hf_offline,
)
from mica.rag.rerank import RerankedRetriever
from mica.rag.retriever import embedder_for_kb, make_retriever
from mica.setup import EMBEDDER_FILES

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
REV = "9a0624b896d81da7492a910ffa53731274b6cf3d"


class Recorder:
    """Pengganti SentenceTransformer/CrossEncoder: mencatat argumen, tanpa memuat apa pun."""

    def __init__(self, fail: bool = False):
        self.calls: list[dict] = []
        self.fail = fail

    def __call__(self, model_id, **kwargs):
        self.calls.append({"model_id": model_id, **kwargs})
        if self.fail:
            raise OSError("LocalEntryNotFoundError: tidak ada di cache")
        return object()


def _settings(mode: str, reranker: bool = False):
    settings = load_settings(DEV_YAML)
    app = settings.app.model_copy(update={"mode": mode})
    rag = settings.rag.model_copy(
        update={"reranker": settings.rag.reranker.model_copy(update={"enabled": reranker})}
    )
    return settings.model_copy(update={"app": app, "rag": rag})


def test_hf_offline_only_in_prod():
    assert hf_offline("prod") is True
    assert hf_offline("dev") is False


def test_force_hf_offline_sets_both_variables():
    env: dict[str, str] = {}
    force_hf_offline(env)
    assert env == HF_OFFLINE_ENV == {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}


def test_embedder_prod_loads_with_local_files_only(tmp_path):
    loader = Recorder()
    BgeM3Embedder("BAAI/bge-m3", revision=REV, cache_dir=tmp_path, offline=True,
                  loader=loader).load()  # fmt: skip
    (call,) = loader.calls
    assert call["local_files_only"] is True
    assert call["revision"] == REV  # revisi terkunci tetap dipakai
    assert call["model_kwargs"] == {"use_safetensors": True}


def test_embedder_dev_unchanged(tmp_path):
    loader = Recorder()
    BgeM3Embedder("BAAI/bge-m3", revision=REV, cache_dir=tmp_path, loader=loader).load()
    (call,) = loader.calls
    assert "local_files_only" not in call


def test_embedder_prod_missing_cache_points_to_setup(tmp_path):
    emb = BgeM3Embedder("BAAI/bge-m3", revision=REV, cache_dir=tmp_path, offline=True,
                        loader=Recorder(fail=True))  # fmt: skip
    with pytest.raises(ModelNotCached, match="python -m mica setup"):
        emb.load()


def test_embedder_dev_missing_cache_keeps_original_error(tmp_path):
    emb = BgeM3Embedder("BAAI/bge-m3", revision=REV, cache_dir=tmp_path,
                        loader=Recorder(fail=True))  # fmt: skip
    with pytest.raises(OSError) as info:
        emb.load()
    assert not isinstance(info.value, ModelNotCached)


@pytest.mark.parametrize("offline", [True, False])
def test_reranker_local_files_only_follows_offline(tmp_path, offline):
    ce = Recorder()
    base = make_retriever(_settings("dev"), make_kb(), lambda m, r: None)
    reranked = RerankedRetriever(base, "BAAI/bge-reranker-v2-m3", revision=REV, cache_dir=tmp_path,
                                 offline=offline, cross_encoder=ce)  # fmt: skip
    reranked._load()
    (call,) = ce.calls
    assert call.get("local_files_only") is (True if offline else None)


def test_reranker_prod_missing_cache_points_to_setup(tmp_path):
    reranked = RerankedRetriever(None, "BAAI/bge-reranker-v2-m3", revision=REV,
                                 cache_dir=tmp_path, offline=True,
                                 cross_encoder=Recorder(fail=True))  # fmt: skip
    with pytest.raises(ModelNotCached, match="python -m mica setup"):
        reranked._load()


def test_embedder_for_kb_passes_offline():
    kb = make_kb()
    kb.manifest["embedder"]["weights_file"] = "model.safetensors"
    assert embedder_for_kb(kb, offline=True).offline is True
    assert embedder_for_kb(kb).offline is False


@pytest.mark.parametrize(("mode", "offline"), [("prod", True), ("dev", False)])
def test_make_retriever_offline_by_mode(mode, offline):
    kb = make_kb()
    kb.manifest["embedder"]["weights_file"] = "model.safetensors"
    settings = _settings(mode, reranker=True)
    retriever = make_retriever(settings, kb, cross_encoder_loader=object)
    reranked = retriever.inner
    assert isinstance(reranked, RerankedRetriever) and reranked.offline is offline
    dense = reranked.base.sources[1]
    assert dense.embedder.offline is offline


# --- mica check ------------------------------------------------------------------------------


def _kb_root(tmp_path, revision=REV):
    folder = tmp_path / "kb" / "tes-kb"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(
        '{"format_version": 1, "kb_id": "tes-kb", "source_type": "official", "config_hash": "x",'
        f' "n_chunks": 1, "embedder": {{"model": "BAAI/bge-m3", "revision": "{revision}"}}}}',
        encoding="utf-8",
    )
    return tmp_path / "kb"


def _prod_settings(reranker=False, reranker_revision=None):
    settings = _settings("prod", reranker=reranker)
    kb = settings.kb.model_copy(update={"active_id": "tes-kb"})
    rr = settings.rag.reranker.model_copy(update={"revision": reranker_revision})
    rag = settings.rag.model_copy(update={"reranker": rr})
    return settings.model_copy(update={"kb": kb, "rag": rag})


def _snapshot(models, model, rev, files):
    snap = models / f"models--{model.replace('/', '--')}" / "snapshots" / rev
    for f in files:
        (snap / f).parent.mkdir(parents=True, exist_ok=True)
        (snap / f).write_bytes(b"x")


def test_check_cache_row_absent_in_dev(tmp_path):
    assert check._check_hf_cache(_settings("dev"), tmp_path, _kb_root(tmp_path)) is None


def test_check_cache_prod_missing_embedder_fails_with_setup_hint(tmp_path):
    row = check._check_hf_cache(_prod_settings(), tmp_path / "models", _kb_root(tmp_path))
    assert row.status == "GAGAL"
    assert "BAAI/bge-m3" in row.message and "python -m mica setup" in row.message


def test_check_cache_prod_ok_uses_kb_manifest_revision(tmp_path):
    models = tmp_path / "models"
    _snapshot(models, "BAAI/bge-m3", REV, EMBEDDER_FILES)
    row = check._check_hf_cache(_prod_settings(), models, _kb_root(tmp_path))
    assert row.status == "OK", row.message


def test_check_cache_prod_reranker_when_enabled(tmp_path):
    models = tmp_path / "models"
    _snapshot(models, "BAAI/bge-m3", REV, EMBEDDER_FILES)
    root = _kb_root(tmp_path)
    row = check._check_hf_cache(_prod_settings(reranker=True), models, root)
    assert row.status == "GAGAL" and "bge-reranker-v2-m3" in row.message
    rr_rev = "1" * 40
    _snapshot(models, "BAAI/bge-reranker-v2-m3", rr_rev, check.RERANKER_FILES)
    row = check._check_hf_cache(_prod_settings(True, rr_rev), models, root)
    assert row.status == "OK", row.message
