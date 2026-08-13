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
  test('home page renders the ranking dashboard with product visuals', async ({ page, request }) => {
    await page.goto('/index.html?variant=A');

    await expect(page).toHaveTitle(/Home · BSS Trend Ranking/);
    await expect(page.getByRole('heading', { name: 'Beauty Supply 제품별 트렌드 순위' })).toBeVisible();
    await expect(page.getByText(/\d+ items · 8 categories/)).toBeVisible();
    await expect(page.getByText('Data health')).toBeVisible();
    await expect(page.locator('.data-health div')).toHaveCount(4);
    await expect(page.getByText('500/day')).toBeVisible();
    await expect(page.locator('script[src="/assets/growth.js"]')).toHaveCount(1);
    await expect(page.locator('[data-return-visitor-panel]')).toBeHidden();
    await expect(page.locator('[data-return-visitor-panel]')).not.toHaveAttribute('data-growth-section', /.+/);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', 'https://gnsresearchhub.vercel.app/index.html');
    await expect(page.locator('link[rel="alternate"][type="application/rss+xml"]')).toHaveAttribute('href', 'https://gnsresearchhub.vercel.app/feed.xml');
    await expect(page.locator('link[rel="alternate"][type="text/calendar"]')).toHaveAttribute('href', 'https://gnsresearchhub.vercel.app/owner-weekly-reminder.ics');
    await expect(page.locator('link[rel="manifest"]')).toHaveAttribute('href', '/manifest.webmanifest');
    await expect(page.locator('link[rel="icon"][href="/assets/app-icon.svg"]')).toHaveCount(1);
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#111827');
    await expect(page.locator('meta[name="gns:growth-goal"]')).toHaveAttribute('content', 'daily-visits-500');
    await expect(page.locator('meta[name="gns:growth-experiment"]')).toHaveAttribute('content', 'hero-growth-cta-v1');
    await expect(page.locator('meta[property="og:image"]')).toHaveAttribute('content', 'https://gnsresearchhub.vercel.app/assets/share-weekly.svg');
    await expect(page.locator('meta[name="twitter:image"]')).toHaveAttribute('content', 'https://gnsresearchhub.vercel.app/assets/share-weekly.svg');
    const shareCardResponse = await request.get('/assets/share-weekly.svg');
    expect(shareCardResponse.status()).toBeLessThan(400);
    const shareCardSvg = await shareCardResponse.text();
    expect(shareCardSvg).toContain('BSS-WIDE ITEM RANKING · WEEKLY');
    expect(shareCardSvg).toContain('Trend-backed');
    const manifestResponse = await request.get('/manifest.webmanifest');
    expect(manifestResponse.status()).toBeLessThan(400);
    const manifest = await manifestResponse.json();
    expect(manifest.start_url).toContain('daily-visits-500-owner-shortcut');
    expect(manifest.icons?.[0]?.src).toBe('/assets/app-icon.svg');
    const appIconResponse = await request.get('/assets/app-icon.svg');
    expect(appIconResponse.status()).toBeLessThan(400);
    expect(await appIconResponse.text()).toContain('BSS Trend Ranking app icon');
    await expect(page.locator('script[type="application/ld+json"]')).toHaveCount(1);
    const homeJsonLd = await page.locator('script[type="application/ld+json"]').first().textContent();
    expect(JSON.parse(homeJsonLd ?? '{}')['@type']).toBe('ItemList');
    await expect(page.locator('script[src="https://www.googletagmanager.com/gtag/js?id=G-SW7HBY6WRE"]')).toHaveCount(1);
    const hasGa4InlineConfig = await page.locator('script:not([src])').evaluateAll((scripts) =>
      scripts.some((script) => (script.textContent ?? '').includes('G-SW7HBY6WRE')),
    );
    expect(hasGa4InlineConfig).toBe(true);
    await expect(page.locator('[data-growth-cta="primary"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="run-change-snapshot-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="run-change-snapshot-v1"]')).toHaveAttribute('data-growth-experiment', 'run-change-snapshot-v1');
    await expect(page.getByRole('heading', { name: '오늘 다시 볼 이유' })).toBeVisible();
    await expect(page.locator('[data-growth-section="run-change-snapshot-v1"]').getByText('Cached fallback')).toBeVisible();
    await expect(page.locator('[data-growth-cta="run_change_review"]')).toHaveAttribute('href', '/data/operations_review_public.json');
    await expect(page.locator('[data-growth-section="evidence-gap-transparency-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="evidence-gap-transparency-v1"]')).toHaveAttribute('data-growth-experiment', 'evidence-window-transparency-v1');
    await expect(page.getByText('Evidence quality snapshot')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Weekly evidence window를 먼저 확인' })).toBeVisible();
    await expect(page.getByText('Active trend window')).toBeVisible();
    await expect(page.getByText('365d captured published URLs')).toBeVisible();
    await expect(page.locator('.evidence-snapshot-grid div').filter({ hasText: 'Missing TikTok Shop' }).getByText('0')).toBeVisible();
    const tiktokSourceHealth = page.locator('[data-source-health="tiktok_shop"]');
    await expect(tiktokSourceHealth).toBeVisible();
    await expect(tiktokSourceHealth).toHaveAttribute('data-source-health-status', /.+/);
    await expect(tiktokSourceHealth).toHaveAttribute('data-fresh-urls', /\d+/);
    await expect(tiktokSourceHealth).toHaveAttribute('data-cached-urls', /\d+/);
    await expect(tiktokSourceHealth).toContainText('TikTok Shop freshness');
    await expect(tiktokSourceHealth).toContainText(/Fresh \d+/);
    await expect(tiktokSourceHealth).toContainText(/Cached \d+/);
    await expect(tiktokSourceHealth.locator('.source-health-status')).toBeVisible();
    const tiktokSourceStatus = await tiktokSourceHealth.getAttribute('data-source-health-status');
    if (tiktokSourceStatus?.includes('cache')) {
      await expect(tiktokSourceHealth).toContainText('supply-only');
    }
    await expect(page.locator('[data-growth-cta="evidence_snapshot_review"]')).toHaveAttribute('href', '/data/operations_review_public.json');
    await expect(page.locator('[data-growth-section="timeframe-evidence-ladder-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="timeframe-evidence-ladder-v1"]')).toHaveAttribute('data-growth-experiment', 'timeframe-evidence-ladder-v1');
    await expect(page.getByRole('heading', { name: 'Evidence window별로 먼저 보기' })).toBeVisible();
    const ladderCards = page.locator('.evidence-ladder-card');
    await expect(ladderCards).toHaveCount(4);
    await expect(ladderCards.first()).toHaveAttribute('data-growth-cta', 'timeframe_evidence_ladder');
    await expect(ladderCards.first()).toHaveAttribute('href', /utm_medium=evidence_ladder/);
    await expect(ladderCards.first()).toHaveAttribute('href', /daily-visits-500-timeframe-evidence-ladder/);
    await expect(ladderCards.first()).toContainText('trend-backed items');
    await expect(page.locator('[data-growth-section="evidence-focus-watchlist-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="evidence-focus-watchlist-v1"]')).toHaveAttribute('data-growth-experiment', 'evidence-focus-watchlist-v1');
    await expect(page.getByRole('heading', { name: 'Weekly WATCHLIST 근거 보강 대상' })).toBeVisible();
    const focusCards = page.locator('.focus-card');
    expect(await focusCards.count()).toBeGreaterThanOrEqual(3);
    await expect(focusCards.first()).toHaveAttribute('href', /daily-visits-500-weekly-evidence-focus-watchlist/);
    await expect(focusCards.first()).toHaveAttribute('href', /utm_medium=focus_watchlist/);
    await expect(focusCards.first()).toHaveAttribute('data-growth-cta', 'evidence_focus_watchlist');
    await expect(focusCards.first()).toHaveAttribute('data-item-id', /.+/);
    await expect(page.locator('[data-growth-cta="evidence_focus_public_json"]')).toHaveAttribute('href', '/data/next_loop_focus_public.json');
    const focusResponse = await request.get('/data/next_loop_focus_public.json');
    expect(focusResponse.status()).toBeLessThan(400);
    const focusPayload = await focusResponse.json();
    expect(focusPayload.updated_at).toBeTruthy();
    expect(focusPayload.focus_items?.length).toBeGreaterThanOrEqual(7);
    await expect(page.locator('.focus-note')).toContainText(focusPayload.updated_at);
    const firstFocusItem = focusPayload.focus_items?.[0];
    if (firstFocusItem?.item_name) {
      await expect(focusCards.first()).toContainText(firstFocusItem.item_name);
    }
    const collectionNotesResponse = await request.get('/data/collection_notes_public.json');
    expect(collectionNotesResponse.status()).toBeLessThan(400);
    const collectionNotes = await collectionNotesResponse.json();
    const apifyNotes = collectionNotes.source_health?.apify_tiktok_shop ?? {};
    const liveCachedAttr = await tiktokSourceHealth.getAttribute('data-cached-urls');
    if (apifyNotes.partial_cached_evidence_urls !== undefined) {
      expect(Number(liveCachedAttr)).toBe(Number(apifyNotes.partial_cached_evidence_urls));
      if (Number(apifyNotes.cached_evidence_urls ?? 0) !== Number(apifyNotes.partial_cached_evidence_urls ?? 0)) {
        expect(Number(liveCachedAttr)).not.toBe(Number(apifyNotes.cached_evidence_urls ?? 0));
      }
    }
    const missingPublishedItems = collectionNotes.coverage_gaps?.missing_published_trend_items ?? [];
    const focusIds = new Set((focusPayload.focus_items ?? []).map((item: any) => item.item_id));
    if (missingPublishedItems.length > 0 && missingPublishedItems.length <= 8) {
      expect(missingPublishedItems.every((item: any) => focusIds.has(item.item_id))).toBe(true);
    }
    await expect(page.locator('[data-growth-section="category-landing-nav-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="category-landing-nav-v1"]')).toHaveAttribute('data-growth-experiment', 'category-landing-pages-v1');
    await expect(page.getByRole('heading', { name: 'Category별 item ranking 바로가기' })).toBeVisible();
    const categoryLandingCards = page.locator('.category-landing-card');
    await expect(categoryLandingCards).toHaveCount(8);
    await expect(categoryLandingCards.first()).toHaveAttribute('href', /\/categories\/.+\.html\?utm_source=site/);
    await expect(categoryLandingCards.first()).toHaveAttribute('href', /utm_medium=category_nav/);
    await expect(categoryLandingCards.first()).toHaveAttribute('data-growth-cta', 'category_landing_nav');
    await expect(categoryLandingCards.first()).toHaveAttribute('data-category-id', /.+/);
    const categoryResponse = await request.get('/categories/wigs-hair-pieces.html');
    expect(categoryResponse.status()).toBeLessThan(400);
    const categoryHtml = await categoryResponse.text();
    expect(categoryHtml).toContain('Wigs &amp; Hair Pieces item ranking');
    expect(categoryHtml).toContain('category-landing-pages-v1');
    await expect(page.locator('[data-growth-section="owner-quick-picks-v1"]')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Weekly 매장 테스트 빠른 선택' })).toBeVisible();
    const quickPickCards = page.locator('.quick-pick-card');
    expect(await quickPickCards.count()).toBeGreaterThanOrEqual(4);
    await expect(quickPickCards.first()).toHaveAttribute('href', /daily-visits-500-weekly-owner-quick-picks/);
    await expect(quickPickCards.first()).toHaveAttribute('href', /utm_medium=quick_pick/);
    await expect(quickPickCards.first()).toHaveAttribute('data-growth-cta', 'owner_quick_pick');
    await expect(quickPickCards.first()).toHaveAttribute('data-item-id', /.+/);
    await expect(page.locator('[data-growth-section="owner-5-minute-route-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="owner-5-minute-route-v1"]')).toHaveAttribute('data-growth-experiment', 'owner-5-minute-route-v1');
    await expect(page.getByRole('heading', { name: 'Weekly 매장 5분 점검 route' })).toBeVisible();
    const ownerRouteCards = page.locator('.owner-route-card');
    await expect(ownerRouteCards).toHaveCount(3);
    await expect(ownerRouteCards.first()).toHaveAttribute('href', /daily-visits-500-weekly-owner-route/);
    await expect(ownerRouteCards.first()).toHaveAttribute('href', /utm_medium=owner_route/);
    await expect(ownerRouteCards.first()).toHaveAttribute('data-growth-cta', 'owner_route_item');
    await expect(page.locator('[data-growth-share="weekly_owner_route_copy"]')).toHaveAttribute('data-copy-url', /daily-visits-500-weekly-owner-route/);
    await expect(page.locator('[data-growth-share="weekly_owner_route_copy"]')).toHaveAttribute('data-copy-text', /5-minute owner route/);
    await expect(page.locator('[data-growth-cta="owner_route_full_ranking"]')).toHaveAttribute('href', /utm_medium=owner_route/);
    await expect(page.locator('[data-growth-section="owner-brief-copy-v1"]')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Weekly owner에게 바로 보낼 3줄 요약' })).toBeVisible();
    await expect(page.locator('.owner-brief-steps li')).toHaveCount(3);
    const ownerBriefCopy = page.locator('[data-growth-share="weekly_owner_brief_copy"]');
    await expect(ownerBriefCopy).toHaveAttribute('data-copy-url', /daily-visits-500-weekly-owner-brief/);
    await expect(ownerBriefCopy).toHaveAttribute('data-copy-url', /utm_medium=brief_copy/);
    await expect(ownerBriefCopy).toHaveAttribute('data-copy-text', /BSS owner brief/);
    await expect(ownerBriefCopy).toHaveAttribute('data-copy-text', /Display test/);
    await expect(page.locator('[data-growth-section="owner-feed-subscribe-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="owner-feed-subscribe-v1"]')).toHaveAttribute('data-growth-experiment', 'owner-feed-subscribe-v1');
    await expect(page.getByRole('heading', { name: 'Weekly owner feed 구독/저장' })).toBeVisible();
    await expect(page.locator('[data-growth-cta="owner_feed_open"]')).toHaveAttribute('href', /daily-visits-500-owner-feed-subscribe/);
    await expect(page.locator('[data-growth-cta="owner_feed_open"]')).toHaveAttribute('href', /utm_medium=feed_subscribe/);
    await expect(page.locator('[data-growth-share="weekly_feed_copy"]')).toHaveAttribute('data-copy-url', /feed\.xml\?utm_source=site/);
    await expect(page.locator('[data-growth-section="owner-shortcut-save-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="owner-shortcut-save-v1"]')).toHaveAttribute('data-growth-experiment', 'owner-shortcut-save-v1');
    await expect(page.getByRole('heading', { name: 'Weekly dashboard shortcut 저장' })).toBeVisible();
    await expect(page.locator('[data-growth-cta="owner_shortcut_open"]')).toHaveAttribute('href', /daily-visits-500-owner-shortcut/);
    await expect(page.locator('[data-growth-cta="owner_shortcut_open"]')).toHaveAttribute('href', /utm_medium=shortcut/);
    await expect(page.locator('[data-growth-share="weekly_shortcut_copy"]')).toHaveAttribute('data-copy-url', /daily-visits-500-owner-shortcut/);
    await expect(page.locator('[data-growth-cta="owner_shortcut_manifest"]')).toHaveAttribute('href', '/manifest.webmanifest');
    await expect(page.locator('[data-growth-section="owner-calendar-reminder-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="owner-calendar-reminder-v1"]')).toHaveAttribute('data-growth-experiment', 'owner-calendar-reminder-v1');
    await expect(page.getByRole('heading', { name: 'Weekly calendar reminder 저장' })).toBeVisible();
    await expect(page.locator('[data-growth-cta="owner_calendar_download"]')).toHaveAttribute('href', /owner-weekly-reminder\.ics/);
    await expect(page.locator('[data-growth-cta="owner_calendar_download"]')).toHaveAttribute('href', /utm_medium=calendar_reminder/);
    await expect(page.locator('[data-growth-share="weekly_calendar_copy"]')).toHaveAttribute('data-copy-url', /owner-weekly-reminder\.ics/);
    await expect(page.locator('[data-growth-share="weekly_calendar_message_copy"]')).toHaveAttribute('data-copy-text', /BSS weekly ranking reminder/);
    await expect(page.locator('[data-growth-section="owner-print-sheet-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="owner-print-sheet-v1"]')).toHaveAttribute('data-growth-experiment', 'owner-print-sheet-v1');
    await expect(page.getByRole('heading', { name: 'Weekly owner print/share sheet' })).toBeVisible();
    await expect(page.locator('[data-growth-cta="owner_print_sheet_open"]')).toHaveAttribute('href', /owner-share-sheet\.html/);
    await expect(page.locator('[data-growth-cta="owner_print_sheet_open"]')).toHaveAttribute('href', /daily-visits-500-owner-print-sheet/);
    await expect(page.locator('[data-growth-share="weekly_owner_print_sheet_copy"]')).toHaveAttribute('data-copy-url', /owner-share-sheet\.html/);
    await expect(page.locator('[data-growth-share="weekly_owner_print_sheet_copy"]')).toHaveAttribute('data-copy-text', /BSS owner print\/share sheet/);
    const printSheetResponse = await request.get('/owner-share-sheet.html');
    expect(printSheetResponse.status()).toBeLessThan(400);
    const printSheetHtml = await printSheetResponse.text();
    expect(printSheetHtml).toContain('Weekly BSS owner print/share sheet');
    expect(printSheetHtml).toContain('owner-print-sheet-page-v1');
    await expect(page.locator('.share-kit')).toBeVisible();
    await expect(page.locator('[data-growth-section="owner-share-kit-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="owner-share-kit-v1"]')).toHaveAttribute('data-growth-experiment', 'owner-share-kit-v1');
    await expect(page.locator('[data-growth-share="weekly_x_intent"]')).toHaveAttribute('href', /daily-visits-500-weekly-owner-share/);
    await expect(page.locator('[data-growth-share="weekly_sms_draft"]')).toHaveAttribute('href', /^sms:/);
    await expect(page.locator('[data-growth-share="weekly_whatsapp_draft"]')).toHaveAttribute('href', /^https:\/\/wa\.me\/\?text=/);
    await expect(page.locator('[data-growth-share="weekly_native_share"]')).toHaveAttribute('data-native-share', 'true');
    await expect(page.locator('[data-growth-share="weekly_native_share"]')).toHaveAttribute('data-native-share-url', /utm_source=native_share/);
    await expect(page.locator('[data-growth-share="weekly_native_share"]')).toHaveAttribute('data-native-share-url', /utm_medium=mobile/);
    await expect(page.locator('[data-growth-share="weekly_native_share"]')).toHaveAttribute('data-native-share-text', /BSS mobile share/);
    await expect(page.locator('[data-growth-share="weekly_message_copy"]')).toHaveAttribute('data-copy-url', /utm_source=message/);
    await expect(page.locator('[data-growth-share="weekly_message_copy"]')).toHaveAttribute('data-copy-url', /utm_medium=direct/);
    await expect(page.locator('[data-growth-share="weekly_message_copy"]')).toHaveAttribute('data-copy-text', /BSS owner text/);
    await expect(page.locator('[data-growth-share="weekly_copy_link"]')).toHaveAttribute('data-copy-url', /utm_campaign=daily-visits-500-weekly-owner-share/);
    await expect(page.locator('[data-growth-section="top3-owner-share-strip-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-share="weekly_top3_x_intent"]').first()).toHaveAttribute('href', /daily-visits-500-weekly-top3-owner-share/);
    await expect(page.locator('[data-growth-share="weekly_top3_sms_draft"]').first()).toHaveAttribute('href', /^sms:/);
    await expect(page.locator('[data-growth-share="weekly_top3_whatsapp_draft"]').first()).toHaveAttribute('href', /^https:\/\/wa\.me\/\?text=/);
    await expect(page.locator('[data-growth-share="weekly_top3_native_share"]').first()).toHaveAttribute('data-native-share', 'true');
    await expect(page.locator('[data-growth-share="weekly_top3_native_share"]').first()).toHaveAttribute('data-native-share-url', /utm_source=native_share/);
    await expect(page.locator('[data-growth-share="weekly_top3_native_share"]').first()).toHaveAttribute('data-native-share-url', /utm_campaign=daily-visits-500-weekly-top3-owner-share/);
    await expect(page.locator('[data-growth-share="weekly_top3_message_copy"]').first()).toHaveAttribute('data-copy-url', /utm_source=message/);
    await expect(page.locator('[data-growth-share="weekly_top3_message_copy"]').first()).toHaveAttribute('data-copy-url', /utm_medium=direct/);
    await expect(page.locator('[data-growth-share="weekly_top3_message_copy"]').first()).toHaveAttribute('data-copy-text', /BSS direct share/);
    await expect(page.locator('[data-growth-share="weekly_top3_copy_link"]').first()).toHaveAttribute('data-copy-url', /utm_campaign=daily-visits-500-weekly-top3-owner-share/);
    await expect(page.locator('[data-growth-share="weekly_top3_copy_link"]').first()).toHaveAttribute('data-copy-url', /utm_content=/);
    await expect(page.locator('[data-growth-section="top3-leaderboard-v1"]')).toHaveAttribute('data-growth-experiment', 'ranking-list-engagement-context-v1');
    await expect(page.locator('[data-growth-section="ranking-main-list-v1"]')).toHaveAttribute('data-growth-experiment', 'ranking-list-engagement-context-v1');
    await expect(page.locator('[data-growth-section="monthly-preview-list-v1"]')).toHaveAttribute('data-growth-experiment', 'ranking-list-engagement-context-v1');
    const homeSectionOrder = await page.locator('[data-growth-section]').evaluateAll((sections) =>
      sections.map((section) => section.getAttribute('data-growth-section') ?? ''),
    );
    const homeSectionIndex = (sectionId: string) => homeSectionOrder.indexOf(sectionId);
    expect(homeSectionIndex('top3-leaderboard-v1')).toBeGreaterThanOrEqual(0);
    expect(homeSectionIndex('ranking-main-list-v1')).toBeGreaterThan(homeSectionIndex('top3-leaderboard-v1'));
    expect(homeSectionIndex('ranking-main-list-v1')).toBeLessThan(homeSectionIndex('category-landing-nav-v1'));
    expect(homeSectionIndex('ranking-main-list-v1')).toBeLessThan(homeSectionIndex('evidence-gap-transparency-v1'));
    expect(homeSectionIndex('ranking-main-list-v1')).toBeLessThan(homeSectionIndex('owner-share-kit-v1'));
    await expect(page.locator('.podium-card')).toHaveCount(3);
    await expect(page.locator('.podium-card').first()).toHaveAttribute('data-item-id', /.+/);
    await expect(page.locator('.podium-card').first()).toHaveAttribute('data-item-rank', /\d+/);

    const rankCards = page.locator('.rank-card');
    await expect(rankCards.first()).toBeVisible();
    expect(await rankCards.count()).toBeGreaterThanOrEqual(8);
    await expect(rankCards.first().locator('.owner-actions')).toBeVisible();
    await expect(rankCards.first().locator('.owner-action-note')).toHaveCount(3);
    await expect(rankCards.first().getByText('Display')).toBeVisible();
    await expect(rankCards.first().getByText('Risk')).toBeVisible();
    await expect(rankCards.first().getByText('Owner phrase')).toBeVisible();

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

    const analyticsBridge = await page.evaluate(() => ({
      vaType: typeof (window as any).va,
      vercelPath: (window as any).__GNS_VERCEL_ANALYTICS_PATH,
      queuedVercelEvents: Array.isArray((window as any).vaq) ? (window as any).vaq.length : 0,
    }));
    expect(analyticsBridge.vaType).toBe('function');
    expect(analyticsBridge.vercelPath).toBe('/_vercel/insights/script.js');

    const exposure = await page.evaluate(() => {
      const growth = (window as any).__GNS_GROWTH__;
      return {
        goalId: growth?.goalId,
        target: growth?.targetAverageDailyVisits,
        sessionId: growth?.sessionId,
        visitorId: growth?.visitorId,
        visitor: growth?.visitor?.(),
        attribution: growth?.attribution?.(),
        analyticsBridgeStatus: growth?.analyticsBridgeStatus?.(),
        growthSections: growth?.growthSections?.() ?? [],
        events: growth?.events?.() ?? [],
      };
    });
    expect(exposure.goalId).toBe('daily-visits-500');
    expect(exposure.target).toBe(500);
    expect(exposure.sessionId).toMatch(/^gns_/);
    expect(exposure.visitorId).toMatch(/^gns_v_/);
    expect(exposure.visitor.visitor_id).toBe(exposure.visitorId);
    expect(exposure.visitor.visit_count).toBeGreaterThanOrEqual(1);
    expect(exposure.visitor.is_returning_visitor).toBe(false);
    expect(exposure.visitor.visit_window_minutes).toBe(30);
    expect(exposure.attribution.first.utm_source).toBe('e2e');
    expect(exposure.attribution.first.utm_campaign).toBe('daily-visits-500');
    expect(exposure.analyticsBridgeStatus.provider).toBe('analytics_bridge');
    expect(exposure.analyticsBridgeStatus.status).toBe('snapshot');
    expect(exposure.analyticsBridgeStatus.event_schema_version).toBe('growth-event-schema-v2');
    expect(exposure.analyticsBridgeStatus.vercel_queue_ready).toBe(true);
    expect(exposure.analyticsBridgeStatus.vercel_script_path).toBe('/_vercel/insights/script.js');
    expect(exposure.analyticsBridgeStatus.data_layer_ready).toBe(true);
    expect(exposure.analyticsBridgeStatus.ga4_ready).toBe(true);
    expect(exposure.growthSections.some((section: any) => section.id === 'run-change-snapshot-v1')).toBe(true);
    expect(exposure.growthSections.some((section: any) => section.id === 'owner-quick-picks-v1')).toBe(true);
    expect(exposure.growthSections.some((section: any) => section.id === 'owner-5-minute-route-v1')).toBe(true);
    expect(exposure.growthSections.some((section: any) => section.id === 'owner-brief-copy-v1')).toBe(true);
    expect(exposure.growthSections.some((section: any) => section.id === 'owner-feed-subscribe-v1')).toBe(true);
    expect(exposure.growthSections.some((section: any) => section.id === 'owner-shortcut-save-v1')).toBe(true);
    expect(exposure.growthSections.some((section: any) => section.id === 'owner-calendar-reminder-v1')).toBe(true);
    expect(exposure.growthSections.some((section: any) => section.id === 'owner-print-sheet-v1')).toBe(true);
    expect(exposure.growthSections.some((section: any) => section.id === 'evidence-focus-watchlist-v1')).toBe(true);
    expect(exposure.growthSections.some((section: any) => section.id === 'timeframe-evidence-ladder-v1')).toBe(true);
    expect(exposure.growthSections.some((section: any) => section.id === 'category-landing-nav-v1')).toBe(true);
    expect(exposure.growthSections.some((section: any) => section.id === 'top3-leaderboard-v1')).toBe(true);
    expect(exposure.growthSections.some((section: any) => section.id === 'ranking-main-list-v1')).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && event.utm_campaign === 'daily-visits-500')).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_provider_ready' && event.provider === 'analytics_bridge' && event.status === 'client_bridge_ready' && event.vercel_queue_ready === true && event.ga4_ready === true && event.event_schema_version === 'growth-event-schema-v2' && event.utm_campaign === 'daily-visits-500')).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && event.event_schema_version === 'growth-event-schema-v2' && event.tracking_runtime === 'assets/growth.js' && event.client_language)).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && event.first_utm_source === 'e2e')).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && event.visitor_id === exposure.visitorId && event.visit_count >= 1 && event.is_returning_visitor === false)).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && event.page_type === 'home' && event.timeframe === 'weekly_home' && event.page_item_id === '')).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && String(event.visible_growth_sections).includes('run-change-snapshot-v1'))).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && String(event.visible_growth_sections).includes('owner-quick-picks-v1'))).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && String(event.visible_growth_sections).includes('owner-5-minute-route-v1'))).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && String(event.visible_growth_sections).includes('owner-brief-copy-v1'))).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && String(event.visible_growth_sections).includes('owner-feed-subscribe-v1'))).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && String(event.visible_growth_sections).includes('owner-shortcut-save-v1'))).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && String(event.visible_growth_sections).includes('owner-calendar-reminder-v1'))).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && String(event.visible_growth_sections).includes('owner-print-sheet-v1'))).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && String(event.visible_growth_sections).includes('evidence-focus-watchlist-v1'))).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && String(event.visible_growth_sections).includes('timeframe-evidence-ladder-v1'))).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && String(event.visible_growth_sections).includes('category-landing-nav-v1'))).toBe(true);
    expect(exposure.events.some((event: any) => event.event === 'growth_exposure' && String(event.visible_growth_sections).includes('ranking-main-list-v1'))).toBe(true);

    await page.locator('[data-growth-section="owner-quick-picks-v1"]').scrollIntoViewIfNeeded();
    await page.waitForFunction(() =>
      ((window as any).__GNS_GROWTH__?.events?.() ?? []).some(
        (event: any) => event.event === 'growth_section_view' && event.section === 'owner-quick-picks-v1' && event.item_count > 0,
      ),
    );
    const sectionViewEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(sectionViewEvents.some((event: any) => event.event === 'growth_section_view' && event.type === 'section_view' && event.component_experiment_id === 'owner-quick-picks-v1' && event.section_position && String(event.heading).includes('매장 테스트 빠른 선택'))).toBe(true);

    const top3CopyButton = page.locator('[data-growth-share="weekly_top3_copy_link"]').first();
    await top3CopyButton.click();
    await expect(top3CopyButton).toHaveText(/Copied|Link ready/);
    const top3ShareEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(top3ShareEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_top3_copy_link' && event.item_id)).toBe(true);
    expect(top3ShareEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_top3_copy_link' && event.link_utm_source === 'owner_share' && event.link_utm_medium === 'organic' && event.link_utm_campaign === 'daily-visits-500-weekly-top3-owner-share' && event.link_utm_content)).toBe(true);
    expect(top3ShareEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'weekly_top3_copy_link' && event.section === 'top3-owner-share-strip-v1' && event.component_experiment_id === 'top3-owner-share-strip-v1' && event.section_position && event.item_id)).toBe(true);
    expect(top3ShareEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'weekly_top3_copy_link' && event.link_has_utm === true && event.link_utm_source === 'owner_share' && event.link_utm_campaign === 'daily-visits-500-weekly-top3-owner-share')).toBe(true);

    const top3MessageButton = page.locator('[data-growth-share="weekly_top3_message_copy"]').first();
    await top3MessageButton.click();
    await expect(top3MessageButton).toHaveText(/Copied|Text ready/);
    const top3MessageEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(top3MessageEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'weekly_top3_message_copy' && event.section === 'top3-owner-share-strip-v1' && event.item_id && event.link_utm_source === 'message' && event.link_utm_medium === 'direct' && event.link_utm_campaign === 'daily-visits-500-weekly-top3-owner-share')).toBe(true);

    const copyButton = page.locator('[data-growth-share="weekly_copy_link"]').first();
    await copyButton.click();
    await expect(copyButton).toHaveText(/Copied|Link ready/);
    const shareEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(shareEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_copy_link' && event.section === 'owner-share-kit-v1' && event.component_experiment_id === 'owner-share-kit-v1')).toBe(true);
    expect(shareEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'weekly_copy_link' && event.section === 'owner-share-kit-v1' && event.component_experiment_id === 'owner-share-kit-v1')).toBe(true);

    await page.evaluate(() => {
      const link = document.querySelector('[data-growth-share="weekly_sms_draft"]') as HTMLAnchorElement | null;
      if (!link) throw new Error('missing weekly SMS draft link');
      link.addEventListener('click', (event) => event.preventDefault(), { once: true });
      link.click();
    });
    const smsDraftEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(smsDraftEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_sms_draft' && event.link_utm_source === 'message' && event.link_utm_medium === 'direct' && event.link_utm_campaign === 'daily-visits-500-weekly-owner-share')).toBe(true);

    await page.evaluate(() => {
      const link = document.querySelector('[data-growth-share="weekly_whatsapp_draft"]') as HTMLAnchorElement | null;
      if (!link) throw new Error('missing weekly WhatsApp draft link');
      link.addEventListener('click', (event) => event.preventDefault(), { once: true });
      link.click();
    });
    const whatsappDraftEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(whatsappDraftEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_whatsapp_draft' && event.link_utm_source === 'message' && event.link_utm_medium === 'direct' && event.link_utm_campaign === 'daily-visits-500-weekly-owner-share')).toBe(true);

    const nativeShareButton = page.locator('[data-growth-share="weekly_native_share"]').first();
    await nativeShareButton.click();
    await expect(nativeShareButton).toHaveText(/Shared|Copied|Text ready/);
    const nativeShareEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(nativeShareEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_native_share' && event.link_utm_source === 'native_share' && event.link_utm_medium === 'mobile' && event.link_utm_campaign === 'daily-visits-500-weekly-owner-share')).toBe(true);
    expect(nativeShareEvents.some((event: any) => event.event === 'growth_native_share_result' && event.share_action === 'weekly_native_share' && event.section === 'owner-share-kit-v1' && event.link_utm_source === 'native_share' && event.copy_mode && event.copy_text_length > 120)).toBe(true);
    expect(nativeShareEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'weekly_native_share' && event.section === 'owner-share-kit-v1' && event.link_utm_medium === 'mobile')).toBe(true);

    const directMessageButton = page.locator('[data-growth-share="weekly_message_copy"]').first();
    await directMessageButton.click();
    await expect(directMessageButton).toHaveText(/Copied|Text ready/);
    const directMessageEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(directMessageEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_message_copy' && event.component_experiment_id === 'owner-share-kit-v1' && event.link_utm_source === 'message' && event.link_utm_medium === 'direct')).toBe(true);
    expect(directMessageEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'weekly_message_copy' && event.copy_mode === 'brief_text' && event.section === 'owner-share-kit-v1' && event.link_utm_source === 'message' && event.link_utm_medium === 'direct')).toBe(true);

    await page.evaluate(() => {
      const link = document.querySelector('.quick-pick-card') as HTMLAnchorElement | null;
      if (!link) throw new Error('missing quick-pick card');
      link.addEventListener('click', (event) => event.preventDefault(), { once: true });
      link.click();
    });
    const quickPickEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(quickPickEvents.some((event: any) => event.event === 'growth_click' && event.type === 'cta_owner_quick_pick' && event.component_experiment_id === 'owner-quick-picks-v1' && event.item_id && String(event.href).includes('utm_medium=quick_pick') && event.link_utm_medium === 'quick_pick' && event.link_utm_campaign === 'daily-visits-500-weekly-owner-quick-picks')).toBe(true);

    await page.evaluate(() => {
      const link = document.querySelector('.owner-route-card') as HTMLAnchorElement | null;
      if (!link) throw new Error('missing owner route card');
      link.addEventListener('click', (event) => event.preventDefault(), { once: true });
      link.click();
    });
    const ownerRouteEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(ownerRouteEvents.some((event: any) => event.event === 'growth_click' && event.type === 'cta_owner_route_item' && event.component_experiment_id === 'owner-5-minute-route-v1' && event.item_id && String(event.href).includes('utm_medium=owner_route') && event.link_utm_medium === 'owner_route' && event.link_utm_campaign === 'daily-visits-500-weekly-owner-route')).toBe(true);

    const ownerRouteButton = page.locator('[data-growth-share="weekly_owner_route_copy"]').first();
    await ownerRouteButton.click();
    await expect(ownerRouteButton).toHaveText(/Copied|Text ready/);
    const ownerRouteCopyEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(ownerRouteCopyEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_owner_route_copy' && event.component_experiment_id === 'owner-5-minute-route-v1' && String(event.href).includes('daily-visits-500-weekly-owner-route') && event.link_utm_source === 'owner_share' && event.link_utm_medium === 'route_copy')).toBe(true);
    expect(ownerRouteCopyEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'weekly_owner_route_copy' && event.copy_mode === 'brief_text' && event.section === 'owner-5-minute-route-v1' && event.link_utm_campaign === 'daily-visits-500-weekly-owner-route')).toBe(true);

    await page.evaluate(() => {
      const link = document.querySelector('.focus-card') as HTMLAnchorElement | null;
      if (!link) throw new Error('missing focus-watchlist card');
      link.addEventListener('click', (event) => event.preventDefault(), { once: true });
      link.click();
    });
    const focusEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(focusEvents.some((event: any) => event.event === 'growth_click' && event.type === 'cta_evidence_focus_watchlist' && event.component_experiment_id === 'evidence-focus-watchlist-v1' && event.item_id && String(event.href).includes('utm_medium=focus_watchlist') && event.link_utm_medium === 'focus_watchlist')).toBe(true);

    await page.evaluate(() => {
      const link = document.querySelector('.category-landing-card') as HTMLAnchorElement | null;
      if (!link) throw new Error('missing category landing card');
      link.addEventListener('click', (event) => event.preventDefault(), { once: true });
      link.click();
    });
    const categoryNavEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(categoryNavEvents.some((event: any) => event.event === 'growth_click' && event.type === 'cta_category_landing_nav' && event.component_experiment_id === 'category-landing-pages-v1' && event.category_id && String(event.href).includes('utm_medium=category_nav') && event.link_utm_campaign === 'daily-visits-500-category-landing-pages')).toBe(true);

    await page.evaluate(() => {
      const link = document.querySelector('[data-growth-section="top3-leaderboard-v1"] .podium-card') as HTMLAnchorElement | null;
      if (!link) throw new Error('missing top3 podium card');
      link.addEventListener('click', (event) => event.preventDefault(), { once: true });
      link.click();
    });
    const podiumEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(podiumEvents.some((event: any) => event.event === 'growth_click' && event.type === 'podium_card' && event.section === 'top3-leaderboard-v1' && event.component_experiment_id === 'ranking-list-engagement-context-v1' && event.item_id && event.item_rank)).toBe(true);

    await page.evaluate(() => {
      const link = document.querySelector('[data-growth-section="ranking-main-list-v1"] .rank-card .rank-hit') as HTMLAnchorElement | null;
      if (!link) throw new Error('missing ranking list item card');
      link.addEventListener('click', (event) => event.preventDefault(), { once: true });
      link.click();
    });
    const rankCardEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(rankCardEvents.some((event: any) => event.event === 'growth_click' && event.type === 'item_card' && event.section === 'ranking-main-list-v1' && event.component_experiment_id === 'ranking-list-engagement-context-v1' && event.item_id && event.item_rank)).toBe(true);

    const ownerBriefButton = page.locator('[data-growth-share="weekly_owner_brief_copy"]').first();
    await ownerBriefButton.click();
    await expect(ownerBriefButton).toHaveText(/Copied|Text ready/);
    const ownerBriefEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(ownerBriefEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_owner_brief_copy' && event.component_experiment_id === 'owner-brief-copy-v1' && String(event.href).includes('daily-visits-500-weekly-owner-brief'))).toBe(true);
    expect(ownerBriefEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'weekly_owner_brief_copy' && event.copy_mode === 'brief_text' && event.copy_text_length > 120 && event.section === 'owner-brief-copy-v1')).toBe(true);

    const feedCopyButton = page.locator('[data-growth-share="weekly_feed_copy"]').first();
    await feedCopyButton.click();
    await expect(feedCopyButton).toHaveText(/Copied|Link ready/);
    const feedEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(feedEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_feed_copy' && event.component_experiment_id === 'owner-feed-subscribe-v1' && String(event.href).includes('daily-visits-500-owner-feed-subscribe'))).toBe(true);
    expect(feedEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'weekly_feed_copy' && event.section === 'owner-feed-subscribe-v1' && event.component_experiment_id === 'owner-feed-subscribe-v1' && String(event.href).includes('feed.xml'))).toBe(true);

    const shortcutCopyButton = page.locator('[data-growth-share="weekly_shortcut_copy"]').first();
    await shortcutCopyButton.click();
    await expect(shortcutCopyButton).toHaveText(/Copied|Link ready/);
    const shortcutEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(shortcutEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_shortcut_copy' && event.component_experiment_id === 'owner-shortcut-save-v1' && String(event.href).includes('daily-visits-500-owner-shortcut'))).toBe(true);
    expect(shortcutEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'weekly_shortcut_copy' && event.section === 'owner-shortcut-save-v1' && event.component_experiment_id === 'owner-shortcut-save-v1' && String(event.href).includes('daily-visits-500-owner-shortcut'))).toBe(true);

    await page.evaluate(() => {
      const link = document.querySelector('[data-growth-cta="owner_calendar_download"]') as HTMLAnchorElement | null;
      if (!link) throw new Error('missing owner calendar download link');
      link.addEventListener('click', (event) => event.preventDefault(), { once: true });
      link.click();
    });
    const calendarClickEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(calendarClickEvents.some((event: any) => event.event === 'growth_click' && event.type === 'cta_owner_calendar_download' && event.component_experiment_id === 'owner-calendar-reminder-v1' && String(event.href).includes('owner-weekly-reminder.ics'))).toBe(true);

    const calendarTextButton = page.locator('[data-growth-share="weekly_calendar_message_copy"]').first();
    await calendarTextButton.click();
    await expect(calendarTextButton).toHaveText(/Copied|Text ready/);
    const calendarEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(calendarEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_calendar_message_copy' && event.component_experiment_id === 'owner-calendar-reminder-v1' && String(event.href).includes('daily-visits-500-owner-calendar-reminder'))).toBe(true);
    expect(calendarEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'weekly_calendar_message_copy' && event.section === 'owner-calendar-reminder-v1' && event.copy_mode === 'brief_text')).toBe(true);

    const printSheetButton = page.locator('[data-growth-share="weekly_owner_print_sheet_copy"]').first();
    await printSheetButton.click();
    await expect(printSheetButton).toHaveText(/Copied|Text ready/);
    const printSheetEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(printSheetEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_weekly_owner_print_sheet_copy' && event.component_experiment_id === 'owner-print-sheet-v1' && String(event.href).includes('daily-visits-500-owner-print-sheet'))).toBe(true);
    expect(printSheetEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'weekly_owner_print_sheet_copy' && event.section === 'owner-print-sheet-v1' && event.link_utm_medium === 'print_sheet')).toBe(true);

    const engagementResult = await page.evaluate(() => {
      const growth = (window as any).__GNS_GROWTH__;
      const summary = growth?.flushEngagementSummary?.('playwright_manual');
      return { summary, events: growth?.events?.() ?? [] };
    });
    expect(engagementResult.summary?.type).toBe('engagement_summary');
    expect(engagementResult.summary?.reason).toBe('playwright_manual');
    expect(engagementResult.summary?.page_type).toBe('home');
    expect(engagementResult.summary?.timeframe).toBe('weekly_home');
    expect(engagementResult.summary?.max_scroll_depth_percent).toBeGreaterThan(0);
    expect(engagementResult.summary?.viewed_section_count).toBeGreaterThanOrEqual(1);
    expect(String(engagementResult.summary?.viewed_sections)).toContain('owner-quick-picks-v1');
    expect(engagementResult.summary?.share_click_count).toBeGreaterThanOrEqual(3);
    expect(engagementResult.summary?.copy_result_count).toBeGreaterThanOrEqual(3);
    expect(engagementResult.events.some((event: any) => event.event === 'growth_engagement_summary' && event.reason === 'playwright_manual' && event.goal_id === 'daily-visits-500')).toBe(true);

    await page.getByRole('link', { name: '이번 주 팔아볼 제품 보기' }).click();
    await expect(page).toHaveURL(/\/rankings\/weekly\.html/);
    const clickEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(clickEvents.some((event: any) => event.event === 'growth_click' && event.type === 'cta_primary')).toBe(true);
    const postCtaAttribution = await page.evaluate(() => (window as any).__GNS_GROWTH__?.attribution?.());
    expect(postCtaAttribution.first.utm_source).toBe('e2e');
    expect(postCtaAttribution.current.utm_source).toBe('site');
    expect(clickEvents.some((event: any) => event.event === 'growth_exposure' && event.page_type === 'ranking' && event.first_utm_source === 'e2e' && event.current_utm_source === 'site')).toBe(true);

    await page.locator('#all-items .rank-card .rank-hit').first().click();
    await expect(page).toHaveURL(/\/items\/.+\.html$/);
    const itemExposure = await page.evaluate(() => {
      const events = (window as any).__GNS_GROWTH__?.events?.() ?? [];
      const exposures = events.filter((event: any) => event.event === 'growth_exposure' && event.page_type === 'item_detail');
      return exposures[exposures.length - 1];
    });
    expect(itemExposure.utm_source).toBe('site');
    expect(itemExposure.first_utm_source).toBe('e2e');
    expect(itemExposure.page_item_id).toMatch(/.+/);
    expect(itemExposure.session_id).toMatch(/^gns_/);

    const goalResponse = await request.get('/data/growth_goal_public.json');
    expect(goalResponse.status()).toBeLessThan(400);
    const goal = await goalResponse.json();
    expect(goal.primary_goal?.target).toBe(500);
    expect(goal.analytics_providers?.ga4?.measurement_id).toBe('G-SW7HBY6WRE');
    expect(String(goal.analytics_providers?.vercel_web_analytics?.status ?? '')).toMatch(/^enabled/);
    expect(goal.measurement_status?.rolling_30d_average_daily_visits).not.toBeNull();
    expect(goal.measurement_status?.vercel_web_analytics?.status).toBe('measured');
    expect(goal.sns_strategy?.tool).toBe('xurl');
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'hero-growth-cta-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'utm-attribution-persistence-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'owner-brief-copy-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'source-evidence-clicks-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'section-visibility-engagement-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'run-change-snapshot-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'evidence-window-transparency-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'evidence-focus-watchlist-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'timeframe-evidence-ladder-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'engagement-summary-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'ranking-list-engagement-context-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'apify-sharded-fallback-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'post-review-site-sync-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'return-visitor-attribution-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'return-visitor-prompt-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'social-share-preview-card-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'basic-analytics-measurement-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'ranking-first-layout-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'rss-owner-feed-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'owner-feed-subscribe-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'focus-query-diversification-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'item-evidence-summary-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'owner-calendar-reminder-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'link-destination-utm-context-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'collection-evidence-regression-recovery-v1')).toBe(true);
    expect(goal.initial_experiments?.some((experiment: any) => experiment.experiment_id === 'direct-message-owner-share-v1')).toBe(true);
  });

  test('category landing pages focus broad store lanes into item-level owner actions', async ({ page, request }) => {
    await page.goto('/categories/wigs-hair-pieces.html?utm_source=e2e&utm_medium=category_page&utm_campaign=daily-visits-500-category-landing-pages');

    await expect(page).toHaveTitle(/Wigs & Hair Pieces Category · BSS Trend Ranking/);
    await expect(page.locator('body')).toHaveAttribute('data-page-type', 'category');
    await expect(page.getByRole('heading', { name: 'Wigs & Hair Pieces item ranking' })).toBeVisible();
    await expect(page.getByText('Category health')).toBeVisible();
    await expect(page.locator('meta[property="og:image"]')).toHaveAttribute('content', 'https://gnsresearchhub.vercel.app/assets/share-category-wigs-hair-pieces.svg');
    await expect(page.locator('meta[name="twitter:image"]')).toHaveAttribute('content', 'https://gnsresearchhub.vercel.app/assets/share-category-wigs-hair-pieces.svg');
    const categoryShareResponse = await request.get('/assets/share-category-wigs-hair-pieces.svg');
    expect(categoryShareResponse.status()).toBeLessThan(400);
    const categoryShareSvg = await categoryShareResponse.text();
    expect(categoryShareSvg).toContain('BSS CATEGORY LANE · WEEKLY');
    expect(categoryShareSvg).toContain('Wigs &amp; Hair Pieces');
    expect(categoryShareSvg).toContain('Concrete item types only');
    await expect(page.locator('[data-growth-section="category-share-kit-v1"]')).toHaveAttribute('data-growth-experiment', 'category-landing-pages-v1');
    await expect(page.locator('[data-growth-section="category-brief-copy-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="category-brief-copy-v1"]')).toHaveAttribute('data-growth-experiment', 'category-brief-copy-v1');
    await expect(page.locator('[data-growth-section="category-brief-copy-v1"]')).toHaveAttribute('data-category-id', 'wigs-hair-pieces');
    await expect(page.getByRole('heading', { name: 'Wigs & Hair Pieces category owner brief' })).toBeVisible();
    await expect(page.locator('[data-growth-section="category-top-items-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="category-owner-test-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="category-ranking-list-v1"]')).toBeVisible();
    await expect(page.locator('#all-items .rank-card')).toHaveCount(5);
    await expect(page.locator('[data-growth-share="category_copy_link"]')).toHaveAttribute('data-copy-url', /daily-visits-500-category-landing-pages/);
    await expect(page.locator('[data-growth-share="category_brief_copy"]')).toHaveAttribute('data-copy-url', /utm_medium=category_brief/);
    await expect(page.locator('[data-growth-share="category_brief_copy"]')).toHaveAttribute('data-copy-url', /daily-visits-500-category-brief-copy/);
    await expect(page.locator('[data-growth-share="category_brief_copy"]')).toHaveAttribute('data-copy-text', /BSS category owner brief/);
    await expect(page.locator('[data-growth-share="category_brief_copy"]')).toHaveAttribute('data-copy-text', /Display test/);

    const categoryContext = await page.evaluate(() => {
      const growth = (window as any).__GNS_GROWTH__;
      return {
        categoryId: growth?.pageCategoryId?.(),
        sections: growth?.growthSections?.() ?? [],
        events: growth?.events?.() ?? [],
      };
    });
    expect(categoryContext.categoryId).toBe('wigs-hair-pieces');
    expect(categoryContext.sections.some((section: any) => section.id === 'category-share-kit-v1')).toBe(true);
    expect(categoryContext.sections.some((section: any) => section.id === 'category-brief-copy-v1')).toBe(true);
    expect(categoryContext.events.some((event: any) => event.event === 'growth_exposure' && event.page_type === 'category' && event.timeframe === 'weekly_category' && event.page_category_id === 'wigs-hair-pieces')).toBe(true);

    await page.locator('[data-growth-section="category-brief-copy-v1"]').scrollIntoViewIfNeeded();
    await page.waitForFunction(() =>
      ((window as any).__GNS_GROWTH__?.events?.() ?? []).some(
        (event: any) => event.event === 'growth_section_view' && event.section === 'category-brief-copy-v1' && event.category_id === 'wigs-hair-pieces',
      ),
    );

    const categoryBriefButton = page.locator('[data-growth-share="category_brief_copy"]');
    await categoryBriefButton.click();
    await expect(categoryBriefButton).toHaveText(/Copied|Text ready/);
    const briefEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(briefEvents.some((event: any) => event.event === 'growth_click' && event.type === 'share_category_brief_copy' && event.component_experiment_id === 'category-brief-copy-v1' && event.category_id === 'wigs-hair-pieces' && event.link_utm_medium === 'category_brief' && event.link_utm_campaign === 'daily-visits-500-category-brief-copy')).toBe(true);
    expect(briefEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'category_brief_copy' && event.copy_mode === 'brief_text' && event.category_id === 'wigs-hair-pieces' && event.link_utm_medium === 'category_brief' && event.copy_text_length > 180)).toBe(true);

    const copyButton = page.locator('[data-growth-share="category_copy_link"]');
    await copyButton.click();
    await expect(copyButton).toHaveText(/Copied|Link ready/);
    const copyEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(copyEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'category_copy_link' && event.category_id === 'wigs-hair-pieces')).toBe(true);
  });

  test('return visitor prompt appears and is event-tracked on a later visit', async ({ page }) => {
    await page.goto('/index.html?variant=A&utm_source=e2e_first&utm_medium=playwright&utm_campaign=daily-visits-500');
    const firstVisit = await page.evaluate(() => {
      const growth = (window as any).__GNS_GROWTH__;
      return { visitor: growth?.visitor?.(), sessionId: growth?.sessionId };
    });
    expect(firstVisit.visitor?.visit_count).toBe(1);
    expect(firstVisit.visitor?.is_returning_visitor).toBe(false);
    expect(firstVisit.sessionId).toMatch(/^gns_/);
    await expect(page.locator('[data-return-visitor-panel]')).toBeHidden();

    await page.evaluate(() => {
      const key = 'gns_growth:visitor';
      const stored = JSON.parse(window.localStorage.getItem(key) || '{}');
      stored.visit_count = Math.max(1, Number(stored.visit_count || 1));
      stored.last_visit_at = new Date(Date.now() - (31 * 60 * 1000)).toISOString();
      window.localStorage.setItem(key, JSON.stringify(stored));
    });

    await page.goto('/index.html?variant=A&utm_source=return_test&utm_medium=direct&utm_campaign=daily-visits-500-return-visitor-prompt');
    const panel = page.locator('[data-return-visitor-panel]');
    await expect(panel).toBeVisible();
    await expect(panel).toHaveAttribute('data-growth-section', 'return-visitor-prompt-v1');
    await expect(panel).toHaveAttribute('data-growth-experiment', 'return-visitor-prompt-v1');
    await expect(panel).toHaveAttribute('data-visit-count', '2');
    await expect(panel).toContainText('Visit #2');
    await expect(panel.getByRole('link', { name: 'Current ranking 보기' })).toHaveAttribute('href', /daily-visits-500-return-visitor-prompt/);

    const returnVisit = await page.evaluate(() => {
      const growth = (window as any).__GNS_GROWTH__;
      return {
        visitor: growth?.visitor?.(),
        sessionId: growth?.sessionId,
        sections: growth?.growthSections?.() ?? [],
        events: growth?.events?.() ?? [],
      };
    });
    expect(returnVisit.visitor?.is_returning_visitor).toBe(true);
    expect(returnVisit.visitor?.visit_count).toBe(2);
    expect(returnVisit.sessionId).toMatch(/^gns_/);
    expect(returnVisit.sessionId).not.toBe(firstVisit.sessionId);
    expect(returnVisit.sections.some((section: any) => section.id === 'return-visitor-prompt-v1')).toBe(true);
    expect(returnVisit.events.some((event: any) => event.event === 'growth_return_visit_prompt' && event.section === 'return-visitor-prompt-v1' && event.visit_count === 2 && event.is_returning_visitor === true)).toBe(true);
    expect(returnVisit.events.some((event: any) => event.event === 'growth_exposure' && event.is_returning_visitor === true && String(event.visible_growth_sections).includes('return-visitor-prompt-v1'))).toBe(true);
  });

  test('timeframe tabs and category chips navigate to working ranking sections', async ({ page }) => {
    for (const [label, path] of timeframes) {
      await page.goto(path);

      await expect(page.locator('.tabs a.active')).toHaveText(label);
      await expect(page.getByRole('heading', { name: `${label} ranking` })).toBeVisible();
      await expect(page.locator('meta[property="og:image"]')).toHaveAttribute('content', `https://gnsresearchhub.vercel.app/assets/share-${label.toLowerCase()}.svg`);
      await expect(page.locator('[data-growth-section="run-change-snapshot-v1"]')).toBeVisible();
      await expect(page.locator('[data-growth-section="evidence-gap-transparency-v1"]')).toBeVisible();
      await expect(page.locator('[data-growth-section="timeframe-evidence-ladder-v1"]')).toBeVisible();
      await expect(page.locator('.evidence-ladder-card.active')).toHaveAttribute('data-growth-timeframe', label.toLowerCase());
      await expect(page.locator('[data-growth-section="evidence-focus-watchlist-v1"]')).toBeVisible();
      await expect(page.locator('[data-growth-section="owner-quick-picks-v1"]')).toBeVisible();
      await expect(page.locator('[data-growth-section="owner-5-minute-route-v1"]')).toBeVisible();
      await expect(page.locator('[data-growth-section="owner-5-minute-route-v1"]')).toHaveAttribute('data-growth-experiment', 'owner-5-minute-route-v1');
      await expect(page.locator('[data-growth-section="owner-brief-copy-v1"]')).toBeVisible();
      await expect(page.locator('[data-growth-section="owner-feed-subscribe-v1"]')).toBeVisible();
      await expect(page.locator('[data-growth-section="owner-shortcut-save-v1"]')).toBeVisible();
      await expect(page.locator('[data-growth-section="owner-calendar-reminder-v1"]')).toBeVisible();
      await expect(page.locator('[data-growth-section="owner-print-sheet-v1"]')).toBeVisible();
      await expect(page.locator('[data-growth-share$="_owner_brief_copy"]')).toHaveAttribute('data-copy-text', /BSS owner brief/);
      await expect(page.locator('[data-growth-share$="_owner_route_copy"]')).toHaveAttribute('data-copy-text', /5-minute owner route/);
      await expect(page.locator('[data-growth-share$="_owner_route_copy"]')).toHaveAttribute('data-copy-url', /daily-visits-500-.*-owner-route/);
      await expect(page.locator('[data-growth-share$="_feed_copy"]')).toHaveAttribute('data-copy-url', /daily-visits-500-owner-feed-subscribe/);
      await expect(page.locator('[data-growth-share$="_shortcut_copy"]')).toHaveAttribute('data-copy-url', /daily-visits-500-owner-shortcut/);
      await expect(page.locator('[data-growth-share$="_calendar_message_copy"]')).toHaveAttribute('data-copy-text', /BSS weekly ranking reminder/);
      await expect(page.locator('[data-growth-share$="_owner_print_sheet_copy"]')).toHaveAttribute('data-copy-url', /daily-visits-500-owner-print-sheet/);
      await expect(page.locator('[data-growth-cta="owner_calendar_download"]')).toHaveAttribute('href', /daily-visits-500-owner-calendar-reminder/);
      await expect(page.locator('.quick-pick-card').first()).toHaveAttribute('href', new RegExp(`daily-visits-500-${label.toLowerCase()}-owner-quick-picks`));
      expect(await page.locator('#all-items .rank-card').count()).toBeGreaterThan(0);
      await expect(page.locator('#all-items .rank-card').first().locator('.owner-actions')).toBeVisible();

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

  test('ranking cards click through to item detail pages and back', async ({ page, request }) => {
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
    await expect(page.locator('[data-growth-section="source-evidence-clicks-v1"]')).toBeVisible();
    const firstSourceCard = page.locator('.source-card').first();
    await expect(firstSourceCard).toHaveAttribute('data-growth-source-layer', /.+/);
    await expect(firstSourceCard).toHaveAttribute('data-growth-source-kind', /.+/);
    await expect(firstSourceCard).toHaveAttribute('data-growth-source-type', /.+/);
    await expect(firstSourceCard).toHaveAttribute('data-growth-source-status', /.+/);
    await expect(firstSourceCard).toHaveAttribute('data-growth-source-domain', /.+/);
    await expect(firstSourceCard).toHaveAttribute('data-growth-source-discovery-kind', /.+/);
    await firstSourceCard.evaluate((element) => {
      element.addEventListener('click', (event) => event.preventDefault(), { once: true });
      (element as HTMLAnchorElement).click();
    });
    const sourceClickEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(sourceClickEvents.some((event: any) => event.event === 'growth_click' && event.type === 'source_link' && event.section === 'source-evidence-clicks-v1' && event.component_experiment_id === 'source-evidence-clicks-v1' && event.source_layer && event.source_kind && event.source_status && event.source_domain && event.source_discovery_kind)).toBe(true);
    const detailOgImage = await page.locator('meta[property="og:image"]').getAttribute('content');
    expect(detailOgImage).toMatch(/https:\/\/gnsresearchhub\.vercel\.app\/assets\/share-item-.+\.svg$/);
    await expect(page.locator('meta[name="twitter:image"]')).toHaveAttribute('content', detailOgImage ?? '');
    const itemShareCardPath = new URL(detailOgImage ?? '').pathname;
    const itemShareCardResponse = await request.get(itemShareCardPath);
    expect(itemShareCardResponse.status()).toBeLessThan(400);
    const itemShareCardSvg = await itemShareCardResponse.text();
    expect(itemShareCardSvg).toContain('BSS ITEM DETAIL · WEEKLY');
    expect(itemShareCardSvg).toContain('Evidence status');
    expect(itemShareCardSvg).toContain(itemName);
    await expect(page.locator('.item-share-kit')).toBeVisible();
    await expect(page.locator('.item-share-kit')).toHaveAttribute('data-growth-section', 'item-detail-share-card-v1');
    await expect(page.locator('.item-share-kit')).toHaveAttribute('data-growth-experiment', 'item-detail-share-card-v1');
    await expect(page.locator('[data-growth-section="item-evidence-summary-v1"]')).toBeVisible();
    await expect(page.locator('[data-growth-section="item-evidence-summary-v1"]')).toHaveAttribute('data-growth-experiment', 'item-evidence-summary-v1');
    await expect(page.getByRole('heading', { name: '이 item을 trend로 말해도 되는지 먼저 확인' })).toBeVisible();
    await expect(page.locator('.item-evidence-grid article')).toHaveCount(4);
    await expect(page.locator('[data-growth-cta="item_evidence_source_jump"]')).toHaveAttribute('href', '#source-links');
    const evidenceSummaryButton = page.locator('[data-growth-share="item_evidence_summary_copy"]').first();
    await expect(evidenceSummaryButton).toHaveAttribute('data-copy-url', /daily-visits-500-item-evidence-summary/);
    await expect(evidenceSummaryButton).toHaveAttribute('data-copy-text', /BSS item evidence check/);
    await evidenceSummaryButton.click();
    await expect(evidenceSummaryButton).toHaveText(/Copied|Text ready/);
    const evidenceSummaryEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(evidenceSummaryEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'item_evidence_summary_copy' && event.section === 'item-evidence-summary-v1' && event.component_experiment_id === 'item-evidence-summary-v1' && event.copy_mode === 'brief_text' && event.link_utm_medium === 'evidence_summary')).toBe(true);
    const itemCopyButton = page.locator('[data-growth-share="item_copy_link"]').first();
    await expect(itemCopyButton).toHaveAttribute('data-copy-url', /utm_campaign=daily-visits-500-item-detail-share/);
    await expect(itemCopyButton).toHaveAttribute('data-copy-url', /utm_content=/);
    await expect(page.locator('[data-growth-share="item_sms_draft"]')).toHaveAttribute('href', /^sms:/);
    await expect(page.locator('[data-growth-share="item_whatsapp_draft"]')).toHaveAttribute('href', /^https:\/\/wa\.me\/\?text=/);
    await expect(page.locator('[data-growth-share="item_native_share"]')).toHaveAttribute('data-native-share', 'true');
    await expect(page.locator('[data-growth-share="item_native_share"]')).toHaveAttribute('data-native-share-url', /utm_source=native_share/);
    await expect(page.locator('[data-growth-share="item_native_share"]')).toHaveAttribute('data-native-share-url', /utm_campaign=daily-visits-500-item-detail-share/);
    await expect(page.locator('[data-growth-share="item_native_share"]')).toHaveAttribute('data-native-share-text', /BSS item detail mobile share/);
    await expect(page.locator('[data-growth-share="item_message_copy"]')).toHaveAttribute('data-copy-url', /utm_source=message/);
    await expect(page.locator('[data-growth-share="item_message_copy"]')).toHaveAttribute('data-copy-url', /utm_medium=direct/);
    await expect(page.locator('[data-growth-share="item_message_copy"]')).toHaveAttribute('data-copy-text', /BSS item detail text/);
    await itemCopyButton.click();
    await expect(itemCopyButton).toHaveText(/Copied|Link ready/);
    const itemShareEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(itemShareEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'item_copy_link' && event.section === 'item-detail-share-card-v1' && event.component_experiment_id === 'item-detail-share-card-v1' && event.link_utm_source === 'owner_share' && event.link_utm_campaign === 'daily-visits-500-item-detail-share')).toBe(true);

    const itemNativeShareButton = page.locator('[data-growth-share="item_native_share"]').first();
    await itemNativeShareButton.click();
    await expect(itemNativeShareButton).toHaveText(/Shared|Copied|Text ready/);
    const itemNativeShareEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(itemNativeShareEvents.some((event: any) => event.event === 'growth_native_share_result' && event.share_action === 'item_native_share' && event.section === 'item-detail-share-card-v1' && event.link_utm_source === 'native_share' && event.link_utm_campaign === 'daily-visits-500-item-detail-share')).toBe(true);
    expect(itemNativeShareEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'item_native_share' && event.copy_text_length > 120 && event.link_utm_medium === 'mobile')).toBe(true);

    const itemMessageButton = page.locator('[data-growth-share="item_message_copy"]').first();
    await itemMessageButton.click();
    await expect(itemMessageButton).toHaveText(/Copied|Text ready/);
    const itemMessageEvents = await page.evaluate(() => (window as any).__GNS_GROWTH__?.events?.() ?? []);
    expect(itemMessageEvents.some((event: any) => event.event === 'growth_share_copy_result' && event.share_action === 'item_message_copy' && event.section === 'item-detail-share-card-v1' && event.copy_mode === 'brief_text' && event.link_utm_source === 'message' && event.link_utm_medium === 'direct' && event.link_utm_campaign === 'daily-visits-500-item-detail-share')).toBe(true);

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
    expect(review.collection_health?.coverage_gap_summary?.published_trend_missing_items).toBeGreaterThanOrEqual(0);
    expect(review.collection_evidence_deltas).toBeTruthy();
    const collectionDeltas = Object.values(review.collection_evidence_deltas ?? {}) as any[];
    if (collectionDeltas.length > 0) {
      expect(collectionDeltas.some((delta: any) => String(delta.label ?? '').includes('published trend'))).toBe(true);
    }
    expect(review.independent_ai_review?.review_type).toBe('independent_ai_operator_review');
    expect(review.independent_ai_review?.primary_growth_blockers?.some((blocker: string) => /analytics export/i.test(blocker))).toBe(true);
    expect(review.material_changes?.length).toBeGreaterThan(0);
    const watchlistRegressionBlocker = review.independent_ai_review?.primary_growth_blockers?.some((blocker: string) => /Coverage regression detected:.*WATCHLIST item count/i.test(blocker));
    if (watchlistRegressionBlocker) {
      expect(review.material_changes?.some((note: string) => /Needs recovery: WATCHLIST item count/i.test(note))).toBe(true);
    }

    const weeklyTop3Ids = (rankings.rankings?.weekly ?? [])
      .filter((row: any) => Number(row.source_counts?.trend_evidence ?? 0) > 0)
      .slice(0, 3)
      .map((row: any) => row.item_id);

    const collectionResponse = await request.get('/data/collection_notes_public.json');
    expect(collectionResponse.status()).toBeLessThan(400);
    const collection = await collectionResponse.json();
    expect(collection.evidence_totals?.items_requested).toBeGreaterThan(0);
    expect(collection.source_health?.apify_tiktok_shop?.status).toBeTruthy();
    expect(collection.coverage_gaps?.summary?.published_trend_missing_items).toBeGreaterThanOrEqual(0);
    expect(collection.coverage_gaps?.weak_categories?.length).toBeGreaterThan(0);
    expect(collection.source_cap_policy?.policy_id).toBe('trend_preserving_verified_source_cap_v1');
    expect(collection.source_cap_policy?.published_first).toBe(true);
    expect(collection.supplemental_trend_query_policy?.policy_id).toBe('supplemental_item_look_published_query_v1');
    expect(collection.supplemental_trend_query_policy?.mapped_items).toBeGreaterThanOrEqual(20);
    expect(collection.supplemental_trend_query_policy?.purpose).toMatch(/Tools\/Accessories/i);
    expect(collection.supplemental_trend_query_policy?.discipline).toMatch(/Generated search URLs are still non-evidence/i);

    const marketingResponse = await request.get('/data/marketing_backlog_public.json');
    expect(marketingResponse.status()).toBeLessThan(400);
    const marketing = await marketingResponse.json();
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'owner-share-kit-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'top3-owner-share-strip-v1')).toBe(true);
    const top3Campaign = marketing.active_campaigns?.find((campaign: any) => campaign.campaign_id === 'top3-owner-share-strip-v1');
    expect(top3Campaign?.last_refreshed_at).toBeTruthy();
    const draftIds = (top3Campaign?.drafts?.x_twitter_top3_weekly ?? []).map((draft: any) => draft.item_id);
    if (review.source_generated_at === rankings.generated_at) {
      expect(top3Campaign?.quality_control?.current_weekly_top3_item_ids).toEqual(weeklyTop3Ids);
      expect(draftIds).toEqual(weeklyTop3Ids);
    } else {
      // During the pre-review build inside npm run test:e2e, public marketing may
      // still reflect the previous review if the collector just changed Top 3.
      // The post-Playwright review step must resync it before deployment.
      expect(top3Campaign?.quality_control?.current_weekly_top3_item_ids?.length).toBeGreaterThan(0);
      expect(draftIds.length).toBeGreaterThan(0);
      expect(draftIds.every((itemId: string) => Boolean(itemId))).toBe(true);
    }
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'marketing-draft-freshness-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'owner-brief-copy-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'source-evidence-clicks-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'evidence-window-transparency-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'evidence-focus-watchlist-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'timeframe-evidence-ladder-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'engagement-summary-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'ranking-list-engagement-context-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'return-visitor-attribution-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'return-visitor-prompt-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'social-share-preview-card-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'ranking-first-layout-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'rss-owner-feed-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'owner-feed-subscribe-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'focus-query-diversification-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'supplemental-trend-query-coverage-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'collection-evidence-regression-recovery-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'item-evidence-summary-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'owner-calendar-reminder-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'link-destination-utm-context-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'direct-message-owner-share-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'whatsapp-owner-share-v1')).toBe(true);
    expect(marketing.active_campaigns?.some((campaign: any) => campaign.campaign_id === 'native-mobile-share-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'social-share-preview-card-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'ranking-first-layout-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'rss-owner-feed-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'owner-feed-subscribe-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'focus-query-diversification-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'supplemental-trend-query-coverage-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'collection-evidence-regression-recovery-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'item-evidence-summary-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'owner-calendar-reminder-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'link-destination-utm-context-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'direct-message-owner-share-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'whatsapp-owner-share-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'native-mobile-share-v1')).toBe(true);
    expect(marketing.experiment_backlog?.some((experiment: any) => experiment.experiment_id === 'timeframe-evidence-ladder-v1')).toBe(true);
    const socialShareCampaign = marketing.active_campaigns?.find((campaign: any) => campaign.campaign_id === 'social-share-preview-card-v1');
    expect(socialShareCampaign?.live_locations).toContain('https://gnsresearchhub.vercel.app/assets/share-weekly.svg');
    const rssCampaign = marketing.active_campaigns?.find((campaign: any) => campaign.campaign_id === 'rss-owner-feed-v1');
    expect(rssCampaign?.live_locations).toContain('https://gnsresearchhub.vercel.app/feed.xml');

    const feedResponse = await request.get('/feed.xml');
    expect(feedResponse.status()).toBeLessThan(400);
    const feed = await feedResponse.text();
    expect(feed).toContain('<rss version="2.0"');
    expect(feed).toContain('BSS Trend Ranking · Weekly Owner Picks');
    expect(feed).toContain('daily-visits-500-rss-feed');
    expect(feed).toContain('utm_source=rss');
    expect(feed).toContain('Published URLs drive trend movement');
    const weeklyTopItemName = rankings.rankings?.weekly?.[0]?.item_name;
    if (weeklyTopItemName) {
      expect(feed).toContain(weeklyTopItemName);
    }

    const manifestResponse = await request.get('/manifest.webmanifest');
    expect(manifestResponse.status()).toBeLessThan(400);
    const manifest = await manifestResponse.json();
    expect(manifest.start_url).toContain('utm_medium=shortcut');
    expect(manifest.start_url).toContain('daily-visits-500-owner-shortcut');
    expect(manifest.shortcuts?.some((shortcut: any) => String(shortcut.url).includes('/rankings/weekly.html'))).toBe(true);
    const iconResponse = await request.get('/assets/app-icon.svg');
    expect(iconResponse.status()).toBeLessThan(400);

    const calendarResponse = await request.get('/owner-weekly-reminder.ics');
    expect(calendarResponse.status()).toBeLessThan(400);
    const calendar = await calendarResponse.text();
    const unfoldedCalendar = calendar.replace(/\r?\n[ \t]/g, '');
    expect(calendar).toContain('BEGIN:VCALENDAR');
    expect(calendar).toContain('RRULE:FREQ=WEEKLY;COUNT=26');
    expect(unfoldedCalendar).toContain('daily-visits-500-owner-calendar-reminder');
    expect(unfoldedCalendar).toContain('utm_source=calendar');

    const ownerSheetResponse = await request.get('/owner-share-sheet.html');
    expect(ownerSheetResponse.status()).toBeLessThan(400);
    const ownerSheet = await ownerSheetResponse.text();
    expect(ownerSheet).toContain('Owner handout · print/screenshot ready');
    expect(ownerSheet).toContain('print-sheet-leaders-v1');
    expect(ownerSheet).toContain('daily-visits-500-owner-print-sheet');

    const focusResponse = await request.get('/data/next_loop_focus_public.json');
    expect(focusResponse.status()).toBeLessThan(400);
    const focus = await focusResponse.json();
    expect(focus.focus_items?.length).toBeGreaterThan(0);
    expect(focus.focus_items?.[0]?.queries).toBeUndefined();

    const snsRulesResponse = await request.get('/data/sns_posting_rules_public.json');
    expect(snsRulesResponse.status()).toBeLessThan(400);
    const snsRules = await snsRulesResponse.json();
    expect(snsRules.primary_channel?.tool).toBe('xurl');
    expect(snsRules.posting_rule?.frequency_limits?.standard_post).toBe('max_1_per_day');
    expect(snsRules.measurement?.events).toContain('growth_engagement_summary');

    const robotsResponse = await request.get('/robots.txt');
    expect(robotsResponse.status()).toBeLessThan(400);
    expect(await robotsResponse.text()).toContain('Sitemap: https://gnsresearchhub.vercel.app/sitemap.xml');

    const sitemapResponse = await request.get('/sitemap.xml');
    expect(sitemapResponse.status()).toBeLessThan(400);
    const sitemap = await sitemapResponse.text();
    expect(sitemap).toContain('<loc>https://gnsresearchhub.vercel.app/index.html</loc>');
    expect(sitemap).toContain('<loc>https://gnsresearchhub.vercel.app/feed.xml</loc>');
    expect(sitemap).toContain('<loc>https://gnsresearchhub.vercel.app/owner-share-sheet.html</loc>');
    expect(sitemap).toContain('<loc>https://gnsresearchhub.vercel.app/owner-weekly-reminder.ics</loc>');
    expect(sitemap).toContain('/rankings/weekly.html</loc>');
    expect(sitemap).toContain('/categories/wigs-hair-pieces.html</loc>');
    expect(sitemap).toContain('/items/');
  });
});
