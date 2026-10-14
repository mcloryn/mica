"""Teks ke suara (TTS): mengubah teks menjadi suara MP3 dengan edge-tts. Butuh internet.

Dipakai aplikasi web: browser meminta suara lewat alamat /speak, lalu memutarnya sendiri.
"""

from functools import lru_cache

import edge_tts

VOICE = "id-ID-GadisNeural"  # suara perempuan bahasa Indonesia; alternatif: id-ID-ArdiNeural (laki-laki)


@lru_cache(maxsize=64)
def synthesize(text):
    """Kembalikan isi file MP3 (bytes) untuk `text`.

    Hasilnya disimpan di memori (lru_cache): kalimat yang sama, misalnya sapaan untuk baju biru,
    tidak perlu dibuat ulang ke server Microsoft. Yang disimpan paling banyak 64 kalimat terakhir.
    """
    chunks = []
    for part in edge_tts.Communicate(text, VOICE).stream_sync():
        if part["type"] == "audio":  # selain audio, edge-tts juga mengirim data waktu per kata
            chunks.append(part["data"])
    return b"".join(chunks)
