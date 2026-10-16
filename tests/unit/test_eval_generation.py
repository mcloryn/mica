import csv
import json
import re
from pathlib import Path

import pytest
from kb_samples import FakeEmbedder, make_kb_folder

from mica.config import load_settings
from mica.core.types import LlmAnswer, LlmRequest, LlmUnavailable
from mica.eval.generation import (
    PER_QUESTION_COLUMNS,
    EvalLlm,
    GenerationRow,
    LlmCache,
    TokenRateLimiter,
    effective_settings,
    run_generation,
    status_at,
    sweep_generation,
)
from mica.kb.index import build_kb, load_kb
from mica.rag.llm import ProviderFailed
from mica.rag.prompts import PROMPT_VERSION

DEV_YAML = Path(__file__).resolve().parents[2] / "config" / "dev.yaml"
USAGE = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
REQUEST = LlmRequest(system="s", user="u", allowed_chunk_ids=("c#0",))


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeProvider:
    name = "groq:fake"
    model = "fake"

    def __init__(self, rule=None, failures=()):
        self.rule = rule or (lambda q: ("answered", "Jawaban tanpa angka."))
        self.failures = list(failures)
        self.requests: list[LlmRequest] = []

    def request_body(self, request):
        return {"model": self.model, "system": request.system, "user": request.user}

    def generate(self, request, timeout_s):
        self.requests.append(request)
        if self.failures:
            raise self.failures.pop(0)
        question = re.search(r"<<<PERTANYAAN>>>\n(.*?)\n<<<AKHIR", request.user, re.DOTALL)
        status, answer = self.rule(question.group(1) if question else request.user)
        cites = (request.allowed_chunk_ids[0],) if status != "not_found" else ()
        return LlmAnswer(status, answer, cites, self.name, 0.5, dict(USAGE))


# --- pembatas laju -------------------------------------------------------------------


def test_rate_limiter_waits_for_window():
    clock = FakeClock()
    limiter = TokenRateLimiter(tpm=6000, first_estimate=2500, clock=clock, sleep=clock.sleep)
    assert limiter.wait() == 0  # belum ada pemakaian
    limiter.record(2500)
    clock.now = 1.0
    assert limiter.wait() == 0  # 2500 + perkiraan 2500 <= 6000
    limiter.record(2500)
    clock.now = 2.0
    waited = limiter.wait()  # 5000 + 2500 > 6000: tunggu sampai pemakaian t=0 keluar jendela
    assert waited == pytest.approx(58.0)
    assert clock.now == pytest.approx(60.0)
    assert limiter.used() == 2500


def test_rate_limiter_uses_last_usage_as_estimate():
    clock = FakeClock()
    limiter = TokenRateLimiter(tpm=6000, clock=clock, sleep=clock.sleep)
    limiter.record(1000)
    limiter.record(1000)
    assert limiter.wait() == 0  # 2000 + perkiraan 1000 (bukan 2500)
    limiter.record(5500)
    assert limiter.wait() > 0


def test_eval_llm_respects_limit_between_calls(tmp_path):
    clock = FakeClock()
    limiter = TokenRateLimiter(tpm=200, first_estimate=110, clock=clock, sleep=clock.sleep)
    llm = EvalLlm(FakeProvider(), limiter, cache=None, sleep=clock.sleep)
    for i in range(3):
        llm.generate(LlmRequest("s", f"u{i}", ("c#0",)), 5)
    # 110 token per panggilan, batas 200 per menit: panggilan ke-2 dan ke-3 menunggu
    assert len(clock.sleeps) == 2 and all(s > 0 for s in clock.sleeps)


# --- cache ----------------------------------------------------------------------------


def test_cache_second_call_skips_llm(tmp_path):
    provider = FakeProvider()
    llm = EvalLlm(provider, TokenRateLimiter(), cache=LlmCache(tmp_path / "cache"))
    first = llm.generate(REQUEST, 5)
    second = llm.generate(REQUEST, 5)
    assert len(provider.requests) == 1
    assert second == first and llm.last_from_cache is True
    assert (llm.stats.api_calls, llm.stats.from_cache) == (1, 1)
    llm.generate(LlmRequest("s", "pertanyaan lain", ("c#0",)), 5)
    assert len(provider.requests) == 2


