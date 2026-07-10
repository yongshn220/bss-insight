#!/usr/bin/env python3
"""Build a clean store-style item ranking dashboard for BSS trend intelligence."""
from __future__ import annotations

import datetime as dt
import html
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RANKINGS_PATH = DATA_DIR / "rankings.json"
RANKINGS_DIR = ROOT / "rankings"
ITEMS_DIR = ROOT / "items"

TIMEFRAME_ORDER = ["weekly", "monthly", "quarterly", "yearly"]
TIMEFRAME_LABELS = {"weekly": "Weekly", "monthly": "Monthly", "quarterly": "Quarterly", "yearly": "Yearly"}


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


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


def shell(title: str, body: str, active: str = "weekly") -> str:
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)} · BSS Trend Ranking</title>
  <link rel="stylesheet" href="/assets/style.css">
</head>
<body>
  <header class="topbar">
    <div class="wrap navline">
      <a class="brand" href="/index.html"><span class="brand-dot"></span>BSS Trend Ranking</a>
      <nav class="tabs">{nav(active)}</nav>
    </div>
  </header>
  {body}
  <footer class="footer wrap">
    <span>Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
    <span>Verified URL evidence counted · search links are watchlists only</span>
  </footer>
</body>
</html>"""


def score_bar(score: Any) -> str:
    try:
        width = max(4, min(100, float(score)))
    except Exception:
        width = 0
    return f'<div class="scorebar"><span style="width:{width:.0f}%"></span></div>'


def evidence_chips(row: dict[str, Any]) -> str:
    counts = row.get("source_counts", {})
    chips = [
        ("Evidence", counts.get("verified_evidence", counts.get("news_magazine", 0))),
        ("Recent", counts.get("recent_evidence", 0)),
        ("Exact", counts.get("exact_evidence", 0)),
        ("Domains", counts.get("unique_domains", 0)),
        ("BSS", f'{row.get("bss_fit")}/5'),
    ]
    if row.get("seasonal_now"):
        chips.append(("Season", "Now"))
    return "".join(f'<span class="chip"><b>{esc(label)}</b>{esc(value)}</span>' for label, value in chips)


def item_card(row: dict[str, Any], compact: bool = False) -> str:
    item_url = f"/items/{esc(row.get('item_id'))}.html"
    desc = row.get("reason_summary", "")
    if compact and len(desc) > 150:
        desc = desc[:147] + "…"
    return f"""
    <article class="rank-card">
      <a class="rank-hit" href="{item_url}" aria-label="View {esc(row.get('item_name'))}"></a>
      <div class="rank-num">#{esc(row.get('rank'))}</div>
      <div class="rank-main">
        <div class="card-topline">
          <span class="category-label">{esc(row.get('category_name'))}</span>
          <span class="move {esc(row.get('momentum'))}">{esc(momentum_label(row))} · {esc(fmt_change(row.get('rank_change')))}</span>
        </div>
        <h3>{esc(row.get('item_name'))}</h3>
        <p>{esc(desc)}</p>
        <p class="change-note">{esc(row.get('change_note'))}</p>
        <div class="chips">{evidence_chips(row)}</div>
      </div>
      <div class="score-box">
        <span>Score</span>
        <strong>{esc(row.get('score'))}</strong>
        {score_bar(row.get('score'))}
      </div>
    </article>"""


def category_chips(categories: list[dict[str, Any]]) -> str:
    chips = ['<a href="#all" class="cat-chip active">All</a>']
    for cat in categories:
        chips.append(f'<a href="#{esc(cat.get("id"))}" class="cat-chip">{esc(cat.get("name"))}</a>')
    return '<nav class="category-strip">' + ''.join(chips) + '</nav>'


def top_three(rows: list[dict[str, Any]]) -> str:
    cards = []
    for row in rows[:3]:
        cards.append(f"""
        <a class="podium-card" href="/items/{esc(row.get('item_id'))}.html">
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
          <h1>Beauty Supply 제품별 트렌드 순위</h1>
          <p class="lead">검색 링크를 근거로 세지 않고, 실제 URL과 날짜가 잡힌 public evidence만 점수에 반영합니다. 근거가 부족한 항목은 trend가 아니라 WATCHLIST로 표시합니다.</p>
        </div>
        <div class="hero-panel">
          <span>Latest run</span>
          <strong>{esc(data.get('date'))}</strong>
          <small>{len(weekly)} items · {len(cats)} categories</small>
        </div>
      </section>
      <div class="wrap">{category_chips(cats)}</div>
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
    return shell("Home", body, active="weekly")


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
          <p class="lead">{esc(cfg.get('description'))}. 실제 URL 근거, 최근성, 이전 run 대비 변화를 기준으로 정렬하고, 근거 없는 항목은 watchlist로 낮춰 표시합니다.</p>
        </div>
        <div class="hero-panel">
          <span>Ranked items</span>
          <strong>{len(rows)}</strong>
          <small>{esc(data.get('date'))}</small>
        </div>
      </section>
      <div class="wrap">{category_chips(cats)}</div>
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
    return shell(f"{TIMEFRAME_LABELS.get(timeframe, timeframe.title())} Ranking", body, active=timeframe)


def grouped_sources(row: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for src in row.get("verified_evidence", row.get("news_evidence", [])):
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
        return shell("Item not found", '<main class="wrap"><h1>Item not found</h1></main>')
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
            date = src.get("published_date") or src.get("seendate") or src.get("published") or ""
            summary = src.get("summary") or src.get("snippet") or date or "Reference source"
            source_cards.append(f"""
            <a class="source-card" href="{esc(src.get('url'))}" target="_blank" rel="noreferrer">
              <span>{esc(src.get('publisher') or src.get('domain') or src.get('source_kind') or src.get('source_type'))}{' · ' + esc(date) if date else ''}</span>
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
          <span>Weekly score</span>
          <strong>{esc(row.get('score'))}</strong>
          {score_bar(row.get('score'))}
          <small>{esc(momentum_label(row))} · {esc(fmt_change(row.get('rank_change')))}</small>
        </div>
      </section>
      <section class="wrap metrics-grid">{''.join(rank_cards)}</section>
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
    return shell(row.get("item_name", "Item"), body, active="weekly")


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
    generated = ["index.html"] + [f"rankings/{tf}.html" for tf in TIMEFRAME_ORDER]
    print(json.dumps({"site_root": str(ROOT), "generated": generated, "items": len(item_ids)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())