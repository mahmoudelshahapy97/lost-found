-- ---------------------------------------------------------------------------
-- InsightEye — Lost & Found : schema
--
-- The source of truth for this feature's schema. Bind-mounted into
-- /docker-entrypoint-initdb.d/ by docker-compose.yml, so Postgres applies it
-- once on the first boot of an empty data volume. There is no Alembic here —
-- what this file says is what the database is.
--
-- Apply it by hand to a database that already exists:
--
--   psql -h 127.0.0.1 -p 5436 -U lostfound -d lostfound_db -f schema.sql
--
-- Safe to re-run: every object is created IF NOT EXISTS.
-- ---------------------------------------------------------------------------

BEGIN;

-- ---------------------------------------------------------------------------
-- Extensions. Both must exist before any table that depends on their types.
-- ---------------------------------------------------------------------------

-- pgvector supplies the VECTOR type and the <=> cosine-distance operator that
-- lost <-> found matching is built on.
CREATE EXTENSION IF NOT EXISTS vector;

-- gen_random_uuid() lives in pgcrypto on older servers; on PG13+ it is built
-- in. Creating it anyway keeps this file portable across both.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- camera — one watched RTSP source
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS camera (
    camera_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    -- rtsp:// URL, or a local video file path when exercising the pipeline
    -- without hardware.
    rtsp_url    TEXT NOT NULL,
    location    TEXT,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,

    -- Optional region of interest: [[x, y], ...] in pixel coordinates. Only
    -- detections inside it count, which is how a baggage belt is excluded from
    -- a camera that also watches the concourse.
    roi         JSONB,

    -- Per-camera overrides of the abandonment thresholds, e.g.
    -- {"abandon_seconds": 45}. An absent key means "inherit the global .env
    -- value", which is a different thing from 0.
    settings    JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Partial index: startup only ever asks for the enabled rows.
CREATE INDEX IF NOT EXISTS idx_camera_enabled ON camera (enabled) WHERE enabled;

-- ---------------------------------------------------------------------------
-- abandoned_event — one confirmed abandonment
--
-- A row appears only after the object has gone static, lost its owner, and
-- stayed unattended past ABANDON_SECONDS, so a bag set down while its owner
-- buys coffee never becomes an event.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS abandoned_event (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id       UUID NOT NULL REFERENCES camera (camera_id) ON DELETE CASCADE,
    track_key       TEXT NOT NULL,
    class_name      TEXT NOT NULL,
    confidence      REAL,
    bbox            JSONB NOT NULL,          -- {"x1":..,"y1":..,"x2":..,"y2":..}
    owner_track_id  INTEGER,
    first_seen_at   TIMESTAMPTZ NOT NULL,
    static_since    TIMESTAMPTZ,
    abandoned_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    frame_jpeg      BYTEA,                   -- annotated full frame
    status          TEXT NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'FALSE_POSITIVE')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Makes event recording idempotent: a worker replaying a track cannot
    -- raise a second alert for the same object.
    UNIQUE (camera_id, track_key)
);

