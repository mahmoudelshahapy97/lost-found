-- ---------------------------------------------------------------------------
-- InsightEye — Lost & Found : demo data
--
-- Development only. Deliberately NOT mounted into docker-entrypoint-initdb.d,
-- so a fresh stack comes up empty and nobody ships fabricated incident history
-- to a real deployment. Load it when you want a populated console to work
-- against, with no cameras and no ML stack running:
--
--   docker compose exec -T postgres psql -U lostfound -d lostfound_db < database/seed.sql
--
-- Re-runnable: every row carries a fixed UUID and every insert is
-- ON CONFLICT DO NOTHING, so a second load leaves the same data rather than
-- doubling it.
-- ---------------------------------------------------------------------------

BEGIN;

-- =============================================================================
-- DEMO EMBEDDING HELPERS
-- =============================================================================
-- Real embeddings come from CLIP at ingest time. Seeding cannot run CLIP, so
-- these build reproducible stand-ins: demo_embedding() is a deterministic random
-- vector, demo_embedding_near() jitters an existing one so a lost report lands
-- close enough to its found item for the cosine search to rank it first.
-- Both are dropped at the end of this file.

CREATE OR REPLACE FUNCTION demo_embedding(p_seed DOUBLE PRECISION)
RETURNS VECTOR
LANGUAGE plpgsql
AS $fn$
DECLARE
    literal TEXT;
BEGIN
    PERFORM setseed(p_seed);
    SELECT '[' || string_agg(ROUND((random() * 2 - 1)::NUMERIC, 6)::TEXT, ',') || ']'
      INTO literal
      FROM generate_series(1, 512);
    RETURN literal::VECTOR;
END;
$fn$;

CREATE OR REPLACE FUNCTION demo_embedding_near(
    p_base  VECTOR,
    p_seed  DOUBLE PRECISION,
    p_noise DOUBLE PRECISION DEFAULT 0.35
)
RETURNS VECTOR
LANGUAGE plpgsql
AS $fn$
DECLARE
    base    REAL[];
    literal TEXT;
BEGIN
    PERFORM setseed(p_seed);
    base := p_base::REAL[];
    SELECT '[' || string_agg(
               ROUND((base[i] + p_noise * (random() * 2 - 1))::NUMERIC, 6)::TEXT, ',' ORDER BY i
           ) || ']'
      INTO literal
      FROM generate_series(1, array_length(base, 1)) AS i;
    RETURN literal::VECTOR;
END;
$fn$;

-- =============================================================================
-- CAMERAS
-- =============================================================================
-- All four point at the mediamtx sidecar from docker-compose.yml, which is a
-- real RTSP URL only while that profile is up:
--   docker compose --profile testing up -d mediamtx
-- Only the first is enabled; the rest are placeholders so the console has a
-- realistic camera list without four workers competing for the CPU.
INSERT INTO camera (camera_id, name, rtsp_url, location, enabled, roi, settings) VALUES
    ('11111111-1111-4111-8111-000000000001',
     'Terminal 1 - Arrivals Hall',
     'rtsp://mediamtx:8554/lostfound',
     'Terminal 1, Ground Floor',
     TRUE,
     NULL,
     '{"abandon_seconds": 30}'::jsonb),

    ('11111111-1111-4111-8111-000000000002',
     'Terminal 1 - Baggage Belt 3',
     'rtsp://mediamtx:8554/lostfound',
     'Terminal 1, Baggage Claim',
     FALSE,
     -- Ignore the belt itself; only luggage left on the concourse counts.
     '[[120,340],[1180,340],[1180,700],[120,700]]'::jsonb,
     '{"abandon_seconds": 45, "owner_distance_px": 220}'::jsonb),

    ('11111111-1111-4111-8111-000000000003',
     'Metro - North Concourse',
     'rtsp://mediamtx:8554/lostfound',
     'Metro Station, North Entrance',
     FALSE,
     NULL,
     '{"abandon_seconds": 20, "abandon_distance_px": 300}'::jsonb),

    ('11111111-1111-4111-8111-000000000004',
     'Mall - Food Court',
     'rtsp://mediamtx:8554/lostfound',
     'Level 2, Food Court',
     FALSE,
     NULL,
     '{}'::jsonb)
ON CONFLICT (camera_id) DO NOTHING;

