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
-- Extensions.
-- ---------------------------------------------------------------------------

-- gen_random_uuid() lives in pgcrypto on older servers; on PG13+ it is built
-- in. Creating it anyway keeps this file portable across both.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- workspace — a partition of the data: its cameras, their events and found
-- items, and the lost reports filed in it
--
-- Users see the workspaces they are members of (workspace_member, below);
-- admins see all of them. The account roles stay global. "Default" has a
-- fixed id so seed data and tools can name it; the api never deletes it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS workspace (
    workspace_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    description   TEXT,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_by    UUID,                     -- app_user; FK added after that table
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_name ON workspace (lower(name));

INSERT INTO workspace (workspace_id, name, description)
VALUES ('00000000-0000-0000-0000-000000000001', 'Default',
        'Created with workspaces; holds everything recorded before them.')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- camera — one watched RTSP source
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS camera (
    camera_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Defaults to Default for hand-written inserts; the api always names it.
    workspace_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                REFERENCES workspace (workspace_id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
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
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Names are unique within a workspace.
    CONSTRAINT camera_workspace_name_key UNIQUE (workspace_id, name)
);

-- Partial index: startup only ever asks for the enabled rows.
CREATE INDEX IF NOT EXISTS idx_camera_enabled ON camera (enabled) WHERE enabled;
CREATE INDEX IF NOT EXISTS idx_camera_workspace ON camera (workspace_id);

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
    -- Always the camera's: set by trg_event_workspace when left out.
    workspace_id    UUID NOT NULL REFERENCES workspace (workspace_id) ON DELETE CASCADE,
    track_key       TEXT NOT NULL,
    class_name      TEXT NOT NULL,
    confidence      REAL,
    bbox            JSONB NOT NULL,          -- {"x1":..,"y1":..,"x2":..,"y2":..}
    owner_track_id  INTEGER,
    first_seen_at   TIMESTAMPTZ NOT NULL,
    static_since    TIMESTAMPTZ,
    abandoned_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    frame_jpeg      BYTEA,                   -- annotated full frame (fallback when MinIO is down)
    frame_key       TEXT,                    -- the frame in MinIO: frames/<camera>/<event>.jpg
    clip_path       TEXT,                    -- evidence mp4 under CLIP_DIR (fallback when MinIO is down)
    clip_key        TEXT,                    -- the clip in MinIO: clips/<camera>/<event>.mp4
    status          TEXT NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'FALSE_POSITIVE')),
    -- How the alert was closed out: what the operator did and their notes.
    action_taken    TEXT,
    description     TEXT,
    acknowledged_at TIMESTAMPTZ,            -- first left OPEN
    resolved_at     TIMESTAMPTZ,            -- RESOLVED or FALSE_POSITIVE
    resolved_by     UUID,                   -- app_user; FK added after that table
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Makes event recording idempotent: a worker replaying a track cannot
    -- raise a second alert for the same object.
    UNIQUE (camera_id, track_key)
);

