"""Integration tests against a live Postgres.

Skipped automatically when no database is reachable, so ``pytest`` stays green
without one. To run them, point the usual DB_* variables at a server that has
``database/init/002_schema.sql`` applied - for example the compose stack::

    DB_HOST=localhost DB_PORT=5433 pytest tests/test_integration.py

No model weights are needed: found items and events are written directly, so
the search filters and the match rules can be exercised on their own.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import List

import numpy as np
import pytest

from app.core.config import config
from app.core.database import (
    close_db_pool,
    db_manager,
    ensure_schema_upgrades,
    init_db_pool,
    wait_for_schema,
)
from app.services.abandonment_service import AbandonmentEvent
from app.services.analytics_service import analytics_service
from app.services.camera_service import camera_service
from app.services.event_service import event_service
from app.services.matching_service import matching_service
from app.services.object_store import object_store

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
async def database():
    """Connect once for the module, or skip the whole file."""
    try:
        await init_db_pool()
    except Exception as e:
        pytest.skip(f"No database reachable ({config.db_host}:{config.db_port}): {e}")

    if not await wait_for_schema(timeout=5):
        await close_db_pool()
        pytest.skip("Database reachable but database/init/002_schema.sql has not been applied.")

    # The same idempotent upgrades the api runs at startup.
    await ensure_schema_upgrades()
    yield
    await close_db_pool()


# Rows created directly by the helpers below, torn down after each test so the
# gallery does not accumulate across runs.
_CREATED: List[tuple] = []


@pytest.fixture(autouse=True)
async def cleanup_helper_rows(database):
    yield
    for table, column, identifier in _CREATED:
        await db_manager.execute_query(
            f"DELETE FROM {table} WHERE {column} = $1", (identifier,)
        )
    _CREATED.clear()


@pytest.fixture
async def camera(database):
    """A throwaway camera; deleting it cascades to its events and found items."""
    created = await camera_service.create_camera(
        name=f"test-cam-{uuid.uuid4().hex[:8]}",
        rtsp_url="rtsp://example.invalid:8554/test",
        location="test-suite",
        enabled=False,
    )
    yield created
    await camera_service.delete_camera(created["camera_id"])
    for prefix in ("frames", "crops", "clips"):
        await object_store.remove_prefix(f"{prefix}/{created['camera_id']}/")


# ------------------------------------------------------------------- cameras
async def test_camera_crud_roundtrip(database):
    name = f"crud-cam-{uuid.uuid4().hex[:8]}"
    created = await camera_service.create_camera(
        name=name,
        rtsp_url="rtsp://example.invalid/a",
        enabled=False,
        roi=[[0, 0], [100, 0], [100, 100]],
        settings={"abandon_seconds": 45},
    )
    try:
        assert created["name"] == name

        fetched = await camera_service.get_camera(created["camera_id"])
        assert fetched["rtsp_url"] == "rtsp://example.invalid/a"
        assert camera_service.parse_settings(fetched)["abandon_seconds"] == 45
        assert len(camera_service.parse_roi(fetched)) == 3

        updated = await camera_service.update_camera(
            created["camera_id"], rtsp_url="rtsp://example.invalid/b", location="gate 2"
        )
        assert updated["rtsp_url"] == "rtsp://example.invalid/b"
        assert updated["location"] == "gate 2"
        assert updated["name"] == name  # untouched columns survive

        assert any(c["camera_id"] == created["camera_id"] for c in await camera_service.list_cameras())
    finally:
        assert await camera_service.delete_camera(created["camera_id"])
        assert await camera_service.get_camera(created["camera_id"]) is None


# -------------------------------------------------------------------- events
async def test_record_event_creates_event_and_found_item(camera):
    frame = np.full((480, 640, 3), 200, dtype=np.uint8)
    event = AbandonmentEvent(
        track_id=42,
        class_name="bag",
        confidence=0.91,
        box=(100.0, 100.0, 200.0, 220.0),
        first_seen_at=1_700_000_000.0,
        static_since=1_700_000_005.0,
        abandoned_at=1_700_000_040.0,
        owner_track_id=3,
        unattended_seconds=35.0,
    )

    stored = await event_service.record_event(camera["camera_id"], event, frame)

    assert stored is not None
    assert stored["class_name"] == "bag"
    assert stored["owner_track_id"] == 3

    # The annotated alert frame is retrievable as JPEG bytes.
    jpeg = await event_service.get_event_frame(stored["event_id"])
    assert jpeg and jpeg[:2] == b"\xff\xd8"  # JPEG magic

    # The event auto-populated the found gallery.
    gallery = await matching_service.list_found_items(camera_id=camera["camera_id"])
    assert gallery["total"] == 1
    assert gallery["found_items"][0]["class_name"] == "bag"

    listed = await event_service.list_events(camera_id=camera["camera_id"])
    assert listed["total"] == 1
    assert listed["events"][0]["bbox"]["x1"] == 100.0


def _event(track_id: int = 7) -> AbandonmentEvent:
    return AbandonmentEvent(
        track_id=track_id,
        class_name="bag",
        confidence=0.8,
        box=(100.0, 100.0, 200.0, 220.0),
        first_seen_at=1_700_000_000.0,
        static_since=1_700_000_005.0,
        abandoned_at=1_700_000_040.0,
        owner_track_id=1,
        unattended_seconds=35.0,
    )


async def _media_columns(event_id):
    return await db_manager.execute_query(
        """
        SELECT e.frame_key, e.frame_jpeg IS NOT NULL AS frame_in_db,
               f.found_id, f.crop_key, f.crop_jpeg IS NOT NULL AS crop_in_db
        FROM abandoned_event e JOIN found_item f ON f.event_id = e.event_id
        WHERE e.event_id = $1
        """,
        (event_id,),
        fetch_one=True,
    )


async def test_event_media_is_stored_in_minio_with_keys_in_postgres(camera):
    if not object_store.enabled or not await object_store.healthy():
        pytest.skip("MinIO not configured or not reachable")
    frame = np.full((480, 640, 3), 120, dtype=np.uint8)

    stored = await event_service.record_event(camera["camera_id"], _event(), frame)
    row = await _media_columns(stored["event_id"])

    assert row["frame_key"] == f"frames/{camera['camera_id']}/{stored['event_id']}.jpg"
    assert row["crop_key"] == f"crops/{camera['camera_id']}/{row['found_id']}.jpg"
    assert not row["frame_in_db"] and not row["crop_in_db"]  # MinIO only
    assert (await object_store.get_bytes(row["frame_key"]))[:2] == b"\xff\xd8"
    assert (await event_service.get_event_frame(stored["event_id"]))[:2] == b"\xff\xd8"
    assert (await matching_service.get_found_crop(row["found_id"]))[:2] == b"\xff\xd8"


async def test_event_media_falls_back_to_postgres_when_minio_is_down(camera, monkeypatch):
    monkeypatch.setattr(config, "minio_endpoint", "")  # store "unreachable"
    frame = np.full((480, 640, 3), 120, dtype=np.uint8)

    stored = await event_service.record_event(camera["camera_id"], _event(8), frame)
    row = await _media_columns(stored["event_id"])

    assert row["frame_key"] is None and row["crop_key"] is None
    assert row["frame_in_db"] and row["crop_in_db"]
    assert (await event_service.get_event_frame(stored["event_id"]))[:2] == b"\xff\xd8"


async def test_lost_photo_round_trips_through_minio(database):
    if not object_store.enabled or not await object_store.healthy():
        pytest.skip("MinIO not configured or not reachable")
    photo = np.full((120, 90, 3), (160, 40, 120), dtype=np.uint8)

    report = await matching_service.create_lost_item(image=photo, description="purple bag")
    _CREATED.append(("lost_item", "lost_id", report["lost_id"]))
    try:
        fetched = await matching_service.get_lost_item(report["lost_id"], include_photo=True)
        key = (await db_manager.execute_query(
            "SELECT photo_key FROM lost_item WHERE lost_id = $1", (report["lost_id"],), fetch_one=True
        ))["photo_key"]
        assert key == f"lost/{report['lost_id']}.jpg"
        assert fetched["photo_base64"]
    finally:
        await object_store.remove([f"lost/{report['lost_id']}.jpg"])


async def test_record_event_is_idempotent(camera):
    """A replayed event for the same track must not duplicate the row."""
    event = AbandonmentEvent(
        track_id=99,
        class_name="umbrella",
        confidence=0.8,
        box=(10.0, 10.0, 60.0, 60.0),
        first_seen_at=1_700_000_000.0,
        static_since=1_700_000_005.0,
        abandoned_at=1_700_000_040.0,
        owner_track_id=None,
        unattended_seconds=31.0,
    )
    frame = np.zeros((120, 120, 3), dtype=np.uint8)

    first = await event_service.record_event(camera["camera_id"], event, frame)
    second = await event_service.record_event(camera["camera_id"], event, frame)

    assert first is not None
    assert second is None

    listed = await event_service.list_events(camera_id=camera["camera_id"])
    assert listed["total"] == 1


async def test_event_status_transitions(camera):
    event = AbandonmentEvent(
        track_id=7,
        class_name="wallet",
        confidence=0.7,
        box=(0.0, 0.0, 50.0, 50.0),
        first_seen_at=1_700_000_000.0,
        static_since=1_700_000_002.0,
        abandoned_at=1_700_000_035.0,
        owner_track_id=None,
        unattended_seconds=33.0,
    )
    stored = await event_service.record_event(camera["camera_id"], event, None)

    updated = await event_service.update_status(stored["event_id"], "ACKNOWLEDGED")
    assert updated["status"] == "ACKNOWLEDGED"

    stats = await event_service.stats(camera["camera_id"])
    assert stats["total"] == 1
    assert stats["open"] == 0


# -------------------------------------------------------------------- search
async def test_found_items_filter_by_camera_time_type_and_colour(camera):
    now = datetime.now(timezone.utc)
    cam = camera["camera_id"]
    early = await _insert_found_item(cam, "bag", "black", found_at=now - timedelta(hours=5))
    late = await _insert_found_item(cam, "bag", "black", found_at=now - timedelta(hours=1))
    red = await _insert_found_item(cam, "umbrella", "red", found_at=now - timedelta(hours=1))

    def ids(result):
        return [row["found_id"] for row in result["found_items"]]

    everything = await matching_service.list_found_items(camera_id=cam, per_page=100)
    assert ids(everything) == [late, red, early] or ids(everything) == [red, late, early]

    window = await matching_service.list_found_items(
        camera_id=cam, start=now - timedelta(hours=2), end=now, per_page=100
    )
    assert set(ids(window)) == {late, red}

    bags = await matching_service.list_found_items(camera_id=cam, class_name="bag")
    assert set(ids(bags)) == {early, late}

    reds = await matching_service.list_found_items(camera_id=cam, color="red")
    assert ids(reds) == [red] and reds["total"] == 1


# ------------------------------------------------------------------ matching
async def test_rules_rank_same_type_and_colour_first(camera):
    lost_at = datetime.now(timezone.utc) - timedelta(hours=6)
    cam = camera["camera_id"]
    right = await _insert_found_item(
        cam, "bag", "black", found_at=lost_at + timedelta(hours=1), box=(10, 10, 60, 60)
    )
    wrong_colour = await _insert_found_item(
        cam, "bag", "red", found_at=lost_at + timedelta(hours=1), box=(300, 10, 350, 60)
    )
    lost_id = await _insert_lost_item("bag", "black", lost_after=lost_at)

    # A shared database holds live detections too; ask for the whole pool so
    # both test items are in the ranking whatever else is there.
    matches = await matching_service.find_matches_for_lost_item(
        lost_id, top_k=10_000, min_score=0.0, persist=False
    )
    by_id = {m["found_id"]: m for m in matches}

    assert by_id[right]["score"] > by_id[wrong_colour]["score"]
    assert by_id[right]["same_class"] and by_id[right]["same_color"]


async def test_items_found_before_the_loss_are_excluded(camera):
    lost_at = datetime.now(timezone.utc) - timedelta(hours=3)
    before = await _insert_found_item(
        camera["camera_id"], "wallet", "brown", found_at=lost_at - timedelta(hours=1)
    )
    lost_id = await _insert_lost_item("wallet", "brown", lost_after=lost_at)

    matches = await matching_service.find_matches_for_lost_item(
        lost_id, top_k=50, min_score=0.0, persist=False
    )
    assert before not in [m["found_id"] for m in matches]


async def test_repeat_detections_collapse_into_one_suggestion(camera):
    lost_at = datetime.now(timezone.utc) - timedelta(hours=4)
    cam = camera["camera_id"]
    first = await _insert_found_item(
        cam, "umbrella", "blue", found_at=lost_at + timedelta(hours=1), box=(100, 100, 200, 200)
    )
    again = await _insert_found_item(
        cam, "umbrella", "blue", found_at=lost_at + timedelta(hours=2), box=(102, 101, 201, 203)
    )
    lost_id = await _insert_lost_item("umbrella", "blue", lost_after=lost_at)

    matches = await matching_service.find_matches_for_lost_item(
        lost_id, top_k=50, min_score=0.0, persist=False
    )
    ours = [m for m in matches if m["found_id"] in (first, again)]
    assert len(ours) == 1 and ours[0]["sightings"] == 2
    assert "bbox" not in ours[0]


async def test_description_colour_is_used_when_there_is_no_photo(camera):
    lost_id = (
        await matching_service.create_lost_item(
            description="small navy umbrella", class_name="umbrella"
        )
    )["lost_id"]
    _CREATED.append(("lost_item", "lost_id", lost_id))

    report = await matching_service.get_lost_item(lost_id)
    assert report["dominant_color"] == "blue"  # "navy" read from the description


async def test_confirm_match_resolves_both_sides(camera):
    frame = np.full((200, 200, 3), 128, dtype=np.uint8)
    event = AbandonmentEvent(
        track_id=1234,
        class_name="bag",
        confidence=0.95,
        box=(20.0, 20.0, 120.0, 120.0),
        first_seen_at=1_700_000_000.0,
        static_since=1_700_000_003.0,
        abandoned_at=1_700_000_040.0,
        owner_track_id=None,
        unattended_seconds=37.0,
    )
    stored = await event_service.record_event(camera["camera_id"], event, frame)
    found = await db_manager.execute_query(
        "SELECT found_id FROM found_item WHERE event_id = $1", (stored["event_id"],), fetch_one=True
    )
    lost_id = await _insert_lost_item("bag", None)

    await matching_service.confirm_match(lost_id, found["found_id"], 0.93)

    lost = await matching_service.get_lost_item(lost_id)
    assert lost["status"] == "RESOLVED"

    found_row = await db_manager.execute_query(
        "SELECT status FROM found_item WHERE found_id = $1", (found["found_id"],), fetch_one=True
    )
    assert found_row["status"] == "CLAIMED"

    event_row = await event_service.get_event(stored["event_id"], include_frame=False)
    assert event_row["status"] == "RESOLVED"

    # A claimed item drops out of the searchable gallery.
    remaining = await matching_service.find_matches_for_lost_item(
        lost_id, top_k=50, min_score=0.0
    )
    assert found["found_id"] not in [m["found_id"] for m in remaining]


# ----------------------------------------------------------------- analytics
async def test_analytics_summary_windows_and_buckets(camera):
    cam = camera["camera_id"]
    now = datetime.now(timezone.utc)
    await _insert_event(cam, "bag", now - timedelta(hours=1))
    await _insert_event(cam, "bag", now - timedelta(days=2))
    await _insert_event(cam, "wallet", now - timedelta(days=3), status="FALSE_POSITIVE")
    await _insert_event(cam, "bag", now - timedelta(days=10))  # outside a 7-day window

    week = await analytics_service.summary(days=7, camera_id=cam, tz="UTC")

    # Zero-filled: one point per day whether or not anything happened.
    assert week["window"]["bucket"] == "day"
    assert len(week["series"]) == 7
    assert sum(point["events"] for point in week["series"]) == 3

    assert week["kpis"]["events"] == 3
    assert week["kpis"]["false_positives"] == 1
    assert week["kpis"]["false_positive_pct"] == 33.3
    assert week["kpis"]["avg_unattended_s"] == 30.0
    assert sum(cell["events"] for cell in week["heatmap"]) == 3

    assert [row["camera_id"] for row in week["by_camera"]] == [cam]
    assert {row["class_name"]: row["events"] for row in week["by_class"]} == {"bag": 2, "wallet": 1}

    day = await analytics_service.summary(days=1, camera_id=cam, tz="Africa/Cairo")
    assert day["window"]["bucket"] == "hour"
    assert len(day["series"]) == 24
    assert day["kpis"]["events"] == 1

    with pytest.raises(ValueError):
        await analytics_service.summary(days=7, tz="Not/AZone")


# ------------------------------------------------------------------- helpers
async def _insert_event(camera_id, class_name: str, abandoned_at: datetime, status: str = "OPEN"):
    """An event abandoned after 30 s unattended; the camera fixture's cascade removes it."""
    await db_manager.execute_query(
        """
        INSERT INTO abandoned_event (
            camera_id, track_key, class_name, confidence, bbox, first_seen_at,
            static_since, abandoned_at, status
        )
        VALUES ($1, $2, $3, 0.8, '{"x1": 0, "y1": 0, "x2": 50, "y2": 50}'::jsonb, $4, $4, $5, $6)
        """,
        (
            camera_id,
            f"test-{uuid.uuid4().hex[:8]}",
            class_name,
            abandoned_at - timedelta(seconds=30),
            abandoned_at,
            status,
        ),
    )


