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
    await page.goto('/index.html?variant=A');

    await expect(page).toHaveTitle(/Home · BSS Trend Ranking/);
    await expect(page.getByRole('heading', { name: 'Beauty Supply 제품별 트렌드 순위' })).toBeVisible();
    await expect(page.getByText(/\d+ items · 8 categories/)).toBeVisible();
    await expect(page.getByText('Data health')).toBeVisible();
    await expect(page.locator('.data-health div')).toHaveCount(4);
    await expect(page.getByText('500/day')).toBeVisible();
    await expect(page.locator('script[src="/assets/growth.js"]')).toHaveCount(1);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', 'https://gnsresearchhub.vercel.app/index.html');
    await expect(page.locator('meta[name="gns:growth-goal"]')).toHaveAttribute('content', 'daily-visits-500');
    await expect(page.locator('meta[name="gns:growth-experiment"]')).toHaveAttribute('content', 'hero-growth-cta-v1');
    await expect(page.locator('meta[property="og:image"]')).toHaveAttribute('content', /^https:\/\//);
    await expect(page.locator('script[type="application/ld+json"]')).toHaveCount(1);
    const homeJsonLd = await page.locator('script[type="application/ld+json"]').first().textContent();
    expect(JSON.parse(homeJsonLd ?? '{}')['@type']).toBe('ItemList');
    await expect(page.locator('script[src="https://www.googletagmanager.com/gtag/js?id=G-SW7HBY6WRE"]')).toHaveCount(1);
    const hasGa4InlineConfig = await page.locator('script:not([src])').evaluateAll((scripts) =>
      scripts.some((script) => (script.textContent ?? '').includes('G-SW7HBY6WRE')),
    );
    expect(hasGa4InlineConfig).toBe(true);
    await expect(page.locator('[data-growth-cta="primary"]')).toBeVisible();
    await expect(page.locator('.share-kit')).toBeVisible();
    await expect(page.locator('[data-growth-share="weekly_x_intent"]')).toHaveAttribute('href', /daily-visits-500-weekly-owner-share/);
    await expect(page.locator('[data-growth-share="weekly_copy_link"]')).toHaveAttribute('data-copy-url', /utm_campaign=daily-visits-500-weekly-owner-share/);
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

  test('growth goal tracking and A/B variant are wired', async ({ page, request }) => {
    await page.goto('/index.html?variant=B&utm_source=e2e&utm_medium=playwright&utm_campaign=daily-visits-500');

    await expect(page.locator('body')).toHaveAttribute('data-experiment-id', 'hero-growth-cta-v1');
    await expect(page.locator('body')).toHaveAttribute('data-experiment-variant', 'B_retail_action_first');
    await expect(page.getByRole('heading', { name: '이번 주 BSS 매장에서 바로 테스트할 제품 순위' })).toBeVisible();
    await expect(page.getByRole('link', { name: '이번 주 팔아볼 제품 보기' })).toBeVisible();

    const exposure = await page.evaluate(() => {
      const growth = (window as any).__GNS_GROWTH__;
      return {
        goalId: growth?.goalId,
        target: growth?.targetAverageDailyVisits,
        events: growth?.events?.() ?? [],
      };
    });
    expect(exposure.goalId).toBe('daily-visits-500');
    expect(exposure.target).toBe(500);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && event.utm_campaign === 'daily-visits-500')).toBe(true);

    const copyButton = page.locator('[data-growth-share="weekly_copy_link"]').first();
    await copyButton.click();
    await expect(copyButton).toHaveText(/Copied|Link ready/);
    const shareEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(shareEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_copy_link')).toBe(true);
    expect(shareEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'weekly_copy_link')).toBe(true);

    await page.getByRole('link', { name: '이번 주 팔아볼 제품 보기' }).click();
    await expect(page).toHaveURL(/\/rankings\/weekly\.html/);
    const clickEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(clickEvents.some((event: any) => event.event === 'growth_click' && event.type === 'cta_primary')).toBe(true);

    const goalResponse = await request.get('/data/growth_goal_public.json');
    expect(goalResponse.status()).toBeLessThan(400);
    const goal = await goalResponse.json();
    expect(goal.primary_goal?.target).toBe(500);
    expect(goal.analytics_providers?.ga4?.measurement_id).toBe('G-SW7HBY6WRE');
    expect(goal.analytics_providers?.vercel_web_analytics?.status).toBe('enabled');
    expect(goal.sns_strategy?.tool).toBe('xurl');
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'hero-growth-cta-v1')).toBe(true);
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

    await expect(page.getByRole('heading', { level: 1, name: itemName })).toBeVisible();
    await expect(page.locator('.detail-img img')).toHaveAttribute('src', /.+/);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', /\/items\/.+\.html$/);
    const detailJsonLd = await page.locator('script[type="application/ld+json"]').first().textContent();
    expect(JSON.parse(detailJsonLd ?? '{}')['@type']).toBe('Product');
    expect(await page.locator('.metrics-grid .metric-card').count()).toBeGreaterThan(0);
    await expect(page.getByRole('heading', { name: '실제 근거와 참고 링크 분리' })).toBeVisible();
    await expect(page.locator('.item-share-kit')).toBeVisible();
    const itemCopyButton = page.locator('[data-growth-share="item_copy_link"]').first();
    await expect(itemCopyButton).toHaveAttribute('data-copy-url', /utm_campaign=daily-visits-500-item-detail-share/);
    await expect(itemCopyButton).toHaveAttribute('data-copy-url', /utm_content=/);
    await itemCopyButton.click();
    await expect(itemCopyButton).toHaveText(/Copied|Link ready/);
    const itemShareEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(itemShareEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'item_copy_link')).toBe(true);

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

  test('public deploy data artifacts expose review and collection health', async ({ request }) => {
    const rankingsResponse = await request.get('/data/rankings.json');
    expect(rankingsResponse.status()).toBeLessThan(400);
    const rankings = await rankingsResponse.json();
    expect(rankings.collection_health?.evidence_totals?.items_requested).toBeGreaterThan(0);

    const reviewResponse = await request.get('/data/operations_review_public.json');
    expect(reviewResponse.status()).toBeLessThan(400);
    const review = await reviewResponse.json();
    expect(review.metrics?.items).toBeGreaterThan(0);
    expect(review.collection_health?.source_health).toBeTruthy();

    const collectionResponse = await request.get('/data/collection_notes_public.json');
    expect(collectionResponse.status()).toBeLessThan(400);
    const collection = await collectionResponse.json();
    expect(collection.evidence_totals?.items_requested).toBeGreaterThan(0);
    expect(collection.source_health?.apify_tiktok_shop?.status).toBeTruthy();

    const marketingResponse = await request.get('/data/marketing_backlog_public.json');
    expect(marketingResponse.status()).toBeLessThan(400);
    const marketing = await marketingResponse.json();
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'owner-share-kit-v1')).toBe(true);

    const snsRulesResponse = await request.get('/data/sns_posting_rules_public.json');
    expect(snsRulesResponse.status()).toBeLessThan(400);
    const snsRules = await snsRulesResponse.json();
    expect(snsRules.primary_channel?.tool).toBe('xurl');
    expect(snsRules.posting_rule?.frequency_limits?.standard_post).toBe('max_1_per_day');

    const robotsResponse = await request.get('/robots.txt');
    expect(robotsResponse.status()).toBeLessThan(400);
    expect(await robotsResponse.text()).toContain('Sitemap: https://gnsresearchhub.vercel.app/sitemap.xml');

    const sitemapResponse = await request.get('/sitemap.xml');
    expect(sitemapResponse.status()).toBeLessThan(400);
    const sitemap = await sitemapResponse.text();
    expect(sitemap).toContain('<loc>https://gnsresearchhub.vercel.app/index.html</loc>');
    expect(sitemap).toContain('/rankings/weekly.html</loc>');
    expect(sitemap).toContain('/items/');
  });
});
