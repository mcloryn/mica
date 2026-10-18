"""UI web (ADR-19, opsi ui.backend: web): serialisasi ViewModel ke JSON dan pesan browser ke event controller.

Tanpa Qt dan tanpa Flask, supaya bisa diuji murni. Aturan tampilan dan event di sini harus
sama dengan mica.ui.main_window (PySide6); kesamaan itu dibuktikan tes yang membandingkan
keduanya. Pesan hanya berisi teks tampilan, tidak pernah frame atau audio (N-08).
"""

from __future__ import annotations

from typing import Any

from mica.config import UiConfig
from mica.core import texts
from mica.core.controller import DebugInfo
from mica.core.session import Event, StopTapped, TalkTapped, TextSubmitted, TopicTapped
from mica.ui.viewmodel import ViewModel, source_line


def status_label(vm: ViewModel) -> str:
    """Sama dengan MainWindow.render: label status, ditambah pesan bila berbeda."""
    status = texts.STATUS_LABELS[vm.status.value]
    extra = vm.status_message
    if extra and extra.lower() != status.lower():
        status = f"{status}: {extra}"
    return status


def color_slug(name: str | None) -> str | None:
    """Nama warna van de Weijer (COLOR_NAMES) -> kunci token CSS (--c-<slug>-swatch/-tint)."""
    return None if not name else name.replace(" ", "-")


def message_kind(m: Any) -> str:
    """visitor | answer (jawaban bersumber) | notice (penolakan/tidak tersedia: tanpa sumber)."""
    if m.role == "visitor":
        return "visitor"
    return "answer" if m.sources else "notice"


def view_json(vm: ViewModel) -> dict[str, Any]:
    pill, pill_label = texts.PILLS[vm.status.value]
    return {
        "pill": pill,
        "pill_label": pill_label,
        "greeting": vm.home_greeting,
        "target_present": vm.target_present,
        "target_color": vm.target_color,
        # warna sesi: hanya saat target terkunci; None = netral (juga setelah sesi reset)
        "session_color": color_slug(vm.target_color) if vm.target_present else None,
        "status_line": (
            texts.STATUS_READY_NO_MIC
            if pill == "ready" and not vm.mic_ok
            else texts.STATUS_LINES[pill]
        ),
        "preview": vm.preview,
        "notice": texts.NOTICE_SHORT if vm.camera_ok else texts.NOTICE_SHORT_NO_CAMERA,
        "status": vm.status.value,
        "status_label": status_label(vm),
        "camera_label": texts.CAMERA_ON if vm.camera_ok else texts.CAMERA_OFF,
        "mic_label": texts.MIC_ON if vm.mic_ok else texts.MIC_OFF,
        "camera_ok": vm.camera_ok,
        "mic_ok": vm.mic_ok,
        "talk_enabled": vm.mic_ok,
        "send_enabled": vm.send_enabled,
        "home": vm.home,
        "last_transcript": vm.last_transcript,
        "messages": [
            {
                "role": m.role,
                "kind": message_kind(m),
                "who": texts.VISITOR if m.role == "visitor" else texts.MICA,
                "text": m.text,
                "sources": [source_line(s) for s in m.sources],
            }
            for m in vm.messages
        ],
    }


def topic_question(ui: UiConfig, topic: str) -> str:
    """Sama dengan MainWindow._home_page: saran pertama, atau nama topik bila tanpa saran."""
    suggestions = ui.suggestions.get(topic, ())
    return suggestions[0] if suggestions else topic


def config_json(ui: UiConfig, dev: bool) -> dict[str, Any]:
    return {
        "dev": dev,
        "font_scale": ui.font_scale,
        "logo": "/logo" if ui.logo_path else None,
        "preview": ui.camera_preview,
        "topics": [
            {
                "topic": t,
                "question": topic_question(ui, t),
                "suggestions": list(ui.suggestions.get(t, ())),
            }
            for t in ui.topics
        ],
        "texts": {
            "home_title": texts.HOME_TITLE,
            "input_placeholder": texts.INPUT_PLACEHOLDER,
            "send": texts.SEND,
            "talk": texts.TALK,
            "stop": texts.STOP,
            "resend": texts.RESEND,
            "transcript_label": texts.TRANSCRIPT_LABEL,
            "sources_label": texts.SOURCES_LABEL,
            "notice": f"{texts.NOTICE_CAMERA}  {texts.NOTICE_AI}",
            "app_title": texts.APP_TITLE,
            "approach": texts.APPROACH,
            "camera_unavailable": texts.CAMERA_UNAVAILABLE,
            "wearing": texts.WEARING,
            "detected_no_color": texts.DETECTED_NO_COLOR,
            "camera_info": texts.CAMERA_INFO,
            "welcome_title": texts.WELCOME_TITLE,
            "topics_hint": texts.TOPICS_HINT,
            "mic_unavailable_button": texts.MIC_UNAVAILABLE_BUTTON,
            "camera_on": texts.CAMERA_ON,
            "camera_off": texts.CAMERA_OFF,
            "mic_on": texts.MIC_ON,
            "mic_off": texts.MIC_OFF,
            "camera_title": texts.CAMERA_TITLE,
        },
    }


def event_from_message(msg: dict[str, Any], vm: ViewModel, ui: UiConfig) -> Event | None:
    """Pesan input browser -> event yang sama dengan sinyal MainWindow; selain itu None."""
    kind = msg.get("type")
    if kind in ("text", "resend"):
        text = str(msg.get("text", "")).strip()
        return TextSubmitted(text) if text and vm.send_enabled else None
    if kind == "topic":
        topic, question = msg.get("topic"), msg.get("question")
        if topic not in ui.topics:
            return None
        allowed = set(ui.suggestions.get(topic, ())) | {topic_question(ui, topic)}
        return TopicTapped(topic, question) if question in allowed else None
    if kind == "talk":
        return TalkTapped() if vm.mic_ok else None  # tombol bicara nonaktif tanpa mikrofon
    if kind == "stop":
        return StopTapped()
    return None


def format_debug(info: DebugInfo) -> str:
    """Salinan mica.ui.main_window.format_debug (tanpa memuat Qt); kesamaan dibuktikan tes."""

    def fmt(value: Any) -> str:
        return "-" if value is None else str(value)

    lines = [f"state M-09: {info.state.value}", f"FPS kamera: {fmt(info.camera_fps)}",
             f"status jawaban: {fmt(info.final_status)}", f"gerbang: {fmt(info.gate)}",
             f"penyedia LLM: {fmt(info.llm_provider)}", "potongan teratas:"]  # fmt: skip
    lines += [f"  {chunk_id}  {score:.3f}" for chunk_id, score in info.top_hits] or ["  -"]
    lines.append("waktu per tahap (s):")
    timings = info.timings or {}
    lines += [f"  {k}: {v:.3f}" for k, v in timings.items()] or ["  -"]
    return "\n".join(lines)
