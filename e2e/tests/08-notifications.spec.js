import { expect, test } from "@playwright/test";
import { API, authHeaders } from "./helpers.js";

/**
 * How an alert reaches the people watching: the Alerts menu entry counts the
 * open ones, the Alerts page keeps itself current, a notification is pushed
 * to the bell (and pops up) on any page, and an account can switch its alert
 * emails off and on.
 *
 * The bell test sends a test notification to itself rather than waiting for a
 * camera to detect something, which would make it slow and nondeterministic;
 * it still travels the real path: database row, hub, WebSocket, console.
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

test("a notification arrives live in the bell and pops up wherever you are", async ({ page }) => {
  await page.goto("/notifications");
  await expect(page.getByRole("heading", { name: "Notifications", level: 5 })).toBeVisible();
  const badge = page.getByTestId("notification-badge");
  const count = async () => Number((await badge.innerText()).replace(/\D+/g, "") || 0);
  const before = await count();

  // Pushed over the socket: no reload, no polling interval to wait out.
  await page.getByRole("button", { name: "Send a test" }).click();
  const popup = page.getByTestId("notification-popup");
  await expect(popup).toContainText("Test notification", { timeout: 15_000 });
  await expect.poll(count).toBe(before + 1);

  // Opening it from the pop-up marks it read.
  await popup.getByRole("button", { name: "View" }).click();
  await expect(page).toHaveURL(/\/notifications$/);
  await expect.poll(count).toBe(before);

  await page.getByRole("button", { name: "Notifications", exact: true }).click();
  await expect(page.getByRole("presentation").getByText("Test notification").first()).toBeVisible();
  await page.keyboard.press("Escape");
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
