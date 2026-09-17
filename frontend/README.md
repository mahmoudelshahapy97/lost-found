# Frontend — Lost & Found

Operator console for the abandoned-object detection and lost/found matching
service. **Vite + React 18 + react-router-dom 6 + MUI 6**, talking to the
FastAPI backend through a dev proxy.

## Quick start

The backend must be running first (see `../backend/README.md`), or bring the
whole stack up with `docker compose up -d --build` from `features/lost&found`.

```bash
cd "features/lost&found/frontend"       # quote the path — it contains '&'
npm install
cp .env.example .env                    # adjust VITE_API_TARGET if needed
npm run dev
```

Open <http://localhost:5173>.

> **Windows note.** The `&` in the directory name breaks npm's `cmd.exe` script
> shim: `npm run dev` fails with a truncated path. Run it from WSL or Git Bash,
> or invoke Vite directly — `node node_modules/vite/bin/vite.js dev`.

## The proxy, and why there is one

`vite.config.js` forwards `/api`, `/health`, `/docs`, `/redoc` and
`/openapi.json` to the backend, so **the browser only ever makes same-origin
requests**. Two things fall out of that, and both matter:

- **No CORS.** `CORS_ORIGINS` in `backend/.env` lists a fixed set of origins,
  and it cannot know the port a dev server happened to bind. A same-origin
  proxy sidesteps the negotiation entirely.
- **`<img>` works against the binary endpoints.** Camera snapshots, event
  frames and found-item crops are `image/jpeg` responses handed straight to an
  `<img>`, which can carry neither headers nor a preflight response.

`/health` needs its own proxy entry because it is mounted on the app root,
outside the `/api/v1` prefix — it is the probe behind the health chip in the
app bar.

The target defaults to `http://127.0.0.1:8003`, because
`backend/docker-compose.override.yml` publishes the API on 8003 rather than the
documented 8000, so this stack coexists with the other feature stacks. Override
with `VITE_API_TARGET`.

### In production

`Dockerfile` builds the bundle and serves it from nginx, with
`nginx.conf.template` doing what the dev proxy does. **Keep the two in step** —
a path proxied in dev but not in nginx is a 404 that only appears after a
build.

Two settings there are not optional:

- `try_files $uri $uri/ /index.html` — this is a `BrowserRouter`, so a hard
  refresh on `/lost-items/<uuid>` asks the server for a path that is not on disk.
- `client_max_body_size 12m` — reported photos are multipart uploads capped at
  10 MB by `MAX_UPLOAD_BYTES`. nginx defaults to 1 MB and would reject them
  first, with a 413 the operator cannot act on.

## Routes

| Path | Page |
|---|---|
| `/` | Dashboard — open alerts, unclaimed items, waiting reports |
| `/cameras` | Registered cameras, with worker controls |
| `/cameras/new` · `/cameras/:id/edit` | Create / edit a camera |
| `/cameras/:id` | One camera: snapshot, config, live tracked objects |
| `/events` | Alert history (filters live in the URL) |
| `/events/:id` | One alert: annotated frame, timeline, triage |
| `/lost-items` | Reports people have filed |
| `/lost-items/new` | Report a lost item, with a photo |
| `/lost-items/:id` | One report and its ranked candidates |
| `/found-items` | The auto-harvested found gallery |
| `/search` | Ad-hoc search by photo or description |
| `/system` | Workers and the configuration in force |

Filters on `/events`, `/lost-items` and `/found-items` live in the query string,
so a filtered view is a shareable link that survives a reload.

## Layout

```
src/
├── api/
│   ├── client.js      axios instance, error-shape flattening, media URLs
│   └── endpoints.js   one function per backend route
├── components/        DataStates, StatusChips, ItemImage, dialogs, toasts
├── hooks/
│   ├── usePolling.js  interval fetch with abort + tab-visibility pause
│   └── useAsync.js    one-shot fetch, same abort discipline
├── layouts/AppLayout.jsx    sidebar, backend health chip, theme toggle
├── pages/             one file per route
├── routes/AppRouter.jsx     lazy-loaded routes
└── utils/             constants (mirrors the backend enums), formatters, theme
```

## Things worth knowing before changing this

**`roi` and `settings` arrive as strings, not objects.** They are `jsonb`
columns, and asyncpg hands `jsonb` back as text unless a codec is registered —
`CameraResponse` types them as `Any`, so the JSON string reaches the browser
untouched. Everything that reads them goes through `parseJsonField`. Skip it and
`Object.keys(settings)` enumerates *character indices*.

**A blank threshold is not zero.** The camera form omits empty overrides from
the `settings` payload entirely, because an absent key means "inherit the global
value" while `0` is a real — and catastrophic — setting. `abandon_seconds: 0`
would alert on every object the moment it stopped moving.

**Images are `<img>` tags, not fetches.** Snapshots, frames and crops bypass
axios: `mediaUrl()` builds the path and the browser does the rest. Snapshot URLs
carry a cache-busting timestamp, without which a "refresh frame" click re-renders
the frame already in cache. `ItemImage` handles the 404 these endpoints
legitimately return — a crop that was never stored is an ordinary state, not a
broken-image glyph.

**Polling pauses on hidden tabs.** `usePolling` schedules the next request only
after the previous response, and skips ticks while `document.hidden`. A
forgotten wall-display tab would otherwise keep asking a CPU-bound pipeline for
live tracker state.

**The event detail page asks for `include_frame=false`.** The API can embed the
annotated frame as base64 in the JSON, which inflates it by a third and makes it
uncacheable; fetching `/events/:id/frame` as an image instead lets the browser
stream and cache it.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_TARGET` | `http://127.0.0.1:8003` | Backend origin the dev proxy forwards to |
| `VITE_PORT` | `5173` | Dev server port |
| `VITE_PREVIEW_PORT` | `4173` | `npm run preview` port |
| `VITE_API_BASE` | `/api/v1` | Path prefix the client calls |
| `VITE_POLL_INTERVAL_MS` | `5000` | Base refresh cadence |

In the container, `LF_API_URL` (default `http://api:8000`) is what nginx proxies
to — set on the `web` service in `../docker-compose.yml`.

## Scripts

```bash
npm run dev       # dev server with the proxy
npm run build     # production bundle into dist/
npm run preview   # serve dist/, proxy still applied
```
