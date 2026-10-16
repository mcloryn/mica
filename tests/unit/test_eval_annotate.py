import csv
import json
from pathlib import Path

import pytest
from kb_samples import FakeEmbedder, make_kb_folder

from mica.config import load_settings
from mica.eval import __main__ as eval_cli
from mica.eval.annotate import POOL_COLUMNS, export_pool, import_pool
from mica.eval.dataset import DatasetError, load_questions, retrieval_query
from mica.kb.index import build_kb, load_kb

DEV_YAML = Path(__file__).resolve().parents[2] / "config" / "dev.yaml"

QUESTIONS = [
    {
        "qid": "q1",
        "question": "Berapa biaya pendaftaran?",
        "type": "answerable",
        "topic": "Biaya",
        "gold_chunk_ids": [],
        "reference_answer": "Rp300.000.",
        "split": "dev",
        "prev_qid": None,
        "gold_refs": ["biaya::Beasiswa"],
    },
    {
        "qid": "q2",
        "question": "Kalau beasiswa?",
        "type": "followup",
        "topic": "Beasiswa",
        "gold_chunk_ids": [],
        "reference_answer": "Nilai rapor minimal 85.",
        "split": "dev",
        "prev_qid": "q1",
        "gold_refs": [],
    },
    {
        "qid": "q3",
        "question": "Apakah ada asrama?",
        "type": "out_of_kb",
        "oos_level": "jauh",
        "topic": "Fasilitas",
        "gold_chunk_ids": [],
        "reference_answer": "",
        "split": "dev",
        "prev_qid": None,
    },
]


def write_dataset(path: Path, questions=QUESTIONS) -> Path:
    path.write_text(
        "".join(json.dumps(q, ensure_ascii=False) + "\n" for q in questions), encoding="utf-8"
    )
    return path


class SpyEmbedder(FakeEmbedder):
    def __init__(self):
        super().__init__()
        self.queries = []

    def embed(self, texts):
        self.queries.extend(texts)
        return super().embed(texts)


@pytest.fixture
def env(tmp_path):
    settings = load_settings(DEV_YAML)
    kb_root = tmp_path / "kb"
    build_kb(
        make_kb_folder(tmp_path / "src"), settings.kb.active_id, "dev", settings.kb,
        FakeEmbedder(), kb_root,
    )
    kb = load_kb(settings.kb.active_id, kb_root)
    dataset = write_dataset(tmp_path / "questions.jsonl")
    return settings, kb, kb_root, dataset, tmp_path


def read_pool(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_pool(path: Path, rows, delimiter=","):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=POOL_COLUMNS, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


# --- dataset ---------------------------------------------------------------


def test_load_questions_valid(tmp_path):
    questions = load_questions(write_dataset(tmp_path / "q.jsonl"))
    assert [q["qid"] for q in questions] == ["q1", "q2", "q3"]
    assert questions[0]["gold_refs"] == ["biaya::Beasiswa"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda qs: qs[1].update(qid="q1"), "qid ganda"),
        (lambda qs: qs[0].update(type="answerabel"), "type"),
        (lambda qs: qs[1].update(prev_qid="q9"), "prev_qid 'q9' tidak ada"),
        (lambda qs: qs[1].update(prev_qid=None), "followup wajib punya prev_qid"),
        (lambda qs: qs[0].update(gold_refs=["biaya-Beasiswa"]), "gold_ref"),
    ],
)
def test_load_questions_rejects_invalid(tmp_path, change, message):
    questions = [dict(q) for q in QUESTIONS]
    change(questions)
    with pytest.raises(DatasetError) as exc:
        load_questions(write_dataset(tmp_path / "q.jsonl", questions))
    assert message in str(exc.value)


def test_load_questions_rejects_non_json(tmp_path):
    path = tmp_path / "q.jsonl"
    path.write_text("Dua bagian, commit terpisah.\n", encoding="utf-8")
    with pytest.raises(DatasetError) as exc:
        load_questions(path)
    assert "baris 1" in str(exc.value)


