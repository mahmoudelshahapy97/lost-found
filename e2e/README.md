# End-to-end tests

Playwright driving the operator console in a real browser, against the real
stack: nginx serving the built bundle, FastAPI behind it, Postgres with pgvector
behind that. Nothing is mocked. When these pass, the wiring works — not just the
React components.

## Running

```bash
cd features/lost&found
docker compose up -d --build                    # postgres + api + web
docker compose exec -T postgres psql -U lostfound -d lostfound_db < database/seed.sql
./e2e/run.sh                                    # whole suite
./e2e/run.sh tests/04-lost-and-found.spec.js    # one file
```

`run.sh` executes the tests inside `mcr.microsoft.com/playwright`, so nothing
has to be installed locally beyond Docker — the image already carries the
browsers and their system libraries. It runs with `--network host`, which is
why `BASE_URL` defaults to `http://localhost:8082` rather than a compose
service name.

Results land in:

| Path | What |
| --- | --- |
| `playwright-report/` | HTML report — `npx playwright show-report` |
| `results.json` | machine-readable summary |
| `test-results/` | screenshots, video and traces for failures |

To run against a different origin — a staging deploy, or the Vite dev server:

```bash
BASE_URL=http://localhost:5173 ./e2e/run.sh
```

## The seed is a fixture

Specs 03 and 04 assert against the rows in `database/seed.sql` rather than
waiting for the detection pipeline to produce something. That is deliberate:
CLIP and YOLO on CPU make a full detect-to-alert cycle minutes long and
non-deterministic, which is a bad foundation for assertions about *the console*.

Both files `test.skip` themselves when the tables are empty, with a message
naming the seed, so an unseeded database reads as "load the fixture" rather than
as a wall of failures.

The seeded vectors are reproducible random stand-ins, not real CLIP embeddings —
two lost reports are planted next to a specific found item so the ranking is
deterministic. That is why `04` drops the similarity threshold to 0 for the
free-text search: a realistic floor would correctly reject a random vector, and
the assertion is about the round trip, not about CLIP's judgement.

Spec 02 does start a real worker, so the RTSP path is exercised. Bring up the
stream first, or that spec asserts only that the worker registered:

```bash
docker compose --profile testing up -d mediamtx
```

## Auth: one login, shared by everything

Every route but `/health` and `/login` needs a session (see the backend's
Auth section in `../backend/README.md`). Rather than have five files each log
in, `global.setup.js` runs once as a Playwright *setup project* — logs in as
the bootstrap admin through the real `/login` page, saves the browser's
storageState (the access/refresh tokens `localStorage` holds, plus the
httpOnly cookie the three image routes accept) to `.auth/admin.json`, and
seeds one operator and one viewer account for role assertions. `chromium`
(the project `01`–`05` run under) starts every test already signed in with
that state, so those five files need no login step of their own.

The bare `request` fixture used for direct API assertions is a *separate*
context from the browser — it only inherits storageState's cookie, and the
JSON API requires the bearer header (the cookie is scoped to the image routes
only, see `get_image_viewer` in `backend/app/api/deps.py`). Anywhere a spec
calls `request.get/post/patch/delete` directly, it passes
`{ headers: authHeaders() }` (`tests/helpers.js`), which reads the token back
out of `.auth/admin.json`.

`00-auth.spec.js` runs in its own project, signed out on purpose: the login
page itself, a wrong password, the redirect-and-return-to flow, and what a
viewer and an operator can and cannot reach. It still depends on the setup
project, for the operator/viewer accounts.

## The specs are one story

`playwright.config.js` runs a single worker, files in order, and they share
state:

| File | What it covers |
| --- | --- |
| `00-auth.spec.js` | Login, bad credentials, redirects, role boundaries — runs signed out |
| `01-shell.spec.js` | Health, every route renders, nav, 404, theme toggle |
| `02-camera-lifecycle.spec.js` | Register a camera through the form, validation, start its worker |
| `03-observability.spec.js` | Alert list and filters, triage, gallery, system page |
| `04-lost-and-found.spec.js` | File a report with a photo, ranking, search, confirm a match |
| `05-teardown.spec.js` | Edit, stop, delete — and check nothing else was taken with it |

Anything that has to survive between files is re-read from the API
(`findCamera`), never kept in a module variable: each spec file gets a fresh
module registry.

They are ordered rather than parallel because two files racing would fight over
the camera-name uniqueness constraint and over the same found items — confirming
a match claims an item, which removes it from every other search.

## Conventions worth keeping

**`collectPageProblems` runs on most specs.** A React page that throws still
renders its shell, so a passing visual assertion can hide a broken component.
Console errors are collected and asserted empty at the end. 404s from image
endpoints are filtered out — a crop that was never stored is a state the UI
handles on purpose.

**Assertions check the API as well as the page.** A form that navigates
correctly but wrote nothing is the failure mode worth catching, so the write
specs read the row back. `02` in particular checks that a blank threshold is
*absent* from `settings`, not stored as `0`.

**`05` verifies the seed survived.** Deleting a camera cascades to its events,
so a stray delete would silently gut the fixture and leave the next run failing
somewhere unrelated.
