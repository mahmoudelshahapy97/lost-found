import { expect, test } from "@playwright/test";
import { API, SEED, authHeaders } from "./helpers.js";

/**
 * How an alert reaches the people watching: the Alerts menu entry counts the
 * open ones, the Alerts page keeps itself current, a new alert pops up on any
 * page, and an account can switch its alert emails off and on.
 *
 * The pop-up test feeds the console a "newer" alert through page.route rather
 * than waiting for a camera to detect one, which would make it slow and
 * nondeterministic. Everything else talks to the real API.
 */
test.describe.configure({ mode: "serial" });

async function openAlerts(request) {
  const response = await request.get(`${API}/events/stats`, { headers: authHeaders() });
  return (await response.json()).data.open;
}

test("the Alerts menu entry counts the open alerts", async ({ page, request }) => {
  test.skip((await openAlerts(request)) === 0, "no open alerts — load database/seed.sql");
  await page.goto("/lost-items");

  const entry = page.getByRole("navigation").getByRole("link", { name: /^Alerts/ });
  // A camera may raise one while we look, so compare against a fresh count.
  await expect
    .poll(async () => {
      const shown = (await entry.innerText()).replace(/\D+/g, "");
      const open = await openAlerts(request);
      return shown === String(Math.min(open, 99)) || (open > 99 && shown === "99");
    }, { timeout: 30_000 })
    .toBe(true);
});

test("the Alerts page refreshes on its own", async ({ page }) => {
  const isList = (r) => r.method() === "GET" && /\/api\/v1\/events\?/.test(r.url());
  await Promise.all([page.waitForRequest(isList), page.goto("/events")]);
  await expect(page.getByText(/Updates every \d+ s/)).toBeVisible();
  // A second fetch with nobody touching the page.
  await page.waitForRequest(isList, { timeout: 30_000 });
});

test("a new alert pops up wherever you are and opens it", async ({ page }) => {
  const future = new Date(Date.now() + 60 * 60 * 1000).toISOString();
  let statsCalls = 0;

  // The first stats answer is the baseline; every later one reports an alert
  // newer than anything stored, as if a camera had just raised it.
  await page.route("**/api/v1/events/stats*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    statsCalls += 1;
    if (statsCalls > 1) body.data = { ...body.data, last_event_at: future };
    await route.fulfill({ response, json: body });
  });
  // The watcher's own lookup of what arrived (per_page=5, no filters).
  await page.route(/\/api\/v1\/events\?per_page=5$/, (route) =>
    route.fulfill({
      json: {
        total: 1,
        page: 1,
        per_page: 5,
        events: [
          {
            event_id: SEED.openEventId,
            camera_id: SEED.cameraId,
            camera_name: "E2E Pop-up Camera",
            class_name: "bag",
            abandoned_at: future,
            status: "OPEN",
          },
        ],
      },
    })
  );

  await page.goto("/found-items");
  const popup = page.getByRole("alert").filter({ hasText: "New alert" });
  await expect(popup).toContainText("abandoned bag on E2E Pop-up Camera", { timeout: 40_000 });

  await popup.getByRole("button", { name: "View" }).click();
  await expect(page).toHaveURL(new RegExp(`/events/${SEED.openEventId}$`));
});

test("an account can switch its alert emails off and on", async ({ page, request }) => {
  const options = await (await request.get(`${API}/auth/options`)).json();
  test.skip(!options.alert_emails, "the API sends no alert emails (SMTP_HOST is not set)");

  const me = async () =>
    (await (await request.get(`${API}/auth/me`, { headers: authHeaders() })).json()).alert_emails;
  const toggle = async () => {
    await page.getByRole("button", { name: "Account menu" }).click();
    await page.getByRole("menuitem", { name: "Email me new alerts" }).click();
  };

  await page.goto("/");
  const before = await me();
  await toggle();
  await expect(page.getByText(before ? "Alert emails turned off." : "New alerts will be emailed to you.")).toBeVisible();
  await expect.poll(me).toBe(!before);

  await page.keyboard.press("Escape");
  await toggle();
  await expect.poll(me).toBe(before);
});