def test_cache_key_covers_model_prompt_schema_and_settings():
    from pydantic import SecretStr

    from mica.eval.generation import cache_key
    from mica.rag.llm import GroqProvider

    def groq(model="m", temperature=0.2, effort="low"):
        return GroqProvider(model, api_key=SecretStr("k"), temperature=temperature,
                            reasoning_effort=effort)  # fmt: skip

    base = cache_key(groq(), REQUEST)
    assert base == cache_key(groq(), REQUEST)
    assert base != cache_key(groq(model="m2"), REQUEST)
    assert base != cache_key(groq(temperature=0.3), REQUEST)
    assert base != cache_key(groq(effort="medium"), REQUEST)
    assert base != cache_key(groq(), LlmRequest("s2", "u", ("c#0",)))  # system
    assert base != cache_key(groq(), LlmRequest("s", "u2", ("c#0",)))  # user
    assert base != cache_key(groq(), LlmRequest("s", "u", ("c#1",)))  # skema (enum sitasi)
    assert "k" not in base


def test_no_cache_reads_nothing_but_writes(tmp_path):
    provider = FakeProvider()
    cache = LlmCache(tmp_path / "cache")
    EvalLlm(provider, TokenRateLimiter(), cache=cache).generate(REQUEST, 5)
    forced = EvalLlm(provider, TokenRateLimiter(), cache=cache, read_cache=False)
    forced.generate(REQUEST, 5)
    assert len(provider.requests) == 2 and forced.stats.from_cache == 0
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1


# --- 429 -----------------------------------------------------------------------------


def test_429_waits_retry_after_then_succeeds():
    clock = FakeClock()
    failures = [ProviderFailed("HTTP 429", 429, "3"), ProviderFailed("HTTP 429", 429, None)]
    provider = FakeProvider(failures=failures)
    llm = EvalLlm(provider, TokenRateLimiter(clock=clock, sleep=clock.sleep), sleep=clock.sleep)
    out = llm.generate(REQUEST, 5)
    assert out.provider == "groq:fake"
    assert clock.sleeps == [3.0, 10.0]  # tanpa header: 10 detik
    assert (llm.stats.retries_429, llm.stats.api_calls) == (2, 3)


def test_429_gives_up_after_five_retries():
    clock = FakeClock()
    provider = FakeProvider(failures=[ProviderFailed("HTTP 429", 429, "1")] * 6)
    llm = EvalLlm(provider, TokenRateLimiter(clock=clock, sleep=clock.sleep), sleep=clock.sleep)
    with pytest.raises(LlmUnavailable):
        llm.generate(REQUEST, 5)
    assert len(provider.requests) == 6 and llm.stats.retries_429 == 5


def test_other_failure_not_retried():
    provider = FakeProvider(failures=[ProviderFailed("HTTP 500", 500)])
    llm = EvalLlm(provider, TokenRateLimiter())
    with pytest.raises(LlmUnavailable):
        llm.generate(REQUEST, 5)
    assert len(provider.requests) == 1


# --- sweep offline (dihitung manual) ---------------------------------------------------


def _row(qid, type_, score, on, off=None, llm_status="answered", check=True, oos=None):
    return GenerationRow(
        qid=qid, type=type_, oos_level=oos, question="q", reference_answer="", gate_score=score,
        llm_status=llm_status, answer="a", citations=(), check_passed=check,
        check_unsupported=(), status_on=on, status_off=off or on, final_text="t",
        provider="p", usage=None, timings={}, error_code=None, llm_latency_s=None,
        from_cache=False,
    )  # fmt: skip


