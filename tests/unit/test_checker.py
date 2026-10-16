import json
from datetime import date
from pathlib import Path

import pytest

from mica.config import load_settings
from mica.core.types import CheckResult, Chunk
from mica.rag.checker import NumericFactChecker, make_checker

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "kb_dev_checker_chunks.json"

checker = NumericFactChecker()


def _chunk(text: str, i: int = 0) -> Chunk:
    return Chunk(f"doc#{i}", "doc", "Dokumen", "Bagian", date(2026, 9, 29), "dev", text, False)


def _check(answer: str, *sources: str) -> CheckResult:
    return checker.check(answer, [_chunk(s, i) for i, s in enumerate(sources)])


@pytest.fixture(scope="module")
def kb_dev() -> dict[str, Chunk]:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))["chunks"]
    return {
        c["chunk_id"]: Chunk(
            c["chunk_id"], c["doc_id"], c["doc_title"], c["section"],
            date.fromisoformat(c["valid_from"]), c["source_type"], c["text"], c["is_table"],
        )
        for c in raw
    }  # fmt: skip


@pytest.mark.parametrize(
    ("answer", "source"),
    [
        # nominal rupiah
        ("Biaya Rp7.500.000 per tahun.", "Biaya 7,5 juta per tahun."),
        ("Biaya Rp 7.500.000,- per tahun.", "Biaya Rp7.500.000 per tahun."),
        ("Biaya 7,5 juta per tahun.", "Biaya Rp7.500.000 per tahun."),
        ("Biaya Rp7,5 jt per tahun.", "Biaya Rp7.500.000 per tahun."),
        ("Biaya 7.500.000 rupiah per tahun.", "Biaya Rp7,5 juta per tahun."),
        ("Biaya Rp7.500.000,00.", "Biaya 7,5 juta."),
        ("Formulir Rp300 ribu.", "Formulir Rp300.000."),
        ("Formulir Rp300 rb.", "Formulir Rp300.000."),
        ("Dana Rp1,2 miliar.", "Dana Rp1.200.000.000."),
        ("Dana Rp1,2 M.", "Dana Rp1.200.000.000."),
        # desimal dan angka ambigu
        ("IPK minimal 2,75.", "IPK minimal 2.75."),
        ("IPK minimal 3,5.", "IPK minimal 3,5."),
        ("Nilai 2.750.", "Nilai 2,75."),
        ("Nilai 2.750.", "Nilai 2750."),
        # persentase
        ("Potongan 13%.", "Potongan 13 persen."),
        ("Potongan 13 persen.", "Potongan 13%."),
        ("Potongan 2,5%.", "Potongan 2.5 persen."),
        # tanggal
        ("Dibuka 17 September 2026.", "Dibuka 2026-09-17."),
        ("Dibuka 17-09-2026.", "Dibuka 17 September 2026."),
        ("Dibuka 17/9/2026.", "Dibuka 17 September 2026."),
        ("Dibuka 2026-09-17.", "Dibuka 17/09/2026."),
        ("Dibuka 17 Sep 2026.", "Dibuka 17 September 2026."),
        ("Dibuka 17 september 2026.", "Dibuka 17-09-2026."),
        ("Dibuka 2 Okt 2026.", "Dibuka 02/10/2026."),
        ("Dibuka 17 September.", "Dibuka 17 September 2026."),
        ("Pendaftaran tahun 2026.", "Dibuka 17 September 2026."),
        # jam
        ("Buka 09.00.", "Buka 9:00."),
        ("Buka 9:00.", "Buka 09.00 WIB."),
        ("Buka pukul 9 WIB.", "Buka 09.00."),
        ("Buka pukul 9 pagi.", "Buka 09.00."),
        ("Tutup pukul 3 sore.", "Tutup 15.00."),
        ("Buka pukul 09.00 WIB.", "Buka 9:00."),
        # telepon
        ("WhatsApp 0811 602 5151.", "WhatsApp +62 811-602-5151."),
        ("WhatsApp +628116025151.", "WhatsApp 0811.602.5151."),
        ("Telepon (061) 4573767.", "Telepon 061-4573767."),
    ],
)
def test_same_value_other_format_passes(answer, source):
    result = _check(answer, source)
    assert result == CheckResult(passed=True, unsupported=(), checked=1)


