-- 002_event_resolution.sql
-- How an alert was closed out, as in InsightEye's lost_found_events: what the
-- operator did, their notes, when it was acknowledged / resolved, and by whom.

ALTER TABLE abandoned_event
    ADD COLUMN IF NOT EXISTS action_taken    TEXT,
    ADD COLUMN IF NOT EXISTS description     TEXT,
    ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS resolved_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS resolved_by     UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'abandoned_event_resolved_by_fkey'
    ) THEN
        ALTER TABLE abandoned_event
            ADD CONSTRAINT abandoned_event_resolved_by_fkey
            FOREIGN KEY (resolved_by) REFERENCES app_user (user_id) ON DELETE SET NULL;
    END IF;
END $$;
