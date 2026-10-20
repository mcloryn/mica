"""Teks jawaban untuk TTS (prompt v3): daftar baris "- " dibacakan sebagai satu kalimat.

Teks layar tidak berubah (formatter tampilan mica.webui.answer_format merender baris "- " sebagai
daftar poin). Hanya teks yang dikirim ke Speak yang diubah: baris "- A", "- B", "- C" menjadi
"A, B, dan C.", baris lain digabung dengan spasi. Teks tanpa baris "- " dikembalikan apa adanya,
jadi jawaban v2 dibacakan persis seperti sebelumnya.
"""

from __future__ import annotations

import re

NEWLINE = re.compile(r"\r\n|\r|\n")
BULLET = re.compile(r"^\s*-\s+(.*\S)\s*$")
ITEM_END = re.compile(r"[\s.;,]+$")


def _join_items(items: list[str]) -> str:
    items = [ITEM_END.sub("", i) for i in items]
    if len(items) == 1:
        return items[0] + "."
    if len(items) == 2:
        return f"{items[0]} dan {items[1]}."
    return ", ".join(items[:-1]) + f", dan {items[-1]}."


def spoken_answer(text: str) -> str:
    """Teks Speak untuk satu jawaban; identik dengan text bila tidak ada baris "- "."""
    lines = NEWLINE.split(text)
    if not any(BULLET.match(line) for line in lines):
        return text
    parts: list[str] = []
    items: list[str] = []
    for line in lines:
        m = BULLET.match(line)
        if m:
            items.append(m.group(1))
            continue
        if items:
            parts.append(_join_items(items))
            items = []
        if line.strip():
            parts.append(line.strip())
    if items:
        parts.append(_join_items(items))
    return " ".join(parts)


# --- prompt v4 (docs/PROMPT-V4.md): field items dibacakan setelah answer ----------------------

# Heuristik langkah: kalimat pengantar menyebut langkah/tahap/urutan/alur -> dibaca berurutan
STEPS = re.compile(r"\b(langkah|tahap|tahapan|urutan|alur)\w*", re.IGNORECASE)
ORDINALS = ("Pertama", "kedua", "ketiga", "keempat", "kelima", "keenam", "ketujuh", "kedelapan",
            "kesembilan")  # fmt: skip


def _steps(items: list[str]) -> str:
    """ "Pertama A, kedua B, ..., terakhir F." (maksimal 10 item: 9 ordinal + terakhir)."""
    head = [f"{ORDINALS[i]} {item}" for i, item in enumerate(items[:-1])]
    return ", ".join([*head, f"terakhir {items[-1]}"]) + "."


def spoken_items(items: tuple[str, ...] | list[str], steps: bool = False) -> str:
    """Butir items sebagai satu kalimat: "A, B, dan C." atau, untuk langkah, berurutan."""
    cleaned = [ITEM_END.sub("", i.strip()) for i in items if i.strip()]
    if not cleaned:
        return ""
    if steps and len(cleaned) >= 2:
        return _steps(cleaned)
    return _join_items(cleaned)


def spoken_with_items(text: str, items: tuple[str, ...] | list[str]) -> str:
    """Teks Speak: answer (lewat spoken_answer) lalu items; tanpa items = spoken_answer(text)."""
    spoken = spoken_answer(text)
    said = spoken_items(items, steps=bool(STEPS.search(text)))
    return f"{spoken} {said}" if said else spoken
