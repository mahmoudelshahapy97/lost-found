-- ---------------------------------------------------------------------------
-- InsightEye — Lost & Found : queries
--
-- A reference, not a script. Each block is annotated with the endpoint or the
-- service function that issues it, so a statement can be pasted into psql and
-- run in isolation while working out why the API returned what it did.
--
-- Parameters use asyncpg's $1, $2 style, matching the source. Substitute real
-- values before running a block by hand.
--
--   psql -h 127.0.0.1 -p 5436 -U lostfound -d lostfound_db
--
-- Sections:
--   1. cameras       2. events        3. found items
--   4. lost items    5. matching      6. analytics and operations
-- ---------------------------------------------------------------------------

-- ==========================================================================
-- 1. CAMERAS
-- ==========================================================================
-- Camera CRUD. These are the statements app/services/camera_service.py issues,
-- kept here so they can be run by hand against the database when debugging.
-- Parameters use the asyncpg $n style.

-- :name create_camera
-- POST /api/v1/cameras
INSERT INTO camera (name, rtsp_url, location, enabled, roi, settings)
VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
RETURNING *;

-- :name get_camera
SELECT * FROM camera WHERE camera_id = $1;

-- :name get_camera_by_name
-- Guards the 409 on POST /api/v1/cameras; name carries a UNIQUE constraint.
SELECT * FROM camera WHERE name = $1;

-- :name list_cameras
SELECT * FROM camera ORDER BY created_at;

-- :name list_cameras_enabled_only
-- GET /api/v1/cameras?enabled_only=true, and what start_enabled_cameras() runs
-- at boot. Served by idx_camera_enabled.
SELECT * FROM camera WHERE enabled ORDER BY created_at;

-- :name update_camera
-- PATCH /api/v1/cameras/{camera_id}. The service builds the SET list from the
-- supplied fields only; this is the shape it produces for a full update.
UPDATE camera
SET name     = $1,
    rtsp_url = $2,
    location = $3,
    enabled  = $4,
    roi      = $5::jsonb,
    settings = $6::jsonb,
    updated_at = NOW()
WHERE camera_id = $7
RETURNING *;

-- :name toggle_camera
UPDATE camera SET enabled = $2, updated_at = NOW()
WHERE camera_id = $1
RETURNING camera_id, name, enabled;

-- :name delete_camera
-- Cascades to abandoned_event (and from there to found_item); found_item.camera_id
-- is ON DELETE SET NULL so orphaned crops stay searchable.
DELETE FROM camera WHERE camera_id = $1;

-- :name cameras_with_activity
-- Camera list enriched with its event counters - what the frontend camera table
-- shows next to each row.
SELECT c.camera_id,
       c.name,
       c.location,
       c.enabled,
       COUNT(e.event_id)                                   AS total_events,
       COUNT(e.event_id) FILTER (WHERE e.status = 'OPEN')  AS open_events,
       MAX(e.abandoned_at)                                 AS last_event_at
FROM camera c
LEFT JOIN abandoned_event e ON e.camera_id = c.camera_id
GROUP BY c.camera_id, c.name, c.location, c.enabled
ORDER BY c.created_at;

-- :name camera_effective_settings
-- The per-camera overrides merged over the defaults, mirroring
-- AbandonmentParams.from_settings(). Useful when an event fires late.
SELECT camera_id,
       name,
       COALESCE((settings ->> 'abandon_seconds')::REAL,     30.0)  AS abandon_seconds,
       COALESCE((settings ->> 'owner_distance_px')::REAL,   180.0) AS owner_distance_px,
       COALESCE((settings ->> 'abandon_distance_px')::REAL, 260.0) AS abandon_distance_px,
       COALESCE((settings ->> 'static_tolerance_px')::REAL, 25.0)  AS static_tolerance_px
FROM camera
ORDER BY name;

-- ==========================================================================
-- 2. EVENTS
-- ==========================================================================
-- Abandoned-object events: what app/services/event_service.py writes and reads.

