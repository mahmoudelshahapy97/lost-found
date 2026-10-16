# tools/migrate_media_to_minio.py
"""Copy images and clips stored before MinIO into MinIO, and record their keys.

    event frames      abandoned_event.frame_jpeg   -> frames/<camera>/<event>.jpg  (frame_key)
    found crops       found_item.crop_jpeg         -> crops/<camera>/<found>.jpg   (crop_key)
    lost photos       lost_item.photo_jpeg         -> lost/<lost>.jpg              (photo_key)
    evidence clips    CLIP_DIR/<clip_path>         -> clips/<camera>/<event>.mp4   (clip_key)

Each object's size is checked against the source before its key is written,
so a key only ever points at a complete copy. Only rows without a key are
touched, so the tool can be re-run after an interruption. Nothing is deleted:
the bytes and clip files stay as the fallback until --cleanup is run.

Run inside the api container:

    python tools/migrate_media_to_minio.py             # copy, verify, record keys
    python tools/migrate_media_to_minio.py --dry-run   # only count what would move
    python tools/migrate_media_to_minio.py --cleanup   # afterwards: drop the copied
                                                       # bytes and clip files
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import config  # noqa: E402
from app.core.database import close_db_pool, db_manager, ensure_schema_upgrades, init_db_pool  # noqa: E402
from app.services.object_store import (  # noqa: E402
    clip_key,
    crop_key,
    frame_key,
    object_store,
    photo_key,
)

BATCH = 200
PARALLEL = 8

IMAGES = (
    # label, table, id column, key column, bytes column, key builder
    ("frames", "abandoned_event", "event_id", "frame_key", "frame_jpeg",
     lambda row: frame_key(row["camera_id"], row["event_id"])),
    ("crops", "found_item", "found_id", "crop_key", "crop_jpeg",
     lambda row: crop_key(row["camera_id"], row["found_id"])),
    ("photos", "lost_item", "lost_id", "photo_key", "photo_jpeg",
     lambda row: photo_key(row["lost_id"])),
)


class Tally:
    def __init__(self, label: str) -> None:
        self.label, self.copied, self.failed, self.bytes = label, 0, 0, 0
        self.started = time.time()

    def line(self) -> str:
        return (f"{self.label:7s} copied={self.copied} failed={self.failed} "
                f"{self.bytes / 1048576:.1f} MB in {time.time() - self.started:.0f}s")


async def _copy_bytes(key: str, data: bytes, content_type: str) -> bool:
    return await object_store.put_bytes(key, data, content_type) and await object_store.size(key) == len(data)


async def migrate_images(label, table, id_col, key_col, bytes_col, make_key, dry_run) -> Tally:
    tally = Tally(label)
    camera = "camera_id, " if table != "lost_item" else ""
    if dry_run:
        row = await db_manager.execute_query(
            f"SELECT COUNT(*) AS n, COALESCE(SUM(octet_length({bytes_col})), 0) AS b FROM {table} "
            f"WHERE {bytes_col} IS NOT NULL AND {key_col} IS NULL",
            fetch_one=True,
        )
        tally.copied, tally.bytes = row["n"], row["b"]
        return tally

    gate = asyncio.Semaphore(PARALLEL)
    failed_ids = set()

    async def one(row):
        key = make_key(row)
        data = bytes(row[bytes_col])
        async with gate:
            ok = await _copy_bytes(key, data, "image/jpeg")
        if ok:
            await db_manager.execute_query(
                f"UPDATE {table} SET {key_col} = $2 WHERE {id_col} = $1", (row[id_col], key)
            )
            tally.copied += 1
            tally.bytes += len(data)
        else:
            tally.failed += 1
            failed_ids.add(row[id_col])

    while True:
        rows = await db_manager.execute_query(
            f"SELECT {id_col}, {camera}{bytes_col} FROM {table} "
            f"WHERE {bytes_col} IS NOT NULL AND {key_col} IS NULL "
            f"AND NOT ({id_col} = ANY($1::uuid[])) ORDER BY {id_col} LIMIT {BATCH}",
            (list(failed_ids),),
            fetch_all=True,
        )
        if not rows:
            return tally
        await asyncio.gather(*(one(row) for row in rows))
        print("  " + tally.line(), flush=True)


async def migrate_clips(dry_run) -> Tally:
    tally = Tally("clips")
    root = Path(config.clip_dir)
    rows = await db_manager.execute_query(
        "SELECT event_id, camera_id, clip_path FROM abandoned_event "
        "WHERE clip_path IS NOT NULL AND clip_key IS NULL ORDER BY abandoned_at",
        fetch_all=True,
    ) or []
    gate = asyncio.Semaphore(PARALLEL)

    async def one(row):
        path = (root / row["clip_path"]).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            tally.failed += 1
            print(f"  clip file missing for event {row['event_id']}: {row['clip_path']}", flush=True)
            return
        size = path.stat().st_size
        if dry_run:
            tally.copied += 1
            tally.bytes += size
            return
        key = clip_key(row["camera_id"], row["event_id"])
        async with gate:
            ok = await object_store.put_file(key, str(path), "video/mp4") and await object_store.size(key) == size
        if ok:
            await db_manager.execute_query(
                "UPDATE abandoned_event SET clip_key = $2 WHERE event_id = $1", (row["event_id"], key)
            )
            tally.copied += 1
            tally.bytes += size
        else:
            tally.failed += 1

    for start in range(0, len(rows), BATCH):
        await asyncio.gather(*(one(row) for row in rows[start:start + BATCH]))
        if not dry_run:
            print("  " + tally.line(), flush=True)
    return tally


async def cleanup() -> None:
    """Drop the fallback copies of everything that is safely in MinIO."""
    for label, table, id_col, key_col, bytes_col, _ in IMAGES:
        n = await db_manager.execute_query(
            f"UPDATE {table} SET {bytes_col} = NULL WHERE {key_col} IS NOT NULL AND {bytes_col} IS NOT NULL",
            return_rowcount=True,
        )
        print(f"{label:7s} cleared {n} byte copies from Postgres")
    root = Path(config.clip_dir)
    rows = await db_manager.execute_query(
        "SELECT event_id, clip_path FROM abandoned_event WHERE clip_key IS NOT NULL AND clip_path IS NOT NULL",
        fetch_all=True,
    ) or []
    removed = 0
    for row in rows:
        path = (root / row["clip_path"]).resolve()
        if path.is_relative_to(root.resolve()):
            path.unlink(missing_ok=True)
            removed += 1
        await db_manager.execute_query(
            "UPDATE abandoned_event SET clip_path = NULL WHERE event_id = $1", (row["event_id"],)
        )
    print(f"clips   removed {removed} local files")
    print("Run VACUUM FULL on abandoned_event / found_item / lost_item to return the space to the OS.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="count what would be copied")
    parser.add_argument("--cleanup", action="store_true", help="drop copies already safe in MinIO")
    args = parser.parse_args()

    if not object_store.enabled or not await object_store.healthy():
        sys.exit("MinIO is not configured or not reachable (MINIO_ENDPOINT / credentials).")

    await init_db_pool()
    try:
        await ensure_schema_upgrades()
        if args.cleanup:
            await cleanup()
            return
        print(f"{'Dry run: ' if args.dry_run else ''}migrating to bucket '{object_store.bucket}' at {config.minio_endpoint}")
        tallies = []
        for label, table, id_col, key_col, bytes_col, make_key in IMAGES:
            tallies.append(await migrate_images(label, table, id_col, key_col, bytes_col, make_key, args.dry_run))
        tallies.append(await migrate_clips(args.dry_run))
        print("\n" + "\n".join(t.line() for t in tallies))
        if any(t.failed for t in tallies):
            sys.exit("Some items failed; re-run to retry them.")
    finally:
        await close_db_pool()


if __name__ == "__main__":
    asyncio.run(main())
