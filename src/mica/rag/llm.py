"""M-05: penyedia LLM dengan rantai cadangan (ADR-08, Provisional).

Klien HTTP memakai httpx langsung (non-ADR), bukan SDK resmi: satu klien untuk Groq dan Gemini,
tanpa retry otomatis yang mengganggu rantai cadangan dan anggaran latensi, dan bisa diuji dengan
httpx.MockTransport tanpa jaringan.

Penanganan error:
- 429, timeout, galat koneksi, 5xx, 401/403, dan 4xx lain -> penyedia itu gagal; ProviderChain
  mencoba penyedia berikutnya (log LLM_FALLBACK dengan status HTTP dan retry-after).
- JSON rusak, field hilang atau salah tipe, atau HTTP 400 karena keluaran tidak cocok skema ->
  satu kali coba ulang ke penyedia yang sama, lalu LlmBadOutput (tidak pindah penyedia).
- Semua penyedia gagal -> LlmUnavailable.

API key hanya dibaca dari Settings.api_keys (.env) dan hanya dipasang di header. Teks error dan
log disaring supaya key tidak pernah ikut tertulis.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Literal, Protocol

import httpx
from pydantic import SecretStr

from mica.config import API_KEY_VARS, CFG_GEMINI_IN_PROD, CFG_INVALID, ConfigError, Settings
from mica.core.types import ErrorCode, LlmAnswer, LlmBadOutput, LlmRequest, LlmUnavailable

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

STATUSES = ("answered", "not_found", "false_premise")

# Skema keluaran SDD 5.3 (JSON Schema, untuk structured output Groq strict); citations dibatasi
# per request lewat output_schema()
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(STATUSES)},
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "answer", "citations"],
    "additionalProperties": False,
}

# Skema yang sama dalam format responseSchema Gemini (subset OpenAPI; tanpa additionalProperties)
GEMINI_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "status": {"type": "STRING", "enum": list(STATUSES)},
        "answer": {"type": "STRING"},
        "citations": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["status", "answer", "citations"],
    "propertyOrdering": ["status", "answer", "citations"],
}

ReasoningEffort = Literal["low", "medium", "high"]


def _citations_schema(allowed: tuple[str, ...], array: str, string: str) -> dict[str, Any]:
    # sitasi dibatasi ke ID potongan yang dikirim; tanpa potongan, sitasi harus kosong
    if not allowed:
        return {"type": array, "items": {"type": string}, "maxItems": 0}
    return {"type": array, "items": {"type": string, "enum": list(allowed)}}


# Prompt v3 (docs/PROMPT-V3.md): field tambahan follow_up_topic = salah satu label ui.topics atau
# null. Deviasi dari skema SDD 5.3, hanya bila request membawa follow_up_topics; tanpa itu (v2)
# skema dan badan request sama persis seperti sebelumnya, jadi kunci cache v2 tidak berubah.
FOLLOW_UP_FIELD = "follow_up_topic"
# Prompt v4 (docs/PROMPT-V4.md): field items = larik string (boleh kosong), wajib bila request
# membawa items_field. Deviasi lain dari SDD 5.3; v2/v3 tidak berubah.
ITEMS_FIELD = "items"
MAX_ITEMS = 10  # nilai desain (docs/PROMPT-V4.md), bukan hasil ukur


def _with_items(schema: dict[str, Any], array: str, string: str) -> dict[str, Any]:
    """Sisipkan items tepat setelah answer (urutan properti = urutan isi yang diharapkan)."""
    props = {}
    for key, value in schema["properties"].items():
        props[key] = value
        if key == "answer":
            props[ITEMS_FIELD] = {"type": array, "items": {"type": string}, "maxItems": MAX_ITEMS}
    schema["properties"] = props
    schema["required"].insert(schema["required"].index("answer") + 1, ITEMS_FIELD)
    if "propertyOrdering" in schema:
        order = schema["propertyOrdering"]
        order.insert(order.index("answer") + 1, ITEMS_FIELD)
    return schema


def output_schema(
    allowed: tuple[str, ...], topics: tuple[str, ...] = (), items: bool = False
) -> dict[str, Any]:
    """OUTPUT_SCHEMA dengan citations.items.enum = allowed_chunk_ids request ini (Groq)."""
    schema = json.loads(json.dumps(OUTPUT_SCHEMA))
    schema["properties"]["citations"] = _citations_schema(allowed, "array", "string")
    if topics:  # strict Groq: semua field wajib, nilai opsional lewat gabungan dengan null
        schema["properties"][FOLLOW_UP_FIELD] = {
            "anyOf": [{"type": "string", "enum": list(topics)}, {"type": "null"}]
        }
        schema["required"].append(FOLLOW_UP_FIELD)
    return _with_items(schema, "array", "string") if items else schema


def gemini_schema(
    allowed: tuple[str, ...], topics: tuple[str, ...] = (), items: bool = False
) -> dict[str, Any]:
    """GEMINI_SCHEMA dengan citations dibatasi seperti output_schema."""
    schema = json.loads(json.dumps(GEMINI_SCHEMA))
    schema["properties"]["citations"] = _citations_schema(allowed, "ARRAY", "STRING")
    if topics:  # Schema Gemini: format enum + nullable
        schema["properties"][FOLLOW_UP_FIELD] = {
            "type": "STRING", "format": "enum", "enum": list(topics), "nullable": True
        }  # fmt: skip
        schema["required"].append(FOLLOW_UP_FIELD)
        schema["propertyOrdering"].append(FOLLOW_UP_FIELD)
    return _with_items(schema, "ARRAY", "STRING") if items else schema


class LLMProvider(Protocol):
    name: str

    def generate(self, request: LlmRequest, timeout_s: float) -> LlmAnswer: ...


class ProviderFailed(Exception):
    """Satu penyedia gagal dan rantai boleh pindah ke penyedia berikutnya."""

    def __init__(
        self,
        reason: str,
        status: int | None = None,
        retry_after: str | None = None,
        retry_delay_s: float | None = None,
        quota_id: str | None = None,
    ):
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.retry_after = retry_after
        # dari badan respons 429 Gemini (RetryInfo.retryDelay, QuotaFailure.quotaId); None bila tidak ada
        self.retry_delay_s = retry_delay_s
        self.quota_id = quota_id


class _BadOutput(Exception):
    """Keluaran tidak sesuai skema; penyedia yang sama dicoba ulang sekali."""


def parse_output(
    content: str, topics: tuple[str, ...] = (), items: bool = False
) -> tuple[str, str, tuple[str, ...], str | None, tuple[str, ...]]:
    """Validasi keluaran terhadap skema SDD 5.3; field tambahan juga ditolak.

    topics tidak kosong (prompt v3): follow_up_topic wajib ada, berisi salah satu topics atau null.
    items True (prompt v4): items wajib ada, larik string, paling banyak MAX_ITEMS.
    Hasil: (status, answer, citations, follow_up_topic, items).
    """
    try:
        data = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise _BadOutput(f"bukan JSON valid: {exc}") from None
    if not isinstance(data, dict):
        raise _BadOutput("keluaran bukan objek JSON")
    required = [*OUTPUT_SCHEMA["required"], *([FOLLOW_UP_FIELD] if topics else []),
                *([ITEMS_FIELD] if items else [])]  # fmt: skip
    missing = [k for k in required if k not in data]
    if missing:
        raise _BadOutput(f"field hilang: {missing}")
    extra = sorted(set(data) - set(required))
    if extra:
        raise _BadOutput(f"field tidak dikenal: {extra}")
    status, answer, citations = data["status"], data["answer"], data["citations"]
    if status not in STATUSES:
        raise _BadOutput(f"status tidak dikenal: {status!r}")
    if not isinstance(answer, str):
        raise _BadOutput("answer bukan string")
    if not isinstance(citations, list) or not all(isinstance(c, str) for c in citations):
        raise _BadOutput("citations bukan array string")
    follow_up = data.get(FOLLOW_UP_FIELD)
    if follow_up is not None and follow_up not in topics:
        raise _BadOutput(f"follow_up_topic tidak dikenal: {follow_up!r}")
    values = data.get(ITEMS_FIELD, [])
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise _BadOutput("items bukan array string")
    if len(values) > MAX_ITEMS:
        raise _BadOutput(f"items lebih dari {MAX_ITEMS}")
    return status, answer, tuple(citations), follow_up, tuple(values)


class _HttpProvider:
    """Kerangka bersama: kirim, klasifikasikan error, coba ulang sekali bila keluaran rusak."""

    provider = ""

    def __init__(
        self,
        model: str,
        *,
        api_key: SecretStr,
        temperature: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.get_secret_value():
            raise ConfigError(CFG_INVALID, f"{API_KEY_VARS[self.provider]} belum diisi di .env")
        self.model = model
        self.name = f"{self.provider}:{model}"
        self.temperature = temperature
        self._api_key = api_key
        self._client = client or httpx.Client()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.model!r})"

    def request_body(self, request: LlmRequest) -> dict[str, Any]:
        """Badan request persis seperti yang dikirim (tanpa header/key); dipakai kunci cache M-12."""
        return self._body(request)

    # diisi subkelas
    def _url(self) -> str:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _body(self, request: LlmRequest) -> dict[str, Any]:
        raise NotImplementedError

    def _schema_mismatch(self, response: httpx.Response) -> bool:
        return False

    def _quota_info(self, response: httpx.Response) -> tuple[float | None, str | None]:
        """(retry_delay_s, quota_id) dari badan respons galat; bawaan: tidak ada."""
        return None, None

    def _content_and_usage(self, data: Any) -> tuple[str, dict[str, int] | None]:
        raise NotImplementedError

    def _redact(self, text: str) -> str:
        secret = self._api_key.get_secret_value()
        return text.replace(secret, "***") if secret else text

    def _post(self, request: LlmRequest, timeout_s: float) -> httpx.Response:
        try:
            response = self._client.post(
                self._url(),
                headers=self._headers(),
                json=self._body(request),
                timeout=httpx.Timeout(timeout_s),
            )
        except httpx.TimeoutException:
            raise ProviderFailed(f"timeout {timeout_s} detik") from None
        except httpx.HTTPError as exc:
            raise ProviderFailed(self._redact(f"galat koneksi: {type(exc).__name__}")) from None
        if response.status_code == 200:
            return response
        if response.status_code == 400 and self._schema_mismatch(response):
            raise _BadOutput("HTTP 400: keluaran tidak cocok skema")
        retry_delay_s, quota_id = self._quota_info(response)
        raise ProviderFailed(
            f"HTTP {response.status_code}" + (f" ({quota_id})" if quota_id else ""),
            status=response.status_code,
            retry_after=response.headers.get("retry-after"),
            retry_delay_s=retry_delay_s,
            quota_id=quota_id,
        )

    def generate(self, request: LlmRequest, timeout_s: float) -> LlmAnswer:
        start = time.perf_counter()
        last = ""
        for _attempt in range(2):
            try:
                response = self._post(request, timeout_s)
                try:
                    data = response.json()
                except ValueError:
                    raise _BadOutput("badan respons bukan JSON") from None
                content, usage = self._content_and_usage(data)
                status, answer, citations, follow_up, items = parse_output(
                    content, request.follow_up_topics, request.items_field
                )
            except _BadOutput as exc:
                last = self._redact(str(exc))
                logger.warning(
                    "%s: %s, keluaran rusak: %s", ErrorCode.LLM_BAD_OUTPUT, self.name, last
                )
                continue
            return LlmAnswer(
                status=status,  # type: ignore[arg-type]  # sudah divalidasi parse_output
                answer=answer,
                citations=citations,
                provider=self.name,
                latency_s=time.perf_counter() - start,
                usage=usage,
                follow_up_topic=follow_up,
                items=items,
            )
        raise LlmBadOutput(f"{self.name}: keluaran tidak valid setelah coba ulang ({last})")


def _usage(prompt: Any, completion: Any, total: Any) -> dict[str, int] | None:
    values = {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}
    if not all(isinstance(v, int) for v in values.values()):
        return None
    return values


class GroqProvider(_HttpProvider):
    provider = "groq"

    def __init__(
        self,
        model: str,
        *,
        api_key: SecretStr,
        temperature: float | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(model, api_key=api_key, temperature=temperature, client=client)
        self.reasoning_effort = reasoning_effort

    def _url(self) -> str:
        return GROQ_URL

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}

    def _body(self, request: LlmRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "include_reasoning": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "mica_answer",
                    "strict": True,
                    "schema": output_schema(
                        request.allowed_chunk_ids, request.follow_up_topics, request.items_field
                    ),
                },
            },
            "stream": False,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def _schema_mismatch(self, response: httpx.Response) -> bool:
        # Groq: {"error": {"code": "json_validate_failed", "message": "... does not match the
        # expected schema ..."}}
        try:
            error = response.json().get("error") or {}
        except (ValueError, AttributeError):
            return False
        message = str(error.get("message", ""))
        return error.get("code") == "json_validate_failed" or "match the expected schema" in message

    def _content_and_usage(self, data: Any) -> tuple[str, dict[str, int] | None]:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise _BadOutput("respons tanpa choices[0].message.content") from None
        usage = data.get("usage") or {}
        return content, _usage(
            usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens")
        )


class GeminiProvider(_HttpProvider):
    """Khusus mode dev; ditolak di mode prod (N-09, SDD 8.2).

    reasoning_effort (llm.reasoning_effort) dikirim sebagai thinkingConfig.thinkingLevel
    (keputusan pengguna 19 Okt 2026, E-04: padanan reasoning_effort gpt-oss di Groq).
    """

    provider = "gemini"

    def __init__(
        self,
        model: str,
        *,
        mode: Literal["prod", "dev"],
        api_key: SecretStr,
        temperature: float | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if mode != "dev":
            raise ConfigError(CFG_GEMINI_IN_PROD, "GeminiProvider hanya boleh saat app.mode: dev")
        super().__init__(model, api_key=api_key, temperature=temperature, client=client)
        self.reasoning_effort = reasoning_effort

    def _url(self) -> str:
        return GEMINI_URL.format(model=self.model)

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._api_key.get_secret_value()}

    def _body(self, request: LlmRequest) -> dict[str, Any]:
        config: dict[str, Any] = {
            "responseMimeType": "application/json",
            "responseSchema": gemini_schema(
                request.allowed_chunk_ids, request.follow_up_topics, request.items_field
            ),
        }
        if self.temperature is not None:
            config["temperature"] = self.temperature
        if self.reasoning_effort is not None:
            config["thinkingConfig"] = {"thinkingLevel": self.reasoning_effort}
        return {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": request.user}]}],
            "generationConfig": config,
        }

    def _quota_info(self, response: httpx.Response) -> tuple[float | None, str | None]:
        """google.rpc.RetryInfo.retryDelay ("67854s") dan QuotaFailure.violations[0].quotaId."""
        try:
            details = response.json()["error"]["details"]
        except (ValueError, KeyError, TypeError):
            return None, None
        delay: float | None = None
        quota_id: str | None = None
        for item in details if isinstance(details, list) else ():
            if not isinstance(item, dict):
                continue
            kind = str(item.get("@type", ""))
            if kind.endswith("RetryInfo"):
                match = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(item.get("retryDelay", "")))
                if match:
                    delay = float(match.group(1))
            elif kind.endswith("QuotaFailure"):
                violations = item.get("violations") or []
                if violations and isinstance(violations[0], dict):
                    quota_id = violations[0].get("quotaId")
        return delay, quota_id

    def _content_and_usage(self, data: Any) -> tuple[str, dict[str, int] | None]:
        try:
            parts = data["candidates"][0]["content"]["parts"]
            content = "".join(p["text"] for p in parts if "text" in p and not p.get("thought"))
        except (KeyError, IndexError, TypeError):
            raise _BadOutput("respons tanpa candidates[0].content.parts") from None
        meta = data.get("usageMetadata") or {}
        return content, _usage(
            meta.get("promptTokenCount"),
            meta.get("candidatesTokenCount"),
            meta.get("totalTokenCount"),
        )


class ProviderChain:
    """Mencoba penyedia berurutan; LlmBadOutput tidak memicu pindah penyedia (SDD M-05)."""

    def __init__(self, providers: list[LLMProvider]) -> None:
        if not providers:
            raise ValueError("ProviderChain butuh minimal satu penyedia")
        self.providers = tuple(providers)
        self.name = " > ".join(p.name for p in self.providers)

    def __repr__(self) -> str:
        return f"ProviderChain({[p.name for p in self.providers]})"

    def generate(self, request: LlmRequest, timeout_s: float) -> LlmAnswer:
        failures: list[str] = []
        for i, provider in enumerate(self.providers):
            try:
                # llm.prompt_variants: penyedia ini bisa punya request (varian prompt) sendiri
                return provider.generate(request.for_provider(provider.name), timeout_s)
            except ProviderFailed as exc:
                failures.append(f"{provider.name}: {exc.reason}")
                has_next = i + 1 < len(self.providers)
                logger.warning(
                    "%s: %s gagal (%s, status=%s, retry_after=%s)",
                    ErrorCode.LLM_FALLBACK if has_next else ErrorCode.LLM_UNAVAILABLE,
                    provider.name,
                    exc.reason,
                    exc.status,
                    exc.retry_after,
                )
        raise LlmUnavailable("semua penyedia gagal: " + "; ".join(failures))


def make_llm(settings: Settings, client: httpx.Client | None = None) -> ProviderChain:
    """Bangun rantai dari llm.chain ("groq:<id>", "gemini:<id>"); key dari .env."""
    llm = settings.llm
    providers: list[LLMProvider] = []
    for entry in llm.chain:
        kind, _, model = entry.partition(":")
        key = getattr(settings.api_keys, kind) or SecretStr("")
        if kind == "groq":
            providers.append(
                GroqProvider(
                    model,
                    api_key=key,
                    temperature=llm.temperature,
                    reasoning_effort=llm.reasoning_effort,
                    client=client,
                )
            )
        elif kind == "gemini":
            providers.append(
                GeminiProvider(
                    model,
                    mode=settings.app.mode,
                    api_key=key,
                    temperature=llm.temperature,
                    reasoning_effort=llm.reasoning_effort,
                    client=client,
                )
            )
        else:  # pragma: no cover - sudah divalidasi M-01
            raise ConfigError(CFG_INVALID, f"penyedia tidak dikenal: {kind}")
    return ProviderChain(providers)