-- :name record_event
-- Called by the camera worker the moment the state machine declares an object
-- abandoned. ON CONFLICT DO NOTHING on (camera_id, track_key) is what makes a
-- replayed track a no-op rather than a duplicate alert.
INSERT INTO abandoned_event (
    camera_id, track_key, class_name, confidence, bbox,
    owner_track_id, first_seen_at, static_since, abandoned_at, frame_jpeg
)
VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10)
ON CONFLICT (camera_id, track_key) DO NOTHING
RETURNING event_id, camera_id, track_key, class_name, confidence,
          bbox, owner_track_id, first_seen_at, abandoned_at, status;

-- :name list_events
-- GET /api/v1/events. The service appends only the filters that were supplied;
-- this is the fully-filtered form. frame_jpeg is joined in only when
-- include_frame=true, because a page of annotated frames is megabytes.
SELECT e.event_id, e.camera_id, c.name AS camera_name, e.track_key,
       e.class_name, e.confidence, e.bbox, e.owner_track_id,
       e.first_seen_at, e.abandoned_at, e.status,
       f.found_id, f.dominant_color
FROM abandoned_event e
LEFT JOIN camera c     ON c.camera_id = e.camera_id
LEFT JOIN found_item f ON f.event_id  = e.event_id
WHERE e.camera_id    = $1
  AND e.status       = $2
  AND e.class_name   = $3
  AND e.abandoned_at >= $4
  AND e.abandoned_at <= $5
ORDER BY e.abandoned_at DESC
LIMIT $6 OFFSET $7;

-- :name count_events
SELECT COUNT(*) AS total FROM abandoned_event e WHERE e.camera_id = $1;

-- :name get_event
-- GET /api/v1/events/{event_id}
SELECT e.*, c.name AS camera_name, f.found_id, f.dominant_color
FROM abandoned_event e
LEFT JOIN camera c     ON c.camera_id = e.camera_id
LEFT JOIN found_item f ON f.event_id  = e.event_id
WHERE e.event_id = $1;

-- :name get_event_frame
-- GET /api/v1/events/{event_id}/frame - streamed straight out as image/jpeg.
SELECT frame_jpeg FROM abandoned_event WHERE event_id = $1;

-- :name update_event_status
-- PATCH /api/v1/events/{event_id}/status
-- $1 in ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'FALSE_POSITIVE')
UPDATE abandoned_event SET status = $1
WHERE event_id = $2
RETURNING event_id, status;

-- :name event_stats
-- GET /api/v1/events/stats - the dashboard counters.
SELECT COUNT(*)                                                            AS total,
       COUNT(*) FILTER (WHERE status = 'OPEN')                             AS open,
       COUNT(*) FILTER (WHERE abandoned_at > NOW() - INTERVAL '24 hours')  AS last_24h,
       MAX(abandoned_at)                                                   AS last_event_at
FROM abandoned_event;

-- :name event_stats_by_camera
SELECT e.camera_id,
       c.name AS camera_name,
       COUNT(*)                                 AS total,
       COUNT(*) FILTER (WHERE e.status = 'OPEN') AS open,
       MAX(e.abandoned_at)                       AS last_event_at
FROM abandoned_event e
LEFT JOIN camera c ON c.camera_id = e.camera_id
GROUP BY e.camera_id, c.name
ORDER BY total DESC;

-- :name open_events_feed
-- Everything still awaiting an operator, newest first - the alert panel.
SELECT e.event_id, e.class_name, e.confidence, e.abandoned_at,
       c.name AS camera_name, c.location, f.found_id, f.dominant_color
FROM abandoned_event e
LEFT JOIN camera c     ON c.camera_id = e.camera_id
LEFT JOIN found_item f ON f.event_id  = e.event_id
WHERE e.status = 'OPEN'
ORDER BY e.abandoned_at DESC
LIMIT $1;

-- :name purge_old_frames
-- Housekeeping: frame_jpeg dominates table size. Dropping the blob on settled
-- events keeps the row (and its audit trail) while reclaiming the bytes.
UPDATE abandoned_event
SET frame_jpeg = NULL
WHERE frame_jpeg IS NOT NULL
  AND status IN ('RESOLVED', 'FALSE_POSITIVE')
  AND abandoned_at < NOW() - ($1 || ' days')::INTERVAL;

