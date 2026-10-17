"""M-08 normalize_for_speech: tiap aturan dan contoh asli KB dev (data/sources/dev)."""

import pytest

from mica.audio.normalize import normalize_for_speech as norm
from mica.rag.prompts import REFUSAL, UNAVAILABLE


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Rp15.000.000", "lima belas juta rupiah"),
        ("Rp 15.000.000", "lima belas juta rupiah"),
        ("Rp300.000,00", "tiga ratus ribu rupiah"),
        ("Rp1000,00", "seribu rupiah"),
        ("Rp15.000.000,-", "lima belas juta rupiah"),
        ("Rp12.500.000 per tahun", "dua belas juta lima ratus ribu rupiah per tahun"),
    ],
)
def test_rupiah(text, expected):
    assert norm(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("09.00-15.00", "pukul sembilan sampai pukul lima belas"),
        ("09.00 – 15.00", "pukul sembilan sampai pukul lima belas"),
        ("09.00 s.d. 15.00", "pukul sembilan sampai pukul lima belas"),
        ("09.00 sampai 17.00", "pukul sembilan sampai pukul tujuh belas"),
        ("17.45", "pukul tujuh belas empat puluh lima"),
        ("09.00", "pukul sembilan"),
        ("pukul 09.30", "pukul sembilan tiga puluh"),
        ("pukul 18.00 sampai 20.00", "pukul delapan belas sampai pukul dua puluh"),
        ("Senin s.d. Jumat", "Senin sampai Jumat"),
    ],
)
def test_time(text, expected):
    assert norm(text) == expected


def test_time_not_part_of_other_numbers():
    assert norm("12.500 orang") == "dua belas ribu lima ratus orang"
    assert norm("24.00") != "pukul dua puluh empat"  # jam 24 tidak sah


def test_wib_date_academic_year():
    assert norm("09.00 WIB") == "pukul sembilan waktu Indonesia barat"
    assert norm("29 September 2026") == "dua puluh sembilan September dua ribu dua puluh enam"
    assert norm("2026/2027") == "dua ribu dua puluh enam, dua ribu dua puluh tujuh"
    assert norm("T.A. 2026/2027").startswith("tahun ajaran dua ribu dua puluh enam,")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0811 602 5151", "nol delapan satu satu, enam nol dua, lima satu lima satu"),
        (
            "+62 851 7346 3468",
            "plus enam dua, delapan lima satu, tujuh tiga empat enam, tiga empat enam delapan",
        ),
        (
            "+6281170703990",
            "plus enam dua delapan satu satu tujuh nol tujuh nol tiga sembilan sembilan nol",
        ),
        (
            "+62 811-7070-3990",
            "plus enam dua, delapan satu satu tujuh nol tujuh nol tiga sembilan sembilan nol",
        ),
    ],
)
def test_phone(text, expected):
    assert norm(text) == expected


def test_short_08_number_is_not_phone():
    assert norm("08 orang") == "delapan orang"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("88%", "delapan puluh delapan persen"),
        ("3,5", "tiga koma lima"),
        ("2,75", "dua koma tujuh lima"),
        ("1.000", "seribu"),
        ("120", "seratus dua puluh"),
        ("ke-2", "kedua"),
    ],
)
def test_numbers(text, expected):
    assert norm(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("S1", "es satu"),
        ("S2", "es dua"),
        ("S3", "es tiga"),
        ("D3", "de tiga"),
        ("SKS", "es ka es"),
        ("IPK", "i pe ka"),
        ("PMB", "pe em be"),
        ("KIP", "kip"),
        ("dll", "dan lain-lain"),
        ("dsb", "dan sebagainya"),
        ("No. 140", "nomor seratus empat puluh"),
        ("Jl. Thamrin", "jalan Thamrin"),
    ],
)
def test_abbreviations(text, expected):
    assert norm(text) == expected


def test_abbreviations_whole_word_case_sensitive():
    assert norm("SMKN1 dan IP4") == "SMKN1 dan IP4"  # kode di luar kamus dibiarkan
    assert norm("pmb") == "pmb" and norm("SKSnya") == "SKSnya"


def test_spaces_collapsed():
    assert norm("  Halo   kamu  ") == "Halo kamu"


# Contoh asli dari sumber KB dev (data/sources/dev, 15 Okt 2026)
KB_EXAMPLES = [
    (
        ("Senin sampai Jumat 09.00 sampai 20.30 WIB; Sabtu 09.00 sampai 17.00 WIB; "
        "istirahat 12.00 sampai 13.00"),
        ("Senin sampai Jumat pukul sembilan sampai pukul dua puluh tiga puluh waktu Indonesia "
        "barat; Sabtu pukul sembilan sampai pukul tujuh belas waktu Indonesia barat; istirahat "
        "pukul dua belas sampai pukul tiga belas"),
    ),
    ("Senin | 17.45 – 20.50", "Senin | pukul tujuh belas empat puluh lima sampai pukul dua puluh lima puluh"),
    ("12:00 – 13:00 WIB", "pukul dua belas sampai pukul tiga belas waktu Indonesia barat"),
    ("Jumat: 09.00 s.d. 20.00 WIB", "Jumat: pukul sembilan sampai pukul dua puluh waktu Indonesia barat"),
    ("s.d 15:00 WIB", "sampai pukul lima belas waktu Indonesia barat"),
    ("biaya Rp300.000,00,", "biaya tiga ratus ribu rupiah,"),
    (
        "## Jadwal Pendaftaran Program Sarjana (S1) T.A. 2027/2028",
        ("## Jadwal Pendaftaran Program Sarjana (es satu) tahun ajaran dua ribu dua puluh tujuh, "
        "dua ribu dua puluh delapan"),
    ),
    (
        "17 September 2026 sampai 31 Mei 2027",
        ("tujuh belas September dua ribu dua puluh enam sampai tiga puluh satu Mei dua ribu dua "
        "puluh tujuh"),
    ),
    ("WhatsApp 0811 602 5151;", "WhatsApp nol delapan satu satu, enam nol dua, lima satu lima satu;"),
    (
        "- 88% lulusan sudah bekerja kurang dari 6 bulan setelah lulus.",
        "- delapan puluh delapan persen lulusan sudah bekerja kurang dari enam bulan setelah lulus.",
    ),
    ("Lulus dalam 3,5 Tahun", "Lulus dalam tiga koma lima Tahun"),
    ('penerima "Beasiswa IP4" per semester', 'penerima "Beasiswa IP4" per semester'),
]  # fmt: skip


@pytest.mark.parametrize(("text", "expected"), KB_EXAMPLES)
def test_kb_dev_examples(text, expected):
    assert norm(text) == expected


def test_refusal_texts_only_abbreviation_changes():
    assert norm(REFUSAL) == REFUSAL.replace("PMB", "pe em be")
    assert norm(UNAVAILABLE) == UNAVAILABLE.replace("PMB", "pe em be")
