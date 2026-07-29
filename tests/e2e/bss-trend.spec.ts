import { expect, Page, test } from '@playwright/test';

const pageBugs = new WeakMap<Page, string[]>();
const timeframes = [
  ['Weekly', '/rankings/weekly.html'],
  ['Monthly', '/rankings/monthly.html'],
  ['Quarterly', '/rankings/quarterly.html'],
  ['Yearly', '/rankings/yearly.html'],
] as const;

function installBugWatch(page: Page, baseURL: string): void {
  const bugs: string[] = [];
  const localOrigin = new URL(baseURL).origin;
  pageBugs.set(page, bugs);

  page.on('pageerror', (error) => {
    bugs.push(`pageerror: ${error.message}`);
  });

  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const text = message.text();
    // External image/font failures are noisy and network-dependent. Same-origin
    // 4xx/5xx and JS exceptions are caught separately below.
    if (/Failed to load resource|net::ERR_/i.test(text)) return;
    bugs.push(`console error: ${text}`);
  });

  page.on('response', (response) => {
    const url = new URL(response.url());
    if (url.origin !== localOrigin) return;
    if (response.status() >= 400) {
      bugs.push(`local ${response.status()} response: ${url.pathname}`);
    }
  });

  page.on('requestfailed', (request) => {
    const url = new URL(request.url());
    if (url.origin !== localOrigin) return;
    bugs.push(`local request failed: ${url.pathname} ${request.failure()?.errorText ?? ''}`.trim());
  });
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

test.beforeEach(async ({ page, baseURL }) => {
  installBugWatch(page, baseURL ?? 'http://127.0.0.1:8765');
});

test.afterEach(async ({ page }) => {
  expect.soft(pageBugs.get(page) ?? []).toEqual([]);
});

test.describe('BSS Trend Ranking Playwright bug + operation tests', () => {
  test('home page renders the ranking dashboard with product visuals', async ({ page }) => {
    await page.goto('/index.html');

    await expect(page).toHaveTitle(/Home · BSS Trend Ranking/);
    await expect(page.getByRole('heading', { name: 'Beauty Supply 제품별 트렌드 순위' })).toBeVisible();
    await expect(page.getByText(/\d+ items · 8 categories/)).toBeVisible();
    await expect(page.locator('.podium-card')).toHaveCount(3);

    const rankCards = page.locator('.rank-card');
    await expect(rankCards.first()).toBeVisible();
    expect(await rankCards.count()).toBeGreaterThanOrEqual(8);

    const missingImageMetadata = await page.locator('img').evaluateAll((images) =>
      images
        .map((image) => ({ src: image.getAttribute('src') ?? '', alt: image.getAttribute('alt') ?? '' }))
        .filter((image) => image.src.trim().length === 0 || image.alt.trim().length === 0),
    );
    expect(missingImageMetadata).toEqual([]);
  });

  test('timeframe tabs and category chips navigate to working ranking sections', async ({ page }) => {
    for (const [label, path] of timeframes) {
      await page.goto(path);

      await expect(page.locator('.tabs a.active')).toHaveText(label);
      await expect(page.getByRole('heading', { name: `${label} ranking` })).toBeVisible();
      expect(await page.locator('#all-items .rank-card').count()).toBeGreaterThan(0);

      const categoryChips = page.locator('.category-strip a');
      expect(await categoryChips.count()).toBeGreaterThan(1);

      const chipTargets = await categoryChips.evaluateAll((links) =>
        links.map((link) => ({
          text: (link.textContent ?? '').trim(),
          href: (link as HTMLAnchorElement).getAttribute('href') ?? '',
        })),
      );

      for (const target of chipTargets) {
        if (!target.href.includes('#')) continue;
        const hash = target.href.split('#')[1];
        expect(hash, `category chip "${target.text}" must include a hash target`).toBeTruthy();
        const exists = await page.evaluate((id) => Boolean(document.getElementById(id)), decodeURIComponent(hash));
        expect(exists, `${path} is missing category anchor #${hash}`).toBe(true);
      }
    }

    await page.goto('/rankings/weekly.html');
    await page.locator('.category-strip a[href="#wigs-hair-pieces"]').click();
    await expect(page.locator('#wigs-hair-pieces .rank-card').first()).toBeVisible();
  });

  test('ranking cards click through to item detail pages and back', async ({ page }) => {
    await page.goto('/rankings/weekly.html');

    const firstCard = page.locator('#all-items .rank-card').first();
    await expect(firstCard).toBeVisible();
    const itemName = (await firstCard.locator('h3').innerText()).trim();
    await firstCard.locator('.rank-hit').click();

    await expect(page.getByRole('heading', { name: itemName })).toBeVisible();
    await expect(page.locator('.detail-img img')).toHaveAttribute('src', /.+/);
    expect(await page.locator('.metrics-grid .metric-card').count()).toBeGreaterThan(0);
    await expect(page.getByRole('heading', { name: '실제 근거와 참고 링크 분리' })).toBeVisible();

    await page.getByRole('link', { name: /Ranking으로 돌아가기/ }).click();
    await expect(page).toHaveURL(/\/rankings\/weekly\.html$/);
  });

  test('all internal links and hash anchors from core pages resolve', async ({ page, request, baseURL }) => {
    const base = new URL(baseURL ?? 'http://127.0.0.1:8765');
    const startPages = ['/index.html', ...timeframes.map(([, path]) => path)];
    const targets = new Map<string, Set<string>>();

    for (const startPage of startPages) {
      await page.goto(startPage);
      const hrefs = await page.locator('a[href]').evaluateAll((links) => links.map((link) => (link as HTMLAnchorElement).href));

      for (const href of hrefs) {
        const target = new URL(href);
        if (target.origin !== base.origin) continue;
        const path = target.pathname === '/' ? '/index.html' : target.pathname;
        if (!targets.has(path)) targets.set(path, new Set());
        if (target.hash) targets.get(path)?.add(decodeURIComponent(target.hash.slice(1)));
      }
    }

    for (const [path, hashTargets] of targets) {
      const response = await request.get(path);
      expect(response.status(), `${path} should return HTTP 2xx/3xx`).toBeLessThan(400);
      const html = await response.text();

      for (const hashTarget of hashTargets) {
        expect(
          new RegExp(`id=["']${escapeRegExp(hashTarget)}["']`).test(html),
          `${path} is missing hash target #${hashTarget}`,
        ).toBe(true);
      }
    }
  });
});
