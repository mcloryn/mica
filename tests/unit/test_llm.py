import json
import logging
from pathlib import Path

import httpx
import pytest
import yaml
from pydantic import SecretStr

from mica.config import CFG_GEMINI_IN_PROD, CFG_INVALID, ConfigError, load_settings
from mica.core.types import LlmAnswer, LlmBadOutput, LlmRequest, LlmUnavailable
from mica.rag.llm import (
    GEMINI_URL,
    GROQ_URL,
    OUTPUT_SCHEMA,
    GeminiProvider,
    GroqProvider,
    ProviderChain,
    ProviderFailed,
    make_llm,
    output_schema,
)

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
KEY = "gsk_TESTSECRET_jangan_bocor_123"
REQUEST = LlmRequest(
    system="Jawab dari potongan.", user="[1] doc#0: Rp14.000.000", allowed_chunk_ids=("doc#0",)
)
GOOD = {"status": "answered", "answer": "Rp14.000.000 per tahun.", "citations": ["doc#0"]}
USAGE = {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}


def _groq_ok(content=GOOD, usage=USAGE) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": usage})


class Server:
    """Server tiruan: membalas berurutan per model dan mencatat request."""

    def __init__(self, replies: dict[str, list]):
        self.replies = {k: list(v) for k, v in replies.items()}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if "googleapis" in request.url.host:
            model = request.url.path.split("/models/")[1].split(":")[0]
        else:
            model = json.loads(request.content)["model"]
        reply = self.replies[model].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


def _groq(server: Server, model: str, **kw) -> GroqProvider:
    return GroqProvider(model, api_key=SecretStr(KEY), client=server.client(), **kw)


def _chain(server: Server) -> ProviderChain:
    return ProviderChain(
        [_groq(server, "openai/gpt-oss-120b"), _groq(server, "openai/gpt-oss-20b")]
    )


def test_groq_success():
    server = Server({"openai/gpt-oss-120b": [_groq_ok()]})
    out = _chain(server).generate(REQUEST, 5)
    assert isinstance(out, LlmAnswer)
    assert (out.status, out.answer, out.citations) == ("answered", GOOD["answer"], ("doc#0",))
    assert out.provider == "groq:openai/gpt-oss-120b"
    assert out.usage == USAGE and out.latency_s >= 0
    assert str(server.requests[0].url) == GROQ_URL
    assert server.requests[0].headers["authorization"] == f"Bearer {KEY}"


def test_groq_request_body():
    server = Server({"m": [_groq_ok()]})
    _groq(server, "m", temperature=0.2, reasoning_effort="low").generate(REQUEST, 5)
    body = server.bodies()[0]
    assert body["messages"] == [
        {"role": "system", "content": REQUEST.system},
        {"role": "user", "content": REQUEST.user},
    ]
    assert body["temperature"] == 0.2
    assert body["reasoning_effort"] == "low"
    assert body["include_reasoning"] is False
    assert body["stream"] is False
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    assert schema == output_schema(("doc#0",))
    assert schema["properties"]["citations"] == {
        "type": "array",
        "items": {"type": "string", "enum": ["doc#0"]},
    }
    assert {k: v for k, v in schema.items() if k != "properties"} == {
        k: v for k, v in OUTPUT_SCHEMA.items() if k != "properties"
    }
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["status", "answer", "citations"]
    assert schema["properties"]["status"]["enum"] == ["answered", "not_found", "false_premise"]


def test_usage_none_when_missing():
    server = Server({"m": [_groq_ok(usage=None)]})
    assert _groq(server, "m").generate(REQUEST, 5).usage is None


def test_429_falls_back_to_20b(caplog):
    server = Server({
        "openai/gpt-oss-120b": [httpx.Response(429, headers={"retry-after": "7"}, json={})],
        "openai/gpt-oss-20b": [_groq_ok()],
    })  # fmt: skip
    with caplog.at_level(logging.WARNING, logger="mica.rag.llm"):
        out = _chain(server).generate(REQUEST, 5)
    assert out.provider == "groq:openai/gpt-oss-20b"
    assert "LLM_FALLBACK" in caplog.text and "status=429" in caplog.text
    assert "retry_after=7" in caplog.text


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("timeout"),
        httpx.ConnectError("tidak ada jaringan"),
        httpx.Response(500, json={}),
        httpx.Response(503, json={}),
        httpx.Response(401, json={"error": {"message": "Invalid API Key"}}),
        httpx.Response(403, json={}),
    ],
    ids=["timeout", "koneksi", "500", "503", "401", "403"],
)
def test_provider_failure_falls_back(failure):
    server = Server({"openai/gpt-oss-120b": [failure], "openai/gpt-oss-20b": [_groq_ok()]})
    assert _chain(server).generate(REQUEST, 5).provider == "groq:openai/gpt-oss-20b"


