# app/services/analytics_service.py
"""Windowed aggregates behind the Analytics page.

These are the reporting queries from database/queries.sql section 6, narrowed
to a time window and optionally one camera. Time buckets are cut in the
viewer's timezone: "busiest hour" is only useful in the hours the operator
actually lives in, and a UTC heatmap is off by the local offset.
"""

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import asyncpg

from app.core.config import config
from app.core.database import db_manager

logger = logging.getLogger(__name__)


HISTOGRAM_BUCKETS = 10
LATEST_EVENTS = 50


def _num(value: Any) -> Optional[float]:
    """numeric/Decimal and double alike, as a plain float (or None)."""
    return float(value) if value is not None else None


def _pct(part: int, whole: int) -> Optional[float]:
    return round(100.0 * part / whole, 1) if whole else None


class AnalyticsService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    async def _window(self, days: int, tz: str) -> Dict[str, Any]:
        """The bucket grid, computed by Postgres so its tz database is the one used.

        One day is the last 24 hourly buckets; anything longer is ``days`` daily
        buckets ending with today. Both are aligned to bucket boundaries in
        ``tz``, so the first bucket is never a partial one.
        """
        bucket = "hour" if days == 1 else "day"
        step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
        count = 24 if bucket == "hour" else days
        try:
            row = await self.db_manager.execute_query(
                """
                WITH t AS (SELECT date_trunc($1, NOW() AT TIME ZONE $2) AS end_local)
                SELECT end_local,
                       end_local - $3::interval                    AS start_local,
                       (end_local - $3::interval) AT TIME ZONE $2  AS start_at,
                       NOW()                                       AS now
                FROM t
                """,
                (bucket, tz, step * (count - 1)),
                fetch_one=True,
            )
        except asyncpg.exceptions.InvalidParameterValueError as e:
            # "time zone ... not recognized" - the caller's input, not our fault.
            raise ValueError(f"Unknown timezone: {tz}") from e
        return {"bucket": bucket, "step": step, **row}

    async def summary(
        self, days: int = 7, camera_id: Optional[UUID] = None, tz: str = "UTC"
    ) -> Dict[str, Any]:
        window = await self._window(days, tz)
        start_at = window["start_at"]

        # $1 is always the window start, $2 the camera when one is given.
        base: Tuple[Any, ...] = (start_at, camera_id) if camera_id else (start_at,)
        n = len(base)
        event_where = "e.abandoned_at >= $1" + (" AND e.camera_id = $2" if camera_id else "")
        found_camera = " AND f.camera_id = $2" if camera_id else ""

        totals = await self.db_manager.execute_query(
            f"""
            SELECT COUNT(*)                                          AS events,
                   COUNT(*) FILTER (WHERE status = 'OPEN')           AS open,
                   COUNT(*) FILTER (WHERE status = 'FALSE_POSITIVE') AS false_positives,
                   AVG(EXTRACT(EPOCH FROM (abandoned_at - static_since)))
                       FILTER (WHERE static_since IS NOT NULL)       AS avg_unattended_s
            FROM abandoned_event e
            WHERE {event_where}
            """,
            base,
            fetch_one=True,
        )

        found = await self.db_manager.execute_query(
            f"SELECT COUNT(*) AS total FROM found_item f WHERE f.found_at >= $1{found_camera}",
            base,
            fetch_one=True,
        )

        # lost_item has no camera: a report describes an object, not a place.
        lost = await self.db_manager.execute_query(
            "SELECT COUNT(*) AS total FROM lost_item WHERE reported_at >= $1",
            (start_at,),
            fetch_one=True,
        )

        reunions = await self.db_manager.execute_query(
            f"""
            SELECT COUNT(*) AS reunions,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY EXTRACT(EPOCH FROM (m.created_at - l.reported_at))
                   )                                                    AS median_s,
                   MIN(EXTRACT(EPOCH FROM (m.created_at - l.reported_at))) AS fastest_s
            FROM match_result m
            JOIN lost_item l  ON l.lost_id  = m.lost_id
            JOIN found_item f ON f.found_id = m.found_id
            WHERE m.confirmed AND m.created_at >= $1{found_camera}
            """,
            base,
            fetch_one=True,
        )

        # generate_series supplies the empty buckets a GROUP BY would drop.
        series_rows = await self.db_manager.execute_query(
            f"""
            WITH buckets AS (
                SELECT generate_series(${n + 1}::timestamp, ${n + 2}::timestamp, ${n + 3}::interval)
                       AS bucket_start
            ),
            ev AS (
                SELECT date_trunc(${n + 4}, e.abandoned_at AT TIME ZONE ${n + 5}) AS bucket_start,
                       e.status
                FROM abandoned_event e
                WHERE {event_where}
            )
            SELECT b.bucket_start,
                   COUNT(ev.status)                                     AS events,
                   COUNT(*) FILTER (WHERE ev.status = 'FALSE_POSITIVE') AS false_positives,
                   COUNT(*) FILTER (WHERE ev.status = 'RESOLVED')       AS resolved
            FROM buckets b
            LEFT JOIN ev ON ev.bucket_start = b.bucket_start
            GROUP BY b.bucket_start
            ORDER BY b.bucket_start
            """,
            base
            + (window["start_local"], window["end_local"], window["step"], window["bucket"], tz),
            fetch_all=True,
        )

        heatmap_rows = await self.db_manager.execute_query(
            f"""
            SELECT EXTRACT(DOW  FROM e.abandoned_at AT TIME ZONE ${n + 1})::int AS weekday,
                   EXTRACT(HOUR FROM e.abandoned_at AT TIME ZONE ${n + 1})::int AS hour,
                   COUNT(*)                                                   AS events
            FROM abandoned_event e
            WHERE {event_where}
            GROUP BY weekday, hour
            ORDER BY weekday, hour
            """,
            base + (tz,),
            fetch_all=True,
        )

        camera_rows = await self.db_manager.execute_query(
            f"""
            SELECT e.camera_id,
                   c.name                                              AS camera_name,
                   c.location,
                   COUNT(*)                                            AS events,
                   COUNT(*) FILTER (WHERE e.status = 'OPEN')           AS open,
                   COUNT(*) FILTER (WHERE e.status = 'FALSE_POSITIVE') AS false_positives,
                   AVG(EXTRACT(EPOCH FROM (e.abandoned_at - e.static_since)))
                       FILTER (WHERE e.static_since IS NOT NULL)       AS avg_unattended_s
            FROM abandoned_event e
            LEFT JOIN camera c ON c.camera_id = e.camera_id
            WHERE {event_where}
            GROUP BY e.camera_id, c.name, c.location
            ORDER BY events DESC, camera_name
            """,
            base,
            fetch_all=True,
        )

        class_rows = await self.db_manager.execute_query(
            f"""
            SELECT e.class_name,
                   COUNT(*)                                            AS events,
                   AVG(e.confidence)                                   AS avg_confidence,
                   COUNT(*) FILTER (WHERE e.status = 'FALSE_POSITIVE') AS false_positives
            FROM abandoned_event e
            WHERE {event_where}
            GROUP BY e.class_name
            ORDER BY events DESC, e.class_name
            """,
            base,
            fetch_all=True,
        )

        events = totals["events"]
        kpis = {
            "events": events,
            "open": totals["open"],
            "false_positives": totals["false_positives"],
            "false_positive_pct": _pct(totals["false_positives"], events),
            "found_items": found["total"],
            "lost_reports": lost["total"],
            "reunions": reunions["reunions"],
            "median_reunite_s": _num(reunions["median_s"]),
            "fastest_reunite_s": _num(reunions["fastest_s"]),
            "avg_unattended_s": _num(totals["avg_unattended_s"]),
        }

        return {
            "window": {
                "start": start_at,
                "end": window["now"],
                "bucket": window["bucket"],
                "tz": tz,
            },
            "kpis": kpis,
            # Naive local timestamps: they are wall-clock times in ``tz``.
            "series": [
                {
                    "bucket_start": row["bucket_start"].isoformat(),
                    "events": row["events"],
                    "false_positives": row["false_positives"],
                    "resolved": row["resolved"],
                }
                for row in series_rows
            ],
            "heatmap": heatmap_rows,
            "by_camera": [self._camera_row(row) for row in camera_rows],
            "by_class": [
                {**row, "avg_confidence": _num(row["avg_confidence"])} for row in class_rows
            ],
            "funnel": {
                "events_detected": events,
                "items_harvested": kpis["found_items"],
                "reports_filed": kpis["lost_reports"],
                "reunions": kpis["reunions"],
            },
        }

    async def confidence_audit(
        self, days: int = 7, camera_id: Optional[UUID] = None, tz: str = "UTC"
    ) -> Dict[str, Any]:
        """Model accuracy & confidence audit (InsightEye evidence_analytics.confidence_audit).

        How sure the detector was about the alerts in the window: totals, a
        10-bucket histogram over [0, 1], the spread per camera and the latest
        scored alerts. Operator verdicts stand in for ground truth, so each part
        also counts false positives. ``low_confidence`` counts alerts within 0.1
        of the detector threshold, the ones most worth a second look.
        """
        window = await self._window(days, tz)
        start_at = window["start_at"]
        threshold = float(config.yolo_confidence)
        low_cutoff = round(min(1.0, threshold + 0.1), 4)

        base: Tuple[Any, ...] = (start_at, camera_id) if camera_id else (start_at,)
        n = len(base)
        where = "e.abandoned_at >= $1" + (" AND e.camera_id = $2" if camera_id else "")
        scored = f"{where} AND e.confidence IS NOT NULL"
        low = f"${n + 1}"

        totals = await self.db_manager.execute_query(
            f"""
            SELECT COUNT(*)                                                  AS events,
                   COUNT(e.confidence)                                       AS scored_events,
                   AVG(e.confidence)::float                                  AS avg_confidence,
                   MIN(e.confidence)::float                                  AS min_confidence,
                   MAX(e.confidence)::float                                  AS max_confidence,
                   COUNT(*) FILTER (WHERE e.confidence < {low})              AS low_confidence,
                   COUNT(*) FILTER (WHERE e.status = 'ACKNOWLEDGED')         AS acknowledged,
                   COUNT(*) FILTER (WHERE e.status = 'RESOLVED')             AS resolved,
                   COUNT(*) FILTER (WHERE e.status = 'FALSE_POSITIVE')       AS false_positives,
                   AVG(e.confidence) FILTER (WHERE e.status = 'RESOLVED')::float
                                                                             AS avg_confidence_resolved,
                   AVG(e.confidence) FILTER (WHERE e.status = 'FALSE_POSITIVE')::float
                                                                             AS avg_confidence_false_positive
            FROM abandoned_event e
            WHERE {where}
            """,
            base + (low_cutoff,),
            fetch_one=True,
        )

        bucket_rows = await self.db_manager.execute_query(
            f"""
            SELECT LEAST(width_bucket(e.confidence, 0, 1, {HISTOGRAM_BUCKETS}), {HISTOGRAM_BUCKETS})
                       AS b,
                   COUNT(*)                                            AS count,
                   COUNT(*) FILTER (WHERE e.status = 'FALSE_POSITIVE') AS false_positives
            FROM abandoned_event e
            WHERE {scored}
            GROUP BY 1
            """,
            base,
            fetch_all=True,
        )
        by_bucket = {row["b"]: row for row in bucket_rows}
        step = 1 / HISTOGRAM_BUCKETS
        histogram = [
            {
                "bucket": f"{(i - 1) * step:.1f}-{i * step:.1f}",
                "min": round((i - 1) * step, 2),
                "max": round(i * step, 2),
                "count": by_bucket[i]["count"] if i in by_bucket else 0,
                "false_positives": by_bucket[i]["false_positives"] if i in by_bucket else 0,
            }
            for i in range(1, HISTOGRAM_BUCKETS + 1)
        ]

        camera_rows = await self.db_manager.execute_query(
            f"""
            SELECT e.camera_id,
                   c.name                                              AS camera_name,
                   COUNT(*)                                            AS events,
                   AVG(e.confidence)::float                            AS avg_confidence,
                   MIN(e.confidence)::float                            AS min_confidence,
                   MAX(e.confidence)::float                            AS max_confidence,
                   COUNT(*) FILTER (WHERE e.confidence < {low})        AS low_confidence,
                   COUNT(*) FILTER (WHERE e.status = 'FALSE_POSITIVE') AS false_positives
            FROM abandoned_event e
            LEFT JOIN camera c ON c.camera_id = e.camera_id
            WHERE {scored}
            GROUP BY e.camera_id, c.name
            ORDER BY avg_confidence DESC NULLS LAST, camera_name
            """,
            base + (low_cutoff,),
            fetch_all=True,
        )

        latest = await self.db_manager.execute_query(
            f"""
            SELECT e.event_id, e.abandoned_at, e.camera_id, c.name AS camera_name,
                   e.class_name, e.confidence::float AS confidence, e.status
            FROM abandoned_event e
            LEFT JOIN camera c ON c.camera_id = e.camera_id
            WHERE {scored}
            ORDER BY e.abandoned_at DESC, e.event_id DESC
            LIMIT {LATEST_EVENTS}
            """,
            base,
            fetch_all=True,
        )

        scored_events = totals["scored_events"]
        return {
            "window": {"start": start_at, "end": window["now"], "tz": tz},
            "summary": {
                **totals,
                "low_confidence_pct": _pct(totals["low_confidence"], scored_events),
                "false_positive_pct": _pct(totals["false_positives"], totals["events"]),
                "threshold": threshold,
                "low_confidence_cutoff": low_cutoff,
            },
            "histogram": histogram,
            "by_camera": [
                {**row, "false_positive_pct": _pct(row["false_positives"], row["events"])}
                for row in camera_rows
            ],
            "latest": latest,
        }

    @staticmethod
    def _camera_row(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            **row,
            "false_positive_pct": _pct(row["false_positives"], row["events"]),
            "avg_unattended_s": _num(row["avg_unattended_s"]),
        }


analytics_service = AnalyticsService()