SWEEP_ROWS = [
    _row("a1", "answerable", 0.60, "answered"),
    _row("a2", "answerable", 0.49, "answered"),
    _row("a3", "answerable", 0.70, "refused_check", off="answered", check=False),
    _row("f1", "followup", 0.53, "answered"),
    _row("j1", "out_of_kb", 0.40, "answered", oos="jauh"),
    _row("k1", "out_of_kb", 0.51, "refused_llm", llm_status="not_found", check=None, oos="dekat"),
    _row("k2", "out_of_kb", 0.56, "answered", oos="dekat"),
    _row("p1", "false_premise", 0.47, "false_premise", llm_status="false_premise"),
]


def test_status_at():
    a3 = SWEEP_ROWS[2]
    assert status_at(a3, None, "on") == "refused_check"
    assert status_at(a3, None, "off") == "answered"
    assert status_at(a3, 0.75, "off") == "refused_gate"
    assert status_at(SWEEP_ROWS[1], 0.49, "on") == "answered"  # sama dengan ambang = lolos


def test_sweep_hand_computed():
    rows = {(r["threshold"], r["fact_check"]): r for r in sweep_generation(SWEEP_ROWS)}
    assert len(rows) == 12

    r = rows[("null", "on")]
    # wanted: a1 ok, a2 ok, a3 refused_check, f1 ok -> 1/4
    assert (r["false_reject_n"], r["false_reject_rate"]) == (1, "0.2500")
    # out_of_kb: hanya k1 refused -> 1/3; jauh 0/1, dekat 1/2
    assert (r["correct_reject_n"], r["correct_reject_rate"]) == (1, "0.3333")
    assert (r["jauh_reject_n"], r["dekat_reject_n"]) == (0, 1)
    assert (r["false_premise_fp"], r["false_premise_refused"], r["false_premise_answered"]) == (
        1,
        0,
        0,
    )
    assert r["answered_failed_check"] == "1"

    r = rows[("null", "off")]
    assert r["false_reject_n"] == 0 and r["answered_failed_check"] == ""

    r = rows[("0.50", "off")]
    # a2 (0.49) ditolak gerbang -> salah tolak 1/4; j1 (0.40) ditolak -> benar 2/3; p1 ditolak
    assert (r["false_reject_n"], r["correct_reject_n"]) == (1, 2)
    assert (r["jauh_reject_n"], r["dekat_reject_n"]) == (1, 1)
    assert (r["false_premise_fp"], r["false_premise_refused"]) == (0, 1)

    r = rows[("0.55", "on")]
    # a2, f1 ditolak gerbang + a3 refused_check -> 3/4; j1, k1 ditolak gerbang -> 2/3
    assert (r["false_reject_n"], r["correct_reject_n"]) == (3, 2)
    assert r["answered_failed_check"] == "1"


def test_sweep_rule_marks_best_eligible_row():
    rows = sweep_generation(SWEEP_ROWS)
    marked = [(r["threshold"], r["fact_check"]) for r in rows if r["meets_rule"] == "ya"]
    # salah tolak <= 10%: (null, off), (0.45, off), (0.48, off), semuanya 0/4. Penolakan benar
    # 0/3, 1/3, 1/3 -> 0.45 dan 0.48 seri (salah tolak sama), keduanya ditandai
    assert marked == [("0.45", "off"), ("0.48", "off")]


def test_sweep_rule_tie_prefers_smaller_false_reject():
    rows = [
        _row("a1", "answerable", 0.9, "answered"),
        _row("a2", "answerable", 0.9, "answered"),
        _row("j1", "out_of_kb", 0.1, "answered", oos="jauh"),
    ]
    marked = [(r["threshold"], r["fact_check"]) for r in sweep_generation(rows) if r["meets_rule"]]
    # semua ambang selain null menolak j1 (penolakan benar 1/1), salah tolak 0 -> semua seri
    assert ("null", "on") not in marked and len(marked) == 10


# --- run penuh dengan KB kecil dan LLM tiruan --------------------------------------------


