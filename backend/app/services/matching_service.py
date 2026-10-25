# app/services/matching_service.py
"""Lost-item reports, the searchable found gallery, and rule-based matching.

No models are involved. The search page filters found items by camera, time
range, object type, colour and status - plain indexed SQL. A lost report is
matched by rules: candidates share its object type or colour, and each is
scored on

    same object type        match_class_weight   (0.5)
    compatible colour       match_color_weight   (0.3)
    found soon after loss   match_time_weight    (0.2, fading over match_window_hours)
    looks like the photo    match_visual_weight  (0.3, only when the report has one:
                            perceptual hash + colour histogram against the crop)

and the score is the weighted mean over the parts available.

A static object re-detected by the same camera (overlapping boxes) is folded
into a single suggestion with a sighting count.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

import numpy as np

from app.core.config import config
from app.core.database import db_manager
from app.services import media_service
from app.services.object_store import photo_key
from app.utils import visual_similarity
from app.utils.color_utils import color_agreement, color_from_text, dominant_color
from app.utils.geometry_utils import iou
from app.utils.image_utils import bytes_to_base64, decode_jpeg, encode_jpeg

logger = logging.getLogger(__name__)

# Enough to cover a busy day of detections for one report; the rerank and the
# repeat-sighting collapse run in Python over these.
_MAX_CANDIDATES = 500


def _box(bbox: Any) -> Optional[tuple]:
    """abandoned_event.bbox ({"x1":..,"y1":..,"x2":..,"y2":..}) as a tuple."""
    if isinstance(bbox, str):
        try:
            bbox = json.loads(bbox)
        except ValueError:
            return None
    if not isinstance(bbox, dict):
        return None
    try:
        return (float(bbox["x1"]), float(bbox["y1"]), float(bbox["x2"]), float(bbox["y2"]))
    except (KeyError, TypeError, ValueError):
        return None


def score_candidate(
    candidate: Dict[str, Any],
    class_name: Optional[str],
    color: Optional[str],
    lost_after: Optional[datetime],
    visual: Optional[float] = None,
    has_photo: bool = False,
) -> Dict[str, Any]:
    """Weigh one found item against a report's type, colour, loss time and photo.

    ``visual`` is the photo's likeness to the item's crop (0-1). When the report
    has a photo but the item has no crop to compare (``visual`` None), the
    likeness counts as neutral: leaving it out would rank items that cannot be
    checked above items that were checked and look only fairly alike.
    """
    same_class = bool(class_name) and candidate.get("class_name") == class_name
    same_color = color_agreement(color, candidate.get("dominant_color"))

    found_at = candidate.get("found_at")
    if lost_after is not None and found_at is not None:
        hours = max(0.0, (found_at - lost_after).total_seconds() / 3600.0)
        window = max(config.match_window_hours, 1e-6)
        time_fit = max(0.0, 1.0 - hours / window)
    else:
        # No loss time given: nothing to be close to, so half credit for all.
        time_fit = 0.5

    parts = [
        (config.match_class_weight, float(same_class)),
        (config.match_color_weight, float(same_color)),
        (config.match_time_weight, time_fit),
    ]
    if visual is not None or has_photo:
        parts.append((config.match_visual_weight, 0.5 if visual is None else visual))
    total = sum(weight for weight, _ in parts)
    score = sum(weight * value for weight, value in parts) / total if total > 0 else 0.0

    match = dict(candidate)
    match.pop("phash", None)
    match.pop("color_hist", None)
    match["same_class"] = same_class
    match["same_color"] = same_color
    match["visual_similarity"] = None if visual is None else round(visual, 4)
    match["score"] = round(min(1.0, score), 4)
    return match


def collapse_repeat_sightings(
    matches: Sequence[Dict[str, Any]], min_iou: float
) -> List[Dict[str, Any]]:
    """Fold re-detections of one static object into its best-scoring match.

    ``matches`` must be sorted best-first. A later match from the same camera
    whose box overlaps a kept one by at least ``min_iou`` is the same object
    seen again (an abandoned item does not move): it is dropped, and the kept
    match counts it in ``sightings`` / ``last_seen_at``. Object type is
    deliberately ignored - the detector flips labels on one object.
    """
    kept: List[Dict[str, Any]] = []
    boxes: List[Optional[tuple]] = []

    for match in matches:
        box = _box(match.get("bbox"))
        owner = None
        if box is not None:
            for index, other in enumerate(kept):
                if (
                    boxes[index] is not None
                    and other.get("camera_id") == match.get("camera_id")
                    and iou(box, boxes[index]) >= min_iou
                ):
                    owner = other
                    break

        if owner is None:
            match = dict(match)
            match["sightings"] = 1
            match["last_seen_at"] = match.get("found_at")
            kept.append(match)
            boxes.append(box)
            continue

        owner["sightings"] += 1
        seen = match.get("found_at")
        if seen is not None and (owner["last_seen_at"] is None or seen > owner["last_seen_at"]):
            owner["last_seen_at"] = seen

    for match in kept:
        match.pop("bbox", None)
    return kept


class MatchingService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    # ------------------------------------------------------------ lost items
    async def create_lost_item(
        self,
        image: Optional[np.ndarray] = None,
        description: Optional[str] = None,
        reporter_name: Optional[str] = None,
        reporter_email: Optional[str] = None,
        class_name: Optional[str] = None,
        lost_after: Optional[datetime] = None,
        workspace_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Register a lost item from a photo and/or a text description.

        The colour used for matching comes from the photo, or failing that from
        a colour word in the description ("black leather bag").
        """
        photo_jpeg = encode_jpeg(image) if image is not None else None
        color = dominant_color(image) if image is not None else None
        if color is None:
            color = color_from_text(description)
        features = visual_similarity.extract(image, keep=config.match_photo_keep)

        query = """
            INSERT INTO lost_item (
                reporter_name, reporter_email, description, class_name, dominant_color,
                lost_after, phash, color_hist, workspace_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                    COALESCE($9, '00000000-0000-0000-0000-000000000001'::uuid))
            RETURNING lost_id, workspace_id, reporter_name, reporter_email, description, class_name,
                      dominant_color, lost_after, reported_at, status
        """
        report = await self.db_manager.execute_query(
            query,
            (
                reporter_name,
                reporter_email,
                description,
                class_name,
                color,
                lost_after,
                features.phash if features else None,
                features.histogram_bytes if features else None,
                workspace_id,
            ),
            fetch_one=True,
        )
        if report:
            await media_service.save_image(
                media_service.LOST_PHOTO, report["lost_id"], photo_key(report["lost_id"]), photo_jpeg
            )
        return report

    async def get_lost_item(self, lost_id: UUID, include_photo: bool = False) -> Optional[Dict]:
        row = await self.db_manager.execute_query(
            """
            SELECT lost_id, reporter_name, reporter_email, description, class_name,
                   dominant_color, lost_after, reported_at, status, reporter_notified_at
            FROM lost_item WHERE lost_id = $1
            """,
            (lost_id,),
            fetch_one=True,
        )
        if row and include_photo:
            row = dict(row)
            photo = await media_service.load_image(media_service.LOST_PHOTO, lost_id)
            row["photo_base64"] = bytes_to_base64(photo)
        return row

    async def set_lost_status(self, lost_id: UUID, status: str) -> Optional[Dict[str, Any]]:
        """Close a report nobody will follow up, or reopen one."""
        return await self.db_manager.execute_query(
            "UPDATE lost_item SET status = $2 WHERE lost_id = $1 RETURNING lost_id, status",
            (lost_id, status),
            fetch_one=True,
        )

    async def list_lost_items(
        self,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        workspace_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        conditions: List[str] = []
        params: List[Any] = []
        for column, value in (("workspace_id", workspace_id), ("status", status)):
            if value:
                params.append(value)
                conditions.append(f"{column} = ${len(params)}")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        total = await self.db_manager.execute_query(
            f"SELECT COUNT(*) AS total FROM lost_item {where}", tuple(params), fetch_one=True
        )

        params.extend([per_page, (page - 1) * per_page])
        rows = await self.db_manager.execute_query(
            f"""
            SELECT lost_id, reporter_name, reporter_email, description, class_name,
                   dominant_color, lost_after, reported_at, status
            FROM lost_item {where}
            ORDER BY reported_at DESC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}
            """,
            tuple(params),
            fetch_all=True,
        )
        return {
            "total": total["total"] if total else 0,
            "page": page,
            "per_page": per_page,
            "lost_items": rows,
        }

    # --------------------------------------------------------------- matching
    async def find_matches_for_lost_item(
        self,
        lost_id: UUID,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        persist: bool = True,
    ) -> List[Dict[str, Any]]:
        """Rank unclaimed found items against a stored lost report."""
        report = await self.db_manager.execute_query(
            """
            SELECT workspace_id, class_name, dominant_color, lost_after, phash, color_hist
            FROM lost_item WHERE lost_id = $1
            """,
            (lost_id,),
            fetch_one=True,
        )
        if not report:
            return []

        class_name, color = report["class_name"], report["dominant_color"]
        rows = await self.db_manager.execute_query(
            """
            SELECT f.found_id, f.event_id, f.camera_id, c.name AS camera_name,
                   f.class_name, f.dominant_color, f.found_at, f.status, e.bbox,
                   f.phash, f.color_hist
            FROM found_item f
            LEFT JOIN camera c          ON c.camera_id = f.camera_id
            LEFT JOIN abandoned_event e ON e.event_id  = f.event_id
            WHERE f.status = 'UNCLAIMED'
              -- Only the gallery of the workspace the report was filed in.
              AND f.workspace_id = $5
              AND ($3::timestamptz IS NULL OR f.found_at >= $3)
              AND (($1::text IS NULL AND $2::text IS NULL)
                   OR f.class_name = $1 OR f.dominant_color = $2
                   OR ($2::text IN ('black', 'gray', 'brown')
                       AND f.dominant_color IN ('black', 'gray', 'brown')))
            -- The pool is capped, so fill it with the likeliest items first:
            -- same type and colour, then the soonest after the loss.
            ORDER BY (f.class_name = $1) IS TRUE DESC,
                     (f.dominant_color = $2) IS TRUE DESC,
                     f.found_at
            LIMIT $4
            """,
            (class_name, color, report["lost_after"], _MAX_CANDIDATES, report["workspace_id"]),
            fetch_all=True,
        )

        limit = top_k or config.match_top_k
        threshold = config.match_min_score if min_score is None else min_score
        photo_hash = report["phash"]
        photo_hist = visual_similarity.histogram_from_bytes(report["color_hist"])
        if photo_hash is not None or photo_hist is not None:
            await self._backfill_features(rows)

        matches = []
        for row in rows:
            visual = None
            if photo_hash is not None or photo_hist is not None:
                visual = visual_similarity.similarity(
                    photo_hash,
                    photo_hist,
                    row["phash"],
                    visual_similarity.histogram_from_bytes(row["color_hist"]),
                    config.match_hash_share,
                )
            has_photo = photo_hash is not None or photo_hist is not None
            matches.append(score_candidate(row, class_name, color, report["lost_after"], visual, has_photo))
        matches.sort(key=lambda m: (m["score"], m["found_at"]), reverse=True)
        matches = collapse_repeat_sightings(matches, config.match_dedupe_iou)
        matches = [m for m in matches if m["score"] >= threshold][:limit]

        if persist and matches:
            await self._persist_suggestions(lost_id, matches)
        return matches

    async def _backfill_features(self, rows: List[Dict[str, Any]]) -> None:
        """Compute visual features for found items stored before they existed.

        The stored crop carries context around the box (crop_context_ratio), so
        only its centre is used - the part that is the item.
        """
        missing = [row for row in rows if row["phash"] is None and row["color_hist"] is None]
        if not missing:
            return
        crops = await self.db_manager.execute_query(
            "SELECT found_id, crop_key, crop_jpeg FROM found_item WHERE found_id = ANY($1::uuid[])",
            ([row["found_id"] for row in missing],),
            fetch_all=True,
        )
        keep = 1.0 / (1.0 + 2.0 * config.crop_context_ratio)
        by_id = {row["found_id"]: row for row in missing}
        for crop in crops or []:
            data = await media_service.load(crop["crop_key"], crop["crop_jpeg"])
            image = decode_jpeg(data) if data else None
            features = visual_similarity.extract(image, keep=keep)
            if features is None:
                continue
            await self.db_manager.execute_query(
                "UPDATE found_item SET phash = $2, color_hist = $3 WHERE found_id = $1",
                (crop["found_id"], features.phash, features.histogram_bytes),
            )
            row = by_id[crop["found_id"]]
            row["phash"], row["color_hist"] = features.phash, features.histogram_bytes

    async def _persist_suggestions(self, lost_id: UUID, matches: List[Dict[str, Any]]) -> None:
        """Keep the suggested shortlist so operators can review it later."""
        try:
            await self.db_manager.execute_many(
                """
                INSERT INTO match_result (lost_id, found_id, score, method)
                VALUES ($1, $2, $3, 'rule_based')
                ON CONFLICT (lost_id, found_id)
                DO UPDATE SET score = EXCLUDED.score, created_at = NOW()
                """,
                [(lost_id, m["found_id"], m["score"]) for m in matches],
            )
        except Exception as e:
            logger.warning("Could not persist match suggestions for %s: %s", lost_id, e)

    # ---------------------------------------------------------- confirmation
    async def confirm_match(self, lost_id: UUID, found_id: UUID, score: float = 1.0) -> Dict:
        """Operator confirms a pairing: the lost report closes, the item is claimed."""
        match = await self.db_manager.execute_query(
            """
            INSERT INTO match_result (lost_id, found_id, score, method, confirmed)
            VALUES ($1, $2, $3, 'operator_confirmed', TRUE)
            ON CONFLICT (lost_id, found_id)
            DO UPDATE SET confirmed = TRUE, method = 'operator_confirmed', created_at = NOW()
            RETURNING match_id, lost_id, found_id, score, confirmed
            """,
            (lost_id, found_id, score),
            fetch_one=True,
        )

        await self.db_manager.execute_query(
            "UPDATE lost_item SET status = 'RESOLVED' WHERE lost_id = $1", (lost_id,)
        )
        await self.db_manager.execute_query(
            "UPDATE found_item SET status = 'CLAIMED' WHERE found_id = $1", (found_id,)
        )
        await self.db_manager.execute_query(
            """
            UPDATE abandoned_event SET status = 'RESOLVED'
            WHERE event_id = (SELECT event_id FROM found_item WHERE found_id = $1)
            """,
            (found_id,),
        )

        logger.info("Match confirmed: lost %s <-> found %s", lost_id, found_id)
        return match

    async def reject_match(self, lost_id: UUID, found_id: UUID) -> bool:
        rows = await self.db_manager.execute_query(
            "DELETE FROM match_result WHERE lost_id = $1 AND found_id = $2",
            (lost_id, found_id),
            return_rowcount=True,
        )
        return bool(rows)

    # ----------------------------------------------------------- found items
    async def list_found_items(
        self,
        status: Optional[str] = None,
        camera_id: Optional[UUID] = None,
        class_name: Optional[str] = None,
        color: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        page: int = 1,
        per_page: int = 20,
        workspace_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """The found gallery and the search page: every filter is optional."""
        conditions: List[str] = []
        params: List[Any] = []
        for column, op, value in (
            ("f.workspace_id", "=", workspace_id),
            ("f.status", "=", status),
            ("f.camera_id", "=", camera_id),
            ("f.class_name", "=", class_name),
            ("f.dominant_color", "=", color),
            ("f.found_at", ">=", start),
            ("f.found_at", "<=", end),
        ):
            if value is not None and value != "":
                params.append(value)
                conditions.append(f"{column} {op} ${len(params)}")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        total = await self.db_manager.execute_query(
            f"SELECT COUNT(*) AS total FROM found_item f {where}", tuple(params), fetch_one=True
        )

        params.extend([per_page, (page - 1) * per_page])
        rows = await self.db_manager.execute_query(
            f"""
            SELECT f.found_id, f.event_id, f.camera_id, c.name AS camera_name,
                   f.class_name, f.dominant_color, f.found_at, f.status
            FROM found_item f
            LEFT JOIN camera c ON c.camera_id = f.camera_id
            {where}
            ORDER BY f.found_at DESC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}
            """,
            tuple(params),
            fetch_all=True,
        )
        return {
            "total": total["total"] if total else 0,
            "page": page,
            "per_page": per_page,
            "found_items": rows,
        }

    async def get_found_item(self, found_id: UUID) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            """
            SELECT f.found_id, f.event_id, f.camera_id, c.name AS camera_name,
                   f.class_name, f.dominant_color, f.found_at, f.status
            FROM found_item f
            LEFT JOIN camera c ON c.camera_id = f.camera_id
            WHERE f.found_id = $1
            """,
            (found_id,),
            fetch_one=True,
        )

    async def set_found_status(self, found_id: UUID, status: str) -> Optional[Dict[str, Any]]:
        """Discard an item (thrown away, handed to the police) or put it back in the gallery."""
        return await self.db_manager.execute_query(
            "UPDATE found_item SET status = $2 WHERE found_id = $1 RETURNING found_id, status",
            (found_id, status),
            fetch_one=True,
        )

    async def get_found_crop(self, found_id: UUID) -> Optional[bytes]:
        return await media_service.load_image(media_service.FOUND_CROP, found_id)


matching_service = MatchingService()