-- ==========================================================================
-- 3. FOUND ITEMS
-- ==========================================================================
-- The found gallery. Rows here are never typed in by hand: every one is derived
-- from an abandoned_event by event_service._create_found_item().

-- :name create_found_item
-- The embedding arrives as a pgvector text literal ('[0.1,0.2,...]'), hence the
-- ::text::vector double cast - asyncpg has no native codec for VECTOR.
INSERT INTO found_item (
    event_id, camera_id, class_name, dominant_color, crop_jpeg, embedding
)
VALUES ($1, $2, $3, $4, $5, $6::text::vector)
RETURNING found_id;

-- :name list_found_items
-- GET /api/v1/found-items
SELECT f.found_id, f.event_id, f.camera_id, c.name AS camera_name,
       f.class_name, f.dominant_color, f.found_at, f.status
FROM found_item f
LEFT JOIN camera c ON c.camera_id = f.camera_id
WHERE f.status    = $1
  AND f.camera_id = $2
ORDER BY f.found_at DESC
LIMIT $3 OFFSET $4;

-- :name count_found_items
SELECT COUNT(*) AS total FROM found_item f WHERE f.status = $1;

-- :name get_found_crop
-- GET /api/v1/found-items/{found_id}/crop
SELECT crop_jpeg FROM found_item WHERE found_id = $1;

-- :name mark_found_claimed
-- $1 in ('UNCLAIMED', 'CLAIMED', 'DISCARDED')
UPDATE found_item SET status = $1 WHERE found_id = $2
RETURNING found_id, status;

-- :name found_items_by_class
-- Gallery breakdown for the dashboard.
SELECT class_name,
       COUNT(*)                                        AS total,
       COUNT(*) FILTER (WHERE status = 'UNCLAIMED')    AS unclaimed,
       COUNT(*) FILTER (WHERE status = 'CLAIMED')      AS claimed,
       COUNT(*) FILTER (WHERE embedding IS NOT NULL)   AS searchable
FROM found_item
GROUP BY class_name
ORDER BY total DESC;

-- :name found_items_missing_embedding
-- Diagnostic. A crop with no embedding is invisible to matching - it means CLIP
-- was unavailable when the event fired, or no crop could be taken from the frame.
SELECT f.found_id, f.class_name, f.found_at, c.name AS camera_name,
       (f.crop_jpeg IS NOT NULL) AS has_crop
FROM found_item f
LEFT JOIN camera c ON c.camera_id = f.camera_id
WHERE f.embedding IS NULL
ORDER BY f.found_at DESC;

-- :name found_gallery_size
-- How much of the table is image bytes, which is what drives the disk footprint.
SELECT COUNT(*)                                        AS rows,
       pg_size_pretty(SUM(LENGTH(crop_jpeg))::BIGINT)  AS crop_bytes,
       pg_size_pretty(pg_total_relation_size('found_item')) AS total_size
FROM found_item;

-- ==========================================================================
-- 4. LOST ITEMS
-- ==========================================================================
-- Lost reports filed by people. A report may carry a photo, a description, or
-- both - which is why embedding and text_embedding are independently nullable.

-- :name create_lost_item
-- POST /api/v1/lost-items (multipart)
INSERT INTO lost_item (
    reporter_name, reporter_email, description, class_name, dominant_color,
    photo_jpeg, embedding, text_embedding, lost_after
)
VALUES ($1, $2, $3, $4, $5, $6, $7::text::vector, $8::text::vector, $9)
RETURNING lost_id, reporter_name, reporter_email, description, class_name,
          dominant_color, lost_after, reported_at, status;

-- :name get_lost_item
SELECT lost_id, reporter_name, reporter_email, description, class_name,
       dominant_color, lost_after, reported_at, status
FROM lost_item
WHERE lost_id = $1;

-- :name get_lost_item_with_photo
-- ?include_photo=true. The service base64-encodes photo_jpeg into the response.
SELECT lost_id, reporter_name, reporter_email, description, class_name,
       dominant_color, lost_after, reported_at, status, photo_jpeg
FROM lost_item
WHERE lost_id = $1;