-- =============================================================================
-- ABANDONED EVENTS
-- =============================================================================
-- Spread across the last few days and across every status so the events list,
-- the status filters and the dashboard counters all have something to show.
INSERT INTO abandoned_event (
    event_id, camera_id, track_key, class_name, confidence, bbox,
    owner_track_id, first_seen_at, static_since, abandoned_at, status
) VALUES
    ('22222222-2222-4222-8222-000000000001',
     '11111111-1111-4111-8111-000000000001', '4101', 'backpack', 0.91,
     '{"x1": 612, "y1": 388, "x2": 742, "y2": 546}'::jsonb,
     4088, NOW() - INTERVAL '2 hours 6 minutes', NOW() - INTERVAL '2 hours 1 minute',
     NOW() - INTERVAL '2 hours', 'OPEN'),

    ('22222222-2222-4222-8222-000000000002',
     '11111111-1111-4111-8111-000000000001', '4137', 'suitcase', 0.87,
     '{"x1": 240, "y1": 402, "x2": 396, "y2": 610}'::jsonb,
     NULL, NOW() - INTERVAL '5 hours 4 minutes', NOW() - INTERVAL '5 hours 1 minute',
     NOW() - INTERVAL '5 hours', 'ACKNOWLEDGED'),

    ('22222222-2222-4222-8222-000000000003',
     '11111111-1111-4111-8111-000000000002', '2210', 'handbag', 0.78,
     '{"x1": 880, "y1": 470, "x2": 964, "y2": 552}'::jsonb,
     2199, NOW() - INTERVAL '1 day 3 hours', NOW() - INTERVAL '1 day 2 hours 56 minutes',
     NOW() - INTERVAL '1 day 2 hours 55 minutes', 'RESOLVED'),

    ('22222222-2222-4222-8222-000000000004',
     '11111111-1111-4111-8111-000000000003', '981', 'backpack', 0.66,
     '{"x1": 1020, "y1": 300, "x2": 1128, "y2": 428}'::jsonb,
     NULL, NOW() - INTERVAL '2 days 1 hour', NOW() - INTERVAL '2 days 58 minutes',
     NOW() - INTERVAL '2 days', 'FALSE_POSITIVE'),

    ('22222222-2222-4222-8222-000000000005',
     '11111111-1111-4111-8111-000000000003', '1043', 'suitcase', 0.94,
     '{"x1": 455, "y1": 355, "x2": 640, "y2": 590}'::jsonb,
     1030, NOW() - INTERVAL '3 days 2 hours', NOW() - INTERVAL '3 days 1 hour 55 minutes',
     NOW() - INTERVAL '3 days', 'OPEN'),

    ('22222222-2222-4222-8222-000000000006',
     '11111111-1111-4111-8111-000000000004', '77', 'handbag', 0.72,
     '{"x1": 300, "y1": 250, "x2": 388, "y2": 340}'::jsonb,
     70, NOW() - INTERVAL '40 minutes', NOW() - INTERVAL '35 minutes',
     NOW() - INTERVAL '32 minutes', 'OPEN')
ON CONFLICT (camera_id, track_key) DO NOTHING;

-- =============================================================================
-- FOUND ITEMS
-- =============================================================================
-- One per event, exactly as event_service._create_found_item() would write it.
-- The event that was marked FALSE_POSITIVE is DISCARDED; the RESOLVED one is
-- CLAIMED, which also keeps it out of the matching candidate pool.
INSERT INTO found_item (
    found_id, event_id, camera_id, class_name, dominant_color, embedding, found_at, status
) VALUES
    ('33333333-3333-4333-8333-000000000001',
     '22222222-2222-4222-8222-000000000001', '11111111-1111-4111-8111-000000000001',
     'backpack', 'black', demo_embedding(0.11), NOW() - INTERVAL '2 hours', 'UNCLAIMED'),

    ('33333333-3333-4333-8333-000000000002',
     '22222222-2222-4222-8222-000000000002', '11111111-1111-4111-8111-000000000001',
     'suitcase', 'navy', demo_embedding(0.22), NOW() - INTERVAL '5 hours', 'UNCLAIMED'),

    ('33333333-3333-4333-8333-000000000003',
     '22222222-2222-4222-8222-000000000003', '11111111-1111-4111-8111-000000000002',
     'handbag', 'brown', demo_embedding(0.33), NOW() - INTERVAL '1 day 2 hours 55 minutes',
     'CLAIMED'),

    ('33333333-3333-4333-8333-000000000004',
     '22222222-2222-4222-8222-000000000004', '11111111-1111-4111-8111-000000000003',
     'backpack', 'grey', demo_embedding(0.44), NOW() - INTERVAL '2 days', 'DISCARDED'),

    ('33333333-3333-4333-8333-000000000005',
     '22222222-2222-4222-8222-000000000005', '11111111-1111-4111-8111-000000000003',
     'suitcase', 'red', demo_embedding(0.55), NOW() - INTERVAL '3 days', 'UNCLAIMED'),

    ('33333333-3333-4333-8333-000000000006',
     '22222222-2222-4222-8222-000000000006', '11111111-1111-4111-8111-000000000004',
     'handbag', 'black', demo_embedding(0.66), NOW() - INTERVAL '32 minutes', 'UNCLAIMED')
