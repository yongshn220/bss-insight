#!/usr/bin/env python3
"""Build a clean store-style item ranking dashboard for BSS trend intelligence."""
from __future__ import annotations

import datetime as dt
import email.utils
import html
import json
import shutil
import urllib.parse
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RANKINGS_PATH = DATA_DIR / "rankings.json"
NEXT_LOOP_FOCUS_PATH = DATA_DIR / "next_loop_focus.json"
RANKING_HISTORY_PATH = DATA_DIR / "ranking_history.json"
RANKINGS_DIR = ROOT / "rankings"
ITEMS_DIR = ROOT / "items"
CATEGORIES_DIR = ROOT / "categories"
ROBOTS_PATH = ROOT / "robots.txt"
SITEMAP_PATH = ROOT / "sitemap.xml"
FEED_PATH = ROOT / "feed.xml"
MANIFEST_PATH = ROOT / "manifest.webmanifest"

TIMEFRAME_ORDER = ["weekly", "monthly", "quarterly", "yearly"]
TIMEFRAME_LABELS = {"weekly": "Weekly", "monthly": "Monthly", "quarterly": "Quarterly", "yearly": "Yearly"}
TIMEFRAME_DAYS = {"weekly": 14, "monthly": 45, "quarterly": 120, "yearly": 365}
SITE_BASE = "https://gnsresearchhub.vercel.app"
GA4_MEASUREMENT_ID = "G-SW7HBY6WRE"

STORE_ZONE_LABELS = {
    "wigs-hair-pieces": "Wig wall",
    "braiding-crochet-hair": "Braid aisle",
    "hair-care-styling": "Hair care / install shelf",
    "lashes-brows": "Lash front-end",
    "nails": "Nail impulse tray",
    "makeup-cosmetics": "Lip / eye cosmetics bay",
    "tools-accessories": "Install tools clip strip",
    "jewelry-fashion-accessories": "Checkout jewelry wall",
}


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def absolute_url(path_or_url: object) -> str:
    """Return an absolute URL suitable for canonical/OG/JSON-LD metadata."""
    value = str(path_or_url or "").strip()
    if not value:
        return f"{SITE_BASE}/index.html"
    if value.startswith(("http://", "https://")):
        return value
    if not value.startswith("/"):
        value = "/" + value
    return f"{SITE_BASE}{value}"


def json_ld_script(payload: dict[str, Any] | list[dict[str, Any]] | None) -> str:
    """Serialize JSON-LD without allowing a literal closing script tag."""
    if not payload:
        return ""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'  <script type="application/ld+json">{text}</script>\n'


def generated_datetime(data: dict[str, Any]) -> dt.datetime:
    """Parse the current data timestamp for RSS/SEO metadata."""
    raw = str(data.get("generated_at") or data.get("date") or "").strip()
    if raw:
        try:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.UTC)
            return parsed.astimezone(dt.UTC)
        except ValueError:
            try:
                parsed_date = dt.date.fromisoformat(raw[:10])
                return dt.datetime.combine(parsed_date, dt.time.min, tzinfo=dt.UTC)
            except ValueError:
                pass
    return dt.datetime.now(dt.UTC)


def rss_datetime(value: dt.datetime) -> str:
    """Return an RFC 2822 timestamp accepted by RSS readers."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return email.utils.format_datetime(value.astimezone(dt.UTC), usegmt=True)


def analytics_head() -> str:
    """Return production analytics tags shared by every generated page.

    GA4 can be loaded directly, but Vercel Web Analytics is injected by
    ``assets/growth.js`` only on the production host. Defining the Vercel path
    and ``window.va`` queue in the head keeps the provider bridge ready before
    the deferred growth bundle sends the first exposure event, without forcing a
    local Playwright server to request ``/_vercel/insights/script.js``.
    """
    return f"""  <script async src=\"https://www.googletagmanager.com/gtag/js?id={GA4_MEASUREMENT_ID}\"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', '{GA4_MEASUREMENT_ID}');
    window.__GNS_VERCEL_ANALYTICS_PATH = '/_vercel/insights/script.js';
    window.va = window.va || function(){{(window.vaq = window.vaq || []).push(arguments);}};
  </script>
"""


def load_rankings() -> dict[str, Any]:
    if not RANKINGS_PATH.exists():
        return {"rankings": {}, "categories": [], "generated_at": ""}
    return json.loads(RANKINGS_PATH.read_text(encoding="utf-8"))


def load_next_loop_focus() -> dict[str, Any]:
    """Load sanitized focus candidates from the feedback loop for owner-visible trust UX."""
    if not NEXT_LOOP_FOCUS_PATH.exists():
        return {}
    try:
        loaded = json.loads(NEXT_LOOP_FOCUS_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def load_ranking_history() -> dict[str, Any]:
    """Load recent ranking snapshots so the page can say what actually changed."""
    if not RANKING_HISTORY_PATH.exists():
        return {"runs": []}
    try:
        loaded = json.loads(RANKING_HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"runs": []}
    return loaded if isinstance(loaded, dict) else {"runs": []}


def source_count(row: dict[str, Any], key: str) -> int:
    try:
        return int((row.get("source_counts") or {}).get(key) or 0)
    except Exception:
        return 0


def previous_history_rows(current_generated_at: object, timeframe: str) -> list[dict[str, Any]]:
    """Return the latest prior rows for the same timeframe, excluding the current snapshot."""
    history = load_ranking_history()
    runs = history.get("runs", []) if isinstance(history, dict) else []
    if not isinstance(runs, list):
        return []
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("generated_at") == current_generated_at:
            continue
        rankings = run.get("rankings", {}) if isinstance(run.get("rankings"), dict) else {}
        rows = rankings.get(timeframe, [])
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def coverage_snapshot(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Small metrics used by the owner-facing change snapshot."""
    return {
        "items": len(rows),
        "trend_items": sum(1 for row in rows if source_count(row, "trend_evidence") > 0),
        "watchlist_items": sum(
            1 for row in rows
            if row.get("momentum") == "watchlist" or source_count(row, "trend_evidence") == 0
        ),
        "retail_items": sum(1 for row in rows if source_count(row, "retail_product_evidence") > 0),
        "tiktok_items": sum(1 for row in rows if source_count(row, "tiktok_shop_product_evidence") > 0),
        "cached_tiktok_items": sum(1 for row in rows if source_count(row, "cached_tiktok_shop_product_evidence") > 0),
    }


def signed_delta(current: int, previous: int | None, inverse: bool = False) -> tuple[str, str]:
    """Return a compact delta string and CSS class. Inverse means lower is better."""
    if previous is None:
        return "baseline", "neutral"
    delta = current - previous
    if delta == 0:
        return "—", "neutral"
    improved = delta < 0 if inverse else delta > 0
    arrow = "▼" if delta < 0 else "▲"
    return f"{arrow} {abs(delta)}", "good" if improved else "watch"


def top3_change_summary(rows: list[dict[str, Any]], previous_rows: list[dict[str, Any]]) -> tuple[str, str]:
    current_top = [str(row.get("item_id") or "") for row in rows[:3]]
    previous_top = [str(row.get("item_id") or "") for row in previous_rows[:3]]
    current_names = ", ".join(
        f"#{row.get('rank')} {row.get('item_name')}" for row in rows[:3]
    )
    if not previous_rows:
        return "New baseline", current_names
    if current_top == previous_top:
        return "Top 3 unchanged", current_names
    previous_set = set(previous_top)
    entrants = [row.get("item_name") for row in rows[:3] if str(row.get("item_id") or "") not in previous_set]
    if entrants:
        return "Top 3 changed", "New Top 3 entrant(s): " + ", ".join(str(name) for name in entrants)
    return "Top 3 reordered", current_names


def return_visitor_panel(timeframe: str = "weekly") -> str:
    """Hidden repeat-visit prompt revealed by growth.js for returning owners.

    The dashboard's growth goal depends on repeat visits, but first-time visitors
    should not see a personalized message. growth.js reveals this panel only when
    anonymous local visitor context shows a later visit, then attaches the growth
    section metadata so exposure/click tracking stays accurate.
    """
    label = TIMEFRAME_LABELS.get(timeframe, timeframe.title())
    ranking_path = f"/rankings/{timeframe}.html"
    campaign = "daily-visits-500-return-visitor-prompt"
    primary_url = (
        f"{ranking_path}?utm_source=site&utm_medium=return_prompt"
        f"&utm_campaign={campaign}&utm_content=current-ranking&utm_term={timeframe}"
    )
    all_items_url = (
        f"{ranking_path}?utm_source=site&utm_medium=return_prompt"
        f"&utm_campaign={campaign}&utm_content=all-items&utm_term={timeframe}#all-items"
    )
    return f"""
      <section class="wrap return-visitor-panel" hidden data-return-visitor-panel aria-hidden="true">
        <div class="return-visitor-copy">
          <span>Return owner path</span>
          <h2 data-return-visitor-title>다시 오신 owner님, 바뀐 ranking부터 확인하세요</h2>
          <p data-return-visitor-copy>{esc(label)} page에서 Top 3, WATCHLIST, display test를 먼저 보고 이번 방문에서 바로 공유/저장할 item을 고르세요.</p>
        </div>
        <div class="return-visitor-actions">
          <a class="primary-action" data-growth-cta="return_visitor_current_ranking" href="{esc(primary_url)}">Current ranking 보기</a>
          <a class="secondary-action" data-growth-cta="return_visitor_all_items" href="{esc(all_items_url)}">All item 확인</a>
        </div>
      </section>"""


def run_change_snapshot(data: dict[str, Any], timeframe: str, rows: list[dict[str, Any]]) -> str:
    """Owner-facing answer to: why should I revisit this dashboard today?

    The panel reports measured changes only. Routine refreshes with no evidence or
    rank movement are labeled as no material movement instead of being framed as
    research improvement.
    """
    if not rows:
        return ""
    label = TIMEFRAME_LABELS.get(timeframe, timeframe.title())
    previous_rows = previous_history_rows(data.get("generated_at"), timeframe)
    current = coverage_snapshot(rows)
    previous = coverage_snapshot(previous_rows) if previous_rows else {}
    trend_delta, trend_delta_class = signed_delta(
        current["trend_items"], previous.get("trend_items") if previous else None
    )
    watch_delta, watch_delta_class = signed_delta(
        current["watchlist_items"], previous.get("watchlist_items") if previous else None, inverse=True
    )
    cached_delta, cached_delta_class = signed_delta(
        current["cached_tiktok_items"], previous.get("cached_tiktok_items") if previous else None, inverse=True
    )

    health = data.get("collection_health", {}) if isinstance(data.get("collection_health"), dict) else {}
    source_health = health.get("source_health", {}) if isinstance(health.get("source_health"), dict) else {}
    apify = source_health.get("apify_tiktok_shop", {}) if isinstance(source_health, dict) else {}
    apify = apify if isinstance(apify, dict) else {}
    fresh_urls = int(apify.get("fresh_evidence_urls") or 0)
    total_urls = int(apify.get("evidence_urls") or 0)
    status = str(apify.get("status") or "unknown")
    source_note = (
        f"TikTok Shop source health: {status} · fresh URLs {fresh_urls}/{total_urls}. "
        "Supply URLs are not trend evidence."
    )

    top3_status, top3_note = top3_change_summary(rows, previous_rows)
    material_notes = []
    if previous:
        if current["trend_items"] != previous.get("trend_items"):
            material_notes.append(f"trend-backed items {previous.get('trend_items')}→{current['trend_items']}")
        if current["watchlist_items"] != previous.get("watchlist_items"):
            material_notes.append(f"WATCHLIST items {previous.get('watchlist_items')}→{current['watchlist_items']}")
        if current["cached_tiktok_items"] != previous.get("cached_tiktok_items"):
            material_notes.append(f"cached TikTok fallback items {previous.get('cached_tiktok_items')}→{current['cached_tiktok_items']}")
        if top3_status != "Top 3 unchanged":
            material_notes.append(top3_status.lower())
    material_text = "; ".join(material_notes) if material_notes else "No material rank/evidence movement versus previous snapshot; measurement pending."

    generated_at = data.get("generated_at") or ""
    cards = [
        ("Trend-backed", f"{current['trend_items']}/{current['items']}", trend_delta, trend_delta_class, "Published/date-bearing URLs in this view"),
        ("WATCHLIST", str(current["watchlist_items"]), watch_delta, watch_delta_class, "Evidence insufficient; not trend claims"),
        ("Fresh TikTok Shop", str(fresh_urls), "source", "neutral", "Supply/social-commerce validation only"),
        ("Cached fallback", str(current["cached_tiktok_items"]), cached_delta, cached_delta_class, "Should stay low and labeled supply-only"),
    ]
    metric_cards = "".join(
        f"""
        <div class="run-change-card {esc(delta_class)}">
          <span>{esc(title)}</span>
          <strong>{esc(value)}</strong>
          <em>{esc(delta)}</em>
          <small>{esc(note)}</small>
        </div>"""
        for title, value, delta, delta_class, note in cards
    )
    return f"""
      <section class="wrap run-change" data-growth-section="run-change-snapshot-v1" data-growth-experiment="run-change-snapshot-v1" aria-label="Latest loop change snapshot">
        <div class="run-change-copy">
          <span>Latest loop change · {esc(label)}</span>
          <h2>오늘 다시 볼 이유</h2>
          <p>{esc(material_text)}</p>
          <small>{esc(source_note)} · Generated {esc(generated_at)}</small>
        </div>
        <div class="run-change-grid">{metric_cards}</div>
        <div class="run-change-top3">
          <span>{esc(top3_status)}</span>
          <strong>{esc(top3_note)}</strong>
          <a data-growth-cta="run_change_review" href="/data/operations_review_public.json">Review JSON</a>
        </div>
      </section>"""


