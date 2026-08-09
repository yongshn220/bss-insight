#!/usr/bin/env python3
"""Post-QA review and next-loop focus generator for BSS item rankings.

This script runs after the production build and Playwright e2e QA pass. It does
not make market claims; it reviews the latest generated ranking data for:
- what worked well,
- what should be improved,
- which focused queries/items should be applied on the next collection loop.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import urllib.parse
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PUBLIC_DATA_DIR = ROOT / "public" / "data"
RANKINGS_PATH = DATA_DIR / "rankings.json"
OPS_REVIEW_PATH = DATA_DIR / "operations_review.json"
OPS_HISTORY_PATH = DATA_DIR / "operations_review_history.json"
NEXT_LOOP_FOCUS_PATH = DATA_DIR / "next_loop_focus.json"
COLLECTION_NOTES_PATH = DATA_DIR / "collection_notes.json"
MARKETING_BACKLOG_PATH = DATA_DIR / "marketing_backlog.json"
GROWTH_GOAL_PATH = DATA_DIR / "growth_goal.json"
PUBLIC_OPS_REVIEW_PATH = PUBLIC_DATA_DIR / "operations_review_public.json"
PUBLIC_NEXT_LOOP_FOCUS_PATH = PUBLIC_DATA_DIR / "next_loop_focus_public.json"

TIMEFRAME = "weekly"
MAX_FOCUS_ITEMS = 6
SITE_BASE = "https://gnsresearchhub.vercel.app"


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def count(row: dict[str, Any], key: str) -> int:
    try:
        return int((row.get("source_counts") or {}).get(key) or 0)
    except Exception:
        return 0


def has_trend_evidence(row: dict[str, Any]) -> bool:
    """Return true only when the ranking row has published/date-bearing trend evidence."""
    return bool(count(row, "trend_evidence") or count(row, "news_magazine"))


def evidence_status_label(row: dict[str, Any]) -> str:
    """Human-readable evidence label for marketing drafts without inflating WATCHLIST rows."""
    trend_count = count(row, "trend_evidence") or count(row, "news_magazine")
    if trend_count:
        return f"{trend_count} published trend URL(s)"
    return "WATCHLIST · evidence insufficient"


def growth_campaign_url(path: str, *, source: str, medium: str, campaign: str, **extra: object) -> str:
    params = {"utm_source": source, "utm_medium": medium, "utm_campaign": campaign}
    for key, value in extra.items():
        if value not in (None, ""):
            params[key] = str(value)
    return f"{SITE_BASE}{path}?{urllib.parse.urlencode(params)}"


def item_quality_flags(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if count(row, "trend_evidence") == 0:
        flags.append("published trend URL 부족")
    if count(row, "recent_trend_evidence") == 0:
        flags.append("최근 14일 발행 근거 부족")
    if count(row, "retail_product_evidence") == 0:
        flags.append("BSS/marketplace live product URL 부족")
    if count(row, "unique_domains") <= 1:
        flags.append("source/domain 다양성 낮음")
    if row.get("image_status") == "category_visual":
        flags.append("상품 이미지가 category placeholder")
    if row.get("momentum") == "watchlist":
        flags.append("WATCHLIST 상태 유지")
    return flags


def category_stats(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("category_name") or row.get("category_id") or "Uncategorized")].append(row)
    stats = []
    for category, cat_rows in sorted(grouped.items()):
        total = len(cat_rows)
        trend = sum(1 for row in cat_rows if count(row, "trend_evidence") > 0)
        retail = sum(1 for row in cat_rows if count(row, "retail_product_evidence") > 0)
        product_images = sum(1 for row in cat_rows if row.get("image_status") != "category_visual")
        stats.append({
            "category": category,
            "items": total,
            "trend_items": trend,
            "retail_items": retail,
            "product_image_items": product_images,
            "trend_ratio": round(trend / total, 2) if total else 0,
            "retail_ratio": round(retail / total, 2) if total else 0,
            "product_image_ratio": round(product_images / total, 2) if total else 0,
        })
    return stats


def previous_focus_follow_up(previous_focus: dict[str, Any], rows_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    follow_up = []
    focus_items = previous_focus.get("focus_items", []) if isinstance(previous_focus, dict) else []
    if not isinstance(focus_items, list):
        return []
    for item in focus_items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("item_id")
        row = rows_by_id.get(str(item_id))
        if not row:
            continue
        baseline = item.get("baseline_source_counts") or {}
        if not isinstance(baseline, dict):
            baseline = {}
        current = row.get("source_counts") or {}
        current_trend = count(row, "trend_evidence")
        baseline_trend = int(baseline.get("trend_evidence") or 0)
        current_retail = count(row, "retail_product_evidence")
        baseline_retail = int(baseline.get("retail_product_evidence") or 0)
        improved = current_trend > baseline_trend or current_retail > baseline_retail
        follow_up.append({
            "item_id": item_id,
            "item_name": row.get("item_name"),
            "status": "improved" if improved else "still_needs_focus",
            "baseline": baseline,
            "current": current,
            "note": "이전 loop focus 후 근거 수가 개선되었습니다." if improved else "아직 근거 보강이 필요합니다. 다음 loop focus에 유지할 수 있습니다.",
        })
    return follow_up[:MAX_FOCUS_ITEMS]


def query_variants(row: dict[str, Any]) -> list[str]:
    name = str(row.get("item_name") or "").strip()
    category = str(row.get("category_name") or "").lower()
    if not name:
        return []
    # The collector treats generated/search queries as probes only; a result must
    # still resolve to a dated, item-relevant URL before it can affect ranking.
    # Mix exact phrases with looser item-type language so zero-trend categories do
    # not get stuck on over-narrow searches forever.
    queries = [
        f'"{name}" beauty supply trend',
        f'{name} 2026 trend',
        f'{name} customer review 2026',
        f'"{name}" black beauty supply',
    ]
    if "wig" in category or "hair pieces" in category:
        queries.extend([f'{name} wig install trend', f'{name} natural hair review'])
    elif "braiding" in category or "crochet" in category:
        queries.extend([f'{name} protective style trend', f'{name} knotless braids review'])
    elif "tools" in category:
        queries.extend([f'{name} wig install accessory review', f'{name} beauty supply accessory'])
    elif "jewelry" in category or "accessories" in category:
        queries.extend([f'{name} outfit trend black women', f'{name} body jewelry trend'])
    elif "lashes" in category:
        queries.extend([f'{name} DIY lash review', f'{name} lash tutorial trend'])
    elif "nails" in category:
        queries.extend([f'{name} press-on nail trend', f'{name} nail design review'])
    elif "makeup" in category:
        queries.extend([f'{name} makeup review', f'{name} beauty supply haul'])
    seen = set()
    output = []
    for query in queries:
        if query not in seen:
            output.append(query)
            seen.add(query)
    return output[:6]


def previous_history_run(current_generated_at: object) -> dict[str, Any]:
    """Return the most recent prior review with a different ranking snapshot."""
    history = load_json(OPS_HISTORY_PATH, {"runs": []})
    runs = history.get("runs", []) if isinstance(history, dict) else []
    if not isinstance(runs, list):
        return {}
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("source_generated_at") != current_generated_at:
            return run
    return {}


def metric_deltas(current: dict[str, int], previous: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Compare coverage metrics to the previous loop so material changes are visible."""
    deltas: dict[str, dict[str, int]] = {}
    for key in [
        "trend_items",
        "recent_trend_items",
        "retail_product_items",
        "tiktok_shop_items",
        "product_image_items",
        "watchlist_items",
    ]:
        try:
            prev_value = int(previous.get(key) or 0)
        except Exception:
            continue
        current_value = int(current.get(key) or 0)
        deltas[key] = {
            "previous": prev_value,
            "current": current_value,
            "delta": current_value - prev_value,
        }
    return deltas


