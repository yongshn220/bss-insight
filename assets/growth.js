(() => {
  'use strict';

  const GOAL_ID = 'daily-visits-500';
  const EXPERIMENT_ID = 'hero-growth-cta-v1';
  const RETURN_VISITOR_EXPERIMENT_ID = 'return-visitor-prompt-v1';
  const STORAGE_PREFIX = 'gns_growth';
  const EVENT_KEY = `${STORAGE_PREFIX}:events`;
  const VARIANT_KEY = `${STORAGE_PREFIX}:${EXPERIMENT_ID}:variant`;
  const ATTRIBUTION_KEY = `${STORAGE_PREFIX}:attribution`;
  const SESSION_KEY = `${STORAGE_PREFIX}:session_id`;
  const SESSION_FALLBACK_KEY = `${STORAGE_PREFIX}:session_fallback`;
  const VISITOR_KEY = `${STORAGE_PREFIX}:visitor`;
  const MAX_LOCAL_EVENTS = 80;
  const VISIT_WINDOW_MS = 30 * 60 * 1000;
  const UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'];
  const pageStartedAt = Date.now();
  const viewedSections = new Set();
  const engagementCounters = {
    click_count: 0,
    share_click_count: 0,
    copy_result_count: 0,
    source_click_count: 0,
    item_card_click_count: 0,
  };
  let maxScrollDepthPercent = 0;
  let scrollTicking = false;
  let engagementSummarySent = false;
  let visitorContextCache = null;

  function safeNow() {
    return new Date().toISOString();
  }

  function getVariant() {
    const params = new URLSearchParams(window.location.search);
    const forced = params.get('variant') || params.get('ab');
    if (forced && /^b/i.test(forced)) return 'B_retail_action_first';
    if (forced && /^a/i.test(forced)) return 'A_evidence_first';

    try {
      const stored = window.localStorage.getItem(VARIANT_KEY);
      if (stored) return stored;
      const variant = Math.random() < 0.5 ? 'A_evidence_first' : 'B_retail_action_first';
      window.localStorage.setItem(VARIANT_KEY, variant);
      return variant;
    } catch (_error) {
      return 'A_evidence_first';
    }
  }

  function trimText(value, max = 96) {
    return String(value || '').replace(/\s+/g, ' ').trim().slice(0, max);
  }

  function pageTimeframe() {
    const path = window.location.pathname;
    const match = path.match(/\/rankings\/(weekly|monthly|quarterly|yearly)\.html$/i);
    if (match) return match[1].toLowerCase();
    if (/\/categories\/[^/]+\.html$/i.test(path)) return 'weekly_category';
    if (/\/(index\.html)?$/i.test(path)) return 'weekly_home';
    return '';
  }

  function pageCategoryId() {
    const path = window.location.pathname;
    const match = path.match(/\/categories\/([^/]+)\.html$/i);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function pageItemId() {
    const path = window.location.pathname;
    const match = path.match(/\/items\/([^/]+)\.html$/i);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function scrollDepthPercent() {
    const doc = document.documentElement;
    const body = document.body;
    const totalHeight = Math.max(
      doc?.scrollHeight || 0,
      body?.scrollHeight || 0,
      window.innerHeight || 0,
      1,
    );
    const scrollTop = window.scrollY || doc?.scrollTop || body?.scrollTop || 0;
    const viewedBottom = Math.min(totalHeight, scrollTop + (window.innerHeight || 0));
    return Math.max(0, Math.min(100, Math.round((viewedBottom / totalHeight) * 100)));
  }

  function updateScrollDepth() {
    maxScrollDepthPercent = Math.max(maxScrollDepthPercent, scrollDepthPercent());
    return maxScrollDepthPercent;
  }

  function storageGet(area, key) {
    try {
      return window[area]?.getItem(key) || '';
    } catch (_error) {
      return '';
    }
  }

  function storageSet(area, key, value) {
    try {
      window[area]?.setItem(key, value);
    } catch (_error) {
      // Tracking storage should never block the dashboard.
    }
  }

  function parseStoredJson(key, fallback) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (_error) {
      return fallback;
    }
  }

  function storedVisitWindowExpired() {
    const stored = parseStoredJson(VISITOR_KEY, {});
    const lastVisitMs = parseTimestamp(stored.last_visit_at);
    return Boolean(lastVisitMs && (Date.now() - lastVisitMs) > VISIT_WINDOW_MS);
  }

  function getSessionId() {
    const visitWindowExpired = storedVisitWindowExpired();
    let sessionId = visitWindowExpired ? '' : storageGet('sessionStorage', SESSION_KEY);
    if (!sessionId) {
      const fallback = parseStoredJson(SESSION_FALLBACK_KEY, {});
      const fallbackCreatedAt = parseTimestamp(fallback.created_at);
      const fallbackAgeMs = fallbackCreatedAt ? Date.now() - fallbackCreatedAt : Number.POSITIVE_INFINITY;
      if (!visitWindowExpired && fallback.session_id && fallbackAgeMs >= 0 && fallbackAgeMs <= VISIT_WINDOW_MS) {
        sessionId = fallback.session_id;
      }
    }
    if (!sessionId) {
      sessionId = `gns_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
    }
    storageSet('sessionStorage', SESSION_KEY, sessionId);
    storageSet('localStorage', SESSION_FALLBACK_KEY, JSON.stringify({ session_id: sessionId, created_at: safeNow() }));
    return sessionId;
  }

  function parseTimestamp(value) {
    const parsed = Date.parse(String(value || ''));
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function safeInteger(value, fallback = 0) {
    const parsed = Number.parseInt(String(value ?? ''), 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
  }

  function getVisitorContext() {
    if (visitorContextCache) return visitorContextCache;

    const now = safeNow();
    const nowMs = Date.now();
    const stored = parseStoredJson(VISITOR_KEY, {});
    const visitorId = stored.visitor_id || `gns_v_${nowMs.toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
    const firstSeenAt = stored.first_seen_at || now;
    const lastVisitAt = stored.last_visit_at || '';
    const lastVisitMs = parseTimestamp(lastVisitAt);
    const previousVisitCount = safeInteger(stored.visit_count, 0);
    const isNewVisit = !lastVisitMs || (nowMs - lastVisitMs) > VISIT_WINDOW_MS;
    const visitCount = previousVisitCount + (isNewVisit ? 1 : 0);
    const firstSeenMs = parseTimestamp(firstSeenAt) || nowMs;
    const daysSinceFirstSeen = Math.max(0, Math.floor((nowMs - firstSeenMs) / 86400000));

    visitorContextCache = {
      visitor_id: visitorId,
      first_seen_at: firstSeenAt,
      last_seen_at: now,
      last_visit_at: isNewVisit ? now : (lastVisitAt || now),
      visit_count: visitCount,
      is_returning_visitor: visitCount > 1,
      days_since_first_seen: daysSinceFirstSeen,
      visit_window_minutes: Math.round(VISIT_WINDOW_MS / 60000),
    };
    storageSet('localStorage', VISITOR_KEY, JSON.stringify(visitorContextCache));
    return visitorContextCache;
  }

  function currentUtm() {
    const params = new URLSearchParams(window.location.search);
    return UTM_KEYS.reduce((memo, key) => {
      memo[key] = params.get(key) || '';
      return memo;
    }, {});
  }

  function hasAnyUtm(utm) {
    return UTM_KEYS.some((key) => Boolean(utm[key]));
  }

  function attributionRecord(utm, path, referrer, ts) {
    const record = {
      landing_path: path,
      referrer: referrer || '',
      captured_at: ts,
    };
    UTM_KEYS.forEach((key) => {
      record[key] = utm[key] || '';
    });
    return record;
  }

  function getAttribution() {
    const now = safeNow();
    const path = window.location.pathname;
    const utm = currentUtm();
    const hasUtm = hasAnyUtm(utm);
    const stored = parseStoredJson(ATTRIBUTION_KEY, {});
    const first = stored.first || attributionRecord(utm, path, document.referrer, now);
    const current = hasUtm ? attributionRecord(utm, path, document.referrer, now) : (stored.current || first);
    const attribution = {
      first,
      current,
      landing_path: stored.landing_path || first.landing_path || path,
      last_path: path,
      updated_at: now,
    };
    storageSet('localStorage', ATTRIBUTION_KEY, JSON.stringify(attribution));
    return attribution;
  }

  function attributionUtm(attribution, key) {
    const params = new URLSearchParams(window.location.search);
    return params.get(key) || attribution.current?.[key] || '';
  }

  function localEvents() {
    try {
      const raw = window.localStorage.getItem(EVENT_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
      return [];
    }
  }

  function persistLocalEvent(event) {
    try {
      const events = localEvents();
      events.push(event);
      window.localStorage.setItem(EVENT_KEY, JSON.stringify(events.slice(-MAX_LOCAL_EVENTS)));
    } catch (_error) {
      // Browsers can block storage. Tracking should never break UX.
    }
  }

  function providerTrack(eventName, payload) {
    try {
      if (typeof window.va === 'function') {
        window.va('event', { name: eventName, data: payload });
      }
    } catch (_error) {}

    try {
      if (typeof window.plausible === 'function') {
        window.plausible(eventName, { props: payload });
      }
    } catch (_error) {}

    try {
      if (typeof window.gtag === 'function') {
        window.gtag('event', eventName, payload);
      }
    } catch (_error) {}
  }

  function analyticsBridgePayload(status = 'client_bridge_ready') {
    const scriptPath = window.__GNS_VERCEL_ANALYTICS_PATH || '/_vercel/insights/script.js';
    return {
      type: 'analytics_provider_health',
      provider: 'analytics_bridge',
      status,
      vercel_queue_ready: typeof window.va === 'function',
      vercel_script_path: scriptPath,
      vercel_script_present: Boolean(document.querySelector('script[data-gns-vercel-analytics]')),
      ga4_ready: typeof window.gtag === 'function',
      plausible_ready: typeof window.plausible === 'function',
    };
  }

  function trackAnalyticsBridgeStatus(status = 'client_bridge_ready') {
    track('growth_provider_ready', analyticsBridgePayload(status));
  }

  function track(eventName, payload = {}) {
    const attribution = getAttribution();
    const visitor = getVisitorContext();
    const event = {
      event: eventName,
      ts: safeNow(),
      goal_id: GOAL_ID,
      experiment_id: EXPERIMENT_ID,
      variant: window.__GNS_GROWTH__?.variant || 'unknown',
      session_id: getSessionId(),
      visitor_id: visitor.visitor_id,
      visit_count: visitor.visit_count,
      is_returning_visitor: visitor.is_returning_visitor,
      visitor_first_seen_at: visitor.first_seen_at,
      days_since_first_seen: visitor.days_since_first_seen,
      path: window.location.pathname,
      page_type: document.body?.dataset.pageType || 'unknown',
      timeframe: pageTimeframe(),
      page_category_id: pageCategoryId(),
      page_item_id: pageItemId(),
      referrer: document.referrer || '',
      landing_path: attribution.landing_path || '',
      first_referrer: attribution.first?.referrer || '',
      first_utm_source: attribution.first?.utm_source || '',
      first_utm_medium: attribution.first?.utm_medium || '',
      first_utm_campaign: attribution.first?.utm_campaign || '',
      current_utm_source: attribution.current?.utm_source || '',
      current_utm_medium: attribution.current?.utm_medium || '',
      current_utm_campaign: attribution.current?.utm_campaign || '',
      utm_source: attributionUtm(attribution, 'utm_source'),
      utm_medium: attributionUtm(attribution, 'utm_medium'),
      utm_campaign: attributionUtm(attribution, 'utm_campaign'),
      utm_content: attributionUtm(attribution, 'utm_content'),
      utm_term: attributionUtm(attribution, 'utm_term'),
      ...payload,
    };
    persistLocalEvent(event);
    providerTrack(eventName, event);
  }

  function loadVercelAnalyticsIfHosted() {
    if (!/\.vercel\.app$/i.test(window.location.hostname) && window.location.hostname !== 'gnsresearchhub.vercel.app') {
      return;
    }
    if (document.querySelector('script[data-gns-vercel-analytics]')) return;
    if (typeof window.va !== 'function') {
      window.va = function () {
        (window.vaq = window.vaq || []).push(arguments);
      };
    }
    const scriptPath = window.__GNS_VERCEL_ANALYTICS_PATH || '/_vercel/insights/script.js';
    const script = document.createElement('script');
    script.defer = true;
    script.src = scriptPath;
    script.setAttribute('data-gns-vercel-analytics', 'true');
    script.addEventListener('load', () => trackAnalyticsBridgeStatus('vercel_script_loaded'), { once: true });
    script.addEventListener('error', () => trackAnalyticsBridgeStatus('vercel_script_error'), { once: true });
    document.head.appendChild(script);
  }

  function applyExperiment(variant) {
    document.documentElement.dataset.growthGoal = GOAL_ID;
    document.body.dataset.experimentId = EXPERIMENT_ID;
    document.body.dataset.experimentVariant = variant;

    if (variant !== 'B_retail_action_first') return;

    const heroTitle = document.querySelector('[data-growth-hero-title]');
    const heroLead = document.querySelector('[data-growth-hero-lead]');
    const primaryCta = document.querySelector('[data-growth-cta="primary"]');
    const secondaryCta = document.querySelector('[data-growth-cta="secondary"]');

    if (heroTitle) heroTitle.textContent = '이번 주 BSS 매장에서 바로 테스트할 제품 순위';
    if (heroLead) {
      heroLead.textContent = '바쁜 Beauty Supply Store owner가 이번 주 무엇을 전면 진열하고, 어떤 add-on item을 테스트할지 빠르게 고르도록 만든 ranking입니다. Trend evidence와 supply URL은 분리해서 표시합니다.';
    }
    if (primaryCta) primaryCta.textContent = '이번 주 팔아볼 제품 보기';
    if (secondaryCta) secondaryCta.textContent = '근거와 watchlist 확인';
  }

  function applyReturnVisitorPrompt(visitor) {
    if (!visitor?.is_returning_visitor) return;
    const panel = document.querySelector('[data-return-visitor-panel]');
    if (!panel) return;

    const visitCount = safeInteger(visitor.visit_count, 1);
    const daysSinceFirstSeen = safeInteger(visitor.days_since_first_seen, 0);
    const title = panel.querySelector('[data-return-visitor-title]');
    const copy = panel.querySelector('[data-return-visitor-copy]');
    if (title) title.textContent = `Visit #${visitCount}: 바뀐 ranking과 WATCHLIST부터 확인하세요`;
    if (copy) {
      const dayText = daysSinceFirstSeen > 0 ? `${daysSinceFirstSeen}일 전 첫 방문 이후 ` : '';
      copy.textContent = `${dayText}Top 3, evidence gap, owner-ready display tip을 먼저 확인하고 공유할 item을 고르세요. Repeat visit 여부는 익명 event로만 측정합니다.`;
    }

    panel.hidden = false;
    panel.removeAttribute('aria-hidden');
    panel.setAttribute('data-growth-section', RETURN_VISITOR_EXPERIMENT_ID);
    panel.setAttribute('data-growth-experiment', RETURN_VISITOR_EXPERIMENT_ID);
    panel.setAttribute('data-visit-count', String(visitCount));
    panel.setAttribute('data-days-since-first-seen', String(daysSinceFirstSeen));
    track('growth_return_visit_prompt', {
      type: 'return_visitor_prompt',
      section: RETURN_VISITOR_EXPERIMENT_ID,
      component_experiment_id: RETURN_VISITOR_EXPERIMENT_ID,
      visit_count: visitCount,
      days_since_first_seen: daysSinceFirstSeen,
    });
  }

  function growthSections() {
    return Array.from(document.querySelectorAll('[data-growth-section]'))
      .map((section, index) => ({
        id: section.getAttribute('data-growth-section') || '',
        position: index + 1,
      }))
      .filter((section) => section.id);
  }

  function sectionPosition(section) {
    if (!section) return '';
    const sections = Array.from(document.querySelectorAll('[data-growth-section]'));
    const index = sections.indexOf(section);
    return index >= 0 ? String(index + 1) : '';
  }

  function elementContext(target) {
    const section = target.closest?.('[data-growth-section]');
    const experiment = target.closest?.('[data-growth-experiment]');
    const item = target.closest?.('[data-item-id]');
    const category = target.closest?.('[data-category-id]');
    const source = target.closest?.('[data-growth-source-layer]');
    const sectionId = section?.getAttribute('data-growth-section') || '';
    const componentExperimentId = experiment?.getAttribute('data-growth-experiment') || sectionId;
    return {
      section: sectionId,
      component_experiment_id: componentExperimentId,
      section_position: sectionPosition(section),
      item_id: item?.getAttribute('data-item-id') || '',
      item_rank: item?.getAttribute('data-item-rank') || '',
      item_category: item?.getAttribute('data-item-category') || '',
      category_id: category?.getAttribute('data-category-id') || pageCategoryId(),
      source_layer: source?.getAttribute('data-growth-source-layer') || '',
      source_kind: source?.getAttribute('data-growth-source-kind') || '',
      source_type: source?.getAttribute('data-growth-source-type') || '',
      source_status: source?.getAttribute('data-growth-source-status') || '',
      source_date_kind: source?.getAttribute('data-growth-source-date-kind') || '',
      source_domain: source?.getAttribute('data-growth-source-domain') || '',
      source_discovery_kind: source?.getAttribute('data-growth-source-discovery-kind') || '',
    };
  }

  function sectionViewPayload(section) {
    const context = elementContext(section);
    const heading = section.querySelector('h1, h2, h3');
    const itemCount = section.querySelectorAll('[data-item-id]').length;
    return {
      type: 'section_view',
      ...context,
      heading: trimText(heading?.textContent || section.getAttribute('aria-label') || context.section, 120),
      item_count: itemCount,
    };
  }

  function installSectionViewTracking() {
    const sections = Array.from(document.querySelectorAll('[data-growth-section]'));
    if (!sections.length) return;
    const seen = new Set();

    function markViewed(section) {
      const sectionId = section.getAttribute('data-growth-section') || '';
      if (!sectionId || seen.has(sectionId)) return;
      seen.add(sectionId);
      viewedSections.add(sectionId);
      track('growth_section_view', sectionViewPayload(section));
    }

    if (typeof window.IntersectionObserver !== 'function') {
      sections.forEach(markViewed);
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting || entry.intersectionRatio < 0.35) return;
        markViewed(entry.target);
        observer.unobserve(entry.target);
      });
    }, { threshold: [0.35, 0.6] });

    sections.forEach((section) => observer.observe(section));
  }

  function parseTrackingUrl(value) {
    const text = String(value || '').trim();
    if (!text) return null;
    try {
      const base = `${window.location.origin}${window.location.pathname}`;
      return new URL(text, base);
    } catch (_error) {
      return null;
    }
  }

  function embeddedShareDestination(clickedUrl) {
    if (!clickedUrl) return null;
    const embeddedUrl = clickedUrl.searchParams?.get('url') || clickedUrl.searchParams?.get('u') || '';
    if (embeddedUrl) return parseTrackingUrl(embeddedUrl);
    const textBody = clickedUrl.searchParams?.get('body') || clickedUrl.searchParams?.get('text') || '';
    if (clickedUrl.protocol === 'mailto:' || clickedUrl.protocol === 'sms:' || /wa\.me|whatsapp\.com|t\.me/i.test(clickedUrl.hostname || '')) {
      const match = textBody.match(/https?:\/\/[^\s<>"')]+/i);
      if (match) return parseTrackingUrl(match[0].replace(/[.,;]+$/, ''));
    }
    return clickedUrl;
  }

  function linkDestinationPayload(href) {
    const clickedUrl = parseTrackingUrl(href);
    if (!clickedUrl) {
      return {
        link_has_utm: false,
        link_is_external: false,
      };
    }
    const destinationUrl = embeddedShareDestination(clickedUrl) || clickedUrl;
    const clickedOrigin = clickedUrl.origin === 'null' ? clickedUrl.protocol.replace(':', '') : clickedUrl.origin;
    const destinationOrigin = destinationUrl.origin === 'null' ? destinationUrl.protocol.replace(':', '') : destinationUrl.origin;
    const payload = {
      link_protocol: clickedUrl.protocol.replace(':', ''),
      link_origin: clickedOrigin,
      link_path: clickedUrl.pathname || '',
      link_is_external: clickedUrl.origin !== window.location.origin,
      destination_origin: destinationOrigin,
      destination_path: destinationUrl.pathname || '',
    };
    let hasUtm = false;
    UTM_KEYS.forEach((key) => {
      const value = destinationUrl.searchParams?.get(key) || clickedUrl.searchParams?.get(key) || '';
      payload[`link_${key}`] = value;
      if (value) hasUtm = true;
    });
    payload.link_has_utm = hasUtm;
    return payload;
  }

  function labelForClick(target) {
    const context = elementContext(target);
    const share = target.closest('[data-growth-share]');
    if (share) {
      const href = share.getAttribute('href') || share.getAttribute('data-copy-url') || '';
      const text = trimText(share.textContent || share.getAttribute('aria-label') || href);
      const shareAction = share.getAttribute('data-growth-share') || 'unknown';
      return { type: `share_${shareAction}`, share_action: shareAction, href, text, ...linkDestinationPayload(href), ...context };
    }

    const link = target.closest('a');
    if (!link) return null;
    const href = link.getAttribute('href') || '';
    const text = trimText(link.textContent || link.getAttribute('aria-label') || href);
    const label = { href, text, ...linkDestinationPayload(href), ...context };
    if (link.matches('[data-growth-cta]')) return { type: `cta_${link.dataset.growthCta}`, ...label };
    if (link.matches('.rank-hit')) return { type: 'item_card', ...label, item: trimText(link.getAttribute('aria-label')) };
    if (link.matches('.podium-card')) return { type: 'podium_card', ...label };
    if (link.matches('.cat-chip')) return { type: 'category_filter', ...label };
    if (link.matches('.tabs a')) return { type: 'timeframe_tab', ...label };
    if (link.matches('.source-card')) return { type: 'source_link', ...label, outbound: true };
    return { type: 'link', ...label };
  }

  function recordClickMetrics(label) {
    if (!label) return;
    engagementCounters.click_count += 1;
    if (String(label.type || '').startsWith('share_')) engagementCounters.share_click_count += 1;
    if (label.type === 'source_link') engagementCounters.source_click_count += 1;
    if (label.type === 'item_card' || label.type === 'podium_card') engagementCounters.item_card_click_count += 1;
  }

  function installClickTracking() {
    document.addEventListener('click', (event) => {
      const label = labelForClick(event.target);
      if (!label) return;
      recordClickMetrics(label);
      track('growth_click', label);
    }, { capture: true });
  }

  async function safeWriteClipboard(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (_error) {}
    return false;
  }

  function installCopyButtons() {
    document.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-copy-url]');
      if (!button) return;
      event.preventDefault();
      const url = button.getAttribute('data-copy-url') || '';
      const copyText = button.getAttribute('data-copy-text') || url;
      const context = elementContext(button);
      const copied = await safeWriteClipboard(copyText);
      const fallbackLabel = button.hasAttribute('data-copy-text') ? 'Text ready' : 'Link ready';
      button.setAttribute('data-copy-state', copied ? 'copied' : 'manual-copy');
      button.textContent = copied ? 'Copied' : fallbackLabel;
      engagementCounters.copy_result_count += 1;
      track('growth_share_copy_result', {
        type: 'share_copy_result',
        share_action: button.getAttribute('data-growth-share') || 'unknown',
        href: url,
        copied,
        copy_mode: button.hasAttribute('data-copy-text') ? 'brief_text' : 'url',
        copy_text_length: copyText.length,
        ...linkDestinationPayload(url),
        ...context,
      });
    });
  }

  function engagementSnapshot(reason = 'snapshot') {
    updateScrollDepth();
    const sections = Array.from(viewedSections);
    return {
      type: 'engagement_summary',
      reason,
      page_type: document.body?.dataset.pageType || 'unknown',
      timeframe: pageTimeframe(),
      category_id: pageCategoryId(),
      item_id: pageItemId(),
      time_on_page_ms: Math.max(0, Date.now() - pageStartedAt),
      max_scroll_depth_percent: maxScrollDepthPercent,
      viewed_section_count: sections.length,
      viewed_sections: sections.join(','),
      ...engagementCounters,
    };
  }

  function sendEngagementSummary(reason = 'pagehide') {
    if (engagementSummarySent) return engagementSnapshot(`${reason}_already_sent`);
    engagementSummarySent = true;
    const summary = engagementSnapshot(reason);
    track('growth_engagement_summary', summary);
    return summary;
  }

  function installEngagementSummaryTracking() {
    updateScrollDepth();
    window.addEventListener('scroll', () => {
      if (scrollTicking) return;
      scrollTicking = true;
      window.requestAnimationFrame(() => {
        updateScrollDepth();
        scrollTicking = false;
      });
    }, { passive: true });
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') sendEngagementSummary('visibility_hidden');
    });
    window.addEventListener('pagehide', () => sendEngagementSummary('pagehide'));
  }

  function init() {
    const variant = getVariant();
    const sessionId = getSessionId();
    const visitor = getVisitorContext();
    const attribution = getAttribution();
    window.__GNS_GROWTH__ = {
      goalId: GOAL_ID,
      targetAverageDailyVisits: 500,
      experimentId: EXPERIMENT_ID,
      variant,
      sessionId,
      visitorId: visitor.visitor_id,
      visitor: () => getVisitorContext(),
      attribution: () => getAttribution(),
      initialAttribution: attribution,
      pageCategoryId,
      events: localEvents,
      growthSections,
      engagementSnapshot,
      flushEngagementSummary: sendEngagementSummary,
      analyticsBridgeStatus: () => analyticsBridgePayload('snapshot'),
      track,
    };
    loadVercelAnalyticsIfHosted();
    applyExperiment(variant);
    applyReturnVisitorPrompt(visitor);
    installClickTracking();
    installCopyButtons();
    installSectionViewTracking();
    installEngagementSummaryTracking();
    trackAnalyticsBridgeStatus('client_bridge_ready');
    const sections = growthSections();
    track('growth_exposure', {
      title: trimText(document.title),
      page_type: document.body.dataset.pageType || 'unknown',
      visible_growth_sections: sections.map((section) => section.id).join(','),
      visible_growth_section_count: sections.length,
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
