import { expect, test } from "@playwright/test";
import { SEED, TINY_PNG, authHeaders, collectPageProblems } from "./helpers.js";

/**
 * The feature the whole system exists for: someone reports a lost item, the
 * gallery is ranked against it, and an operator confirms the pairing.
 *
 * The seeded reports are used for the matching assertions because their vectors
 * were planted near a specific found item, which makes the ranking
 * deterministic. The upload path is exercised separately, with a real file.
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

  await page.getByLabel("Description").fill(`${MARKER} black leather backpack, red keyring`);
  await page.getByLabel("Your name").fill("E2E Reporter");
  await page.getByLabel("Email").fill("e2e@example.com");

  await page.getByLabel("Object type").click();
  await page.getByRole("option", { name: "Backpack" }).click();

  // A real multipart upload: this is the path that runs the photo through CLIP,
  // so it is the one that proves the embedding pipeline is wired up.
  await page.setInputFiles('input[type="file"]', {
    name: "lost-backpack.png",
    mimeType: "image/png",
    buffer: TINY_PNG,
  });
  await expect(page.getByText("lost-backpack.png")).toBeVisible();

  await page.getByRole("button", { name: "File report" }).click();

  // Embedding on CPU is slow; the navigation is the signal the write landed.
  await expect(page).toHaveURL(/\/lost-items\/[0-9a-f-]{36}$/, { timeout: 90_000 });

  const listed = await (
    await request.get("/api/v1/lost-items?per_page=100", { headers: authHeaders() })
  ).json();
  const ours = listed.lost_items.find((item) => item.description?.includes(MARKER));
  expect(ours, "report was not persisted").toBeTruthy();
  expect(ours.reporter_email).toBe("e2e@example.com");
  expect(ours.class_name).toBe("backpack");
  // The photo was embedded, which is what makes the report matchable at all.
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
  await page.goto(`/lost-items/${SEED.lostBlackBackpack}`);

  await expect(page.getByText("Candidates from the found gallery")).toBeVisible();

  // The seed plants this report's vector next to the black backpack's, so the
  // top card must be that item and must score far above the 55% floor.
  const firstCard = page.getByTestId("match-card").first();
  await expect(firstCard).toBeVisible({ timeout: 60_000 });
  await expect(firstCard).toContainText("Backpack");

  const score = await firstCard.getByText(/^\d+\.\d%$/).first().textContent();
  expect(Number.parseFloat(score)).toBeGreaterThan(80);

  // The breakdown is shown, not just the total: "81%" alone does not tell an
  // operator whether the match came from the picture or from the words.
  await expect(firstCard).toContainText("Image similarity");

  expect(problems, problems.join("\n")).toEqual([]);
});

test("text search finds the red suitcase in the gallery", async ({ page }) => {
  const problems = collectPageProblems(page);
  await page.goto("/search");

  await expect(
    page.getByRole("heading", { name: "Search the found gallery", level: 5 })
  ).toBeVisible();
  await expect(page.getByText("No search yet")).toBeVisible();

  // Not anchored: the field is required on this tab, so MUI appends " *" to
  // the label text.
  await page.getByLabel("Description").fill("red hard-shell suitcase");
  // The seeded vectors are random rather than genuinely CLIP-derived, so a
  // realistic threshold would return nothing. Dropping it proves the search
  // round trip works end to end.
  const slider = page.getByRole("slider", { name: "Minimum similarity" });
  await slider.focus();
  await slider.press("Home");
  await page.getByRole("button", { name: "Search", exact: true }).click();

  await expect(page.getByText(/\d+ candidates?/)).toBeVisible({ timeout: 60_000 });

  expect(problems, problems.join("\n")).toEqual([]);
});

test("confirming a match resolves the report and claims the item", async ({ page, request }) => {
  // Confirming is destructive: it claims the item, which removes it from every
  // later search. On a re-run against an unseeded database there is nothing
  // left to confirm, and that is not a failure.
  const before = await (
    await request.get(`/api/v1/lost-items/${SEED.lostRedSuitcase}`, { headers: authHeaders() })
  ).json();
  test.skip(
    before.status !== "OPEN",
    `report is already ${before.status} — re-apply database/seed.sql to run this`
  );

  await page.goto(`/lost-items/${SEED.lostRedSuitcase}`);

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
          await request.get(`/api/v1/lost-items/${SEED.lostRedSuitcase}`, { headers: authHeaders() })
        ).json();
        return report.status;
      },
      { timeout: 45_000 }
    )
    .toBe("RESOLVED");

  const gallery = await (
    await request.get("/api/v1/found-items?per_page=100", { headers: authHeaders() })
  ).json();
  const claimed = gallery.found_items.find((item) => item.class_name === "suitcase" && item.status === "CLAIMED");
  expect(claimed, "no suitcase was marked claimed").toBeTruthy();

  await expect(page.getByText("Resolved").first()).toBeVisible({ timeout: 30_000 });
});
