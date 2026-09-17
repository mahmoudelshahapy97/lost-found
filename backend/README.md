# Lost & Found — FastAPI Computer Vision Backend

Two capabilities in one service, as the [feature research](../readme.md) concluded a real
lost-and-found system needs:

1. **Abandoned-object detection** — YOLO + ByteTrack over live RTSP cameras. `abandoned` is never a
   detection class; it is a *status* derived from tracking, distance and time.
2. **Lost ↔ found matching** — CLIP embeddings + pgvector cosine search, so a photo of a lost bag
   can be matched against the object crops the cameras harvested automatically.

The found gallery is self-populating: every abandoned-object event contributes its cropped image and
a 512-d CLIP embedding to `found_item`. A person reporting a loss uploads one photo, and the API
ranks the gallery against it.

---

## How an object becomes "abandoned"

```
MOVING      centroid drifts more than static_tolerance_px
   ↓
STATIC      centroid stable for static_window_seconds
            → nearest person within owner_distance_px is recorded as the owner
   ↓
ATTENDED    owner still in frame and within abandon_distance_px
UNATTENDED  owner gone or too far → the clock starts
   ↓
ABANDONED   unattended for abandon_seconds (default 30 s, the PETS2006 convention)
            → event + annotated frame + embedded crop, emitted exactly once
```

If the owner comes back within range the timer resets. If the owner's track is lost to occlusion,
any person standing within `owner_distance_px` is adopted as the owner, which suppresses the most
common false positive. The whole machine lives in
[app/services/abandonment_service.py](app/services/abandonment_service.py) and is pure Python — see
[tests/test_abandonment.py](tests/test_abandonment.py) for it being exercised without a camera.

Every threshold is tunable globally through `.env` and per camera through `camera.settings`:

```json
{ "abandon_seconds": 45, "owner_distance_px": 220, "static_tolerance_px": 30 }
```

---

## Layout

```
app/
├── api/routes/     camera_router, event_router, lostfound_router, system_router
├── core/           config.py (pydantic-settings), database.py (asyncpg), logging_config.py
├── schemas/        pydantic request/response models
├── services/       model_registry, rtsp_reader, tracking, abandonment, stream_manager,
│                   camera, event, embedding, matching
├── utils/          image, geometry, color, vector, response
└── main.py         app factory, lifespan, /health

../database/        schema, seed and reference queries (see database/README.md)
├── init/           applied automatically on first boot of an empty volume
├── seed/           demo rows, applied on demand
└── queries/        annotated reference queries, one file per area
```

---

## Running with Docker (recommended)

Docker is not yet installed in the WSL distro. One-time setup:

```bash
sudo apt update && sudo apt install -y ffmpeg
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER      # then: wsl --shutdown  from PowerShell
```

Then, from `/mnt/c/Users/User/Desktop/insighteye/features/lost&found/backend` (quote the `&`):

```bash
cp .env.example .env               # already done; edit if you like
docker compose up --build                        # database + API
docker compose --profile testing up -d mediamtx  # plus a fake RTSP camera
```

Services:

| service    | what it is                                       | port |
|------------|--------------------------------------------------|------|
| `postgres` | `pgvector/pgvector:pg17`, schema auto-applied     | 5433 |
| `api`      | this FastAPI app                                 | 8000 |
| `mediamtx` | mediamtx looping `videos/sample.mp4` over RTSP    | 8554 |

Docs at <http://localhost:8000/docs>.

`docker-compose.override.yml` remaps those host ports to 5436, 8003 and 8555
on this machine, where the other feature stacks already hold the defaults.
Compose loads it automatically; delete it to go back to the documented ports.

This is the **backend-only** stack. `../docker-compose.yml` is the full one —
the same database and API plus the operator console — and both declare the
project name `lost-found`, so they share one `pgdata` volume and one API
image. The cost is that `docker compose up` here reports the `web` container
as an orphan; harmless, and much better than a second stack running against a
second, empty database. Do not pass `--remove-orphans`.

The first boot downloads the YOLO and CLIP weights into `./models`, which is volume-mounted so
rebuilds do not re-download them.

