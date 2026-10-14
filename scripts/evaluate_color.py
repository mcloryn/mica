"""Hitung akurasi deteksi warna baju dari predictions.csv yang sudah dilabel.

Langkah:
1. Siapkan predictions.csv dengan kolom prediction, crop_file, dan true_label.
   (Catatan: run_cv.py belum membuat file ini.)
2. Buka predictions.csv, lihat gambar di kolom crop_file, isi kolom true_label
   dengan salah satu nama warna di reference_colors pada config/mica.yaml (huruf kecil).
3. Jalankan:
       python scripts/evaluate_color.py logs/<waktu>/predictions.csv

Hasil: akurasi, precision/recall/F1 per warna, dan confusion matrix (PNG).
Beberapa file predictions.csv boleh digabung: tulis semua path-nya.
"""

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # simpan gambar ke file tanpa membuka jendela
import matplotlib.pyplot as plt  # noqa: E402
from sklearn.metrics import ConfusionMatrixDisplay, accuracy_score, classification_report  # noqa: E402

from mica.vision.color import COLOR_NAMES  # noqa: E402


def main(paths):
    truths, predictions = [], []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                label = (row["true_label"] or "").strip().lower()
                if not label:
                    continue  # baris yang belum dilabel dilewati
                if label not in COLOR_NAMES:
                    sys.exit(f"Label tidak dikenal di {path}: '{label}'. Pilihan: {', '.join(COLOR_NAMES)}")
                truths.append(label)
                predictions.append(row["prediction"] or "tidak ada")
    if not truths:
        sys.exit("Belum ada baris dengan true_label terisi.")

    print(f"Jumlah sampel: {len(truths)}")
    print(f"Akurasi: {accuracy_score(truths, predictions):.2%}\n")
    labels = [c for c in COLOR_NAMES if c in truths or c in predictions]
    print(classification_report(truths, predictions, labels=labels, zero_division=0))

    fig, ax = plt.subplots(figsize=(9, 8))
    ConfusionMatrixDisplay.from_predictions(truths, predictions, labels=labels, ax=ax,
                                            xticks_rotation=45, colorbar=False)
    ax.set_xlabel("Prediksi")
    ax.set_ylabel("Label benar")
    ax.set_title("Confusion matrix warna baju")
    output = Path(paths[0]).with_name("confusion_matrix_color.png")
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    print(f"Confusion matrix disimpan di {output}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
