"""Format tampilan jawaban MICA di gelembung percakapan UI web (tampilan saja).

Versi acuan Python dari formatAnswer di static/answer_format.js; keduanya harus memberi hasil
yang sama (diuji di tests/unit/test_answer_format.py, termasuk uji kesetaraan lewat Edge).
Tidak mengubah teks jawaban, teks TTS, prompt, pipeline, atau JSON ViewModel: teks dipecah
menjadi blok paragraf/daftar tanpa menambah atau mengganti kata.

Aturan berurutan:
  a. baris baru asli dipertahankan (setiap baris jadi blok sendiri; baris bernomor berurutan
     jadi satu daftar bernomor);
  b. enumerasi dalam kalimat ("1) ... 2) ...", "1. ... 2. ...", "(1) ... (2) ...") jadi daftar
     bernomor; teks sebelum nomor 1 jadi paragraf pembuka, kalimat setelah kalimat pertama
     butir terakhir jadi paragraf penutup;
  c. blok yang masih lebih dari MAX_SENTENCES_PER_PARAGRAPH kalimat dipecah menjadi paragraf
     berisi paling banyak MAX_SENTENCES_PER_PARAGRAPH kalimat.
"""

from __future__ import annotations

import itertools
import re

# Nilai desain tampilan (bukan hasil ukur): paling banyak 2 kalimat per paragraf.
MAX_SENTENCES_PER_PARAGRAPH = 2

# Singkatan bertitik yang bukan akhir kalimat (huruf kecil, dengan titik).
ABBREVIATIONS = frozenset(
    {
        "rp.", "no.", "nomor.", "dll.", "dsb.", "dst.", "jl.", "jln.", "prof.", "dr.", "drs.",
        "dra.", "ir.", "h.", "hj.", "st.", "tlp.", "telp.", "hlm.", "kab.", "kec.", "kel.",
        "sdr.", "bpk.", "yth.", "a.n.", "u.p.", "s.kom.", "s.e.", "s.ak.", "s.h.", "m.kom.",
        "m.m.", "m.sc.", "m.si.", "m.ak.", "ph.d.", "t.a.",
    }
)  # fmt: skip
# Gelar/singkatan bertitik bersusun (S.Kom., M.Sc., Ph.D., T.A.): 2+ potongan 1-4 huruf.
DOTTED = re.compile(r"^(?:[A-Za-z]{1,4}\.){2,}$")
# Kandidat akhir kalimat: . ! ? (+ penutup kutip/kurung), spasi, lalu huruf besar/angka/pembuka.
# Angka desimal (3,5 / 3.5), jam (09.30), tanggal (17.10.2026), URL, dan email tidak punya
# spasi setelah titik, jadi tidak pernah cocok.
BOUNDARY = re.compile(r"[.!?]+[\"')\]”’]*\s+(?=[A-Z0-9\"'(“‘])")
LEADING_OPEN = re.compile(r"^[\"'(\[“‘]+")
# Penanda enumerasi dalam kalimat, diawali awal teks atau spasi; urutan gaya dicoba berurutan.
ENUM_STYLES = (
    re.compile(r"(?:^|(?<=\s))\((\d{1,2})\)\s+"),  # (1) (2)
    re.compile(r"(?:^|(?<=\s))(\d{1,2})\)\s+"),  # 1) 2)
    re.compile(r"(?:^|(?<=\s))(\d{1,2})\.\s+"),  # 1. 2.
)
# Baris yang diawali nomor (aturan a): "1. ...", "1) ...", "(1) ...".
LINE_ITEM = re.compile(r"^\s*(?:\((\d{1,2})\)|(\d{1,2})[.)])\s+(.*\S)\s*$")
ITEM_TRAIL = re.compile(r"[\s;,]+$")
NEWLINE = re.compile(r"\r\n|\r|\n")

Block = dict  # {"type": "p", "text": str} | {"type": "ol", "start": int, "items": list[str]}


def split_sentences(text: str) -> list[str]:
    """Pecah teks menjadi kalimat; aman untuk singkatan, gelar, angka, jam, tanggal, URL."""
    text = text.strip()
    out: list[str] = []
    start = 0
    for m in BOUNDARY.finditer(text):
        if text[m.start()] == ".":
            words = text[: m.start() + 1].split()
            word = LEADING_OPEN.sub("", words[-1]) if words else ""
            if word.lower() in ABBREVIATIONS or DOTTED.match(word):
                continue
        sentence = text[start : m.end()].strip()
        if sentence:
            out.append(sentence)
        start = m.end()
    rest = text[start:].strip()
    if rest:
        out.append(rest)
    return out


def _paragraphs(text: str) -> list[Block]:
    """Aturan c: paragraf berisi paling banyak MAX_SENTENCES_PER_PARAGRAPH kalimat."""
    sentences = split_sentences(text)
    n = MAX_SENTENCES_PER_PARAGRAPH
    return [
        {"type": "p", "text": " ".join(sentences[i : i + n])} for i in range(0, len(sentences), n)
    ]


def _enumeration(text: str) -> list[re.Match[str]] | None:
    """Penanda nomor 1, 2, 3, ... berurutan dengan gaya yang sama (minimal 2 butir)."""
    for style in ENUM_STYLES:
        chain: list[re.Match[str]] = []
        for m in style.finditer(text):
            if int(m.group(1)) == len(chain) + 1:
                chain.append(m)
        if len(chain) >= 2:
            return chain
    return None


def _item(text: str) -> str:
    return ITEM_TRAIL.sub("", text.strip())


def _format_line(line: str) -> list[Block]:
    chain = _enumeration(line)
    if chain is None:
        return _paragraphs(line)
    blocks = _paragraphs(line[: chain[0].start()])
    items = [_item(line[a.end() : b.start()]) for a, b in itertools.pairwise(chain)]
    last = split_sentences(line[chain[-1].end() :])
    items.append(_item(last[0]) if last else "")
    blocks.append({"type": "ol", "start": 1, "items": items})
    return blocks + _paragraphs(" ".join(last[1:]))


def format_answer(text: str) -> list[Block]:
    """Blok tampilan untuk satu jawaban; gabungan teks blok = teks asli (hanya spasi berubah)."""
    blocks: list[Block] = []
    for line in NEWLINE.split(text):
        m = LINE_ITEM.match(line) if _enumeration(line) is None else None
        if m:  # aturan a: baris bernomor berurutan digabung jadi satu daftar
            number = int(m.group(1) or m.group(2))
            prev = blocks[-1] if blocks else None
            if prev and prev["type"] == "ol" and prev["start"] + len(prev["items"]) == number:
                prev["items"].append(m.group(3))
            else:
                blocks.append({"type": "ol", "start": number, "items": [m.group(3)]})
        elif line.strip():
            blocks.extend(_format_line(line))
    return blocks