def fmt_change(change: Any) -> str:
    if change is None:
        return "NEW"
    try:
        c = int(change)
    except Exception:
        return "—"
    if c > 0:
        return f"▲ {c}"
    if c < 0:
        return f"▼ {abs(c)}"
    return "—"


def momentum_label(row: dict[str, Any]) -> str:
    mapping = {
        "new": "NEW",
        "new_shift": "NEW SHIFT",
        "accelerating": "ACCELERATING",
        "rising": "RISING",
        "stable": "STABLE",
        "cooling": "COOLING",
        "falling": "FALLING",
        "watchlist": "WATCHLIST",
    }
    return mapping.get(row.get("momentum"), str(row.get("momentum") or "—").upper())


def nav(active: str = "weekly") -> str:
    return "".join(
        f'<a class="{esc("active" if tf == active else "")}" href="/rankings/{tf}.html">{TIMEFRAME_LABELS[tf]}</a>'
        for tf in TIMEFRAME_ORDER
    )


def shell(
    title: str,
    body: str,
    active: str = "weekly",
    page_type: str = "ranking",
    page_path: str = "/index.html",
    description: str | None = None,
    image_url: str | None = None,
    json_ld: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> str:
    description = description or (
        "BSS retail-owner product ranking with separated trend evidence, supply validation, "
        "watchlist links, and weekly growth experiments."
    )
    canonical_path = page_path
    canonical_url = absolute_url(canonical_path)
    og_image = absolute_url(image_url or "/assets/category-tools-accessories.svg")
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{esc(description)}">
  <meta name="gns:growth-goal" content="daily-visits-500">
  <meta name="gns:growth-target" content="500 average daily visits">
  <meta name="gns:growth-experiment" content="hero-growth-cta-v1">
  <link rel="canonical" href="{esc(canonical_url)}">
  <link rel="alternate" type="application/rss+xml" title="BSS Trend Ranking RSS" href="{SITE_BASE}/feed.xml">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/assets/app-icon.svg" type="image/svg+xml">
  <meta name="theme-color" content="#111827">
  <meta name="application-name" content="BSS Trend Ranking">
  <meta name="apple-mobile-web-app-title" content="BSS Trend Ranking">
  <meta property="og:title" content="{esc(title)} · BSS Trend Ranking">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{esc(canonical_url)}">
  <meta property="og:image" content="{esc(og_image)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(title)} · BSS Trend Ranking">
  <meta name="twitter:description" content="{esc(description)}">
  <meta name="twitter:image" content="{esc(og_image)}">
  <title>{esc(title)} · BSS Trend Ranking</title>
{analytics_head()}{json_ld_script(json_ld)}  <link rel="stylesheet" href="/assets/style.css">
  <script defer src="/assets/growth.js"></script>
</head>
<body data-page-type="{esc(page_type)}" data-growth-goal-id="daily-visits-500" data-experiment-id="hero-growth-cta-v1">
  <header class="topbar">
    <div class="wrap navline">
      <a class="brand" href="/index.html"><span class="brand-dot"></span>BSS Trend Ranking</a>
      <nav class="tabs">{nav(active)}</nav>
    </div>
  </header>
  {body}
  <footer class="footer wrap">
    <span>Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
    <span>Growth goal: 500 average daily visits · Published URLs drive trend movement · BSS/wholesale/TikTok Shop URLs validate supply · search links are watchlists only</span>
  </footer>
</body>
</html>"""


def score_bar(score: Any) -> str:
    try:
        width = max(4, min(100, float(score)))
    except Exception:
        width = 0
    return f'<div class="scorebar"><span style="width:{width:.0f}%"></span></div>'


def image_tag(row: dict[str, Any], class_name: str) -> str:
    url = row.get("image_url") or f"/assets/category-{row.get('category_id', 'tools-accessories')}.svg"
    alt = row.get("image_alt") or f"{row.get('item_name')} visual"
    status = row.get("image_status") or "category_visual"
    source = row.get("image_source") or "Category visual"
    return (
        f'<figure class="{esc(class_name)} {esc(status)}">'
        f'<img src="{esc(url)}" alt="{esc(alt)}" loading="lazy">'
        f'<figcaption>{esc(source)}</figcaption>'
        '</figure>'
    )


def evidence_chips(row: dict[str, Any]) -> str:
    counts = row.get("source_counts", {})
    chips = [
        ("Trend URLs", counts.get("trend_evidence", counts.get("news_magazine", 0))),
        ("14d", counts.get("recent_trend_evidence", counts.get("recent_evidence", 0))),
        ("Store URLs", counts.get("retail_product_evidence", 0)),
        ("TikTok Shop", counts.get("tiktok_shop_product_evidence", 0)),
    ]
    if counts.get("cached_tiktok_shop_product_evidence"):
        chips.append(("TikTok cache", counts.get("cached_tiktok_shop_product_evidence")))
    chips.extend([
        ("Domains", counts.get("unique_domains", 0)),
        ("BSS", f'{row.get("bss_fit")}/5'),
    ])
    if row.get("seasonal_now"):
        chips.append(("Season", "Now"))
    return "".join(f'<span class="chip"><b>{esc(label)}</b>{esc(value)}</span>' for label, value in chips)


def clamp_text(value: object, limit: int) -> str:
    """Keep ranking cards scannable while still showing owner-useful details."""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def owner_action_panel(row: dict[str, Any], compact: bool = False) -> str:
    """Show retail-owner display/risk/message on the card, not only detail pages."""
    limit = 88 if compact else 122
    notes = [
        ("Display", row.get("display_tip")),
        ("Risk", row.get("risk")),
        ("Owner phrase", row.get("owner_message_en")),
    ]
    return '<div class="owner-actions" aria-label="Retail owner action summary">' + "".join(
        f'<div class="owner-action-note"><b>{esc(label)}</b><span>{esc(clamp_text(value, limit))}</span></div>'
        for label, value in notes
        if value
    ) + '</div>'


def item_card(row: dict[str, Any], compact: bool = False) -> str:
    item_url = f"/items/{esc(row.get('item_id'))}.html"
    desc = row.get("reason_summary", "")
    evidence_class = "has-trend" if (row.get("source_counts", {}).get("trend_evidence") or row.get("source_counts", {}).get("news_magazine")) else "watchlist-only"
    if compact and len(desc) > 150:
        desc = desc[:147] + "…"
    return f"""
    <article class="rank-card {esc(evidence_class)}" data-item-id="{esc(row.get('item_id'))}" data-item-rank="{esc(row.get('rank'))}" data-item-category="{esc(row.get('category_id'))}">
      <a class="rank-hit" href="{item_url}" aria-label="View {esc(row.get('item_name'))}"></a>
      <div class="rank-num">#{esc(row.get('rank'))}</div>
      {image_tag(row, 'rank-img')}
      <div class="rank-main">
        <div class="card-topline">
          <span class="category-label">{esc(row.get('category_name'))}</span>
          <span class="move {esc(row.get('momentum'))}">{esc(momentum_label(row))} · {esc(fmt_change(row.get('rank_change')))}</span>
        </div>
        <h3>{esc(row.get('item_name'))}</h3>
        <p>{esc(desc)}</p>
        <p class="change-note">{esc(row.get('change_note'))}</p>
        {owner_action_panel(row, compact=compact)}
        <div class="chips">{evidence_chips(row)}</div>
      </div>
      <div class="score-box">
        <span>Score</span>
        <strong>{esc(row.get('score'))}</strong>
        {score_bar(row.get('score'))}
      </div>
    </article>"""


def category_chips(categories: list[dict[str, Any]], base_path: str = "") -> str:
    prefix = esc(base_path)
    chips = [f'<a href="{prefix}#all" class="cat-chip active">All</a>']
    for cat in categories:
        chips.append(f'<a href="{prefix}#{esc(cat.get("id"))}" class="cat-chip">{esc(cat.get("name"))}</a>')
    return '<nav class="category-strip">' + ''.join(chips) + '</nav>'


def growth_campaign_path(path: str, *, source: str, medium: str, campaign: str, **extra: object) -> str:
    """Return a same-origin UTM path for internal growth links."""
    params = {
        "utm_source": source,
        "utm_medium": medium,
        "utm_campaign": campaign,
    }
    for key, value in extra.items():
        if value not in (None, ""):
            params[key] = str(value)
    return f"{path}?{urllib.parse.urlencode(params)}"


def rows_for_category(rows: list[dict[str, Any]], category_id: object) -> list[dict[str, Any]]:
    category_id = str(category_id or "")
    return [row for row in rows if str(row.get("category_id") or "") == category_id]


def category_landing_nav(categories: list[dict[str, Any]], rows: list[dict[str, Any]]) -> str:
    """Create crawlable category landing links without ranking broad categories."""
    if not categories or not rows:
        return ""
    cards: list[str] = []
    campaign = "daily-visits-500-category-landing-pages"
    for cat in categories:
        cat_id = str(cat.get("id") or "").strip()
        if not cat_id:
            continue
        cat_rows = rows_for_category(rows, cat_id)
        if not cat_rows:
            continue
        trend_items = sum(1 for row in cat_rows if has_trend_evidence(row))
        watchlist_items = sum(1 for row in cat_rows if not has_trend_evidence(row))
        top = next((row for row in cat_rows if has_trend_evidence(row)), cat_rows[0])
        href = growth_campaign_path(
            f"/categories/{cat_id}.html",
            source="site",
            medium="category_nav",
            campaign=campaign,
            utm_content=cat_id,
            utm_term="weekly",
        )
        cards.append(f"""
        <a class="category-landing-card" data-growth-cta="category_landing_nav" data-category-id="{esc(cat_id)}" data-item-id="{esc(top.get('item_id'))}" data-item-rank="{esc(top.get('rank'))}" data-item-category="{esc(cat_id)}" href="{esc(href)}">
          <span>{esc(cat.get('name'))}</span>
          <strong>{esc(top.get('item_name'))}</strong>
          <p>{esc(cat.get('description'))}</p>
          <small>{esc(STORE_ZONE_LABELS.get(cat_id, 'Store zone'))} · {esc(trend_items)}/{esc(len(cat_rows))} trend-backed · {esc(watchlist_items)} WATCHLIST</small>
        </a>""")
    if not cards:
        return ""
    return f"""
      <section class="wrap category-landing-nav" data-growth-section="category-landing-nav-v1" data-growth-experiment="category-landing-pages-v1" aria-labelledby="category-landing-title">
        <div class="section-title category-landing-title">
          <div><span>Store category pages · SEO/share path</span><h2 id="category-landing-title">Category별 item ranking 바로가기</h2></div>
          <em>daily-visits-500-category-landing-pages</em>
        </div>
        <p class="category-landing-note">Category는 browsing lane일 뿐 rank 대상이 아닙니다. 각 landing page는 해당 매장 zone 안의 concrete item type만 보여주고, WATCHLIST와 trend-backed item을 분리합니다.</p>
        <div class="category-landing-grid">{''.join(cards)}</div>
      </section>"""


def count_items_with_source(rows: list[dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if int((row.get("source_counts") or {}).get(key) or 0) > 0)


def data_health_panel(rows: list[dict[str, Any]]) -> str:
    trend_items = count_items_with_source(rows, "trend_evidence")
    store_items = count_items_with_source(rows, "retail_product_evidence")
    tiktok_items = count_items_with_source(rows, "tiktok_shop_product_evidence")
    watchlist_items = sum(1 for row in rows if row.get("momentum") == "watchlist" or int((row.get("source_counts") or {}).get("trend_evidence") or 0) == 0)
    metrics = [
        ("Trend items", trend_items),
        ("Store URLs", store_items),
        ("TikTok Shop", tiktok_items),
        ("Watchlist", watchlist_items),
    ]
    return '<div class="data-health" aria-label="Data health">' + ''.join(
        f'<div><b>{esc(value)}</b><span>{esc(label)}</span></div>' for label, value in metrics
    ) + '</div>'


def tiktok_shop_freshness_cell(health: dict[str, Any], cached_tiktok_count: int) -> str:
    """Show current TikTok Shop source freshness without overstating cached URLs."""
    source_health = health.get("source_health", {}) if isinstance(health.get("source_health"), dict) else {}
    apify = source_health.get("apify_tiktok_shop", {}) if isinstance(source_health, dict) else {}
    if not isinstance(apify, dict) or not apify:
        return ""

    status = str(apify.get("status") or "unknown")
    fresh_urls = int(apify.get("fresh_evidence_urls") or 0)
    total_urls = int(apify.get("evidence_urls") or apify.get("cached_evidence_urls") or cached_tiktok_count or 0)
    cached_urls = int(apify.get("partial_cached_evidence_urls") or 0) or cached_tiktok_count
    partial_items = int(apify.get("partial_cached_items") or 0)
    cache_age = apify.get("cache_age_days")
    attempts = apify.get("attempts")

    if status == "success":
        note = f"Actor success · {attempts or 1} attempt(s) · no cache used"
    elif status == "success_sharded_after_full_failure":
        shards = apify.get("shards_succeeded") or apify.get("shards_requested") or "n/a"
        note = f"Full actor failed; shard fallback recovered fresh URLs via {shards} shard(s) · no cache used"
    elif status == "success_sharded_with_partial_cache":
        shards = apify.get("shards_succeeded") or apify.get("shards_requested") or "n/a"
        note = f"Shard fallback recovered fresh URLs via {shards} shard(s) plus {partial_items} cached item(s) · supply-only"
    elif status == "success_with_partial_cache":
        note = f"Actor success plus {partial_items} cached item(s); cache age {cache_age if cache_age is not None else 'n/a'}d · supply-only"
    elif status == "failed_using_cache":
        note = f"Actor failed; cached TikTok Shop URLs reused as supply-only · cache age {cache_age if cache_age is not None else 'n/a'}d"
    elif status in {"failed", "success_empty", "skipped"}:
        note = f"Status {status}; TikTok Shop freshness needs next-run recovery"
    else:
        note = f"Status {status}; source health is shown for owner trust"

    return (
        f'<div class="source-health-cell {esc(status)}" data-source-health="tiktok_shop">'
        f'<b>{esc(fresh_urls)}/{esc(cached_urls)}</b>'
        '<span>TikTok Shop freshness</span>'
        f'<small>{esc(note)} · total URLs {esc(total_urls)}</small></div>'
    )


def evidence_gap_snapshot(rows: list[dict[str, Any]], timeframe: str, collection_health: dict[str, Any] | None = None) -> str:
    """Compact transparency panel so ranking scores do not feel black-box.

    The active ranking window can be much stricter than broader collection
    diagnostics. Showing both prevents owners from misreading a 365-day captured
    source count as a weekly trend claim.
    """
    if not rows:
        return ""
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"items": 0, "trend": 0})
    missing_tiktok: list[str] = []
    cached_tiktok = 0
    for row in rows:
        counts = row.get("source_counts", {}) or {}
        category = str(row.get("category_name") or row.get("category_id") or "Uncategorized")
        by_category[category]["items"] += 1
        if int(counts.get("trend_evidence") or counts.get("news_magazine") or 0) > 0:
            by_category[category]["trend"] += 1
        if int(counts.get("tiktok_shop_product_evidence") or 0) == 0:
            missing_tiktok.append(str(row.get("item_name") or "Unknown item"))
        cached_tiktok += int(counts.get("cached_tiktok_shop_product_evidence") or 0)

    trend_items = count_items_with_source(rows, "trend_evidence")
    watchlist_items = sum(
        1
        for row in rows
        if row.get("momentum") == "watchlist" or int((row.get("source_counts") or {}).get("trend_evidence") or 0) == 0
    )
    zero_trend_categories = [
        f"{category} {stats['items']} items"
        for category, stats in sorted(by_category.items())
        if stats["trend"] == 0
    ]
    zero_summary = ", ".join(zero_trend_categories[:4]) if zero_trend_categories else "None"
    if len(zero_trend_categories) > 4:
        zero_summary += f" +{len(zero_trend_categories) - 4} more"
    tiktok_summary = ", ".join(missing_tiktok[:3]) if missing_tiktok else "None"
    if len(missing_tiktok) > 3:
        tiktok_summary += f" +{len(missing_tiktok) - 3} more"

    label = TIMEFRAME_LABELS.get(timeframe, timeframe.title())
    window_days = TIMEFRAME_DAYS.get(timeframe) or "—"
    health = collection_health if isinstance(collection_health, dict) else {}
    totals = health.get("evidence_totals", {}) if isinstance(health.get("evidence_totals"), dict) else {}
    captured_trend_items = int(totals.get("items_with_published_trend_url") or 0)
    captured_total_items = int(totals.get("items_requested") or len(rows) or 0)
    captured_cell = ""
    if captured_trend_items or captured_total_items:
        captured_cell = (
            f"<div><b>{esc(captured_trend_items)}/{esc(captured_total_items)}</b>"
            "<span>365d captured published URLs</span>"
            "<small>Collection diagnostic only · not weekly trend movement</small></div>"
        )
    freshness_cell = tiktok_shop_freshness_cell(health, cached_tiktok)
    return f"""
      <section class="wrap evidence-snapshot" data-growth-section="evidence-gap-transparency-v1" data-growth-experiment="evidence-window-transparency-v1" aria-label="Evidence quality snapshot">
        <div class="evidence-snapshot-copy">
          <span>Evidence quality snapshot</span>
          <h2>{esc(label)} evidence window를 먼저 확인</h2>
          <p>이 view의 trend-backed count는 {esc(window_days)}일 안에 잡힌 published URL 기준입니다. 365d captured source는 수집 coverage 진단일 뿐, weekly movement를 만들지 않습니다. TikTok Shop freshness는 fresh/cached supply URL을 분리해 보여줍니다.</p>
        </div>
        <div class="evidence-snapshot-grid">
          <div><b>{esc(window_days)}d</b><span>Active trend window</span><small>Rank movement uses this view's dated URLs</small></div>
          <div><b>{esc(trend_items)}/{esc(len(rows))}</b><span>Trend-backed items</span></div>
          <div><b>{esc(watchlist_items)}</b><span>WATCHLIST items</span></div>
          <div><b>{esc(len(zero_trend_categories))}</b><span>Zero-trend categories</span><small>{esc(zero_summary)}</small></div>
          <div><b>{esc(len(missing_tiktok))}</b><span>Missing TikTok Shop</span><small>{esc(tiktok_summary)}</small></div>
          {captured_cell}
          {freshness_cell}
        </div>
        <a class="snapshot-review-link" data-growth-cta="evidence_snapshot_review" href="/data/operations_review_public.json">Public review JSON 보기</a>
      </section>"""


def evidence_focus_watchlist(timeframe: str, rows: list[dict[str, Any]]) -> str:
    """Show which weak items the next evidence loop is actively trying to upgrade.

    This does not turn focus queries into evidence. It gives BSS owners and reps a
    concrete reason to revisit later while keeping WATCHLIST limitations visible.
    """
    focus = load_next_loop_focus()
    focus_items = focus.get("focus_items", []) if isinstance(focus, dict) else []
    if not isinstance(focus_items, list) or not rows:
        return ""
    by_id = {str(row.get("item_id") or ""): row for row in rows}
    cards = []
    label = TIMEFRAME_LABELS.get(timeframe, timeframe.title())
    campaign = f"daily-visits-500-{timeframe}-evidence-focus-watchlist"
    for item in focus_items[:6]:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id") or "").strip()
        row = by_id.get(item_id)
        if not row:
            continue
        counts = row.get("source_counts", {}) or {}
        detail_url = growth_campaign_url(
            f"/items/{item_id}.html",
            source="site",
            medium="focus_watchlist",
            campaign=campaign,
            utm_content=item_id,
            utm_term=timeframe,
        )
        reason = item.get("reason") or evidence_status_label(row)
        cards.append(f"""
        <a class="focus-card" data-growth-cta="evidence_focus_watchlist" data-item-id="{esc(item_id)}" data-item-rank="{esc(row.get('rank'))}" data-item-category="{esc(row.get('category_id'))}" href="{esc(detail_url)}">
          <span>{esc(row.get('category_name'))} · #{esc(row.get('rank'))}</span>
          <strong>{esc(row.get('item_name'))}</strong>
          <p>{esc(clamp_text(reason, 118))}</p>
          <small>Trend {esc(counts.get('trend_evidence', 0))} · 14d {esc(counts.get('recent_trend_evidence', 0))} · Store {esc(counts.get('retail_product_evidence', 0))} · TikTok {esc(counts.get('tiktok_shop_product_evidence', 0))}</small>
        </a>""")
    if not cards:
        return ""
    reviewed_at = focus.get("updated_at") or "pending review"
    return f"""
      <section class="wrap focus-watchlist" data-growth-section="evidence-focus-watchlist-v1" data-growth-experiment="evidence-focus-watchlist-v1" aria-labelledby="focus-watchlist-{esc(timeframe)}">
        <div class="section-title focus-title">
          <div><span>Evidence focus · next loop</span><h2 id="focus-watchlist-{esc(timeframe)}">{esc(label)} WATCHLIST 근거 보강 대상</h2></div>
          <em>{esc(campaign)}</em>
        </div>
        <p class="focus-note">아래 item은 ranking에서 숨기지 않고 다음 수집 loop가 우선 보강하는 대상입니다. 검색 URL이나 query 자체는 evidence가 아니며, 발행일 있는 post/article/listing URL이 잡힐 때만 trend claim으로 올라갑니다. Updated {esc(reviewed_at)}.</p>
        <div class="focus-grid">{''.join(cards)}</div>
        <a class="focus-review-link" data-growth-cta="evidence_focus_public_json" href="/data/next_loop_focus_public.json">Focus JSON 보기</a>
      </section>"""


def growth_campaign_url(path: str, *, source: str, medium: str, campaign: str, **extra: object) -> str:
    params = {
        "utm_source": source,
        "utm_medium": medium,
        "utm_campaign": campaign,
    }
    for key, value in extra.items():
        if value not in (None, ""):
            params[key] = str(value)
    query = urllib.parse.urlencode(params)
    return f"{SITE_BASE}{path}?{query}"


def has_trend_evidence(row: dict[str, Any]) -> bool:
    counts = row.get("source_counts", {})
    return bool(counts.get("trend_evidence") or counts.get("news_magazine"))


def evidence_status_label(row: dict[str, Any]) -> str:
    """Human-readable evidence status for share copy without inflating watchlist items."""
    counts = row.get("source_counts", {}) or {}
    trend_count = int(counts.get("trend_evidence") or counts.get("news_magazine") or 0)
    if trend_count:
        return f"{trend_count} published trend URL(s)"
    return "WATCHLIST · evidence insufficient"


def page_description(prefix: str, rows: list[dict[str, Any]] | None = None) -> str:
    """Short page-specific description for SEO/social previews."""
    if rows:
        top_names = ", ".join(str(row.get("item_name")) for row in rows[:3] if row.get("item_name"))
        if top_names:
            return f"{prefix}: {top_names}. Evidence-backed BSS item ranking with display tips, risk notes, supply URLs, and watchlist separation."
    return f"{prefix}. Evidence-backed BSS item ranking with display tips, risk notes, supply URLs, and watchlist separation."


def item_list_json_ld(rows: list[dict[str, Any]], timeframe: str, path: str) -> dict[str, Any]:
    """Schema.org ItemList so search engines understand the ranking page."""
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"{TIMEFRAME_LABELS.get(timeframe, timeframe.title())} BSS Item Ranking",
        "url": absolute_url(path),
        "itemListOrder": "https://schema.org/ItemListOrderDescending",
        "numberOfItems": len(rows),
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": row.get("rank") or idx,
                "url": absolute_url(f"/items/{row.get('item_id')}.html"),
                "name": row.get("item_name"),
            }
            for idx, row in enumerate(rows[:24], start=1)
        ],
    }


def product_json_ld(row: dict[str, Any]) -> dict[str, Any]:
    """Lightweight product-style metadata; no price/availability claims are invented."""
    counts = row.get("source_counts", {}) or {}
    return {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": row.get("item_name"),
        "category": row.get("category_name"),
        "image": absolute_url(row.get("image_url") or f"/assets/category-{row.get('category_id', 'tools-accessories')}.svg"),
        "description": row.get("reason_summary"),
        "url": absolute_url(f"/items/{row.get('item_id')}.html"),
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "BSS weekly score", "value": row.get("score")},
            {"@type": "PropertyValue", "name": "Momentum", "value": momentum_label(row)},
            {"@type": "PropertyValue", "name": "Published trend URLs", "value": counts.get("trend_evidence", 0)},
            {"@type": "PropertyValue", "name": "Supply/listing URLs", "value": counts.get("retail_product_evidence", 0)},
        ],
    }


def social_share_card_path(timeframe: str) -> str:
    """Return the generated OG/Twitter image path for a ranking timeframe."""
    return f"/assets/share-{timeframe}.svg"


def svg_text(value: object, limit: int | None = None) -> str:
    """Escape and optionally clamp text for the generated social preview SVG."""
    text = " ".join(str(value or "").split())
    if limit and len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return html.escape(text, quote=False)


def write_social_share_cards(data: dict[str, Any]) -> list[str]:
    """Generate local social preview cards for OG/Twitter shareability.

    Shared ranking links should not depend on a random product image or a text-only
    preview. These static SVGs summarize top items and evidence/watchlist counts
    from the current ranking snapshot without making any new trend claims.
    """
    assets_dir = ROOT / "assets"
    assets_dir.mkdir(exist_ok=True)
    generated: list[str] = []
    rankings = data.get("rankings", {}) if isinstance(data.get("rankings"), dict) else {}
    generated_at = str(data.get("generated_at") or data.get("date") or "")
    for timeframe in TIMEFRAME_ORDER:
        rows = rankings.get(timeframe, []) if isinstance(rankings, dict) else []
        rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        if not rows:
            continue
        label = TIMEFRAME_LABELS.get(timeframe, timeframe.title())
        trend_rows = [row for row in rows if has_trend_evidence(row)]
        leaders = (trend_rows or rows)[:3]
        trend_items = count_items_with_source(rows, "trend_evidence")
        watchlist_items = sum(
            1
            for row in rows
            if row.get("momentum") == "watchlist" or source_count(row, "trend_evidence") == 0
        )
        leader_lines = []
        y = 278
        for row in leaders:
            evidence = evidence_status_label(row)
            leader_lines.append(f"""
  <g transform="translate(82 {y})">
    <rect width="1036" height="82" rx="24" fill="#ffffff" opacity="0.96"/>
    <text x="28" y="34" font-family="Arial, Helvetica, sans-serif" font-size="28" font-weight="700" fill="#171717">#{svg_text(row.get('rank'))} {svg_text(row.get('item_name'), 48)}</text>
    <text x="28" y="62" font-family="Arial, Helvetica, sans-serif" font-size="18" fill="#666666">{svg_text(row.get('category_name'), 34)} · {svg_text(evidence, 38)}</text>
    <text x="966" y="51" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="32" font-weight="700" fill="#171717">{svg_text(row.get('score'))}</text>
  </g>""")
            y += 98
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-label="{svg_text(label)} BSS Trend Ranking social preview">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#f7fbff"/>
      <stop offset="0.52" stop-color="#ffffff"/>
      <stop offset="1" stop-color="#fff7ed"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <circle cx="1040" cy="96" r="118" fill="#171717" opacity="0.06"/>
  <circle cx="96" cy="548" r="142" fill="#0072f5" opacity="0.07"/>
  <text x="82" y="82" font-family="Arial, Helvetica, sans-serif" font-size="22" font-weight="700" fill="#0072f5" letter-spacing="3">BSS-WIDE ITEM RANKING · {svg_text(label.upper())}</text>
  <text x="82" y="150" font-family="Arial, Helvetica, sans-serif" font-size="60" font-weight="800" fill="#171717">Beauty Supply Store</text>
  <text x="82" y="208" font-family="Arial, Helvetica, sans-serif" font-size="50" font-weight="800" fill="#171717">owner product picks</text>
  <text x="82" y="246" font-family="Arial, Helvetica, sans-serif" font-size="22" fill="#555555">Published URLs drive trend movement. Supply URLs stay validation-only.</text>
  {''.join(leader_lines)}
  <g transform="translate(82 578)">
    <text font-family="Arial, Helvetica, sans-serif" font-size="18" fill="#555555">Trend-backed {trend_items}/{len(rows)} · WATCHLIST {watchlist_items} · Growth goal 500/day · Generated {svg_text(generated_at, 24)}</text>
  </g>
</svg>
"""
        out = assets_dir / f"share-{timeframe}.svg"
        out.write_text(svg, encoding="utf-8")
        generated.append(str(out.relative_to(ROOT)))
    return generated


def rss_feed_rows(data: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    """Return weekly rows for RSS: trend-backed first, then clearly labeled watchlist."""
    rankings = data.get("rankings", {}) if isinstance(data.get("rankings"), dict) else {}
    weekly = rankings.get("weekly", []) if isinstance(rankings, dict) else []
    rows = [row for row in weekly if isinstance(row, dict)] if isinstance(weekly, list) else []
    trend_rows = [row for row in rows if has_trend_evidence(row)]
    watch_rows = [row for row in rows if not has_trend_evidence(row)]
    return (trend_rows + watch_rows)[:limit]


def write_rss_feed(data: dict[str, Any]) -> str:
    """Generate an owner/subscriber RSS feed for organic repeat visits.

    The feed is a distribution artifact, not a new evidence source. It links to
    item detail pages with UTM tags and labels WATCHLIST rows as evidence
    insufficient so RSS readers cannot mistake supply-only items for trends.
    """
    generated = generated_datetime(data)
    generated_label = str(data.get("generated_at") or data.get("date") or generated.date().isoformat())
    rows = rss_feed_rows(data)
    items: list[str] = []
    for row in rows:
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            continue
        evidence = evidence_status_label(row)
        status = "trend-backed" if has_trend_evidence(row) else "WATCHLIST"
        link = growth_campaign_url(
            f"/items/{item_id}.html",
            source="rss",
            medium="organic",
            campaign="daily-visits-500-rss-feed",
            utm_content=item_id,
            utm_term="weekly",
        )
        title = f"#{row.get('rank')} {row.get('item_name')} · {status}"
        description = (
            f"Category: {row.get('category_name')}. Score {row.get('score')}. "
            f"Evidence: {evidence}. Display test: {row.get('display_tip')}. "
            f"Risk/caution: {row.get('risk')}. "
            "Published URLs drive trend movement; supply/search links are not trend evidence."
        )
        items.append(f"""
    <item>
      <title>{esc(title)}</title>
      <link>{esc(link)}</link>
      <guid isPermaLink="false">gnsresearchhub:{esc(item_id)}:{esc(generated_label)}</guid>
      <pubDate>{esc(rss_datetime(generated))}</pubDate>
      <category>{esc(row.get('category_name'))}</category>
      <description>{esc(description)}</description>
    </item>""")
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>BSS Trend Ranking · Weekly Owner Picks</title>
    <link>{SITE_BASE}/index.html</link>
    <atom:link href="{SITE_BASE}/feed.xml" rel="self" type="application/rss+xml" />
    <description>Weekly Beauty Supply Store item ranking updates with evidence status, display tests, risk cautions, and UTM-tagged item links. Search/watchlist URLs are not counted as trend evidence.</description>
    <language>ko-US</language>
    <lastBuildDate>{esc(rss_datetime(generated))}</lastBuildDate>
    <ttl>720</ttl>
{''.join(items)}
  </channel>
</rss>
"""
    FEED_PATH.write_text(feed, encoding="utf-8")
    return str(FEED_PATH.relative_to(ROOT))


def write_web_manifest(data: dict[str, Any]) -> list[str]:
    """Generate an install/save shortcut manifest for repeat BSS owner visits.

    The 500/day goal depends on owners/reps remembering and reopening the hub.
    A lightweight web app manifest plus a same-origin icon gives browsers a real
    Add-to-Home-Screen/bookmark target, while UTM-tagged start URLs keep the path
    measurable once analytics exports are connected.
    """
    assets_dir = ROOT / "assets"
    assets_dir.mkdir(exist_ok=True)
    generated_at = str(data.get("generated_at") or data.get("date") or "")
    icon_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512" role="img" aria-label="BSS Trend Ranking app icon">
  <defs>
    <linearGradient id="icon-bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0f172a"/>
      <stop offset="0.55" stop-color="#111827"/>
      <stop offset="1" stop-color="#f97316"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" rx="112" fill="url(#icon-bg)"/>
  <circle cx="394" cy="112" r="74" fill="#ffffff" opacity="0.12"/>
  <circle cx="118" cy="392" r="96" fill="#38bdf8" opacity="0.16"/>
  <text x="256" y="218" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="108" font-weight="900" fill="#ffffff">BSS</text>
  <text x="256" y="292" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="44" font-weight="800" fill="#fef3c7">RANKING</text>
  <text x="256" y="350" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="28" font-weight="700" fill="#dbeafe">500/day growth loop</text>
  <text x="256" y="402" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="20" fill="#ffffff" opacity="0.82">Generated {svg_text(generated_at, 22)}</text>
</svg>
"""
    icon_path = assets_dir / "app-icon.svg"
    icon_path.write_text(icon_svg, encoding="utf-8")

    shortcut_campaign = "daily-visits-500-owner-shortcut"
    manifest = {
        "id": "/?app=gns-bss-ranking",
        "name": "BSS Trend Ranking · GNS Research Hub",
        "short_name": "BSS Ranking",
        "description": "Evidence-separated Beauty Supply Store item rankings with display tips, risk notes, and owner share links.",
        "lang": "ko-US",
        "start_url": "/index.html?utm_source=pwa&utm_medium=shortcut&utm_campaign=daily-visits-500-owner-shortcut",
        "scope": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#111827",
        "categories": ["business", "shopping", "news"],
        "icons": [
            {"src": "/assets/app-icon.svg", "sizes": "512x512", "type": "image/svg+xml", "purpose": "any maskable"},
        ],
        "shortcuts": [
            {
                "name": "Weekly BSS ranking",
                "short_name": "Weekly",
                "description": "Open the current weekly item ranking with evidence/watchlist separation.",
                "url": f"/rankings/weekly.html?utm_source=pwa&utm_medium=shortcut&utm_campaign={shortcut_campaign}&utm_content=weekly",
                "icons": [{"src": "/assets/app-icon.svg", "sizes": "512x512", "type": "image/svg+xml"}],
            },
            {
                "name": "Owner feed",
                "short_name": "Feed",
                "description": "Open the weekly owner item feed for repeat visits.",
                "url": "/feed.xml?utm_source=pwa&utm_medium=shortcut&utm_campaign=daily-visits-500-owner-feed-subscribe",
                "icons": [{"src": "/assets/app-icon.svg", "sizes": "512x512", "type": "image/svg+xml"}],
            },
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return [str(MANIFEST_PATH.relative_to(ROOT)), str(icon_path.relative_to(ROOT))]


def choose_share_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prefer evidence-backed leaders, then fall back to the top ranked item."""
    return next((row for row in rows if has_trend_evidence(row)), rows[0] if rows else None)


def share_panel(timeframe: str, rows: list[dict[str, Any]]) -> str:
    row = choose_share_row(rows)
    if not row:
        return ""
    label = TIMEFRAME_LABELS.get(timeframe, timeframe.title())
    campaign = f"daily-visits-500-{timeframe}-owner-share"
    ranking_path = f"/rankings/{timeframe}.html"
    owner_url = growth_campaign_url(ranking_path, source="owner_share", medium="organic", campaign=campaign)
    x_url = growth_campaign_url(ranking_path, source="x", medium="organic", campaign=campaign)
    email_url = growth_campaign_url(ranking_path, source="email", medium="owner_forward", campaign=campaign)
    item_name = row.get("item_name") or "top item"
    category = row.get("category_name") or "BSS item"
    score = row.get("score") or ""
    display = row.get("display_tip") or "front-area test"
    risk = row.get("risk") or "track sell-through and shrink"
    text = (
        f"Beauty Supply Store owners: {label} ranking에서 #{row.get('rank')} {item_name} "
        f"({category})를 확인하세요. Score {score}. Display test: {display}."
    )
    x_intent = "https://twitter.com/intent/tweet?" + urllib.parse.urlencode({"text": text, "url": x_url})
    mailto = "mailto:?" + urllib.parse.urlencode({
        "subject": f"{label} BSS item ranking: {item_name}",
        "body": f"이번 {label} BSS item ranking 공유드립니다.\n\nTop item: {item_name}\nDisplay tip: {display}\nRisk/caution: {risk}\n\nOwner link: {email_url}",
    })
    return f"""
      <section class="wrap share-kit" data-growth-section="owner-share-kit-v1" data-growth-experiment="owner-share-kit-v1" aria-labelledby="share-kit-{esc(timeframe)}">
        <div>
          <span>Growth loop · owner share kit</span>
          <h2 id="share-kit-{esc(timeframe)}">바로 공유할 수 있는 {esc(label)} owner link</h2>
          <p>500 average daily visits 목표를 위해 owner가 다시 열어볼 이유를 강화합니다. 이 링크는 UTM이 붙어 있어 analytics provider 연결 후 channel별 방문/클릭을 분리 측정할 수 있습니다.</p>
        </div>
        <article class="share-card">
          <p class="share-eyebrow">Featured item</p>
          <h3>#{esc(row.get('rank'))} {esc(item_name)}</h3>
          <p>{esc(display)}</p>
          <small>Risk/caution: {esc(risk)}</small>
          <code>{esc(owner_url)}</code>
          <div class="share-actions">
            <a class="share-action" data-growth-share="{esc(timeframe)}_x_intent" href="{esc(x_intent)}" target="_blank" rel="noreferrer">X draft</a>
            <a class="share-action" data-growth-share="{esc(timeframe)}_email_forward" href="{esc(mailto)}">Email draft</a>
            <button class="share-action" type="button" data-growth-share="{esc(timeframe)}_copy_link" data-copy-url="{esc(owner_url)}">Copy owner link</button>
          </div>
        </article>
      </section>"""


def owner_brief_panel(timeframe: str, rows: list[dict[str, Any]]) -> str:
    """One-copy owner brief for reps/owners to forward without writing copy by hand."""
    if not rows:
        return ""
    label = TIMEFRAME_LABELS.get(timeframe, timeframe.title())
    campaign = f"daily-visits-500-{timeframe}-owner-brief"
    ranking_path = f"/rankings/{timeframe}.html"
    owner_url = growth_campaign_url(
        ranking_path,
        source="owner_share",
        medium="brief_copy",
        campaign=campaign,
        utm_content="one_minute_owner_brief",
    )
    email_url = growth_campaign_url(
        ranking_path,
        source="email",
        medium="owner_forward",
        campaign=campaign,
        utm_content="one_minute_owner_brief",
    )

    trend_rows = [row for row in rows if has_trend_evidence(row)]
    lead = trend_rows[0] if trend_rows else rows[0]
    add_on = next(
        (
            row
            for row in trend_rows[1:]
            if row.get("category_id") != lead.get("category_id")
        ),
        trend_rows[1] if len(trend_rows) > 1 else None,
    )
    watch = next((row for row in rows if not has_trend_evidence(row)), None)
    steps = [
        {
            "label": "Floor test",
            "row": lead,
            "note": "가장 먼저 보여줄 evidence-backed item",
        }
    ]
    if add_on:
        steps.append({"label": "Add-on angle", "row": add_on, "note": "같이 팔기 쉬운 adjacent item"})
    if watch:
        steps.append({"label": "Small test only", "row": watch, "note": "WATCHLIST · trend evidence insufficient"})

    step_cards = []
    brief_lines = [f"{label} BSS owner brief:"]
    for index, step in enumerate(steps, start=1):
        row = step["row"]
        item_name = row.get("item_name") or "BSS item"
        display = row.get("display_tip") or "front-area display test"
        risk = row.get("risk") or "track sell-through and shrink"
        evidence_label = evidence_status_label(row)
        brief_lines.append(
            f"{index}) {step['label']}: #{row.get('rank')} {item_name}. "
            f"Display test: {display}. Evidence: {evidence_label}. Risk: {risk}."
        )
        step_cards.append(f"""
          <li>
            <span>{esc(step['label'])}</span>
            <strong>#{esc(row.get('rank'))} {esc(item_name)}</strong>
            <p>{esc(clamp_text(display, 126))}</p>
            <small>{esc(step['note'])} · {esc(evidence_label)}</small>
          </li>""")
    brief_lines.append(f"Full ranking: {owner_url}")
    brief_text = "\n".join(brief_lines)
    mailto = "mailto:?" + urllib.parse.urlencode({
        "subject": f"{label} BSS owner brief",
        "body": brief_text.replace(owner_url, email_url),
    })

    return f"""
      <section class="wrap owner-brief" data-growth-section="owner-brief-copy-v1" data-growth-experiment="owner-brief-copy-v1" aria-labelledby="owner-brief-{esc(timeframe)}">
        <div class="section-title owner-brief-title">
          <div><span>One-minute owner brief · copy-ready</span><h2 id="owner-brief-{esc(timeframe)}">{esc(label)} owner에게 바로 보낼 3줄 요약</h2></div>
          <em>{esc(campaign)}</em>
        </div>
        <ol class="owner-brief-steps">{''.join(step_cards)}</ol>
        <div class="owner-brief-copybox">
          <code>{esc(brief_text)}</code>
          <div class="share-actions">
            <button class="share-action" type="button" data-growth-share="{esc(timeframe)}_owner_brief_copy" data-copy-url="{esc(owner_url)}" data-copy-text="{esc(brief_text)}">Copy owner brief</button>
            <a class="share-action" data-growth-share="{esc(timeframe)}_owner_brief_email" href="{esc(mailto)}">Email brief</a>
          </div>
        </div>
      </section>"""


def owner_feed_subscribe_panel(timeframe: str, rows: list[dict[str, Any]]) -> str:
    """Visible repeat-visit CTA for the weekly RSS/feed distribution path.

    The feed already exists as a crawlable artifact, but a hidden rel=alternate
    tag is too passive for busy owners/reps. This panel makes the repeat-visit
    path visible without making new trend claims: the feed contains the same
    evidence labels and UTM-tagged item links generated from current rankings.
    """
    if not rows:
        return ""
    label = TIMEFRAME_LABELS.get(timeframe, timeframe.title())
    trend_rows = [row for row in rows if has_trend_evidence(row)]
    watchlist_items = len(rows) - len(trend_rows)
    top_names = ", ".join(str(row.get("item_name")) for row in (trend_rows or rows)[:3] if row.get("item_name"))
    campaign = "daily-visits-500-owner-feed-subscribe"
    feed_path = growth_campaign_path(
        "/feed.xml",
        source="site",
        medium="feed_subscribe",
        campaign=campaign,
        utm_content=timeframe,
    )
    feed_url = absolute_url(feed_path)
    return f"""
      <section class="wrap owner-feed" data-growth-section="owner-feed-subscribe-v1" data-growth-experiment="owner-feed-subscribe-v1" aria-labelledby="owner-feed-{esc(timeframe)}">
        <div class="owner-feed-copy">
          <span>Repeat visit path · RSS / saved feed</span>
          <h2 id="owner-feed-{esc(timeframe)}">Weekly owner feed 구독/저장</h2>
          <p>{esc(label)} dashboard를 매번 직접 찾지 않아도, weekly feed에서 item detail로 다시 들어올 수 있습니다. Feed item도 display/risk/evidence status를 포함하고, WATCHLIST {esc(watchlist_items)}개는 evidence insufficient로 표시합니다.</p>
          <small>Current feed leaders: {esc(top_names or 'ranking items')} · {esc(len(trend_rows))}/{esc(len(rows))} trend-backed</small>
        </div>
        <article class="owner-feed-card">
          <strong>Subscribe / save link</strong>
          <code>{esc(feed_url)}</code>
          <div class="share-actions">
            <a class="share-action" data-growth-cta="owner_feed_open" href="{esc(feed_path)}">Open RSS feed</a>
            <button class="share-action" type="button" data-growth-share="{esc(timeframe)}_feed_copy" data-copy-url="{esc(feed_url)}">Copy feed link</button>
          </div>
        </article>
      </section>"""


def owner_shortcut_panel(timeframe: str, rows: list[dict[str, Any]]) -> str:
    """Visible save/bookmark CTA backed by the web app manifest.

    RSS helps subscribers, but many BSS owners will simply save a link on a phone
    or POS/back-office browser. This panel gives them a measurable shortcut URL
    and explains that the dashboard can be saved like an app/bookmark without
    promising traffic gains before analytics access exists.
    """
    if not rows:
        return ""
    label = TIMEFRAME_LABELS.get(timeframe, timeframe.title())
    campaign = "daily-visits-500-owner-shortcut"
    shortcut_path = growth_campaign_path(
        f"/rankings/{timeframe}.html",
        source="site",
        medium="shortcut",
        campaign=campaign,
        utm_content=timeframe,
    )
    shortcut_url = absolute_url(shortcut_path)
    trend_count = sum(1 for row in rows if has_trend_evidence(row))
    top = choose_share_row(rows)
    top_name = top.get("item_name") if top else "current ranking"
    return f"""
      <section class="wrap owner-feed owner-shortcut" data-growth-section="owner-shortcut-save-v1" data-growth-experiment="owner-shortcut-save-v1" aria-labelledby="owner-shortcut-{esc(timeframe)}">
        <div class="owner-feed-copy">
          <span>Repeat visit path · app/bookmark shortcut</span>
          <h2 id="owner-shortcut-{esc(timeframe)}">{esc(label)} dashboard shortcut 저장</h2>
          <p>500 average daily visits 목표를 위해 owner가 다시 열기 쉬운 저장 경로를 추가했습니다. Browser의 Add to Home Screen/Bookmark에 맞춘 manifest가 있고, 아래 shortcut link는 UTM이 붙어 provider 연결 후 repeat visit 경로를 분리 측정할 수 있습니다.</p>
          <small>Shortcut opens {esc(label)} ranking · trend-backed {esc(trend_count)}/{esc(len(rows))} · lead item {esc(top_name)}</small>
        </div>
        <article class="owner-feed-card">
          <strong>Owner shortcut link</strong>
          <code>{esc(shortcut_url)}</code>
          <div class="share-actions">
            <a class="share-action" data-growth-cta="owner_shortcut_open" href="{esc(shortcut_path)}">Open shortcut view</a>
            <button class="share-action" type="button" data-growth-share="{esc(timeframe)}_shortcut_copy" data-copy-url="{esc(shortcut_url)}">Copy shortcut link</button>
            <a class="share-action" data-growth-cta="owner_shortcut_manifest" href="/manifest.webmanifest">Manifest</a>
          </div>
        </article>
      </section>"""


def owner_share_strip(timeframe: str, rows: list[dict[str, Any]]) -> str:
    """Item-specific top share starters for reps/owners, with UTM and item-level tracking."""
    share_rows = [row for row in rows if has_trend_evidence(row)][:3]
    if not share_rows:
        return ""
    label = TIMEFRAME_LABELS.get(timeframe, timeframe.title())
    campaign = f"daily-visits-500-{timeframe}-top3-owner-share"
    cards = []
    for row in share_rows:
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            continue
        item_name = row.get("item_name") or "BSS item"
        display = row.get("display_tip") or "front-area test"
        risk = row.get("risk") or "track sell-through and shrink"
        category = row.get("category_name") or "BSS item"
        evidence_label = evidence_status_label(row)
        item_path = f"/items/{item_id}.html"
        owner_url = growth_campaign_url(
            item_path,
            source="owner_share",
            medium="organic",
            campaign=campaign,
            utm_content=item_id,
            utm_term=timeframe,
        )
        x_url = growth_campaign_url(
            item_path,
            source="x",
            medium="organic",
            campaign=campaign,
            utm_content=item_id,
            utm_term=timeframe,
        )
        email_url = growth_campaign_url(
            item_path,
            source="email",
            medium="owner_forward",
            campaign=campaign,
            utm_content=item_id,
            utm_term=timeframe,
        )
        text = (
            f"Beauty Supply owners: {label} share starter — {item_name}. "
            f"Display test: {display}. Evidence status: {evidence_label}."
        )
        x_intent = "https://twitter.com/intent/tweet?" + urllib.parse.urlencode({"text": text, "url": x_url})
        mailto = "mailto:?" + urllib.parse.urlencode({
            "subject": f"{label} BSS share starter: {item_name}",
            "body": (
                f"Owner님, {label} ranking에서 바로 테스트 검토할 item입니다.\n\n"
                f"Item: {item_name}\n"
                f"Category: {category}\n"
                f"Evidence status: {evidence_label}\n"
                f"Display test: {display}\n"
                f"Risk/caution: {risk}\n\n"
                f"Item link: {email_url}"
            ),
        })
        cards.append(f"""
        <article class="top-share-card" data-item-id="{esc(item_id)}" data-item-rank="{esc(row.get('rank'))}" data-item-category="{esc(row.get('category_id'))}">
          <span>{esc(label)} share starter · #{esc(row.get('rank'))}</span>
          <h3>{esc(item_name)}</h3>
          <p><b>Display</b>{esc(display)}</p>
          <small><b>Risk</b>{esc(risk)}</small>
          <em>{esc(evidence_label)}</em>
          <code>{esc(owner_url)}</code>
          <div class="share-actions">
            <a class="share-action" data-growth-share="{esc(timeframe)}_top3_x_intent" href="{esc(x_intent)}" target="_blank" rel="noreferrer">X draft</a>
            <a class="share-action" data-growth-share="{esc(timeframe)}_top3_email_forward" href="{esc(mailto)}">Email draft</a>
            <button class="share-action" type="button" data-growth-share="{esc(timeframe)}_top3_copy_link" data-copy-url="{esc(owner_url)}">Copy item link</button>
          </div>
        </article>""")
    if not cards:
        return ""
    return f"""
      <section class="wrap top-share-strip" data-growth-section="top3-owner-share-strip-v1" aria-labelledby="top-share-{esc(timeframe)}">
        <div class="section-title top-share-title">
          <div><span>Share starters · measurable growth path</span><h2 id="top-share-{esc(timeframe)}">Top 3 item-specific owner links</h2></div>
          <em>{esc(campaign)}</em>
        </div>
        <p class="top-share-note">Single featured link만으로 끝내지 않고, evidence-backed 상위 item 3개를 owner/reps가 바로 복사·공유할 수 있게 분리했습니다. 모든 링크는 item_id가 붙은 UTM과 growth event context를 남깁니다.</p>
        <div class="top-share-grid">{''.join(cards)}</div>
      </section>"""


def quick_pick_rows(rows: list[dict[str, Any]], max_cards: int = 6) -> list[dict[str, Any]]:
    """Return store-zone picks that help owners act before reading the full ranking.

    Trend-backed categories are prioritized, then zero-trend categories are added
    as clearly labeled WATCHLIST picks so weak evidence lanes stay visible without
    being upgraded into trend claims.
    """
    selected: list[dict[str, Any]] = []
    selected_categories: set[str] = set()
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_category[str(row.get("category_id") or "")].append(row)

    for row in rows:
        category_id = str(row.get("category_id") or "")
        if not has_trend_evidence(row) or category_id in selected_categories:
            continue
        selected.append(row)
        selected_categories.add(category_id)
        if len(selected) >= max_cards - 2:
            break

    zero_trend_picks = []
    for category_id, cat_rows in by_category.items():
        if category_id in selected_categories:
            continue
        if any(has_trend_evidence(row) for row in cat_rows):
            continue
        if cat_rows:
            zero_trend_picks.append(cat_rows[0])
    zero_trend_picks.sort(key=lambda row: int(row.get("rank") or 999))
    for row in zero_trend_picks:
        category_id = str(row.get("category_id") or "")
        if category_id in selected_categories:
            continue
        selected.append(row)
        selected_categories.add(category_id)
        if len(selected) >= max_cards:
            break

    for row in rows:
        category_id = str(row.get("category_id") or "")
        if category_id in selected_categories:
            continue
        selected.append(row)
        selected_categories.add(category_id)
        if len(selected) >= max_cards:
            break

    if len(selected) < max_cards:
        selected_ids = {str(row.get("item_id") or "") for row in selected}
        for row in rows:
            item_id = str(row.get("item_id") or "")
            if item_id in selected_ids:
                continue
            selected.append(row)
            selected_ids.add(item_id)
            if len(selected) >= max_cards:
                break
    return selected[:max_cards]


def owner_quick_picks(timeframe: str, rows: list[dict[str, Any]]) -> str:
    """Store-zone action cards with UTM links for growth and owner usefulness."""
    picks = quick_pick_rows(rows)
    if not picks:
        return ""
    label = TIMEFRAME_LABELS.get(timeframe, timeframe.title())
    campaign = f"daily-visits-500-{timeframe}-owner-quick-picks"
    cards = []
    for row in picks:
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            continue
        zone = STORE_ZONE_LABELS.get(str(row.get("category_id") or ""), row.get("category_name") or "Store zone")
        evidence_label = evidence_status_label(row)
        detail_url = growth_campaign_url(
            f"/items/{item_id}.html",
            source="site",
            medium="quick_pick",
            campaign=campaign,
            utm_content=item_id,
            utm_term=timeframe,
        )
        cards.append(f"""
        <a class="quick-pick-card" data-growth-cta="owner_quick_pick" data-item-id="{esc(item_id)}" data-item-rank="{esc(row.get('rank'))}" data-item-category="{esc(row.get('category_id'))}" href="{esc(detail_url)}">
          <span>{esc(zone)} · #{esc(row.get('rank'))}</span>
          <strong>{esc(row.get('item_name'))}</strong>
          <p>{esc(clamp_text(row.get('display_tip'), 118))}</p>
          <small>{esc(evidence_label)} · Risk: {esc(clamp_text(row.get('risk'), 72))}</small>
        </a>""")
    if not cards:
        return ""
    return f"""
      <section class="wrap quick-picks" data-growth-section="owner-quick-picks-v1" aria-labelledby="quick-picks-{esc(timeframe)}">
        <div class="section-title quick-picks-title">
          <div><span>Owner quick picks · store-zone action</span><h2 id="quick-picks-{esc(timeframe)}">{esc(label)} 매장 테스트 빠른 선택</h2></div>
          <em>{esc(campaign)}</em>
        </div>
        <p class="quick-picks-note">바쁜 BSS owner가 full ranking을 읽기 전에 store zone별로 바로 눌러볼 item을 고르게 만든 growth/UX 실험입니다. WATCHLIST item은 evidence insufficient로 표시해 trend claim으로 과장하지 않습니다.</p>
        <div class="quick-pick-grid">{''.join(cards)}</div>
      </section>"""


def item_share_panel(row: dict[str, Any]) -> str:
    """Owner-ready share CTA for detail pages with item-specific UTM tracking."""
    item_id = str(row.get("item_id") or "").strip()
    if not item_id:
        return ""
    item_name = row.get("item_name") or "BSS item"
    display = row.get("display_tip") or "front-area test"
    risk = row.get("risk") or "track sell-through and shrink"
    category = row.get("category_name") or "BSS item"
    evidence_label = evidence_status_label(row)
    campaign = "daily-visits-500-item-detail-share"
    item_path = f"/items/{item_id}.html"
    owner_url = growth_campaign_url(
        item_path,
        source="owner_share",
        medium="organic",
        campaign=campaign,
        utm_content=item_id,
    )
    x_url = growth_campaign_url(
        item_path,
        source="x",
        medium="organic",
        campaign=campaign,
        utm_content=item_id,
    )
    email_url = growth_campaign_url(
        item_path,
        source="email",
        medium="owner_forward",
        campaign=campaign,
        utm_content=item_id,
    )
    text = (
        f"Beauty Supply Store owners: {item_name} detail page shows display tip, risk, "
        f"and evidence status ({evidence_label}). Display test: {display}."
    )
    x_intent = "https://twitter.com/intent/tweet?" + urllib.parse.urlencode({"text": text, "url": x_url})
    mailto = "mailto:?" + urllib.parse.urlencode({
        "subject": f"BSS item detail: {item_name}",
        "body": (
            f"BSS owner용 item detail 공유드립니다.\n\n"
            f"Item: {item_name}\n"
            f"Category: {category}\n"
            f"Evidence status: {evidence_label}\n"
            f"Display tip: {display}\n"
            f"Risk/caution: {risk}\n\n"
            f"Detail link: {email_url}"
        ),
    })
    return f"""
      <section class="wrap share-kit item-share-kit" data-growth-section="item-detail-share-card-v1" data-growth-experiment="item-detail-share-card-v1" aria-labelledby="item-share-{esc(item_id)}">
        <div>
          <span>Growth loop · item detail share</span>
          <h2 id="item-share-{esc(item_id)}">이 item detail을 owner에게 바로 공유</h2>
          <p>개별 상품 페이지도 repeat visit 진입점으로 만들기 위해 UTM이 붙은 item-specific link를 제공합니다. Evidence status를 함께 보여 과장된 trend claim 없이 공유할 수 있습니다.</p>
        </div>
        <article class="share-card">
          <p class="share-eyebrow">Item share</p>
          <h3>{esc(item_name)}</h3>
          <p>{esc(display)}</p>
          <small>{esc(evidence_label)} · Risk/caution: {esc(risk)}</small>
          <code>{esc(owner_url)}</code>
          <div class="share-actions">
            <a class="share-action" data-growth-share="item_x_intent" href="{esc(x_intent)}" target="_blank" rel="noreferrer">X draft</a>
            <a class="share-action" data-growth-share="item_email_forward" href="{esc(mailto)}">Email draft</a>
            <button class="share-action" type="button" data-growth-share="item_copy_link" data-copy-url="{esc(owner_url)}">Copy item link</button>
          </div>
        </article>
      </section>"""


def top_three(rows: list[dict[str, Any]]) -> str:
    trend_rows = [row for row in rows if has_trend_evidence(row)]
    if not trend_rows:
        return """
        <section class="empty-state">
          <strong>이번 기간 검증된 Top 3 없음</strong>
          <p>발행일 있는 item-specific URL이 없어 Top 3를 trend로 표시하지 않습니다. 아래 전체 리스트는 live product URL과 BSS 적합도를 포함한 watchlist입니다.</p>
        </section>"""
    cards = []
    for row in trend_rows[:3]:
        cards.append(f"""
        <a class="podium-card" data-item-id="{esc(row.get('item_id'))}" data-item-rank="{esc(row.get('rank'))}" data-item-category="{esc(row.get('category_id'))}" href="/items/{esc(row.get('item_id'))}.html">
          {image_tag(row, 'podium-img')}
          <span class="podium-rank">#{esc(row.get('rank'))}</span>
          <div>
            <p>{esc(row.get('category_name'))}</p>
            <h2>{esc(row.get('item_name'))}</h2>
          </div>
          <strong>{esc(row.get('score'))}</strong>
        </a>""")
    return '<section class="podium">' + ''.join(cards) + '</section>'


def render_home(data: dict[str, Any]) -> str:
    weekly = data.get("rankings", {}).get("weekly", [])
    monthly = data.get("rankings", {}).get("monthly", [])
    cats = data.get("categories", [])
    body = f"""
    <main>
      <section class="hero wrap" id="all">
        <div class="hero-copy">
          <p class="eyebrow">BSS-wide · Specific product ranking</p>
          <h1 data-growth-hero-title>Beauty Supply 제품별 트렌드 순위</h1>
          <p class="lead" data-growth-hero-lead>검색 링크는 근거로 세지 않습니다. 발행일 있는 실제 URL은 trend movement에, BSS/wholesale/TikTok Shop 실제 상품 URL은 supply/social-commerce validation에만 반영합니다. 발행 근거가 부족한 항목은 trend가 아니라 WATCHLIST로 표시합니다.</p>
          <div class="hero-actions" aria-label="Growth actions">
            <a class="primary-action" data-growth-cta="primary" href="/rankings/weekly.html?utm_source=site&utm_medium=hero&utm_campaign=daily-visits-500">Weekly ranking 보기</a>
            <a class="secondary-action" data-growth-cta="secondary" href="/rankings/weekly.html#all-items">Evidence / watchlist 보기</a>
          </div>
        </div>
        <div class="hero-panel">
          <span>Latest run</span>
          <strong>{esc(data.get('date'))}</strong>
          <small>{len(weekly)} items · {len(cats)} categories</small>
          <div class="growth-goal" aria-label="Growth goal">
            <span>Growth goal</span>
            <strong>500/day</strong>
            <small>rolling 30-day visits</small>
          </div>
          <span class="health-label">Data health</span>
          {data_health_panel(weekly)}
        </div>
      </section>
      <div class="wrap">{category_chips(cats, base_path='/rankings/weekly.html')}</div>
      {category_landing_nav(cats, weekly)}
      {return_visitor_panel('weekly')}
      {run_change_snapshot(data, 'weekly', weekly)}
      {evidence_gap_snapshot(weekly, 'weekly', data.get('collection_health', {}))}
      {evidence_focus_watchlist('weekly', weekly)}
      {owner_quick_picks('weekly', weekly)}
      {owner_brief_panel('weekly', weekly)}
      {owner_feed_subscribe_panel('weekly', weekly)}
      {owner_shortcut_panel('weekly', weekly)}
      {share_panel('weekly', weekly)}
      {owner_share_strip('weekly', weekly)}
      <section class="wrap block" data-growth-section="top3-leaderboard-v1" data-growth-experiment="ranking-list-engagement-context-v1">
        <div class="section-title"><div><span>Weekly leaders</span><h2>이번 주 Top 3</h2></div><a href="/rankings/weekly.html">전체 보기</a></div>
        {top_three(weekly)}
      </section>
      <section class="wrap board" data-growth-section="ranking-main-list-v1" data-growth-experiment="ranking-list-engagement-context-v1">
        <div class="section-title"><div><span>Weekly ranking</span><h2>Top item list</h2></div><a href="/rankings/monthly.html">Monthly 보기</a></div>
        <div class="rank-list">{''.join(item_card(row, compact=True) for row in weekly[:12])}</div>
      </section>
      <section class="wrap board secondary-board" data-growth-section="monthly-preview-list-v1" data-growth-experiment="ranking-list-engagement-context-v1">
        <div class="section-title"><div><span>Monthly leaders</span><h2>월간 흐름</h2></div></div>
        <div class="rank-grid">{''.join(item_card(row, compact=True) for row in monthly[:6])}</div>
      </section>
    </main>"""
    return shell(
        "Home",
        body,
        active="weekly",
        page_type="home",
        page_path="/index.html",
        description=page_description("Weekly BSS retail-owner product ranking", weekly),
        image_url=social_share_card_path("weekly") if weekly else None,
        json_ld=item_list_json_ld(weekly, "weekly", "/index.html"),
    )


def render_category_page(data: dict[str, Any], category: dict[str, Any]) -> str:
    """Render an SEO/share landing page for one store-like category lane.

    The page does not rank broad categories. It gives owners a focused, shareable
    view of the concrete item types inside one BSS store zone.
    """
    cat_id = str(category.get("id") or "").strip()
    cat_name = str(category.get("name") or cat_id or "Category")
    weekly_rows = data.get("rankings", {}).get("weekly", [])
    rows = rows_for_category([row for row in weekly_rows if isinstance(row, dict)], cat_id)
    trend_rows = [row for row in rows if has_trend_evidence(row)]
    watchlist_items = len(rows) - len(trend_rows)
    store_zone = STORE_ZONE_LABELS.get(cat_id, "Store zone")
    category_path = f"/categories/{cat_id}.html"
    ranking_anchor = f"/rankings/weekly.html#{cat_id}"
    owner_url = growth_campaign_url(
        category_path,
        source="owner_share",
        medium="category_page",
        campaign="daily-visits-500-category-landing-pages",
        utm_content=cat_id,
        utm_term="weekly",
    )
    x_intent = "https://twitter.com/intent/tweet?" + urllib.parse.urlencode({
        "text": (
            f"Beauty Supply owners: {cat_name} item ranking shows concrete product types, "
            f"display tests, risk cautions, and WATCHLIST separation."
        ),
        "url": growth_campaign_url(
            category_path,
            source="x",
            medium="organic",
            campaign="daily-visits-500-category-landing-pages",
            utm_content=cat_id,
            utm_term="weekly",
        ),
    })
    mailto = "mailto:?" + urllib.parse.urlencode({
        "subject": f"BSS category item ranking: {cat_name}",
        "body": (
            f"Owner님, {cat_name} category 안에서 이번 주 볼 item ranking입니다.\n"
            f"Store zone: {store_zone}\nTrend-backed: {len(trend_rows)}/{len(rows)} · WATCHLIST: {watchlist_items}\n"
            f"Link: {owner_url}"
        ),
    })
    top_cards = top_three(rows)
    if not rows:
        top_cards = """
        <section class="empty-state">
          <strong>현재 이 category에 표시할 item이 없습니다.</strong>
          <p>다음 refresh에서 data/rankings.json category mapping을 확인합니다.</p>
        </section>"""
    owner_test_cards = []
    for row in rows[:3]:
        item_id = str(row.get("item_id") or "").strip()
        item_href = growth_campaign_path(
            f"/items/{item_id}.html",
            source="site",
            medium="category_page",
            campaign="daily-visits-500-category-landing-pages",
            utm_content=item_id,
            utm_term=cat_id,
        )
        owner_test_cards.append(f"""
        <a class="quick-pick-card" data-growth-cta="category_owner_test" data-item-id="{esc(item_id)}" data-item-rank="{esc(row.get('rank'))}" data-item-category="{esc(cat_id)}" href="{esc(item_href)}">
          <span>{esc(store_zone)} · #{esc(row.get('rank'))}</span>
          <strong>{esc(row.get('item_name'))}</strong>
          <p>{esc(row.get('display_tip'))}</p>
          <small>{esc(evidence_status_label(row))} · Risk: {esc(row.get('risk'))}</small>
        </a>""")
    body = f"""
    <main>
      <section class="hero wrap compact category-hero" id="all">
        <div class="hero-copy">
          <a class="back" href="/rankings/weekly.html">← Weekly ranking으로 돌아가기</a>
          <p class="eyebrow">Store category · weekly item ranking</p>
          <h1>{esc(cat_name)} item ranking</h1>
          <p class="lead">{esc(category.get('description'))}. 이 page는 category 자체를 trend로 주장하지 않고, {esc(store_zone)} 안에서 owner가 실제로 stock/test/reorder할 수 있는 item type만 보여줍니다.</p>
          <div class="hero-actions" aria-label="Category growth actions">
            <a class="primary-action" data-growth-cta="category_weekly_anchor" href="{esc(ranking_anchor)}">Weekly section 보기</a>
            <a class="secondary-action" data-growth-cta="category_all_items" href="#all-items">이 category item 보기</a>
          </div>
        </div>
        <div class="hero-panel">
          <span>Category health</span>
          <strong>{esc(len(rows))} items</strong>
          <small>{esc(store_zone)} · {esc(data.get('date'))}</small>
          <div class="data-health" aria-label="Category data health">
            <div><b>{esc(len(trend_rows))}</b><span>Trend-backed</span></div>
            <div><b>{esc(watchlist_items)}</b><span>WATCHLIST</span></div>
            <div><b>{esc(count_items_with_source(rows, 'retail_product_evidence'))}</b><span>Store URLs</span></div>
            <div><b>{esc(count_items_with_source(rows, 'tiktok_shop_product_evidence'))}</b><span>TikTok Shop</span></div>
          </div>
        </div>
      </section>
      <div class="wrap">{category_chips(data.get('categories', []), base_path='/rankings/weekly.html')}</div>
      {return_visitor_panel('weekly')}
      <section class="wrap share-kit category-share-kit" data-growth-section="category-share-kit-v1" data-growth-experiment="category-landing-pages-v1" aria-labelledby="category-share-{esc(cat_id)}">
        <div>
          <span>Category share path</span>
          <h2 id="category-share-{esc(cat_id)}">{esc(cat_name)} owner link</h2>
          <p>Category-specific page를 공유하면 owner가 broad ranking 전체를 읽기 전에 자신의 매장 zone과 관련된 item만 빠르게 확인할 수 있습니다. WATCHLIST는 evidence insufficient로 유지합니다.</p>
        </div>
        <article class="share-card">
          <p class="share-eyebrow">Focused owner link</p>
          <h3>{esc(cat_name)}</h3>
          <p>{esc(store_zone)} · {esc(len(trend_rows))}/{esc(len(rows))} trend-backed · {esc(watchlist_items)} WATCHLIST</p>
          <code>{esc(owner_url)}</code>
          <div class="share-actions">
            <a class="share-action" data-growth-share="category_x_intent" href="{esc(x_intent)}" target="_blank" rel="noreferrer">X draft</a>
            <a class="share-action" data-growth-share="category_email_forward" href="{esc(mailto)}">Email draft</a>
            <button class="share-action" type="button" data-growth-share="category_copy_link" data-copy-url="{esc(owner_url)}">Copy category link</button>
          </div>
        </article>
      </section>
      <section class="wrap block" data-growth-section="category-top-items-v1" data-growth-experiment="category-landing-pages-v1">
        <div class="section-title"><div><span>{esc(cat_name)}</span><h2>Top item signals</h2></div><em>{esc(len(trend_rows))}/{esc(len(rows))} trend-backed</em></div>
        {top_cards}
      </section>
      <section class="wrap quick-picks category-owner-test" data-growth-section="category-owner-test-v1" data-growth-experiment="category-landing-pages-v1" aria-labelledby="category-owner-test-{esc(cat_id)}">
        <div class="section-title quick-picks-title"><div><span>Owner test · {esc(store_zone)}</span><h2 id="category-owner-test-{esc(cat_id)}">이 category에서 먼저 볼 display test</h2></div><em>trend-backed 먼저, 없으면 WATCHLIST 소량 test</em></div>
        <div class="quick-pick-grid">{''.join(owner_test_cards)}</div>
      </section>
      <section class="wrap board" id="all-items" data-growth-section="category-ranking-list-v1" data-growth-experiment="category-landing-pages-v1">
        <div class="section-title"><div><span>Concrete item types only</span><h2>{esc(cat_name)} 전체 item</h2></div><a href="{esc(ranking_anchor)}">Weekly ranking anchor</a></div>
        <div class="rank-list">{''.join(item_card(row) for row in rows)}</div>
      </section>
    </main>"""
    return shell(
        f"{cat_name} Category",
        body,
        active="weekly",
        page_type="category",
        page_path=category_path,
        description=page_description(f"Weekly BSS {cat_name} category item ranking", rows),
        image_url=social_share_card_path("weekly") if rows else f"/assets/category-{cat_id}.svg",
        json_ld=item_list_json_ld(rows, "weekly", category_path),
    )


def render_timeframe(data: dict[str, Any], timeframe: str) -> str:
    rows = data.get("rankings", {}).get(timeframe, [])
    cfg = data.get("timeframes", {}).get(timeframe, {})
    cats = data.get("categories", [])
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_cat[row.get("category_id")].append(row)
    cat_sections = []
    for cat in cats:
        cat_rows = by_cat.get(cat.get("id"), [])
        if not cat_rows:
            continue
        cat_sections.append(f"""
        <section class="category-block" id="{esc(cat.get('id'))}">
          <div class="section-title compact-title"><div><span>{esc(cat.get('description'))}</span><h2>{esc(cat.get('name'))}</h2></div></div>
          <div class="rank-list">{''.join(item_card(row) for row in cat_rows)}</div>
        </section>""")
    body = f"""
    <main>
      <section class="hero wrap compact" id="all">
        <div class="hero-copy">
          <p class="eyebrow">{esc(TIMEFRAME_LABELS.get(timeframe, timeframe.title()))} · {esc(cfg.get('days'))} days</p>
          <h1>{esc(TIMEFRAME_LABELS.get(timeframe, timeframe.title()))} ranking</h1>
          <p class="lead">{esc(cfg.get('description'))}. 발행일 있는 실제 URL, 최근성, 이전 run 대비 변화를 우선 정렬하고, live product URL은 trend claim이 아닌 검토용 supply 근거로 분리합니다.</p>
        </div>
        <div class="hero-panel">
          <span>Ranked items</span>
          <strong>{len(rows)}</strong>
          <small>{esc(data.get('date'))}</small>
        </div>
      </section>
      <div class="wrap">{category_chips(cats)}</div>
      {return_visitor_panel(timeframe)}
      {run_change_snapshot(data, timeframe, rows)}
      {evidence_gap_snapshot(rows, timeframe, data.get('collection_health', {}))}
      {evidence_focus_watchlist(timeframe, rows)}
      {owner_quick_picks(timeframe, rows)}
      {owner_brief_panel(timeframe, rows)}
      {owner_feed_subscribe_panel(timeframe, data.get("rankings", {}).get("weekly", rows))}
      {owner_shortcut_panel(timeframe, rows)}
      {share_panel(timeframe, rows)}
      {owner_share_strip(timeframe, rows)}
      <section class="wrap block" data-growth-section="top3-leaderboard-v1" data-growth-experiment="ranking-list-engagement-context-v1">
        <div class="section-title"><div><span>Leaderboard</span><h2>Top 3</h2></div></div>
        {top_three(rows)}
      </section>
      <section class="wrap board" id="all-items" data-growth-section="ranking-main-list-v1" data-growth-experiment="ranking-list-engagement-context-v1">
        <div class="section-title"><div><span>All categories</span><h2>전체 순위</h2></div><em>{len(rows)} items</em></div>
        <div class="rank-list">{''.join(item_card(row) for row in rows)}</div>
      </section>
      <section class="wrap category-stack">{''.join(cat_sections)}</section>
    </main>"""
    ranking_path = f"/rankings/{timeframe}.html"
    return shell(
        f"{TIMEFRAME_LABELS.get(timeframe, timeframe.title())} Ranking",
        body,
        active=timeframe,
        page_type="ranking",
        page_path=ranking_path,
        description=page_description(f"{TIMEFRAME_LABELS.get(timeframe, timeframe.title())} BSS product ranking", rows),
        image_url=social_share_card_path(timeframe) if rows else None,
        json_ld=item_list_json_ld(rows, timeframe, ranking_path),
    )


def grouped_sources(row: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for src in row.get("trend_evidence", row.get("news_evidence", [])):
        groups["Published trend evidence · URL/date counted"].append(src)
    for src in row.get("retail_product_evidence", []):
        if src.get("source_type") == "bss_online_store":
            label = "Verified BSS product URLs · supply only"
        elif src.get("source_kind") == "tiktok_shop_apify":
            if src.get("cache_status"):
                label = "Cached TikTok Shop URLs · previous capture supply only"
            else:
                label = "Verified TikTok Shop URLs · social commerce supply only"
        elif src.get("source_type") == "marketplace_product":
            label = "Verified marketplace product URLs · supply only"
        else:
            label = "Verified wholesale product URLs · supply only"
        groups[label].append(src)
    # Backward compatibility for older data where all verified evidence was in one list.
    if not groups:
        for src in row.get("verified_evidence", []):
            groups["Verified evidence · actual URL/date"].append(src)
    for src in row.get("watchlist_links", row.get("manual_references", [])):
        label = {
            "sns": "Watchlist only · SNS / TikTok",
            "visual": "Watchlist only · Pinterest / Visual",
            "social": "Watchlist only · X / Twitter",
            "community": "Watchlist only · Reddit",
            "marketplace": "Watchlist only · Amazon / Marketplace",
            "search_interest": "Watchlist only · Google Trends",
            "bss_online_store": "Watchlist only · BSS Online Stores",
            "wholesale": "Watchlist only · Wholesale / Supply",
        }.get(src.get("source_type"), f"Watchlist only · {src.get('source_type', 'Other')}")
        groups[label].append(src)
    return groups


def render_item_detail(data: dict[str, Any], item_id: str) -> str:
    rows_by_tf = {tf: next((r for r in data.get("rankings", {}).get(tf, []) if r.get("item_id") == item_id), None) for tf in TIMEFRAME_ORDER}
    row = rows_by_tf.get("weekly") or next((r for r in rows_by_tf.values() if r), None)
    if not row:
        return shell("Item not found", '<main class="wrap"><h1>Item not found</h1></main>', page_type="item_detail", page_path="/items/not-found.html")
    rank_cards = []
    for tf in TIMEFRAME_ORDER:
        r = rows_by_tf.get(tf)
        if r:
            rank_cards.append(f'<div class="metric-card"><span>{TIMEFRAME_LABELS[tf]}</span><strong>#{esc(r.get("rank"))}</strong><small>Score {esc(r.get("score"))}</small></div>')
    evidence_items = "".join(f"<li>{esc(x)}</li>" for x in row.get("evidence_summary", []))
    breakdown = row.get("score_breakdown", {})
    breakdown_items = "".join(
        f"<li><b>{esc(k.replace('_', ' ').title())}</b>: {esc(v)}</li>"
        for k, v in breakdown.items()
    )
    source_sections = []
    for label, sources in grouped_sources(row).items():
        source_cards = []
        for src in sources[:12]:
            title = src.get("title") or src.get("publisher") or src.get("source_kind") or src.get("source_type")
            date = src.get("published_date") or src.get("observed_date") or src.get("seendate") or src.get("published") or ""
            date_kind = "Published" if src.get("date_kind") == "published" else ("Observed" if src.get("observed_date") else "")
            date_label = f"{date_kind} {date}".strip() if date else ""
            price = f" · ${esc(src.get('price'))}" if src.get("price") else ""
            summary = src.get("summary") or src.get("snippet") or date_label or "Reference source"
            if src.get("cache_status"):
                summary = (
                    f"Cached fallback after current TikTok Shop actor failure; originally observed {src.get('observed_date') or 'date n/a'}. "
                    + str(summary)
                )
            source_layer = src.get("source_layer") or src.get("source_type") or "unknown"
            source_kind = src.get("source_kind") or src.get("publisher") or src.get("domain") or "unknown"
            source_type = src.get("source_type") or "unknown"
            source_status = src.get("evidence_status") or ("cached_verified_url" if src.get("cache_status") else "unknown")
            source_date_kind = src.get("date_kind") or "unknown"
            source_cards.append(f"""
            <a class="source-card" href="{esc(src.get('url'))}" target="_blank" rel="noreferrer" data-growth-source-layer="{esc(source_layer)}" data-growth-source-kind="{esc(source_kind)}" data-growth-source-type="{esc(source_type)}" data-growth-source-status="{esc(source_status)}" data-growth-source-date-kind="{esc(source_date_kind)}">
              <span>{esc(src.get('publisher') or src.get('domain') or src.get('source_kind') or src.get('source_type'))}{' · ' + esc(date_label) if date_label else ''}{price}</span>
              <strong>{esc(title)}</strong>
              <p>{esc(summary)}</p>
            </a>""")
        source_sections.append(f'<section class="source-group"><h2>{esc(label)}</h2><div class="source-grid">{"".join(source_cards)}</div></section>')
    body = f"""
    <main class="item-page">
      <section class="hero wrap item-hero">
        <div class="hero-copy">
          <a class="back" href="/rankings/weekly.html">← Ranking으로 돌아가기</a>
          <p class="eyebrow">{esc(row.get('category_name'))}</p>
          <h1>{esc(row.get('item_name'))}</h1>
          <p class="lead">{esc(row.get('reason_summary'))}</p>
        </div>
        <div class="score-hero">
          {image_tag(row, 'detail-img')}
          <span>Weekly score</span>
          <strong>{esc(row.get('score'))}</strong>
          {score_bar(row.get('score'))}
          <small>{esc(momentum_label(row))} · {esc(fmt_change(row.get('rank_change')))}</small>
        </div>
      </section>
      <section class="wrap metrics-grid">{''.join(rank_cards)}</section>
      {item_share_panel(row)}
      <section class="wrap detail-grid">
        <article><span>Display</span><p>{esc(row.get('display_tip'))}</p></article>
        <article><span>Risk</span><p>{esc(row.get('risk'))}</p></article>
        <article><span>Owner message</span><p>{esc(row.get('owner_message_en'))}</p></article>
        <article><span>Evidence summary</span><ul>{evidence_items}</ul></article>
        <article><span>Score breakdown</span><ul>{breakdown_items}</ul></article>
        <article><span>Movement rule</span><p>{esc(row.get('change_note'))}</p></article>
      </section>
      <section class="wrap sources" data-growth-section="source-evidence-clicks-v1" data-growth-experiment="source-evidence-clicks-v1">
        <div class="section-title"><div><span>Evidence vs watchlist</span><h2>실제 근거와 참고 링크 분리</h2></div></div>
        {''.join(source_sections)}
      </section>
    </main>"""
    return shell(
        row.get("item_name", "Item"),
        body,
        active="weekly",
        page_type="item_detail",
        page_path=f"/items/{item_id}.html",
        description=page_description(str(row.get("item_name") or "BSS item detail"), [row]),
        image_url=row.get("image_url"),
        json_ld=product_json_ld(row),
    )


def sitemap_entry(path: str, lastmod: str, priority: str, changefreq: str = "daily") -> str:
    return (
        "  <url>"
        f"<loc>{esc(absolute_url(path))}</loc>"
        f"<lastmod>{esc(lastmod)}</lastmod>"
        f"<changefreq>{esc(changefreq)}</changefreq>"
        f"<priority>{esc(priority)}</priority>"
        "</url>"
    )


def write_seo_files(data: dict[str, Any], item_ids: set[str], category_ids: set[str] | None = None) -> None:
    """Generate crawl/share discovery artifacts for the deployed static site."""
    lastmod = str(data.get("date") or dt.date.today().isoformat())
    category_ids = category_ids or set()
    paths: list[tuple[str, str, str]] = [
        ("/index.html", "1.0", "daily"),
        ("/feed.xml", "0.8", "daily"),
        *[(f"/rankings/{tf}.html", "0.9", "daily") for tf in TIMEFRAME_ORDER],
        *[(f"/categories/{category_id}.html", "0.82", "daily") for category_id in sorted(category_ids) if category_id],
        *[(f"/items/{item_id}.html", "0.72", "weekly") for item_id in sorted(item_ids) if item_id],
    ]
    sitemap = "\n".join(
        ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"]
        + [sitemap_entry(path, lastmod, priority, changefreq) for path, priority, changefreq in paths]
        + ["</urlset>"]
    )
    SITEMAP_PATH.write_text(sitemap + "\n", encoding="utf-8")
    ROBOTS_PATH.write_text(
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {SITE_BASE}/sitemap.xml\n",
        encoding="utf-8",
    )


def main() -> int:
    for generated_dir in (RANKINGS_DIR, ITEMS_DIR, CATEGORIES_DIR):
        if generated_dir.exists():
            shutil.rmtree(generated_dir)
    RANKINGS_DIR.mkdir(exist_ok=True)
    ITEMS_DIR.mkdir(exist_ok=True)
    CATEGORIES_DIR.mkdir(exist_ok=True)
    data = load_rankings()
    generated_social_cards = write_social_share_cards(data)
    generated_feed = write_rss_feed(data)
    generated_manifest = write_web_manifest(data)
    (ROOT / "index.html").write_text(render_home(data), encoding="utf-8")
    for tf in TIMEFRAME_ORDER:
        (RANKINGS_DIR / f"{tf}.html").write_text(render_timeframe(data, tf), encoding="utf-8")
    category_ids = set()
    for category in data.get("categories", []):
        if isinstance(category, dict) and category.get("id"):
            category_id = str(category.get("id"))
            category_ids.add(category_id)
            (CATEGORIES_DIR / f"{category_id}.html").write_text(render_category_page(data, category), encoding="utf-8")
    item_ids = {r.get("item_id") for rows in data.get("rankings", {}).values() for r in rows}
    for item_id in item_ids:
        if item_id:
            (ITEMS_DIR / f"{item_id}.html").write_text(render_item_detail(data, item_id), encoding="utf-8")
    write_seo_files(data, {str(item_id) for item_id in item_ids if item_id}, category_ids)
    generated = ["index.html", "robots.txt", "sitemap.xml", generated_feed, *generated_manifest, *generated_social_cards] + [f"rankings/{tf}.html" for tf in TIMEFRAME_ORDER] + [f"categories/{category_id}.html" for category_id in sorted(category_ids)]
    print(json.dumps({"site_root": str(ROOT), "generated": generated, "items": len(item_ids), "categories": len(category_ids)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())