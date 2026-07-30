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
RANKINGS_PATH = DATA_DIR / "rankings.json"
OPS_REVIEW_PATH = DATA_DIR / "operations_review.json"
OPS_HISTORY_PATH = DATA_DIR / "operations_review_history.json"
NEXT_LOOP_FOCUS_PATH = DATA_DIR / "next_loop_focus.json"

TIMEFRAME = "weekly"
MAX_FOCUS_ITEMS = 6


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
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
    for item in previous_focus.get("focus_items", []):
        item_id = item.get("item_id")
        row = rows_by_id.get(str(item_id))
        if not row:
            continue
        baseline = item.get("baseline_source_counts") or {}
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
    queries = [
        f'"{name}" beauty supply trend',
        f'"{name}" TikTok review',
        f'"{name}" Amazon reviews',
        f'"{name}" black beauty supply',
    ]
    if "wig" in category or "hair pieces" in category:
        queries.extend([f'"{name}" install review', f'"{name}" lace wig customer review'])
    elif "braiding" in category or "crochet" in category:
        queries.extend([f'"{name}" protective styles trend', f'"{name}" knotless braids TikTok'])
    elif "tools" in category:
        queries.extend([f'"{name}" beauty supply review', f'"{name}" hair tool TikTok'])
    elif "jewelry" in category or "accessories" in category:
        queries.extend([f'"{name}" black women outfit trend', f'"{name}" wholesale beauty supply'])
    elif "lashes" in category:
        queries.extend([f'"{name}" DIY lash review', f'"{name}" lash tutorial TikTok'])
    elif "nails" in category:
        queries.extend([f'"{name}" nail inspo trend', f'"{name}" press on review'])
    elif "makeup" in category:
        queries.extend([f'"{name}" makeup review', f'"{name}" beauty supply haul'])
    elif "tools" in category:
        queries.extend([f'"{name}" beauty supply review', f'"{name}" hair tool TikTok'])
    seen = set()
    output = []
    for query in queries:
        if query not in seen:
            output.append(query)
            seen.add(query)
    return output[:6]


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
    focus = []
    for _priority, row, flags in scored[:MAX_FOCUS_ITEMS]:
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
    rows = data.get("rankings", {}).get(TIMEFRAME, [])
    if not rows:
        raise SystemExit(f"No {TIMEFRAME} rankings found at {RANKINGS_PATH}")

    cats = data.get("categories", [])
    rows_by_id = {str(row.get("item_id")): row for row in rows if row.get("item_id")}
    previous_focus = load_json(NEXT_LOOP_FOCUS_PATH, {})
    cat_stats = category_stats(rows)

    trend_items = sum(1 for row in rows if count(row, "trend_evidence") > 0)
    recent_items = sum(1 for row in rows if count(row, "recent_trend_evidence") > 0)
    retail_items = sum(1 for row in rows if count(row, "retail_product_evidence") > 0)
    tiktok_items = sum(1 for row in rows if count(row, "tiktok_shop_product_evidence") > 0)
    product_image_items = sum(1 for row in rows if row.get("image_status") != "category_visual")
    watchlist_items = sum(1 for row in rows if row.get("momentum") == "watchlist" or count(row, "trend_evidence") == 0)
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

    improvement_points = []
    if watchlist_items:
        improvement_points.append(f"{watchlist_items}개 item은 아직 published trend URL이 부족해 WATCHLIST 성격이 강합니다. trend claim으로 과장하지 말고 post/listing/thread 단위 근거를 추가 수집해야 합니다.")
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
        "metrics": {
            "items": len(rows),
            "categories": len(cats),
            "trend_items": trend_items,
            "recent_trend_items": recent_items,
            "retail_product_items": retail_items,
            "tiktok_shop_items": tiktok_items,
            "product_image_items": product_image_items,
            "watchlist_items": watchlist_items,
        },
        "category_stats": cat_stats,
        "previous_loop_follow_up": previous_focus_follow_up(previous_focus, rows_by_id),
        "good_points": good_points,
        "improvement_points": improvement_points,
        "next_loop_focus_items": next_focus_items,
        "qa_focus": qa_focus,
    }
    return review


def persist_review(review: dict[str, Any]) -> dict[str, Any]:
    save_json(OPS_REVIEW_PATH, review)

    history = load_json(OPS_HISTORY_PATH, {"runs": []})
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--playwright-summary", default="", help="Human-readable Playwright result line from the just-completed QA run.")
    args = parser.parse_args()

    review = build_review(args.playwright_summary)
    next_focus = persist_review(review)
    print(json.dumps({
        "status": "reviewed",
        "review_path": str(OPS_REVIEW_PATH),
        "history_path": str(OPS_HISTORY_PATH),
        "next_focus_path": str(NEXT_LOOP_FOCUS_PATH),
        "metrics": review["metrics"],
        "good_points": review["good_points"][:3],
        "improvement_points": review["improvement_points"][:3],
        "next_focus_items": [item.get("item_name") for item in next_focus.get("focus_items", [])],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