def _q(qid, type_, question, oos=None, prev=None, split="dev", ref=""):
    q = {"qid": qid, "question": question, "type": type_, "topic": "x", "gold_chunk_ids": [],
         "reference_answer": ref, "split": split, "prev_qid": prev}  # fmt: skip
    if oos is not None:
        q["oos_level"] = oos
    return q


QUESTIONS = [
    _q("a0", "followup", "Kalau beasiswa?", prev="a1"),  # urut qid sebelum prev-nya
    _q("a1", "answerable", "Berapa biaya pendaftaran?", ref="Rp300.000"),
    _q("a2", "answerable", "Biaya Informatika per semester?"),
    _q("j1", "out_of_kb", "Cuaca hari ini?", oos="jauh"),
    _q("p1", "false_premise", "Biaya kedokteran?"),
    _q("t1", "answerable", "Pertanyaan test", split="test"),
]


def _rule(question):
    if question.startswith("Cuaca"):
        return "not_found", ""
    if question.startswith("Biaya kedokteran"):
        return "false_premise", "Tidak ada prodi kedokteran."
    if question.startswith("Biaya Informatika"):
        return "answered", "Biaya Informatika Rp9.999.999 per semester."  # karangan
    if question.startswith("Berapa biaya pendaftaran"):
        return "answered", "Biaya pendaftaran Rp300.000."
    return "answered", "Ada beasiswa prestasi."


@pytest.fixture
def env(tmp_path):
    settings = load_settings(DEV_YAML)
    kb_root = tmp_path / "kb"
    build_kb(make_kb_folder(tmp_path / "src"), settings.kb.active_id, "dev", settings.kb,
             FakeEmbedder(), kb_root)  # fmt: skip
    kb = load_kb(settings.kb.active_id, kb_root)
    dataset = tmp_path / "questions.jsonl"
    dataset.write_text("".join(json.dumps(q) + "\n" for q in QUESTIONS), encoding="utf-8")
    return settings, kb, dataset, tmp_path


def _run(env, provider, out="out", **kw):
    settings, kb, dataset, tmp = env
    return run_generation(settings, kb, dataset, tmp / out, provider=provider,
                          embedder=FakeEmbedder(), cache_dir=tmp / "cache",
                          environment={"git_dirty": False}, progress=None, **kw)  # fmt: skip


def _bom_csv(path):
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_run_generation_outputs(env):
    provider = FakeProvider(_rule)
    run_dir, rows, _ = _run(env, provider, gate_off=True)
    assert [r.qid for r in rows] == ["a0", "a1", "a2", "j1", "p1"]  # hanya dev, urut qid
    # prev dijawab dulu, lalu riwayat followup = pertanyaan + jawaban sistem untuk a1
    asked = [re.search(r"<<<PERTANYAAN>>>\n(.*?)\n", r.user).group(1) for r in provider.requests]
    assert asked[:2] == ["Berapa biaya pendaftaran?", "Kalau beasiswa?"]
    followup_prompt = provider.requests[1].user
    assert "Pengunjung: Berapa biaya pendaftaran?" in followup_prompt
    assert "MICA: Biaya pendaftaran Rp300.000." in followup_prompt

    by = {r.qid: r for r in rows}
    assert (by["a1"].status_on, by["a1"].status_off) == ("answered", "answered")
    assert (by["a2"].status_on, by["a2"].status_off) == ("refused_check", "answered")
    assert by["a2"].check_unsupported == ("Rp9.999.999",)
    assert (by["j1"].status_on, by["j1"].status_off) == ("refused_llm", "refused_llm")
    assert by["p1"].status_on == "false_premise"
    assert all(r.gate_score is not None for r in rows)

    per_q = _bom_csv(run_dir / "per_question.csv")
    assert tuple(per_q[0]) == PER_QUESTION_COLUMNS
    a2 = next(r for r in per_q if r["qid"] == "a2")
    assert a2["final_status_check_on"] == "refused_check" and a2["check_passed"] == "0"
    assert a2["prompt_tokens"] == "100" and a2["error_code"] == "REFUSED_CHECK"

    sweep = _bom_csv(run_dir / "e02_sweep.csv")
    assert len(sweep) == 12

    annotate = _bom_csv(run_dir / "annotate_generation.csv")
    # cek angka mati: a0, a1, a2 answered + p1 false_premise; j1 tidak
    assert [r["qid"] for r in annotate] == ["a0", "a1", "a2", "p1"]
    a1 = next(r for r in annotate if r["qid"] == "a1")
    assert a1["reference_answer"] == "Rp300.000" and a1["cited_chunks"].startswith("[")
    assert (a1["benar"], a1["halusinasi"], a1["catatan"]) == ("", "", "")

    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["experiment"] == "E-02" and run["gate_off"] is True
    threshold = env[0].rag.gate.threshold
    assert run["gate_threshold_config"] == threshold and run["gate_threshold_effective"] is None
    assert run["config_hash"] == effective_settings(env[0], True).config_hash()
    assert run["config_hash"] != run["config_hash_file"]
    assert run["llm_calls"]["api_calls"] == 5 and run["llm_calls"]["from_cache"] == 0
    assert run["tokens_api"]["total_tokens"] == 5 * 110
    assert run["llm"]["model"] == "fake" and run["llm"]["reasoning_effort"] == "low"
    assert run["environment"] == {"git_dirty": False}
    assert run_dir.name.endswith("-E-02-dev-hybrid-gateoff")


