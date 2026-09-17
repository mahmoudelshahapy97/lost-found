import { expect, test } from "@playwright/test";
import { SEED, authHeaders, collectPageProblems } from "./helpers.js";

/**
 * Reading what the system holds: alerts and their triage, the found gallery,
 * and the effective configuration.
 *
 * These assert against the rows in database/seed.sql rather than waiting on the
 * ML pipeline, so they stay fast and deterministic — the detection path itself
 * is exercised by spec 02 starting a worker.
 */
test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ request }) => {
  const response = await request.get(`/api/v1/events?per_page=1`, { headers: authHeaders() });
  const body = await response.json();
  test.skip(
    body.total === 0,
    "no events in the database — load database/seed.sql to run the observability specs"
  );
});

test("the alert list renders the seeded events", async ({ page }) => {
  const problems = collectPageProblems(page);
  await page.goto("/events");

  await expect(page.getByRole("heading", { name: "Alerts", level: 5 })).toBeVisible();
  // Six seeded events across four statuses; the table must show more than one.
  await expect(page.getByRole("row")).not.toHaveCount(1);
  await expect(page.getByRole("cell", { name: "Backpack" }).first()).toBeVisible();

  expect(problems, problems.join("\n")).toEqual([]);
});

test("filtering by status narrows the list and lands in the URL", async ({ page }) => {
  await page.goto("/events");

  await page.getByLabel("Status").click();
  await page.getByRole("option", { name: "False Positive" }).click();

  // The filter is query-string state, so the filtered view is a real, linkable
  // URL that survives a reload — that is the point of putting it there.
  await expect(page).toHaveURL(/status=FALSE_POSITIVE/);
  await expect(page.getByText("False Positive").first()).toBeVisible();
  await expect(page.getByRole("cell", { name: "Open", exact: true })).toHaveCount(0);

  await page.reload();
  await expect(page.getByText("False Positive").first()).toBeVisible();
});

test("filtering by object type composes with the status filter", async ({ page }) => {
  await page.goto("/events?status=OPEN");

  await page.getByLabel("Object").click();
  await page.getByRole("option", { name: "Suitcase" }).click();

  await expect(page).toHaveURL(/status=OPEN/);
  await expect(page).toHaveURL(/class_name=suitcase/);

  const rows = page.getByRole("row");
  const count = await rows.count();
  for (let index = 1; index < count; index += 1) {
    await expect(rows.nth(index)).toContainText("Suitcase");
  }
});

test("a filter combination with no matches says so rather than looking broken", async ({
  page,
}) => {
  await page.goto("/events?status=RESOLVED&class_name=backpack");

  await expect(page.getByText("Nothing matches these filters")).toBeVisible();
  // Two of these on screen: one in the filter bar, one in the empty state.
  // Click the empty state's, which is the one an operator is looking at.
  await page.getByRole("button", { name: "Clear filters" }).last().click();
  await expect(page).toHaveURL(/\/events$/);
});

test("an alert opens to its detail, timeline and triage actions", async ({ page }) => {
  const problems = collectPageProblems(page);
  await page.goto(`/events/${SEED.openEventId}`);

  await expect(page.getByRole("heading", { name: /abandoned backpack/i, level: 5 })).toBeVisible();
  // exact: the frame caption also ends "...was declared abandoned", and a
  // substring match would resolve to two elements.
  await expect(page.getByText("First seen", { exact: true })).toBeVisible();
  await expect(page.getByText("Declared abandoned", { exact: true })).toBeVisible();
  // The owner walked away — that is what made it an alert rather than a bag
  // sitting next to its owner.
  await expect(page.getByText(/#4088 walked away/)).toBeVisible();

  for (const action of ["Acknowledge", "Resolve", "False positive"]) {
    await expect(page.getByRole("button", { name: action })).toBeVisible();
  }

  expect(problems, problems.join("\n")).toEqual([]);
});

test("acknowledging an alert persists and disables the button", async ({ page, request }) => {
  await page.goto(`/events/${SEED.openEventId}`);

  const acknowledge = page.getByRole("button", { name: "Acknowledge" });
  await acknowledge.click();

  await expect(acknowledge).toBeDisabled({ timeout: 30_000 });

  const response = await request.get(`/api/v1/events/${SEED.openEventId}?include_frame=false`, {
    headers: authHeaders(),
  });
  expect((await response.json()).status).toBe("ACKNOWLEDGED");

  // Put it back, so a re-run starts from the same state the seed describes.
  await page.getByRole("button", { name: "False positive" }).click();
  await request.patch(`/api/v1/events/${SEED.openEventId}/status`, {
    headers: authHeaders(),
    data: { status: "OPEN" },
  });
});

test("the found gallery renders the harvested crops", async ({ page }) => {
  const problems = collectPageProblems(page);
  await page.goto("/found-items");

  await expect(page.getByRole("heading", { name: "Found gallery", level: 5 })).toBeVisible();
  await expect(page.getByText("Backpack").first()).toBeVisible();
  // Every item carries a status; UNCLAIMED is what makes it a match candidate.
  await expect(page.getByText("Unclaimed").first()).toBeVisible();

  expect(problems, problems.join("\n")).toEqual([]);
});

test("the gallery status filter excludes claimed items", async ({ page }) => {
  await page.goto("/found-items?status=CLAIMED");

  // The seed confirms one match, which claims exactly one item.
  await expect(page.getByText("Claimed").first()).toBeVisible();
  await expect(page.getByText("Unclaimed")).toHaveCount(0);
});

test("the system page reports workers and the config in force", async ({ page }) => {
  const problems = collectPageProblems(page);
  await page.goto("/system");

  await expect(page.getByRole("heading", { name: "Workers & config", level: 5 })).toBeVisible();
  // The value, not the panel caption that also says "connected" — the stat
  // card renders its value as an h4.
  await expect(page.getByRole("heading", { name: "Connected", level: 4 })).toBeVisible({
    timeout: 30_000,
  });

  // The tuning values are the first thing to check when an alert fires late, so
  // the groups must actually render rather than sit empty behind a failed call.
  for (const group of ["Detection", "Abandonment", "Stream", "Matching"]) {
    await expect(page.getByRole("heading", { name: group, exact: true })).toBeVisible();
  }
  await expect(page.getByText("abandon seconds")).toBeVisible();

  expect(problems, problems.join("\n")).toEqual([]);
});
