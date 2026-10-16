"""M-07 PresenceTracker: kebijakan satu pengunjung (ADR-15; SDD 7.3 kehadiran dan sapaan).

IDLE -> CANDIDATE -> ENGAGED:
- memenuhi syarat: tinggi box / tinggi frame >= min_box_height_ratio; target = box tertinggi;
- CANDIDATE menjadi ENGAGED (PersonArrived sekali) bila track yang sama memenuhi syarat >= dwell_s;
  hilang sebelum itu -> IDLE tanpa event (orang lewat);
- ENGAGED: ID berganti (ID switch) -> ID diperbarui diam-diam, tanpa sapaan kedua;
- tidak ada yang memenuhi syarat >= leave_s -> PersonLeft, IDLE.

Warna pakaian: selama CANDIDATE, suara warna target (color_of) dikumpulkan di ColorVoting dan
direset bila kandidat berganti; hasilnya mengisi PersonArrived.color dan color_confidence.

Waktu hanya dari parameter now (monotonic) supaya bisa diuji. dwell_s, leave_s, dan
min_box_height_ratio TBD (E-07), jadi wajib diberikan pemanggil; tidak ada nilai bawaan.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum

from mica.vision.color import ColorResult, ColorVoting
from mica.vision.types import PersonArrived, PersonLeft, PersonTrack, VisionEvent

log = logging.getLogger(__name__)


class PresenceState(StrEnum):
    IDLE = "IDLE"
    CANDIDATE = "CANDIDATE"
    ENGAGED = "ENGAGED"


def select_target(
    tracks: list[PersonTrack], frame_h: int, min_box_height_ratio: float
) -> PersonTrack | None:
    eligible = [t for t in tracks if t.height_ratio(frame_h) >= min_box_height_ratio]
    return max(eligible, key=lambda t: t.height, default=None)


class PresenceTracker:
    def __init__(
        self,
        dwell_s: float,
        leave_s: float,
        min_box_height_ratio: float,
        voting: ColorVoting | None = None,
    ) -> None:
        self.voting = voting
        self.dwell_s = dwell_s
        self.leave_s = leave_s
        self.min_box_height_ratio = min_box_height_ratio
        self.state = PresenceState.IDLE
        self.track_id: int | None = None
        self.since: float | None = None  # awal CANDIDATE
        self.arrived_at: float | None = None
        self.last_seen: float | None = None
        self.id_switches = 0

    def _reset(self) -> None:
        self.state = PresenceState.IDLE
        self.track_id = None
        self.since = self.arrived_at = self.last_seen = None
        if self.voting is not None:
            self.voting.reset()

    def update(
        self,
        tracks: list[PersonTrack],
        frame_h: int,
        now: float,
        color_of: Callable[[PersonTrack], ColorResult | None] | None = None,
    ) -> list[VisionEvent]:
        """color_of(target) menamai warna area pakaian frame ini (dipanggil hanya saat CANDIDATE)."""
        target = select_target(tracks, frame_h, self.min_box_height_ratio)
        events: list[VisionEvent] = []

        if self.state == PresenceState.ENGAGED:
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
