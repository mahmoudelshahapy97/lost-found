"""State-machine tests driven by synthetic detections - no camera, no model, no DB."""

from typing import List, Sequence

import pytest

from app.services.abandonment_service import (
    AbandonmentParams,
    AbandonmentTracker,
    ObjectStatus,
)
from app.services.tracking_service import Detection

PERSON_CLASS = 0
BACKPACK_CLASS = 24

BAG_BOX = (100.0, 100.0, 150.0, 150.0)
NEAR_PERSON_BOX = (160.0, 100.0, 200.0, 180.0)   # 10 px gap from the bag
FAR_PERSON_BOX = (600.0, 100.0, 640.0, 180.0)    # 450 px gap from the bag


def params(**overrides) -> AbandonmentParams:
    base = dict(
        static_tolerance_px=10.0,
        static_window_seconds=1.0,
        owner_distance_px=100.0,
        abandon_distance_px=150.0,
        abandon_seconds=5.0,
        track_max_misses=5,
        event_cooldown_seconds=300.0,
    )
    base.update(overrides)
    return AbandonmentParams(**base)


def bag(box=BAG_BOX, track_id: int = 7) -> Detection:
    return Detection(
        track_id=track_id,
        class_id=BACKPACK_CLASS,
        class_name="backpack",
        confidence=0.9,
        box=box,
    )


def person(box=NEAR_PERSON_BOX, track_id: int = 1) -> Detection:
    return Detection(
        track_id=track_id, class_id=PERSON_CLASS, class_name="person", confidence=0.9, box=box
    )


def run(
    tracker: AbandonmentTracker,
    frames: Sequence[Sequence[Detection]],
    dt: float = 0.5,
    start: float = 0.0,
) -> List:
    """Feed a sequence of frames dt seconds apart and collect every event emitted."""
    events = []
    for index, detections in enumerate(frames):
        events.extend(tracker.update(detections, start + index * dt))
    return events


def frames_for(seconds: float, dt: float, detections_at) -> List[List[Detection]]:
    """Build ``seconds / dt`` frames, calling ``detections_at(t)`` for each timestamp."""
    count = int(seconds / dt) + 1
    return [detections_at(i * dt) for i in range(count)]


# ---------------------------------------------------------------- core behaviour
def test_owner_leaves_object_becomes_abandoned():
    """Bag goes static with an owner beside it; owner walks off; event fires."""
    tracker = AbandonmentTracker(params=params())

    def at(t: float) -> List[Detection]:
        return [bag()] if t >= 5.0 else [bag(), person()]

    events = run(tracker, frames_for(12.0, 0.5, at))

    assert len(events) == 1
    event = events[0]
    assert event.class_name == "backpack"
    assert event.track_id == 7
    assert event.owner_track_id == 1
    assert event.unattended_seconds >= 5.0
    assert tracker.tracks[7].status is ObjectStatus.ABANDONED


def test_owner_returns_before_timeout_no_event():
    """The clock resets the moment the owner comes back within range."""
    tracker = AbandonmentTracker(params=params())

    def at(t: float) -> List[Detection]:
        if 5.0 <= t < 8.0:
            return [bag()]  # owner briefly out of frame
        return [bag(), person()]

    events = run(tracker, frames_for(20.0, 0.5, at))

    assert events == []
    assert tracker.tracks[7].status is ObjectStatus.ATTENDED


def test_owner_present_but_too_far_starts_the_clock():
    """Still in frame is not enough - the owner has to stay close."""
    tracker = AbandonmentTracker(params=params())

    def at(t: float) -> List[Detection]:
        return [bag(), person(FAR_PERSON_BOX if t >= 5.0 else NEAR_PERSON_BOX)]

    events = run(tracker, frames_for(12.0, 0.5, at))

    assert len(events) == 1
    assert events[0].owner_track_id == 1