ON CONFLICT (found_id) DO NOTHING;

-- =============================================================================
-- LOST ITEMS
-- =============================================================================
-- The first two are deliberately planted near a specific found item so that
-- GET /lost-items/{id}/matches returns a believable ranking straight away.
INSERT INTO lost_item (
    lost_id, reporter_name, reporter_email, description, class_name, dominant_color,
    embedding, text_embedding, lost_after, reported_at, status
) VALUES
    ('44444444-4444-4444-8444-000000000001',
     'Layla Hassan', 'layla.hassan@example.com',
     'Black leather backpack with a laptop sleeve and a red keyring',
     'backpack', 'black',
     -- Sits close to found item ...0001 (black backpack, same camera).
     demo_embedding_near(demo_embedding(0.11), 0.71, 0.30),
     demo_embedding(0.91),
     NOW() - INTERVAL '3 hours', NOW() - INTERVAL '1 hour 30 minutes', 'OPEN'),

    ('44444444-4444-4444-8444-000000000002',
     'Omar Farouk', 'omar.farouk@example.com',
     'Large red hard-shell suitcase, four wheels, airline tag still attached',
     'suitcase', 'red',
     -- Sits close to found item ...0005 (red suitcase).
     demo_embedding_near(demo_embedding(0.55), 0.72, 0.30),
     demo_embedding(0.92),
     NOW() - INTERVAL '4 days', NOW() - INTERVAL '2 days 20 hours', 'OPEN'),

    ('44444444-4444-4444-8444-000000000003',
     'Nour El Sayed', 'nour.elsayed@example.com',
     'Brown handbag with gold clasp',
     'handbag', 'brown',
     demo_embedding_near(demo_embedding(0.33), 0.73, 0.25),
     demo_embedding(0.93),
     NOW() - INTERVAL '2 days', NOW() - INTERVAL '1 day 1 hour', 'RESOLVED'),

    ('44444444-4444-4444-8444-000000000004',
     'Sara Mahmoud', NULL,
     'Small navy cabin bag, no photo available',
     'suitcase', NULL,
     NULL,                       -- description-only report: no image embedding
     demo_embedding(0.94),
     NULL, NOW() - INTERVAL '25 minutes', 'OPEN')
ON CONFLICT (lost_id) DO NOTHING;

-- =============================================================================
-- MATCHES
-- =============================================================================
-- The brown handbag was reunited with its owner: a confirmed pairing, which is
-- why lost item ...0003 is RESOLVED and found item ...0003 is CLAIMED above.
INSERT INTO match_result (match_id, lost_id, found_id, score, method, confirmed, created_at) VALUES
    ('55555555-5555-4555-8555-000000000001',
     '44444444-4444-4444-8444-000000000003', '33333333-3333-4333-8333-000000000003',
     0.9420, 'operator_confirmed', TRUE, NOW() - INTERVAL '1 day'),

    -- An unconfirmed suggestion, as matching_service._persist_suggestions() writes them.
    ('55555555-5555-4555-8555-000000000002',
     '44444444-4444-4444-8444-000000000001', '33333333-3333-4333-8333-000000000001',
     0.8130, 'clip_cosine', FALSE, NOW() - INTERVAL '1 hour')
ON CONFLICT (lost_id, found_id) DO NOTHING;

-- =============================================================================
-- CLEANUP
-- =============================================================================
DROP FUNCTION IF EXISTS demo_embedding_near(VECTOR, DOUBLE PRECISION, DOUBLE PRECISION);
DROP FUNCTION IF EXISTS demo_embedding(DOUBLE PRECISION);

COMMIT;
