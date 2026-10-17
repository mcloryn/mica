"""M-08 normalize_for_speech: angka, rupiah, jam, tanggal, dan singkatan menjadi kata sebelum TTS.

Non-ADR (SDD M-08), divalidasi di E-06. Aturan diterapkan berurutan; angka menjadi kata lewat
num2words(lang="id"):
1. rupiah: "Rp15.000.000", "Rp 15.000.000", "Rp300.000,00", "Rp15.000.000,-" -> "<angka> rupiah";
2. jam HH.MM (juga HH:MM, bentuk yang ada di KB dev): rentang "09.00-15.00", "09.00 – 15.00",
   "09.00 s.d. 15.00", "09.00 sampai 15.00" -> "pukul sembilan sampai pukul lima belas"; jam
   tunggal ".00" -> "pukul <jam>", selain itu "pukul <jam> <menit>"; tidak dobel "pukul";
   "s.d."/"s.d" yang tersisa -> "sampai";
3. "WIB" -> "waktu Indonesia barat";
4. tanggal "29 September 2026";
5. tahun ajaran "2026/2027" dan "T.A.";
6. nomor telepon (awal 08 atau +62, minimal 9 digit): per digit, "+" -> "plus", koma antar
   kelompok yang dipisah spasi (strip dibuang); telepon kantor dengan kode area dalam kurung
   ("(061) 4573767", "(061) 457-3767") juga per digit, koma setelah kode area;
7. "ke-2" -> "kedua", persen, desimal koma, ribuan bertitik, bilangan bulat lain;
8. singkatan dari kamus ABBREVIATIONS (kata utuh, peka huruf besar); kode huruf+angka lain
   (misalnya SMKN1, IP4) dibiarkan;
9. spasi ganda dirapikan.
Fungsi murni, tanpa I/O.
"""

from __future__ import annotations

import re

from num2words import num2words

MONTHS = "Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember"
ABBREVIATIONS = {
    "S1": "es satu",
    "S2": "es dua",
    "S3": "es tiga",
    "D3": "de tiga",
    "SKS": "es ka es",
    "IPK": "i pe ka",
    "PMB": "P M B",  # pilihan hasa setelah pilot E-06 ("pe em be" terdengar "pe m be")
    "KIP": "kip",
    "dll": "dan lain-lain",
    "dsb": "dan sebagainya",
    "No.": "nomor",
    "Jl.": "jalan",
}
DIGITS = ("nol", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan")

_RUPIAH = re.compile(r"Rp\s?(\d{1,3}(?:\.\d{3})+|\d+)(?:,00|,-)?")
# HH 00-23, MM 00-59, tepat dua digit, tidak menempel pada angka lain
_TIME = r"(?<![\d.,:])([01]\d|2[0-3])[.:]([0-5]\d)(?![\d]|[.,:]\d)"
_TIME_RANGE = re.compile(_TIME + r"\s*(?:-|–|—|s\.d\.?|sampai)\s*" + _TIME)
_TIME_ONE = re.compile(_TIME)
_SD = re.compile(r"(?<!\w)s\.d\.?(?!\w)")  # "s.d." yang tersisa di luar rentang jam
_PUKUL_BEFORE = re.compile(r"pukul\s*$", re.IGNORECASE)
_WIB = re.compile(r"(?<!\w)WIB(?!\w)")
_DATE = re.compile(rf"(?<!\d)(\d{{1,2}}) ({MONTHS}) (\d{{4}})(?!\d)")
_ACADEMIC_YEAR = re.compile(r"(?<![\d/])(\d{4})/(\d{4})(?![\d/])")
_TA = re.compile(r"(?<!\w)T\.A\.")
_PHONE = re.compile(r"(?<![\w+])(?:\+62|08)[\d -]*\d")
_LANDLINE = re.compile(r"\((0\d{1,4})\)\s?(\d[\d -]*\d)")
_ORDINAL = re.compile(r"(?<!\w)ke-(\d+)(?!\w)")
_PERCENT = re.compile(r"(?<![\w.,])(\d+(?:,\d+)?)\s?%")
_DECIMAL = re.compile(r"(?<![\w.,])(\d+),(\d+)(?![\w]|[.,]\d)")
_THOUSANDS = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+)(?![\w]|[.,]\d)")
_INTEGER = re.compile(r"(?<![\w.,])(\d+)(?!\w)")
_SPACES = re.compile(r"[ \t]{2,}")