-- :name get_lost_item_vectors
-- What find_matches_for_lost_item() loads before searching. The ::text casts
-- hand the vectors back as pgvector literals so they can be passed straight
-- back in as query parameters.
SELECT lost_id, class_name, dominant_color, lost_after,
       embedding::text      AS embedding,
       text_embedding::text AS text_embedding
FROM lost_item
WHERE lost_id = $1;

-- :name list_lost_items
-- GET /api/v1/lost-items
SELECT lost_id, reporter_name, reporter_email, description, class_name,
       dominant_color, lost_after, reported_at, status
FROM lost_item
WHERE status = $1
ORDER BY reported_at DESC
LIMIT $2 OFFSET $3;

-- :name count_lost_items
SELECT COUNT(*) AS total FROM lost_item WHERE status = $1;

-- :name update_lost_status
-- $1 in ('OPEN', 'MATCHED', 'RESOLVED', 'CLOSED')
UPDATE lost_item SET status = $1 WHERE lost_id = $2
RETURNING lost_id, status;

-- :name lost_items_with_match_counts
-- The queue an operator works through: open reports, with how many candidates
-- the last matching run left behind and the best score among them.
SELECT l.lost_id,
       l.reporter_name,
       l.description,
       l.class_name,
       l.dominant_color,
       l.reported_at,
       l.status,
       COUNT(m.match_id)                                AS suggestion_count,
       MAX(m.score)                                     AS best_score,
       BOOL_OR(m.confirmed)                             AS has_confirmed
FROM lost_item l
LEFT JOIN match_result m ON m.lost_id = l.lost_id
GROUP BY l.lost_id
ORDER BY l.reported_at DESC;

-- :name stale_open_reports
-- Reports nobody has resolved and that matching has never shortlisted. These
-- are the ones worth re-running a search on after new items arrive.
SELECT l.lost_id, l.reporter_name, l.reporter_email, l.description, l.reported_at
FROM lost_item l
WHERE l.status = 'OPEN'
  AND l.reported_at < NOW() - INTERVAL '7 days'
  AND NOT EXISTS (SELECT 1 FROM match_result m WHERE m.lost_id = l.lost_id)
ORDER BY l.reported_at;

-- ==========================================================================
-- 5. MATCHING
-- ==========================================================================
-- Vector search and the match_result bookkeeping around it.
--
-- <=> is pgvector's cosine DISTANCE, so similarity is 1 - (a <=> b). Ordering by
-- the raw distance (not by the similarity expression) is what lets the planner
-- use idx_found_embedding; wrapping it in 1 - (...) would force a sequential scan.

-- :name search_found_items
-- The candidate retrieval behind every match endpoint. $1 is the query vector,
-- $2 the optional text vector, $3 the optional "only items found after" bound,
-- $4 the over-fetch limit (top_k * 3) that leaves the Python rerank room to
-- reorder on class and colour bonuses.
SELECT f.found_id, f.event_id, f.camera_id, c.name AS camera_name,
       f.class_name, f.dominant_color, f.found_at, f.status,
       1 - (f.embedding <=> $1::text::vector) AS image_similarity,
       CASE WHEN $2::text IS NULL THEN NULL
            ELSE 1 - (f.embedding <=> $2::text::vector)
       END                                    AS text_similarity
FROM found_item f
LEFT JOIN camera c ON c.camera_id = f.camera_id
WHERE f.embedding IS NOT NULL
  AND f.status = 'UNCLAIMED'
  AND ($3::timestamptz IS NULL OR f.found_at >= $3)
ORDER BY f.embedding <=> $1::text::vector
LIMIT $4;

-- :name persist_suggestions
-- Written in one executemany() after a ranking run so operators can revisit the
-- shortlist. Re-running matching refreshes the score rather than duplicating.
INSERT INTO match_result (lost_id, found_id, score, method)
VALUES ($1, $2, $3, 'clip_cosine')
ON CONFLICT (lost_id, found_id)
DO UPDATE SET score = EXCLUDED.score, created_at = NOW();

