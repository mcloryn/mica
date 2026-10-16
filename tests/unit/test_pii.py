import pytest

from mica.core.types import ScrubbedText
from mica.rag.pii import scrub_pii


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("email budi.santoso@gmail.com ya", "email [EMAIL] ya"),
        ("kirim ke a_b+pmb@mail.mikroskil.ac.id", "kirim ke [EMAIL]"),
        ("NIK saya 1271012345678901", "NIK saya [NIK]"),
        ("HP 081234567890", "HP [TELEPON]"),
        ("HP 0812-3456-7890 ya", "HP [TELEPON] ya"),
        ("HP 0812 3456 7890", "HP [TELEPON]"),
        ("HP 0812.3456.7890", "HP [TELEPON]"),
        ("wa +62 812 3456 7890", "wa [TELEPON]"),
        ("wa +6281234567890", "wa [TELEPON]"),
        ("wa 6281234567890", "wa [TELEPON]"),
        ("telp 061-4573767", "telp [TELEPON]"),
        ("telp (061) 4573767", "telp [TELEPON]"),
        ("HP 081234567 (9 digit)", "HP [TELEPON] (9 digit)"),
        ("HP 0812345678901 (13 digit)", "HP [TELEPON] (13 digit)"),
        (
            "Saya Budi, 0812-3456-7890, budi@x.id, NIK 1271012345678901.",
            "Saya Budi, [TELEPON], [EMAIL], NIK [NIK].",
        ),
    ],
)
def test_pii_masked(text, expected):
    result = scrub_pii(text)
    assert result == expected
    assert isinstance(result, ScrubbedText)


@pytest.mark.parametrize(
    "text",
    [
        "Biaya Rp14.000.000 per tahun",
        "Biaya Rp 625.000.000.000",
        "Dana 62.500.000 rupiah",
        "Biaya 7,5 juta",
        "Tahun 2026 dan 2027/2028",
        "Tanggal 17-09-2026, 01/09/2026, 2026-09-17, 17 September 2026",
        "Jam 09.00 sampai 20.30 WIB, pukul 9:00",
        "Kode mata kuliah 21.ECGR.101",
        "Gelombang 2, 6 langkah, IPK 2,75, potongan 13%",
        "Nomor pendek 08123",
        "Deretan 17 digit 12345678901234567",
        "Deretan 15 digit 127101234567890",
        "HP 14 digit 08123456789012",
    ],
)
def test_non_pii_untouched(text):
    assert scrub_pii(text) == text


def test_scrub_is_idempotent():
    once = scrub_pii("HP 0812-3456-7890, budi@x.id")
    assert scrub_pii(once) == once
