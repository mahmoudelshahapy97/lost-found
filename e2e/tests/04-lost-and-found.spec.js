import { expect, test } from "@playwright/test";
import { SEED, TINY_PNG, authHeaders, collectPageProblems } from "./helpers.js";

/**
 * The feature the whole system exists for: someone reports a lost item, the
 * gallery is ranked against it, and an operator confirms the pairing.
 *
 * The seeded reports are used for the matching assertions because each shares
 * its object type and colour with a specific found item, which makes the
 * rule-based ranking deterministic. The upload path is exercised separately.
 */
test.describe.configure({ mode: "serial" });

const MARKER = "e2e-report";

test.beforeEach(async ({ request }) => {
  const response = await request.get(`/api/v1/found-items?per_page=1`, { headers: authHeaders() });
  const body = await response.json();
  test.skip(
    body.total === 0,
    "the found gallery is empty — load database/seed.sql to run the matching specs"
  );
});

test("the report form refuses a submission with neither photo nor description", async ({
  page,
}) => {
  await page.goto("/lost-items/new");
  await expect(page.getByRole("heading", { name: "Report a lost item", level: 5 })).toBeVisible();

  // The backend answers 400 for this; catching it here keeps the operator from
  // waiting on a round trip to be told they left everything blank.
  await expect(page.getByRole("button", { name: "File report" })).toBeDisabled();
});

test("an invalid email is caught before the upload", async ({ page }) => {
  await page.goto("/lost-items/new");

  await page.getByLabel("Description").fill(`${MARKER} navy holdall`);
  await page.getByLabel("Email").fill("not-an-email");
  await page.getByRole("button", { name: "File report" }).click();

  await expect(page.getByText("Not a valid email address")).toBeVisible();
  await expect(page).toHaveURL(/\/lost-items\/new$/);
});

test("a report with a photo is filed and lands on its matching page", async ({ page, request }) => {
  const problems = collectPageProblems(page);
  await page.goto("/lost-items/new");

  await page.getByLabel("Description").fill(`${MARKER} black leather bag, red keyring`);
  await page.getByLabel("Your name").fill("E2E Reporter");
  await page.getByLabel("Email").fill("e2e@example.com");

  await page.getByLabel("Object type").click();
  await page.getByRole("option", { name: "Bag" }).click();

  // A real multipart upload: the path that decodes the photo and reads its colour.
  await page.setInputFiles('input[type="file"]', {
    name: "lost-bag.png",
    mimeType: "image/png",
    buffer: TINY_PNG,
  });
  await expect(page.getByText("lost-bag.png")).toBeVisible();

  await page.getByRole("button", { name: "File report" }).click();

  // The navigation is the signal the write landed.
  await expect(page).toHaveURL(/\/lost-items\/[0-9a-f-]{36}$/, { timeout: 30_000 });

  const listed = await (
    await request.get("/api/v1/lost-items?per_page=100", { headers: authHeaders() })
  ).json();
  const ours = listed.lost_items.find((item) => item.description?.includes(MARKER));
  expect(ours, "report was not persisted").toBeTruthy();
  expect(ours.reporter_email).toBe("e2e@example.com");
  expect(ours.class_name).toBe("bag");
  // The colour was read from the photo; matching weighs it.
  expect(ours.dominant_color).toBeTruthy();

  expect(problems, problems.join("\n")).toEqual([]);
});

test("the report appears in the list with its status", async ({ page }) => {
  await page.goto("/lost-items");

  const row = page.getByRole("row").filter({ hasText: MARKER });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await expect(row.getByText("E2E Reporter")).toBeVisible();
  await expect(row.getByText("Open", { exact: true })).toBeVisible();
});

test("a seeded report ranks its planted found item first", async ({ page }) => {
  const problems = collectPageProblems(page);
  await page.goto(`/lost-items/${SEED.lostBlackBag}`);

  await expect(page.getByText("Candidates from the found gallery")).toBeVisible();

  // Same type, same colour, found an hour after the loss: the top card must be
  // that item, scoring near the top of the scale.
  const firstCard = page.getByTestId("match-card").first();
  await expect(firstCard).toBeVisible({ timeout: 60_000 });
  await expect(firstCard).toContainText("Bag");

  const score = await firstCard.getByText(/^\d+\.\d%$/).first().textContent();
  expect(Number.parseFloat(score)).toBeGreaterThan(80);

  // The reasons are shown, not just the total.
  await expect(firstCard).toContainText("Same type");
  await expect(firstCard).toContainText("Same colour");

  expect(problems, problems.join("\n")).toEqual([]);
});

test("search filters by camera, type and time, and keeps them in the URL", async ({ page }) => {
  const problems = collectPageProblems(page);
  await page.goto("/search");

  await expect(
    page.getByRole("heading", { name: "Search the found gallery", level: 5 })
  ).toBeVisible();
  await expect(page.getByText(/\d+ items? found/)).toBeVisible();

  await page.getByLabel("Camera").click();
  await page.getByRole("option", { name: SEED.cameraName }).click();
  await expect(page).toHaveURL(new RegExp(`camera_id=${SEED.cameraId}`));
  await expect(page.getByTestId("search-result").first()).toBeVisible();

  await page.getByLabel("Object type").click();
  await page.getByRole("option", { name: "Bag" }).click();
  await expect(page).toHaveURL(/class_name=bag/);
  const results = page.getByTestId("search-result");
  await expect(results.first()).toBeVisible();
  for (const card of await results.all()) await expect(card).toContainText("Bag");

  // A quick range sets "From"; the seeded bag was found two hours ago.
  await page.getByRole("button", { name: "Last hour" }).click();
  await expect(page).toHaveURL(/start=/);
  await page.getByRole("button", { name: "Last 7 days" }).click();
  await expect(results.first()).toBeVisible();

  // Filters live in the URL, so a reload keeps the search.
  await page.reload();
  await expect(page.getByLabel("Camera")).toContainText(SEED.cameraName);
  await expect(results.first()).toBeVisible();

  expect(problems, problems.join("\n")).toEqual([]);
});

