"""M-12 eval copy (E-03): extractive fragments Grusky dkk. 2018, dihitung manual."""

import json
from types import SimpleNamespace

import pytest

from mica.eval import copy_rate as cr


def test_full_copy():
    s = cr.copy_score("a b c d", ["a b c d"])
    assert s.n_tokens == 4 and s.coverage == 1.0
    assert s.density == pytest.approx(4**2 / 4)  # panjang^2 / panjang
    assert s.fragments == (("a", "b", "c", "d"),)


def test_total_paraphrase():
    s = cr.copy_score("uang sekolah setahun", ["biaya kuliah per tahun"])
    assert (s.coverage, s.density, s.fragments) == (0.0, 0.0, ())


def test_mixed_hand_computed():
    source = "Biaya kuliah Sistem Informasi Rp14.000.000 per tahun"
    answer = "Biaya kuliah adalah Rp14.000.000 per tahun"
    # S = biaya kuliah adalah rp14 000 000 per tahun (8 token)
    # F = [biaya kuliah] (2), [rp14 000 000 per tahun] (5)
    s = cr.copy_score(answer, [source])
    assert s.n_tokens == 8
    assert s.coverage == pytest.approx(7 / 8)
    assert s.density == pytest.approx((2**2 + 5**2) / 8)
    assert s.longest == ("rp14", "000", "000", "per", "tahun")


def test_greedy_picks_longest_fragment():
    # "y z" muncul dua kali di A; yang kedua diikuti "w", jadi fragmen terpanjang [y z w]
    assert cr.fragments(list("xyz.yzw"), list("yzw")) == [["y", "z", "w"]]
    # setelah fragmen, i melompat melewati fragmen dan j kembali ke awal
    assert cr.fragments(list("abab"), list("abab")) == [["a", "b", "a", "b"]]
    assert cr.fragments(list("ab"), list("abab")) == [["a", "b"], ["a", "b"]]


def test_fragments_do_not_cross_chunk_boundary():
    s = cr.copy_score("b c", ["a b", "c d"])
    assert s.fragments == (("b",), ("c",))
    assert s.coverage == 1.0 and s.density == pytest.approx((1 + 1) / 2)


def test_empty_texts():
    assert cr.copy_score("", ["a b"]) == cr.CopyScore(0, 0.0, 0.0, ())
    assert cr.copy_score("a b", []).coverage == 0.0
    assert cr.copy_score("a b", [""]).density == 0.0


def test_tokenization_matches_bm25():
    from mica.kb.index import tokenize

    assert cr.copy_score("S1, Rp7.500.000!", ["s1 rp7 500 000"]).coverage == 1.0
    assert tokenize("S1, Rp7.500.000!") == ["s1", "rp7", "500", "000"]


def _item(qid, status, answer, cited=("c1",), context=("c1", "c2")):
    return cr.AnswerItem(qid, "m", status, answer, tuple(cited), tuple(context))


TEXTS = {"c1": "biaya kuliah rp14 000 000 per tahun", "c2": "kelas sore rp15 000 000"}


def test_score_items_excludes_refusals_and_handles_no_citation():
    items = [
        _item("q1", "answered", "biaya kuliah rp14 000 000 per tahun"),
        _item("q2", "false_premise", "tidak ada kelas malam", cited=()),
        _item("q3", "not_found", ""),
        _item("q4", "refused", "x"),
    ]
    scored, excluded = cr.score_items(items, TEXTS)
    assert excluded == 2 and [s.item.qid for s in scored] == ["q1", "q2"]
    assert scored[0].cited.coverage == 1.0 and scored[1].cited is None
    rows = cr.summary_rows("m", scored, excluded)
    kutip, konteks = rows
    assert kutip["sumber"] == "kutip" and kutip["n"] == 1 and kutip["n_tanpa_kutipan"] == 1
    assert konteks["n"] == 2 and konteks["n_dikecualikan"] == 2
    assert kutip["coverage_mean"] == "1.0000"


def test_score_items_unknown_chunk():
    with pytest.raises(KeyError, match="c9"):
        cr.score_items([_item("q1", "answered", "a", cited=("c9",))], TEXTS)


def test_top_density_examples_truncated():
    long = " ".join(f"t{i}" for i in range(30))
    items = [_item("q1", "answered", long, cited=("c1",)), _item("q2", "answered", "biaya")]
    scored, _ = cr.score_items(items, {"c1": long, "c2": ""})
    lines = cr.top_density(scored, n=3, max_words=25)
    assert lines[0].startswith("q1 density 30.00 (30 token): t0 t1") and lines[0].endswith("...")
    assert len(lines[0].split(": ", 1)[1].split()) == 26  # 25 kata + "..."


def test_item_row_columns():
    scored, _ = cr.score_items([_item("q1", "answered", "biaya kuliah")], TEXTS)
    row = cr.item_row(scored[0])
    assert tuple(row) == cr.ITEM_FIELDS
    assert row["fragmen_terpanjang"] == "biaya kuliah" and row["n_fragmen"] == 1