## Running without Docker

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# point at a Postgres that has the pgvector extension and database/init/002_schema.sql applied
sed -i 's/^DB_HOST=.*/DB_HOST="localhost"/' .env
uvicorn app.main:app --reload
```

---

## Auth

Every route below `/api/v1` requires a bearer token except `GET /health`. There is no
public signup: the first admin is created automatically at startup from
`BOOTSTRAP_ADMIN_USERNAME` / `_EMAIL` / `_PASSWORD` in `.env` (default `admin` /
`ChangeMe!123` — change it immediately after first login), and every other account is
created by an admin through `POST /users`.

| method | path | purpose |
|---|---|---|
| POST | `/auth/login` | `{username, password}` → access + refresh token, sets the image-auth cookie |
| POST | `/auth/refresh` | `{refresh_token}` → a new pair; rotates the refresh token |
| POST | `/auth/logout` | revoke this session |
| POST | `/auth/logout-all` | revoke every session for the account |
| GET | `/auth/me` | the calling user |
| POST | `/auth/change-password` | verifies the current password, then logs the account out everywhere |

Three roles, each a superset of the one before it: `viewer` (read everything),
`operator` (triage alerts, file reports, confirm matches, start/stop workers), `admin`
(register/delete cameras, manage accounts). The floor for each route is enforced in
`app/api/deps.py` and applied per-router — see the guards on `camera_router.py`,
`event_router.py`, `lostfound_router.py` and `system_router.py`.

The three `image/jpeg` routes (`/cameras/{id}/snapshot`, `/events/{id}/frame`,
`/found-items/{id}/crop`) also accept the httpOnly cookie `/auth/login` sets, since a
plain `<img src>` cannot attach an `Authorization` header. No other route accepts the
cookie — see the comment on `get_image_viewer` in `app/api/deps.py` for why that
boundary matters.

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"ChangeMe!123"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s localhost:8000/api/v1/cameras -H "Authorization: Bearer $TOKEN"
```

---

## API

Base prefix `/api/v1`. Every route needs `-H "Authorization: Bearer $TOKEN"` — see Auth above.

### Cameras
| method | path | purpose |
|---|---|---|
| POST | `/cameras` | register an RTSP camera (starts processing if `enabled`) |
| GET | `/cameras` | list cameras |
| PATCH | `/cameras/{id}` | update; a running worker restarts with the new settings |
| DELETE | `/cameras/{id}` | delete camera and, by cascade, its events |
| POST | `/cameras/{id}/start` · `/stop` | control the worker |
| GET | `/cameras/{id}/status` | live worker state + every object being tracked |
| GET | `/cameras/{id}/snapshot` | latest frame as JPEG |

### Events
| method | path | purpose |
|---|---|---|
| GET | `/events` | filter by camera, status, class, time range; paginated |
| GET | `/events/stats` | totals, open count, last 24 h |
| GET | `/events/{id}/frame` | the annotated alert frame |
| PATCH | `/events/{id}/status` | acknowledge / resolve / mark false positive |

### Lost & found
| method | path | purpose |
|---|---|---|
| POST | `/lost-items` | report a loss (multipart photo and/or description) |
| GET | `/lost-items/{id}/matches` | rank the found gallery against the report |
| POST | `/search/image` | ad-hoc photo search, stores nothing |
| POST | `/search/text` | search by description alone — CLIP shares one text/image space |
| GET | `/found-items` | the auto-harvested gallery |
| GET | `/found-items/{id}/crop` | the cropped object image |
| POST | `/matches/confirm` | confirm a pairing: report resolved, item claimed |
| DELETE | `/matches` | reject a suggested pairing |

### System
`GET /health`, `GET /api/v1/system/workers`, `GET /api/v1/system/config` (the tuning values actually
in force — the first place to look when an event fires later than expected).

---

## Walkthrough