def test_moving_object_never_abandoned():
    """An object being carried keeps drifting, so it never goes static."""
    tracker = AbandonmentTracker(params=params())

    def at(t: float) -> List[Detection]:
        shift = t * 60.0  # well beyond static_tolerance_px per frame
        return [bag((100 + shift, 100.0, 150 + shift, 150.0))]

    events = run(tracker, frames_for(20.0, 0.5, at))

    assert events == []
    assert tracker.tracks[7].status is ObjectStatus.MOVING


def test_unowned_object_starts_timer_immediately():
    """A bag that is already alone when it goes static needs no owner handover."""
    tracker = AbandonmentTracker(params=params())

    events = run(tracker, frames_for(12.0, 0.5, lambda t: [bag()]))

    assert len(events) == 1
    assert events[0].owner_track_id is None


def test_event_emitted_exactly_once():
    """Long after the alert, the same track must not keep re-firing."""
    tracker = AbandonmentTracker(params=params())

    def at(t: float) -> List[Detection]:
        return [bag()] if t >= 5.0 else [bag(), person()]

    events = run(tracker, frames_for(120.0, 0.5, at))

    assert len(events) == 1


def test_person_alone_is_ignored():
    """People are tracked for ownership only; they are never abandonment candidates."""
    tracker = AbandonmentTracker(params=params())

    events = run(tracker, frames_for(30.0, 0.5, lambda t: [person()]))

    assert events == []
    assert tracker.tracks == {}


# --------------------------------------------------------------------- ROI gating
def test_object_outside_roi_is_ignored():
    roi = [(0.0, 0.0), (80.0, 0.0), (80.0, 80.0), (0.0, 80.0)]  # bag centre is (125,125)
    tracker = AbandonmentTracker(params=params(), roi=roi)

    events = run(tracker, frames_for(20.0, 0.5, lambda t: [bag()]))

    assert events == []


def test_object_inside_roi_still_fires():
    roi = [(0.0, 0.0), (400.0, 0.0), (400.0, 400.0), (0.0, 400.0)]
    tracker = AbandonmentTracker(params=params(), roi=roi)

    events = run(tracker, frames_for(12.0, 0.5, lambda t: [bag()]))

    assert len(events) == 1


# ------------------------------------------------------------------- housekeeping
def test_track_expires_after_max_misses():
    tracker = AbandonmentTracker(params=params(track_max_misses=3))

    run(tracker, [[bag()]] * 4)
    assert 7 in tracker.tracks

    run(tracker, [[]] * 5, start=100.0)
    assert 7 not in tracker.tracks


def test_reset_clears_state():
    tracker = AbandonmentTracker(params=params())
    run(tracker, frames_for(12.0, 0.5, lambda t: [bag()]))

    tracker.reset()

    assert tracker.tracks == {}
    assert tracker.snapshot() == []


def test_snapshot_reports_live_status():
    tracker = AbandonmentTracker(params=params())
    run(tracker, frames_for(3.0, 0.5, lambda t: [bag(), person()]))

    snapshot = tracker.snapshot()

    assert len(snapshot) == 1
    assert snapshot[0]["track_id"] == 7
    assert snapshot[0]["status"] == ObjectStatus.ATTENDED.value
    assert snapshot[0]["owner_track_id"] == 1


@pytest.mark.parametrize("abandon_seconds,expected", [(2.0, 1), (60.0, 0)])
def test_threshold_is_configurable(abandon_seconds: float, expected: int):
    """Per-camera overrides really do change when the alert fires."""
    tracker = AbandonmentTracker(params=params(abandon_seconds=abandon_seconds))

    def at(t: float) -> List[Detection]:
        return [bag()] if t >= 2.0 else [bag(), person()]

    assert len(run(tracker, frames_for(15.0, 0.5, at))) == expected


def test_params_from_settings_overrides_only_known_keys():
    merged = AbandonmentParams.from_settings({"abandon_seconds": 45, "nonsense": "x"})

    assert merged.abandon_seconds == 45.0
    assert not hasattr(merged, "nonsense")
