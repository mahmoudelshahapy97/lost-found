# Database

Postgres 17 + [pgvector](https://github.com/pgvector/pgvector). Five tables carry
the feature itself: cameras are watched, an abandoned object becomes an **event**,
the crop from that event becomes a searchable **found item**, a person files a
**lost item**, and a **match result** ties the last two together.

```
camera ──< abandoned_event ──< found_item ──┐
                                            ├──< match_result >── lost_item
                                            ┘
```

Two more carry the operator console's accounts: `app_user` (username, email,
Argon2 password hash, role, `token_version`) and `refresh_session` (one row per
logged-in device, keyed by the refresh token's `jti`). Neither is seeded — the
first admin is created by the API at startup if `app_user` is empty (see
`backend/app/services/user_service.py:ensure_bootstrap_admin`).

## Layout

| Path | Runs when | Contents |
| --- | --- | --- |
| `init/001_extensions.sql` | first boot, automatic | `vector`, `pgcrypto` |
| `init/002_schema.sql` | first boot, automatic | tables, constraints, indexes |
| `seed/001_seed.sql` | on demand | demo cameras, events, items, matches |
| `queries/*.sql` | never automatic | reference queries, one file per area |

`init/` is bind-mounted into `/docker-entrypoint-initdb.d/` by
`backend/docker-compose.yml`, which Postgres executes **once**, in filename order,
on the first boot of an empty data volume. Editing a file in `init/` does nothing
to a database that already exists — see *Resetting* below.

`queries/` is documentation, not migration. Each statement is annotated with the
endpoint or service function that issues it, so a query can be pasted into `psql`
and run in isolation while debugging. Parameters use asyncpg's `$1, $2` style.

## Applying the schema

The compose stack does it for you:

```bash
cd backend
docker compose up -d db
```

Against a database that already exists, or one you manage elsewhere:

```bash
docker compose exec -T db psql -U lostfound -d lostfound_db < ../database/init/001_extensions.sql
docker compose exec -T db psql -U lostfound -d lostfound_db < ../database/init/002_schema.sql
```

Every statement is `IF NOT EXISTS`, so re-applying is a no-op.

## Seeding

The seed is deliberately **not** in `init/`, so a fresh stack comes up empty.
Load it when you want the UI to have something to render:

```bash
cd backend
docker compose exec -T db psql -U lostfound -d lostfound_db < ../database/seed/001_seed.sql
```

It inserts 4 cameras, 6 events across all four statuses, 6 found items, 4 lost
reports and 2 matches (one confirmed). Every row uses a fixed UUID and every
insert is `ON CONFLICT DO NOTHING`, so it is safe to run repeatedly.

Two lost reports are planted near a specific found item's vector, so
`GET /lost-items/{id}/matches` returns a believable ranking without ever running
CLIP. Those vectors come from `demo_embedding()` / `demo_embedding_near()`, which
the seed defines, uses, and drops again in the same transaction — nothing is left
behind in the schema.

## Resetting

Init scripts only run against an empty volume. To start over:

```bash
cd backend
docker compose down -v          # -v drops lostfound_pgdata, and with it all data
docker compose up -d db
```

## Connecting

| From | Command |
| --- | --- |
| Host | `psql postgresql://lostfound:lostfound_pass@localhost:5436/lostfound_db` |
| Container | `docker compose exec db psql -U lostfound -d lostfound_db` |
| API container | `DB_HOST=db`, `DB_PORT=5432` (compose network) |

The host port is set by `backend/docker-compose.override.yml`; the default in
`docker-compose.yml` is 5433.

## Notes on the schema

- **`VECTOR(512)`** is the CLIP ViT-B-32 embedding width. Changing
  `CLIP_MODEL_NAME` changes this dimension, and the column has to change with it.
- **HNSW over `vector_cosine_ops`** is what keeps candidate lookup off a
  sequential scan. It is only used when the query orders by the raw `<=>`
  distance — ordering by `1 - (a <=> b)` silently falls back to a full scan.
- **`UNIQUE (camera_id, track_key)`** on `abandoned_event` makes event recording
  idempotent: a worker replaying a track produces no second alert.
- **`found_item.camera_id`** is `ON DELETE SET NULL` while `event_id` cascades,
  so deleting a camera removes its alerts but leaves the harvested items
  searchable.
- **Blobs live in the row**: `frame_jpeg` and `crop_jpeg` are `BYTEA`. This keeps
  deployment to one service, at the cost of table size — see
  `queries/03_found_items.sql :name found_gallery_size` and
  `queries/02_events.sql :name purge_old_frames`.
