-- 001_baseline_upgrades.sql
-- The column changes that used to run on every start as SCHEMA_UPGRADES in
-- backend/app/core/database.py. A volume created from today's schema.sql
-- already has all of this, so on a fresh install each statement is a no-op.

ALTER TABLE abandoned_event ADD COLUMN IF NOT EXISTS clip_path TEXT;

-- Search is by camera / time / type / colour now; the CLIP and DINOv2
-- vectors (and their HNSW indexes) are no longer written or read.
DROP INDEX IF EXISTS idx_found_embedding, idx_found_visual_embedding,
    idx_lost_embedding, idx_lost_visual_embedding;
ALTER TABLE found_item DROP COLUMN IF EXISTS embedding,
    DROP COLUMN IF EXISTS visual_embedding;
ALTER TABLE lost_item DROP COLUMN IF EXISTS embedding,
    DROP COLUMN IF EXISTS text_embedding, DROP COLUMN IF EXISTS visual_embedding;

-- The search page filters a camera's items by time.
CREATE INDEX IF NOT EXISTS idx_found_camera_time ON found_item (camera_id, found_at DESC);

-- Photo matching by perceptual hash + colour histogram (no model).
ALTER TABLE found_item ADD COLUMN IF NOT EXISTS phash BIGINT,
    ADD COLUMN IF NOT EXISTS color_hist BYTEA;
ALTER TABLE lost_item ADD COLUMN IF NOT EXISTS phash BIGINT,
    ADD COLUMN IF NOT EXISTS color_hist BYTEA;

-- Images and videos live in MinIO; these hold their object keys. The old
-- bytes / clip_path stay as the fallback when the store is unreachable.
ALTER TABLE abandoned_event ADD COLUMN IF NOT EXISTS frame_key TEXT,
    ADD COLUMN IF NOT EXISTS clip_key TEXT;
ALTER TABLE found_item ADD COLUMN IF NOT EXISTS crop_key TEXT;
ALTER TABLE lost_item ADD COLUMN IF NOT EXISTS photo_key TEXT;