CREATE INDEX IF NOT EXISTS idx_event_camera_time
    ON abandoned_event (camera_id, abandoned_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_status ON abandoned_event (status);
CREATE INDEX IF NOT EXISTS idx_event_class  ON abandoned_event (class_name);

-- ---------------------------------------------------------------------------
-- found_item — the searchable crop harvested from an event
--
-- Never typed in by hand. Every row is derived from an abandoned_event by
-- event_service._create_found_item(), which crops the object out of the frame
-- and embeds it with CLIP.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS found_item (
    found_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id        UUID REFERENCES abandoned_event (event_id) ON DELETE CASCADE,
    -- SET NULL rather than CASCADE: deleting a camera must not delete items
    -- that are still waiting to be claimed.
    camera_id       UUID REFERENCES camera (camera_id) ON DELETE SET NULL,
    class_name      TEXT NOT NULL,
    dominant_color  TEXT,
    crop_jpeg       BYTEA,
    embedding       VECTOR(512),             -- CLIP image embedding of the crop
    found_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          TEXT NOT NULL DEFAULT 'UNCLAIMED'
                    CHECK (status IN ('UNCLAIMED', 'CLAIMED', 'DISCARDED')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_found_status     ON found_item (status);
CREATE INDEX IF NOT EXISTS idx_found_class_time ON found_item (class_name, found_at DESC);

-- HNSW over cosine distance. This is what keeps candidate lookup off a
-- sequential scan of the whole gallery.
CREATE INDEX IF NOT EXISTS idx_found_embedding
    ON found_item USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- lost_item — what a person reported missing
--
-- A report may carry a photo, a description, or both, which is why the two
-- embedding columns are independently nullable.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lost_item (
    lost_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reporter_name   TEXT,
    reporter_email  TEXT,
    description     TEXT,
    class_name      TEXT,
    dominant_color  TEXT,
    photo_jpeg      BYTEA,
    embedding       VECTOR(512),        -- CLIP image embedding of the photo
    text_embedding  VECTOR(512),        -- CLIP text embedding of the description
    lost_after      TIMESTAMPTZ,        -- narrows the found-item search window
    reported_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          TEXT NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN', 'MATCHED', 'RESOLVED', 'CLOSED')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lost_status   ON lost_item (status);
CREATE INDEX IF NOT EXISTS idx_lost_reported ON lost_item (reported_at DESC);
CREATE INDEX IF NOT EXISTS idx_lost_embedding
    ON lost_item USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- match_result — one pairing between a lost report and a found item
--
-- Holds both machine suggestions (confirmed = FALSE, method = 'clip_cosine')
-- and operator decisions (confirmed = TRUE). Keeping suggestions rather than
-- discarding them is what lets an operator revisit a shortlist later.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS match_result (
    match_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lost_id     UUID NOT NULL REFERENCES lost_item (lost_id) ON DELETE CASCADE,
    found_id    UUID NOT NULL REFERENCES found_item (found_id) ON DELETE CASCADE,
    score       REAL NOT NULL,
    method      TEXT NOT NULL DEFAULT 'clip_cosine',
    confirmed   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One row per pairing: re-running matching updates the score in place
    -- rather than accumulating duplicates.
    UNIQUE (lost_id, found_id)
);

CREATE INDEX IF NOT EXISTS idx_match_lost ON match_result (lost_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_match_confirmed ON match_result (confirmed) WHERE confirmed;

-- ---------------------------------------------------------------------------
-- app_user — an operator console account
--
-- Three roles, in ascending order of what they may do:
--   viewer    read everything: dashboard, alerts, reports, found gallery, search
--   operator  the daily work: triage alerts, file reports, confirm matches,
--             start and stop camera workers
--   admin     register and delete cameras, and manage accounts
--
-- There is no public signup. The API creates the first admin at startup from
-- BOOTSTRAP_ADMIN_* if this table is empty; every later account is made by an
-- admin. The hash lives on the row rather than in a side table because there is
-- only ever one credential per account here.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_user (
    user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL UNIQUE,
    full_name     TEXT,

    -- Argon2, produced by passlib in app/core/security.py. Never a plain digest.
    password_hash TEXT NOT NULL,

    role          TEXT NOT NULL DEFAULT 'viewer'
                  CHECK (role IN ('admin', 'operator', 'viewer')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,

    -- Bumped on "log out everywhere", password change and deactivation. Every
    -- access token carries the value it was minted with, and a mismatch is a
    -- 401. That makes revocation instant without a per-request blacklist
    -- lookup: the row is already being read to check role and is_active.
    token_version INTEGER NOT NULL DEFAULT 1,

    last_login    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_app_user_active ON app_user (is_active) WHERE is_active;

-- ---------------------------------------------------------------------------
-- refresh_session — one row per logged-in device
--
-- Keyed by the refresh token's jti, never by the token string itself, so a
-- lookup is an indexed UUID equality test rather than a scan over TEXT.
--
-- Refresh rotates: spending a refresh token revokes its row and issues a new
-- one. A revoked jti presented again means the token was captured, and the
-- attempt is refused rather than silently honoured.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS refresh_session (
    session_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES app_user (user_id) ON DELETE CASCADE,
    jti         UUID NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,

    -- Context for the account's session list, so a stolen session is
    -- recognisable before it is revoked.
    user_agent  TEXT,
    ip_address  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_session (user_id)
    WHERE revoked_at IS NULL;

COMMIT;

-- ---------------------------------------------------------------------------
-- Notes
--
-- VECTOR(512) is the width of CLIP ViT-B-32, set by CLIP_MODEL_NAME in
-- backend/.env. Changing the model changes this dimension, and the two columns
-- plus their HNSW indexes have to change with it.
--
-- The HNSW indexes are only used by a query that orders by the raw <=>
-- distance. Ordering by `1 - (a <=> b)` reads as the same ranking but silently
-- falls back to a sequential scan — see database/queries.sql.
--
-- frame_jpeg and crop_jpeg are BYTEA, so the images live in the row. That keeps
-- deployment to one service at the cost of table size; queries.sql carries both
-- the size query and the purge that reclaims it.
-- ---------------------------------------------------------------------------