def test_followup_query_concat():
    by_qid = {q["qid"]: q for q in QUESTIONS}
    assert retrieval_query(QUESTIONS[1], by_qid) == "Berapa biaya pendaftaran? Kalau beasiswa?"
    assert retrieval_query(QUESTIONS[0], by_qid) == "Berapa biaya pendaftaran?"


# --- export ----------------------------------------------------------------


def test_export_pool_rows_and_meta(env):
    settings, kb, _, dataset, tmp = env
    out = tmp / "eval" / "pool.csv"
    result = export_pool(settings, kb, dataset, out, embedder_factory=lambda m, r: FakeEmbedder())
    rows = read_pool(out)
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
    assert tuple(rows[0].keys()) == POOL_COLUMNS
    assert {r["qid"] for r in rows} == {"q1", "q2"}  # out_of_kb tidak dipool
    pairs = [(r["qid"], r["chunk_id"]) for r in rows]
    assert len(pairs) == len(set(pairs)) == result.rows
    assert result.questions == 2
    assert all(r["relevant"] == "" for r in rows)
    chunk_text = {c.chunk_id: c.text for c in kb.chunks}
    assert all(r["text"] == chunk_text[r["chunk_id"]] for r in rows)  # teks lengkap
    # urut menurut posisi chunk di KB per pertanyaan
    order = {c.chunk_id: i for i, c in enumerate(kb.chunks)}
    q1 = [order[r["chunk_id"]] for r in rows if r["qid"] == "q1"]
    assert q1 == sorted(q1)

    meta = json.loads((out.parent / "pool_meta.json").read_text(encoding="utf-8"))
    assert meta["kb_id"] == kb.kb_id
    assert meta["config_hash"] == settings.config_hash()
    assert meta["retrievers"] == ["bm25", "dense", "hybrid"]
    assert meta["depth"] == 10


def test_export_includes_gold_ref_chunks(env):
    settings, kb, _, dataset, tmp = env
    out = tmp / "pool.csv"
    export_pool(settings, kb, dataset, out, embedder_factory=lambda m, r: FakeEmbedder(), depth=1)
    gold = {c.chunk_id for c in kb.chunks if (c.doc_id, c.section) == ("biaya", "Beasiswa")}
    assert gold
    q1 = {r["chunk_id"]: r["from_gold_ref"] for r in read_pool(out) if r["qid"] == "q1"}
    assert all(q1[c] == "ya" for c in gold)
    assert set(q1.values()) <= {"ya", "tidak"}
    assert all(v == "tidak" for c, v in q1.items() if c not in gold)


def test_export_followup_uses_concat_query(env):
    settings, kb, _, dataset, tmp = env
    spy = SpyEmbedder()
    export_pool(settings, kb, dataset, tmp / "pool.csv", embedder_factory=lambda m, r: spy)
    assert "Berapa biaya pendaftaran? Kalau beasiswa?" in spy.queries


def test_export_reports_unmatched_gold_ref(env):
    settings, kb, _, _, tmp = env
    questions = [dict(q) for q in QUESTIONS]
    questions[0]["gold_refs"] = ["biaya::Bagian Salah Ketik"]
    dataset = write_dataset(tmp / "q.jsonl", questions)
    result = export_pool(settings, kb, dataset, tmp / "p.csv",
                         embedder_factory=lambda m, r: FakeEmbedder())
    assert result.unmatched_gold_refs == ["q1: biaya::Bagian Salah Ketik"]


def test_export_does_not_overwrite_pool(env):
    settings, kb, _, dataset, tmp = env
    out = tmp / "pool.csv"
    out.write_text("anotasi lama", encoding="utf-8")
    with pytest.raises(FileExistsError):
        export_pool(settings, kb, dataset, out, embedder_factory=lambda m, r: FakeEmbedder())
    assert out.read_text(encoding="utf-8") == "anotasi lama"
    export_pool(settings, kb, dataset, out, embedder_factory=lambda m, r: FakeEmbedder(),
                force=True)
    assert read_pool(out)


# --- import ----------------------------------------------------------------