CREATE INDEX IF NOT EXISTS idx_event_camera_time
    ON abandoned_event (camera_id, abandoned_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_status ON abandoned_event (status);
CREATE INDEX IF NOT EXISTS idx_event_class  ON abandoned_event (class_name);
CREATE INDEX IF NOT EXISTS idx_event_workspace_time
    ON abandoned_event (workspace_id, abandoned_at DESC);

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
    -- Its own column, so it outlives the camera: set from the camera (or the
    -- event) by trg_found_workspace when left out.
    workspace_id    UUID NOT NULL REFERENCES workspace (workspace_id) ON DELETE CASCADE,
    class_name      TEXT NOT NULL,
    dominant_color  TEXT,
    crop_jpeg       BYTEA,              -- fallback when MinIO is down
    crop_key        TEXT,               -- crops/<camera>/<found>.jpg in MinIO
    -- Visual features of the item for photo matching (utils/visual_similarity):
    -- 64-bit perceptual hash and HSV histogram as float32 bytes.
    phash           BIGINT,
    color_hist      BYTEA,
    found_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          TEXT NOT NULL DEFAULT 'UNCLAIMED'
                    CHECK (status IN ('UNCLAIMED', 'CLAIMED', 'DISCARDED')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_found_status     ON found_item (status);
CREATE INDEX IF NOT EXISTS idx_found_class_time ON found_item (class_name, found_at DESC);
-- The search page's main query: one camera's items over a time range.
CREATE INDEX IF NOT EXISTS idx_found_camera_time ON found_item (camera_id, found_at DESC);
CREATE INDEX IF NOT EXISTS idx_found_workspace_time ON found_item (workspace_id, found_at DESC);

-- ---------------------------------------------------------------------------
-- lost_item — what a person reported missing
--
-- A report may carry a photo, a description, or both. Matching uses its object
-- type, its colour (read from the photo, or a colour word in the description)
-- and lost_after; the photo itself is kept for staff to look at.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lost_item (
    lost_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- The workspace it was filed in; matching only looks at that workspace.
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                    REFERENCES workspace (workspace_id) ON DELETE CASCADE,
    reporter_name   TEXT,
    reporter_email  TEXT,
    description     TEXT,
    class_name      TEXT,
    dominant_color  TEXT,
    photo_jpeg      BYTEA,              -- fallback when MinIO is down
    photo_key       TEXT,               -- lost/<lost>.jpg in MinIO
    phash           BIGINT,             -- features of the photo, as on found_item
    color_hist      BYTEA,
    lost_after      TIMESTAMPTZ,        -- narrows the found-item search window
    reported_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          TEXT NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN', 'MATCHED', 'RESOLVED', 'CLOSED')),
    -- When the reporter was emailed that their item was found; set once.
    reporter_notified_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lost_status   ON lost_item (status);
CREATE INDEX IF NOT EXISTS idx_lost_reported ON lost_item (reported_at DESC);
CREATE INDEX IF NOT EXISTS idx_lost_workspace_time ON lost_item (workspace_id, reported_at DESC);

-- ---------------------------------------------------------------------------
-- match_result — one pairing between a lost report and a found item
--
-- Holds both rule-based suggestions (confirmed = FALSE, method = 'rule_based')
-- and operator decisions (confirmed = TRUE). Keeping suggestions rather than
-- discarding them is what lets an operator revisit a shortlist later.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS match_result (
    match_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lost_id     UUID NOT NULL REFERENCES lost_item (lost_id) ON DELETE CASCADE,
    found_id    UUID NOT NULL REFERENCES found_item (found_id) ON DELETE CASCADE,
    score       REAL NOT NULL,
    method      TEXT NOT NULL DEFAULT 'rule_based',
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
    -- Operators and admins are emailed new alerts unless they turn this off.
    alert_emails  BOOLEAN NOT NULL DEFAULT TRUE,

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

-- ---------------------------------------------------------------------------
-- password_otp — a "forgot your password?" code mailed to the account
--
-- At most one live code per account. Only an HMAC of the code is stored; it
-- expires after OTP_TTL_SECONDS and dies after OTP_MAX_ATTEMPTS wrong guesses.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS password_otp (
    user_id       UUID PRIMARY KEY REFERENCES app_user (user_id) ON DELETE CASCADE,
    otp_hash      TEXT NOT NULL,
    expires_at    TIMESTAMPTZ NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_sent_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- workspace_member — who may see a workspace
--
-- Admins see every workspace without a row here. A new account joins the
-- workspaces it is created with, or Default.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS workspace_member (
    workspace_id  UUID NOT NULL REFERENCES workspace (workspace_id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES app_user (user_id) ON DELETE CASCADE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_member_user ON workspace_member (user_id);

ALTER TABLE workspace
    ADD CONSTRAINT workspace_created_by_fkey
    FOREIGN KEY (created_by) REFERENCES app_user (user_id) ON DELETE SET NULL;

-- Events and found items take their camera's workspace, so the workers never
-- have to know about workspaces and the two can never disagree.
CREATE OR REPLACE FUNCTION lf_inherit_workspace() RETURNS trigger AS $$
BEGIN
    IF NEW.workspace_id IS NULL THEN
        SELECT c.workspace_id INTO NEW.workspace_id FROM camera c WHERE c.camera_id = NEW.camera_id;
    END IF;
    IF NEW.workspace_id IS NULL AND TG_TABLE_NAME = 'found_item' THEN
        SELECT e.workspace_id INTO NEW.workspace_id FROM abandoned_event e WHERE e.event_id = NEW.event_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_event_workspace
    BEFORE INSERT ON abandoned_event
    FOR EACH ROW EXECUTE FUNCTION lf_inherit_workspace();
CREATE OR REPLACE TRIGGER trg_found_workspace
    BEFORE INSERT ON found_item
    FOR EACH ROW EXECUTE FUNCTION lf_inherit_workspace();

-- abandoned_event is created before app_user, so its reference to the
-- operator who closed it out is added here.
ALTER TABLE abandoned_event
    ADD CONSTRAINT abandoned_event_resolved_by_fkey
    FOREIGN KEY (resolved_by) REFERENCES app_user (user_id) ON DELETE SET NULL;

COMMIT;

-- ---------------------------------------------------------------------------
-- Notes
--
-- No embeddings are stored. Earlier versions kept CLIP/DINOv2 vectors in
-- found_item and lost_item; database/migrations/001_baseline_upgrades.sql
-- drops those columns from an existing database.
--
-- Every change made here after the first release also goes into a numbered
-- file in database/migrations/, which the api applies at startup.
--
-- Images and videos live in MinIO (the *_key columns). The BYTEA columns and
-- clip_path are the fallback the api writes when MinIO is unreachable, and
-- hold data from before the move until it is cleaned up;
-- backend/tools/migrate_media_to_minio.py copies them into MinIO.
-- ---------------------------------------------------------------------------
