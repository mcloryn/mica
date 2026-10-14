"""Mencatat setiap orang (per ID ByteTrack): kumpulan suara warna dan kapan terakhir terlihat.

"Suara" (vote) di sini artinya satu hasil baca warna dari satu frame. Warna baju diputuskan
dengan suara terbanyak setelah cukup frame terkumpul, supaya satu frame yang salah baca
tidak langsung menentukan sapaan.
"""

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class PersonRecord:
    last_seen: float                                  # waktu terakhir terlihat (detik)
    votes: Counter = field(default_factory=Counter)   # berapa kali tiap warna terbaca
    color: str | None = None                          # warna yang sudah diputuskan


class SessionManager:
    """min_frames: banyak suara sebelum warna diputuskan.
    forget_after: detik tanpa terlihat sebelum catatan seseorang dihapus.
    """

    def __init__(self, min_frames=10, forget_after=30.0):
        self.min_frames = min_frames
        self.forget_after = forget_after
        self.people = {}  # track_id -> PersonRecord

    def see(self, track_id, time):
        """Tandai bahwa track_id terlihat. Kembalikan True jika ini orang baru."""
        is_new = track_id not in self.people
        if is_new:
            self.people[track_id] = PersonRecord(last_seen=time)
        self.people[track_id].last_seen = time
        return is_new

    def needs_color(self, track_id):
        """True selama warna orang ini belum diputuskan."""
        return self.people[track_id].color is None

    def add_vote(self, track_id, color):
        """Tambah satu suara warna.

        Kembalikan (pemenang, jumlah, total) tepat pada saat warna diputuskan,
        selain itu None. Karena itu sapaan hanya terjadi sekali per orang.
        """
        person = self.people[track_id]
        if person.color is not None:
            return None
        person.votes[color] += 1
        total = sum(person.votes.values())
        if total < self.min_frames:
            return None
        winner, count = person.votes.most_common(1)[0]
        person.color = winner
        return winner, count, total

    def label(self, track_id):
        """Teks yang ditampilkan di layar untuk orang ini."""
        person = self.people[track_id]
        if person.color is not None:
            return person.color
        return f"membaca... {sum(person.votes.values())}/{self.min_frames}"

    def remove_stale(self, time):
        """Hapus catatan orang yang sudah lama tidak terlihat. Kembalikan daftar ID yang dihapus."""
        gone = [t for t, p in self.people.items() if time - p.last_seen > self.forget_after]
        for track_id in gone:
            del self.people[track_id]
        return gone