def _words(n: int | str) -> str:
    return num2words(int(n), lang="id")


def _decimal_words(whole: str, frac: str) -> str:
    return f"{_words(whole)} koma " + " ".join(DIGITS[int(d)] for d in frac)


def _rupiah(m: re.Match[str]) -> str:
    return f"{_words(m.group(1).replace('.', ''))} rupiah"


def _clock(hour: str, minute: str) -> str:
    text = _words(hour)
    return text if minute == "00" else f"{text} {_words(minute)}"


def _pukul_prefix(m: re.Match[str]) -> str:
    return "" if _PUKUL_BEFORE.search(m.string[: m.start()]) else "pukul "


def _time_range(m: re.Match[str]) -> str:
    h1, m1, h2, m2 = m.groups()
    return f"{_pukul_prefix(m)}{_clock(h1, m1)} sampai pukul {_clock(h2, m2)}"


def _time_one(m: re.Match[str]) -> str:
    return f"{_pukul_prefix(m)}{_clock(m.group(1), m.group(2))}"


def _date(m: re.Match[str]) -> str:
    return f"{_words(m.group(1))} {m.group(2)} {_words(m.group(3))}"


def _academic_year(m: re.Match[str]) -> str:
    return f"{_words(m.group(1))}, {_words(m.group(2))}"


def _phone(m: re.Match[str]) -> str | None:
    raw = m.group(0)
    if sum(c.isdigit() for c in raw) < 9:
        return raw
    groups = []
    for group in raw.split():
        words = ["plus"] if group.startswith("+") else []
        words += [DIGITS[int(c)] for c in group if c.isdigit()]
        if words:
            groups.append(" ".join(words))
    return ", ".join(groups)


def _landline(m: re.Match[str]) -> str:
    groups = [m.group(1), *m.group(2).split()]
    return ", ".join(" ".join(DIGITS[int(c)] for c in g if c.isdigit()) for g in groups)


def _percent(m: re.Match[str]) -> str:
    whole, _, frac = m.group(1).partition(",")
    number = _decimal_words(whole, frac) if frac else _words(whole)
    return f"{number} persen"


def _abbreviation_pattern() -> re.Pattern[str]:
    keys = sorted(ABBREVIATIONS, key=len, reverse=True)
    alternatives = "|".join(re.escape(k) + ("" if k.endswith(".") else r"(?!\w)") for k in keys)
    return re.compile(rf"(?<!\w)(?:{alternatives})")


_ABBREVIATION = _abbreviation_pattern()


def normalize_for_speech(text: str) -> str:
    text = _RUPIAH.sub(_rupiah, text)
    text = _TIME_RANGE.sub(_time_range, text)
    text = _TIME_ONE.sub(_time_one, text)
    text = _SD.sub("sampai", text)
    text = _WIB.sub("waktu Indonesia barat", text)
    text = _DATE.sub(_date, text)
    text = _ACADEMIC_YEAR.sub(_academic_year, text)
    text = _TA.sub("tahun ajaran", text)
    text = _PHONE.sub(_phone, text)
    text = _LANDLINE.sub(_landline, text)
    text = _ORDINAL.sub(lambda m: num2words(int(m.group(1)), lang="id", to="ordinal"), text)
    text = _PERCENT.sub(_percent, text)
    text = _DECIMAL.sub(lambda m: _decimal_words(m.group(1), m.group(2)), text)
    text = _THOUSANDS.sub(lambda m: _words(m.group(1).replace(".", "")), text)
    text = _INTEGER.sub(lambda m: _words(m.group(1)), text)
    text = _ABBREVIATION.sub(lambda m: ABBREVIATIONS[m.group(0)], text)
    return _SPACES.sub(" ", text).strip()