@pytest.mark.parametrize(
    ("answer", "source"),
    [
        ("Biaya Rp14.500.000 per tahun.", "Biaya Rp14.000.000 per tahun."),
        ("Biaya 14,5 juta per tahun.", "Biaya Rp14.000.000 per tahun."),
        ("Biaya Rp15 juta per tahun.", "Biaya Rp14.000.000 per tahun."),
        ("Biaya Rp140.000.000 per tahun.", "Biaya Rp14.000.000 per tahun."),
        ("Dibuka 18 September 2026.", "Dibuka 17 September 2026."),
        ("Dibuka 16-09-2026.", "Dibuka 17 September 2026."),
        ("Dibuka 2026-09-18.", "Dibuka 17 September 2026."),
        ("Dibuka 17 September 2027.", "Dibuka 17 September 2026."),
        ("Dibuka 18 September.", "Dibuka 17 September 2026."),
        ("Potongan 14%.", "Potongan 13%."),
        ("Potongan 1,3%.", "Potongan 13%."),
        ("IPK minimal 2,57.", "IPK minimal 2,75."),
        ("Buka pukul 10 WIB.", "Buka 09.00 WIB."),
        ("Buka 09.30.", "Buka 09.00 WIB."),
        ("Buka pukul 9 malam.", "Buka 09.00 WIB."),
        ("WhatsApp 0811 602 5152.", "WhatsApp 0811 602 5151."),
    ],
)
def test_fabricated_value_rejected(answer, source):
    result = _check(answer, source)
    assert result.passed is False
    assert result.checked == 1
    assert len(result.unsupported) == 1


def test_one_correct_one_fabricated_reports_only_fabricated():
    result = _check(
        "Kelas pagi Rp14.000.000 per tahun dan daftar ulang Rp2.500.000.",
        "Kelas pagi Rp14.000.000 per tahun.",
    )
    assert result == CheckResult(passed=False, unsupported=("Rp2.500.000",), checked=2)


def test_answer_without_numbers_passes():
    assert _check("Silakan hubungi Admisi.", "Rp14.000.000") == CheckResult(True, (), 0)


def test_list_numbering_and_letter_digits_ignored():
    answer = "1. Biaya S1 Rp14.000.000\n2) Kelas sore Rp15.000.000"
    result = _check(answer, "S1: Rp14.000.000 pagi, Rp15.000.000 sore.")
    assert result == CheckResult(passed=True, unsupported=(), checked=2)


def test_sources_are_joined():
    result = _check("Pagi Rp14.000.000, sore Rp15.000.000.", "Pagi Rp14.000.000.", "Sore 15 juta.")
    assert result.passed is True and result.checked == 2


def test_make_checker():
    settings = load_settings(ROOT / "config" / "dev.yaml")
    assert isinstance(make_checker(settings), NumericFactChecker)


# Teks chunk asli KB dev (tests/fixtures/kb_dev_checker_chunks.json)


def test_kb_dev_biaya_si(kb_dev):
    sources = [kb_dev["03_biaya_kuliah_dan_syarat_masuk#2"]]
    ok = checker.check(
        "Biaya kuliah S1 Sistem Informasi Rp14.000.000 per tahun untuk kelas pagi "
        "dan 15 juta per tahun untuk kelas sore.",
        sources,
    )
    assert ok == CheckResult(passed=True, unsupported=(), checked=2)
    bad = checker.check("Biaya kuliah S1 Sistem Informasi Rp14,5 juta per tahun.", sources)
    assert bad == CheckResult(passed=False, unsupported=("Rp14,5 juta",), checked=1)


