"""Chatbot MICA. Untuk sekarang masih jawaban sementara.

Nanti diganti dengan RAG: cari potongan dokumen Mikroskil yang relevan,
lalu minta LLM menjawab hanya berdasarkan potongan itu.
"""


def answer(question, history):
    """Kembalikan jawaban untuk `question`.

    history: daftar pesan sebelumnya dalam sesi ini, misalnya
             [{"role": "mica", "text": "Halo..."}, {"role": "visitor", "text": "..."}]
    """
    return ("Maaf, MICA belum bisa menjawab pertanyaan. "
            "Bagian chatbot sedang dibangun dan akan memakai dokumen resmi Mikroskil.")
