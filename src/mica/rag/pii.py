"""M-06: scrub_pii, penyamaran data pribadi sebelum teks dikirim ke API atau ditulis ke log.

Non-ADR: aturan regex sederhana untuk N-09 dan F-18 (SDD M-06). Urutan: email, NIK, telepon.
- Email -> [EMAIL].
- Deretan tepat 16 digit tanpa pemisah (format NIK) -> [NIK].
- Telepon Indonesia diawali 0, 62, atau +62, dengan 9-13 digit (62 dihitung sebagai 0), boleh
  dipisah spasi, titik, tanda hubung, atau kurung kode area ("(061) 4573767") -> [TELEPON].

Yang sengaja tidak disamarkan: nominal ("Rp14.000.000", "62.500.000"), tahun, tanggal, jam, dan
kode seperti "21.ECGR.101". Deretan berpola ribuan (kelompok 3 digit dipisah titik) dianggap
nominal, bukan telepon.
"""

from __future__ import annotations

import re

from mica.core.types import ScrubbedText

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
NIK = re.compile(r"(?<![\d.,])\d{16}(?![\d]|[.,]\d)")
PHONE = re.compile(r"(?<![\w+.,])(?:\+62|62|\(0|0)(?:\)?[ .-]?\d){8,12}(?![ .-]?\d)")
THOUSANDS = re.compile(r"\d{1,3}(?:\.\d{3})+")


def _phone(match: re.Match[str]) -> str:
    raw = match.group()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith(("+62", "62")):
        digits = "0" + digits[2:]
    if not 9 <= len(digits) <= 13 or THOUSANDS.fullmatch(raw):
        return raw
    return "[TELEPON]"


def scrub_pii(text: str) -> ScrubbedText:
    text = EMAIL.sub("[EMAIL]", text)
    text = NIK.sub("[NIK]", text)
    text = PHONE.sub(_phone, text)
    return ScrubbedText(text)