test("cards and table views show the same results", async ({ page }) => {
  await page.goto(`/search?camera_id=${SEED.cameraId}`);
  const results = page.getByTestId("search-result");
  await expect(results.first()).toBeVisible();
  const cards = await results.count();

  await page.getByRole("button", { name: "Table" }).click();
  await expect(page).toHaveURL(/view=table/);
  await expect(page.getByRole("columnheader", { name: "Camera" })).toBeVisible();
  await expect(results).toHaveCount(cards);

  await page.getByRole("button", { name: "Cards" }).click();
  await expect(page).not.toHaveURL(/view=table/);
});

test("clear filters resets the search", async ({ page }) => {
  await page.goto("/search?class_name=key&color=pink");
  await expect(page.getByText("Nothing matches these filters")).toBeVisible();

  await page.getByRole("button", { name: "Clear filters" }).first().click();
  await expect(page).toHaveURL(/\/search$/);
  await expect(page.getByText(/\d+ items? found/)).toBeVisible();
});

test("a found item can be discarded from the gallery and restored", async ({ page, request }) => {
  const foundStatus = async () =>
    (
      await (
        await request.get(`/api/v1/found-items/${SEED.foundBlackBag}`, { headers: authHeaders() })
      ).json()
    ).status;
  test.skip((await foundStatus()) !== "UNCLAIMED", "re-apply database/seed.sql to run this");

  await page.goto("/found-items");
  const card = page.locator(`[data-found-id="${SEED.foundBlackBag}"]`);
  await expect(card).toBeVisible({ timeout: 30_000 });

  await card.getByRole("button", { name: "Discard" }).click();
  await expect(card.getByRole("button", { name: "Restore" })).toBeVisible();
  await expect.poll(foundStatus).toBe("DISCARDED");

  await card.getByRole("button", { name: "Restore" }).click();
  await expect(card.getByRole("button", { name: "Discard" })).toBeVisible();
  await expect.poll(foundStatus).toBe("UNCLAIMED");
});

test("a lost report can be closed and reopened", async ({ page, request }) => {
  const listed = await (
    await request.get("/api/v1/lost-items?per_page=100", { headers: authHeaders() })
  ).json();
  const ours = listed.lost_items.find((item) => item.description?.includes(MARKER));
  test.skip(!ours, "the report from the earlier spec is missing");

  await page.goto(`/lost-items/${ours.lost_id}`);
  await page.getByRole("button", { name: "Close report" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Close report" }).click();

  await expect(page.getByRole("button", { name: "Reopen report" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Closed", { exact: true }).first()).toBeVisible();

  await page.getByRole("button", { name: "Reopen report" }).click();
  await expect(page.getByRole("button", { name: "Close report" })).toBeVisible({ timeout: 20_000 });
  const report = await (
    await request.get(`/api/v1/lost-items/${ours.lost_id}`, { headers: authHeaders() })
  ).json();
  expect(report.status).toBe("OPEN");
});

test("confirming a match resolves the report and claims the item", async ({ page, request }) => {
  // Confirming is destructive: it claims the item, which removes it from every
  // later search. On a re-run against an unseeded database there is nothing
  // left to confirm, and that is not a failure.
  const before = await (
    await request.get(`/api/v1/lost-items/${SEED.lostRedUmbrella}`, { headers: authHeaders() })
  ).json();
  test.skip(
    before.status !== "OPEN",
    `report is already ${before.status} — re-apply database/seed.sql to run this`
  );

  await page.goto(`/lost-items/${SEED.lostRedUmbrella}`);

  const firstCard = page.getByTestId("match-card").first();
  await expect(firstCard).toBeVisible({ timeout: 60_000 });

  await firstCard.getByRole("button", { name: "This is it" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Confirm match" }).click();

  // One click has to move three rows: the report resolves, the item is claimed,
  // and the alert it came from closes. Any one of those left behind is a bug.
  await expect
    .poll(
      async () => {
        const report = await (
          await request.get(`/api/v1/lost-items/${SEED.lostRedUmbrella}`, { headers: authHeaders() })
        ).json();
        return report.status;
      },
      { timeout: 45_000 }
    )
    .toBe("RESOLVED");

  const gallery = await (
    await request.get("/api/v1/found-items?per_page=100", { headers: authHeaders() })
  ).json();
  const claimed = gallery.found_items.find((item) => item.class_name === "umbrella" && item.status === "CLAIMED");
  expect(claimed, "no umbrella was marked claimed").toBeTruthy();

  await expect(page.getByText("Resolved").first()).toBeVisible({ timeout: 30_000 });
});
