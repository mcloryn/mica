"""M-04: cek angka jawaban terhadap potongan sumber (ADR-06 lapis 3, Provisional).

NumericFactChecker mengekstrak nominal rupiah, angka, desimal, persentase, tanggal, jam, dan
nomor telepon dari jawaban, menormalisasinya ke nilai pembanding, lalu mencarinya di gabungan
teks sumber yang dinormalisasi dengan fungsi yang sama.

Setiap token punya `interps` (semua tafsiran yang mungkin; token ambigu seperti "09.00" atau
"2.750" punya lebih dari satu) dan `implied` (fakta tambahan yang hanya dipakai di sisi sumber,
misalnya "17 September 2026" juga mendukung "17 September" dan tahun "2026"). Token jawaban
didukung bila salah satu tafsirannya ada di indeks sumber.

Keterlacakan normalisasi:
- Rupiah: "Rp7.500.000", "Rp 7.500.000,-", "7,5 juta", "Rp7,5 jt", "7.500.000 rupiah" -> 7500000;
  pengali ribu/rb, juta/jt, miliar/milyar/M, triliun. Setelah "Rp" tanpa pengali, titik dibaca
  sebagai pemisah ribuan saja.
- Desimal: koma gaya Indonesia ("2,75") dan titik gaya Inggris ("2.75") sama-sama dibaca.
- Tanggal: "17 September 2026", "17 Sep 2026", "17-09-2026", "17/9/2026", "17.09.2026",
  "2026-09-17" -> 2026-09-17; tanggal tanpa tahun ("17 September") dicocokkan dengan hari-bulan.
- Jam: "09.00", "9:00", "pukul 9 WIB/pagi" -> 09:00; "sore" (jam < 12) dan "malam" (jam 6-11)
  ditambah 12, "siang" (jam < 6) ditambah 12. "pukul 9" tanpa penanda dibaca sebagai angka 9.
- Telepon: diawali 0, +62, atau "(0", 9-13 digit; hanya urutan digit, +62 disamakan dengan 0.
- Diabaikan: penomoran daftar di awal baris ("1.", "2)") dan angka yang menempel pada huruf
  ("S1", "IP4").

Keterbatasan (bisa lolos padahal salah, atau ditolak padahal benar):
- Hanya nilai yang dicek, bukan pasangannya: "SI kelas pagi Rp15.000.000" lolos bila
  Rp15.000.000 ada di sumber untuk kelas sore.
- Token ambigu dianggap didukung bila satu tafsiran cocok: "09.00" didukung oleh angka 9 mana
  pun di sumber, "2.750" didukung oleh 2,75.
- Angka kecil (1, 2, 3) hampir selalu ada di sumber, sehingga hampir tidak pernah ditolak.
- Angka yang ditulis sebagai kata ("tiga jalur", "lima juta") tidak diekstrak sama sekali.
- Rentang di sumber tidak diuraikan: "22 sampai 27 Februari 2027" tidak mendukung jawaban
  "22 Februari 2027".
- Hasil hitung (jumlah, selisih, biaya per semester dari biaya per tahun) selalu ditolak.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from mica.config import Settings
from mica.core.types import CheckResult, Chunk

MASK = "\x00"  # pengganti span yang sudah diekstrak; bukan \w dan bukan spasi

MONTHS = {
    "januari": 1, "jan": 1,
    "februari": 2, "feb": 2, "peb": 2,
    "maret": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "agustus": 8, "agu": 8, "agt": 8, "ags": 8,
    "september": 9, "sept": 9, "sep": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11, "nop": 11,
    "desember": 12, "des": 12,
}  # fmt: skip
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))

MULTIPLIERS = {
    "ribu": 10**3, "rb": 10**3,
    "juta": 10**6, "jt": 10**6,
    "miliar": 10**9, "milyar": 10**9, "m": 10**9,
    "triliun": 10**12,
}  # fmt: skip

# angka: ribuan bertitik, ribuan berkoma, atau bilangan dengan satu pemisah desimal
_NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?"
_MULT = r"(?:(?i:ribu|rb|juta|jt|miliar|milyar|triliun)|M)\b"
_TIME_MARK = r"(?i:WIB|WITA|WIT|pagi|siang|sore|malam)\b"

LIST_MARKER = re.compile(r"^([ \t]*)\d{1,2}[.)](?=[ \t])", re.MULTILINE)
PHONE = re.compile(r"(?<![\w+])(?:\+62[ .-]?|\(0|0)\d[\d .()-]*\d")
DATE_TEXT = re.compile(
    rf"(?<![\w.,])(\d{{1,2}})[ \t]+((?i:{_MONTH_RE}))\.?(?:[ \t]+(\d{{4}}))?(?!\w)"
)
DATE_DMY = re.compile(r"(?<![\w.,/-])(\d{1,2})([-/.])(\d{1,2})\2(\d{4})(?![\w/-]|[.,]\d)")
DATE_ISO = re.compile(r"(?<![\w.,/-])(\d{4})-(\d{1,2})-(\d{1,2})(?![\w/-]|[.,]\d)")
MONEY_RP = re.compile(
    rf"(?<!\w)(?i:Rp)\.?[ \t]*({_NUM})(?:,-)?(?:[ \t]*({_MULT}))?(?:[ \t]*(?i:rupiah)\b)?"
)
MONEY_WORD = re.compile(
    rf"(?<![\w.,])({_NUM})(?:[ \t]*({_MULT})(?:[ \t]*(?i:rupiah)\b)?|(?:,-)?[ \t]*(?i:rupiah)\b)"
)
PERCENT = re.compile(rf"(?<![\w.,])({_NUM})[ \t]*(?:%|(?i:persen)\b)")
TIME_WORD = re.compile(
    rf"(?i:pukul|jam)[ \t]+(\d{{1,2}})(?:[.:](\d{{2}}))?(?![\d.,:])(?:[ \t]*({_TIME_MARK}))?"
)
TIME_CLOCK = re.compile(
    rf"(?<![\w.,:])(\d{{1,2}})([.:])(\d{{2}})(?![\w]|[.,:]\d)(?:[ \t]*({_TIME_MARK}))?"
)
NUMBER = re.compile(rf"(?<![\w.,])({_NUM})(?!\w|[.,]\d)")

Interp = tuple[str, object]


@dataclass(frozen=True)
class NumericToken:
    text: str  # teks asli di jawaban atau sumber
    interps: frozenset[Interp]  # semua tafsiran token ini
    implied: frozenset[Interp] = frozenset()  # fakta tambahan, hanya untuk indeks sumber


Built = tuple[NumericToken, int] | None  # token dan ujung span-nya, atau None bila bukan token


class FactChecker(Protocol):
    def check(self, answer: str, sources: list[Chunk]) -> CheckResult: ...


def number_values(text: str, thousands_only: bool = False) -> set[Decimal]:
    """Semua tafsiran angka; "2.750" -> {2750, 2.75}, "2,75" -> {2.75}, "7.500.000" -> {7500000}."""
    if "." in text and "," in text:
        if text.rfind(",") > text.rfind("."):
            return {Decimal(text.replace(".", "").replace(",", "."))}
        return {Decimal(text.replace(",", ""))}
    for sep, decimal_ok in ((".", not thousands_only), (",", True)):
        if sep in text:
            parts = text.split(sep)
            values: set[Decimal] = set()
            head = parts[0]
            if head[0] != "0" and len(head) <= 3 and all(len(p) == 3 for p in parts[1:]):
                values.add(Decimal("".join(parts)))
            if len(parts) == 2 and (decimal_ok or not values):
                values.add(Decimal(".".join(parts)))
            return values
    return {Decimal(text)}


def _nums(values: Iterable[Decimal], kind: str = "num") -> frozenset[Interp]:
    return frozenset((kind, v) for v in values)


def _date_token(text: str, day: int, month: int, year: int | None) -> NumericToken | None:
    try:
        date(year or 2024, month, day)  # 2024 kabisat, supaya 29 Februari tanpa tahun sah
    except ValueError:
        return None
    if year is None:
        return NumericToken(text, frozenset({("dm", (month, day))}))
    return NumericToken(
        text,
        frozenset({("date", date(year, month, day))}),
        frozenset({("dm", (month, day)), ("num", Decimal(year))}),
    )


def _hour_24(hour: int, mark: str | None) -> int:
    mark = (mark or "").lower()
    if (mark == "sore" and hour < 12) or (mark == "siang" and hour < 6):
        return hour + 12
    if mark == "malam" and 6 <= hour < 12:
        return hour + 12
    return hour


def _time_token(text: str, hour: int, minute: int, extra: frozenset[Interp]) -> NumericToken | None:
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return NumericToken(text, frozenset({("time", (hour, minute))}) | extra)


def _phone_token(match: re.Match[str]) -> tuple[NumericToken, int] | None:
    """Ambil awalan terpanjang yang berisi 9-13 digit; kembalikan token dan ujung span."""
    raw = match.group()
    best: tuple[NumericToken, int] | None = None
    for group in re.finditer(r"\d+", raw):
        span_text = raw[: group.end()]
        digits = re.sub(r"\D", "", span_text)
        if span_text.startswith("+62"):
            digits = "0" + digits[2:]
        if len(digits) > 13:
            break
        if len(digits) >= 9:
            best = (NumericToken(span_text, frozenset({("phone", digits)})), group.end())
    return best


def _scan(text: str) -> Iterator[tuple[int, NumericToken]]:
    """Token berurutan menurut jenis; span yang sudah diambil diganti MASK."""
    buf = LIST_MARKER.sub(lambda m: m.group(1) + MASK * (len(m.group()) - len(m.group(1))), text)

    def take(start: int, end: int) -> None:
        nonlocal buf
        buf = buf[:start] + MASK * (end - start) + buf[end:]

    def run(
        pattern: re.Pattern[str], build: Callable[[re.Match[str]], Built]
    ) -> Iterator[tuple[int, NumericToken]]:
        for m in list(pattern.finditer(buf)):
            built = build(m)
            if built is None:
                continue
            token, end = built
            take(m.start(), end)
            yield m.start(), token

    def phone(m: re.Match[str]) -> Built:
        found = _phone_token(m)
        return found and (found[0], m.start() + found[1])

    def date_text(m: re.Match[str]) -> Built:
        year = int(m.group(3)) if m.group(3) else None
        token = _date_token(m.group(), int(m.group(1)), MONTHS[m.group(2).lower()], year)
        return token and (token, m.end())

    def date_dmy(m: re.Match[str]) -> Built:
        token = _date_token(m.group(), int(m.group(1)), int(m.group(3)), int(m.group(4)))
        return token and (token, m.end())

    def date_iso(m: re.Match[str]) -> Built:
        token = _date_token(m.group(), int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return token and (token, m.end())

    def money(m: re.Match[str]) -> Built:
        mult = m.group(2)
        values = number_values(m.group(1), thousands_only=mult is None and m.re is MONEY_RP)
        factor = MULTIPLIERS[mult.lower()] if mult else 1
        return NumericToken(m.group(), _nums(v * factor for v in values)), m.end()

    def percent(m: re.Match[str]) -> Built:
        return NumericToken(m.group(), _nums(number_values(m.group(1)), "pct")), m.end()

    def time_word(m: re.Match[str]) -> Built:
        if m.group(2) is None and m.group(3) is None:
            return None  # "pukul 9" tanpa penanda: dibaca sebagai angka biasa
        hour = _hour_24(int(m.group(1)), m.group(3))
        token = _time_token(m.group(), hour, int(m.group(2) or 0), frozenset())
        return token and (token, m.end())

    def time_clock(m: re.Match[str]) -> Built:
        hour, sep, minute, mark = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
        # "09.00" tanpa penanda juga bisa angka desimal; "9:00" dan "09.00 WIB" pasti jam
        extra: frozenset[Interp] = frozenset()
        if sep == "." and mark is None:
            extra = _nums({Decimal(f"{m.group(1)}.{m.group(3)}")})
        token = _time_token(m.group(), _hour_24(hour, mark), minute, extra)
        return token and (token, m.end())

    def number(m: re.Match[str]) -> Built:
        return NumericToken(m.group(), _nums(number_values(m.group()))), m.end()

    # urutan penting: jenis yang lebih spesifik diambil dulu
    for pattern, build in (
        (PHONE, phone),
        (DATE_TEXT, date_text),
        (DATE_DMY, date_dmy),
        (DATE_ISO, date_iso),
        (MONEY_RP, money),
        (MONEY_WORD, money),
        (PERCENT, percent),
        (TIME_WORD, time_word),
        (TIME_CLOCK, time_clock),
        (NUMBER, number),
    ):
        yield from run(pattern, build)


def extract_numbers(text: str) -> list[NumericToken]:
    """Semua token angka di teks, urut menurut posisi."""
    return [token for _, token in sorted(_scan(text), key=lambda item: item[0])]


def source_index(sources: Iterable[Chunk]) -> frozenset[Interp]:
    text = "\n".join(chunk.text for chunk in sources)
    index: set[Interp] = set()
    for token in extract_numbers(text):
        index |= token.interps | token.implied
    return frozenset(index)


class NumericFactChecker:
    def check(self, answer: str, sources: list[Chunk]) -> CheckResult:
        tokens = extract_numbers(answer)
        if not tokens:
            return CheckResult(passed=True, unsupported=(), checked=0)
        index = source_index(sources)
        unsupported = tuple(t.text for t in tokens if not (t.interps & index))
        return CheckResult(passed=not unsupported, unsupported=unsupported, checked=len(tokens))


def make_checker(settings: Settings) -> FactChecker:
    # Baru ada satu implementasi. rag.fact_check.enabled diperiksa pipeline (SDD 7.3): bila
    # false, checker tidak dipanggil.
    return NumericFactChecker()
