#!/usr/bin/env python3
"""Build a clean store-style item ranking dashboard for BSS trend intelligence."""
from __future__ import annotations

import datetime as dt
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
RANKINGS_DIR = ROOT / "rankings"
ITEMS_DIR = ROOT / "items"
ROBOTS_PATH = ROOT / "robots.txt"
SITEMAP_PATH = ROOT / "sitemap.xml"

TIMEFRAME_ORDER = ["weekly", "monthly", "quarterly", "yearly"]
TIMEFRAME_LABELS = {"weekly": "Weekly", "monthly": "Monthly", "quarterly": "Quarterly", "yearly": "Yearly"}
SITE_BASE = "https://gnsresearchhub.vercel.app"
GA4_MEASUREMENT_ID = "G-SW7HBY6WRE"


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


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


def analytics_head() -> str:
    """Return production analytics tags shared by every generated page."""
    return f"""  <script async src=\"https://www.googletagmanager.com/gtag/js?id={GA4_MEASUREMENT_ID}\"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', '{GA4_MEASUREMENT_ID}');
  </script>
"""


def load_rankings() -> dict[str, Any]:
    if not RANKINGS_PATH.exists():
        return {"rankings": {}, "categories": [], "generated_at": ""}
    return json.loads(RANKINGS_PATH.read_text(encoding="utf-8"))


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


def evidence_gap_snapshot(rows: list[dict[str, Any]], timeframe: str) -> str:
    """Compact transparency panel so ranking scores do not feel black-box."""
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
    cache_cell = ""
    if cached_tiktok:
        cache_cell = (
            f"<div><b>{esc(cached_tiktok)}</b><span>Cached TikTok Shop</span>"
            "<small>Current actor failed; previous capture is labeled supply-only</small></div>"
        )
    return f"""
      <section class="wrap evidence-snapshot" data-growth-section="evidence-gap-transparency-v1" aria-label="Evidence quality snapshot">
        <div class="evidence-snapshot-copy">
          <span>Evidence quality snapshot</span>
          <h2>{esc(label)} score를 과장하지 않기 위한 공개 체크</h2>
          <p>Trend URL, WATCHLIST, zero-trend category, TikTok Shop coverage를 한눈에 보여 owner가 점수와 evidence gap을 같이 판단하게 합니다.</p>
        </div>
        <div class="evidence-snapshot-grid">
          <div><b>{esc(trend_items)}/{esc(len(rows))}</b><span>Trend-backed items</span></div>
          <div><b>{esc(watchlist_items)}</b><span>WATCHLIST items</span></div>
          <div><b>{esc(len(zero_trend_categories))}</b><span>Zero-trend categories</span><small>{esc(zero_summary)}</small></div>
          <div><b>{esc(len(missing_tiktok))}</b><span>Missing TikTok Shop</span><small>{esc(tiktok_summary)}</small></div>
          {cache_cell}
        </div>
        <a class="snapshot-review-link" data-growth-cta="evidence_snapshot_review" href="/data/operations_review_public.json">Public review JSON 보기</a>
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
      <section class="wrap share-kit" aria-labelledby="share-kit-{esc(timeframe)}">
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
      <section class="wrap share-kit item-share-kit" aria-labelledby="item-share-{esc(item_id)}">
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
        <a class="podium-card" href="/items/{esc(row.get('item_id'))}.html">
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
      {evidence_gap_snapshot(weekly, 'weekly')}
      {share_panel('weekly', weekly)}
      {owner_share_strip('weekly', weekly)}
      <section class="wrap block">
        <div class="section-title"><div><span>Weekly leaders</span><h2>이번 주 Top 3</h2></div><a href="/rankings/weekly.html">전체 보기</a></div>
        {top_three(weekly)}
      </section>
      <section class="wrap board">
        <div class="section-title"><div><span>Weekly ranking</span><h2>Top item list</h2></div><a href="/rankings/monthly.html">Monthly 보기</a></div>
        <div class="rank-list">{''.join(item_card(row, compact=True) for row in weekly[:12])}</div>
      </section>
      <section class="wrap board secondary-board">
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
        image_url=(choose_share_row(weekly) or {}).get("image_url") if weekly else None,
        json_ld=item_list_json_ld(weekly, "weekly", "/index.html"),
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
      {evidence_gap_snapshot(rows, timeframe)}
      {share_panel(timeframe, rows)}
      {owner_share_strip(timeframe, rows)}
      <section class="wrap block">
        <div class="section-title"><div><span>Leaderboard</span><h2>Top 3</h2></div></div>
        {top_three(rows)}
      </section>
      <section class="wrap board" id="all-items">
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
        image_url=(choose_share_row(rows) or {}).get("image_url") if rows else None,
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
            source_cards.append(f"""
            <a class="source-card" href="{esc(src.get('url'))}" target="_blank" rel="noreferrer">
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
      <section class="wrap sources">
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


def write_seo_files(data: dict[str, Any], item_ids: set[str]) -> None:
    """Generate crawl/share discovery artifacts for the deployed static site."""
    lastmod = str(data.get("date") or dt.date.today().isoformat())
    paths: list[tuple[str, str, str]] = [
        ("/index.html", "1.0", "daily"),
        *[(f"/rankings/{tf}.html", "0.9", "daily") for tf in TIMEFRAME_ORDER],
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
    for generated_dir in (RANKINGS_DIR, ITEMS_DIR):
        if generated_dir.exists():
            shutil.rmtree(generated_dir)
    RANKINGS_DIR.mkdir(exist_ok=True)
    ITEMS_DIR.mkdir(exist_ok=True)
    data = load_rankings()
    (ROOT / "index.html").write_text(render_home(data), encoding="utf-8")
    for tf in TIMEFRAME_ORDER:
        (RANKINGS_DIR / f"{tf}.html").write_text(render_timeframe(data, tf), encoding="utf-8")
    item_ids = {r.get("item_id") for rows in data.get("rankings", {}).values() for r in rows}
    for item_id in item_ids:
        if item_id:
            (ITEMS_DIR / f"{item_id}.html").write_text(render_item_detail(data, item_id), encoding="utf-8")
    write_seo_files(data, {str(item_id) for item_id in item_ids if item_id})
    generated = ["index.html", "robots.txt", "sitemap.xml"] + [f"rankings/{tf}.html" for tf in TIMEFRAME_ORDER]
    print(json.dumps({"site_root": str(ROOT), "generated": generated, "items": len(item_ids)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())