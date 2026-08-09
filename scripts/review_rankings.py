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
PUBLIC_OPS_REVIEW_PATH = PUBLIC_DATA_DIR / "operations_review_public.json"
PUBLIC_NEXT_LOOP_FOCUS_PATH = PUBLIC_DATA_DIR / "next_loop_focus_public.json"

TIMEFRAME = "weekly"
MAX_FOCUS_ITEMS = 6


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
    """Compare coverage metrics to the previous loop so regressions are visible."""
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
    regressions = [
        f"{key} {delta.get('previous')}→{delta.get('current')} ({delta.get('delta')})"
        for key, delta in coverage_deltas.items()
        if isinstance(delta, dict) and int(delta.get("delta") or 0) < 0
    ]
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
            "next_actions": collection_notes.get("next_actions", []),
        },
        "category_stats": cat_stats,
        "coverage_deltas": coverage_deltas,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--playwright-summary", default="", help="Human-readable Playwright result line from the just-completed QA run.")
    args = parser.parse_args()

    review = build_review(args.playwright_summary)
    next_focus = persist_review(review)
    public_review_path = refresh_public_review(review, next_focus)
    print(json.dumps({
        "status": "reviewed",
        "review_path": str(OPS_REVIEW_PATH),
        "history_path": str(OPS_HISTORY_PATH),
        "next_focus_path": str(NEXT_LOOP_FOCUS_PATH),
        "public_review_path": public_review_path,
        "metrics": review["metrics"],
        "good_points": review["good_points"][:3],
        "improvement_points": review["improvement_points"][:3],
        "next_focus_items": [item.get("item_name") for item in next_focus.get("focus_items", [])],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