def test_rerun_uses_cache(env):
    _run(env, FakeProvider(_rule), gate_off=True)
    provider = FakeProvider(_rule)
    run_dir, rows, _ = _run(env, provider, out="out2", gate_off=True)
    assert provider.requests == []
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["llm_calls"]["from_cache"] == 5 and run["tokens_api"]["total_tokens"] == 0
    assert run["tokens_all_answers"]["total_tokens"] == 5 * 110
    assert all(r.from_cache for r in rows)


def test_rerun_no_cache_calls_again(env):
    _run(env, FakeProvider(_rule), gate_off=True)
    provider = FakeProvider(_rule)
    _run(env, provider, out="out2", gate_off=True, use_cache=False)
    assert len(provider.requests) == 5


def test_gate_on_uses_config_threshold(env):
    run_dir, _rows, _ = _run(env, FakeProvider(_rule), gate_off=False)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    threshold = env[0].rag.gate.threshold
    assert run["gate_threshold_effective"] == threshold and not run_dir.name.endswith("gateoff")


def test_cli_parser_generation():
    from mica.eval.__main__ import build_parser

    args = build_parser().parse_args(
        ["generation", "--config", "c.yaml", "--dataset", "q.jsonl", "--out", "o", "--gate-off"]
    )
    assert args.gate_off is True and args.no_cache is False
    assert args.cache_dir.as_posix() == "data/cache/llm"


def test_cache_only_stops_before_api(tmp_path):
    from mica.eval.generation import CacheMiss

    provider = FakeProvider()
    cache = LlmCache(tmp_path / "cache")
    EvalLlm(provider, TokenRateLimiter(), cache=cache).generate(REQUEST, 5)
    guarded = EvalLlm(provider, TokenRateLimiter(), cache=cache, cache_only=True)
    assert guarded.generate(REQUEST, 5).provider == "groq:fake"  # dari cache
    with pytest.raises(CacheMiss):
        guarded.generate(LlmRequest("s", "baru", ("c#0",)), 5)
    assert len(provider.requests) == 1 and guarded.stats.api_calls == 0


def test_run_cache_only(env):
    from mica.eval.generation import CacheMiss

    with pytest.raises(CacheMiss):
        _run(env, FakeProvider(_rule), gate_off=True, cache_only=True)
    _run(env, FakeProvider(_rule), out="out2", gate_off=True)
    provider = FakeProvider(_rule)
    run_dir, *_ = _run(env, provider, out="out3", gate_off=True, cache_only=True)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert provider.requests == []
    assert run["llm_calls"]["cache_only"] is True and run["llm_calls"]["api_calls"] == 0
    assert run["prompt_version"] == PROMPT_VERSION


