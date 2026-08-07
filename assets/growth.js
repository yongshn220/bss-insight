(() => {
  'use strict';

  const GOAL_ID = 'daily-visits-500';
  const EXPERIMENT_ID = 'hero-growth-cta-v1';
  const STORAGE_PREFIX = 'gns_growth';
  const EVENT_KEY = `${STORAGE_PREFIX}:events`;
  const VARIANT_KEY = `${STORAGE_PREFIX}:${EXPERIMENT_ID}:variant`;
  const ATTRIBUTION_KEY = `${STORAGE_PREFIX}:attribution`;
  const SESSION_KEY = `${STORAGE_PREFIX}:session_id`;
  const MAX_LOCAL_EVENTS = 80;
  const UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'];

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

  function getSessionId() {
    let sessionId = storageGet('sessionStorage', SESSION_KEY) || storageGet('localStorage', SESSION_KEY);
    if (!sessionId) {
      sessionId = `gns_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
    }
    storageSet('sessionStorage', SESSION_KEY, sessionId);
    storageSet('localStorage', SESSION_KEY, sessionId);
    return sessionId;
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

  function track(eventName, payload = {}) {
    const attribution = getAttribution();
    const event = {
      event: eventName,
      ts: safeNow(),
      goal_id: GOAL_ID,
      experiment_id: EXPERIMENT_ID,
      variant: window.__GNS_GROWTH__?.variant || 'unknown',
      session_id: getSessionId(),
      path: window.location.pathname,
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
    const script = document.createElement('script');
    script.defer = true;
    script.src = '/_vercel/insights/script.js';
    script.setAttribute('data-gns-vercel-analytics', 'true');
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
    const sectionId = section?.getAttribute('data-growth-section') || '';
    const componentExperimentId = experiment?.getAttribute('data-growth-experiment') || sectionId;
    return {
      section: sectionId,
      component_experiment_id: componentExperimentId,
      section_position: sectionPosition(section),
      item_id: item?.getAttribute('data-item-id') || '',
      item_rank: item?.getAttribute('data-item-rank') || '',
      item_category: item?.getAttribute('data-item-category') || '',
    };
  }

  function labelForClick(target) {
    const context = elementContext(target);
    const share = target.closest('[data-growth-share]');
    if (share) {
      const href = share.getAttribute('href') || share.getAttribute('data-copy-url') || '';
      const text = trimText(share.textContent || share.getAttribute('aria-label') || href);
      const shareAction = share.getAttribute('data-growth-share') || 'unknown';
      return { type: `share_${shareAction}`, share_action: shareAction, href, text, ...context };
    }

    const link = target.closest('a');
    if (!link) return null;
    const href = link.getAttribute('href') || '';
    const text = trimText(link.textContent || link.getAttribute('aria-label') || href);
    const label = { href, text, ...context };
    if (link.matches('[data-growth-cta]')) return { type: `cta_${link.dataset.growthCta}`, ...label };
    if (link.matches('.rank-hit')) return { type: 'item_card', ...label, item: trimText(link.getAttribute('aria-label')) };
    if (link.matches('.podium-card')) return { type: 'podium_card', ...label };
    if (link.matches('.cat-chip')) return { type: 'category_filter', ...label };
    if (link.matches('.tabs a')) return { type: 'timeframe_tab', ...label };
    if (link.matches('.source-card')) return { type: 'source_link', ...label, outbound: true };
    return { type: 'link', ...label };
  }

  function installClickTracking() {
    document.addEventListener('click', (event) => {
      const label = labelForClick(event.target);
      if (!label) return;
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
      const context = elementContext(button);
      const copied = await safeWriteClipboard(url);
      button.setAttribute('data-copy-state', copied ? 'copied' : 'manual-copy');
      button.textContent = copied ? 'Copied' : 'Link ready';
      track('growth_share_copy_result', {
        type: 'share_copy_result',
        share_action: button.getAttribute('data-growth-share') || 'unknown',
        href: url,
        copied,
        ...context,
      });
    });
  }

  function init() {
    const variant = getVariant();
    const sessionId = getSessionId();
    const attribution = getAttribution();
    window.__GNS_GROWTH__ = {
      goalId: GOAL_ID,
      targetAverageDailyVisits: 500,
      experimentId: EXPERIMENT_ID,
      variant,
      sessionId,
      attribution: () => getAttribution(),
      initialAttribution: attribution,
      events: localEvents,
      growthSections,
      track,
    };
    loadVercelAnalyticsIfHosted();
    applyExperiment(variant);
    installClickTracking();
    installCopyButtons();
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
