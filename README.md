# Lost & Found

Abandoned-object detection and lost/found item matching: RTSP cameras, YOLO + ByteTrack,
an abandonment state machine, and CLIP embeddings in pgvector for matching reported lost
items against found ones.

```
RTSP camera → YOLO + ByteTrack → abandonment logic → event + found item (CLIP embedding)
                                                                       │
browser ──same origin──> web (Vite / nginx) ──proxy──> api ────────────┴──> postgres + pgvector
```

| Tier | Directory | Stack |
|---|---|---|
| Console | [`frontend/`](frontend) | React 18, Vite, React Router, MUI |
| API + detection | [`backend/`](backend) | FastAPI, asyncpg, Ultralytics, OpenCV, open_clip |
| Database | [`database/`](database) | PostgreSQL 17 + pgvector — schema, seed, ops queries |
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
(there is no Alembic). The first API start downloads the CLIP and YOLO weights into
`backend/models/`, so it takes a few minutes; later starts reuse them.

## Test camera without hardware

```bash
docker compose --profile testing up -d mediamtx
```

This loops `backend/videos/sample.mp4` as RTSP. Register the camera in the console as
`rtsp://mediamtx:8554/lostfound` (from the host: `rtsp://localhost:8556/lostfound`).

## Tests

```bash
./e2e/run.sh                                          # Playwright, against the running stack
docker compose run --rm -v ./backend/tests:/app/tests api pytest -q   # backend unit tests
```