```bash
# 0. log in once (see Auth above) — every call below carries this
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"ChangeMe!123"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"

# 1. register the simulated camera
CAM=$(curl -s -X POST localhost:8000/api/v1/cameras \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"lobby","rtsp_url":"rtsp://mediamtx:8554/lostfound","location":"Terminal 1"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["camera_id"])')

# 2. confirm frames are flowing
curl -s localhost:8000/api/v1/cameras/$CAM/snapshot -H "$AUTH" -o snapshot.jpg
curl -s localhost:8000/api/v1/cameras/$CAM/status -H "$AUTH" | python3 -m json.tool

# 3. wait for abandon_seconds, then read the events
curl -s "localhost:8000/api/v1/events?per_page=5" -H "$AUTH" | python3 -m json.tool
curl -s localhost:8000/api/v1/events/<event_id>/frame -H "$AUTH" -o alert.jpg

# 4. report a loss and match it
curl -s -X POST localhost:8000/api/v1/lost-items \
  -H "$AUTH" \
  -F 'photo=@my_backpack.jpg' \
  -F 'description=black leather backpack' \
  -F 'reporter_email=me@example.com'
curl -s localhost:8000/api/v1/lost-items/<lost_id>/matches -H "$AUTH" | python3 -m json.tool

# 5. text-only search
curl -s -X POST localhost:8000/api/v1/search/text \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"description":"black leather backpack"}' | python3 -m json.tool
```

---

## Tests

```bash
pytest                    # unit tests always run; DB-backed tests skip without a database
```

**Unit** ([test_abandonment.py](tests/test_abandonment.py), [test_utils.py](tests/test_utils.py)) —
the state machine driven by synthetic detections (owner leaves → event; owner returns → no event;
owner present but too far → event; object never static → no event; exactly one event per track; ROI
gating; track expiry; configurable thresholds), plus the geometry, colour and vector helpers. No
camera, model or database.

**Auth** ([test_auth.py](tests/test_auth.py)) — password hashing and strength rules, JWT
create/decode (round trip, expired, tampered, wrong `token_type`), the role ladder, always run
with no database. `verify_credentials`, `token_version` revocation, and refresh-token rotation
need `app_user`/`refresh_session` and skip themselves the same way integration does.

**Integration** ([test_integration.py](tests/test_integration.py)) — camera CRUD, event recording
and idempotency, status transitions, and the full pgvector ranking path with hand-crafted
embeddings, so no YOLO or CLIP weights are needed. They skip themselves unless a database is
reachable and the schema is applied:

```bash
DB_HOST=localhost DB_PORT=5436 pytest      # against the compose stack
```

Each test cleans up after itself, so the suite is repeatable against a persistent database.

### Postgres without Docker or root

Handy while Docker is unavailable — the `pgserver` wheel bundles a complete PostgreSQL 16 *with*
pgvector, and the binaries do not care which Python you extracted them with:

```bash
mkdir -p ~/pgsrv && cd ~/pgsrv
pip download --no-deps --only-binary :all: --python-version 312 \
    --platform manylinux_2_17_x86_64 --implementation cp --abi cp312 -d . pgserver
python -c "import zipfile,glob; zipfile.ZipFile(glob.glob('*.whl')[0]).extractall('.')"
chmod -R +x pgserver/pginstall/bin pgserver/pginstall/lib
export PGBIN=$PWD/pgserver/pginstall/bin LD_LIBRARY_PATH=$PWD/pgserver/pginstall/lib

$PGBIN/initdb -D ~/pgdata -U lostfound --auth=trust -E UTF8
$PGBIN/pg_ctl -D ~/pgdata -o "-p 5455 -k /tmp -h 127.0.0.1" -l ~/pgdata/server.log start
$PGBIN/createdb -h 127.0.0.1 -p 5455 -U lostfound lostfound_db
$PGBIN/psql -h 127.0.0.1 -p 5455 -U lostfound -d lostfound_db -f ../database/init/001_extensions.sql
$PGBIN/psql -h 127.0.0.1 -p 5455 -U lostfound -d lostfound_db -f ../database/init/002_schema.sql

DB_HOST=127.0.0.1 DB_PORT=5455 pytest
```

---

## Tuning notes

- `FRAME_SKIP` / `TARGET_PROCESS_FPS` set how much video actually reaches YOLO. Abandonment is
  measured in wall-clock seconds, so lowering the rate saves CPU without changing when alerts fire.
- `OBJECT_CLASS_IDS` defaults to COCO `24, 26, 28` (backpack, handbag, suitcase). Swap in a custom
  model via `YOLO_MODEL_PATH` and adjust the ids to match its class map.
- `MATCH_MIN_SIMILARITY` is the cosine floor for a suggestion. Raise it when the gallery grows.
- `MODEL_DEVICE` defaults to `cpu` and falls back to CPU automatically if CUDA is unavailable.
