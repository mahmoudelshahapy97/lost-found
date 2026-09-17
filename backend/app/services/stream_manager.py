# app/services/stream_manager.py
"""One asyncio worker per enabled camera, plus the manager that supervises them.

Every blocking call (VideoCapture, YOLO forward pass) is pushed onto a thread so
the event loop keeps serving HTTP while cameras are being processed.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import numpy as np

from app.core.config import config
from app.services.abandonment_service import AbandonmentParams, AbandonmentTracker
from app.services.camera_service import camera_service
from app.services.event_service import event_service
from app.services.rtsp_reader import RTSPReader
from app.services.tracking_service import ObjectTracker

logger = logging.getLogger(__name__)


class CameraWorker:
    """Processes a single RTSP stream until stopped."""

    def __init__(self, camera: Dict[str, Any]) -> None:
        self.camera = camera
        self.camera_id: UUID = camera["camera_id"]
        self.name: str = camera.get("name") or str(self.camera_id)
        self.rtsp_url: str = camera["rtsp_url"]

        settings = camera_service.parse_settings(camera)
        self.params = AbandonmentParams.from_settings(settings)
        self.roi = camera_service.parse_roi(camera)

        self.reader = RTSPReader(self.rtsp_url)
        self.detector: Optional[ObjectTracker] = None
        self.abandonment = AbandonmentTracker(params=self.params, roi=self.roi)

        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._last_frame: Optional[np.ndarray] = None
        self._min_interval = 1.0 / max(0.1, config.target_process_fps)

        self.started_at: Optional[datetime] = None
        self.frames_processed = 0
        self.events_emitted = 0
        self.last_error: Optional[str] = None
        self.connected = False

    # ---------------------------------------------------------------- control
    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self.started_at = datetime.now(timezone.utc)
        self._task = asyncio.create_task(self._run(), name=f"camera-{self.name}")
        logger.info("Worker started for camera %s (%s)", self.name, self.camera_id)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=15)
            except asyncio.TimeoutError:
                logger.warning("Worker %s did not stop in time; cancelling.", self.name)
                self._task.cancel()
            except asyncio.CancelledError:
                pass
        await asyncio.to_thread(self.reader.release)
        self.connected = False
        logger.info("Worker stopped for camera %s", self.name)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> Dict[str, Any]:
        return {
            "camera_id": str(self.camera_id),
            "name": self.name,
            "running": self.running,
            "connected": self.connected,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "frames_processed": self.frames_processed,
            "events_emitted": self.events_emitted,
            "last_error": self.last_error,
            "tracked_objects": self.abandonment.snapshot(),
        }

    def last_frame(self) -> Optional[np.ndarray]:
        return self._last_frame

    # ------------------------------------------------------------------- loop
    async def _run(self) -> None:
        reconnect_attempt = 0

        try:
            self.detector = await asyncio.to_thread(ObjectTracker)
        except Exception as e:
            self.last_error = f"model load failed: {e}"
            logger.error("Camera %s: %s", self.name, self.last_error, exc_info=True)
            return

        while not self._stop.is_set():
            if not self.reader.is_open:
                opened = await asyncio.to_thread(self.reader.open)
                if not opened:
                    reconnect_attempt += 1
                    self.connected = False
                    self.last_error = "could not open stream"
                    await self._sleep_backoff(reconnect_attempt)
                    continue
                reconnect_attempt = 0
                self.connected = True
                # Track ids restart with the connection, so drop stale state.
                self.abandonment.reset()
                if self.detector:
                    self.detector.reset()

            cycle_start = time.monotonic()
            ok, frame = await asyncio.to_thread(self.reader.read)

            if not ok:
                if self.reader.should_reconnect():
                    logger.warning("Camera %s: too many read failures, reconnecting.", self.name)
                    await asyncio.to_thread(self.reader.release)
                    self.connected = False
                await asyncio.sleep(0.2)
                continue

            try:
                await self._process(frame)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.last_error = str(e)
                logger.error("Camera %s processing error: %s", self.name, e, exc_info=True)

            # Hold the configured processing rate without busy-waiting.
            elapsed = time.monotonic() - cycle_start
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)

        await asyncio.to_thread(self.reader.release)

    async def _process(self, frame: np.ndarray) -> None:
        self._last_frame = frame
        self.frames_processed += 1

        detections = await asyncio.to_thread(self.detector.track, frame)
        events = self.abandonment.update(detections, time.time())

        for event in events:
            stored = await event_service.record_event(self.camera_id, event, frame)
            if stored:
                self.events_emitted += 1

    async def _sleep_backoff(self, attempt: int) -> None:
        delay = min(
            config.rtsp_reconnect_delay_base * (2 ** max(0, attempt - 1)),
            config.rtsp_reconnect_delay_max,
        )
        logger.info("Camera %s: retrying connection in %.1fs", self.name, delay)
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass


class StreamManager:
    """Owns the worker per camera and keeps the set in sync with the database."""

    def __init__(self) -> None:
        self.workers: Dict[UUID, CameraWorker] = {}
        self._lock = asyncio.Lock()

    async def start_camera(self, camera: Dict[str, Any]) -> Dict[str, Any]:
        camera_id = camera["camera_id"]
        async with self._lock:
            existing = self.workers.get(camera_id)
            if existing and existing.running:
                return existing.status()
            if existing:
                await existing.stop()

            worker = CameraWorker(camera)
            self.workers[camera_id] = worker
            await worker.start()
            return worker.status()

    async def stop_camera(self, camera_id: UUID) -> bool:
        async with self._lock:
            worker = self.workers.pop(camera_id, None)
        if worker is None:
            return False
        await worker.stop()
        return True

    async def start_enabled_cameras(self) -> int:
        """Called at startup so enabled cameras resume without manual intervention."""
        try:
            cameras = await camera_service.list_cameras(enabled_only=True)
        except Exception as e:
            logger.error("Could not load cameras at startup: %s", e, exc_info=True)
            return 0

        started = 0
        for camera in cameras:
            try:
                await self.start_camera(camera)
                started += 1
                # Stagger so several YOLO loads do not land at once.
                await asyncio.sleep(config.stream_start_stagger_delay)
            except Exception as e:
                logger.error("Failed to start camera %s: %s", camera.get("name"), e, exc_info=True)

        logger.info("Started %s/%s enabled cameras.", started, len(cameras))
        return started

    async def shutdown(self) -> None:
        async with self._lock:
            workers = list(self.workers.values())
            self.workers.clear()
        await asyncio.gather(*(w.stop() for w in workers), return_exceptions=True)
        logger.info("All camera workers stopped.")

    def get_worker(self, camera_id: UUID) -> Optional[CameraWorker]:
        return self.workers.get(camera_id)

    def status(self) -> List[Dict[str, Any]]:
        return [worker.status() for worker in self.workers.values()]


stream_manager = StreamManager()
