# Lost & Found

Abandoned-object detection and lost/found item matching: RTSP cameras, YOLO + ByteTrack,
an abandonment state machine, a found gallery searchable by camera, date/time, object type
and colour, and rule-based matching of reported lost items against found ones.

```
RTSP camera → YOLO + ByteTrack → abandonment logic → event + found item (crop, type, colour)
                                                                       │
browser ──same origin──> web (Vite / nginx) ──proxy──> api ────────────┴──> postgres
```

| Tier | Directory | Stack |
|---|---|---|
| Console | [`frontend/`](frontend) | React 18, Vite, React Router, MUI |
| API + detection | [`backend/`](backend) | FastAPI, asyncpg, Ultralytics, OpenCV |
| Database | [`database/`](database) | PostgreSQL 17 — schema, seed, ops queries |
| End-to-end tests | [`e2e/`](e2e) | Playwright, run against the live stack |

Each directory has its own README with the detail.

---

## Run the whole thing

```bash
cp backend/.env.example backend/.env   # then set SECRET_KEY (see the comment in the file)
docker compose up --build
```

| Service | URL | Notes |
|---|---|---|
| Console | http://localhost:8082 | nginx serving the built SPA and proxying the API |
| API | http://localhost:8003 | `/docs` for Swagger |
| Postgres | localhost:5436 | `lostfound` / `lostfound_pass` / `lostfound_db` |

Sign in as the bootstrap admin from `backend/.env` (`admin` / `ChangeMe!123` by default) and
change the password.

Ports avoid the other stacks on this machine (no-entry-zone 5432/8000/8080, blocked-exit
5433/8001/8081). Override with `POSTGRES_HOST_PORT`, `API_HOST_PORT`, `WEB_HOST_PORT`,
`RTSP_HOST_PORT`.

The schema is `database/schema.sql`, applied by Postgres on the first boot of an empty volume
(there is no Alembic). The first API start downloads the YOLO weights into
`backend/models/`; later starts reuse them.

## Test camera without hardware

`mediamtx` starts with the rest of the stack and serves each clip in `backend/videos/` as an
RTSP path (see the `MTX_PATHS_*` entries in `docker-compose.yml`), looping on demand. Register a
camera in the console as, e.g., `rtsp://mediamtx:8554/lostfound` (from the host:
`rtsp://localhost:${RTSP_HOST_PORT}/lostfound`).

## Cameras stay running

A camera's `enabled` flag is the operator's intent. **Start** sets it and **Stop** clears it,
so a camera comes back after an API restart exactly as it was left. While the API runs, a
supervisor checks every worker every `WORKER_SUPERVISION_INTERVAL_S`. It restarts any worker
that died, errored (for example, a failed model load), or stopped analysing frames, with
exponential backoff. It also starts any enabled camera that has no worker. Per-worker state,
reconnects and supervisor restarts are shown on the camera page and at
`GET /api/v1/system/workers`.

The camera page shows the annotated detection output live, as MJPEG from
`GET /api/v1/cameras/{id}/stream`. Boxes are coloured by status: moving, attended,
unattended or abandoned.

## Event videos

Every abandoned event gets an annotated mp4 clip. It starts `CLIP_PRE_SECONDS` (40 s) before
the alert, which is long enough to show the item being left, and ends `CLIP_POST_SECONDS`
(10 s) after it. Clips are written to `backend/data/clips/<camera_id>/<event_id>.mp4`, play on
the event page, and are served at `GET /api/v1/events/{id}/clip`. A retention pass every 6 h
deletes clips older than `CLIP_RETENTION_DAYS` and keeps the total under
`CLIP_MAX_TOTAL_MB`. The event row, frame and found item are kept.

## Object storage (MinIO)

The `minio` service is S3-compatible storage for images and videos. On first start,
`minio-init` creates the bucket (`MINIO_BUCKET`, default `lostfound`) and exits.

| | Address |
|---|---|
| S3 API, from other containers | `http://minio:9000` |
| S3 API, from the host | `http://localhost:9000` (`MINIO_API_HOST_PORT`) |
| Web console | `http://localhost:9001` (`MINIO_CONSOLE_HOST_PORT`) |

Log in with `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` from the root `.env`. The api
container receives the same values as `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`,
`MINIO_BUCKET` and `MINIO_SECURE`. Data lives in the `miniodata` volume.

Images and videos are stored in MinIO, and Postgres keeps the records plus each object's key:

| Object | Key | Postgres column |
|---|---|---|
| Alert frame | `frames/<camera_id>/<event_id>.jpg` | `abandoned_event.frame_key` |
| Found-item crop | `crops/<camera_id>/<found_id>.jpg` | `found_item.crop_key` |
| Evidence clip | `clips/<camera_id>/<event_id>.mp4` | `abandoned_event.clip_key` |
| Lost-report photo | `lost/<lost_id>.jpg` | `lost_item.photo_key` |

If MinIO is unreachable when something is saved, it goes to the old place instead: image bytes in
Postgres (`frame_jpeg`, `crop_jpeg`, `photo_jpeg`) or the clip file on disk (`clip_path`). Reads
try MinIO first and then that fallback. Clip retention trims both places. Deleting a camera removes
its objects as well.

Data from before MinIO was copied over with `backend/tools/migrate_media_to_minio.py`. The tool
can be re-run and only copies rows that don't have a key yet. The original bytes and files are
kept. To drop them once you're satisfied:

```bash
docker compose exec -w /app api python tools/migrate_media_to_minio.py --cleanup
```

MinIO no longer publishes community images, so the service runs Chainguard's build of MinIO,
pinned by digest in `docker-compose.yml`.

## Tests

```bash
./e2e/run.sh                                          # Playwright, against the running stack
docker compose run --rm -v ./backend/tests:/app/tests api pytest -q   # backend unit tests
```