def coverage_change_labels(coverage_deltas: dict[str, dict[str, int]]) -> tuple[list[str], list[str]]:
    """Return (improvements, regressions) with watchlist direction handled correctly.

    For most coverage metrics, a positive delta is good and a negative delta is a
    regression. WATCHLIST is the inverse: fewer watchlist-only items is progress,
    while an increase means more items lack published/date-bearing trend evidence.
    """
    label_map = {
        "trend_items": "published trend item coverage",
        "recent_trend_items": "recent trend item coverage",
        "retail_product_items": "live product coverage",
        "tiktok_shop_items": "TikTok Shop supply coverage",
        "product_image_items": "product image coverage",
        "watchlist_items": "WATCHLIST item count",
    }
    improvements: list[str] = []
    regressions: list[str] = []
    for key, delta in coverage_deltas.items():
        if not isinstance(delta, dict):
            continue
        try:
            change = int(delta.get("delta") or 0)
        except Exception:
            continue
        if change == 0:
            continue
        label = label_map.get(key, key)
        note = f"{label} {delta.get('previous')}→{delta.get('current')} ({change:+d})"
        if key == "watchlist_items":
            (improvements if change < 0 else regressions).append(note)
        else:
            (improvements if change > 0 else regressions).append(note)
    return improvements, regressions


def material_change_notes(coverage_deltas: dict[str, dict[str, int]]) -> list[str]:
    improvements, regressions = coverage_change_labels(coverage_deltas)
    notes = []
    notes.extend(f"Improved: {note}" for note in improvements)
    notes.extend(f"Needs recovery: {note}" for note in regressions)
    return notes or ["No material coverage movement versus previous distinct ranking snapshot; measurement pending."]


def independent_ai_review(
    metrics: dict[str, int],
    cat_stats: list[dict[str, Any]],
    coverage_deltas: dict[str, dict[str, int]],
    collection_notes: dict[str, Any],
) -> dict[str, Any]:
    """Structured operator review beyond baseline counts.

    This remains deterministic so it can run unattended, but it records the same
    questions the AI operator should ask every loop: what blocks BSS owner trust,
    what blocks the 500/day growth goal, and what should the next run change.
    """
    item_count = max(1, int(metrics.get("items") or 0))
    trend_items = int(metrics.get("trend_items") or 0)
    recent_items = int(metrics.get("recent_trend_items") or 0)
    retail_items = int(metrics.get("retail_product_items") or 0)
    tiktok_items = int(metrics.get("tiktok_shop_items") or 0)
    image_items = int(metrics.get("product_image_items") or 0)
    watchlist_items = int(metrics.get("watchlist_items") or 0)
    zero_trend_categories = [
        str(stat.get("category"))
        for stat in cat_stats
        if isinstance(stat, dict) and int(stat.get("trend_items") or 0) == 0
    ]
    material_improvements, regressions = coverage_change_labels(coverage_deltas)
    evidence_totals = collection_notes.get("evidence_totals", {}) if isinstance(collection_notes, dict) else {}
    source_health = collection_notes.get("source_health", {}) if isinstance(collection_notes, dict) else {}
    apify = source_health.get("apify_tiktok_shop", {}) if isinstance(source_health, dict) else {}
    apify_status = apify.get("status") if isinstance(apify, dict) else "unknown"

    primary_growth_blockers = [
        "Central analytics export is still unavailable, so rolling 30-day average daily visits and component conversion rates cannot be calculated in this runtime.",
        f"WATCHLIST remains high: {watchlist_items}/{item_count} weekly items lack published/date-bearing trend evidence and should not be marketed as trend-backed.",
    ]
    if zero_trend_categories:
        primary_growth_blockers.append("Zero weekly trend-evidence categories: " + ", ".join(zero_trend_categories[:4]) + ".")
    if regressions:
        primary_growth_blockers.append("Coverage regression detected: " + "; ".join(regressions) + ".")
    if apify_status not in {"success", "success_empty", None}:
        primary_growth_blockers.append(f"TikTok Shop collector status requires attention: {apify_status}.")

    good_points = [
        f"Item specificity preserved: {item_count} concrete BSS item types across {metrics.get('categories')} store-like categories.",
        f"Supply/actionability coverage: retail {retail_items}/{item_count}, TikTok Shop {tiktok_items}/{item_count}, product images {image_items}/{item_count}.",
        "Search/watchlist URLs remain separated from scoring evidence; published URLs drive trend movement only.",
    ]
    if recent_items:
        good_points.append(f"Fresh weekly trend evidence exists for {recent_items} item(s), keeping Top 3 from being supply-only.")
    if material_improvements:
        good_points.append("Material coverage progress: " + "; ".join(material_improvements[:3]) + ".")

    next_direction = [
        "Connect GA4 Data API or Vercel Analytics export so growth_section_view, growth_engagement_summary, growth_click, and share/copy events can be tied to the 500/day visit goal.",
        "Prioritize dated item-level source capture for Wigs, Tools, Nails, and Jewelry before expanding broad category claims.",
        "Keep product/listing alias probes strict: recover missing supply URLs, but never promote those URLs into trend movement without a dated post/article/listing signal.",
    ]
    if int(evidence_totals.get("items_with_retail_product_url") or 0) < int(evidence_totals.get("items_requested") or item_count):
        next_direction.append("Recover missing retail/social-commerce supply coverage before the next share push, because blank images/source chips reduce owner trust.")

    scorecards = {
        "ui_ux": {
            "score": 88 if image_items == item_count else 82,
            "reason": "Store-like cards, quick picks, owner brief, and share kits are present; score is capped if any item falls back to a category visual.",
        },
        "structure_architecture": {
            "score": 86,
            "reason": "Static build/test/deploy pipeline is maintainable and public JSON is sanitized, but ranking/review logic is still concentrated in large Python scripts.",
        },
        "stability_security": {
            "score": 90 if not regressions else 84,
            "reason": "Secrets are not exposed and source health is redacted; score drops when source coverage regresses or upstream collectors need recovery.",
        },
        "goal_fit_growth": {
            "score": 70 if trend_items < item_count // 3 else 76,
            "reason": "Growth instrumentation and share paths are active, but analytics export is missing and most weekly items are still WATCHLIST.",
        },
    }
    return {
        "review_type": "independent_ai_operator_review",
        "primary_growth_blockers": primary_growth_blockers,
        "good_points": good_points,
        "remaining_issues": [
            f"Published trend evidence coverage is {trend_items}/{item_count}; recent 14d coverage is {recent_items}/{item_count}.",
            f"Zero-trend category count: {len(zero_trend_categories)}.",
            "Traffic progress is measurement pending until a provider reporting credential/export is connected.",
        ],
        "next_direction": next_direction,
        "scorecards": scorecards,
        "discipline": "Generated search/watchlist links are not scoring evidence. BSS/wholesale/TikTok Shop product URLs validate supply/actionability only.",
    }