-- :name confirm_match
-- POST /api/v1/matches/confirm, step 1 of 4.
INSERT INTO match_result (lost_id, found_id, score, method, confirmed)
VALUES ($1, $2, $3, 'operator_confirmed', TRUE)
ON CONFLICT (lost_id, found_id)
DO UPDATE SET confirmed = TRUE, method = 'operator_confirmed', created_at = NOW()
RETURNING match_id, lost_id, found_id, score, confirmed;

-- :name confirm_match_close_lost
UPDATE lost_item SET status = 'RESOLVED' WHERE lost_id = $1;

-- :name confirm_match_claim_found
UPDATE found_item SET status = 'CLAIMED' WHERE found_id = $1;

-- :name confirm_match_resolve_event
-- Closes the loop back to the alert the item came from.
UPDATE abandoned_event SET status = 'RESOLVED'
WHERE event_id = (SELECT event_id FROM found_item WHERE found_id = $1);

-- :name reject_match
-- DELETE /api/v1/matches - drops a suggestion so it stops resurfacing on the
-- next ranking run.
DELETE FROM match_result WHERE lost_id = $1 AND found_id = $2;

-- :name list_matches_for_lost
-- The stored shortlist, joined back to the gallery for display.
SELECT m.match_id, m.score, m.method, m.confirmed, m.created_at,
       f.found_id, f.class_name, f.dominant_color, f.found_at, f.status,
       c.name AS camera_name
FROM match_result m
JOIN found_item f  ON f.found_id  = m.found_id
LEFT JOIN camera c ON c.camera_id = f.camera_id
WHERE m.lost_id = $1
ORDER BY m.score DESC;

-- :name confirmed_reunions
-- The audit trail: every item actually returned to its owner, with how long the
-- round trip took.
SELECT m.match_id,
       m.score,
       m.created_at                              AS confirmed_at,
       l.reporter_name,
       l.reporter_email,
       l.description,
       f.class_name,
       f.dominant_color,
       f.found_at,
       c.name                                    AS camera_name,
       m.created_at - l.reported_at              AS time_to_reunite
FROM match_result m
JOIN lost_item l   ON l.lost_id   = m.lost_id
JOIN found_item f  ON f.found_id  = m.found_id
LEFT JOIN camera c ON c.camera_id = f.camera_id
WHERE m.confirmed
ORDER BY m.created_at DESC;

-- :name similar_found_items
-- "Is this the same bag we already have?" - dedupes the gallery by comparing a
-- found item against every other one.
SELECT f.found_id,
       f.class_name,
       f.dominant_color,
       f.found_at,
       1 - (f.embedding <=> (SELECT embedding FROM found_item WHERE found_id = $1))
           AS similarity
FROM found_item f
WHERE f.found_id <> $1
  AND f.embedding IS NOT NULL
ORDER BY f.embedding <=> (SELECT embedding FROM found_item WHERE found_id = $1)
LIMIT $2;

-- ==========================================================================
-- 6. ANALYTICS AND OPERATIONS
-- ==========================================================================
-- Reporting and operational queries. Nothing in the API calls these; they back
-- the dashboard charts and answer the questions that come up while running the
-- system ("why did nothing fire last night?").

-- :name events_per_day
-- Series for the dashboard chart. generate_series supplies the zero days, which
-- a plain GROUP BY would silently drop and leave the line graph misleading.
SELECT d.day::date                                            AS day,
       COUNT(e.event_id)                                      AS events,
       COUNT(e.event_id) FILTER (WHERE e.status = 'OPEN')     AS still_open
FROM generate_series(
         date_trunc('day', NOW()) - ($1::int - 1) * INTERVAL '1 day',
         date_trunc('day', NOW()),
         INTERVAL '1 day'
     ) AS d(day)
LEFT JOIN abandoned_event e
       ON e.abandoned_at >= d.day
      AND e.abandoned_at <  d.day + INTERVAL '1 day'
GROUP BY d.day
ORDER BY d.day;

-- :name events_by_hour_of_day
-- Where the alerts cluster - drives staffing, and exposes a camera pointed at a
-- spot that is only busy at one time of day.
SELECT EXTRACT(HOUR FROM abandoned_at)::int AS hour,
       COUNT(*)                             AS events
