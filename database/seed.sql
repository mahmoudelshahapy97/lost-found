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
     '11111111-1111-4111-8111-000000000001', '4101', 'bag', 0.91,
     '{"x1": 612, "y1": 388, "x2": 742, "y2": 546}'::jsonb,
     4088, NOW() - INTERVAL '2 hours 6 minutes', NOW() - INTERVAL '2 hours 1 minute',
     NOW() - INTERVAL '2 hours', 'OPEN'),

    ('22222222-2222-4222-8222-000000000002',
     '11111111-1111-4111-8111-000000000001', '4137', 'umbrella', 0.87,
     '{"x1": 240, "y1": 402, "x2": 396, "y2": 610}'::jsonb,
     NULL, NOW() - INTERVAL '5 hours 4 minutes', NOW() - INTERVAL '5 hours 1 minute',
     NOW() - INTERVAL '5 hours', 'ACKNOWLEDGED'),

    ('22222222-2222-4222-8222-000000000003',
     '11111111-1111-4111-8111-000000000002', '2210', 'wallet', 0.78,
     '{"x1": 880, "y1": 470, "x2": 964, "y2": 552}'::jsonb,
     2199, NOW() - INTERVAL '1 day 3 hours', NOW() - INTERVAL '1 day 2 hours 56 minutes',
     NOW() - INTERVAL '1 day 2 hours 55 minutes', 'RESOLVED'),

    ('22222222-2222-4222-8222-000000000004',
     '11111111-1111-4111-8111-000000000003', '981', 'bag', 0.66,
     '{"x1": 1020, "y1": 300, "x2": 1128, "y2": 428}'::jsonb,
     NULL, NOW() - INTERVAL '2 days 1 hour', NOW() - INTERVAL '2 days 58 minutes',
     NOW() - INTERVAL '2 days', 'FALSE_POSITIVE'),

    ('22222222-2222-4222-8222-000000000005',
     '11111111-1111-4111-8111-000000000003', '1043', 'umbrella', 0.94,
     '{"x1": 455, "y1": 355, "x2": 640, "y2": 590}'::jsonb,
     1030, NOW() - INTERVAL '3 days 2 hours', NOW() - INTERVAL '3 days 1 hour 55 minutes',
     NOW() - INTERVAL '3 days', 'OPEN'),

    ('22222222-2222-4222-8222-000000000006',
     '11111111-1111-4111-8111-000000000004', '77', 'wallet', 0.72,
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
    found_id, event_id, camera_id, class_name, dominant_color, found_at, status
) VALUES
    ('33333333-3333-4333-8333-000000000001',
     '22222222-2222-4222-8222-000000000001', '11111111-1111-4111-8111-000000000001',
     'bag', 'black', NOW() - INTERVAL '2 hours', 'UNCLAIMED'),

    ('33333333-3333-4333-8333-000000000002',
     '22222222-2222-4222-8222-000000000002', '11111111-1111-4111-8111-000000000001',
     'umbrella', 'navy', NOW() - INTERVAL '5 hours', 'UNCLAIMED'),

    ('33333333-3333-4333-8333-000000000003',
     '22222222-2222-4222-8222-000000000003', '11111111-1111-4111-8111-000000000002',
     'wallet', 'brown', NOW() - INTERVAL '1 day 2 hours 55 minutes',
     'CLAIMED'),

    ('33333333-3333-4333-8333-000000000004',
     '22222222-2222-4222-8222-000000000004', '11111111-1111-4111-8111-000000000003',
     'bag', 'grey', NOW() - INTERVAL '2 days', 'DISCARDED'),

    ('33333333-3333-4333-8333-000000000005',
     '22222222-2222-4222-8222-000000000005', '11111111-1111-4111-8111-000000000003',
     'umbrella', 'red', NOW() - INTERVAL '3 days', 'UNCLAIMED'),

    ('33333333-3333-4333-8333-000000000006',
     '22222222-2222-4222-8222-000000000006', '11111111-1111-4111-8111-000000000004',
     'wallet', 'black', NOW() - INTERVAL '32 minutes', 'UNCLAIMED')
ON CONFLICT (found_id) DO NOTHING;

-- =============================================================================
-- LOST ITEMS
-- =============================================================================
-- The first two share an object type and colour with a specific found item, so
-- GET /lost-items/{id}/matches ranks it first straight away.
INSERT INTO lost_item (
    lost_id, reporter_name, reporter_email, description, class_name, dominant_color,
    lost_after, reported_at, status
) VALUES
    ('44444444-4444-4444-8444-000000000001',
     'Layla Hassan', 'layla.hassan@example.com',
     'Black leather bag with a front zip pocket and a red keyring',
     'bag', 'black',
     -- Same type and colour as found item ...0001 (black bag).
     NOW() - INTERVAL '3 hours', NOW() - INTERVAL '1 hour 30 minutes', 'OPEN'),

    ('44444444-4444-4444-8444-000000000002',
     'Omar Farouk', 'omar.farouk@example.com',
     'Large red golf umbrella, wooden handle, strap still fastened',
     'umbrella', 'red',
     -- Same type and colour as found item ...0005 (red umbrella).
     NOW() - INTERVAL '4 days', NOW() - INTERVAL '2 days 20 hours', 'OPEN'),

    ('44444444-4444-4444-8444-000000000003',
     'Nour El Sayed', 'nour.elsayed@example.com',
     'Brown leather wallet with gold clasp',
     'wallet', 'brown',
     NOW() - INTERVAL '2 days', NOW() - INTERVAL '1 day 1 hour', 'RESOLVED'),

    ('44444444-4444-4444-8444-000000000004',
     'Sara Mahmoud', NULL,
     'Small navy folding umbrella, no photo available',
     'umbrella', NULL,
     NULL, NOW() - INTERVAL '25 minutes', 'OPEN')
ON CONFLICT (lost_id) DO NOTHING;

-- =============================================================================
-- MATCHES
-- =============================================================================
-- The brown wallet was reunited with its owner: a confirmed pairing, which is
-- why lost item ...0003 is RESOLVED and found item ...0003 is CLAIMED above.
INSERT INTO match_result (match_id, lost_id, found_id, score, method, confirmed, created_at) VALUES
    ('55555555-5555-4555-8555-000000000001',
     '44444444-4444-4444-8444-000000000003', '33333333-3333-4333-8333-000000000003',
     0.9420, 'operator_confirmed', TRUE, NOW() - INTERVAL '1 day'),

    -- An unconfirmed suggestion, as matching_service._persist_suggestions() writes them.
    ('55555555-5555-4555-8555-000000000002',
     '44444444-4444-4444-8444-000000000001', '33333333-3333-4333-8333-000000000001',
     0.8130, 'rule_based', FALSE, NOW() - INTERVAL '1 hour')
ON CONFLICT (lost_id, found_id) DO NOTHING;

COMMIT;