def test_kb_dev_jadwal_gelombang_s1(kb_dev):
    sources = [kb_dev["02_pendaftaran_dan_jadwal#3"]]
    ok = checker.check(
        "Gelombang 1 berlangsung 17-09-2026 sampai 31 Mei 2027, "
        "Gelombang 2 mulai 2 Juni 2027 sampai 4 Sep 2027.",
        sources,
    )
    assert ok == CheckResult(passed=True, unsupported=(), checked=6)
    bad = checker.check("Gelombang 2 ditutup 5 September 2027.", sources)
    assert bad == CheckResult(passed=False, unsupported=("5 September 2027",), checked=2)


def test_kb_dev_jam_layanan_admisi(kb_dev):
    sources = [kb_dev["02_pendaftaran_dan_jadwal#8"]]
    ok = checker.check(
        "Admisi buka Senin sampai Jumat pukul 9 pagi sampai 20.30 WIB, Sabtu 09.00 sampai "
        "17.00 WIB, istirahat 12.00 sampai 13.00. WhatsApp +62 811-602-5151.",
        sources,
    )
    assert ok == CheckResult(passed=True, unsupported=(), checked=7)
    bad = checker.check("Admisi buka Senin sampai Jumat 09.00 sampai 21.00 WIB.", sources)
    assert bad == CheckResult(passed=False, unsupported=("21.00 WIB",), checked=2)


# Rentang tanggal di sumber: hanya ujung awal dan akhir


RANGE_SOURCES = [
    "Matrikulasi 22 sampai 27 Februari 2027.",
    "Matrikulasi 22-27 Februari 2027.",
    "Matrikulasi 22–27 Feb 2027.",
    "Matrikulasi 22 hingga 27 Februari 2027.",
    "Matrikulasi 22 s.d. 27 Februari 2027.",
    "Matrikulasi 22 s/d 27 Februari 2027.",
]


@pytest.mark.parametrize("source", RANGE_SOURCES)
@pytest.mark.parametrize(
    ("answer", "passed"),
    [("22 Februari 2027", True), ("27 Februari 2027", True), ("25 Februari 2027", False),
     ("21 Februari 2027", False), ("28 Februari 2027", False)],
)  # fmt: skip
def test_range_same_month_endpoints_only(source, answer, passed):
    result = _check(f"Matrikulasi dimulai {answer}.", source)
    assert result.passed is passed and result.checked == 1


@pytest.mark.parametrize(
    ("answer", "passed"),
    [("22 Februari 2027", True), ("3 Maret 2027", True), ("1 Maret 2027", False),
     ("22 Maret 2027", False)],
)  # fmt: skip
def test_range_across_months(answer, passed):
    result = _check(f"Mulai {answer}.", "Periode 22 Februari sampai 3 Maret 2027.")
    assert result.passed is passed


@pytest.mark.parametrize(
    ("answer", "passed"),
    [("17 September 2026", True), ("31 Mei 2027", True), ("30 Mei 2027", False)],
)
def test_range_full_dates(answer, passed):
    result = _check(
        f"Gelombang 1 ditutup {answer}.", "Gelombang 1: 17 September 2026 s.d. 31 Mei 2027."
    )
    assert result.passed is passed


def test_range_across_year_end():
    source = "Libur 20 Desember s/d 5 Januari 2027."
    assert _check("Libur mulai 20 Desember 2026.", source).passed is True
    assert _check("Libur mulai 20 Desember 2027.", source).passed is False


def test_range_in_answer_checks_both_endpoints():
    source = "Matrikulasi 22 sampai 27 Februari 2027."
    assert _check("Matrikulasi 22-27 Februari 2027.", source) == CheckResult(True, (), 2)
    assert _check("Matrikulasi 22-28 Februari 2027.", source) == CheckResult(
        False, ("28 Februari 2027",), 2
    )