def test_load_run_rejects_changed_dataset(tmp_path):
    dataset = tmp_path / "q.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    (run / "run.json").write_text(json.dumps({
        "llm": {"model_override": "groq:openai/gpt-oss-20b", "provider": "x"},
        "kb_id": "kb1", "gate_off": True,
        "dataset": {"path": str(dataset), "sha256": "0" * 64},
    }), encoding="utf-8")  # fmt: skip
    with pytest.raises(cr.RunMismatch, match="berubah"):
        cr.load_run(run, None, SimpleNamespace(kb_id="kb1"), tmp_path, None)
    with pytest.raises(cr.RunMismatch, match="kb_id"):
        cr.load_run(run, None, SimpleNamespace(kb_id="kb2"), tmp_path, None)


# --- metrik pendamping tanpa entitas (SDD 9.5) -------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Biaya S1 Rp4.500.000 per semester (2026/2027), hubungi (061) 4573767.",
        "Email: fin@mikroskil.ac.id atau https://www.mikroskil.ac.id/pmb?x=1",
        "İstanbul ÇEK dan ẞtraße ke-3",  # huruf yang berubah panjang saat lower()
        "",
    ],
)
def test_tokenize_with_offsets_equals_tokenize(text):
    from mica.kb.index import tokenize

    with_offsets = cr.tokenize_with_offsets(text)
    assert [t for t, _, _ in with_offsets] == tokenize(text)
    for token, start, end in with_offsets:
        assert token in text[start:end].lower()  # İ -> i + titik gabung; tokenize ambil 'i'


def _masked(text):
    tokens, mask = cr.entity_mask(text)
    return [t for t, m in zip(tokens, mask, strict=True) if m]


def test_email_url_and_digit_words_are_entities():
    assert _masked("email fin@mikroskil.ac.id ya") == ["fin", "mikroskil", "ac", "id"]
    assert _masked("lihat https://pmb.mikroskil.ac.id/biaya sekarang") == [
        "https", "pmb", "mikroskil", "ac", "id", "biaya"]  # fmt: skip
    assert _masked("lihat www.mikroskil.ac.id sekarang") == ["www", "mikroskil", "ac", "id"]
    assert _masked("tahun 2026/2027 telepon (061) total 4.500.000") == [
        "2026", "2027", "061", "4", "500", "000"]  # fmt: skip
    # kata campur: seluruh kata yang mengandung digit, termasuk "rp"
    assert _masked("biaya Rp4.500.000 per tahun") == ["rp4", "500", "000"]
    assert _masked("Biaya kuliah per tahun") == []


def test_all_entity_answer_gives_empty():
    m = cr.copy_score_masked("Rp4.500.000 fin@mikroskil.ac.id", ["rp4 500 000 fin mikroskil"])
    assert m.n_tokens == m.n_entity == 7 and m.coverage is None and m.density is None
    assert m.fragments == ()


def test_no_entity_equals_original_grusky():
    answer, source = "Biaya kuliah kelas pagi adalah mahal sekali", "biaya kuliah kelas pagi"
    g, m = cr.copy_score(answer, [source]), cr.copy_score_masked(answer, [source])
    assert m.n_entity == 0 and m.coverage == g.coverage and m.density == g.density
    assert m.fragments == g.fragments


def test_fragment_broken_exactly_at_entity_token():
    source = "biaya kuliah rp14 000 000 per tahun untuk kelas pagi"
    answer = "Biaya kuliah Rp14.000.000 per tahun untuk kelas pagi"
    g = cr.copy_score(answer, [source])
    assert g.fragments == (tuple(cr.tokenize(answer)),)  # Grusky asli: satu fragmen 10 token
    m = cr.copy_score_masked(answer, [source])
    # rp14 000 000 di-mask: fragmen [biaya kuliah] dan [per tahun untuk kelas pagi]
    assert m.fragments == (("biaya", "kuliah"), ("per", "tahun", "untuk", "kelas", "pagi"))
    assert m.n_tokens == 10 and m.n_entity == 3
    assert m.coverage == pytest.approx(7 / 7)
    assert m.density == pytest.approx((2**2 + 5**2) / 7)


def test_masked_columns_and_summary_empty_rows():
    items = [
        _item("q1", "answered", "biaya kuliah rp14 000 000 per tahun"),
        _item("q2", "answered", "Rp14.000.000"),  # seluruhnya entitas -> kosong
    ]
    scored, _ = cr.score_items(items, TEXTS)
    row = cr.item_row(scored[1])
    assert row["n_token"] == 3 and row["n_token_entitas"] == 3
    assert row["coverage_tanpa_entitas_kutip"] == "" and row["density_tanpa_entitas_konteks"] == ""
    assert row["coverage_kutip"] == "1.0000"  # Grusky asli tetap terisi
    kutip = cr.summary_rows("m", scored, 0)[0]
    assert kutip["n_tanpa_entitas"] == 1 and kutip["n_kosong_tanpa_entitas"] == 1
    assert kutip["n_token_total"] == 10 and kutip["n_token_entitas_total"] == 6  # q1: rp14 000 000
    assert kutip["coverage_tanpa_entitas_mean"] == "1.0000"
    lines = cr.top_density_masked(scored)
    assert len(lines) == 1 and lines[0].startswith("q1 density_tanpa_entitas")
