"""M-01 Config: membaca config/*.yaml dan .env, memvalidasi, lalu menyediakan Settings yang beku."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from mica.core.types import ErrorCode

CFG_INVALID = ErrorCode.CFG_INVALID
CFG_GEMINI_IN_KIOSK = ErrorCode.CFG_GEMINI_IN_KIOSK

LLM_PROVIDERS = ("groq", "gemini")
API_KEY_VARS = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}


class ConfigError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = ErrorCode(code)
        self.message = message


class _Model(BaseModel):
    # strict: "5" tidak diam-diam menjadi 5; frozen: tidak bisa diubah saat berjalan
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class AppConfig(_Model):
    mode: Literal["kiosk", "dev"]
    version: str


class EmbedderConfig(_Model):
    model: str
    # hash commit Hugging Face lengkap (N-14); wajib di kiosk, null di dev = revisi main
    revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")


class KbConfig(_Model):
    active_id: str
    chunker: Literal["structure_then_fixed", "fixed"]
    chunk_tokens: PositiveInt | None = None
    overlap_tokens: NonNegativeInt | None = None
    embedder: EmbedderConfig


class RerankerConfig(_Model):
    enabled: bool
    model: str
    # hash commit Hugging Face lengkap (N-14); wajib di kiosk, null di dev = revisi main
    revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")


class GateConfig(_Model):
    threshold: float | None = None


class FactCheckConfig(_Model):
    enabled: bool


class RagConfig(_Model):
    retriever: Literal["bm25", "dense", "hybrid"]
    top_k: PositiveInt
    rrf_k: PositiveInt | None = None
    candidates_per_retriever: PositiveInt | None = None
    reranker: RerankerConfig
    gate: GateConfig
    fact_check: FactCheckConfig
    followup_mode: Literal["concat", "llm_rewrite"]
    history_turns: NonNegativeInt
    prompt_variant: Literal["paraphrase", "plain"]

    @model_validator(mode="after")
    def _gate_needs_dense(self) -> RagConfig:
        # Sinyal gerbang = cosine dense peringkat 1; retriever bm25 tidak punya sinyal itu.
        if self.retriever == "bm25" and self.gate.threshold is not None:
            raise ValueError(
                "rag.gate.threshold harus null bila rag.retriever = bm25 (tidak ada skor dense)"
            )
        return self


class LlmConfig(_Model):
    # list YAML -> tuple butuh strict=False; isinya tetap divalidasi sebagai str
    chain: tuple[str, ...] = Field(strict=False)
    timeout_s: PositiveFloat | None = None
    temperature: NonNegativeFloat | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None  # gpt-oss di Groq; E-04

    @field_validator("chain")
    @classmethod
    def _check_chain(cls, chain: tuple[str, ...]) -> tuple[str, ...]:
        if not chain:
            raise ValueError("minimal satu entri 'penyedia:id_model'")
        for i, entry in enumerate(chain):
            provider, sep, model_id = entry.partition(":")
            if not sep or not model_id.strip():
                raise ValueError(f"entri [{i}] {entry!r} harus berformat 'penyedia:id_model'")
            if provider not in LLM_PROVIDERS:
                raise ValueError(
                    f"entri [{i}] penyedia {provider!r} tidak dikenal; pilihan: {LLM_PROVIDERS}"
                )
        return chain


class SttConfig(_Model):
    backend: Literal["faster_whisper", "groq_whisper"]
    model: str
    compute_type: str
    threads: PositiveInt | None = None
    no_speech_threshold: float | None = None  # E-05; penyaring no_speech_prob segmen Whisper


class VadConfig(_Model):
    threshold: float | None = None
    min_silence_ms: NonNegativeInt | None = None
    min_speech_ms: NonNegativeInt | None = None  # E-05; ucapan lebih pendek dibuang sebelum STT


class TtsConfig(_Model):
    voice: str  # nama suara Piper, file models/piper/<voice>.onnx (+ .onnx.json)
    # null = bawaan file .onnx.json suara (inference.length_scale); boleh null di kiosk
    length_scale: PositiveFloat | None = None


class AudioConfig(_Model):
    stt: SttConfig
    vad: VadConfig
    max_utterance_s: PositiveFloat | None = None
    tts: TtsConfig


class ColorConfig(_Model):
    method: Literal["color_names_lut", "hsv_rules"]
    min_majority: float | None = Field(default=None, ge=0, le=1)


class BoxUpperConfig(_Model):
    # fraksi box orang untuk area dada BoxUpperRegion (ADR-13 cadangan); TBD E-08
    top: float | None = Field(default=None, ge=0, le=1)  # dari atas box
    bottom: float | None = Field(default=None, ge=0, le=1)  # dari atas box
    side: float | None = Field(default=None, ge=0, le=1)  # dipotong di kiri dan kanan


class KeypointTorsoConfig(_Model):
    # KeypointTorsoRegion (ADR-13); TBD E-08
    min_kp_conf: float | None = Field(default=None, ge=0, le=1)  # keypoint bahu/pinggul dipakai
    shrink: float | None = Field(default=None, ge=0, le=1)  # fraksi dipersempit per sisi
    torso_aspect: PositiveFloat | None = None  # tinggi torso / lebar bahu bila pinggul tak terlihat


class VisionConfig(_Model):
    model: Literal["yolo26n", "yolo26n-pose", "yolo11n"]
    tracker: str
    region: Literal["keypoint_torso", "box_upper"]
    box_upper: BoxUpperConfig  # juga cadangan KeypointTorsoRegion
    keypoint_torso: KeypointTorsoConfig
    color: ColorConfig
    dwell_s: NonNegativeFloat | None = None
    leave_s: NonNegativeFloat | None = None
    # sinyal kehadiran (E-07); shoulder_width butuh model -pose dan keypoint_torso.min_kp_conf
    presence_signal: Literal["box_height", "shoulder_width"] | None = None
    min_box_height_ratio: float | None = Field(default=None, ge=0, le=1)
    min_shoulder_ratio: float | None = Field(default=None, ge=0, le=1)
    conf: float | None = Field(default=None, ge=0, le=1)  # ambang skor deteksi untuk tracker
    imgsz: PositiveInt | None = None
    fps_idle: PositiveFloat
    fps_busy: PositiveFloat | None = None
    threads: PositiveInt | None = None

    @model_validator(mode="after")
    def _keypoints_need_pose_model(self) -> VisionConfig:
        if self.model.endswith("-pose"):
            return self
        if self.region == "keypoint_torso":
            raise ValueError(
                f"region keypoint_torso butuh model -pose (keypoint), bukan {self.model}; "
                "pakai model yolo26n-pose atau region box_upper"
            )
        if self.presence_signal == "shoulder_width":
            raise ValueError(
                f"presence_signal shoulder_width butuh model -pose (keypoint bahu), bukan "
                f"{self.model}; pakai model yolo26n-pose atau presence_signal box_height"
            )
        return self


class SessionConfig(_Model):
    idle_reset_s: PositiveFloat | None = None
    regreet_cooldown_s: NonNegativeFloat | None = None


class UiConfig(_Model):
    fullscreen: bool
    font_scale: PositiveFloat
    topics: tuple[str, ...] = Field(strict=False)


class LoggingConfig(_Model):
    dir: str


class JudgeConfig(_Model):
    enabled: bool


class EvalConfig(_Model):
    judge: JudgeConfig


class ApiKeys(_Model):
    groq: SecretStr | None = None
    gemini: SecretStr | None = None


class Settings(_Model):
    app: AppConfig
    kb: KbConfig
    rag: RagConfig
    llm: LlmConfig
    audio: AudioConfig
    vision: VisionConfig
    session: SessionConfig
    ui: UiConfig
    logging: LoggingConfig
    eval: EvalConfig
    # Diisi load_settings dari .env/environment, bukan dari YAML; tidak ikut hash.
    api_keys: ApiKeys = ApiKeys()

    def _config_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"api_keys"})

    def config_hash(self) -> str:
        payload = json.dumps(
            self._config_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_env_file(env_file: Path) -> dict[str, str]:
    # Parser sederhana KEY=VALUE; baris kosong dan komentar (#) dilewati.
    values: dict[str, str] = {}
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        line = line.removeprefix("export ")
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _load_api_keys(env_file: Path | None) -> ApiKeys:
    file_values = _read_env_file(env_file) if env_file is not None and env_file.exists() else {}
    keys: dict[str, SecretStr | None] = {}
    for name, var in API_KEY_VARS.items():
        # environment variable diutamakan; env_file hanya cadangan
        value = os.environ.get(var) or file_values.get(var) or ""
        keys[name] = SecretStr(value) if value else None
    return ApiKeys(**keys)


def _check_gemini_in_kiosk(raw: dict[str, Any]) -> None:
    app = raw.get("app")
    llm = raw.get("llm")
    if not isinstance(app, dict) or app.get("mode") != "kiosk" or not isinstance(llm, dict):
        return
    chain = llm.get("chain")
    if not isinstance(chain, list):
        return
    for i, entry in enumerate(chain):
        if isinstance(entry, str) and entry.partition(":")[0].strip() == "gemini":
            raise ConfigError(
                CFG_GEMINI_IN_KIOSK,
                f"llm.chain[{i}]: penyedia gemini hanya boleh saat app.mode: dev",
            )


def _format_validation_error(err: ValidationError) -> str:
    lines = []
    for e in err.errors():
        path = ".".join(str(p) for p in e["loc"]) or "<root>"
        lines.append(f"{path}: {e['msg']}")
    return "konfigurasi tidak valid\n  " + "\n  ".join(lines)


def _optional_in_kiosk(settings: Settings) -> set[str]:
    # Field null yang hanya wajib bila komponennya dipakai.
    optional: set[str] = {"audio.tts.length_scale"}  # null = bawaan .onnx.json suara
    if settings.rag.retriever != "hybrid":
        optional |= {"rag.rrf_k", "rag.candidates_per_retriever"}
    if settings.rag.retriever == "bm25":
        # bm25 tidak punya sinyal dense untuk gerbang, jadi threshold wajib null
        optional.add("rag.gate.threshold")
    if settings.audio.stt.backend != "faster_whisper":
        optional |= {"audio.stt.threads", "audio.stt.no_speech_threshold"}
    if not settings.rag.reranker.enabled:
        optional.add("rag.reranker.revision")
    vision = settings.vision
    if vision.region != "keypoint_torso":
        optional |= {"vision.keypoint_torso.shrink", "vision.keypoint_torso.torso_aspect"}
        if vision.presence_signal != "shoulder_width":
            optional.add("vision.keypoint_torso.min_kp_conf")
    # ambang sinyal yang tidak dipakai; bila presence_signal null keduanya tetap wajib
    if vision.presence_signal == "shoulder_width":
        optional.add("vision.min_box_height_ratio")
    elif vision.presence_signal == "box_height":
        optional.add("vision.min_shoulder_ratio")
    return optional


def _missing_kiosk_fields(settings: Settings) -> list[str]:
    # null yang wajib, dan nilai placeholder (mengandung "<"), misalnya ID model Groq.
    missing: list[str] = []
    optional = _optional_in_kiosk(settings)

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif node is None:
            if path not in optional:
                missing.append(path)
        elif isinstance(node, str) and "<" in node:
            missing.append(path)

    walk(settings._config_dict(), "")
    return missing


def load_settings(path: Path, env_file: Path | None = None) -> Settings:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(CFG_INVALID, f"gagal membaca {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(CFG_INVALID, f"{path}: isi teratas harus berupa mapping")

    _check_gemini_in_kiosk(raw)

    if "api_keys" in raw:
        raise ConfigError(CFG_INVALID, "api_keys: API key hanya boleh di .env")

    try:
        settings = Settings.model_validate({**raw, "api_keys": _load_api_keys(env_file)})
    except ValidationError as exc:
        raise ConfigError(CFG_INVALID, _format_validation_error(exc)) from None

    if settings.app.mode == "kiosk":
        missing = _missing_kiosk_fields(settings)
        if missing:
            raise ConfigError(
                CFG_INVALID,
                "mode kiosk: field berikut belum diisi\n  " + "\n  ".join(missing),
            )
    return settings