def focus_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored: list[tuple[tuple[int, int, int, int, int], dict[str, Any], list[str]]] = []
    for row in rows:
        flags = item_quality_flags(row)
        if not flags:
            continue
        priority = (
            1 if count(row, "trend_evidence") == 0 else 0,
            1 if count(row, "retail_product_evidence") == 0 else 0,
            1 if row.get("image_status") == "category_visual" else 0,
            1 if row.get("momentum") == "watchlist" else 0,
            -int(row.get("rank") or 999),
        )
        scored.append((priority, row, flags))
    scored.sort(key=lambda item: item[0], reverse=True)

    # Independent QA lesson: pure rank-based focus kept selecting the same top
    # watchlist lane and missed zero-trend categories such as Jewelry/Nails.
    # Seed next-loop focus with the weakest categories first, then fill by rank.
    by_category: dict[str, list[tuple[tuple[int, int, int, int, int], dict[str, Any], list[str]]]] = defaultdict(list)
    category_totals: dict[str, int] = defaultdict(int)
    category_trend: dict[str, int] = defaultdict(int)
    for row in rows:
        category = str(row.get("category_name") or row.get("category_id") or "Uncategorized")
        category_totals[category] += 1
        if count(row, "trend_evidence") > 0:
            category_trend[category] += 1
    for entry in scored:
        _priority, row, _flags = entry
        category = str(row.get("category_name") or row.get("category_id") or "Uncategorized")
        by_category[category].append(entry)

    selected: list[tuple[tuple[int, int, int, int, int], dict[str, Any], list[str]]] = []
    selected_ids: set[str] = set()
    weak_categories = sorted(
        by_category,
        key=lambda category: (
            category_trend.get(category, 0) / max(1, category_totals.get(category, 1)),
            -len(by_category.get(category, [])),
            category,
        ),
    )
    for category in weak_categories:
        if len(selected) >= MAX_FOCUS_ITEMS:
            break
        entries = by_category.get(category) or []
        if category_trend.get(category, 0) > 0 and selected:
            continue
        for entry in entries:
            item_id = str(entry[1].get("item_id"))
            if item_id not in selected_ids:
                selected.append(entry)
                selected_ids.add(item_id)
                break
    for entry in scored:
        if len(selected) >= MAX_FOCUS_ITEMS:
            break
        item_id = str(entry[1].get("item_id"))
        if item_id in selected_ids:
            continue
        selected.append(entry)
        selected_ids.add(item_id)

    focus = []
    for _priority, row, flags in selected[:MAX_FOCUS_ITEMS]:
        focus.append({
            "item_id": row.get("item_id"),
            "item_name": row.get("item_name"),
            "category": row.get("category_name"),
            "rank": row.get("rank"),
            "reason": ", ".join(flags[:4]),
            "queries": query_variants(row),
            "baseline_source_counts": row.get("source_counts") or {},
        })
    return focus


