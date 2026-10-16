# app/services/event_service.py
"""Persistence for abandoned-object events and the found-item gallery they feed."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import numpy as np

from app.core.config import config
from app.core.database import db_manager
from app.services import media_service
from app.services.abandonment_service import AbandonmentEvent
from app.services.object_store import crop_key, frame_key
from app.utils.color_utils import dominant_color
from app.utils import visual_similarity
from app.utils.image_utils import annotate_abandoned, bytes_to_base64, crop_box, encode_jpeg

logger = logging.getLogger(__name__)


def _to_datetime(epoch: Optional[float]) -> Optional[datetime]:
    return datetime.fromtimestamp(epoch, tz=timezone.utc) if epoch else None


class EventService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    # -------------------------------------------------------------- ingestion
    async def record_event(
        self,
        camera_id: UUID,
        event: AbandonmentEvent,
        frame: Optional[np.ndarray] = None,
    ) -> Optional[Dict[str, Any]]:
        """Store an abandoned event and derive the matching found_item row.

        Returns None when the (camera, track) pair was already recorded, which
        makes the whole path idempotent even if a worker replays an event.
        """
        annotated_jpeg: Optional[bytes] = None
        crop = None
        features = None

        if frame is not None:
            annotated = annotate_abandoned(
                frame, event.box, event.class_name, event.unattended_seconds
            )
            annotated_jpeg = encode_jpeg(annotated)
            crop = crop_box(frame, event.box, context_ratio=config.crop_context_ratio)
            # Features from the box itself: the context around the crop would
            # put the floor into the colour histogram.
            features = visual_similarity.extract(crop_box(frame, event.box, padding=0))

        x1, y1, x2, y2 = event.box
        query = """
            INSERT INTO abandoned_event (
                camera_id, track_key, class_name, confidence, bbox,
                owner_track_id, first_seen_at, static_since, abandoned_at
            )
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9)
            ON CONFLICT (camera_id, track_key) DO NOTHING
            RETURNING event_id, camera_id, track_key, class_name, confidence,
                      bbox, owner_track_id, first_seen_at, abandoned_at, status
        """
        stored = await self.db_manager.execute_query(
            query,
            (
                camera_id,
                event.track_key or str(event.track_id),
                event.class_name,
                event.confidence,
                json.dumps({"x1": x1, "y1": y1, "x2": x2, "y2": y2}),
                event.owner_track_id,
                _to_datetime(event.first_seen_at),
                _to_datetime(event.static_since),
                _to_datetime(event.abandoned_at),
            ),
            fetch_one=True,
        )

        if not stored:
            logger.debug(
                "Event for camera %s track %s already recorded; skipping.",
                camera_id,
                event.track_id,
            )
            return None

        await media_service.save_image(
            media_service.EVENT_FRAME,
            stored["event_id"],
            frame_key(camera_id, stored["event_id"]),
            annotated_jpeg,
        )
        await self._create_found_item(stored["event_id"], camera_id, event.class_name, crop, features)
        logger.info(
            "Recorded abandoned %s on camera %s (event %s)",
            event.class_name,
            camera_id,
            stored["event_id"],
        )
        return stored

    async def _create_found_item(
        self,
        event_id: UUID,
        camera_id: UUID,
        class_name: str,
        crop: Optional[np.ndarray],
        features: Optional[visual_similarity.VisualFeatures] = None,
    ) -> Optional[UUID]:
        """Add the object to the found gallery, searchable by camera, time, type and colour."""
        color = None
        crop_jpeg = None

        if crop is not None:
            crop_jpeg = encode_jpeg(crop)
            color = dominant_color(crop)

        query = """
            INSERT INTO found_item (
                event_id, camera_id, class_name, dominant_color, phash, color_hist
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING found_id
        """
        result = await self.db_manager.execute_query(
            query,
            (
                event_id,
                camera_id,
                class_name,
                color,
                features.phash if features else None,
                features.histogram_bytes if features else None,
            ),
            fetch_one=True,
        )
        if not result:
            return None
        await media_service.save_image(
            media_service.FOUND_CROP, result["found_id"], crop_key(camera_id, result["found_id"]), crop_jpeg
        )
        return result["found_id"]

    # ---------------------------------------------------------------- queries
    async def list_events(
        self,
        camera_id: Optional[UUID] = None,
        status: Optional[str] = None,
        class_name: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        include_frame: bool = False,
        page: int = 1,
        per_page: int = 20,
    ) -> Dict[str, Any]:
        conditions: List[str] = []
        params: List[Any] = []

        def add(condition: str, value: Any) -> None:
            params.append(value)
            conditions.append(condition.format(n=len(params)))

        if camera_id:
            add("e.camera_id = ${n}", camera_id)
        if status:
            add("e.status = ${n}", status)
        if class_name:
            add("e.class_name = ${n}", class_name)
        if start:
            add("e.abandoned_at >= ${n}", start)
        if end:
            add("e.abandoned_at <= ${n}", end)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        total = await self.db_manager.execute_query(
            f"SELECT COUNT(*) AS total FROM abandoned_event e {where}",
            tuple(params),
            fetch_one=True,
        )

        frame_column = ", e.frame_key, e.frame_jpeg" if include_frame else ""
        params.extend([per_page, (page - 1) * per_page])
        rows = await self.db_manager.execute_query(
            f"""
            SELECT e.event_id, e.camera_id, c.name AS camera_name, e.track_key,
                   e.class_name, e.confidence, e.bbox, e.owner_track_id,
                   e.first_seen_at, e.abandoned_at, e.status,
                   (e.clip_key IS NOT NULL OR e.clip_path IS NOT NULL) AS has_clip,
                   f.found_id, f.dominant_color{frame_column}
            FROM abandoned_event e
            LEFT JOIN camera c ON c.camera_id = e.camera_id
            LEFT JOIN found_item f ON f.event_id = e.event_id
            {where}
            ORDER BY e.abandoned_at DESC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}
            """,
            tuple(params),
            fetch_all=True,
        )

        return {
            "total": total["total"] if total else 0,
            "page": page,
            "per_page": per_page,
            "events": [self._serialize_event(await self._with_frame(row)) for row in rows],
        }

    async def get_event(
        self, event_id: UUID, include_frame: bool = True
    ) -> Optional[Dict[str, Any]]:
        row = await self.db_manager.execute_query(
            f"""
            SELECT e.*, (e.clip_key IS NOT NULL OR e.clip_path IS NOT NULL) AS has_clip,
                   c.name AS camera_name, f.found_id, f.dominant_color
            FROM abandoned_event e
            LEFT JOIN camera c ON c.camera_id = e.camera_id
            LEFT JOIN found_item f ON f.event_id = e.event_id
            WHERE e.event_id = $1
            """,
            (event_id,),
            fetch_one=True,
        )
        if not row:
            return None
        if not include_frame:
            row = {k: v for k, v in row.items() if k not in ("frame_jpeg", "frame_key")}
        return self._serialize_event(await self._with_frame(row))

    @staticmethod
    async def _with_frame(row: Dict[str, Any]) -> Dict[str, Any]:
        """Swap the frame's key/bytes for the image itself (from MinIO when it is there)."""
        if "frame_key" not in row and "frame_jpeg" not in row:
            return row
        row = dict(row)
        row["frame_jpeg"] = await media_service.load(row.pop("frame_key", None), row.get("frame_jpeg"))
        return row

    async def get_event_frame(self, event_id: UUID) -> Optional[bytes]:
        return await media_service.load_image(media_service.EVENT_FRAME, event_id)

    async def set_clip_path(self, event_id: UUID, clip_path: Optional[str]) -> None:
        """Clip kept on disk (MinIO was unreachable)."""
        await self.db_manager.execute_query(
            "UPDATE abandoned_event SET clip_path = $1 WHERE event_id = $2",
            (clip_path, event_id),
        )

    async def set_clip_key(self, event_id: UUID, clip_key: Optional[str]) -> None:
        await self.db_manager.execute_query(
            "UPDATE abandoned_event SET clip_key = $1 WHERE event_id = $2",
            (clip_key, event_id),
        )

    async def get_clip_location(self, event_id: UUID) -> Tuple[Optional[str], Optional[str]]:
        """(MinIO key, on-disk path) of the event's clip; either may be None."""
        row = await self.db_manager.execute_query(
            "SELECT clip_key, clip_path FROM abandoned_event WHERE event_id = $1",
            (event_id,),
            fetch_one=True,
        )
        return (row["clip_key"], row["clip_path"]) if row else (None, None)

    async def update_status(self, event_id: UUID, status: str) -> Optional[Dict[str, Any]]:
        row = await self.db_manager.execute_query(
            """
            UPDATE abandoned_event SET status = $1
            WHERE event_id = $2
            RETURNING event_id, status
            """,
            (status, event_id),
            fetch_one=True,
        )
        return row

    async def stats(self, camera_id: Optional[UUID] = None) -> Dict[str, Any]:
        where = "WHERE camera_id = $1" if camera_id else ""
        params: Sequence[Any] = (camera_id,) if camera_id else ()
        row = await self.db_manager.execute_query(
            f"""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status = 'OPEN') AS open,
                   COUNT(*) FILTER (WHERE abandoned_at > NOW() - INTERVAL '24 hours') AS last_24h,
                   MAX(abandoned_at) AS last_event_at
            FROM abandoned_event {where}
            """,
            params,
            fetch_one=True,
        )
        return row or {}

    # ------------------------------------------------------------ serializing
    @staticmethod
    def _serialize_event(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not row:
            return {}
        event = dict(row)
        # The on-disk path is an implementation detail; clients get has_clip and
        # fetch the file through /events/{id}/clip.
        event.pop("clip_path", None)
        event.pop("clip_key", None)
        event.pop("frame_key", None)
        event.pop("crop_jpeg", None)
        bbox = event.get("bbox")
        if isinstance(bbox, str):
            try:
                event["bbox"] = json.loads(bbox)
            except json.JSONDecodeError:
                event["bbox"] = None
        if "frame_jpeg" in event:
            event["frame_base64"] = bytes_to_base64(event.pop("frame_jpeg"))
        return event


event_service = EventService()
