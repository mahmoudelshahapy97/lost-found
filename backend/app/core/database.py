# app/core/database.py
"""Asyncpg connection pool, schema readiness checks and idempotent upgrades."""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence, Union

import asyncpg

from app.core.config import config

logger = logging.getLogger(__name__)

connection_pool: Optional[asyncpg.Pool] = None


async def init_db_pool() -> asyncpg.Pool:
    """Create the pool, retrying with capped exponential backoff until Postgres is ready."""
    global connection_pool

    if connection_pool is not None and not connection_pool._closed:
        return connection_pool

    delay = config.db_retry_delay_base
    last_error: Optional[Exception] = None

    for attempt in range(1, config.db_max_retries + 1):
        try:
            connection_pool = await asyncpg.create_pool(
                dsn=config.database_dsn,
                min_size=config.db_min_pool_size,
                max_size=config.db_max_pool_size,
                timeout=config.db_timeout,
                command_timeout=config.db_command_timeout,
            )
            logger.info(
                "Postgres pool ready (%s:%s/%s, %s-%s connections)",
                config.db_host,
                config.db_port,
                config.postgres_db,
                config.db_min_pool_size,
                config.db_max_pool_size,
            )
            return connection_pool
        except Exception as e:
            last_error = e
            logger.warning(
                "Postgres not reachable (attempt %s/%s): %s", attempt, config.db_max_retries, e
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, config.db_retry_delay_max)

    raise RuntimeError(f"Could not connect to Postgres after {config.db_max_retries} attempts") from last_error


async def close_db_pool() -> None:
    global connection_pool
    if connection_pool is not None and not connection_pool._closed:
        await connection_pool.close()
        logger.info("Postgres pool closed.")
    connection_pool = None


def get_pool() -> Optional[asyncpg.Pool]:
    return connection_pool


async def check_postgres_health() -> bool:
    """Cheap liveness probe used by /health and at startup."""
    pool = get_pool()
    if pool is None or pool._closed:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception as e:
        logger.warning("Postgres health check failed: %s", e)
        return False


async def wait_for_schema(timeout: float = 60.0) -> bool:
    """Block until database/init/002_schema.sql has been applied.

    The Postgres image can report ready while its init scripts are still
    running, so a fresh volume may briefly have a live server with no tables.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    pool = get_pool()
    if pool is None:
        return False

    while loop.time() < deadline:
        try:
            async with pool.acquire() as conn:
                camera_exists = await conn.fetchval("SELECT to_regclass('public.camera')")
                user_exists = await conn.fetchval("SELECT to_regclass('public.app_user')")
            if camera_exists and user_exists:
                return True
        except Exception as e:
            logger.debug("Schema probe failed: %s", e)
        await asyncio.sleep(2)

    logger.error(
        "Tables 'camera'/'app_user' not found after %.0fs. "
        "Apply database/schema.sql before starting.",
        timeout,
    )
    return False


# schema.sql only runs on the first boot of an empty volume, so a column added
# to it later never reaches an existing database. Each statement here must be
# idempotent: it runs on every start.
SCHEMA_UPGRADES = (
    "ALTER TABLE abandoned_event ADD COLUMN IF NOT EXISTS clip_path TEXT",
    # Search is by camera / time / type / colour now; the CLIP and DINOv2
    # vectors (and their HNSW indexes) are no longer written or read.
    "DROP INDEX IF EXISTS idx_found_embedding, idx_found_visual_embedding, "
    "idx_lost_embedding, idx_lost_visual_embedding",
    "ALTER TABLE found_item DROP COLUMN IF EXISTS embedding, "
    "DROP COLUMN IF EXISTS visual_embedding",
    "ALTER TABLE lost_item DROP COLUMN IF EXISTS embedding, "
    "DROP COLUMN IF EXISTS text_embedding, DROP COLUMN IF EXISTS visual_embedding",
    # The search page filters a camera's items by time.
    "CREATE INDEX IF NOT EXISTS idx_found_camera_time ON found_item (camera_id, found_at DESC)",
    # Photo matching by perceptual hash + colour histogram (no model).
    "ALTER TABLE found_item ADD COLUMN IF NOT EXISTS phash BIGINT, "
    "ADD COLUMN IF NOT EXISTS color_hist BYTEA",
    "ALTER TABLE lost_item ADD COLUMN IF NOT EXISTS phash BIGINT, "
    "ADD COLUMN IF NOT EXISTS color_hist BYTEA",
    # Images and videos live in MinIO; these hold their object keys. The old
    # bytes / clip_path stay as the fallback when the store is unreachable.
    "ALTER TABLE abandoned_event ADD COLUMN IF NOT EXISTS frame_key TEXT, "
    "ADD COLUMN IF NOT EXISTS clip_key TEXT",
    "ALTER TABLE found_item ADD COLUMN IF NOT EXISTS crop_key TEXT",
    "ALTER TABLE lost_item ADD COLUMN IF NOT EXISTS photo_key TEXT",
)


async def ensure_schema_upgrades() -> None:
    """Bring an existing database up to the columns the code expects."""
    pool = get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        for statement in SCHEMA_UPGRADES:
            await conn.execute(statement)
    logger.info("Schema upgrades applied (%s statements).", len(SCHEMA_UPGRADES))


class DatabaseManager:
    """Thin query helper so services never touch the pool directly."""

    async def execute_query(
        self,
        query: str,
        params: Sequence[Any] = (),
        fetch_one: bool = False,
        fetch_all: bool = False,
        return_rowcount: bool = False,
    ) -> Union[Optional[Dict[str, Any]], List[Dict[str, Any]], int, None]:
        pool = get_pool()
        if pool is None or pool._closed:
            raise RuntimeError("Database pool is not initialized.")

        async with pool.acquire() as conn:
            if fetch_one:
                row = await conn.fetchrow(query, *params)
                return dict(row) if row else None
            if fetch_all:
                rows = await conn.fetch(query, *params)
                return [dict(row) for row in rows]

            status = await conn.execute(query, *params)
            if return_rowcount:
                return _rowcount_from_status(status)
            return None

    async def execute_many(self, query: str, args: Sequence[Sequence[Any]]) -> None:
        pool = get_pool()
        if pool is None or pool._closed:
            raise RuntimeError("Database pool is not initialized.")
        async with pool.acquire() as conn:
            await conn.executemany(query, args)


def _rowcount_from_status(status: str) -> int:
    """asyncpg returns command tags like 'DELETE 3' / 'UPDATE 1' / 'INSERT 0 2'."""
    parts = status.split()
    if not parts:
        return 0
    try:
        return int(parts[-1])
    except ValueError:
        return 0


db_manager = DatabaseManager()
