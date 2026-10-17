"""M-12: WER untuk E-05 (STT). Normalisasi ditetapkan sebelum data dan dicatat di run.json.

Referensi dan hipotesis sama-sama: normalize_for_speech -> huruf kecil -> buang tanda baca ->
rapikan spasi; lalu jiwer.
"""

from __future__ import annotations

import re

from mica.audio.normalize import normalize_for_speech

WER_NORMALIZATION = (
    "normalize_for_speech -> huruf kecil -> buang tanda baca (selain huruf, angka, spasi) -> "
    "rapikan spasi; lalu jiwer.wer"
)
_PUNCT = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")


def normalize_for_wer(text: str) -> str:
    text = normalize_for_speech(text).lower()
    text = _PUNCT.sub(" ", text).replace("_", " ")
    return _SPACES.sub(" ", text).strip()


def wer(reference: str, hypothesis: str) -> float:
    """WER satu kalimat; keduanya dinormalkan lebih dulu."""
    import jiwer

    ref = normalize_for_wer(reference)
    hyp = normalize_for_wer(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return float(jiwer.wer(ref, hyp)) if hyp else 1.0


def corpus_wer(references: list[str], hypotheses: list[str]) -> float:
    """WER total atas seluruh daftar (jumlah kesalahan / jumlah kata referensi)."""
    import jiwer

    refs = [normalize_for_wer(r) for r in references]
    hyps = [normalize_for_wer(h) for h in hypotheses]
    return float(jiwer.wer(refs, hyps))