FROM abandoned_event
GROUP BY hour
ORDER BY hour;

-- :name class_distribution
SELECT class_name,
       COUNT(*)                                                  AS events,
       ROUND(AVG(confidence)::numeric, 3)                        AS avg_confidence,
       COUNT(*) FILTER (WHERE status = 'FALSE_POSITIVE')         AS false_positives
FROM abandoned_event
GROUP BY class_name
ORDER BY events DESC;

-- :name false_positive_rate_by_camera
-- A camera well above the others usually needs an ROI or a longer
-- abandon_seconds, not a model change.
SELECT c.name                                                          AS camera_name,
       c.location,
       COUNT(e.event_id)                                               AS events,
       COUNT(e.event_id) FILTER (WHERE e.status = 'FALSE_POSITIVE')     AS false_positives,
       ROUND(
           100.0 * COUNT(e.event_id) FILTER (WHERE e.status = 'FALSE_POSITIVE')
           / NULLIF(COUNT(e.event_id), 0), 1
       )                                                                AS false_positive_pct
FROM camera c
LEFT JOIN abandoned_event e ON e.camera_id = c.camera_id
GROUP BY c.camera_id, c.name, c.location
HAVING COUNT(e.event_id) > 0
ORDER BY false_positive_pct DESC NULLS LAST;

-- :name reunion_funnel
-- The number that matters: of everything the cameras picked up, how much got
-- back to a person.
SELECT (SELECT COUNT(*) FROM abandoned_event)                              AS events_detected,
       (SELECT COUNT(*) FROM found_item)                                   AS items_harvested,
       (SELECT COUNT(*) FROM found_item WHERE embedding IS NOT NULL)       AS items_searchable,
       (SELECT COUNT(*) FROM lost_item)                                    AS reports_filed,
       (SELECT COUNT(*) FROM match_result WHERE confirmed)                 AS reunions;

-- :name median_time_to_reunite
SELECT COUNT(*)                                                            AS reunions,
       PERCENTILE_CONT(0.5) WITHIN GROUP (
           ORDER BY EXTRACT(EPOCH FROM (m.created_at - l.reported_at))
       ) * INTERVAL '1 second'                                             AS median_time,
       MIN(m.created_at - l.reported_at)                                   AS fastest,
       MAX(m.created_at - l.reported_at)                                   AS slowest
FROM match_result m
JOIN lost_item l ON l.lost_id = m.lost_id
WHERE m.confirmed;

-- :name dwell_before_alert
-- How long objects sat still before the state machine gave up on the owner.
-- Consistently hitting the configured abandon_seconds exactly means the timer,
-- not the scene, is deciding - a hint the threshold is too low.
SELECT c.name                                              AS camera_name,
       COUNT(*)                                            AS events,
       ROUND(AVG(EXTRACT(EPOCH FROM (e.abandoned_at - e.static_since)))::numeric, 1)
                                                           AS avg_unattended_seconds,
       ROUND(MIN(EXTRACT(EPOCH FROM (e.abandoned_at - e.static_since)))::numeric, 1)
                                                           AS min_unattended_seconds
FROM abandoned_event e
LEFT JOIN camera c ON c.camera_id = e.camera_id
WHERE e.static_since IS NOT NULL
GROUP BY c.name
ORDER BY events DESC;

-- :name orphaned_events
-- Events with no found_item row: the harvest step failed, so the object will
-- never appear in the gallery and can never be matched.
SELECT e.event_id, e.class_name, e.abandoned_at, c.name AS camera_name
FROM abandoned_event e
LEFT JOIN found_item f ON f.event_id = e.event_id
LEFT JOIN camera c     ON c.camera_id = e.camera_id
WHERE f.found_id IS NULL
ORDER BY e.abandoned_at DESC;

-- :name storage_by_table
SELECT relname                                        AS table_name,
       n_live_tup                                     AS rows,
       pg_size_pretty(pg_total_relation_size(relid))  AS total_size
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;

-- :name index_usage
-- Verifies the HNSW index is actually being hit by the matching queries.
SELECT indexrelname AS index_name,
       relname      AS table_name,
       idx_scan     AS scans,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;
