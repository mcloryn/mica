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
import time
from typing import Any, Literal, Protocol

import httpx
from pydantic import SecretStr

from mica.config import API_KEY_VARS, CFG_GEMINI_IN_KIOSK, CFG_INVALID, ConfigError, Settings
from mica.core.types import ErrorCode, LlmAnswer, LlmBadOutput, LlmRequest, LlmUnavailable

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

STATUSES = ("answered", "not_found", "false_premise")

# Skema keluaran SDD 5.3 (JSON Schema, untuk structured output Groq strict)
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


class LLMProvider(Protocol):
    name: str

    def generate(self, request: LlmRequest, timeout_s: float) -> LlmAnswer: ...


class ProviderFailed(Exception):
    """Satu penyedia gagal dan rantai boleh pindah ke penyedia berikutnya."""

    def __init__(self, reason: str, status: int | None = None, retry_after: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.retry_after = retry_after


class _BadOutput(Exception):
    """Keluaran tidak sesuai skema; penyedia yang sama dicoba ulang sekali."""


def parse_output(content: str) -> tuple[str, str, tuple[str, ...]]:
    """Validasi keluaran terhadap skema SDD 5.3; field tambahan juga ditolak."""
    try:
        data = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise _BadOutput(f"bukan JSON valid: {exc}") from None
    if not isinstance(data, dict):
        raise _BadOutput("keluaran bukan objek JSON")
    missing = [k for k in OUTPUT_SCHEMA["required"] if k not in data]
    if missing:
        raise _BadOutput(f"field hilang: {missing}")
    extra = sorted(set(data) - set(OUTPUT_SCHEMA["properties"]))
    if extra:
        raise _BadOutput(f"field tidak dikenal: {extra}")
    status, answer, citations = data["status"], data["answer"], data["citations"]
    if status not in STATUSES:
        raise _BadOutput(f"status tidak dikenal: {status!r}")
    if not isinstance(answer, str):
        raise _BadOutput("answer bukan string")
    if not isinstance(citations, list) or not all(isinstance(c, str) for c in citations):
        raise _BadOutput("citations bukan array string")
    return status, answer, tuple(citations)


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

    # diisi subkelas
    def _url(self) -> str:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _body(self, request: LlmRequest) -> dict[str, Any]:
        raise NotImplementedError

    def _schema_mismatch(self, response: httpx.Response) -> bool:
        return False

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
        raise ProviderFailed(
            f"HTTP {response.status_code}",
            status=response.status_code,
            retry_after=response.headers.get("retry-after"),
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
                status, answer, citations = parse_output(content)
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
                "json_schema": {"name": "mica_answer", "strict": True, "schema": OUTPUT_SCHEMA},
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
    """Khusus mode dev; ditolak di mode kiosk (N-09, SDD 8.2)."""

    provider = "gemini"

    def __init__(
        self,
        model: str,
        *,
        mode: Literal["kiosk", "dev"],
        api_key: SecretStr,
        temperature: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if mode != "dev":
            raise ConfigError(CFG_GEMINI_IN_KIOSK, "GeminiProvider hanya boleh saat app.mode: dev")
        super().__init__(model, api_key=api_key, temperature=temperature, client=client)

    def _url(self) -> str:
        return GEMINI_URL.format(model=self.model)

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._api_key.get_secret_value()}

    def _body(self, request: LlmRequest) -> dict[str, Any]:
        config: dict[str, Any] = {
            "responseMimeType": "application/json",
            "responseSchema": GEMINI_SCHEMA,
        }
        if self.temperature is not None:
            config["temperature"] = self.temperature
        return {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": request.user}]}],
            "generationConfig": config,
        }

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
                return provider.generate(request, timeout_s)
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
                    client=client,
                )
            )
        else:  # pragma: no cover - sudah divalidasi M-01
            raise ConfigError(CFG_INVALID, f"penyedia tidak dikenal: {kind}")
    return ProviderChain(providers)