def test_timeout_passed_to_http_client():
    seen = {}

    def handler(request):
        seen["timeout"] = request.extensions["timeout"]
        return _groq_ok()

    provider = GroqProvider(
        "m", api_key=SecretStr(KEY), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    provider.generate(REQUEST, 3.5)
    assert seen["timeout"]["read"] == 3.5 and seen["timeout"]["connect"] == 3.5


def test_all_fail_raises_unavailable():
    server = Server({
        "openai/gpt-oss-120b": [httpx.Response(429, json={})],
        "openai/gpt-oss-20b": [httpx.ReadTimeout("timeout")],
    })  # fmt: skip
    with pytest.raises(LlmUnavailable) as exc:
        _chain(server).generate(REQUEST, 5)
    assert "HTTP 429" in str(exc.value) and "timeout" in str(exc.value)


@pytest.mark.parametrize(
    "bad",
    [
        _groq_ok("{bukan json"),
        _groq_ok({"status": "answered", "answer": "x"}),  # citations hilang
        _groq_ok({"status": "ya", "answer": "x", "citations": []}),
        _groq_ok({**GOOD, "extra": 1}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(
            400,
            json={"error": {"code": "json_validate_failed",
                            "message": "Generated JSON does not match the expected schema."}},
        ),
    ],
    ids=["json-rusak", "field-hilang", "status-salah", "field-tambahan", "tanpa-choices", "400-skema"],
)  # fmt: skip
def test_bad_output_retried_once_on_same_provider(bad):
    server = Server({"openai/gpt-oss-120b": [bad, _groq_ok()]})
    out = _chain(server).generate(REQUEST, 5)
    assert out.provider == "groq:openai/gpt-oss-120b"
    assert len(server.requests) == 2


def test_bad_output_twice_raises_without_fallback():
    server = Server({
        "openai/gpt-oss-120b": [_groq_ok("{rusak"), _groq_ok("{rusak lagi")],
        "openai/gpt-oss-20b": [_groq_ok()],
    })  # fmt: skip
    with pytest.raises(LlmBadOutput):
        _chain(server).generate(REQUEST, 5)
    assert [json.loads(r.content)["model"] for r in server.requests] == ["openai/gpt-oss-120b"] * 2


def test_schema_400_twice_raises_bad_output():
    mismatch = {"error": {"message": "Generated JSON does not match the expected schema"}}
    server = Server({"m": [httpx.Response(400, json=mismatch), httpx.Response(400, json=mismatch)]})
    with pytest.raises(LlmBadOutput):
        _groq(server, "m").generate(REQUEST, 5)


def test_other_400_is_provider_failure():
    server = Server({
        "openai/gpt-oss-120b": [httpx.Response(400, json={"error": {"message": "model not found"}})],
        "openai/gpt-oss-20b": [_groq_ok()],
    })  # fmt: skip
    assert _chain(server).generate(REQUEST, 5).provider == "groq:openai/gpt-oss-20b"


def _gemini_ok() -> httpx.Response:
    return httpx.Response(200, json={
        "candidates": [{"content": {"parts": [{"text": "berpikir", "thought": True},
                                              {"text": json.dumps(GOOD)}]}}],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20, "totalTokenCount": 120},
    })  # fmt: skip


def test_gemini_success_and_body():
    server = Server({"gemini-x": [_gemini_ok()]})
    provider = GeminiProvider("gemini-x", mode="dev", api_key=SecretStr(KEY), temperature=0.2,
                              client=server.client())  # fmt: skip
    out = provider.generate(REQUEST, 5)
    assert out.provider == "gemini:gemini-x" and out.citations == ("doc#0",)
    assert out.usage == {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    request = server.requests[0]
    assert str(request.url) == GEMINI_URL.format(model="gemini-x")
    assert request.headers["x-goog-api-key"] == KEY and "key=" not in str(request.url)
    body = json.loads(request.content)
    assert body["systemInstruction"] == {"parts": [{"text": REQUEST.system}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": REQUEST.user}]}]
    config = body["generationConfig"]
    assert config["temperature"] == 0.2 and config["responseMimeType"] == "application/json"
    assert config["responseSchema"]["required"] == ["status", "answer", "citations"]
    assert "thinkingConfig" not in config  # tanpa reasoning_effort: bawaan Gemini


def test_gemini_reasoning_effort_sent_as_thinking_level():
    server = Server({"gemini-x": [_gemini_ok()]})
    provider = GeminiProvider("gemini-x", mode="dev", api_key=SecretStr(KEY),
                              reasoning_effort="low", client=server.client())  # fmt: skip
    provider.generate(REQUEST, 5)
    config = json.loads(server.requests[0].content)["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingLevel": "low"}


def test_make_llm_passes_reasoning_effort_to_gemini():
    from mica.config import ApiKeys

    settings = load_settings(DEV_YAML, env_file=None)
    llm = settings.llm.model_copy(update={"chain": ("gemini:gemini-x",), "reasoning_effort": "low"})
    settings = settings.model_copy(update={"llm": llm, "api_keys": ApiKeys(gemini="x")})
    (provider,) = make_llm(settings).providers
    assert provider.reasoning_effort == "low"


def test_gemini_rejected_in_prod():
    with pytest.raises(ConfigError) as exc:
        GeminiProvider("gemini-x", mode="prod", api_key=SecretStr(KEY))
    assert exc.value.code == CFG_GEMINI_IN_PROD


def test_missing_key_rejected():
    with pytest.raises(ConfigError) as exc:
        GroqProvider("m", api_key=SecretStr(""))
    assert exc.value.code == CFG_INVALID and "GROQ_API_KEY" in str(exc.value)


def test_key_never_in_exception_log_or_repr(caplog):
    # badan respons yang memantulkan key tetap tidak boleh membocorkannya
    echo = {"error": {"message": f"Invalid API Key {KEY}"}}
    bad = _groq_ok(f"{{rusak {KEY}")
    server = Server({
        "openai/gpt-oss-120b": [httpx.Response(401, json=echo)],
        "openai/gpt-oss-20b": [bad, bad],
    })  # fmt: skip
    chain = _chain(server)
    with caplog.at_level(logging.DEBUG, logger="mica.rag.llm"), pytest.raises(LlmBadOutput) as exc:
        chain.generate(REQUEST, 5)
    texts = [str(exc.value), repr(exc.value), caplog.text, repr(chain), *map(repr, chain.providers)]
    assert all(KEY not in t for t in texts)

    server = Server({"openai/gpt-oss-120b": [httpx.Response(401, json=echo)],
                     "openai/gpt-oss-20b": [httpx.ConnectError(f"gagal {KEY}")]})  # fmt: skip
    with pytest.raises(LlmUnavailable) as exc:
        _chain(server).generate(REQUEST, 5)
    assert KEY not in str(exc.value)


def _settings(tmp_path, monkeypatch, **llm):
    raw = yaml.safe_load(DEV_YAML.read_text(encoding="utf-8"))
    raw["llm"].update(llm)
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    return load_settings(path, env_file=None)


def test_make_llm_from_dev_config(tmp_path, monkeypatch):
    chain = make_llm(_settings(tmp_path, monkeypatch))
    assert [p.name for p in chain.providers] == [
        "groq:openai/gpt-oss-120b",
        "groq:openai/gpt-oss-20b",
    ]
    first = chain.providers[0]
    assert isinstance(first, GroqProvider)
    assert (first.temperature, first.reasoning_effort) == (0.2, "low")


def test_make_llm_with_gemini_in_dev(tmp_path, monkeypatch):
    settings = _settings(
        tmp_path, monkeypatch, chain=["groq:openai/gpt-oss-120b", "gemini:gemini-x"]
    )
    chain = make_llm(settings)
    assert isinstance(chain.providers[1], GeminiProvider)


def test_make_llm_without_key(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch)
    monkeypatch.delenv("GROQ_API_KEY")
    settings = load_settings(tmp_path / "cfg.yaml", env_file=None)
    with pytest.raises(ConfigError) as exc:
        make_llm(settings)
    assert "GROQ_API_KEY" in str(exc.value) and KEY not in str(exc.value)


@pytest.mark.parametrize("kind", ["groq", "gemini"])
def test_citation_enum_per_request(kind):
    allowed = ("a#1", "b#2", "c#3")
    request = LlmRequest(system="s", user="u", allowed_chunk_ids=allowed)
    server = Server({"m": [_groq_ok() if kind == "groq" else _gemini_ok()] * 2})
    if kind == "groq":
        provider = _groq(server, "m")
    else:
        provider = GeminiProvider("m", mode="dev", api_key=SecretStr(KEY), client=server.client())
    provider.generate(request, 5)
    provider.generate(REQUEST, 5)
    first, second = server.bodies()
    if kind == "groq":
        cites = [b["response_format"]["json_schema"]["schema"]["properties"]["citations"]
                 for b in (first, second)]  # fmt: skip
    else:
        cites = [b["generationConfig"]["responseSchema"]["properties"]["citations"]
                 for b in (first, second)]  # fmt: skip
    assert cites[0]["items"]["enum"] == list(allowed)
    assert cites[1]["items"]["enum"] == ["doc#0"]


@pytest.mark.parametrize("kind", ["groq", "gemini"])
def test_citation_schema_empty_when_no_chunks(kind):
    request = LlmRequest(system="s", user="u", allowed_chunk_ids=())
    empty = {"status": "not_found", "answer": "", "citations": []}
    server = Server({"m": [_groq_ok(empty)]})
    if kind == "groq":
        _groq(server, "m").generate(request, 5)
        cites = server.bodies()[0]["response_format"]["json_schema"]["schema"]["properties"]
    else:
        server.replies["m"] = [httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": json.dumps(empty)}]}}]})]  # fmt: skip
        GeminiProvider("m", mode="dev", api_key=SecretStr(KEY), client=server.client()).generate(
            request, 5
        )
        cites = server.bodies()[0]["generationConfig"]["responseSchema"]["properties"]
    assert cites["citations"]["maxItems"] == 0
    assert "enum" not in cites["citations"]["items"]


def _gemini_429(quota_id="GenerateRequestsPerDayPerProjectPerModel-FreeTier", delay="67854s"):
    details = [{"@type": "type.googleapis.com/google.rpc.Help", "links": []}]
    if quota_id is not None:
        details.append({"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaId": quota_id, "quotaValue": "20"}]})  # fmt: skip
    if delay is not None:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay})
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": details}}
    return httpx.Response(429, json=body)


def test_gemini_429_reads_retry_delay_and_quota_id():
    server = Server({"m": [_gemini_429()]})
    provider = GeminiProvider("m", mode="dev", api_key=SecretStr(KEY), client=server.client())
    with pytest.raises(ProviderFailed) as exc:
        provider.generate(REQUEST, 5)
    assert exc.value.status == 429 and exc.value.retry_delay_s == 67854.0
    assert exc.value.quota_id == "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    assert "PerDay" in exc.value.reason


@pytest.mark.parametrize("reply", [httpx.Response(429, json={}), httpx.Response(429, text="x")])
def test_gemini_429_without_details(reply):
    server = Server({"m": [reply]})
    provider = GeminiProvider("m", mode="dev", api_key=SecretStr(KEY), client=server.client())
    with pytest.raises(ProviderFailed) as exc:
        provider.generate(REQUEST, 5)
    assert (exc.value.retry_delay_s, exc.value.quota_id) == (None, None)


def test_gemini_429_fractional_delay_without_quota():
    server = Server({"m": [_gemini_429(quota_id=None, delay="12.5s")]})
    provider = GeminiProvider("m", mode="dev", api_key=SecretStr(KEY), client=server.client())
    with pytest.raises(ProviderFailed) as exc:
        provider.generate(REQUEST, 5)
    assert (exc.value.retry_delay_s, exc.value.quota_id) == (12.5, None)
