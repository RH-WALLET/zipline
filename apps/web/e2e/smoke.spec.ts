import { expect, test } from "@playwright/test";

test("dashboard is a live backtest report and states the mode unmistakably", async ({ page }) => {
  await page.goto("/");
  // the Quantopian-red bar and the mode bar
  await expect(page.locator("header.q-nav .q-logo .word")).toHaveText("ZIPLINE");
  await expect(page.locator("header.q-nav nav a[aria-current='page']")).toHaveText("Dashboard");
  const mode = page.locator(".mode-bar strong");
  await expect(mode).toHaveText(/DEMO MODE — LIVE TRADING DISABLED|LIVE TRADING|SYSTEM PAUSED/);
  // the report head and the nine statistics
  await expect(page.getByRole("heading", { level: 1 })).toContainText("ZIPLINE treasury");
  const stats = page.getByRole("list", { name: "Performance statistics" });
  for (const label of ["Total returns", "Benchmark returns", "Alpha", "Beta", "Sharpe", "Sortino", "Information ratio", "Volatility", "Max drawdown"]) {
    await expect(stats).toContainText(label);
  }
  await expect(page.locator('section[aria-label="Cumulative performance"]')).toBeVisible();
  // tabs and the overview ledger
  await expect(page.getByRole("tab", { name: /Overview/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('dl[aria-label="Zipline treasury"]')).toContainText("NAV");
  await page.getByRole("tab", { name: /Strategies/ }).click();
  await expect(page.locator('section[aria-label="Strategy sleeves"]')).toContainText("ZEROIQ");
  await page.getByRole("tab", { name: /Logs/ }).click();
  await expect(page.locator(".console .bar")).toContainText(/live|reconnecting/);
});

test("ten strategies are listed and a report page exposes rules, source and provenance", async ({ page }) => {
  await page.goto("/strategies");
  for (const code of ["TREND", "MOMENTUM", "MEANREV", "BREAKOUT", "LOWVOL", "REVERSAL", "DUALMA", "RISKON", "PAIRS", "ZEROIQ"]) {
    await expect(page.getByRole("link", { name: code, exact: true }).first()).toBeVisible();
  }
  await page.goto("/strategies/ZEROIQ");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("ZEROIQ");
  await expect(page.getByText("NO AI", { exact: true })).toBeVisible();
  await expect(page.getByText("DETERMINISTIC", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: /Source/ }).click();
  await expect(page.locator('section[aria-label="Rules"]')).toContainText("PCG64");
  await expect(page.locator('section[aria-label="Provenance"]')).toContainText("zeroiq.ZeroIQStrategy");
});

test("execution ledger never dresses dry runs as blockchain activity", async ({ page }) => {
  await page.goto("/executions");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Execution ledger");
  const dryRows = page.locator("table.table tbody tr", { hasText: "DRY RUN" });
  const n = await dryRows.count();
  for (let i = 0; i < Math.min(n, 5); i++) {
    const row = dryRows.nth(i);
    await expect(row).toContainText(/dry-\d+/);
    expect(await row.locator("a[href*='/tx/']").count()).toBe(0);
  }
});

test("methodology, treasury, universe and logs render from the engine", async ({ page }) => {
  await page.goto("/methodology");
  await expect(page.getByText("Robinhood Markets, Inc. and its affiliates do not operate, sponsor or endorse this project.")).toBeVisible();
  await page.goto("/treasury");
  await expect(page.locator('section[aria-label="Capital accounting"]')).toContainText("Base capital");
  await page.goto("/universe");
  await expect(page.locator('section[aria-label="Stock Tokens"]')).toContainText("ELIGIBLE");
  await page.goto("/events");
  await expect(page.locator(".console .bar")).toContainText(/live|reconnecting/);
});
