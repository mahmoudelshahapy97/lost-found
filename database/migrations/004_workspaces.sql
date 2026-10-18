-- 004_workspaces.sql
-- Workspaces partition the data, as in InsightEye: each camera belongs to one,
-- its events and found items follow it, and lost reports are filed in one.
-- Users see the workspaces they are members of; admins see all of them.
-- The three account roles (viewer < operator < admin) stay global.
--
-- Everything that exists today moves into the "Default" workspace, which has a
-- fixed id so seed data and tools can name it. Every account becomes a member.

CREATE TABLE IF NOT EXISTS workspace (
    workspace_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    description   TEXT,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_by    UUID REFERENCES app_user (user_id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_name ON workspace (lower(name));

CREATE TABLE IF NOT EXISTS workspace_member (
    workspace_id  UUID NOT NULL REFERENCES workspace (workspace_id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES app_user (user_id) ON DELETE CASCADE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_workspace_member_user ON workspace_member (user_id);

INSERT INTO workspace (workspace_id, name, description)
VALUES ('00000000-0000-0000-0000-000000000001', 'Default',
        'Created with workspaces; holds everything recorded before them.')
ON CONFLICT DO NOTHING;

INSERT INTO workspace_member (workspace_id, user_id)
SELECT '00000000-0000-0000-0000-000000000001', user_id FROM app_user
ON CONFLICT DO NOTHING;

-- ------------------------------------------------------------------ columns
ALTER TABLE camera      ADD COLUMN IF NOT EXISTS workspace_id UUID;
ALTER TABLE abandoned_event ADD COLUMN IF NOT EXISTS workspace_id UUID;
ALTER TABLE found_item  ADD COLUMN IF NOT EXISTS workspace_id UUID;
ALTER TABLE lost_item   ADD COLUMN IF NOT EXISTS workspace_id UUID;

UPDATE camera SET workspace_id = '00000000-0000-0000-0000-000000000001'
WHERE workspace_id IS NULL;

UPDATE abandoned_event e SET workspace_id = c.workspace_id
FROM camera c
WHERE e.workspace_id IS NULL AND c.camera_id = e.camera_id;

-- A found item keeps its workspace when its camera is deleted (camera_id is
-- SET NULL then), so it is copied from the camera, else from its event.
UPDATE found_item f SET workspace_id = COALESCE(
    (SELECT c.workspace_id FROM camera c WHERE c.camera_id = f.camera_id),
    (SELECT e.workspace_id FROM abandoned_event e WHERE e.event_id = f.event_id),
    '00000000-0000-0000-0000-000000000001'
)
WHERE f.workspace_id IS NULL;

UPDATE lost_item SET workspace_id = '00000000-0000-0000-0000-000000000001'
WHERE workspace_id IS NULL;

-- Cameras and lost reports default to Default for hand-written inserts (seed
-- data, tools); the API always names the workspace.
ALTER TABLE camera    ALTER COLUMN workspace_id SET DEFAULT '00000000-0000-0000-0000-000000000001';
ALTER TABLE lost_item ALTER COLUMN workspace_id SET DEFAULT '00000000-0000-0000-0000-000000000001';

ALTER TABLE camera          ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE abandoned_event ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE found_item      ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE lost_item       ALTER COLUMN workspace_id SET NOT NULL;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['camera', 'abandoned_event', 'found_item', 'lost_item'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = t || '_workspace_id_fkey') THEN
            EXECUTE format(
                'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (workspace_id) '
                'REFERENCES workspace (workspace_id) ON DELETE CASCADE',
                t, t || '_workspace_id_fkey'
            );
        END IF;
    END LOOP;
END $$;

-- Camera names are unique per workspace now, not across all of them.
ALTER TABLE camera DROP CONSTRAINT IF EXISTS camera_name_key;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'camera_workspace_name_key') THEN
        ALTER TABLE camera ADD CONSTRAINT camera_workspace_name_key UNIQUE (workspace_id, name);
    END IF;
END $$;

-- ------------------------------------------------------------------ triggers
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

-- ------------------------------------------------------------------ indexes
CREATE INDEX IF NOT EXISTS idx_camera_workspace     ON camera (workspace_id);
CREATE INDEX IF NOT EXISTS idx_event_workspace_time ON abandoned_event (workspace_id, abandoned_at DESC);
CREATE INDEX IF NOT EXISTS idx_found_workspace_time ON found_item (workspace_id, found_at DESC);
CREATE INDEX IF NOT EXISTS idx_lost_workspace_time  ON lost_item (workspace_id, reported_at DESC);
