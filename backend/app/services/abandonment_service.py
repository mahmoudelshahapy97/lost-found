# app/services/abandonment_service.py
"""The abandoned-object state machine.

`abandoned` is never a detection class - it is a *status* derived from tracking,
distance and time, exactly as the feature research concluded:

    MOVING  ->  object's centroid drifts more than the tolerance
    STATIC  ->  centroid stable for `static_window_seconds`; the nearest person
                inside `owner_distance_px` is recorded as the owner
    ATTENDED    -> owner still in frame and within `abandon_distance_px`
    UNATTENDED  -> owner gone or too far; the clock starts
    ABANDONED   -> unattended for `abandon_seconds` (PETS2006 uses 30 s)

Pure Python and dependency-free apart from the geometry helpers, so it can be
unit-tested with synthetic detection sequences and no camera.
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, List, Optional, Sequence, Tuple

from app.core.config import config
from app.services.tracking_service import Detection
from app.utils.geometry_utils import Box, Point, box_gap, box_in_polygon, centroid, euclidean

logger = logging.getLogger(__name__)


class ObjectStatus(str, Enum):
    MOVING = "MOVING"
    ATTENDED = "ATTENDED"
    UNATTENDED = "UNATTENDED"
    ABANDONED = "ABANDONED"


@dataclass
class AbandonmentParams:
    """Thresholds, overridable per camera via ``camera.settings``."""

    static_tolerance_px: float = config.static_tolerance_px
    static_window_seconds: float = config.static_window_seconds
    owner_distance_px: float = config.owner_distance_px
    abandon_distance_px: float = config.abandon_distance_px
    abandon_seconds: float = config.abandon_seconds
    track_max_misses: int = config.track_max_misses
    event_cooldown_seconds: float = config.event_cooldown_seconds

    @classmethod
    def from_settings(cls, settings: Optional[Dict] = None) -> "AbandonmentParams":
        params = cls()
        if not settings:
            return params
        for key, value in settings.items():
            if hasattr(params, key) and isinstance(value, (int, float)):
                setattr(params, key, type(getattr(params, key))(value))
        return params


@dataclass
class TrackState:
    track_id: int
    class_id: int
    class_name: str
    box: Box
    confidence: float
    first_seen: float
    last_seen: float
    history: Deque[Tuple[float, Point]] = field(default_factory=deque)
    misses: int = 0
    static_since: Optional[float] = None
    owner_track_id: Optional[int] = None
    unattended_since: Optional[float] = None
    status: ObjectStatus = ObjectStatus.MOVING
    event_emitted: bool = False

    @property
    def unattended_seconds(self) -> float:
        if self.unattended_since is None:
            return 0.0
        return max(0.0, self.last_seen - self.unattended_since)


@dataclass
class AbandonmentEvent:
    """Emitted exactly once per abandoned object track."""

    track_id: int
    class_name: str
    confidence: float
    box: Box
    first_seen_at: float
    static_since: Optional[float]
    abandoned_at: float
    owner_track_id: Optional[int]
    unattended_seconds: float


class AbandonmentTracker:
    """Per-camera state machine. Feed it detections; it hands back events."""

    def __init__(
        self,
        params: Optional[AbandonmentParams] = None,
        roi: Optional[Sequence[Point]] = None,
    ) -> None:
        self.params = params or AbandonmentParams()
        self.roi = roi
        self.tracks: Dict[int, TrackState] = {}
        self._cooldowns: Dict[int, float] = {}

    # ----------------------------------------------------------------- public
    def update(self, detections: Sequence[Detection], timestamp: float) -> List[AbandonmentEvent]:
        """Advance the machine by one processed frame."""
        persons = [d for d in detections if d.is_person]
        objects = [
            d
            for d in detections
            if not d.is_person
            and d.class_id in config.object_class_ids
            and self._in_roi(d.box)
        ]

        seen_ids = set()
        events: List[AbandonmentEvent] = []

        for detection in objects:
            seen_ids.add(detection.track_id)
            state = self._upsert(detection, timestamp)
            event = self._evaluate(state, persons, timestamp)
            if event is not None:
                events.append(event)

        self._expire(seen_ids)
        return events

    def snapshot(self) -> List[Dict]:
        """Current per-object status, for the camera status endpoint."""
        return [
            {
                "track_id": s.track_id,
                "class_name": s.class_name,
                "status": s.status.value,
                "box": list(s.box),
                "owner_track_id": s.owner_track_id,
                "static_seconds": round(s.last_seen - s.static_since, 1) if s.static_since else 0.0,
                "unattended_seconds": round(s.unattended_seconds, 1),
            }
            for s in self.tracks.values()
        ]

    def reset(self) -> None:
        """Forget everything. Called when the stream reconnects and ids restart."""
        self.tracks.clear()
        self._cooldowns.clear()

    # ---------------------------------------------------------------- internal
    def _in_roi(self, box: Box) -> bool:
        return box_in_polygon(box, self.roi) if self.roi else True

    def _upsert(self, detection: Detection, timestamp: float) -> TrackState:
        state = self.tracks.get(detection.track_id)
        if state is None:
            state = TrackState(
                track_id=detection.track_id,
                class_id=detection.class_id,
                class_name=detection.class_name,
                box=detection.box,
                confidence=detection.confidence,
                first_seen=timestamp,
                last_seen=timestamp,
            )
            self.tracks[detection.track_id] = state
        else:
            state.box = detection.box
            state.confidence = detection.confidence
            state.last_seen = timestamp
            state.misses = 0

        state.history.append((timestamp, centroid(detection.box)))
        self._trim_history(state, timestamp)
        return state

    def _trim_history(self, state: TrackState, timestamp: float) -> None:
        """Keep only the sliding window used by the static test."""
        window = self.params.static_window_seconds
        while len(state.history) > 1 and timestamp - state.history[0][0] > window:
            state.history.popleft()

    def _is_static(self, state: TrackState, timestamp: float) -> bool:
        """Stationary when every centroid in the window sits within tolerance of the latest."""
        if len(state.history) < 2:
            return False
        if timestamp - state.history[0][0] < self.params.static_window_seconds:
            return False

        latest = state.history[-1][1]
        return all(
            euclidean(point, latest) <= self.params.static_tolerance_px
            for _, point in state.history
        )

    def _nearest_person(
        self, box: Box, persons: Sequence[Detection], max_distance: float
    ) -> Optional[Detection]:
        nearest, best = None, max_distance
        for person in persons:
            gap = box_gap(box, person.box)
            if gap <= best:
                nearest, best = person, gap
        return nearest

    def _evaluate(
        self, state: TrackState, persons: Sequence[Detection], timestamp: float
    ) -> Optional[AbandonmentEvent]:
        if not self._is_static(state, timestamp):
            # The object moved: it is being carried, so every timer resets.
            state.static_since = None
            state.owner_track_id = None
            state.unattended_since = None
            state.status = ObjectStatus.MOVING
            state.event_emitted = False
            return None

        if state.static_since is None:
            # First frame of stillness: whoever is closest right now owns it.
            state.static_since = state.history[0][0]
            owner = self._nearest_person(state.box, persons, self.params.owner_distance_px)
            state.owner_track_id = owner.track_id if owner else None

        if self._is_attended(state, persons):
            state.status = ObjectStatus.ATTENDED
            state.unattended_since = None
            state.event_emitted = False
            return None

        if state.unattended_since is None:
            state.unattended_since = timestamp
        state.status = ObjectStatus.UNATTENDED

        if state.unattended_seconds < self.params.abandon_seconds:
            return None

        state.status = ObjectStatus.ABANDONED
        if state.event_emitted or self._in_cooldown(state.track_id, timestamp):
            return None

        state.event_emitted = True
        self._cooldowns[state.track_id] = timestamp
        logger.info(
            "Abandoned %s (track %s) after %.1fs unattended",
            state.class_name,
            state.track_id,
            state.unattended_seconds,
        )
        return AbandonmentEvent(
            track_id=state.track_id,
            class_name=state.class_name,
            confidence=state.confidence,
            box=state.box,
            first_seen_at=state.first_seen,
            static_since=state.static_since,
            abandoned_at=timestamp,
            owner_track_id=state.owner_track_id,
            unattended_seconds=state.unattended_seconds,
        )

    def _is_attended(self, state: TrackState, persons: Sequence[Detection]) -> bool:
        """Someone is minding the object: the known owner, or a re-identified stand-in."""
        if state.owner_track_id is not None:
            owner = next((p for p in persons if p.track_id == state.owner_track_id), None)
            if owner is not None:
                return box_gap(state.box, owner.box) <= self.params.abandon_distance_px

        # Owner track lost (occlusion, re-id) - accept any person standing close
        # enough to plausibly be them, and adopt that track as the new owner.
        stand_in = self._nearest_person(state.box, persons, self.params.owner_distance_px)
        if stand_in is not None:
            state.owner_track_id = stand_in.track_id
            return True

        return False

    def _in_cooldown(self, track_id: int, timestamp: float) -> bool:
        last = self._cooldowns.get(track_id)
        return last is not None and (timestamp - last) < self.params.event_cooldown_seconds

    def _expire(self, seen_ids: set) -> None:
        """Drop tracks the detector has stopped reporting."""
        for track_id in list(self.tracks):
            if track_id in seen_ids:
                continue
            state = self.tracks[track_id]
            state.misses += 1
            if state.misses > self.params.track_max_misses:
                del self.tracks[track_id]