async def _insert_found_item(
    camera_id, class_name: str, color: str = None, found_at: datetime = None, box=None
):
    """A found item, with a backing event when a box is given (for repeat collapsing)."""
    event_id = None
    if box is not None:
        x1, y1, x2, y2 = box
        when = found_at or datetime.now(timezone.utc)
        event = await db_manager.execute_query(
            """
            INSERT INTO abandoned_event (
                camera_id, track_key, class_name, bbox, first_seen_at, abandoned_at
            )
            VALUES ($1, $2, $3, $4::jsonb, $5, $5)
            RETURNING event_id
            """,
            (
                camera_id,
                f"test-{uuid.uuid4().hex[:8]}",
                class_name,
                json.dumps({"x1": x1, "y1": y1, "x2": x2, "y2": y2}),
                when,
            ),
            fetch_one=True,
        )
        event_id = event["event_id"]
    row = await db_manager.execute_query(
        """
        INSERT INTO found_item (event_id, camera_id, class_name, dominant_color, found_at)
        VALUES ($1, $2, $3, $4, COALESCE($5, NOW()))
        RETURNING found_id
        """,
        (event_id, camera_id, class_name, color, found_at),
        fetch_one=True,
    )
    _CREATED.append(("found_item", "found_id", row["found_id"]))
    return row["found_id"]


async def _insert_lost_item(class_name: str = None, color: str = None, lost_after=None):
    row = await db_manager.execute_query(
        """
        INSERT INTO lost_item (description, class_name, dominant_color, lost_after)
        VALUES ('test report', $1, $2, $3)
        RETURNING lost_id
        """,
        (class_name, color, lost_after),
        fetch_one=True,
    )
    _CREATED.append(("lost_item", "lost_id", row["lost_id"]))
    return row["lost_id"]
