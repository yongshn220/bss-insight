(() => {
  'use strict';

  const GOAL_ID = 'daily-visits-500';
  const EXPERIMENT_ID = 'hero-growth-cta-v1';
  const STORAGE_PREFIX = 'gns_growth';
  const EVENT_KEY = `${STORAGE_PREFIX}:events`;
  const VARIANT_KEY = `${STORAGE_PREFIX}:${EXPERIMENT_ID}:variant`;
  const MAX_LOCAL_EVENTS = 80;

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
    const event = {
      event: eventName,
      ts: safeNow(),
      goal_id: GOAL_ID,
      experiment_id: EXPERIMENT_ID,
      variant: window.__GNS_GROWTH__?.variant || 'unknown',
      path: window.location.pathname,
      referrer: document.referrer || '',
      utm_source: new URLSearchParams(window.location.search).get('utm_source') || '',
      utm_medium: new URLSearchParams(window.location.search).get('utm_medium') || '',
      utm_campaign: new URLSearchParams(window.location.search).get('utm_campaign') || '',
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

  function labelForClick(target) {
    const link = target.closest('a');
    if (!link) return null;
    const href = link.getAttribute('href') || '';
    const text = trimText(link.textContent || link.getAttribute('aria-label') || href);
    const label = { href, text };
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

  function init() {
    const variant = getVariant();
    window.__GNS_GROWTH__ = {
      goalId: GOAL_ID,
      targetAverageDailyVisits: 500,
      experimentId: EXPERIMENT_ID,
      variant,
      events: localEvents,
      track,
    };
    loadVercelAnalyticsIfHosted();
    applyExperiment(variant);
    installClickTracking();
    track('growth_exposure', {
      title: trimText(document.title),
      page_type: document.body.dataset.pageType || 'unknown',
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
