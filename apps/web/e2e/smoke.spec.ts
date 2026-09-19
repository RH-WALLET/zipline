import { expect, test } from "@playwright/test";

test("the treasury page is a live tear sheet and stamps the mode unmistakably", async ({ page }) => {
  await page.goto("/");
  // running head: wordmark, current section, engine state; the mode stamp on the title block
  await expect(page.locator("header.masthead .brand")).toContainText("ZIPLINE");
  await expect(page.locator("header.masthead nav a[aria-current='page']")).toHaveText("Treasury");
  await expect(page.locator(".report-title .stamp")).toHaveText(/Demo mode|Live trading|System paused/i);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Treasury");
  // pyfolio's perf_stats table, grouped, plus the plots beside it
  const stats = page.locator('table.stats[aria-label="Performance statistics"]');
  for (const label of ["Total return", "Annual return", "Cumulative returns", "Annual volatility", "Sharpe ratio", "Calmar ratio", "Stability", "Max drawdown", "Omega ratio", "Sortino ratio", "Skew", "Kurtosis", "Tail ratio", "Daily value at risk", "Alpha", "Beta", "Information ratio"]) {
    await expect(stats).toContainText(label);
  }
  await expect(page.locator('figure[aria-label="Cumulative returns"]')).toBeVisible();
  await expect(page.locator('figure[aria-label="Underwater plot"]')).toBeVisible();
  // the ledgers
  await expect(page.locator('dl[aria-label="Zipline treasury"]')).toContainText("Net asset value");
  await expect(page.locator('section[aria-label="Strategy sleeves"]')).toContainText("ZEROIQ");
  await expect(page.locator('section[aria-label="Reconciliation"]')).toBeVisible();
  await expect(page.locator(".log .bar")).toContainText(/live|connecting|reconnecting/);
});

test("ten strategies are listed and a tear sheet exposes rules, class and provenance", async ({ page }) => {
  await page.goto("/strategies");
  for (const code of ["TREND", "MOMENTUM", "MEANREV", "BREAKOUT", "LOWVOL", "REVERSAL", "DUALMA", "RISKON", "PAIRS", "ZEROIQ"]) {
    await expect(page.getByRole("link", { name: code, exact: true }).first()).toBeVisible();
  }
  await page.goto("/strategies/ZEROIQ");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("ZEROIQ");
  const facts = page.locator(".report-title .facts");
  await expect(facts).toContainText("zipline_engine.strategies.zeroiq.ZeroIQStrategy");
  await expect(facts.getByText("NO AI", { exact: true })).toBeVisible();
  await expect(facts.getByText("DETERMINISTIC", { exact: true })).toBeVisible();
  await expect(page.locator('section[aria-label="Performance"] table.stats')).toBeVisible();
  await expect(page.locator('section[aria-label="Rules"]')).toContainText("PCG64");
  await expect(page.locator('section[aria-label="Virtual book"]')).toContainText("Virtual NAV");
});

test("the execution ledger never dresses dry runs as blockchain activity", async ({ page }) => {
  await page.goto("/executions");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Executions");
  const dryRows = page.locator('section[aria-label="Orders"] table.data tbody tr', { hasText: "DRY RUN" });
  const n = await dryRows.count();
  for (let i = 0; i < Math.min(n, 5); i++) {
    const row = dryRows.nth(i);
    await expect(row).toContainText(/dry-\d+/);
    await expect(row).toContainText("no tx (dry run)");
    expect(await row.locator("a[href*='/tx/']").count()).toBe(0);
  }
});

test("methodology, capital, universe and log pages render from the engine", async ({ page }) => {
  await page.goto("/methodology");
  await expect(page.getByText("Robinhood Markets, Inc. and its affiliates do not operate, sponsor or endorse this project.")).toBeVisible();
  await page.goto("/treasury");
  await expect(page.locator('section[aria-label="Capital accounting"]')).toContainText("Base capital");
  await expect(page.locator('figure[aria-label="Net asset value"]')).toBeVisible();
  await page.goto("/universe");
  await expect(page.locator('section[aria-label="Stock Tokens"]')).toContainText("ELIGIBLE");
  await page.goto("/events");
  await expect(page.locator('section[aria-label="Cycles"]')).toBeVisible();
  await expect(page.locator(".log .bar")).toContainText(/live|connecting|reconnecting/);
});

test("no page scrolls sideways at phone width", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  for (const path of ["/", "/strategies/TREND", "/executions", "/universe", "/events", "/methodology"]) {
    await page.goto(path);
    const widths = await page.evaluate(() => ({ doc: document.documentElement.scrollWidth, view: window.innerWidth }));
    expect(widths.doc, path).toBeLessThanOrEqual(widths.view);
  }
});
