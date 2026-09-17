"""Integration tests against a live Postgres with pgvector.

Skipped automatically when no database is reachable, so ``pytest`` stays green
without one. To run them, point the usual DB_* variables at a server that has
``database/init/002_schema.sql`` applied - for example the compose stack::

    DB_HOST=localhost DB_PORT=5433 pytest tests/test_integration.py

No YOLO or CLIP weights are needed: embeddings are crafted by hand so the
pgvector search path can be exercised on its own.
"""

import math
import uuid
from typing import List

import numpy as np
import pytest

from app.core.config import config
from app.core.database import close_db_pool, db_manager, init_db_pool, wait_for_schema
from app.services.abandonment_service import AbandonmentEvent
from app.services.camera_service import camera_service
from app.services.event_service import event_service
from app.services.matching_service import matching_service
from app.utils.vector_utils import to_pgvector

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


def unit_vector(index: int, dim: int = None) -> List[float]:
    """A one-hot vector: orthogonal to every other one, so cosine scores are obvious."""
    dim = dim or config.embedding_dim
    vector = [0.0] * dim
    vector[index] = 1.0
    return vector


def blended(a: int, b: int, weight: float) -> List[float]:
    """Normalised mix of two one-hot vectors, leaning towards ``a``."""
    vector = [0.0] * config.embedding_dim
    vector[a] = weight
    vector[b] = 1.0 - weight
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector]


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
        class_name="backpack",
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
    assert stored["class_name"] == "backpack"
    assert stored["owner_track_id"] == 3

    # The annotated alert frame is retrievable as JPEG bytes.
    jpeg = await event_service.get_event_frame(stored["event_id"])
    assert jpeg and jpeg[:2] == b"\xff\xd8"  # JPEG magic

    # The event auto-populated the found gallery.
    gallery = await matching_service.list_found_items(camera_id=camera["camera_id"])
    assert gallery["total"] == 1
    assert gallery["found_items"][0]["class_name"] == "backpack"

    listed = await event_service.list_events(camera_id=camera["camera_id"])
    assert listed["total"] == 1
    assert listed["events"][0]["bbox"]["x1"] == 100.0


async def test_record_event_is_idempotent(camera):
    """A replayed event for the same track must not duplicate the row."""
    event = AbandonmentEvent(
        track_id=99,
        class_name="suitcase",
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
        class_name="handbag",
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


# ------------------------------------------------------------------ matching
async def test_pgvector_ranks_the_closer_embedding_first(camera):
    """The whole retrieval path: text-cast vectors in, cosine ranking out."""
    close_id = await _insert_found_item(camera["camera_id"], "backpack", unit_vector(0), "blue")
    far_id = await _insert_found_item(camera["camera_id"], "backpack", unit_vector(1), "red")

    lost_id = await _insert_lost_item(blended(0, 1, 0.95), class_name="backpack", color="blue")

    matches = await matching_service.find_matches_for_lost_item(
        lost_id, top_k=50, min_similarity=0.0
    )
    ranked = [m["found_id"] for m in matches]
    by_id = {m["found_id"]: m for m in matches}

    assert ranked.index(close_id) < ranked.index(far_id)
    assert by_id[close_id]["score"] > by_id[far_id]["score"]
    # cos(query, e0) = 0.95 / sqrt(0.95^2 + 0.05^2) = 0.9986
    assert by_id[close_id]["image_similarity"] == pytest.approx(0.9986, abs=1e-3)
    assert by_id[close_id]["same_class"] and by_id[close_id]["same_color"]


async def test_min_similarity_filters_weak_matches(camera):
    await _insert_found_item(camera["camera_id"], "suitcase", unit_vector(5))
    lost_id = await _insert_lost_item(unit_vector(300))  # orthogonal -> similarity 0

    assert await matching_service.find_matches_for_lost_item(lost_id, min_similarity=0.5) == []
    assert await matching_service.find_matches_for_lost_item(lost_id, min_similarity=0.0) != []


async def test_confirm_match_resolves_both_sides(camera):
    frame = np.full((200, 200, 3), 128, dtype=np.uint8)
    event = AbandonmentEvent(
        track_id=1234,
        class_name="backpack",
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
    lost_id = await _insert_lost_item(unit_vector(0))

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
        lost_id, top_k=50, min_similarity=0.0
    )
    assert found["found_id"] not in [m["found_id"] for m in remaining]


# ------------------------------------------------------------------- helpers
async def _insert_found_item(camera_id, class_name: str, embedding, color: str = None):
    row = await db_manager.execute_query(
        """
        INSERT INTO found_item (camera_id, class_name, dominant_color, embedding)
        VALUES ($1, $2, $3, $4::text::vector)
        RETURNING found_id
        """,
        (camera_id, class_name, color, to_pgvector(embedding)),
        fetch_one=True,
    )
    _CREATED.append(("found_item", "found_id", row["found_id"]))
    return row["found_id"]


async def _insert_lost_item(embedding, class_name: str = None, color: str = None):
    row = await db_manager.execute_query(
        """
        INSERT INTO lost_item (description, class_name, dominant_color, embedding)
        VALUES ('test report', $1, $2, $3::text::vector)
        RETURNING lost_id
        """,
        (class_name, color, to_pgvector(embedding)),
        fetch_one=True,
    )
    _CREATED.append(("lost_item", "lost_id", row["lost_id"]))
    return row["lost_id"]
