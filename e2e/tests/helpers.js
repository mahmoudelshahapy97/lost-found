/**
 * Shared vocabulary for the suite.
 *
 * The specs are ordered files run by a single worker (see playwright.config.js),
 * so they form one story: 01 checks the shell, 02 registers a camera, 03 reads
 * the alerts and gallery the seed provides, 04 files a lost report and reunites
 * it, 05 tears down what 02 created. State that has to survive between files is
 * re-read from the API rather than kept in a module variable, because each spec
 * file gets a fresh module registry.
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

export const API = "/api/v1";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ADMIN_STATE = path.join(__dirname, "..", ".auth", "admin.json");

/**
 * There is no public signup (see database/schema.sql:app_user and
 * backend/app/services/user_service.py:ensure_bootstrap_admin). The admin
 * account is whatever BOOTSTRAP_ADMIN_* the stack under test was started
 * with; override via env if a run targets a stack with different bootstrap
 * values. Operator/viewer are created by global.setup.js.
 */
export const ADMIN_CREDENTIALS = {
  username: process.env.E2E_ADMIN_USERNAME || "admin",
  password: process.env.E2E_ADMIN_PASSWORD || "ChangeMe!123",
};
export const OPERATOR_CREDENTIALS = {
  username: "e2e-operator",
  password: "E2eOperator!1",
  role: "operator",
};
export const VIEWER_CREDENTIALS = {
  username: "e2e-viewer",
  password: "E2eViewer!1",
  role: "viewer",
};

/**
 * Every 01-05 spec runs with global.setup.js's admin storageState (see
 * playwright.config.js), which gives the *browser* (the `page` fixture) a
 * working session automatically -- the SPA reads its token from localStorage
 * like any real login. The bare `request` fixture used for direct API
 * assertions in those specs is a separate context that only inherits
 * storageState's cookies, and the JSON API requires the bearer header (the
 * cookie is accepted only on the three image routes, see
 * backend/app/api/deps.py:get_image_viewer) -- so anything calling
 * `request.get/post/patch/delete` directly needs this attached explicitly.
 */
export function authHeaders() {
  const state = JSON.parse(fs.readFileSync(ADMIN_STATE, "utf-8"));
  const origin = state.origins?.find((o) => (o.localStorage || []).length > 0);
  const token = origin?.localStorage?.find((e) => e.name === "lost-found:access-token")?.value;
  if (!token) {
    throw new Error(
      `No access token found in ${ADMIN_STATE}. Did the "setup" project run first?`
    );
  }
  return { Authorization: `Bearer ${token}` };
}

/** The camera every spec after 01 operates on. Fixed name: the backend enforces
 *  uniqueness on it, so a stable name also means a re-run cleans up after itself. */
export const CAMERA_NAME = "E2E Camera — arrivals";
export const CAMERA_LOCATION = "Building 1, Floor 1";

/** Resolved by the api container, not by the browser, so a service name is
 *  correct here and "localhost" would mean the container itself. */
export const CAMERA_SOURCE = "rtsp://mediamtx:8554/lostfound";

/** Seeded by database/seed.sql. Used to assert against known rows without
 *  needing the ML stack to have produced anything. */
export const SEED = {
  cameraId: "11111111-1111-4111-8111-000000000001",
  cameraName: "Terminal 1 - Arrivals Hall",
  openEventId: "22222222-2222-4222-8222-000000000001",
  foundBlackBackpack: "33333333-3333-4333-8333-000000000001",
  lostBlackBackpack: "44444444-4444-4444-8444-000000000001",
  lostRedSuitcase: "44444444-4444-4444-8444-000000000002",
};

/** Find a camera by name through the API, or null when it is not registered. */
export async function findCamera(request, name = CAMERA_NAME) {
  const response = await request.get(`${API}/cameras`, { headers: authHeaders() });
  if (!response.ok()) return null;
  const list = await response.json();
  return list.find((camera) => camera.name === name) || null;
}

export async function deleteCameraIfPresent(request, name = CAMERA_NAME) {
  const camera = await findCamera(request, name);
  if (!camera) return false;
  // Stop first: deleting a camera out from under a running worker leaves it
  // holding a capture the API can no longer address.
  await request
    .post(`${API}/cameras/${camera.camera_id}/stop`, { headers: authHeaders() })
    .catch(() => {});
  await request.delete(`${API}/cameras/${camera.camera_id}`, { headers: authHeaders() });
  return true;
}

/** Remove any lost report this suite filed, so a re-run starts clean. */
export async function deleteLostReports(request, marker) {
  const response = await request.get(`${API}/lost-items?per_page=100`, { headers: authHeaders() });
  if (!response.ok()) return 0;
  const { lost_items: items = [] } = await response.json();
  const ours = items.filter((item) => item.description?.includes(marker));
  // There is no DELETE for a lost item; the suite instead keys its report on a
  // marker string so a leftover is identifiable rather than mistaken for seed
  // data. Returning the count lets a spec assert on what it left behind.
  return ours.length;
}

/**
 * Poll an API predicate until it holds. Used for the things a UI assertion
 * cannot wait on cheaply — a CPU-bound embedding call producing its first
 * result, or a worker reaching a connected state.
 */
export async function waitForApi(
  request,
  path,
  predicate,
  { timeout = 90_000, interval = 2000 } = {}
) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    const response = await request.get(`${API}${path}`, { headers: authHeaders() });
    if (response.ok()) {
      last = await response.json();
      if (predicate(last)) return last;
    }
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
  throw new Error(
    `Timed out after ${timeout}ms waiting on ${path}. Last payload: ${JSON.stringify(last)?.slice(
      0,
      800
    )}`
  );
}

/**
 * Console and page errors are collected rather than asserted inline: a React
 * page that throws still renders its shell, so a passing visual assertion can
 * hide a broken component.
 */
export function collectPageProblems(page) {
  const problems = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    // The image endpoints answer 404 for a row whose blob was never stored,
    // and 503 for a snapshot when the RTSP source is not reachable. Both are
    // states ItemImage renders a fallback for, so the browser logging the
    // failed <img> load is expected rather than a defect.
    if (/favicon|ERR_ABORTED|net::ERR_/i.test(text)) return;
    if (/Failed to load resource/i.test(text) && /40[34]|503/.test(text)) return;
    problems.push(`console: ${text}`);
  });
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  return problems;
}

/** A 1x1 PNG, as the bytes a file input would hand over. Enough to exercise the
 *  upload path and the CLIP embedding without shipping a fixture image. */
export const TINY_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64"
);
