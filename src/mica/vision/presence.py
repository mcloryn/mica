"""M-07 PresenceTracker: kebijakan satu pengunjung (ADR-15; SDD 7.3 kehadiran dan sapaan).

IDLE -> CANDIDATE -> ENGAGED:
- memenuhi syarat: nilai sinyal kehadiran track >= min_signal; target = nilai sinyal terbesar;
- CANDIDATE menjadi ENGAGED (PersonArrived sekali) bila track yang sama memenuhi syarat >= dwell_s;
  hilang sebelum itu -> IDLE tanpa event (orang lewat);
- ENGAGED: ID berganti (ID switch) -> ID diperbarui diam-diam, tanpa sapaan kedua;
- tidak ada yang memenuhi syarat >= leave_s -> PersonLeft, IDLE.

Sinyal kehadiran (vision.presence_signal, dipilih di E-07):
- box_height: tinggi box / tinggi frame;
- shoulder_width: |x bahu kiri - x bahu kanan| (COCO 5, 6) / lebar frame, hanya bila kedua
  confidence >= min_kp_conf. Bila bahu tidak yakin pada frame itu (nilai None):
  - track yang memenuhi syarat pada update sebelumnya dan box-nya masih ada tetap dianggap
    memenuhi syarat dengan nilai terakhirnya (carry-over), supaya keypoint yang goyah tidak
    memicu PersonLeft;
  - carry-over berlaku paling lama leave_s sejak bahu track itu terakhir yakin. leave_s adalah
    definisi "pergi": tanpa bukti kehadiran selama leave_s, orang dianggap pergi. Tanpa batas
    ini, box yang tertinggal (misalnya kursi yang terdeteksi sebagai orang) bisa menahan sesi
    selamanya. Akibatnya PersonLeft paling lambat sekitar 2 x leave_s setelah bahu terakhir
    yakin (leave_s carry-over + leave_s tanpa target);
  - track lain (kandidat baru) tidak memenuhi syarat.

Langkah 51 (temuan uji black-box 21 Okt 2026, dibuat setelah data): sinyal kehadiran hanya
syarat untuk MEMULAI sesi (CANDIDATE -> ENGAGED, sapaan). Selama ENGAGED, bila tidak ada track
yang memenuhi syarat, pengunjung tetap dianggap ada selama box track target masih terdeteksi
(walau bahu tidak terbaca atau lebarnya di bawah ambang, misalnya menunduk ke keyboard), atau,
bila ID target hilang, box orang satu-satunya di frame dianggap target yang sama (belum ada
pencocokan IoU di kode). PersonLeft hanya bila tidak ada keduanya selama leave_s. freeze(d)
menggeser timer pergi saat deteksi dijeda (vision.pause_during_tts).

Warna pakaian: selama CANDIDATE, suara warna target (color_of) dikumpulkan di ColorVoting dan
direset bila kandidat berganti; hasilnya mengisi PersonArrived.color dan color_confidence.

Waktu hanya dari parameter now (monotonic) supaya bisa diuji. dwell_s, leave_s, dan ambang
sinyal TBD (E-07), jadi wajib diberikan pemanggil; tidak ada nilai bawaan.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from mica.vision.color import ColorResult, ColorVoting
from mica.vision.region import shoulder_width_ratio
from mica.vision.types import PersonArrived, PersonLeft, PersonTrack, VisionEvent

log = logging.getLogger(__name__)

FrameShape = tuple[int, ...]  # (tinggi, lebar[, kanal])


class PresenceState(StrEnum):
    IDLE = "IDLE"
    CANDIDATE = "CANDIDATE"
    ENGAGED = "ENGAGED"


class PresenceSignal(Protocol):
    name: str

    def value(self, track: PersonTrack, frame_shape: FrameShape) -> float | None:
        """Nilai sinyal track; None bila tidak bisa diukur pada frame ini."""
        ...


class BoxHeightSignal:
    name = "box_height"

    def value(self, track: PersonTrack, frame_shape: FrameShape) -> float | None:
        return track.height_ratio(frame_shape[0])


class ShoulderWidthSignal:
    name = "shoulder_width"

    def __init__(self, min_kp_conf: float) -> None:
        self.min_kp_conf = min_kp_conf

    def value(self, track: PersonTrack, frame_shape: FrameShape) -> float | None:
        return shoulder_width_ratio(track, frame_shape[1], self.min_kp_conf)


class PresenceTracker:
    def __init__(
        self,
        dwell_s: float,
        leave_s: float,
        min_signal: float,
        signal: PresenceSignal,
        voting: ColorVoting | None = None,
    ) -> None:
        self.voting = voting
        self.dwell_s = dwell_s
        self.leave_s = leave_s
        self.min_signal = min_signal
        self.signal = signal
        self.state = PresenceState.IDLE
        self.track_id: int | None = None
        self.since: float | None = None  # awal CANDIDATE
        self.arrived_at: float | None = None
        self.last_seen: float | None = None
        self.id_switches = 0
        self.eligible: dict[int, float] = {}  # track yang memenuhi syarat di update terakhir
        self.last_measured: dict[int, float] = {}  # track_id -> waktu sinyal terakhir terukur

    def _reset(self) -> None:
        self.state = PresenceState.IDLE
        self.track_id = None
        self.since = self.arrived_at = self.last_seen = None
        if self.voting is not None:
            self.voting.reset()

    def _carry_allowed(self, track_id: int, now: float) -> bool:
        if track_id not in self.eligible:
            return False
        measured = self.last_measured.get(track_id)
        return measured is not None and now - measured < self.leave_s

    def eligible_tracks(
        self, tracks: list[PersonTrack], frame_shape: FrameShape, now: float
    ) -> dict[int, tuple[PersonTrack, float]]:
        """track_id -> (track, nilai sinyal) yang memenuhi syarat frame ini; tidak mengubah state."""
        out: dict[int, tuple[PersonTrack, float]] = {}
        for t in tracks:
            value = self.signal.value(t, frame_shape)
            if value is None:
                if self._carry_allowed(t.track_id, now):  # sinyal goyah: carry-over
                    out[t.track_id] = (t, self.eligible[t.track_id])
            elif value >= self.min_signal:
                out[t.track_id] = (t, value)
        return out

    def kept_track(self, tracks: list[PersonTrack]) -> PersonTrack | None:
        """Selama ENGAGED tanpa track yang memenuhi syarat: box track target, atau satu-satunya
        orang di frame bila ID target hilang (Langkah 51)."""
        if self.state != PresenceState.ENGAGED:
            return None
        same = [t for t in tracks if t.track_id == self.track_id]
        if same:
            return same[0]
        return tracks[0] if len(tracks) == 1 else None

    def freeze(self, seconds: float) -> None:
        """Bekukan timer pergi dan carry-over selama `seconds` (deteksi dijeda)."""
        if seconds <= 0:
            return
        if self.last_seen is not None:
            self.last_seen += seconds
        self.last_measured = {tid: at + seconds for tid, at in self.last_measured.items()}

    def target_for(
        self, tracks: list[PersonTrack], frame_shape: FrameShape, now: float
    ) -> PersonTrack | None:
        eligible = self.eligible_tracks(tracks, frame_shape, now)
        if not eligible:
            return self.kept_track(tracks)
        return max(eligible.values(), key=lambda tv: tv[1])[0]

    def update(
        self,
        tracks: list[PersonTrack],
        frame_shape: FrameShape,
        now: float,
        color_of: Callable[[PersonTrack], ColorResult | None] | None = None,
    ) -> list[VisionEvent]:
        """color_of(target) menamai warna area pakaian frame ini (dipanggil hanya saat CANDIDATE)."""
        eligible = self.eligible_tracks(tracks, frame_shape, now)
        self.eligible = {tid: value for tid, (_t, value) in eligible.items()}
        present = {t.track_id for t in tracks}
        self.last_measured = {tid: at for tid, at in self.last_measured.items() if tid in present}
        for t in tracks:
            if self.signal.value(t, frame_shape) is not None:
                self.last_measured[t.track_id] = now
        target = max(eligible.values(), key=lambda tv: tv[1])[0] if eligible else None
        events: list[VisionEvent] = []

        if self.state == PresenceState.ENGAGED:
            if target is None:
                target = self.kept_track(tracks)
            if target is not None:
                if target.track_id != self.track_id:
                    self.id_switches += 1
                    log.debug(
                        "ID switch %s -> %s; tidak menyapa lagi", self.track_id, target.track_id
                    )
                    self.track_id = target.track_id
                self.last_seen = now
            elif self.last_seen is not None and now - self.last_seen >= self.leave_s:
                assert self.track_id is not None and self.arrived_at is not None
                events.append(PersonLeft(self.track_id, now, now - self.arrived_at))
                self._reset()
            return events

        if target is None:
            self._reset()  # CANDIDATE hilang sebelum dwell_s: orang lewat, tanpa event
            return events
        if self.state == PresenceState.IDLE or target.track_id != self.track_id:
            self.state = PresenceState.CANDIDATE
            self.track_id = target.track_id
            self.since = now
            if self.voting is not None:
                self.voting.reset()  # suara milik kandidat lama dibuang
        assert self.since is not None
        if self.voting is not None and color_of is not None:
            result = color_of(target)
            if result is not None:
                self.voting.add(result)
        if now - self.since >= self.dwell_s:
            self.state = PresenceState.ENGAGED
            self.arrived_at = self.last_seen = now
            color = confidence = None
            if self.voting is not None and self.voting.frames:
                voted = self.voting.result()
                color, confidence = voted.label, voted.majority
            events.append(PersonArrived(target.track_id, target.box_xyxy, now, color, confidence))
        return events
