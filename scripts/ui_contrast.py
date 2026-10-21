"""Rasio kontras token warna UI web (WCAG 2.1, definisi luminans relatif dan rasio kontras).

python scripts/ui_contrast.py   -> tabel pasangan teks/latar dari src/mica/webui/static/tokens.css

Rumus: https://www.w3.org/TR/WCAG21/#dfn-relative-luminance dan #dfn-contrast-ratio
(dicek 18 Okt 2026). Batas SC 1.4.3 (AA) teks normal 4,5:1; SC 1.4.11
komponen non-teks 3:1.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TOKENS = Path(__file__).resolve().parents[1] / "src/mica/webui/static/tokens.css"
# (teks, latar, kegunaan)
COLOR_SLUGS = ("hitam", "biru", "cokelat", "abu-abu", "hijau", "oranye", "merah-muda", "ungu",
               "merah", "putih", "kuning")  # mica.vision.color.COLOR_NAMES  # fmt: skip
PAIRS = (
    ("--text", "--surface", "teks utama di panel / gelembung MICA"),
    ("--text", "--bg", "teks utama di latar"),
    ("--text-muted", "--surface", "teks sekunder di panel"),
    ("--text-muted", "--bg", "teks sekunder di latar, tombol nonaktif"),
    ("--text", "--neutral-tint", "gelembung pengunjung tanpa warna sesi"),
    ("--on-accent", "--accent", "tombol utama"),
    ("--on-accent", "--accent-hover", "tombol utama (hover)"),
    ("--accent", "--surface", "tombol topik / ikon topik / tautan"),
    *(("--text", f"--c-{c}-tint", f"gelembung pengunjung, warna sesi {c}") for c in COLOR_SLUGS),
    # versi F (Langkah 57)
    ("--accent", "--bg", "tautan / teks biru di latar"),
    ("--text-muted", "--muted-fill", "baris status siap, catatan kaki"),
    ("--text-muted", "--disabled-bg", "tombol nonaktif"),
    ("--text-muted", "--accent-soft", "teks sekunder di latar biru muda"),
    ("--text", "--accent-soft", "tombol saat hover/ditekan"),
    ("--text", "--muted-fill", "teks utama di kotak abu muda"),
    ("--accent", "--accent-soft", "tombol topik saat hover, ikon topik"),
    ("--on-accent", "--brand", "tanda MICA, ikon kepala panel, avatar MICA"),
    ("--brand", "--surface", "tulisan MICA, judul sambut, slogan"),
    ("--on-accent", "--listen", "tombol Bicara saat ditahan"),
    ("--listen-ink", "--listen-bg", "baris status mendengarkan"),
    ("--listen-ink", "--surface", "tombol Berhenti"),
    ("--busy-ink", "--accent-soft", "baris status berpikir/menjawab"),
)
AA = 4.5
# komponen non-teks (WCAG 2.1 SC 1.4.11, 3:1): tepi kontrol dan ikon status
NON_TEXT_PAIRS = (
    ("--control", "--surface", "tepi kotak ketik"),
    ("--dot-off", "--surface", "ikon kamera/mikrofon mati"),
)
NON_TEXT = 3.0


def tokens(text: str) -> dict[str, str]:
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\b", text))


def luminance(hex_color: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def ratio(fg: str, bg: str) -> float:
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def rows(pairs=PAIRS) -> list[tuple[str, str, str, float]]:
    t = tokens(TOKENS.read_text(encoding="utf-8"))
    return [(fg, bg, use, ratio(t[fg], t[bg])) for fg, bg, use in pairs]


def main() -> int:
    out = rows()
    print("| teks | latar | kegunaan | rasio | AA 4,5:1 |")
    print("| --- | --- | --- | --- | --- |")
    for fg, bg, use, r in out:
        print(f"| `{fg}` | `{bg}` | {use} | {r:.2f}:1 | {'ya' if r >= AA else 'TIDAK'} |")
    other = rows(NON_TEXT_PAIRS)
    print()
    print("| komponen | latar | kegunaan | rasio | SC 1.4.11 3:1 |")
    print("| --- | --- | --- | --- | --- |")
    for fg, bg, use, r in other:
        print(f"| `{fg}` | `{bg}` | {use} | {r:.2f}:1 | {'ya' if r >= NON_TEXT else 'TIDAK'} |")
    ok = all(r >= AA for *_, r in out) and all(r >= NON_TEXT for *_, r in other)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