def _exported(env):
    settings, kb, _, dataset, tmp = env
    out = tmp / "pool.csv"
    export_pool(settings, kb, dataset, out, embedder_factory=lambda m, r: FakeEmbedder())
    return dataset, out, read_pool(out)


def test_import_fills_gold_chunk_ids(env):
    dataset, pool, rows = _exported(env)
    relevant = {("q1", rows[0]["chunk_id"])}
    for r in rows:
        r["relevant"] = "1" if (r["qid"], r["chunk_id"]) in relevant else "0"
    write_pool(pool, rows)
    gold = import_pool(dataset, pool)
    assert gold == {"q1": [rows[0]["chunk_id"]], "q2": []}  # followup boleh tanpa relevan
    questions = {q["qid"]: q for q in load_questions(dataset)}
    assert questions["q1"]["gold_chunk_ids"] == [rows[0]["chunk_id"]]
    assert questions["q1"]["gold_refs"] == ["biaya::Beasiswa"]  # field lain tetap
    assert questions["q3"]["gold_chunk_ids"] == []
    assert list(questions) == ["q1", "q2", "q3"]


def test_import_accepts_semicolon_csv_from_excel(env):
    dataset, pool, rows = _exported(env)
    for r in rows:
        r["relevant"] = "1"
    write_pool(pool, rows, delimiter=";")
    gold = import_pool(dataset, pool)
    assert len(gold["q1"]) == sum(r["qid"] == "q1" for r in rows)


def test_import_rejects_blank_rows(env):
    dataset, pool, rows = _exported(env)
    before = dataset.read_bytes()
    for r in rows[1:]:
        r["relevant"] = "1"
    write_pool(pool, rows)
    with pytest.raises(DatasetError) as exc:
        import_pool(dataset, pool)
    assert "relevant kosong" in str(exc.value) and rows[0]["qid"] in str(exc.value)
    assert dataset.read_bytes() == before  # dataset tidak ditulis ulang


def test_import_rejects_answerable_without_relevant(env):
    dataset, pool, rows = _exported(env)
    for r in rows:
        r["relevant"] = "0"
    write_pool(pool, rows)
    with pytest.raises(DatasetError) as exc:
        import_pool(dataset, pool)
    assert "qid q1: answerable tanpa satu pun chunk relevan" in str(exc.value)
    assert "q2" not in str(exc.value)


def test_import_rejects_invalid_value(env):
    dataset, pool, rows = _exported(env)
    for r in rows:
        r["relevant"] = "ya"
    write_pool(pool, rows)
    with pytest.raises(DatasetError) as exc:
        import_pool(dataset, pool)
    assert "harus 1 atau 0" in str(exc.value)


# --- CLI -------------------------------------------------------------------


def test_cli_export_then_import(env, capsys):
    _, _, kb_root, dataset, tmp = env
    out = tmp / "pool.csv"
    code = eval_cli.main(
        ["--kb-root", str(kb_root), "annotate", "export", "--config", str(DEV_YAML),
         "--dataset", str(dataset), "--out", str(out)],
        embedder_factory=lambda m, r: FakeEmbedder(),
    )
    printed = capsys.readouterr().out
    assert code == 0 and "2 pertanyaan" in printed and "rata-rata" in printed

    rows = read_pool(out)
    for r in rows:
        r["relevant"] = "1"
    write_pool(out, rows)
    code = eval_cli.main(["annotate", "import", "--dataset", str(dataset), "--pool", str(out)])
    assert code == 0 and "2 pertanyaan diperbarui" in capsys.readouterr().out


def test_cli_export_invalid_dataset(env, capsys):
    _, _, kb_root, _, tmp = env
    bad = tmp / "bad.jsonl"
    bad.write_text("bukan json\n", encoding="utf-8")
    code = eval_cli.main(
        ["--kb-root", str(kb_root), "annotate", "export", "--config", str(DEV_YAML),
         "--dataset", str(bad), "--out", str(tmp / "p.csv")],
        embedder_factory=lambda m, r: FakeEmbedder(),
    )
    assert code == 2 and "bukan JSON valid" in capsys.readouterr().err
