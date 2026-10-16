# app/services/retention.py
"""Bounded storage for evidence clips.

A monitoring service that only ever writes video eventually fills its disk and
takes detection down with it. Each pass deletes clips older than
CLIP_RETENTION_DAYS, then the oldest clips until the total is under
CLIP_MAX_TOTAL_MB, and clears ``clip_path`` on the events that pointed at them.
Event rows, frames and found items are kept: only the video goes.

Turn it off with RETENTION_ENABLED=false where an external archiver owns the data.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from app.core.config import config
from app.core.database import db_manager

logger = logging.getLogger(__name__)

_task: Optional[asyncio.Task] = None


@dataclass
class PurgeReport:
    clips_deleted: int = 0
    bytes_reclaimed: int = 0

    def as_dict(self) -> dict:
        return {
            "clips_deleted": self.clips_deleted,
            "mb_reclaimed": round(self.bytes_reclaimed / (1024 * 1024), 1),
        }


def _scan(root: Path) -> List[Tuple[float, int, Path]]:
    """(mtime, size, path) for every finished clip, oldest first."""
    if not root.exists():
        return []
    files = []
    for path in root.glob("*/*.mp4"):
        if path.name.endswith(".partial.mp4"):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append((stat.st_mtime, stat.st_size, path))
    files.sort()
    return files


def select_expired(
    files: List[Tuple[float, int, Path]], now: float, max_age_s: float, max_total_bytes: int
) -> List[Tuple[float, int, Path]]:
    """Files to delete: everything past max_age_s, then the oldest of the rest
    until the total fits max_total_bytes. ``files`` must be oldest first."""
    expired = [f for f in files if now - f[0] > max_age_s]
    kept = [f for f in files if now - f[0] <= max_age_s]
    total = sum(size for _, size, _ in kept)
    for entry in kept:
        if total <= max_total_bytes:
            break
        expired.append(entry)
        total -= entry[1]
    return expired


def _delete(files: List[Tuple[float, int, Path]], root: Path) -> Tuple[List[str], int]:
    removed, reclaimed = [], 0
    for _, size, path in files:
        try:
            path.unlink()
            removed.append(path.relative_to(root).as_posix())
            reclaimed += size
        except OSError as e:
            logger.warning("Could not delete clip %s: %s", path, e)
    return removed, reclaimed


async def purge_old_clips() -> PurgeReport:
    """Run one retention pass. Never raises -- a purge failure is not fatal."""
    report = PurgeReport()
    try:
        root = Path(config.clip_dir)
        files = await asyncio.to_thread(_scan, root)
        expired = select_expired(
            files,
            time.time(),
            config.clip_retention_days * 86400,
            config.clip_max_total_mb * 1024 * 1024,
        )
        if not expired:
            return report
        removed, reclaimed = await asyncio.to_thread(_delete, expired, root)
        if removed:
            await db_manager.execute_query(
                "UPDATE abandoned_event SET clip_path = NULL WHERE clip_path = ANY($1::text[])",
                (removed,),
            )
        report.clips_deleted = len(removed)
        report.bytes_reclaimed = reclaimed
        logger.info("Retention pass: %s", report.as_dict())
    except Exception:
        logger.exception("Clip retention pass failed")
    return report


async def _loop() -> None:
    interval = max(60.0, config.retention_interval_s)
    while True:
        await purge_old_clips()
        await asyncio.sleep(interval)


def start() -> None:
    global _task
    if not config.retention_enabled or _task is not None:
        return
    _task = asyncio.create_task(_loop(), name="clip-retention")


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
