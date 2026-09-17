import { expect, test } from "@playwright/test";
import { ADMIN_CREDENTIALS, OPERATOR_CREDENTIALS, VIEWER_CREDENTIALS } from "./helpers.js";

/**
 * Runs signed out, in its own project (see playwright.config.js) -- every
 * other spec starts already authenticated via storageState, which is the
 * right default for 01-05 but would hide the very thing this file tests: what
 * happens before and around a session existing at all.
 */
test.describe.configure({ mode: "serial" });

test("an unauthenticated visit to a protected route redirects to login", async ({ page }) => {
  await page.goto("/cameras");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "InsightEye" })).toBeVisible();
});

test("a wrong password is rejected with a visible error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(ADMIN_CREDENTIALS.username);
  await page.getByLabel("Password").fill("definitely-not-the-password");
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page.getByRole("alert")).toBeVisible({ timeout: 15_000 });
  await expect(page).toHaveURL(/\/login$/);
});

test("logging in returns the operator to the page they were headed to", async ({ page }) => {
  // /cameras redirected here; the location travels in router state (see
  // src/routes/RequireAuth.jsx) so login sends the operator back to it
  // instead of always landing on the dashboard.
  await page.goto("/cameras");
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("Username").fill(ADMIN_CREDENTIALS.username);
  await page.getByLabel("Password").fill(ADMIN_CREDENTIALS.password);
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page).toHaveURL(/\/cameras$/, { timeout: 20_000 });
});

test("a viewer sees no camera-management actions and cannot reach Users", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(VIEWER_CREDENTIALS.username);
  await page.getByLabel("Password").fill(VIEWER_CREDENTIALS.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: 20_000 });

  // No admin-only nav entry.
  await expect(page.getByRole("link", { name: "Users" })).toHaveCount(0);

  await page.goto("/cameras");
  await expect(page.getByRole("heading", { name: "Cameras", level: 5 })).toBeVisible();
  await expect(page.getByRole("link", { name: "Add camera" })).toHaveCount(0);

  // Direct navigation to an admin-only route is refused, not silently allowed.
  await page.goto("/users");
  await expect(page.getByText(/does not have permission/i)).toBeVisible();
});

test("an operator can triage but cannot reach admin-only routes", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(OPERATOR_CREDENTIALS.username);
  await page.getByLabel("Password").fill(OPERATOR_CREDENTIALS.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: 20_000 });

  await page.goto("/cameras/new");
  await expect(page.getByText(/does not have permission/i)).toBeVisible();

  await page.goto("/lost-items/new");
  await expect(page.getByRole("heading", { name: "Report a lost item", level: 5 })).toBeVisible();
});

test("logging out clears the session and protected routes redirect again", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(ADMIN_CREDENTIALS.username);
  await page.getByLabel("Password").fill(ADMIN_CREDENTIALS.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: 20_000 });

  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: /log out/i }).click();

  await expect(page).toHaveURL(/\/login$/, { timeout: 15_000 });
  await page.goto("/cameras");
  await expect(page).toHaveURL(/\/login$/);
});
