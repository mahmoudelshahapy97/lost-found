# app/services/matching_service.py
"""Lost-item reporting and lost <-> found visual matching.

Candidate retrieval happens in Postgres via pgvector's cosine operator (which
the HNSW index accelerates); the shortlist is then reranked in Python with cheap
attribute bonuses for a matching class and a matching dominant colour.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import numpy as np

from app.core.config import config
from app.core.database import db_manager
from app.services.embedding_service import embedding_service
from app.utils.color_utils import color_agreement, dominant_color
from app.utils.image_utils import bytes_to_base64, encode_jpeg
from app.utils.vector_utils import to_pgvector

logger = logging.getLogger(__name__)


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
    ) -> Dict[str, Any]:
        """Register a lost item from a photo and/or a text description."""
        photo_jpeg = encode_jpeg(image) if image is not None else None
        color = dominant_color(image) if image is not None else None

        embedding = await embedding_service.embed_image_async(image) if image is not None else None
        text_embedding = (
            await embedding_service.embed_text_async(description) if description else None
        )

        query = """
            INSERT INTO lost_item (
                reporter_name, reporter_email, description, class_name, dominant_color,
                photo_jpeg, embedding, text_embedding, lost_after
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7::text::vector, $8::text::vector, $9)
            RETURNING lost_id, reporter_name, reporter_email, description, class_name,
                      dominant_color, lost_after, reported_at, status
        """
        return await self.db_manager.execute_query(
            query,
            (
                reporter_name,
                reporter_email,
                description,
                class_name,
                color,
                photo_jpeg,
                to_pgvector(embedding),
                to_pgvector(text_embedding),
                lost_after,
            ),
            fetch_one=True,
        )

    async def get_lost_item(self, lost_id: UUID, include_photo: bool = False) -> Optional[Dict]:
        photo_column = ", photo_jpeg" if include_photo else ""
        row = await self.db_manager.execute_query(
            f"""
            SELECT lost_id, reporter_name, reporter_email, description, class_name,
                   dominant_color, lost_after, reported_at, status{photo_column}
            FROM lost_item WHERE lost_id = $1
            """,
            (lost_id,),
            fetch_one=True,
        )
        if row and "photo_jpeg" in row:
            row = dict(row)
            row["photo_base64"] = bytes_to_base64(row.pop("photo_jpeg"))
        return row

    async def list_lost_items(
        self, status: Optional[str] = None, page: int = 1, per_page: int = 20
    ) -> Dict[str, Any]:
        where = "WHERE status = $1" if status else ""
        params: List[Any] = [status] if status else []

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
        min_similarity: Optional[float] = None,
        persist: bool = True,
    ) -> List[Dict[str, Any]]:
        """Rank found items against a stored lost report."""
        row = await self.db_manager.execute_query(
            """
            SELECT lost_id, class_name, dominant_color, lost_after,
                   embedding::text AS embedding, text_embedding::text AS text_embedding
            FROM lost_item WHERE lost_id = $1
            """,
            (lost_id,),
            fetch_one=True,
        )
        if not row:
            return []

        matches = await self._search(
            image_vector=row["embedding"],
            text_vector=row["text_embedding"],
            class_name=row["class_name"],
            color=row["dominant_color"],
            found_after=row["lost_after"],
            top_k=top_k,
            min_similarity=min_similarity,
        )

        if persist and matches:
            await self._persist_suggestions(lost_id, matches)
        return matches

    async def search_by_image(
        self,
        image: np.ndarray,
        description: Optional[str] = None,
        class_name: Optional[str] = None,
        top_k: Optional[int] = None,
        min_similarity: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Ad-hoc search that stores nothing - "does this bag look familiar?"."""
        embedding = await embedding_service.embed_image_async(image)
        if not embedding:
            return []
        text_embedding = (
            await embedding_service.embed_text_async(description) if description else None
        )
        return await self._search(
            image_vector=to_pgvector(embedding),
            text_vector=to_pgvector(text_embedding),
            class_name=class_name,
            color=dominant_color(image),
            found_after=None,
            top_k=top_k,
            min_similarity=min_similarity,
        )

    async def search_by_text(
        self,
        description: str,
        class_name: Optional[str] = None,
        top_k: Optional[int] = None,
        min_similarity: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Text-only search: CLIP puts the phrase in the same space as the crops."""
        text_embedding = await embedding_service.embed_text_async(description)
        if not text_embedding:
            return []
        # With no photo the text vector *is* the query vector.
        return await self._search(
            image_vector=to_pgvector(text_embedding),
            text_vector=None,
            class_name=class_name,
            color=None,
            found_after=None,
            top_k=top_k,
            min_similarity=min_similarity,
        )

    async def _search(
        self,
        image_vector: Optional[str],
        text_vector: Optional[str],
        class_name: Optional[str],
        color: Optional[str],
        found_after: Optional[datetime],
        top_k: Optional[int],
        min_similarity: Optional[float],
    ) -> List[Dict[str, Any]]:
        if not image_vector:
            return []

        limit = top_k or config.match_top_k
        threshold = config.match_min_similarity if min_similarity is None else min_similarity

        # Over-fetch so the attribute rerank has room to reorder.
        rows = await self.db_manager.execute_query(
            """
            SELECT f.found_id, f.event_id, f.camera_id, c.name AS camera_name,
                   f.class_name, f.dominant_color, f.found_at, f.status,
                   1 - (f.embedding <=> $1::text::vector) AS image_similarity,
                   CASE WHEN $2::text IS NULL THEN NULL
                        ELSE 1 - (f.embedding <=> $2::text::vector)
                   END AS text_similarity
            FROM found_item f
            LEFT JOIN camera c ON c.camera_id = f.camera_id
            WHERE f.embedding IS NOT NULL
              AND f.status = 'UNCLAIMED'
              AND ($3::timestamptz IS NULL OR f.found_at >= $3)
            ORDER BY f.embedding <=> $1::text::vector
            LIMIT $4
            """,
            (image_vector, text_vector, found_after, limit * 3),
            fetch_all=True,
        )

        matches = [self._score(row, class_name, color) for row in rows]
        matches = [m for m in matches if m["score"] >= threshold]
        matches.sort(key=lambda m: m["score"], reverse=True)
        return matches[:limit]

    @staticmethod
    def _score(
        row: Dict[str, Any], class_name: Optional[str], color: Optional[str]
    ) -> Dict[str, Any]:
        """Blend visual similarity with the text signal, then add attribute bonuses."""
        image_similarity = float(row.get("image_similarity") or 0.0)
        text_similarity = row.get("text_similarity")

        score = image_similarity
        if text_similarity is not None:
            weight = config.match_text_weight
            score = (1 - weight) * image_similarity + weight * float(text_similarity)

        same_class = bool(class_name) and row.get("class_name") == class_name
        same_color = color_agreement(color, row.get("dominant_color"))
        if same_class:
            score += config.match_same_class_bonus
        if same_color:
            score += config.match_same_color_bonus

        match = dict(row)
        match["image_similarity"] = round(image_similarity, 4)
        match["text_similarity"] = round(float(text_similarity), 4) if text_similarity else None
        match["same_class"] = same_class
        match["same_color"] = same_color
        match["score"] = round(min(1.0, score), 4)
        return match

    async def _persist_suggestions(self, lost_id: UUID, matches: List[Dict[str, Any]]) -> None:
        """Keep the suggested shortlist so operators can review it later."""
        try:
            await self.db_manager.execute_many(
                """
                INSERT INTO match_result (lost_id, found_id, score, method)
                VALUES ($1, $2, $3, 'clip_cosine')
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
        page: int = 1,
        per_page: int = 20,
    ) -> Dict[str, Any]:
        conditions: List[str] = []
        params: List[Any] = []
        if status:
            params.append(status)
            conditions.append(f"f.status = ${len(params)}")
        if camera_id:
            params.append(camera_id)
            conditions.append(f"f.camera_id = ${len(params)}")
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

    async def get_found_crop(self, found_id: UUID) -> Optional[bytes]:
        row = await self.db_manager.execute_query(
            "SELECT crop_jpeg FROM found_item WHERE found_id = $1", (found_id,), fetch_one=True
        )
        return bytes(row["crop_jpeg"]) if row and row["crop_jpeg"] else None


matching_service = MatchingService()