def test_progress_flushes(capsys):
    from mica.eval.generation import print_progress

    print_progress("[1/1] x")
    assert capsys.readouterr().out == "[1/1] x\n"


# --- --model: chain diganti satu model ----------------------------------------------------

MODEL_20B = "groq:openai/gpt-oss-20b"


def test_effective_settings_model_replaces_chain():
    settings = load_settings(DEV_YAML)
    assert len(settings.llm.chain) > 1
    eff = effective_settings(settings, True, MODEL_20B)
    assert eff.llm.chain == (MODEL_20B,)
    assert eff.llm.reasoning_effort == settings.llm.reasoning_effort
    assert eff.llm.temperature == settings.llm.temperature
    assert eff.config_hash() != effective_settings(settings, True).config_hash()
    assert settings.llm.chain != (MODEL_20B,)  # config asli tidak berubah


def test_effective_settings_model_validated():
    settings = load_settings(DEV_YAML)
    with pytest.raises(ValueError):
        effective_settings(settings, True, "openai/gpt-oss-20b")  # tanpa penyedia
    with pytest.raises(ValueError):
        effective_settings(settings, True, "foo:bar")


def test_make_llm_with_model_builds_only_that_model():
    from mica.config import ApiKeys
    from mica.rag.llm import make_llm

    settings = load_settings(DEV_YAML).model_copy(update={"api_keys": ApiKeys(groq="x")})
    eff = effective_settings(settings, True, MODEL_20B)
    assert [p.name for p in make_llm(eff).providers] == [MODEL_20B]


def test_run_generation_model_uses_only_that_model(env, monkeypatch):
    import mica.eval.generation as gen

    seen = []
    provider = FakeProvider(_rule)
    provider.name, provider.model = MODEL_20B, "openai/gpt-oss-20b"

    class Chain:
        def __init__(self, eff):
            seen.append(eff.llm.chain)
            self.providers = [provider]

    monkeypatch.setattr(gen, "make_llm", Chain)
    run_dir, rows, _ = _run(env, None, gate_off=True, model=MODEL_20B)
    assert seen == [(MODEL_20B,)] and len(provider.requests) == len(rows)
    assert run_dir.name.endswith("-dev-hybrid-gpt-oss-20b-gateoff")
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["config_hash"] == effective_settings(env[0], True, MODEL_20B).config_hash()
    assert run["llm"]["chain_effective"] == [MODEL_20B]
    assert run["llm"]["model_override"] == MODEL_20B
    assert run["llm"]["provider"] == MODEL_20B


def test_run_generation_model_guard_stops_other_chain(env, monkeypatch):
    import mica.eval.generation as gen

    other = FakeProvider(_rule)
    other.name = "groq:openai/gpt-oss-120b"

    class Chain:
        def __init__(self, eff):
            self.providers = [other]

    monkeypatch.setattr(gen, "make_llm", Chain)
    with pytest.raises(ValueError):
        _run(env, None, gate_off=True, model=MODEL_20B)
    assert other.requests == []


def test_cli_parser_generation_model():
    from mica.eval.__main__ import build_parser

    base = ["generation", "--config", "c.yaml", "--dataset", "q.jsonl", "--out", "o"]
    assert build_parser().parse_args(base).model is None
    assert build_parser().parse_args([*base, "--model", MODEL_20B]).model == MODEL_20B
    assert build_parser().parse_args(base).experiment == "E-02"
    assert build_parser().parse_args([*base, "--experiment", "E-04"]).experiment == "E-04"


def test_run_generation_experiment_label(env):
    run_dir, *_ = _run(env, FakeProvider(_rule), gate_off=True, experiment="E-04")
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["experiment"] == "E-04"
    assert run_dir.name.endswith("-E-04-dev-hybrid-gateoff")


def test_run_generation_experiment_validated(env):
    with pytest.raises(ValueError):
        _run(env, FakeProvider(_rule), gate_off=True, experiment="../x")
