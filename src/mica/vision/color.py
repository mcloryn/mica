"""M-07 penamaan warna pakaian (ADR-14; SDD 7.3 penamaan warna).

ColorNamesLut memakai tabel van de Weijer dkk. (IEEE TIP 2009) [30], diunduh dengan
`python -m mica.vision fetch-colors` ke models/ (tidak di-commit: halaman sumber tidak mencantumkan
lisensi). Format yang diverifikasi dari ColorNaming.tar (im2c.m, readme.txt, w2c.txt):
- 32.768 baris = grid 32x32x32 sRGB, bin 8 nilai; indeks baris (0-based)
  = R//8 + 32*(G//8) + 1024*(B//8) (R paling cepat berubah);
- kolom 1-3 = pusat bin (3.5, 11.5, ...), kolom 4-14 = peluang 11 nama dengan urutan
  black, blue, brown, grey, green, orange, pink, purple, red, white, yellow.
Tabel disimpan sebagai .npy (32768, 11) float32, hanya kolom peluang.

Piksel masuk dalam urutan kanal BGR (frame OpenCV) dan hanya diproses di memori (N-08).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from mica.core.types import ErrorCode

# urutan kolom tabel van de Weijer, diterjemahkan
COLOR_NAMES = (
    "hitam",
    "biru",
    "cokelat",
    "abu-abu",
    "hijau",
    "oranye",
    "merah muda",
    "ungu",
    "merah",
    "putih",
    "kuning",
)
TABLE_ROWS = 32 * 32 * 32
DEFAULT_COLORS_FILE = Path("models/color_names_w2c.npy")
# sha256 tabel .npy hasil fetch-colors (np.save dari tar ber-sha256 COLORS_TAR_SHA256), diukur
# dari file di laptop dev 16 Okt 2026
COLORS_NPY_SHA256 = "ad16540fe280bb07abec27db5d66df2b97e03cd9f02297d8633a0d0e54120011"


class ColorsMissing(Exception):
    def __init__(self, path: Path) -> None:
        self.code = ErrorCode.VISION_COLORS_MISSING
        self.path = path
        super().__init__(
            f"{self.code}: tabel nama warna {Path(path).as_posix()} tidak ada; "
            "unduh dulu di mode dev: python -m mica.vision fetch-colors"
        )


@dataclass(frozen=True)
class ColorResult:
    label: str | None  # None bila majority < min_majority (sapaan tanpa warna, COLOR_UNSURE)
    majority: float  # proporsi suara warna terbanyak
    top: str | None  # warna terbanyak walau di bawah min_majority (debug); None bila tanpa piksel
    distribution: tuple[float, ...]  # proporsi per COLOR_NAMES
    pixels: int

    def ranked(self, n: int = 3) -> list[tuple[str, float]]:
        order = np.argsort(self.distribution)[::-1][:n]
        return [(COLOR_NAMES[i], self.distribution[i]) for i in order if self.distribution[i] > 0]


def result_from_distribution(
    distribution: np.ndarray, min_majority: float, pixels: int
) -> ColorResult:
    total = float(distribution.sum())
    if total <= 0:
        return ColorResult(None, 0.0, None, (0.0,) * len(COLOR_NAMES), pixels)
    share = distribution / total
    top = int(share.argmax())
    majority = float(share[top])
    label = COLOR_NAMES[top] if majority >= min_majority else None
    return ColorResult(label, majority, COLOR_NAMES[top], tuple(float(v) for v in share), pixels)


class ColorNamer(Protocol):
    def name(self, pixels: np.ndarray) -> ColorResult: ...


def lut_index(pixels_bgr: np.ndarray) -> np.ndarray:
    """Piksel BGR uint8 (..., 3) -> indeks baris tabel (format im2c.m)."""
    px = np.asarray(pixels_bgr, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
    b, g, r = px[:, 0], px[:, 1], px[:, 2]
    return r // 8 + 32 * (g // 8) + 1024 * (b // 8)


class ColorNamesLut:
    """Setiap piksel diberi nama argmax tabel, lalu voting mayoritas."""

    def __init__(self, table: np.ndarray, min_majority: float) -> None:
        table = np.asarray(table)
        if table.shape != (TABLE_ROWS, len(COLOR_NAMES)):
            raise ValueError(
                f"tabel warna harus berukuran {(TABLE_ROWS, 11)}, didapat {table.shape}"
            )
        self.labels = table.argmax(axis=1).astype(np.int64)
        self.min_majority = min_majority

    @classmethod
    def load(cls, path: Path, min_majority: float) -> ColorNamesLut:
        path = Path(path)
        if not path.is_file():
            raise ColorsMissing(path)
        return cls(np.load(path, allow_pickle=False), min_majority)

    def counts(self, pixels: np.ndarray) -> np.ndarray:
        if pixels is None or np.asarray(pixels).size == 0:
            return np.zeros(len(COLOR_NAMES), dtype=np.int64)
        return np.bincount(self.labels[lut_index(pixels)], minlength=len(COLOR_NAMES))

    def name(self, pixels: np.ndarray) -> ColorResult:
        counts = self.counts(pixels)
        return result_from_distribution(counts.astype(float), self.min_majority, int(counts.sum()))


class ColorNamesLutMean(ColorNamesLut):
    """lut_mean (amandemen 1 E-08): rata-rata BGR seluruh piksel, dibulatkan ke bilangan bulat
    terdekat, lalu satu kali lookup di tabel yang sama. Hasilnya satu suara, jadi majority = 1 dan
    min_majority tidak membatasi (cakupan 100 %)."""

    def counts(self, pixels: np.ndarray) -> np.ndarray:
        if pixels is None or np.asarray(pixels).size == 0:
            return np.zeros(len(COLOR_NAMES), dtype=np.int64)
        px = np.asarray(pixels, dtype=np.float64).reshape(-1, 3)
        mean = np.clip(np.rint(px.mean(axis=0)), 0, 255).astype(np.uint8)
        counts = np.zeros(len(COLOR_NAMES), dtype=np.int64)
        counts[self.labels[lut_index(mean)[0]]] = 1
        return counts

    def name(self, pixels: np.ndarray) -> ColorResult:
        counts = self.counts(pixels)
        n = 0 if pixels is None else int(np.asarray(pixels).reshape(-1, 3).shape[0])
        return result_from_distribution(counts.astype(float), 0.0, n if counts.any() else 0)


class ColorVoting:
    """Suara warna lintas frame untuk satu kandidat; tiap frame berbobot sama."""

    def __init__(self, min_majority: float) -> None:
        self.min_majority = min_majority
        self.reset()

    def reset(self) -> None:
        self.total = np.zeros(len(COLOR_NAMES), dtype=float)
        self.frames = 0
        self.pixels = 0

    def add(self, result: ColorResult) -> None:
        if result.pixels == 0:
            return
        self.total += np.asarray(result.distribution, dtype=float)
        self.frames += 1
        self.pixels += result.pixels

    def result(self) -> ColorResult:
        return result_from_distribution(self.total, self.min_majority, self.pixels)