def build_review(playwright_summary: str) -> dict[str, Any]:
    data = load_json(RANKINGS_PATH, {})
    if not isinstance(data, dict):
        data = {}
    rankings = data.get("rankings", {})
    rows = rankings.get(TIMEFRAME, []) if isinstance(rankings, dict) else []
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    if not rows:
        raise SystemExit(f"No {TIMEFRAME} rankings found at {RANKINGS_PATH}")

    cats = data.get("categories", [])
    cats = cats if isinstance(cats, list) else []
    rows_by_id = {str(row.get("item_id")): row for row in rows if row.get("item_id")}
    previous_focus = load_json(NEXT_LOOP_FOCUS_PATH, {})
    collection_notes = load_json(COLLECTION_NOTES_PATH, {})
    if not isinstance(collection_notes, dict):
        collection_notes = {}
    source_health = collection_notes.get("source_health", {}) if isinstance(collection_notes, dict) else {}
    source_health = source_health if isinstance(source_health, dict) else {}
    apify_health = source_health.get("apify_tiktok_shop", {}) if isinstance(source_health, dict) else {}
    apify_health = apify_health if isinstance(apify_health, dict) else {}
    cat_stats = category_stats(rows)

    trend_items = sum(1 for row in rows if count(row, "trend_evidence") > 0)
    recent_items = sum(1 for row in rows if count(row, "recent_trend_evidence") > 0)
    retail_items = sum(1 for row in rows if count(row, "retail_product_evidence") > 0)
    tiktok_items = sum(1 for row in rows if count(row, "tiktok_shop_product_evidence") > 0)
    product_image_items = sum(1 for row in rows if row.get("image_status") != "category_visual")
    watchlist_items = sum(1 for row in rows if row.get("momentum") == "watchlist" or count(row, "trend_evidence") == 0)
    current_metrics = {
        "items": len(rows),
        "categories": len(cats),
        "trend_items": trend_items,
        "recent_trend_items": recent_items,
        "retail_product_items": retail_items,
        "tiktok_shop_items": tiktok_items,
        "product_image_items": product_image_items,
        "watchlist_items": watchlist_items,
    }
    previous_run = previous_history_run(data.get("generated_at"))
    previous_metrics = previous_run.get("metrics", {}) if isinstance(previous_run, dict) else {}
    coverage_deltas = metric_deltas(current_metrics, previous_metrics if isinstance(previous_metrics, dict) else {})
    material_changes = material_change_notes(coverage_deltas)
    previous_collection = previous_run.get("collection_health", {}) if isinstance(previous_run, dict) else {}
    previous_source_health = previous_collection.get("source_health", {}) if isinstance(previous_collection, dict) else {}
    previous_apify = previous_source_health.get("apify_tiktok_shop", {}) if isinstance(previous_source_health, dict) else {}
    if isinstance(previous_apify, dict) and previous_apify:
        current_cached_items = int(apify_health.get("partial_cached_items") or 0)
        previous_cached_items = int(previous_apify.get("partial_cached_items") or 0)
        current_fresh_urls = int(apify_health.get("fresh_evidence_urls") or 0)
        previous_fresh_urls = int(previous_apify.get("fresh_evidence_urls") or 0)
        source_change_notes = []
        if previous_cached_items and current_cached_items < previous_cached_items:
            source_change_notes.append(
                "Improved: TikTok Shop cache fallback recovered "
                f"{previous_cached_items}→{current_cached_items} item(s); fresh URLs {previous_fresh_urls}→{current_fresh_urls}"
            )
        elif apify_health.get("status") != previous_apify.get("status"):
            source_change_notes.append(
                "Source health changed: TikTok Shop collector "
                f"{previous_apify.get('status')}→{apify_health.get('status')}"
            )
        if source_change_notes:
            if len(material_changes) == 1 and str(material_changes[0]).startswith("No material coverage movement"):
                material_changes = []
            material_changes.extend(source_change_notes)
    top3 = rows[:3]
    weakest_category = min(cat_stats, key=lambda item: (item["trend_ratio"], item["retail_ratio"], item["product_image_ratio"]))

    good_points = [
        f"Playwright QA 완료: {playwright_summary or 'e2e run completed'}",
        f"{len(rows)}개 item / {len(cats)}개 category ranking이 production build 기준으로 생성되었습니다.",
        f"Top 3가 item-level로 정렬되었습니다: " + ", ".join(f"#{r.get('rank')} {r.get('item_name')}" for r in top3),
        f"Evidence separation 유지: published trend URL 보유 item {trend_items}개, BSS/marketplace live product URL 보유 item {retail_items}개.",
    ]
    if tiktok_items:
        good_points.append(f"TikTok Shop/marketplace supply signal이 {tiktok_items}개 item에 붙어 social-commerce availability 확인이 강화되었습니다.")
    if product_image_items:
        good_points.append(f"상품/출처 이미지가 {product_image_items}개 item에 연결되어 text-only dashboard 위험을 줄였습니다.")
    if apify_health.get("status") == "success":
        good_points.append(
            "TikTok Shop collector health: "
            f"success, attempts {apify_health.get('attempts')}, evidence URLs {apify_health.get('evidence_urls')}."
        )

    improvement_points = []
    if watchlist_items:
        improvement_points.append(f"{watchlist_items}개 item은 아직 published trend URL이 부족해 WATCHLIST 성격이 강합니다. trend claim으로 과장하지 말고 post/listing/thread 단위 근거를 추가 수집해야 합니다.")
    if apify_health and apify_health.get("status") not in {"success"}:
        error_summary = apify_health.get("error_summary") or apify_health.get("reason") or "no error summary"
        improvement_points.append(
            "TikTok Shop collector health: "
            f"status={apify_health.get('status')} attempts={apify_health.get('attempts', 0)}. "
            f"다음 run에서 source outage/actor upstream 상태를 먼저 확인해야 합니다. ({error_summary})"
        )
    regression_labels = {
        "trend_items": "published trend item",
        "recent_trend_items": "recent trend item",
        "retail_product_items": "live product item",
        "tiktok_shop_items": "TikTok Shop item",
        "product_image_items": "product image item",
    }
    regressions = []
    for key, label in regression_labels.items():
        delta = coverage_deltas.get(key, {}).get("delta", 0)
        if delta < 0:
            values = coverage_deltas.get(key, {})
            regressions.append(f"{label} {values.get('previous')}→{values.get('current')} ({delta})")
    watchlist_delta = coverage_deltas.get("watchlist_items", {}).get("delta", 0)
    if regressions:
        improvement_points.append("이전 run 대비 coverage regression 감지: " + "; ".join(regressions) + ". 다음 loop에서는 source outage/collector query/retail suggest coverage를 우선 확인해야 합니다.")
    if watchlist_delta > 0:
        values = coverage_deltas.get("watchlist_items", {})
        improvement_points.append(f"WATCHLIST item이 이전 run 대비 증가했습니다: {values.get('previous')}→{values.get('current')} (+{watchlist_delta}). trend claim 확대보다 근거 보강이 우선입니다.")
    if recent_items < max(3, len(rows) // 5):
        improvement_points.append(f"최근 14일 발행 근거 보유 item이 {recent_items}개로 낮습니다. weekly view는 recency가 핵심이므로 신선한 article/post URL capture가 필요합니다.")
    if retail_items < len(rows):
        improvement_points.append(f"live product URL이 없는 item이 {len(rows) - retail_items}개 있습니다. BSS online store/marketplace listing 보강이 필요합니다.")
    if product_image_items < len(rows):
        improvement_points.append(f"{len(rows) - product_image_items}개 item은 category placeholder visual입니다. product/listing image 또는 더 구체적인 visual source가 필요합니다.")
    improvement_points.append(
        f"근거가 가장 약한 category: {weakest_category['category']} "
        f"(trend {weakest_category['trend_items']}/{weakest_category['items']}, "
        f"retail {weakest_category['retail_items']}/{weakest_category['items']})."
    )

    next_focus_items = focus_candidates(rows)
    qa_focus = [
        "다음 Playwright QA에서 operations_review.json/next_loop_focus.json 생성 여부를 smoke check에 포함합니다.",
        "ranking card click-through뿐 아니라 top focus item detail page의 source groups와 image metadata를 확인합니다.",
        "mobile viewport에서 category chip/sticky nav가 review/focus 변경 후에도 깨지지 않는지 확인합니다.",
    ]

    review = {
        "reviewed_at": utc_now(),
        "source_generated_at": data.get("generated_at"),
        "date": data.get("date"),
        "timeframe": TIMEFRAME,
        "playwright_summary": playwright_summary,
        "metrics": current_metrics,
        "collection_health": {
            "generated_at": collection_notes.get("generated_at"),
            "source_health": source_health,
            "evidence_totals": collection_notes.get("evidence_totals", {}),
            "source_cap_policy": collection_notes.get("source_cap_policy", {}),
            "next_actions": collection_notes.get("next_actions", []),
        },
        "category_stats": cat_stats,
        "coverage_deltas": coverage_deltas,
        "material_changes": material_changes,
        "previous_loop_follow_up": previous_focus_follow_up(previous_focus, rows_by_id),
        "good_points": good_points,
        "improvement_points": improvement_points,
        "next_loop_focus_items": next_focus_items,
        "qa_focus": qa_focus,
        "independent_ai_review": independent_ai_review(current_metrics, cat_stats, coverage_deltas, collection_notes),
    }
    return review


def persist_review(review: dict[str, Any]) -> dict[str, Any]:
    save_json(OPS_REVIEW_PATH, review)

    history = load_json(OPS_HISTORY_PATH, {"runs": []})
    if not isinstance(history, dict):
        history = {"runs": []}
    if not isinstance(history.get("runs"), list):
        history["runs"] = []
    history.setdefault("runs", []).insert(0, review)
    history["runs"] = history["runs"][:52]
    save_json(OPS_HISTORY_PATH, history)

    next_focus = {
        "updated_at": review["reviewed_at"],
        "source_review": str(OPS_REVIEW_PATH.relative_to(ROOT)),
        "reason": "Generated after Playwright QA from latest ranking strengths/gaps. collect_rankings.py reads this file on the next loop and applies focus queries to weak items.",
        "focus_items": review.get("next_loop_focus_items", []),
        "qa_focus": review.get("qa_focus", []),
    }
    save_json(NEXT_LOOP_FOCUS_PATH, next_focus)
    return next_focus


def weekly_ranking_rows() -> list[dict[str, Any]]:
    data = load_json(RANKINGS_PATH, {})
    rankings = data.get("rankings", {}) if isinstance(data, dict) else {}
    rows = rankings.get(TIMEFRAME, []) if isinstance(rankings, dict) else []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def top3_share_drafts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build current top-3 SNS drafts from live ranking rows.

    This keeps marketing artifacts aligned with the current dashboard so reps do
    not share stale item/rank copy after the collector changes the Top 3.
    """
    share_rows = [row for row in rows if has_trend_evidence(row)][:3] or rows[:3]
    drafts = []
    campaign = "daily-visits-500-weekly-top3-owner-share"
    for row in share_rows:
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            continue
        item_name = row.get("item_name") or "BSS item"
        display = row.get("display_tip") or "front-area test"
        risk = row.get("risk") or "track sell-through and shrink"
        evidence = evidence_status_label(row)
        url = growth_campaign_url(
            f"/items/{item_id}.html",
            source="x",
            medium="organic",
            campaign=campaign,
            utm_content=item_id,
            utm_term=TIMEFRAME,
        )
        drafts.append({
            "item_id": item_id,
            "item_name": item_name,
            "rank": row.get("rank"),
            "url": url,
            "x_twitter": (
                f"Beauty Supply owners: Weekly share starter — {item_name}. "
                f"Display test: {display}. Evidence status: {evidence}. {url}"
            ),
            "sales_rep_note": (
                f"Owner님, 이번 Weekly ranking #{row.get('rank')} item은 {item_name}입니다. "
                f"Display: {display}. Risk/caution: {risk}. Evidence: {evidence}."
            ),
        })
    return drafts


def current_owner_insight_post(drafts: list[dict[str, Any]]) -> str:
    if not drafts:
        return ""
    lead = drafts[0]
    return str(lead.get("x_twitter") or "")


def ensure_experiment(experiments: list[Any], experiment: dict[str, Any]) -> None:
    if not isinstance(experiments, list):
        return
    experiment_id = experiment.get("experiment_id")
    for entry in experiments:
        if isinstance(entry, dict) and entry.get("experiment_id") == experiment_id:
            entry.update(experiment)
            return
    experiments.append(experiment)


def ensure_campaign(campaigns: list[Any], campaign: dict[str, Any]) -> None:
    """Upsert a marketing/growth campaign artifact by campaign_id."""
    if not isinstance(campaigns, list):
        return
    campaign_id = campaign.get("campaign_id")
    for entry in campaigns:
        if isinstance(entry, dict) and entry.get("campaign_id") == campaign_id:
            entry.update(campaign)
            return
    campaigns.append(campaign)


def refresh_marketing_backlog(review: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    marketing = load_json(MARKETING_BACKLOG_PATH, {})
    if not isinstance(marketing, dict):
        marketing = {}
    now = str(review.get("reviewed_at") or utc_now())
    drafts = top3_share_drafts(rows)
    top3_ids = [str(draft.get("item_id")) for draft in drafts if draft.get("item_id")]
    marketing["updated_at"] = now
    marketing.setdefault("goal_id", "daily-visits-500")
    marketing.setdefault("status", "active")
    active_campaigns = marketing.setdefault("active_campaigns", [])
    if not isinstance(active_campaigns, list):
        active_campaigns = []
        marketing["active_campaigns"] = active_campaigns

    found_top3 = False
    for campaign in active_campaigns:
        if not isinstance(campaign, dict):
            continue
        campaign_id = campaign.get("campaign_id")
        if campaign_id == "top3-owner-share-strip-v1":
            found_top3 = True
            campaign["status"] = "live-on-site-after-build-current-drafts"
            campaign.setdefault("drafts", {})["x_twitter_top3_weekly"] = drafts
            campaign["last_refreshed_at"] = now
            campaign["quality_control"] = {
                "source": "data/rankings.json weekly evidence-backed top3",
                "stale_draft_guard": "Draft item_id order must match current weekly Top 3 trend-backed ranking before external posting.",
                "current_weekly_top3_item_ids": top3_ids,
            }
            campaign["tracked_quality_metrics"] = [
                "weekly_top3_current=" + ", ".join(
                    f"#{draft.get('rank')} {draft.get('item_name')}" for draft in drafts
                ),
                f"drafts refreshed at {now} from data/rankings.json after current refresh/review",
                "stale draft guard active: public marketing JSON should match live weekly Top 3 item_ids",
            ]
        elif campaign_id == "weekly-stock-this-test-v1":
            campaign.setdefault("drafts", {})["x_daily_owner_item_insight_current"] = current_owner_insight_post(drafts)
            campaign["last_refreshed_at"] = now
            campaign["tracked_quality_metrics"] = [
                "current weekly owner insight draft regenerated from live top evidence-backed item",
                f"lead_item_id={top3_ids[0] if top3_ids else 'none'}",
            ]
        elif campaign_id == "x-daily-owner-insight-v1":
            campaign["sample_post"] = current_owner_insight_post(drafts) or campaign.get("sample_post", "")
            if drafts:
                campaign["primary_item"] = {
                    "item_id": drafts[0].get("item_id"),
                    "item_name": drafts[0].get("item_name"),
                    "rank": drafts[0].get("rank"),
                    "url": drafts[0].get("url"),
                }
            campaign["last_refreshed_at"] = now

    if not found_top3:
        active_campaigns.append({
            "campaign_id": "top3-owner-share-strip-v1",
            "status": "live-on-site-after-build-current-drafts",
            "objective": "Keep item-specific owner share starters aligned with the current weekly ranking.",
            "utm_campaign_pattern": "daily-visits-500-{timeframe}-top3-owner-share",
            "drafts": {"x_twitter_top3_weekly": drafts},
            "last_refreshed_at": now,
            "quality_control": {
                "source": "data/rankings.json weekly evidence-backed top3",
                "stale_draft_guard": "Draft item_id order must match current weekly Top 3 trend-backed ranking before external posting.",
                "current_weekly_top3_item_ids": top3_ids,
            },
        })

    source_health = ((review.get("collection_health") or {}).get("source_health") or {}) if isinstance(review.get("collection_health"), dict) else {}
    apify = source_health.get("apify_tiktok_shop", {}) if isinstance(source_health, dict) else {}
    apify = apify if isinstance(apify, dict) else {}
    ensure_campaign(active_campaigns, {
        "campaign_id": "apify-sharded-fallback-v1",
        "status": "live-in-collector-resilience-after-build",
        "objective": "Recover fresh TikTok Shop social-commerce supply URLs with bounded keyword shards when the full actor payload fails, instead of silently relying only on stale cache.",
        "live_location_pattern": "https://gnsresearchhub.vercel.app/rankings/{timeframe}.html and https://gnsresearchhub.vercel.app/data/collection_notes_public.json",
        "tracked_quality_metrics": [
            f"apify_status={apify.get('status', 'unknown')}",
            f"fresh_evidence_urls={apify.get('fresh_evidence_urls', 0)}",
            f"cached_fallback_urls={apify.get('cached_evidence_urls', apify.get('partial_cached_evidence_urls', 0))}",
            f"shard_fallback_status={apify.get('shard_fallback_status', 'not_used')}",
        ],
        "owner_value": "BSS owners keep current product/listing context during upstream actor instability, while cached URLs remain explicitly labeled supply-only and never create trend movement.",
        "measurement_need": "Analytics export is still needed to connect source-health transparency and item/source-link clicks to repeat visits.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "return-visitor-prompt-v1",
        "status": "live-client-side-ux-after-build",
        "objective": "Encourage repeat BSS owner visits by revealing a concise current-ranking path only after anonymous visitor context shows a later visit.",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html",
            "https://gnsresearchhub.vercel.app/rankings/monthly.html",
            "https://gnsresearchhub.vercel.app/rankings/quarterly.html",
            "https://gnsresearchhub.vercel.app/rankings/yearly.html",
        ],
        "tracked_events": [
            "growth_return_visit_prompt",
            "growth_exposure with visible_growth_sections containing return-visitor-prompt-v1",
            "growth_click cta_return_visitor_current_ranking",
            "growth_click cta_return_visitor_all_items",
        ],
        "owner_value": "Returning owners see what to check first instead of re-reading the whole dashboard: Top 3, evidence gaps, WATCHLIST, and owner-ready display tips.",
        "measurement_need": "GA4/Vercel event export access is needed to compare repeat-visitor prompt exposure and CTA clicks against first-visit flows.",
        "last_refreshed_at": now,
    })

    experiment_backlog = marketing.setdefault("experiment_backlog", [])
    if isinstance(experiment_backlog, list):
        ensure_experiment(experiment_backlog, {
            "experiment_id": "marketing-draft-freshness-v1",
            "status": "active-data-quality-after-review",
            "hypothesis": "Current item-specific SNS/rep drafts should convert better than stale rank copy because shared links match the live dashboard Top 3.",
            "next_step": "After analytics export access is connected, compare UTM campaigns for top3 owner share links against generic weekly ranking links.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "trend-preserving-source-cap-v1",
            "status": "active-collection-quality-after-review",
            "hypothesis": "If dated published URLs are preserved ahead of same-day supply listings, shared item pages should look more credible and reduce unsupported WATCHLIST confusion.",
            "next_step": "Track items_with_published_trend_url and source_link clicks after analytics export is connected; do not treat generated search URLs as evidence.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "common-event-page-context-v1",
            "status": "active-client-side-provider-ready-after-review",
            "hypothesis": "Adding page_type, timeframe, and page_item_id to every growth event will make ranking vs. item-detail funnels measurable without relying only on path parsing.",
            "next_step": "After GA4/Vercel export access is connected, segment growth_exposure, growth_click, growth_section_view, and share/copy events by page_type/timeframe/page_item_id.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "apify-sharded-fallback-v1",
            "status": "active-collection-resilience-after-review",
            "hypothesis": "Bounded shard fallback should reduce all-cache TikTok Shop regressions after upstream full-payload failures, keeping item cards useful without inflating trend claims.",
            "next_step": "Monitor apify_status, fresh_evidence_urls, cached_fallback_urls, and source-link clicks after analytics export is connected; keep TikTok Shop evidence supply-only.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "return-visitor-prompt-v1",
            "status": "active-repeat-visit-ux-after-review",
            "hypothesis": "A concise returning-owner prompt should increase current-ranking CTA clicks and repeat visits by showing what to check first after the initial visit.",
            "next_step": "After GA4/Vercel export access is connected, segment growth_return_visit_prompt exposure, cta_return_visitor_current_ranking clicks, and is_returning_visitor traffic.",
            "last_refreshed_at": now,
        })

    save_json(MARKETING_BACKLOG_PATH, marketing)
    return {"top3_item_ids": top3_ids, "draft_count": len(drafts), "updated_at": now}


def refresh_growth_goal(review: dict[str, Any], marketing_summary: dict[str, Any]) -> dict[str, Any]:
    goal = load_json(GROWTH_GOAL_PATH, {})
    if not isinstance(goal, dict):
        goal = {}
    now = str(review.get("reviewed_at") or utc_now())
    metrics = review.get("metrics", {}) if isinstance(review.get("metrics"), dict) else {}
    material_changes = review.get("material_changes", []) if isinstance(review.get("material_changes"), list) else []
    top3_ids = marketing_summary.get("top3_item_ids", []) if isinstance(marketing_summary, dict) else []
    goal["updated_at"] = now
    measurement = goal.setdefault("measurement_status", {})
    if isinstance(measurement, dict):
        measurement["last_checked_at"] = now
        measurement["provider_checked"] = (
            "Live Vercel Web Analytics script and GA4 tag are provider-ready, but central visit export is unavailable in this runtime. "
            f"This run refreshed ranking/review metrics (weekly trend_items={metrics.get('trend_items')}, watchlist_items={metrics.get('watchlist_items')}) and regenerated top3 marketing drafts {top3_ids}."
        )
        measurement["rolling_30d_average_daily_visits"] = None
        measurement["raw_result"] = (
            "measurement pending: GA4_PROPERTY_ID plus service-account reporting access or approved Vercel Analytics export/API is still required to calculate rolling 30-day visits and component funnels."
        )
        measurement["interpretation"] = (
            "Traffic progress cannot be claimed yet. Product/share freshness improved, while visit totals remain unavailable until GA4 Data API or Vercel Analytics export access is connected. "
            + " ".join(str(note) for note in material_changes[:2])
        ).strip()

    experiments = goal.setdefault("initial_experiments", [])
    if isinstance(experiments, list):
        ensure_experiment(experiments, {
            "experiment_id": "marketing-draft-freshness-v1",
            "status": "active-data-quality-after-review",
            "variants": ["stale_static_top3_drafts", "current_ranking_synced_top3_drafts"],
            "success_metric": "UTM-attributed top3 share clicks, owner brief copies, item-detail entrances, and repeat visits once analytics export is available",
            "hypothesis": "Keeping public SNS/rep drafts synchronized with the live Top 3 will reduce dead/stale shares and improve repeat-visit quality toward 500/day.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "run-change-snapshot-v1",
            "status": "active-site-ux-after-build",
            "variants": ["hidden_refresh_status", "owner_visible_measured_change_snapshot"],
            "success_metric": "run_change_review clicks, ranking-card clicks after viewing latest-loop changes, share/copy events, and repeat visits once analytics export is available",
            "hypothesis": "BSS owners and reps will revisit/share more often when the dashboard clearly separates material evidence/source changes from routine refreshes.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "trend-preserving-source-cap-v1",
            "status": "active-collection-quality-after-build",
            "variants": ["mixed_recency_cap", "published_first_verified_source_cap"],
            "success_metric": "items_with_published_trend_url, published_trend_urls_total, weekly trend_items, WATCHLIST count, and source-link engagement once analytics export is connected",
            "hypothesis": "Preserving dated published URLs before same-day supply listings enter the per-item cap should improve evidence trust and reduce avoidable WATCHLIST labeling without counting search URLs as evidence.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "common-event-page-context-v1",
            "status": "active-client-side-provider-ready-after-build",
            "variants": ["path_only_event_context", "page_type_timeframe_item_context"],
            "success_metric": "growth_exposure, growth_click, growth_section_view, growth_engagement_summary, and share/copy events segmented by page_type, timeframe, and page_item_id once analytics export is connected",
            "hypothesis": "BSS owner growth optimization needs event context that distinguishes home, timeframe ranking, and item-detail pages without brittle URL parsing in the analytics dashboard.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "apify-sharded-fallback-v1",
            "status": "active-collection-resilience-after-build",
            "variants": ["full_payload_then_cache", "full_payload_then_bounded_keyword_shards_then_labeled_cache"],
            "success_metric": "fresh TikTok Shop URLs retained, cached fallback URLs minimized, no increase in unsupported trend claims, source-link/item-card engagement once analytics export is connected",
            "hypothesis": "Sharded actor fallback will keep BSS owner item cards current through upstream TikTok Shop collector instability while preserving evidence discipline.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "post-review-site-sync-v1",
            "status": "active-ops-quality-after-review",
            "variants": ["json_only_post_qa_review", "html_public_json_rebuilt_after_review"],
            "success_metric": "Live homepage/ranking focus cards show the same updated_at and focus items as /data/next_loop_focus_public.json; downstream focus-watchlist clicks once analytics export is connected",
            "hypothesis": "BSS owners and reps will trust the hub more when visible WATCHLIST focus cards match the latest post-QA review instead of lagging one run behind.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "return-visitor-prompt-v1",
            "status": "active-repeat-visit-ux-after-build",
            "variants": ["hidden_for_first_visit", "shown_for_returning_owner_visit"],
            "success_metric": "growth_return_visit_prompt exposures, return_visitor CTA clicks, share/copy events, and rolling 30-day repeat visits once analytics export is connected",
            "hypothesis": "Returning BSS owners should be routed directly to changed ranking/watchlist actions instead of re-reading the full dashboard, increasing repeat-use value toward 500/day.",
            "last_refreshed_at": now,
        })

    save_json(GROWTH_GOAL_PATH, goal)
    return {"updated_at": now, "top3_item_ids": top3_ids}


def refresh_growth_artifacts(review: dict[str, Any]) -> dict[str, Any]:
    rows = weekly_ranking_rows()
    marketing_summary = refresh_marketing_backlog(review, rows)
    growth_summary = refresh_growth_goal(review, marketing_summary)
    return {"marketing": marketing_summary, "growth_goal": growth_summary}


def public_review_payload(review: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized review suitable for public live verification."""
    payload = {
        key: review.get(key)
        for key in [
            "reviewed_at",
            "source_generated_at",
            "date",
            "timeframe",
            "playwright_summary",
            "metrics",
            "collection_health",
            "coverage_deltas",
            "material_changes",
            "good_points",
            "improvement_points",
            "qa_focus",
            "independent_ai_review",
        ]
        if key in review
    }
    focus_items = review.get("next_loop_focus_items")
    if isinstance(focus_items, list):
        payload["next_loop_focus_items"] = [
            {
                "item_id": item.get("item_id"),
                "item_name": item.get("item_name"),
                "category": item.get("category"),
                "rank": item.get("rank"),
                "reason": item.get("reason"),
            }
            for item in focus_items
            if isinstance(item, dict)
        ]
    follow_up = review.get("previous_loop_follow_up")
    if isinstance(follow_up, list):
        payload["previous_loop_follow_up"] = [
            {
                "item_id": item.get("item_id"),
                "item_name": item.get("item_name"),
                "status": item.get("status"),
                "note": item.get("note"),
            }
            for item in follow_up
            if isinstance(item, dict)
        ]
    return payload


def public_next_loop_focus_payload(next_focus: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: next_focus.get(key)
        for key in ["updated_at", "source_review", "reason", "qa_focus"]
        if key in next_focus
    }
    focus_items = next_focus.get("focus_items")
    if isinstance(focus_items, list):
        payload["focus_items"] = [
            {
                "item_id": item.get("item_id"),
                "item_name": item.get("item_name"),
                "category": item.get("category"),
                "rank": item.get("rank"),
                "reason": item.get("reason"),
            }
            for item in focus_items
            if isinstance(item, dict)
        ]
    return payload


def refresh_public_review(review: dict[str, Any], next_focus: dict[str, Any] | None = None) -> str:
    """Keep public/data fresh when review runs after Playwright's initial build."""
    PUBLIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Remove older full/internal public copies from earlier builds; public should
    # only expose the sanitized review, never raw next-loop query strategy.
    for stale_name in ("operations_review.json", "next_loop_focus.json"):
        stale = PUBLIC_DATA_DIR / stale_name
        if stale.exists() or stale.is_symlink():
            stale.unlink()
    save_json(PUBLIC_OPS_REVIEW_PATH, public_review_payload(review))
    if isinstance(next_focus, dict) and next_focus:
        save_json(PUBLIC_NEXT_LOOP_FOCUS_PATH, public_next_loop_focus_payload(next_focus))
    return str(PUBLIC_OPS_REVIEW_PATH)


def rebuild_site_with_post_review_artifacts() -> dict[str, Any]:
    """Rebuild static HTML after review writes next-loop/growth artifacts.

    The normal refresh/build step runs before post-QA review, so owner-facing HTML
    can otherwise show the previous loop's focus cards while the public JSON shows
    the new review. Rebuilding here keeps live pages, public data, and the next
    loop focus in the same snapshot before deploy.
    """
    commands = [
        ["python3", "scripts/build_site.py"],
        ["python3", "scripts/build_public.py"],
    ]
    results: list[dict[str, Any]] = []
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=300,
            check=True,
        )
        results.append({
            "command": " ".join(command),
            "stdout_tail": completed.stdout.strip().splitlines()[-3:],
        })
    return {
        "status": "rebuilt_after_review",
        "reason": "HTML focus/watchlist/growth sections now reflect the post-QA operations_review and next_loop_focus snapshot, not the previous run.",
        "commands": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--playwright-summary", default="", help="Human-readable Playwright result line from the just-completed QA run.")
    args = parser.parse_args()

    review = build_review(args.playwright_summary)
    next_focus = persist_review(review)
    growth_artifacts = refresh_growth_artifacts(review)
    rebuild_summary = rebuild_site_with_post_review_artifacts()
    public_review_path = refresh_public_review(review, next_focus)
    print(json.dumps({
        "status": "reviewed",
        "review_path": str(OPS_REVIEW_PATH),
        "history_path": str(OPS_HISTORY_PATH),
        "next_focus_path": str(NEXT_LOOP_FOCUS_PATH),
        "public_review_path": public_review_path,
        "growth_artifacts": growth_artifacts,
        "post_review_site_sync": rebuild_summary,
        "metrics": review["metrics"],
        "good_points": review["good_points"][:3],
        "improvement_points": review["improvement_points"][:3],
        "next_focus_items": [item.get("item_name") for item in next_focus.get("focus_items", [])],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
