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
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
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
SECRET_ENV_PATHS = [Path("/opt/data/.hermes/.env"), ROOT / ".env", ROOT / ".env.local"]

TIMEFRAME = "weekly"
TIMEFRAME_ORDER = ["weekly", "monthly", "quarterly", "yearly"]
TIMEFRAME_DAYS = {"weekly": 14, "monthly": 45, "quarterly": 120, "yearly": 365}
MAX_FOCUS_ITEMS = 8
SITE_BASE = "https://gnsresearchhub.vercel.app"
VERCEL_API_BASE = "https://api.vercel.com"
VERCEL_PROJECT_NAME = "gns_research_hub"
VISIT_GOAL_TARGET = 500
VISIT_GOAL_WINDOW_DAYS = 30


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


def env_value(name: str) -> str:
    """Read a secret/config value without echoing it to logs or reports."""
    if os.environ.get(name):
        return str(os.environ[name]).strip()
    for env_path in SECRET_ENV_PATHS:
        if not env_path.exists():
            continue
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def count(row: dict[str, Any], key: str) -> int:
    try:
        return int((row.get("source_counts") or {}).get(key) or 0)
    except Exception:
        return 0


def safe_int(value: object, default: int = 0) -> int:
    """Parse a non-sensitive integer metric without exposing raw env/secrets."""
    try:
        candidate = default if value in (None, "") else value
        return int(candidate)  # type: ignore[arg-type]
    except Exception:
        return default


def current_tiktok_cached_urls(apify: dict[str, Any], fallback: int = 0) -> int:
    """Return current-run cached TikTok Shop fallback URLs, not cache inventory."""
    if not isinstance(apify, dict):
        return max(0, fallback)
    partial = apify.get("partial_cached_evidence_urls")
    if partial not in (None, ""):
        return max(0, safe_int(partial, fallback))
    status = str(apify.get("status") or "")
    if status in {"failed_using_cache", "skipped_recent_failure_using_cache"}:
        return max(0, safe_int(apify.get("cached_evidence_urls"), fallback))
    return max(0, fallback)


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


def api_error_payload(exc: urllib.error.HTTPError) -> dict[str, Any]:
    """Return a small, secret-free HTTP error payload for measurement artifacts."""
    try:
        raw = exc.read(1000).decode("utf-8", errors="replace")
    except Exception:
        raw = ""
    message = raw[:280]
    code = "http_error"
    try:
        parsed = json.loads(raw)
        error = parsed.get("error", {}) if isinstance(parsed, dict) else {}
        if isinstance(error, dict):
            code = str(error.get("code") or code)
            message = str(error.get("message") or message)[:280]
    except Exception:
        pass
    return {"http_status": exc.code, "code": code, "message": message}


def vercel_api_get(path: str, params: dict[str, Any], token: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Call the Vercel REST API and return (json, error) without leaking tokens."""
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value not in (None, "")})
    url = f"{VERCEL_API_BASE}{path}" + (f"?{query}" if query else "")
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "GNSResearchHubCron/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return payload if isinstance(payload, dict) else {}, None
    except urllib.error.HTTPError as exc:
        return None, api_error_payload(exc)
    except Exception as exc:
        return None, {"code": type(exc).__name__, "message": str(exc)[:280]}


def discover_vercel_project_context(token: str) -> dict[str, Any]:
    """Find the Vercel project/team context from env or project listing."""
    project_id = env_value("VERCEL_ANALYTICS_PROJECT_ID") or env_value("VERCEL_PROJECT_ID")
    team_id = env_value("VERCEL_TEAM_ID") or env_value("VERCEL_ORG_ID")
    project_name = env_value("VERCEL_PROJECT_NAME") or VERCEL_PROJECT_NAME
    if project_id and team_id:
        return {"status": "env_configured", "project_id": project_id, "team_id": team_id, "project_name": project_name}

    payload, error = vercel_api_get("/v9/projects", {"limit": 100}, token)
    if error:
        return {"status": "project_lookup_failed", "error": error, "project_name": project_name}
    projects = payload.get("projects", []) if isinstance(payload, dict) else []
    if not isinstance(projects, list):
        projects = []
    for project in projects:
        if not isinstance(project, dict):
            continue
        if project.get("name") == project_name:
            return {
                "status": "project_lookup_success",
                "project_id": project.get("id") or project_id,
                "team_id": project.get("accountId") or project.get("teamId") or team_id,
                "project_name": project_name,
            }
    return {"status": "project_not_found", "project_name": project_name}


def sum_metric(rows: Any, key: str) -> int:
    if not isinstance(rows, list):
        return 0
    total = 0
    for row in rows:
        if isinstance(row, dict):
            total += safe_int(row.get(key))
    return total


def top_rows(rows: Any, keys: list[str], limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        cleaned.append({key: row.get(key) for key in keys if key in row})
    return cleaned


def vercel_group_query(
    token: str,
    project_id: str,
    team_id: str,
    since: str,
    until: str,
    by: str,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    payload, error = vercel_api_get(
        "/v1/query/web-analytics/visits/aggregate",
        {
            "projectId": project_id,
            "teamId": team_id,
            "since": since,
            "until": until,
            "limit": limit,
            "by": by,
        },
        token,
    )
    if error:
        return [], error
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else [], None


def measure_vercel_web_analytics() -> dict[str, Any]:
    """Measure the 500/day goal through Vercel Web Analytics when token access exists.

    Basic visits/pageviews are available on the current project via the Vercel REST
    API. Custom events and some UTM dimensions can be plan-gated; those blockers
    are recorded separately instead of treating the whole measurement as pending.
    """
    token = env_value("VERCEL_TOKEN")
    if not token:
        return {
            "status": "blocked_missing_vercel_token",
            "measurement_source": "vercel_web_analytics_rest_api",
            "message": "VERCEL_TOKEN is unavailable in this runtime, so Vercel Web Analytics visits cannot be queried.",
        }

    context = discover_vercel_project_context(token)
    project_id = str(context.get("project_id") or "")
    team_id = str(context.get("team_id") or "")
    if not project_id or not team_id:
        return {
            "status": "blocked_missing_project_context",
            "measurement_source": "vercel_web_analytics_rest_api",
            "project_context": context,
            "message": "Could not resolve Vercel project_id/team_id for the gns_research_hub project.",
        }

    now = dt.datetime.now(dt.UTC)
    since_dt = now - dt.timedelta(days=VISIT_GOAL_WINDOW_DAYS)
    since = since_dt.isoformat().replace("+00:00", "Z")
    until = now.isoformat().replace("+00:00", "Z")
    base_params = {"projectId": project_id, "teamId": team_id, "since": since, "until": until}

    count_payload, count_error = vercel_api_get("/v1/query/web-analytics/visits/count", base_params, token)
    if count_error:
        return {
            "status": "blocked_visits_count_error",
            "measurement_source": "vercel_web_analytics_rest_api",
            "project_context": {"status": context.get("status"), "project_name": context.get("project_name")},
            "window_days": VISIT_GOAL_WINDOW_DAYS,
            "since": since,
            "until": until,
            "error": count_error,
        }

    daily_rows, daily_error = vercel_group_query(token, project_id, team_id, since, until, "day", 100)
    path_rows, path_error = vercel_group_query(token, project_id, team_id, since, until, "requestPath", 12)
    referrer_rows, referrer_error = vercel_group_query(token, project_id, team_id, since, until, "referrerHostname", 12)
    device_rows, device_error = vercel_group_query(token, project_id, team_id, since, until, "deviceType", 12)
    utm_rows, utm_error = vercel_group_query(token, project_id, team_id, since, until, "utmSource", 12)
    event_payload, event_error = vercel_api_get(
        "/v1/query/web-analytics/events/aggregate",
        {**base_params, "limit": 20, "by": "eventName"},
        token,
    )

    count_data = count_payload.get("data", {}) if isinstance(count_payload, dict) else {}
    count_data = count_data if isinstance(count_data, dict) else {}
    daily_visitor_sum = sum_metric(daily_rows, "visitors")
    daily_pageview_sum = sum_metric(daily_rows, "pageviews")
    period_unique_visitors = safe_int(count_data.get("visitors"))
    period_pageviews = safe_int(count_data.get("pageviews"))
    if daily_visitor_sum <= 0 and period_unique_visitors:
        daily_visitor_sum = period_unique_visitors
    if daily_pageview_sum <= 0 and period_pageviews:
        daily_pageview_sum = period_pageviews

    average_daily_visits = round(daily_visitor_sum / VISIT_GOAL_WINDOW_DAYS, 2)
    average_daily_pageviews = round(daily_pageview_sum / VISIT_GOAL_WINDOW_DAYS, 2)
    return {
        "status": "measured",
        "measurement_source": "vercel_web_analytics_rest_api",
        "project_name": context.get("project_name") or VERCEL_PROJECT_NAME,
        "project_context_status": context.get("status"),
        "window_days": VISIT_GOAL_WINDOW_DAYS,
        "since": since,
        "until": until,
        "rolling_30d_average_daily_visits": average_daily_visits,
        "average_daily_pageviews": average_daily_pageviews,
        "target_average_daily_visits": VISIT_GOAL_TARGET,
        "gap_to_target_average_daily_visits": round(max(0, VISIT_GOAL_TARGET - average_daily_visits), 2),
        "target_progress_percent": round((average_daily_visits / VISIT_GOAL_TARGET) * 100, 3) if VISIT_GOAL_TARGET else 0,
        "period_unique_visitors": period_unique_visitors,
        "period_pageviews": period_pageviews,
        "daily_visitor_sum": daily_visitor_sum,
        "daily_pageview_sum": daily_pageview_sum,
        "daily_rows": top_rows(daily_rows, ["timestamp", "visitors", "pageviews"], 40),
        "top_paths": top_rows(path_rows, ["requestPath", "visitors", "pageviews"], 8),
        "top_referrers": top_rows(referrer_rows, ["referrerHostname", "visitors", "pageviews"], 8),
        "device_breakdown": top_rows(device_rows, ["deviceType", "visitors", "pageviews"], 8),
        "query_errors": {
            "daily": daily_error,
            "requestPath": path_error,
            "referrerHostname": referrer_error,
            "deviceType": device_error,
            "utmSource": utm_error,
            "customEvents": event_error,
        },
        "utm_breakdown_status": "available" if not utm_error else f"blocked_or_unavailable: {utm_error.get('code')}",
        "custom_event_status": "available" if not event_error else f"blocked_or_unavailable: {event_error.get('code')}",
        "note": "Visits/pageviews are measured centrally. Custom event and some UTM breakdown endpoints may require Vercel Pro/Enterprise or GA4 Data API access for component funnel analysis.",
    }


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
    elif "hair care" in category or "styling" in category:
        lowered_name = name.lower()
        if any(term in lowered_name for term in ("wig", "lace", "adhesive", "melting")):
            queries.extend([f'{name} wig install review', f'{name} lace install trend'])
        elif any(term in lowered_name for term in ("mousse", "braid")):
            queries.extend([f'{name} braid maintenance review', f'{name} protective style trend'])
        elif any(term in lowered_name for term in ("edge", "gel")):
            queries.extend([f'{name} edge control review', f'{name} black hair styling trend'])
        else:
            queries.extend([f'{name} natural hair review', f'{name} beauty supply haul'])
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


COLLECTION_DELTA_FIELDS: dict[tuple[str, ...], tuple[str, bool]] = {
    ("evidence_totals", "items_with_published_trend_url"): ("all-window published trend item coverage", False),
    ("evidence_totals", "published_trend_urls_total"): ("published trend URL total", False),
    ("evidence_totals", "items_with_retail_product_url"): ("all-window live product item coverage", False),
    ("evidence_totals", "items_with_tiktok_shop_url"): ("all-window TikTok Shop item coverage", False),
    ("evidence_totals", "items_with_cached_tiktok_shop_url"): ("all-window cached TikTok Shop item coverage", True),
    ("evidence_totals", "cached_tiktok_shop_urls_total"): ("cached TikTok Shop supply URL total", True),
    ("evidence_totals", "collection_error_records"): ("collection error records", True),
    ("source_health", "apify_tiktok_shop", "products_returned"): ("TikTok Shop products returned", False),
    ("source_health", "apify_tiktok_shop", "fresh_evidence_urls"): ("fresh TikTok Shop supply URLs", False),
    ("source_health", "apify_tiktok_shop", "partial_cached_items"): ("TikTok partial-cache fallback items", True),
    ("coverage_gap_summary", "published_trend_missing_items"): ("all-window missing published trend items", True),
}


def nested_int(data: dict[str, Any], path: tuple[str, ...]) -> int | None:
    """Safely read a nested integer metric from collection/review dictionaries."""
    cursor: Any = data
    for key in path:
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(key)
    if cursor in (None, ""):
        return None
    try:
        return int(cursor)
    except Exception:
        return None


def collection_evidence_deltas(
    current_collection: dict[str, Any],
    previous_collection: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Compare all-window/source-health collection metrics, not only weekly rows.

    Weekly trend_items can stay flat while the collector loses all-window dated
    coverage or social-commerce freshness. Surfacing those regressions keeps the
    closed loop from calling a routine refresh an improvement when source quality
    actually moved backward.
    """
    if not isinstance(current_collection, dict) or not isinstance(previous_collection, dict):
        return {}
    deltas: dict[str, dict[str, Any]] = {}
    for path, (label, inverse) in COLLECTION_DELTA_FIELDS.items():
        current_value = nested_int(current_collection, path)
        previous_value = nested_int(previous_collection, path)
        if current_value is None or previous_value is None:
            continue
        key = "__".join(path)
        deltas[key] = {
            "label": label,
            "previous": previous_value,
            "current": current_value,
            "delta": current_value - previous_value,
            "inverse": inverse,
        }
    return deltas


def collection_change_labels(collection_deltas: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Return (improvements, regressions) for collection/source metrics."""
    improvements: list[str] = []
    regressions: list[str] = []
    if not isinstance(collection_deltas, dict):
        return improvements, regressions
    for delta in collection_deltas.values():
        if not isinstance(delta, dict):
            continue
        try:
            change = int(delta.get("delta") or 0)
            previous = int(delta.get("previous") or 0)
            current = int(delta.get("current") or 0)
        except Exception:
            continue
        if change == 0:
            continue
        label = str(delta.get("label") or "collection metric")
        inverse = bool(delta.get("inverse"))
        note = f"{label} {previous}→{current} ({change:+d})"
        improved = change < 0 if inverse else change > 0
        (improvements if improved else regressions).append(note)
    return improvements, regressions


def material_change_notes(
    coverage_deltas: dict[str, dict[str, int]],
    collection_deltas: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    improvements, regressions = coverage_change_labels(coverage_deltas)
    collection_improvements, collection_regressions = collection_change_labels(collection_deltas or {})
    notes = []
    notes.extend(f"Improved: {note}" for note in improvements)
    notes.extend(f"Improved source: {note}" for note in collection_improvements)
    notes.extend(f"Needs recovery: {note}" for note in regressions)
    notes.extend(f"Needs source recovery: {note}" for note in collection_regressions)
    return notes or ["No material coverage movement versus previous distinct ranking snapshot; measurement pending."]


def independent_ai_review(
    metrics: dict[str, int],
    cat_stats: list[dict[str, Any]],
    coverage_deltas: dict[str, dict[str, int]],
    collection_notes: dict[str, Any],
    collection_deltas: dict[str, dict[str, Any]],
    visit_measurement: dict[str, Any] | None = None,
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
    collection_improvements, collection_regressions = collection_change_labels(collection_deltas)
    evidence_totals = collection_notes.get("evidence_totals", {}) if isinstance(collection_notes, dict) else {}
    source_health = collection_notes.get("source_health", {}) if isinstance(collection_notes, dict) else {}
    apify = source_health.get("apify_tiktok_shop", {}) if isinstance(source_health, dict) else {}
    apify_status = apify.get("status") if isinstance(apify, dict) else "unknown"
    all_window_published_items = int(evidence_totals.get("items_with_published_trend_url") or 0)
    all_window_requested_items = int(evidence_totals.get("items_requested") or item_count)

    visit_measurement = visit_measurement if isinstance(visit_measurement, dict) else {}
    visits_measured = visit_measurement.get("status") == "measured"
    avg_visits = visit_measurement.get("rolling_30d_average_daily_visits") if visits_measured else None
    target_visits = visit_measurement.get("target_average_daily_visits") or VISIT_GOAL_TARGET
    gap_to_target = visit_measurement.get("gap_to_target_average_daily_visits")
    custom_event_status = str(visit_measurement.get("custom_event_status") or "unknown")
    utm_breakdown_status = str(visit_measurement.get("utm_breakdown_status") or "unknown")

    if visits_measured:
        primary_growth_blockers = [
            (
                f"Measured traffic is far below the standing goal: {avg_visits}/day vs {target_visits}/day "
                f"(gap {gap_to_target}/day). Distribution and repeat-visit conversion remain the main growth blocker."
            ),
            f"WATCHLIST remains high: {watchlist_items}/{item_count} weekly items lack published/date-bearing trend evidence and should not be marketed as trend-backed.",
        ]
        if custom_event_status != "available" or utm_breakdown_status != "available":
            primary_growth_blockers.insert(
                1,
                (
                    "Component funnel analytics export is still blocked/gated: "
                    f"custom_event_status={custom_event_status}, utm_breakdown_status={utm_breakdown_status}. "
                    "Need GA4 Data API reporting access or Vercel custom-event/UTM export to compare owner-share, message, RSS, shortcut, calendar, category, and item-detail paths."
                ),
            )
    else:
        primary_growth_blockers = [
            (
                "Central visit measurement is unavailable in this runtime, so rolling 30-day average daily visits cannot be calculated. "
                "Component conversion rates also need GA4 Data API or Vercel custom-event/UTM analytics export."
            ),
            f"WATCHLIST remains high: {watchlist_items}/{item_count} weekly items lack published/date-bearing trend evidence and should not be marketed as trend-backed.",
        ]
    if zero_trend_categories:
        primary_growth_blockers.append("Zero weekly trend-evidence categories: " + ", ".join(zero_trend_categories[:4]) + ".")
    if regressions:
        primary_growth_blockers.append("Coverage regression detected: " + "; ".join(regressions) + ".")
    if collection_regressions:
        primary_growth_blockers.append("Collection evidence/source regression detected: " + "; ".join(collection_regressions[:4]) + ".")
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
    if collection_improvements:
        good_points.append("Collection/source progress: " + "; ".join(collection_improvements[:3]) + ".")

    next_direction = [
        (
            "Use the measured Vercel visit baseline to prioritize distribution tests, and connect GA4 Data API or Vercel custom-event/UTM export so "
            "growth_section_view, growth_engagement_summary, growth_click, and share/copy events can be tied to the 500/day visit goal."
            if visits_measured else
            "Connect Vercel Web Analytics reporting or GA4 Data API so rolling 30-day visits, growth_section_view, growth_engagement_summary, growth_click, and share/copy events can be tied to the 500/day visit goal."
        ),
        "Prioritize dated item-level source capture for Wigs, Tools, Nails, and Jewelry before expanding broad category claims.",
        "Keep product/listing alias probes strict: recover missing supply URLs, but never promote those URLs into trend movement without a dated post/article/listing signal.",
    ]
    if int(evidence_totals.get("items_with_retail_product_url") or 0) < int(evidence_totals.get("items_requested") or item_count):
        next_direction.append("Recover missing retail/social-commerce supply coverage before the next share push, because blank images/source chips reduce owner trust.")

    scorecards = {
        "ui_ux": {
            "score": 90 if image_items == item_count else 84,
            "reason": "Ranking-first layout now puts Top 3 and main item cards before support modules; score is capped if any item falls back to a category visual.",
        },
        "structure_architecture": {
            "score": 86,
            "reason": "Static build/test/deploy pipeline is maintainable and public JSON is sanitized, but ranking/review logic is still concentrated in large Python scripts.",
        },
        "stability_security": {
            "score": 90 if not (regressions or collection_regressions) else 84,
            "reason": "Secrets are not exposed and source health is redacted; score drops when weekly or all-window/source collection coverage regresses.",
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
            f"All-window published trend URL coverage is {all_window_published_items}/{all_window_requested_items}; this can regress even when weekly rank counts stay flat.",
            f"Zero-trend category count: {len(zero_trend_categories)}.",
            (
                f"Traffic is measured at {avg_visits}/day against the 500/day target, but component/UTM funnel export remains blocked."
                if visits_measured else
                "Traffic progress is measurement pending until a provider reporting credential/export is connected."
            ),
        ],
        "next_direction": next_direction,
        "scorecards": scorecards,
        "traffic_measurement_status": {
            "status": visit_measurement.get("status") or "unavailable",
            "rolling_30d_average_daily_visits": avg_visits,
            "target_average_daily_visits": target_visits,
            "gap_to_target_average_daily_visits": gap_to_target,
            "custom_event_status": custom_event_status,
            "utm_breakdown_status": utm_breakdown_status,
        },
        "discipline": "Generated search/watchlist links are not scoring evidence. BSS/wholesale/TikTok Shop product URLs validate supply/actionability only.",
    }


def missing_published_gap_ids(collection_notes: dict[str, Any] | None) -> set[str]:
    """Return item IDs with no captured published/date-bearing trend URL yet.

    This is stricter than the weekly WATCHLIST view: an item can have older
    published evidence but no 14-day evidence. For the next-loop research queue,
    true all-window published-source gaps deserve priority because they are the
    most likely to keep BSS owners from trusting an item card.
    """
    if not isinstance(collection_notes, dict):
        return set()
    gaps = collection_notes.get("coverage_gaps", {})
    gaps = gaps if isinstance(gaps, dict) else {}
    missing = gaps.get("missing_published_trend_items", [])
    if not isinstance(missing, list):
        return set()
    return {
        str(item.get("item_id"))
        for item in missing
        if isinstance(item, dict) and item.get("item_id")
    }


def focus_candidates(rows: list[dict[str, Any]], collection_notes: dict[str, Any] | None = None) -> list[dict[str, Any]]:
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
    # 2026-08 improvement: prioritize collection_notes true published-source gaps
    # before recency-only weekly WATCHLIST gaps, because these are the items with
    # no captured dated trend URL in any evidence window.
    missing_gap_ids = missing_published_gap_ids(collection_notes)
    by_category: dict[str, list[tuple[tuple[int, int, int, int, int], dict[str, Any], list[str]]]] = defaultdict(list)
    gap_by_category: dict[str, list[tuple[tuple[int, int, int, int, int], dict[str, Any], list[str]]]] = defaultdict(list)
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
        if str(row.get("item_id")) in missing_gap_ids:
            gap_by_category[category].append(entry)

    selected: list[tuple[tuple[int, int, int, int, int], dict[str, Any], list[str]]] = []
    selected_ids: set[str] = set()
    selected_focus_source: dict[str, str] = {}

    def add_entry(entry: tuple[tuple[int, int, int, int, int], dict[str, Any], list[str]], source: str) -> bool:
        if len(selected) >= MAX_FOCUS_ITEMS:
            return False
        item_id = str(entry[1].get("item_id"))
        if not item_id or item_id in selected_ids:
            return False
        selected.append(entry)
        selected_ids.add(item_id)
        selected_focus_source[item_id] = source
        return True

    weak_categories = sorted(
        by_category,
        key=lambda category: (
            category_trend.get(category, 0) / max(1, category_totals.get(category, 1)),
            -len(by_category.get(category, [])),
            category,
        ),
    )

    # First pass: one true missing-published-source gap per weak category. This
    # keeps the next loop from spending every query on items that already have
    # older evidence while Lashes/Tools/Wigs/Jewelry still have all-window gaps.
    for category in weak_categories:
        for entry in gap_by_category.get(category, []):
            if add_entry(entry, "collection_notes_missing_published_trend"):
                break
        if len(selected) >= MAX_FOCUS_ITEMS:
            break

    # If true all-window published-source gaps fit inside the expanded focus
    # queue, include the remaining gap items before recency-only WATCHLIST rows.
    # This keeps a seven-item missing_published_trend list from losing lower-rank
    # concrete gaps such as drawstring ponytails, 25mm lashes, or elastic melting
    # bands to higher-rank items that already have older dated evidence.
    for category in weak_categories:
        if len(selected) >= MAX_FOCUS_ITEMS:
            break
        for entry in gap_by_category.get(category, []):
            if add_entry(entry, "collection_notes_missing_published_trend") and len(selected) >= MAX_FOCUS_ITEMS:
                break

    # Second pass: original weak-category balancing for weekly gaps/recency gaps.
    for category in weak_categories:
        if len(selected) >= MAX_FOCUS_ITEMS:
            break
        entries = by_category.get(category) or []
        if category_trend.get(category, 0) > 0 and selected:
            continue
        for entry in entries:
            if add_entry(entry, "weekly_quality_flags"):
                break
    for entry in scored:
        if len(selected) >= MAX_FOCUS_ITEMS:
            break
        add_entry(entry, "weekly_quality_flags")

    focus = []
    for _priority, row, flags in selected[:MAX_FOCUS_ITEMS]:
        item_id = str(row.get("item_id") or "")
        focus_source = selected_focus_source.get(item_id, "weekly_quality_flags")
        is_collection_gap = focus_source == "collection_notes_missing_published_trend"
        reason_parts = list(flags[:4])
        if is_collection_gap:
            reason_parts.insert(0, "collection gap: 전체 evidence window에서 published trend URL 미확보")
        focus.append({
            "item_id": row.get("item_id"),
            "item_name": row.get("item_name"),
            "category": row.get("category_name"),
            "rank": row.get("rank"),
            "reason": ", ".join(reason_parts[:5]),
            "focus_source": focus_source,
            "collection_gap": "missing_published_trend_url" if is_collection_gap else "weekly_or_recent_evidence_gap",
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
    coverage_gaps = collection_notes.get("coverage_gaps", {}) if isinstance(collection_notes, dict) else {}
    coverage_gaps = coverage_gaps if isinstance(coverage_gaps, dict) else {}
    coverage_gap_summary = coverage_gaps.get("summary", {}) if isinstance(coverage_gaps.get("summary"), dict) else {}
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
    previous_collection = previous_run.get("collection_health", {}) if isinstance(previous_run, dict) else {}
    current_collection_health = {
        "generated_at": collection_notes.get("generated_at"),
        "source_health": source_health,
        "evidence_totals": collection_notes.get("evidence_totals", {}),
        "coverage_gap_summary": coverage_gap_summary,
        "source_cap_policy": collection_notes.get("source_cap_policy", {}),
        "next_actions": collection_notes.get("next_actions", []),
    }
    visit_measurement = measure_vercel_web_analytics()
    collection_delta_map = collection_evidence_deltas(
        current_collection_health,
        previous_collection if isinstance(previous_collection, dict) else {},
    )
    material_changes = material_change_notes(coverage_deltas, collection_delta_map)
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

    next_focus_items = focus_candidates(rows, collection_notes)
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
            **current_collection_health,
        },
        "category_stats": cat_stats,
        "traffic_measurement": visit_measurement,
        "coverage_deltas": coverage_deltas,
        "collection_evidence_deltas": collection_delta_map,
        "material_changes": material_changes,
        "previous_loop_follow_up": previous_focus_follow_up(previous_focus, rows_by_id),
        "good_points": good_points,
        "improvement_points": improvement_points,
        "next_loop_focus_items": next_focus_items,
        "qa_focus": qa_focus,
        "independent_ai_review": independent_ai_review(
            current_metrics,
            cat_stats,
            coverage_deltas,
            collection_notes,
            collection_delta_map,
            visit_measurement,
        ),
    }
    return review


def persist_review(review: dict[str, Any]) -> dict[str, Any]:
    save_json(OPS_REVIEW_PATH, review)

    history = load_json(OPS_HISTORY_PATH, {"runs": []})
    if not isinstance(history, dict):
        history = {"runs": []}
    if not isinstance(history.get("runs"), list):
        history["runs"] = []
    runs = [run for run in history.setdefault("runs", []) if isinstance(run, dict)]
    current_snapshot = str(review.get("source_generated_at") or "")
    if current_snapshot:
        runs = [run for run in runs if str(run.get("source_generated_at") or "") != current_snapshot]
    runs.insert(0, review)
    cleaned_runs: list[dict[str, Any]] = []
    seen_snapshots: set[str] = set()
    for run in runs:
        snapshot = str(run.get("source_generated_at") or "")
        if snapshot and snapshot in seen_snapshots:
            continue
        if snapshot:
            seen_snapshots.add(snapshot)
        cleaned_runs.append(run)
    history["runs"] = cleaned_runs[:52]
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


def timeframe_coverage_summary() -> list[dict[str, Any]]:
    """Summarize trend/watchlist coverage across ranking windows for growth artifacts."""
    data = load_json(RANKINGS_PATH, {})
    rankings = data.get("rankings", {}) if isinstance(data, dict) else {}
    if not isinstance(rankings, dict):
        return []
    summary: list[dict[str, Any]] = []
    for timeframe in TIMEFRAME_ORDER:
        rows = rankings.get(timeframe, [])
        if not isinstance(rows, list):
            rows = []
        valid_rows = [row for row in rows if isinstance(row, dict)]
        trend_rows = [row for row in valid_rows if has_trend_evidence(row)]
        watchlist_items = sum(
            1 for row in valid_rows
            if row.get("momentum") == "watchlist" or not has_trend_evidence(row)
        )
        top = trend_rows[0] if trend_rows else (valid_rows[0] if valid_rows else {})
        summary.append({
            "timeframe": timeframe,
            "window_days": TIMEFRAME_DAYS.get(timeframe),
            "items": len(valid_rows),
            "trend_items": len(trend_rows),
            "watchlist_items": watchlist_items,
            "top_item_id": top.get("item_id") if isinstance(top, dict) else None,
            "top_item_name": top.get("item_name") if isinstance(top, dict) else None,
        })
    return summary


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
    coverage_summary = timeframe_coverage_summary()
    coverage_labels = [
        f"{item.get('timeframe')}={item.get('trend_items')}/{item.get('items')} trend-backed, WATCHLIST {item.get('watchlist_items')}"
        for item in coverage_summary
        if isinstance(item, dict)
    ]
    metrics = review.get("metrics", {}) if isinstance(review.get("metrics"), dict) else {}
    collection_delta_map = review.get("collection_evidence_deltas", {}) if isinstance(review.get("collection_evidence_deltas"), dict) else {}
    collection_improvements, collection_regressions = collection_change_labels(collection_delta_map)
    category_ids = sorted({
        str(row.get("category_id") or "")
        for row in rows
        if isinstance(row, dict) and row.get("category_id")
    })
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

    lead_item_id = top3_ids[0] if top3_ids else "none"
    ensure_campaign(active_campaigns, {
        "campaign_id": "hero-owner-share-nudge-v1",
        "status": "live-homepage-first-viewport-after-build",
        "objective": "Move one evidence-backed owner/reps share action into the first viewport so low-traffic sessions can copy or open an item before scrolling to deeper share modules.",
        "utm_campaign": "daily-visits-500-weekly-hero-owner-share-nudge",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html (hero-owner-share-nudge-v1)",
        ],
        "tracked_events": [
            "growth_section_view hero-owner-share-nudge-v1",
            "growth_click cta_hero_owner_nudge_item with utm_medium=hero_owner_nudge",
            "growth_click share_weekly_hero_owner_text_copy",
            "growth_share_copy_result share_action=weekly_hero_owner_text_copy",
            "growth_native_share_result share_action=weekly_hero_owner_native_share",
        ],
        "tracked_quality_metrics": [
            f"lead_item_id={lead_item_id}",
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            "owner quick text uses evidence_status_label and does not create new trend claims",
        ],
        "owner_value": "A busy BSS owner or GNS rep can immediately open/copy the current lead item with display/risk/evidence status without finding the lower share kit.",
        "measurement_need": "GA4 Data API or Vercel custom-event export is needed to compare hero-owner-share-nudge exposures/copy/open events against deeper owner-share-kit and top3 share modules.",
        "last_refreshed_at": now,
    })

    source_health = ((review.get("collection_health") or {}).get("source_health") or {}) if isinstance(review.get("collection_health"), dict) else {}
    apify = source_health.get("apify_tiktok_shop", {}) if isinstance(source_health, dict) else {}
    apify = apify if isinstance(apify, dict) else {}
    apify_current_cached_urls = current_tiktok_cached_urls(apify)
    ensure_campaign(active_campaigns, {
        "campaign_id": "apify-sharded-fallback-v1",
        "status": "live-in-collector-resilience-after-build",
        "objective": "Recover fresh TikTok Shop social-commerce supply URLs with bounded keyword shards when the full actor payload fails, instead of silently relying only on stale cache.",
        "live_location_pattern": "https://gnsresearchhub.vercel.app/rankings/{timeframe}.html and https://gnsresearchhub.vercel.app/data/collection_notes_public.json",
        "tracked_quality_metrics": [
            f"apify_status={apify.get('status', 'unknown')}",
            f"fresh_evidence_urls={apify.get('fresh_evidence_urls', 0)}",
            f"cached_fallback_urls={apify_current_cached_urls}",
            f"shard_fallback_status={apify.get('shard_fallback_status', 'not_used')}",
        ],
        "owner_value": "BSS owners keep current product/listing context during upstream actor instability, while cached URLs remain explicitly labeled supply-only and never create trend movement.",
        "measurement_need": "Analytics export is still needed to connect source-health transparency and item/source-link clicks to repeat visits.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "apify-failure-cooldown-v1",
        "status": "live-collector-resilience-after-build",
        "objective": "Avoid repeated TikTok Shop actor/shard retries immediately after a fresh upstream failure when a same-day cache is already available, while keeping cached URLs labeled supply-only.",
        "live_location_pattern": "https://gnsresearchhub.vercel.app/data/collection_notes_public.json and evidence snapshot source-health cell",
        "tracked_quality_metrics": [
            f"apify_status={apify.get('status', 'unknown')}",
            f"failure_cooldown_minutes={apify.get('cooldown_minutes', 'default_or_not_active')}",
            f"cooldown_remaining_minutes={apify.get('cooldown_remaining_minutes', 0)}",
            f"last_actor_failure_observed_at={apify.get('last_actor_failure_observed_at', '')}",
            f"cached_fallback_urls={apify_current_cached_urls}",
        ],
        "owner_value": "The dashboard stays fast and honest during upstream TikTok Shop instability: owners still see cached product availability, but source freshness is visibly marked as recovery work rather than trend evidence.",
        "measurement_need": "Track whether cooldown runs reduce failed actor time/quota without increasing stale cache age; analytics export is still needed for downstream visit/click impact.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "tiktok-source-health-label-v1",
        "status": "live-site-trust-ux-after-build",
        "objective": "Make TikTok Shop source freshness readable at a glance by separating Fresh and Cached counts in the evidence snapshot and labeling cached fallback as supply-only.",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html (evidence-gap-transparency-v1)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (TikTok Shop freshness cell)",
            "https://gnsresearchhub.vercel.app/data/collection_notes_public.json",
        ],
        "tracked_events": [
            "growth_section_view evidence-gap-transparency-v1",
            "growth_click cta_evidence_snapshot_review",
        ],
        "tracked_quality_metrics": [
            f"apify_status={apify.get('status', 'unknown')}",
            f"fresh_evidence_urls={apify.get('fresh_evidence_urls', 0)}",
            f"cached_supply_urls={apify_current_cached_urls}",
            "cache_inventory_urls="
            f"{apify.get('cached_evidence_urls', 0)} (available fallback pool; not current usage)",
            "source-health cell exposes data-source-health-status, data-fresh-urls, and data-cached-urls for QA/live smoke checks",
        ],
        "owner_value": "BSS owners can see whether TikTok Shop links are fresh social-commerce supply or previous cached supply, reducing black-box score confusion during upstream collector outages.",
        "measurement_need": "Analytics export is still needed to compare evidence snapshot views/review clicks against item-card/share behavior and repeat visits.",
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
    ensure_campaign(active_campaigns, {
        "campaign_id": "social-share-preview-card-v1",
        "status": "live-static-og-twitter-card-after-build",
        "objective": "Make owner/reps shared ranking links render a ranking-specific visual preview with Top 3, evidence counts, WATCHLIST count, and the 500/day growth goal instead of a random product image.",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/assets/share-weekly.svg",
            "https://gnsresearchhub.vercel.app/assets/share-monthly.svg",
            "https://gnsresearchhub.vercel.app/assets/share-quarterly.svg",
            "https://gnsresearchhub.vercel.app/assets/share-yearly.svg",
        ],
        "tracked_quality_metrics": [
            "weekly_share_card_top3=" + ", ".join(top3_ids),
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            f"weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
            "homepage and timeframe pages use local /assets/share-{timeframe}.svg in og:image and twitter:image",
        ],
        "owner_value": "When a BSS owner or sales rep shares the hub, the preview itself communicates concrete item picks and evidence discipline before the click, improving trust and repeat-visit intent.",
        "measurement_need": "Analytics export is still needed to compare UTM-attributed sessions from shared links before/after social preview cards; no external posting is performed here.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "rss-owner-feed-v1",
        "status": "live-static-rss-feed-after-build",
        "objective": "Create a subscriber/crawler-friendly RSS feed of weekly BSS owner item picks so repeat visits are not limited to manual page refreshes or SNS posting.",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/feed.xml",
            "https://gnsresearchhub.vercel.app/index.html (rel=alternate application/rss+xml)",
            "https://gnsresearchhub.vercel.app/sitemap.xml",
        ],
        "tracked_quality_metrics": [
            "feed links use utm_source=rss&utm_medium=organic&utm_campaign=daily-visits-500-rss-feed",
            "feed item descriptions include display/risk/evidence status and label WATCHLIST rows as evidence insufficient",
            "rss feed top item ids=" + ", ".join(top3_ids),
        ],
        "owner_value": "BSS owners or reps can subscribe to a lightweight weekly item feed and reopen item detail pages with display/risk copy, which supports repeat visits toward the 500/day goal.",
        "measurement_need": "GA4/Vercel export access is still needed to measure rss UTM sessions and compare feed-driven repeat visits against owner_share/x/email channels.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "owner-feed-subscribe-v1",
        "status": "live-visible-repeat-visit-cta-after-build",
        "objective": "Make the weekly RSS/saved-feed repeat-visit path visible on home and timeframe ranking pages instead of relying only on hidden rel=alternate metadata.",
        "utm_campaign": "daily-visits-500-owner-feed-subscribe",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html (owner-feed-subscribe-v1)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (owner-feed-subscribe-v1)",
            "https://gnsresearchhub.vercel.app/feed.xml",
        ],
        "tracked_events": [
            "growth_section_view owner-feed-subscribe-v1",
            "growth_click cta_owner_feed_open with utm_medium=feed_subscribe",
            "growth_click share_{timeframe}_feed_copy",
            "growth_share_copy_result share_action={timeframe}_feed_copy",
        ],
        "tracked_quality_metrics": [
            f"weekly_feed_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            f"weekly_feed_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
            "visible feed CTA links to /feed.xml?utm_source=site&utm_medium=feed_subscribe&utm_campaign=daily-visits-500-owner-feed-subscribe",
        ],
        "owner_value": "Owners/reps get a one-click way to save or subscribe to weekly item updates; feed entries still preserve display/risk/evidence labels and never turn WATCHLIST items into trend claims.",
        "measurement_need": "Analytics export is still needed to compare owner-feed-subscribe section views/clicks/copy events and downstream utm_source=rss visits against other repeat-visit paths.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "owner-shortcut-save-v1",
        "status": "live-web-manifest-and-shortcut-cta-after-build",
        "objective": "Make repeat visits easier by giving BSS owners/reps a browser Add-to-Home-Screen/bookmark manifest and UTM-tagged shortcut links on home/timeframe pages.",
        "utm_campaign": "daily-visits-500-owner-shortcut",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/manifest.webmanifest",
            "https://gnsresearchhub.vercel.app/assets/app-icon.svg",
            "https://gnsresearchhub.vercel.app/index.html (owner-shortcut-save-v1)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (owner-shortcut-save-v1)",
        ],
        "tracked_events": [
            "growth_section_view owner-shortcut-save-v1",
            "growth_click cta_owner_shortcut_open with utm_medium=shortcut",
            "growth_click cta_owner_shortcut_manifest",
            "growth_click share_{timeframe}_shortcut_copy",
            "growth_share_copy_result share_action={timeframe}_shortcut_copy",
        ],
        "tracked_quality_metrics": [
            "manifest start_url uses utm_source=pwa&utm_medium=shortcut&utm_campaign=daily-visits-500-owner-shortcut",
            "visible shortcut CTA links use utm_source=site&utm_medium=shortcut&utm_campaign=daily-visits-500-owner-shortcut",
            f"shortcut_panel_weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
        ],
        "owner_value": "Busy owners can save the ranking like an app/bookmark and reopen the current weekly view without searching for the URL, supporting repeat visits without external SNS posting.",
        "measurement_need": "GA4/Vercel export access is still needed to measure shortcut UTM sessions, shortcut copy events, and returning-owner visits centrally.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "owner-calendar-reminder-v1",
        "status": "live-static-calendar-retention-after-build",
        "objective": "Give BSS owners/reps a downloadable weekly .ics reminder that brings them back to the ranking without requiring SNS posting or ad spend.",
        "utm_campaign": "daily-visits-500-owner-calendar-reminder",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/owner-weekly-reminder.ics",
            "https://gnsresearchhub.vercel.app/index.html (owner-calendar-reminder-v1)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (owner-calendar-reminder-v1)",
            "https://gnsresearchhub.vercel.app/sitemap.xml",
        ],
        "tracked_events": [
            "growth_section_view owner-calendar-reminder-v1",
            "growth_click cta_owner_calendar_download with utm_medium=calendar_reminder",
            "growth_click share_{timeframe}_calendar_copy",
            "growth_click share_{timeframe}_calendar_message_copy",
            "growth_share_copy_result share_action={timeframe}_calendar_copy or {timeframe}_calendar_message_copy",
        ],
        "tracked_quality_metrics": [
            "calendar file uses RRULE:FREQ=WEEKLY;COUNT=26",
            "calendar URL points back with utm_source=calendar&utm_medium=reminder&utm_campaign=daily-visits-500-owner-calendar-reminder",
            f"calendar_panel_weekly_trend_items={metrics.get('trend_items', 'unknown')}",
            f"calendar_panel_weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
        ],
        "owner_value": "Owners can save a weekly check-in habit in their calendar; reps can copy a reminder text without claiming new evidence or posting externally.",
        "measurement_need": "GA4/Vercel export access is still needed to measure calendar_reminder clicks, calendar UTM return visits, and repeat visitor rate centrally.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "owner-print-sheet-v1",
        "status": "live-static-print-share-sheet-after-build",
        "objective": "Create a print/screenshot-friendly one-page owner handout so reps and BSS owners can share Top 3, 5-minute route, and category lanes without SNS credentials.",
        "utm_campaign": "daily-visits-500-owner-print-sheet",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/owner-share-sheet.html",
            "https://gnsresearchhub.vercel.app/index.html (owner-print-sheet-v1)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (owner-print-sheet-v1)",
            "https://gnsresearchhub.vercel.app/sitemap.xml",
        ],
        "tracked_events": [
            "growth_section_view owner-print-sheet-v1",
            "growth_section_view owner-print-sheet-page-v1",
            "growth_click cta_owner_print_sheet_open with utm_medium=print_sheet",
            "growth_click cta_owner_print_sheet_item with utm_medium=owner_handout",
            "growth_click cta_owner_print_sheet_category with utm_medium=category_lane",
            "growth_click share_owner_print_sheet_sms_draft with embedded utm_source=message&utm_medium=direct",
            "growth_click share_owner_print_sheet_whatsapp_draft with embedded utm_source=message&utm_medium=direct",
            "growth_native_share_result share_action=owner_print_sheet_native_share with utm_source=native_share&utm_medium=mobile",
            "growth_share_copy_result share_action={timeframe}_owner_print_sheet_copy",
            "growth_share_copy_result share_action=owner_print_sheet_copy or owner_print_route_copy",
        ],
        "tracked_quality_metrics": [
            "owner-share-sheet.html summarizes Top 3, 5-minute route, category lanes, and evidence rule",
            "owner-share-sheet.html hero now exposes SMS draft, WhatsApp draft, Phone share, and Copy sheet text actions for mobile/direct distribution",
            "all owner sheet links use daily-visits-500-owner-print-sheet with print_sheet/owner_handout/category_lane/direct/native_share UTMs",
            f"print_sheet_weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            f"print_sheet_weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
        ],
        "owner_value": "BSS owners who prefer printed handouts, screenshots, rep leave-behinds, or mobile direct messages get one concise action sheet while WATCHLIST and supply-only rules remain visible.",
        "measurement_need": "GA4/Vercel export access is needed to compare print_sheet/owner_handout/category_lane/message/native_share visits and copy events against SMS, WhatsApp, RSS, shortcut, calendar, category, and item-detail paths.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "owner-5-minute-route-v1",
        "status": "live-site-ux-distribution-after-build",
        "objective": "Compress the ranking into a copy-ready 3-step store-walk route so busy BSS owners/reps can act and share without reading the full leaderboard first.",
        "utm_campaign_pattern": "daily-visits-500-{timeframe}-owner-route",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html (owner-5-minute-route-v1)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (owner-5-minute-route-v1)",
            "https://gnsresearchhub.vercel.app/rankings/monthly.html (owner-5-minute-route-v1)",
            "https://gnsresearchhub.vercel.app/rankings/quarterly.html (owner-5-minute-route-v1)",
            "https://gnsresearchhub.vercel.app/rankings/yearly.html (owner-5-minute-route-v1)",
        ],
        "tracked_events": [
            "growth_section_view owner-5-minute-route-v1",
            "growth_click cta_owner_route_item with utm_medium=owner_route",
            "growth_click cta_owner_route_full_ranking",
            "growth_click share_{timeframe}_owner_route_copy",
            "growth_share_copy_result share_action={timeframe}_owner_route_copy",
        ],
        "tracked_quality_metrics": [
            f"weekly_route_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            f"weekly_route_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
            "route cards preserve evidence_status_label so WATCHLIST rows remain small-test only",
            "route copy links use utm_medium=route_copy and item links use utm_medium=owner_route",
        ],
        "owner_value": "Owners/reps get a 5-minute route: one hair/install action, one front-end add-on, and one shrink-aware small test. This creates a practical repeat/share path without inventing trend claims.",
        "measurement_need": "GA4/Vercel export access is needed to compare owner-route section views, route-copy events, and item-detail entrances against quick-pick and owner-brief modules.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "category-landing-pages-v1",
        "status": "live-static-category-seo-share-pages-after-build",
        "objective": "Create focused category landing pages that keep broad BSS store lanes navigable while ranking only concrete item types inside each lane.",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/categories/wigs-hair-pieces.html",
            "https://gnsresearchhub.vercel.app/categories/jewelry-fashion-accessories.html",
            "https://gnsresearchhub.vercel.app/index.html (category-landing-nav-v1)",
            "https://gnsresearchhub.vercel.app/sitemap.xml",
        ],
        "tracked_quality_metrics": [
            "category_pages=8",
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            "category pages use utm_medium=category_nav/category_page and preserve WATCHLIST labels",
            "sitemap includes /categories/{category_id}.html URLs for organic discovery",
        ],
        "owner_value": "Busy BSS owners can open a store-zone-specific page such as Wigs, Lashes, Nails, or Jewelry and see item-level display/risk/evidence status without scanning all 44 products.",
        "measurement_need": "Analytics export is still needed to compare category_page/category_nav UTM sessions, category_copy_link events, and category ranking card clicks against generic home/ranking entrances.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "category-brief-copy-v1",
        "status": "live-category-page-copy-ready-brief-after-build",
        "objective": "Give every store-zone category landing page a copy-ready owner brief with top item display tests, risk cautions, and trend-backed/WATCHLIST status so reps can share a category without writing new copy.",
        "utm_campaign": "daily-visits-500-category-brief-copy",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/categories/wigs-hair-pieces.html (category-brief-copy-v1)",
            "https://gnsresearchhub.vercel.app/categories/lashes-brows.html (category-brief-copy-v1)",
            "https://gnsresearchhub.vercel.app/categories/nails.html (category-brief-copy-v1)",
            "https://gnsresearchhub.vercel.app/categories/jewelry-fashion-accessories.html (category-brief-copy-v1)",
        ],
        "tracked_events": [
            "growth_section_view category-brief-copy-v1",
            "growth_click share_category_brief_copy",
            "growth_share_copy_result share_action=category_brief_copy copy_mode=brief_text",
            "growth_click share_category_brief_email",
        ],
        "tracked_quality_metrics": [
            f"category_brief_pages={len(category_ids)}",
            "category brief copy links use utm_source=owner_share&utm_medium=category_brief&utm_campaign=daily-visits-500-category-brief-copy",
            "brief copy includes store zone, trend-backed count, WATCHLIST count, display test, risk, and evidence_status_label",
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            f"weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
        ],
        "owner_value": "A busy BSS owner or GNS rep can copy one share-safe category brief for Wigs, Lashes, Nails, Jewelry, etc.; it is practical without turning the broad category itself into a ranked trend.",
        "measurement_need": "GA4/Vercel export access is needed to compare category_brief copy/email events, category_page UTM sessions, and downstream item-card clicks against generic category links.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "category-share-preview-card-v1",
        "status": "live-static-category-og-twitter-cards-after-build",
        "objective": "Make focused category landing links render store-zone-specific OG/Twitter preview cards instead of the generic all-category ranking image.",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/categories/wigs-hair-pieces.html (og:image share-category-wigs-hair-pieces.svg)",
            "https://gnsresearchhub.vercel.app/categories/lashes-brows.html (og:image share-category-lashes-brows.svg)",
            *[f"https://gnsresearchhub.vercel.app/assets/share-category-{category_id}.svg" for category_id in category_ids[:4]],
        ],
        "tracked_quality_metrics": [
            f"category_share_cards={len(category_ids)}",
            "category page og:image/twitter:image points to /assets/share-category-{category_id}.svg",
            "share card copy labels category lanes as Concrete item types only and does not rank the category itself",
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
        ],
        "owner_value": "When a BSS owner/reps shares a Wig, Lash, Nail, Tools, or Jewelry lane, the preview now matches that store zone and shows trend/WATCHLIST discipline before the click.",
        "measurement_need": "GA4/Vercel export access is still needed to compare category_page UTM sessions and category_copy_link events before/after category-specific share previews.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "category-direct-mobile-share-v1",
        "status": "live-category-page-direct-mobile-share-after-build",
        "objective": "Add SMS/Kakao text copy, SMS draft, WhatsApp draft, and phone-native share actions to every store-zone category page so low-traffic owner/reps sessions can forward the most relevant BSS lane without external SNS credentials.",
        "utm_campaign": "daily-visits-500-category-direct-mobile-share",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/categories/wigs-hair-pieces.html (category-share-kit-v1 direct/mobile actions)",
            "https://gnsresearchhub.vercel.app/categories/lashes-brows.html (category-share-kit-v1 direct/mobile actions)",
            "https://gnsresearchhub.vercel.app/categories/nails.html (category-share-kit-v1 direct/mobile actions)",
            "https://gnsresearchhub.vercel.app/categories/jewelry-fashion-accessories.html (category-share-kit-v1 direct/mobile actions)",
        ],
        "tracked_events": [
            "growth_click share_category_sms_draft with link_utm_source=message and link_utm_medium=direct",
            "growth_click share_category_whatsapp_draft with embedded message UTM parsed from wa.me text",
            "growth_click share_category_native_share with link_utm_source=native_share and link_utm_medium=mobile",
            "growth_native_share_result share_action=category_native_share",
            "growth_share_copy_result share_action=category_message_copy copy_mode=brief_text",
        ],
        "tracked_quality_metrics": [
            f"category_direct_share_pages={len(category_ids)}",
            "category message copy states the category itself is not a trend claim and keeps WATCHLIST rows small-test only",
            "direct/mobile category links use daily-visits-500-category-direct-mobile-share with message/direct or native_share/mobile UTMs",
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            f"weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
        ],
        "owner_value": "A rep or owner can forward a Wig, Lash, Nail, Jewelry, or Tools lane by text/WhatsApp/phone share, preserving concrete item-level evidence labels instead of asking the recipient to scan the full dashboard.",
        "measurement_need": "GA4/Vercel export access is still needed to compare category direct-message/mobile share events and category UTM sessions against X/email/category_copy_link behavior toward 500/day.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "ranking-first-layout-v1",
        "status": "live-site-ux-after-build",
        "objective": "Move the Top 3 leaderboard and main item ranking immediately after the hero/category chips so busy BSS owners see concrete product picks before growth, evidence, or share tooling panels.",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html (top3-leaderboard-v1 before evidence/share modules)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (ranking-main-list-v1 before evidence/share modules)",
            "https://gnsresearchhub.vercel.app/rankings/monthly.html",
            "https://gnsresearchhub.vercel.app/rankings/quarterly.html",
            "https://gnsresearchhub.vercel.app/rankings/yearly.html",
        ],
        "tracked_events": [
            "growth_section_view top3-leaderboard-v1 near first content viewport",
            "growth_section_view ranking-main-list-v1 before evidence/growth modules",
            "growth_click podium_card and item_card with ranking-list-engagement-context-v1",
        ],
        "tracked_quality_metrics": [
            "home_section_order=top3-leaderboard-v1 -> ranking-main-list-v1 -> monthly-preview-list-v1 -> category-landing-nav-v1 -> evidence/growth/share panels",
            "timeframe_section_order=top3-leaderboard-v1 -> ranking-main-list-v1 -> run-change/evidence/owner panels",
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            f"weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
        ],
        "owner_value": "This restores the dashboard to a ranking-first experience: owners can scan stock/test items first, then use evidence, focus, share, feed, shortcut, and calendar tools as supporting modules.",
        "measurement_need": "GA4/Vercel export access is needed to compare scroll depth, first item-card clicks, and share/copy behavior before/after the layout order change.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "ranking-item-click-attribution-v1",
        "status": "live-ranking-card-utm-context-after-build",
        "objective": "Tag core Top 3 podium and ranking-card item-detail clicks with UTM context so owner item-interest can be measured separately from generic page loads.",
        "utm_campaign_pattern": "daily-visits-500-{timeframe}-ranking-item-clicks",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html (Top 3 podium + Weekly/Monthly item cards)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (podium_card and ranking_card links)",
            "https://gnsresearchhub.vercel.app/rankings/monthly.html",
            "https://gnsresearchhub.vercel.app/categories/wigs-hair-pieces.html (category ranking cards use weekly context)",
        ],
        "tracked_events": [
            "growth_click podium_card with link_utm_medium=podium_card",
            "growth_click item_card with link_utm_medium=ranking_card",
            "growth_exposure page_type=item_detail with utm_campaign=daily-visits-500-{timeframe}-ranking-item-clicks after card navigation",
        ],
        "tracked_quality_metrics": [
            "podium hrefs use utm_source=site&utm_medium=podium_card&utm_campaign=daily-visits-500-{timeframe}-ranking-item-clicks",
            "rank-hit hrefs use utm_source=site&utm_medium=ranking_card&utm_campaign=daily-visits-500-{timeframe}-ranking-item-clicks",
            f"weekly_top_item_id={top3_ids[0] if top3_ids else 'none'}",
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
        ],
        "owner_value": "The UI looks the same to BSS owners, but future analytics can identify which concrete product cards drive item-detail interest, helping optimize toward 500/day without external posting or fabricated demand claims.",
        "measurement_need": "Basic Vercel visits are measured; GA4 Data API or Vercel custom-event/UTM export is still needed to compare ranking_card vs podium_card item-detail conversion centrally.",
        "last_refreshed_at": now,
    })
    focus_items = review.get("next_loop_focus_items", []) if isinstance(review.get("next_loop_focus_items", []), list) else []
    focus_item_ids = [str(item.get("item_id")) for item in focus_items if isinstance(item, dict) and item.get("item_id")]
    supplemental_rows = [
        row for row in rows
        if any(
            isinstance(src, dict) and src.get("discovery_kind") == "supplemental_published_trend_query"
            for src in (row.get("trend_evidence") or [])
        )
    ]
    supplemental_item_ids = [str(row.get("item_id")) for row in supplemental_rows if row.get("item_id")]
    supplemental_categories = sorted({
        str(row.get("category_name") or row.get("category_id"))
        for row in supplemental_rows
        if row.get("category_name") or row.get("category_id")
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "focus-query-diversification-v1",
        "status": "live-collector-feedback-loop-after-review",
        "objective": "Improve the next evidence loop by selecting a diversified set of exact, owner-context, and review/tutorial queries for weak WATCHLIST items instead of only the first generic trend probes.",
        "tracked_quality_metrics": [
            "NEXT_LOOP_FOCUS_QUERIES_PER_ITEM default=3",
            "collector chooses exact + owner-context + review/tutorial probes when available",
            "focus_items=" + ", ".join(focus_item_ids[:MAX_FOCUS_ITEMS]),
            f"weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
        ],
        "owner_value": "Weak item cards get a better chance of collecting dated, item-relevant sources in the next run, which can lower WATCHLIST count without treating generated search URLs as evidence.",
        "measurement_need": "Track weekly trend_items/WATCHLIST deltas and later source-link engagement after analytics export access is connected.",
        "last_refreshed_at": now,
    })
    collection_gap_focus = [
        item for item in focus_items
        if isinstance(item, dict) and item.get("focus_source") == "collection_notes_missing_published_trend"
    ]
    ensure_campaign(active_campaigns, {
        "campaign_id": "coverage-gap-first-focus-v1",
        "status": "live-feedback-loop-prioritization-after-review",
        "objective": "Prioritize true collection_notes missing published-trend gaps in next_loop_focus before recency-only weekly WATCHLIST items, so the next collector spends probes on items with no captured dated trend URL at all.",
        "tracked_quality_metrics": [
            f"collection_gap_focus_items={len(collection_gap_focus)}/{MAX_FOCUS_ITEMS}",
            "gap_focus_item_ids=" + ", ".join(str(item.get("item_id")) for item in collection_gap_focus[:MAX_FOCUS_ITEMS]),
            f"published_trend_missing_items={len(missing_published_gap_ids(load_json(COLLECTION_NOTES_PATH, {})))}",
            f"weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
        ],
        "owner_value": "The next research loop is more likely to turn truly unsupported item cards into evidence-backed owner guidance instead of repeatedly refreshing items that already have older dated evidence.",
        "measurement_need": "Compare next run's missing_published_trend_items, weekly trend_items, WATCHLIST count, and focus follow-up status; analytics export is still needed to connect improvements to visits.",
        "last_refreshed_at": now,
    })
    review_collection_health = review.get("collection_health", {}) if isinstance(review.get("collection_health"), dict) else {}
    review_evidence_totals = review_collection_health.get("evidence_totals", {}) if isinstance(review_collection_health.get("evidence_totals"), dict) else {}
    review_gap_summary = review_collection_health.get("coverage_gap_summary", {}) if isinstance(review_collection_health.get("coverage_gap_summary"), dict) else {}
    ensure_campaign(active_campaigns, {
        "campaign_id": "collection-evidence-regression-recovery-v1",
        "status": "live-review-quality-loop-after-build",
        "objective": "Catch all-window evidence/source regressions that weekly ranking counts can hide, then route the next loop toward recovery before claiming product/share improvement.",
        "tracked_quality_metrics": [
            "collection_regressions=" + ("; ".join(collection_regressions[:5]) if collection_regressions else "none"),
            "collection_improvements=" + ("; ".join(collection_improvements[:5]) if collection_improvements else "none"),
            f"all_window_published_trend_items={review_evidence_totals.get('items_with_published_trend_url', 'unknown')}",
            f"published_trend_missing_items={review_gap_summary.get('published_trend_missing_items', 'unknown')}",
        ],
        "owner_value": "BSS owners see a more honest dashboard because source-quality setbacks are labeled as recovery work instead of being hidden behind unchanged Top 3 or weekly counts.",
        "measurement_need": "Analytics export is still required to connect source recovery to owner trust actions such as source-link clicks, item-card clicks, and repeat visits.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "supplemental-trend-query-coverage-v1",
        "status": "live-collector-quality-after-build",
        "objective": "Recover dated published URLs for concrete BSS item types whose public demand signals use look/style wording instead of exact SKU phrases, especially Nails and Jewelry.",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/data/collection_notes_public.json",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html",
            "https://gnsresearchhub.vercel.app/categories/jewelry-fashion-accessories.html",
            "https://gnsresearchhub.vercel.app/categories/nails.html",
        ],
        "tracked_quality_metrics": [
            "SUPPLEMENTAL_TREND_NEWS_QUERIES_PER_ITEM default=3",
            "supplemental_item_ids=" + ", ".join(supplemental_item_ids[:12]),
            "supplemental_categories=" + ", ".join(supplemental_categories[:6]),
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            f"weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
        ],
        "owner_value": "BSS owners get fewer false WATCHLIST cards in accessory-style lanes when actual dated articles exist, while broad search pages and product listings remain non-trend evidence.",
        "measurement_need": "Analytics export is still needed to compare source-link clicks and item-card/share engagement on newly trend-backed Nails/Jewelry items.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "vercel-analytics-head-bootstrap-v1",
        "status": "live-provider-bridge-after-build",
        "objective": "Make Vercel Web Analytics event collection more reliable by exposing the provider path and window.va queue before the deferred growth bundle sends the first growth_exposure.",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html",
            "https://gnsresearchhub.vercel.app/assets/growth.js",
            "https://gnsresearchhub.vercel.app/_vercel/insights/script.js",
        ],
        "tracked_events": [
            "growth_exposure queued to window.va before provider script finishes loading",
            "growth_click and growth_share_copy_result fan-out through Vercel Analytics and GA4 bridges",
        ],
        "tracked_quality_metrics": [
            "head bootstrap defines window.__GNS_VERCEL_ANALYTICS_PATH=/_vercel/insights/script.js",
            "Playwright asserts window.va is a function before growth event checks",
            "live /_vercel/insights/script.js must return HTTP 200",
        ],
        "owner_value": "Traffic and share experiments become easier to measure once analytics export access is connected, reducing guesswork on which BSS owner paths drive repeat visits.",
        "measurement_need": "Still requires GA4 Data API or Vercel Analytics export access to calculate rolling 30-day visits; this run only hardens client-side event capture.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "analytics-provider-health-event-v1",
        "status": "live-client-side-provider-health-and-schema-v2-after-build",
        "objective": "Emit a lightweight growth_provider_ready event plus a stable growth-event-schema-v2 marker so the operator can detect whether GA4, Vercel Analytics queueing, and the production analytics script are available before interpreting growth funnels.",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html",
            "https://gnsresearchhub.vercel.app/assets/growth.js",
            "https://gnsresearchhub.vercel.app/_vercel/insights/script.js",
        ],
        "tracked_events": [
            "growth_provider_ready status=client_bridge_ready on every page load with event_schema_version=growth-event-schema-v2",
            "growth_provider_ready status=vercel_script_loaded or vercel_script_error on production hosts",
            "growth_exposure/growth_click/growth_share_copy_result all carry event_schema_version and tracking_runtime for provider export QA",
        ],
        "tracked_quality_metrics": [
            "Playwright asserts local growth buffer contains growth_provider_ready with ga4_ready=true, vercel_queue_ready=true, and event_schema_version=growth-event-schema-v2",
            "analyticsBridgeStatus() is exposed on window.__GNS_GROWTH__ for smoke checks without reading secrets",
            "analyticsBridgeStatus() now includes vercel_queue_depth and data_layer_ready so provider bootstrap can be audited without dashboard credentials",
            "event payload includes vercel_script_path but no token/key values",
        ],
        "owner_value": "This does not increase traffic by itself; it makes the 500/day growth loop safer by separating tracking-provider health from actual owner engagement once analytics export access is connected.",
        "measurement_need": "GA4 Data API or Vercel Analytics export access is still required to read provider-side event counts and rolling 30-day visits.",
        "last_refreshed_at": now,
    })

    ensure_campaign(active_campaigns, {
        "campaign_id": "item-evidence-summary-v1",
        "status": "live-item-detail-trust-cta-after-build",
        "objective": "Turn each item detail page into a quick owner trust check that separates trend claim status, 14-day recency, supply validation, and watchlist references before owners share or stock-test an item.",
        "utm_campaign": "daily-visits-500-item-evidence-summary",
        "live_location_pattern": "https://gnsresearchhub.vercel.app/items/{item_id}.html (item-evidence-summary-v1)",
        "tracked_events": [
            "growth_section_view item-evidence-summary-v1",
            "growth_click cta_item_evidence_source_jump",
            "growth_click share_item_evidence_summary_copy",
            "growth_share_copy_result share_action=item_evidence_summary_copy",
            "growth_click source_link with source_domain context",
        ],
        "tracked_quality_metrics": [
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            f"weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
            "item detail pages expose Trend claim status, 14d recency, Supply validation, and Watchlist references before source cards",
            "copyable evidence summaries use utm_medium=evidence_summary and preserve the rule that supply/search links are not trend evidence",
        ],
        "owner_value": "Busy BSS owners and reps can copy a share-safe evidence summary from a product detail page and jump to source links without mistaking supply/watchlist URLs for trend proof.",
        "measurement_need": "GA4/Vercel export access is still needed to compare item-evidence-summary section views, source jumps, copy events, and downstream item-detail repeat visits.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "timeframe-evidence-ladder-v1",
        "status": "live-site-ux-after-build",
        "objective": "Keep owners engaged when the strict weekly evidence window is thin by showing Weekly/Monthly/Quarterly/Yearly trend-backed and WATCHLIST coverage side by side without broadening weekly claims.",
        "utm_campaign": "daily-visits-500-timeframe-evidence-ladder",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html (timeframe-evidence-ladder-v1)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (timeframe-evidence-ladder-v1)",
            "https://gnsresearchhub.vercel.app/rankings/monthly.html (timeframe-evidence-ladder-v1)",
            "https://gnsresearchhub.vercel.app/rankings/quarterly.html (timeframe-evidence-ladder-v1)",
            "https://gnsresearchhub.vercel.app/rankings/yearly.html (timeframe-evidence-ladder-v1)",
        ],
        "tracked_events": [
            "growth_section_view timeframe-evidence-ladder-v1",
            "growth_click cta_timeframe_evidence_ladder with utm_medium=evidence_ladder",
        ],
        "tracked_quality_metrics": coverage_labels or ["timeframe coverage summary unavailable"],
        "coverage_summary": coverage_summary,
        "owner_value": "BSS owners can choose a stricter fresh Weekly view or a broader context window deliberately, reducing black-box score confusion and improving repeat navigation across timeframe pages.",
        "measurement_need": "GA4/Vercel export access is needed to compare evidence_ladder clicks and downstream timeframe/item-detail entrances against existing tabs and category navigation.",
        "last_refreshed_at": now,
    })

    ensure_campaign(active_campaigns, {
        "campaign_id": "link-destination-utm-context-v1",
        "status": "live-in-growth-js-after-build",
        "objective": "Make the growth funnel measurable by adding destination UTM fields to growth_click and growth_share_copy_result events for links and copy buttons.",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html (assets/growth.js)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (share/copy/CTA events)",
            "https://gnsresearchhub.vercel.app/items/{item_id}.html (item share and evidence-summary copy events)",
            "https://gnsresearchhub.vercel.app/categories/{category_id}.html (category share/copy events)",
        ],
        "tracked_events": [
            "growth_click includes link_utm_source/link_utm_medium/link_utm_campaign/link_utm_content/link_utm_term",
            "growth_click includes link_protocol/link_origin/link_path/destination_origin/destination_path/link_has_utm/link_is_external",
            "growth_share_copy_result includes the same destination UTM context for data-copy-url buttons",
            "embedded X intent URL, mailto body URLs, and sms: body URLs are parsed so downstream campaign links remain measurable",
        ],
        "tracked_quality_metrics": [
            "Playwright asserts weekly_top3_copy_link carries link_utm_source=owner_share and campaign=daily-visits-500-weekly-top3-owner-share",
            "Playwright asserts owner_route_item and owner_route_copy carry owner_route/route_copy destination media",
            "Playwright asserts focus_watchlist, category_landing, item_evidence_summary, and item_copy_link events carry destination UTM context",
        ],
        "owner_value": "No extra UI clutter. This makes it possible to learn which BSS-owner share paths actually create repeat visits once GA4/Vercel event export is connected, instead of treating all clicks as generic dashboard interactions.",
        "measurement_need": "GA4_PROPERTY_ID plus service credentials or approved Vercel Analytics export/API access is still required to read provider-side link_utm_* event counts and tie them to rolling 30-day visits.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "direct-message-owner-share-v1",
        "status": "live-site-direct-share-after-build",
        "objective": "Add SMS/Kakao-ready owner message copy and SMS draft links to ranking, Top 3, and item detail share modules so distribution can proceed without external SNS posting credentials.",
        "utm_campaign_pattern": "daily-visits-500-{timeframe}-owner-share and daily-visits-500-{timeframe}-top3-owner-share",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html (weekly_message_copy and weekly_top3_message_copy)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (direct message copy buttons)",
            "https://gnsresearchhub.vercel.app/items/{item_id}.html (item_message_copy)",
        ],
        "tracked_events": [
            "growth_click share_{timeframe}_sms_draft with embedded message UTM parsed from sms: body",
            "growth_click share_{timeframe}_message_copy",
            "growth_share_copy_result share_action={timeframe}_message_copy copy_mode=brief_text",
            "growth_share_copy_result share_action={timeframe}_top3_message_copy with item_id context",
            "growth_share_copy_result share_action=item_message_copy on item detail pages",
        ],
        "tracked_quality_metrics": [
            "message links use utm_source=message&utm_medium=direct",
            "SMS/Kakao text includes display test, evidence_status_label, risk/caution, and the rule that supply/watchlist URLs are not trend claims",
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            f"weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
        ],
        "owner_value": "BSS owners and reps often forward short text messages faster than X/email posts; this creates a measurable direct-message path while staying draft/copy-only and evidence-safe.",
        "measurement_need": "GA4/Vercel export access is still needed to compare utm_source=message sessions, SMS draft clicks, message copy events, and return visits against owner_share, X, email, RSS, shortcut, and calendar channels.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "native-mobile-share-v1",
        "status": "live-site-mobile-share-after-build",
        "objective": "Add Web Share API buttons with copy fallback to ranking, Top 3, and item-detail share modules so phone users can forward owner-ready item links without external SNS credentials.",
        "utm_campaign_pattern": "daily-visits-500-{timeframe}-owner-share, daily-visits-500-{timeframe}-top3-owner-share, and daily-visits-500-item-detail-share",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html (weekly_native_share and weekly_top3_native_share)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (native share buttons)",
            "https://gnsresearchhub.vercel.app/items/{item_id}.html (item_native_share)",
        ],
        "tracked_events": [
            "growth_click share_{timeframe}_native_share with link_utm_source=native_share",
            "growth_click share_{timeframe}_top3_native_share with item_id context",
            "growth_native_share_result with native_share_supported/native_shared/copy fallback status",
            "growth_share_copy_result for native share fallback so funnels remain comparable to SMS/Kakao copy events",
        ],
        "tracked_quality_metrics": [
            "native share buttons use utm_source=native_share&utm_medium=mobile",
            "Share text includes display test, evidence_status_label, risk/caution, and evidence discipline rule",
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            f"weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
        ],
        "owner_value": "Many BSS owners open links on mobile. Native share reduces friction by letting them use the phone share sheet or a safe copy fallback while preserving UTM and evidence-safe copy.",
        "measurement_need": "GA4/Vercel export access is still needed to compare native_share mobile events against SMS, WhatsApp, owner_share, RSS, shortcut, and calendar paths.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "whatsapp-owner-share-v1",
        "status": "live-site-whatsapp-draft-after-build",
        "objective": "Add WhatsApp draft links to ranking, Top 3, and item detail share modules so BSS owners/reps get another common direct-message distribution path without auto-posting or external credentials.",
        "utm_campaign_pattern": "daily-visits-500-{timeframe}-owner-share, daily-visits-500-{timeframe}-top3-owner-share, and daily-visits-500-item-detail-share",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html (weekly_whatsapp_draft and weekly_top3_whatsapp_draft)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (WhatsApp draft share actions)",
            "https://gnsresearchhub.vercel.app/items/{item_id}.html (item_whatsapp_draft)",
        ],
        "tracked_events": [
            "growth_click share_{timeframe}_whatsapp_draft with embedded UTM parsed from wa.me text",
            "growth_click share_{timeframe}_top3_whatsapp_draft with item_id context",
            "growth_click share_item_whatsapp_draft on item detail pages",
        ],
        "tracked_quality_metrics": [
            "WhatsApp links use https://wa.me/?text=... and remain user-initiated drafts only",
            "Embedded owner links use utm_source=message&utm_medium=direct so WhatsApp can be compared against SMS/Kakao copy and owner_share links",
            "Playwright asserts WhatsApp draft links and parsed link_utm_* event context",
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            f"weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
        ],
        "owner_value": "Adds a practical mobile-forward path for owners/reps who use WhatsApp groups or one-to-one messages, while preserving draft-only guardrails and evidence-status copy.",
        "measurement_need": "GA4/Vercel export access is still needed to compare utm_source=message sessions and WhatsApp draft click events against SMS/Kakao, owner_share, X, email, RSS, shortcut, and calendar paths.",
        "last_refreshed_at": now,
    })
    ensure_campaign(active_campaigns, {
        "campaign_id": "ranking-card-evidence-badge-v1",
        "status": "live-ranking-list-trust-ux-after-build",
        "objective": "Make every ranking card show a visible Trend-backed vs WATCHLIST small-test badge before the owner opens an item detail page.",
        "live_locations": [
            "https://gnsresearchhub.vercel.app/index.html (.rank-card .evidence-badge)",
            "https://gnsresearchhub.vercel.app/rankings/weekly.html (.rank-card .evidence-badge)",
            "https://gnsresearchhub.vercel.app/rankings/monthly.html (.rank-card .evidence-badge)",
            "https://gnsresearchhub.vercel.app/categories/{category_id}.html (.rank-card .evidence-badge)",
        ],
        "tracked_events": [
            "growth_click item_card after seeing card-level evidence status",
            "growth_section_view ranking-main-list-v1 with visible evidence badges",
            "growth_click podium_card remains trend-backed-only for Top 3 leaders",
        ],
        "tracked_quality_metrics": [
            "every .rank-card includes .evidence-badge with data-evidence-status and data-trend-urls",
            "watchlist cards display WATCHLIST · small test only before chips/detail pages",
            f"weekly_trend_items={metrics.get('trend_items', 'unknown')}/{metrics.get('items', 'unknown')}",
            f"weekly_watchlist_items={metrics.get('watchlist_items', 'unknown')}",
        ],
        "owner_value": "Busy BSS owners can tell immediately whether an item is safe to discuss as trend-backed or should stay a shrink-aware small test, reducing black-box score confusion on the main ranking list.",
        "measurement_need": "GA4/Vercel export access is needed to compare item_card clicks, source-link clicks, and share/copy behavior before/after visible card-level evidence badges.",
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
            "experiment_id": "focus-query-diversification-v1",
            "status": "active-feedback-loop-collection-quality-after-review",
            "hypothesis": "Diversifying next_loop_focus probes into exact, owner-context, and review/tutorial queries should improve dated URL discovery for weak BSS item cards without scoring generated search URLs.",
            "next_step": "Compare previous_loop_follow_up and weekly WATCHLIST deltas after the next refresh; keep query URLs watchlist-only unless a dated item-relevant URL is captured.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "coverage-gap-first-focus-v1",
            "status": "active-feedback-loop-prioritization-after-review",
            "hypothesis": "Prioritizing collection_notes missing_published_trend_items should reduce true all-window dated-source gaps faster than ranking-only WATCHLIST focus, while preserving the rule that generated queries are probes only.",
            "next_step": "Compare next run's missing_published_trend_items, focus follow-up improved/still_needs_focus status, weekly trend_items, and WATCHLIST deltas before claiming research progress.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "collection-evidence-regression-recovery-v1",
            "status": "active-review-quality-loop-after-review",
            "hypothesis": "Explicitly tracking all-window evidence/source deltas will prevent false-positive improvement reports and focus recovery on lost dated URLs or source freshness before broad growth pushes.",
            "next_step": "Compare collection_evidence_deltas, missing_published_trend_items, and next_loop_focus follow-up before claiming source-quality progress; analytics export is still needed for traffic impact.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "supplemental-trend-query-coverage-v1",
            "status": "active-collection-quality-after-review",
            "hypothesis": "Bounded item/look-language published-source probes for concrete Nails/Jewelry SKUs should recover dated evidence that exact SKU queries miss while strict required-term guards prevent broad category overclaims.",
            "next_step": "Compare supplemental source click events, weekly trend_items/WATCHLIST deltas, and zero-trend category count after analytics export access is connected; continue excluding generated search URLs and supply listings from trend scoring.",
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
            "experiment_id": "vercel-analytics-head-bootstrap-v1",
            "status": "active-provider-bridge-after-review",
            "hypothesis": "A head-level window.va queue and explicit /_vercel/insights/script.js path should reduce missed first-exposure/share events while preserving local QA stability.",
            "next_step": "After analytics export access is connected, compare Vercel custom event counts against local growth buffer QA for growth_exposure, growth_click, and share/copy events.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "analytics-provider-health-event-v1",
            "status": "active-provider-health-after-review",
            "hypothesis": "A growth_provider_ready event and analyticsBridgeStatus() smoke snapshot should help distinguish provider/tag failures from true traffic or CTA performance changes.",
            "next_step": "After GA4/Vercel export access is connected, alert on missing growth_provider_ready counts before reading funnel metrics for the 500/day goal.",
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
            "experiment_id": "apify-failure-cooldown-v1",
            "status": "active-collection-resilience-after-review",
            "hypothesis": "A short cache-first cooldown after recent Apify actor failures should reduce repeated failed API runs and preserve dashboard speed, while source-health labeling prevents cached TikTok Shop URLs from being treated as fresh trend evidence.",
            "next_step": "Compare apify_status, attempts, cooldown_remaining_minutes, cache_age_days, and fresh_evidence_urls on the next two loops; retry automatically after APIFY_TIKTOK_FAILURE_COOLDOWN_MINUTES expires.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "tiktok-source-health-label-v1",
            "status": "active-site-trust-ux-after-review",
            "hypothesis": "Explicit Fresh/Cached labels in the evidence snapshot will reduce owner confusion when TikTok Shop actor failures require cache fallback, improving trust before source-link or item-card clicks.",
            "next_step": "After analytics export access is connected, compare evidence-gap section views/review clicks and downstream item-card/share events during fresh vs cached TikTok Shop runs.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "return-visitor-prompt-v1",
            "status": "active-repeat-visit-ux-after-review",
            "hypothesis": "A concise returning-owner prompt should increase current-ranking CTA clicks and repeat visits by showing what to check first after the initial visit.",
            "next_step": "After GA4/Vercel export access is connected, segment growth_return_visit_prompt exposure, cta_return_visitor_current_ranking clicks, and is_returning_visitor traffic.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "visit-session-boundary-v1",
            "status": "active-client-side-provider-ready-after-review",
            "hypothesis": "A new session_id after the 30-minute visit window will make return-owner visits and UTM funnels easier to measure without inflating one long-lived browser session.",
            "next_step": "After GA4/Vercel export access is connected, compare session_id, visit_count, is_returning_visitor, and first/current UTM on repeat ranking and item-detail entrances.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "item-evidence-summary-v1",
            "status": "active-item-detail-trust-cta-after-review",
            "hypothesis": "A compact item-detail trust check with copyable evidence summary should increase source-link clicks, share-safe owner forwards, and repeat item-detail visits because owners can judge trend-backed vs WATCHLIST status before acting.",
            "next_step": "After analytics export access is connected, segment item-evidence-summary section views, item_evidence_summary_copy results, source jumps, source_domain clicks, and downstream owner_share/evidence_summary UTM visits.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "timeframe-evidence-ladder-v1",
            "status": "active-site-ux-after-review",
            "hypothesis": "A visible evidence-window ladder should reduce bounce and black-box score confusion when weekly trend coverage is thin by routing owners to Monthly/Quarterly/Yearly context without overclaiming weekly movement.",
            "next_step": "After analytics export access is connected, compare growth_section_view timeframe-evidence-ladder-v1 and cta_timeframe_evidence_ladder clicks against tab-only navigation and item-detail entrances.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "social-share-preview-card-v1",
            "status": "active-static-shareability-after-review",
            "hypothesis": "Ranking-specific OG/Twitter preview cards should improve trust and click intent when BSS owners/reps share links because the preview shows concrete Top 3 items and evidence/watchlist discipline before the visit.",
            "next_step": "After analytics export access is connected, compare UTM-attributed sessions from owner_share/x/email links and share-copy events before/after /assets/share-{timeframe}.svg deployment.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "rss-owner-feed-v1",
            "status": "active-static-distribution-after-review",
            "hypothesis": "A crawlable/subscribable RSS feed with item-level display, risk, evidence labels, and rss UTM links should increase repeat entrances from BSS owners who prefer saved feeds or rep workflows over manual refreshes.",
            "next_step": "After analytics export access is connected, segment utm_source=rss sessions, item-detail entrances, and returning visitor rate against x/email/owner_share traffic.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "owner-feed-subscribe-v1",
            "status": "active-visible-repeat-visit-cta-after-review",
            "hypothesis": "A visible feed subscribe/save panel should generate more repeat owner entrances than a hidden RSS alternate link because BSS owners/reps can copy or open the update feed from the dashboard itself.",
            "next_step": "After analytics export access is connected, compare owner-feed-subscribe section views, cta_owner_feed_open clicks, feed_copy results, and downstream utm_source=rss item-detail entrances.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "owner-shortcut-save-v1",
            "status": "active-repeat-visit-shortcut-after-review",
            "hypothesis": "A real web manifest plus visible shortcut copy/open CTA should make the hub easier for owners/reps to save and reopen, increasing repeat visit paths without requiring SNS posting credentials.",
            "next_step": "After GA4/Vercel export access is connected, compare utm_medium=shortcut and utm_source=pwa sessions, shortcut copy events, and returning-owner visit_count against RSS/share paths.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "owner-calendar-reminder-v1",
            "status": "active-static-retention-after-review",
            "hypothesis": "A downloadable weekly .ics reminder should create another measurable return-visit path for busy BSS owners/reps who will not subscribe to RSS or save a PWA shortcut.",
            "next_step": "After GA4/Vercel export access is connected, compare calendar_reminder clicks, utm_source=calendar return visits, and is_returning_visitor rates against RSS, shortcut, and owner-share paths.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "ranking-card-evidence-badge-v1",
            "status": "active-ranking-list-trust-ux-after-review",
            "hypothesis": "Visible Trend-backed/WATCHLIST badges on each ranking card should improve owner trust and item-card click quality because weak evidence rows are labeled as small tests before a detail-page click.",
            "next_step": "After GA4/Vercel export access is connected, compare ranking-main-list item_card clicks, WATCHLIST card click rate, source-link clicks, and share/copy behavior against prior ranking cards that exposed status mostly through chips.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "owner-print-sheet-v1",
            "status": "active-static-offline-share-after-review",
            "hypothesis": "A one-page print/screenshot owner handout should make rep visits and owner forwarding more practical than dashboard-only sharing, especially when X posting is unavailable.",
            "next_step": "After analytics export access is connected, compare print_sheet/owner_handout/category_lane UTM sessions and owner_print_sheet copy events against SMS, WhatsApp, RSS, shortcut, and calendar paths.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "link-destination-utm-context-v1",
            "status": "active-client-side-provider-ready-after-review",
            "hypothesis": "BSS owner growth optimization needs destination-level UTM context on every clicked/copied link so owner_share, X, email, RSS, shortcut, calendar, focus-watchlist, and item-detail share paths can be compared without brittle URL parsing.",
            "next_step": "After GA4/Vercel export access is connected, compare link_utm_source/medium/campaign on growth_click and growth_share_copy_result against repeat item-detail entrances and rolling 30-day visits; remove or deprioritize channels that do not create returning-owner behavior.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "direct-message-owner-share-v1",
            "status": "active-site-direct-share-after-review",
            "hypothesis": "SMS/Kakao-ready copy should create more practical owner/reps distribution than X/email-only drafts because many BSS owners respond to direct short messages and no external posting credentials are required.",
            "next_step": "After analytics export access is connected, compare utm_source=message sessions, share_*_message_copy results, sms_draft clicks, and return visits against owner_share/x/email/RSS/shortcut/calendar channels.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "native-mobile-share-v1",
            "status": "active-site-mobile-share-after-review",
            "hypothesis": "A Web Share API button with copy fallback should reduce mobile owner forwarding friction versus forcing users to choose SMS/WhatsApp/X buttons separately, while UTM and evidence labels keep results measurable and safe.",
            "next_step": "After GA4/Vercel export access is connected, compare native_share mobile events, fallback copy results, item-detail entrances, and return visits against SMS/Kakao, WhatsApp, owner_share, RSS, shortcut, and calendar channels.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "whatsapp-owner-share-v1",
            "status": "active-site-whatsapp-draft-after-review",
            "hypothesis": "WhatsApp draft links should improve practical owner/reps distribution in direct-message groups while remaining user-initiated and credential-free, especially for mobile-forward BSS owner sharing.",
            "next_step": "After analytics export access is connected, compare share_*_whatsapp_draft clicks and utm_source=message sessions against SMS/Kakao copy, owner_share, X, email, RSS, shortcut, and calendar channels.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "owner-5-minute-route-v1",
            "status": "active-site-ux-distribution-after-review",
            "hypothesis": "A 3-step store-walk route should increase BSS owner action and share intent versus reading only the full leaderboard because it gives a hair/install pick, a front-end add-on, and a WATCHLIST small-test in one copy-ready block.",
            "next_step": "After analytics export access is connected, compare owner-5-minute-route-v1 section views, owner_route_item clicks, owner_route_copy results, and item-detail entrances against quick-pick and owner-brief components.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "category-landing-pages-v1",
            "status": "active-static-seo-shareability-after-review",
            "hypothesis": "Store-zone category pages should increase organic/search and owner-share entry points because owners can land directly on their relevant BSS lane while still seeing concrete item-level recommendations.",
            "next_step": "After analytics export access is connected, compare utm_medium=category_nav/category_page sessions, category_copy_link events, category-ranking card clicks, and repeat visits against home-page broad ranking entrances.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "category-brief-copy-v1",
            "status": "active-category-page-copy-ready-after-review",
            "hypothesis": "Copy-ready category briefs should increase rep/owner sharing of store-zone pages because they package the top concrete items, display tests, risk cautions, and WATCHLIST status into one share-safe text block.",
            "next_step": "After analytics export access is connected, compare category_brief_copy and category_brief_email events, category_brief UTM sessions, and downstream item-card clicks against generic category_copy_link behavior.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "category-share-preview-card-v1",
            "status": "active-static-category-shareability-after-review",
            "hypothesis": "Category-specific OG/Twitter preview cards should improve owner-share click intent because shared store-zone links show the relevant BSS lane, concrete item leaders, and WATCHLIST discipline instead of a generic all-category image.",
            "next_step": "After analytics export access is connected, compare category_page/category_copy_link UTM sessions and downstream item-card clicks before/after /assets/share-category-{category_id}.svg deployment.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "category-direct-mobile-share-v1",
            "status": "active-category-direct-mobile-share-after-review",
            "hypothesis": "Category pages should produce more practical owner/reps distribution when each store-zone link can be sent as SMS/Kakao text, WhatsApp draft, or phone-native share instead of relying only on X/email/copy-link actions.",
            "next_step": "After GA4/Vercel export access is connected, compare category_message_copy, category_sms_draft, category_whatsapp_draft, and category_native_share events plus daily-visits-500-category-direct-mobile-share UTM sessions against category_copy_link and category_brief behavior.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "ranking-first-layout-v1",
            "status": "active-site-ux-after-review",
            "hypothesis": "Putting Top 3 and the main item ranking before evidence/growth/share panels should increase first-session item-card clicks and reduce owner confusion because the page behaves like a ranking dashboard instead of a long ops report.",
            "next_step": "After analytics export access is connected, compare growth_section_view order, first item_card/podium_card clicks, scroll depth, and share/copy events before/after the ranking-first layout change.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiment_backlog, {
            "experiment_id": "ranking-item-click-attribution-v1",
            "status": "active-utm-context-after-review",
            "hypothesis": "UTM-tagging core podium and ranking-card item links should make item-detail interest measurable by concrete product card and timeframe instead of relying only on generic path counts.",
            "next_step": "After GA4/Vercel export access is connected, compare growth_click item_card/podium_card events and item_detail exposures segmented by link_utm_medium=ranking_card/podium_card and daily-visits-500-{timeframe}-ranking-item-clicks campaigns.",
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
    review_visit_measurement = review.get("traffic_measurement", {}) if isinstance(review.get("traffic_measurement"), dict) else {}
    visit_measurement = review_visit_measurement if review_visit_measurement.get("status") else measure_vercel_web_analytics()
    measured = visit_measurement.get("status") == "measured"
    avg_visits = visit_measurement.get("rolling_30d_average_daily_visits") if measured else None
    goal["updated_at"] = now
    measurement = goal.setdefault("measurement_status", {})
    if isinstance(measurement, dict):
        measurement["last_checked_at"] = now
        measurement["vercel_web_analytics"] = visit_measurement
        measurement["rolling_30d_average_daily_visits"] = avg_visits
        if measured:
            measurement["provider_checked"] = (
                "Vercel Web Analytics REST API is now connected for central visit/pageview measurement. "
                f"Measured rolling {visit_measurement.get('window_days', VISIT_GOAL_WINDOW_DAYS)}d average_daily_visits={avg_visits}, "
                f"period_unique_visitors={visit_measurement.get('period_unique_visitors')}, period_pageviews={visit_measurement.get('period_pageviews')}. "
                "GA4 tag and Vercel client bridge remain provider-ready; component custom-event and some UTM breakdowns are still plan/API gated unless GA4 Data API access or Vercel custom-event export is connected. "
                f"Ranking/review metrics refreshed (weekly trend_items={metrics.get('trend_items')}, watchlist_items={metrics.get('watchlist_items')}) and regenerated top3 marketing drafts {top3_ids}."
            )
            measurement["raw_result"] = (
                f"Vercel Web Analytics visits/count: rolling_{VISIT_GOAL_WINDOW_DAYS}d_average_daily_visits={avg_visits}; "
                f"period_unique_visitors={visit_measurement.get('period_unique_visitors')}; "
                f"period_pageviews={visit_measurement.get('period_pageviews')}; "
                f"target_progress={visit_measurement.get('target_progress_percent')}%; "
                f"top_paths={visit_measurement.get('top_paths')}."
            )
            measurement["interpretation"] = (
                f"Traffic is now measured, but the hub is still far below the 500/day target: {avg_visits}/day vs 500/day "
                f"(gap {visit_measurement.get('gap_to_target_average_daily_visits')}/day). "
                "This run therefore treats distribution/channel measurement and owner-share conversion as the main growth blocker, not just instrumentation. "
                + " ".join(str(note) for note in material_changes[:2])
            ).strip()
        else:
            measurement["provider_checked"] = (
                "Attempted Vercel Web Analytics REST API measurement, but visit totals could not be read in this runtime. "
                "Client-side Vercel/GA4 instrumentation remains provider-ready. "
                f"Measurement status={visit_measurement.get('status')}; ranking metrics refreshed (weekly trend_items={metrics.get('trend_items')}, watchlist_items={metrics.get('watchlist_items')})."
            )
            measurement["raw_result"] = (
                "measurement pending: Vercel visits API failed or project context was unavailable; GA4_PROPERTY_ID plus service-account reporting access can also provide central rolling 30-day visits. "
                f"vercel_measurement_status={visit_measurement.get('status')}"
            )
            measurement["interpretation"] = (
                "Traffic progress cannot be claimed because central visit totals are unavailable. "
                "Keep client-side/provider-ready instrumentation healthy and connect GA4 Data API or Vercel Analytics reporting access. "
                + " ".join(str(note) for note in material_changes[:2])
            ).strip()
        measurement["component_funnel_status"] = (
            "custom events/UTM source breakdown measured" if measured and visit_measurement.get("custom_event_status") == "available"
            else "basic visits measured; custom event and/or UTM source breakdown still blocked by Vercel plan/API or needs GA4 Data API export"
        )

    permissions = goal.setdefault("current_permissions", {})
    if isinstance(permissions, dict):
        permissions["can_use_vercel_web_analytics"] = True
        permissions["can_read_vercel_basic_web_analytics"] = bool(measured)
        permissions["can_read_vercel_custom_event_analytics"] = bool(
            measured and visit_measurement.get("custom_event_status") == "available"
        )
        permissions["can_read_ga4_data_api"] = bool(
            env_value("GA4_PROPERTY_ID") and (env_value("GOOGLE_APPLICATION_CREDENTIALS") or env_value("GA4_SERVICE_ACCOUNT_JSON"))
        )

    providers = goal.setdefault("analytics_providers", {})
    if isinstance(providers, dict):
        vercel_provider = providers.setdefault("vercel_web_analytics", {})
        if isinstance(vercel_provider, dict):
            vercel_provider["status"] = "enabled-basic-reporting-api" if measured else "enabled-client-script-only"
            vercel_provider["reporting_api_status"] = "basic_visits_measured" if measured else str(visit_measurement.get("status"))
            vercel_provider["custom_event_api_status"] = str(visit_measurement.get("custom_event_status") or "unknown")
            vercel_provider["utm_breakdown_status"] = str(visit_measurement.get("utm_breakdown_status") or "unknown")
            vercel_provider["last_basic_measurement_at"] = now

    needs = goal.setdefault("needs_user_permission_or_credentials", [])
    if isinstance(needs, list):
        measurement_need_names = {
            "vercel_analytics_export_or_api_access",
            "ga4_property_id_with_data_api_viewer_access",
            "ga4_data_api_property_or_service_credentials",
            "vercel_pro_or_custom_event_export_access",
        }
        replacement_needs = [
            need for need in needs
            if not (
                isinstance(need, dict)
                and need.get("need") in measurement_need_names
            )
        ]
        replacement_needs.append({
            "need": "ga4_property_id_with_data_api_viewer_access",
            "why": "Basic Vercel visits are now measurable, but GA4 Data API property ID plus service-account reporting access is still needed to read growth_exposure, growth_section_view, growth_click, growth_share_copy_result, and engagement-summary funnels centrally."
        })
        replacement_needs.append({
            "need": "vercel_pro_or_custom_event_export_access",
            "why": "The Vercel REST API returns basic visits/pageviews, but custom event and some UTM breakdown queries are plan/API gated in this runtime. Needed to compare owner-share, WhatsApp/SMS, RSS, shortcut, calendar, category, and item-detail funnel performance toward 500/day."
        })
        deduped_needs: list[dict[str, Any]] = []
        seen_need_names: set[str] = set()
        for need in replacement_needs:
            if not isinstance(need, dict):
                continue
            need_name = str(need.get("need") or "").strip()
            if not need_name or need_name in seen_need_names:
                continue
            seen_need_names.add(need_name)
            deduped_needs.append(need)
        goal["needs_user_permission_or_credentials"] = deduped_needs

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
            "experiment_id": "focus-query-diversification-v1",
            "status": "active-feedback-loop-collection-quality-after-build",
            "variants": ["first_two_generic_focus_queries", "exact_plus_owner_context_plus_review_queries"],
            "success_metric": "next-loop weak-item published trend URL gains, weekly WATCHLIST reduction, and source-link engagement once analytics export is connected",
            "hypothesis": "Diversifying next_loop_focus probes should find more dated item-relevant URLs for weak BSS owner items than repeatedly querying only generic trend phrases, without scoring generated search URLs.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "coverage-gap-first-focus-v1",
            "status": "active-feedback-loop-prioritization-after-build",
            "variants": ["ranking_only_weekly_watchlist_focus", "collection_notes_missing_published_gap_first"],
            "success_metric": "missing_published_trend_items reduction, next-loop focus follow-up improvements, weekly trend_items, WATCHLIST count, and source-link engagement once analytics export is connected",
            "hypothesis": "True all-window missing published-source gaps should be prioritized before recency-only gaps so the next collector improves trust blockers that matter most to BSS owners.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "collection-evidence-regression-recovery-v1",
            "status": "active-review-quality-loop-after-build",
            "variants": ["weekly_metrics_only_review", "weekly_plus_all_window_collection_delta_review"],
            "success_metric": "collection_evidence_deltas recovery, missing_published_trend_items reduction, source-link engagement, and repeat visits once analytics export is connected",
            "hypothesis": "All-window/source delta review will make the 500/day growth loop safer by detecting lost dated evidence or source freshness even when weekly Top 3 stays unchanged.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "supplemental-trend-query-coverage-v1",
            "status": "active-collection-quality-after-build",
            "variants": ["exact_sku_news_queries_only", "bounded_item_look_published_queries_for_nails_jewelry"],
            "success_metric": "weekly trend_items, WATCHLIST count, zero-trend category count, supplemental published source-link engagement, and no increase in unsupported/search evidence claims once analytics export is connected",
            "hypothesis": "Concrete Nails/Jewelry item types are often covered in public sources through look/style language, so bounded supplemental published-source probes should lower false WATCHLIST gaps while preserving the rule that search URLs and supply listings do not create trend claims.",
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
            "experiment_id": "vercel-analytics-head-bootstrap-v1",
            "status": "active-provider-bridge-after-build",
            "variants": ["deferred_growth_js_creates_va_queue", "head_bootstrap_va_queue_plus_growth_js_script_injection"],
            "success_metric": "Vercel Analytics custom event receipt for growth_exposure, growth_click, growth_share_copy_result, and growth_engagement_summary once export access is available",
            "hypothesis": "Creating the Vercel Analytics queue in the document head before deferred growth.js runs should reduce missed first-event risk and make provider-side counts better align with local QA buffers.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "analytics-provider-health-event-v1",
            "status": "active-provider-health-after-build",
            "variants": ["silent_provider_health", "growth_provider_ready_event_plus_analyticsBridgeStatus_snapshot"],
            "success_metric": "growth_provider_ready event presence and provider-side event counts before interpreting growth_click/share/copy funnels once analytics export is available",
            "hypothesis": "Provider health events with event_schema_version=growth-event-schema-v2 should reduce false growth conclusions by showing whether GA4/Vercel bridges were actually ready on each visit before comparing CTA or repeat-visit metrics.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "basic-analytics-measurement-v1",
            "status": "active-basic-visit-measurement-after-build",
            "variants": ["provider_ready_only", "vercel_rest_api_basic_visits_plus_visible_dashboard_panel"],
            "success_metric": "rolling_30d_average_daily_visits, period_unique_visitors, pageviews, top_paths, and gap_to_500/day from Vercel Web Analytics REST API; component funnels still require GA4 Data API or Vercel custom-event export",
            "hypothesis": "Showing real measured traffic on the dashboard and in public JSON will keep growth operations honest and shift the next loop from generic instrumentation to concrete distribution and owner-share conversion work.",
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
            "experiment_id": "apify-failure-cooldown-v1",
            "status": "active-collection-resilience-after-build",
            "variants": ["retry_actor_every_loop_after_failure", "cache_first_short_cooldown_then_retry"],
            "success_metric": "fewer repeated failed Apify attempts during upstream failures, cache_age_days within policy, fresh_evidence_urls recovery after cooldown, and no unsupported trend claims",
            "hypothesis": "Using a short cooldown after a recent TikTok Shop actor failure should preserve cron/runtime stability and owner trust by labeling cache reuse explicitly while still retrying automatically after cooldown expiry.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "tiktok-source-health-label-v1",
            "status": "active-site-trust-ux-after-build",
            "variants": ["ambiguous_fresh_cached_ratio", "explicit_fresh_cached_supply_only_labels"],
            "success_metric": "evidence-gap section views, evidence_snapshot_review clicks, item-card/source-link engagement, and repeat visits once analytics export is connected",
            "hypothesis": "BSS owners will trust the ranking more when TikTok Shop freshness clearly says Fresh vs Cached supply-only instead of a ratio that can look like a score.",
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
        ensure_experiment(experiments, {
            "experiment_id": "visit-session-boundary-v1",
            "status": "active-client-side-provider-ready-after-build",
            "variants": ["persistent_local_session_id", "30_minute_visit_window_session_boundary"],
            "success_metric": "growth_exposure and growth_engagement_summary segmented by fresh session_id, visit_count, is_returning_visitor, first/current UTM, and repeat item-detail entrances once analytics export is connected",
            "hypothesis": "Renewing session_id after the 30-minute visit boundary prevents repeat owners from being collapsed into a stale browser session, improving measurement toward the 500/day goal.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "item-evidence-summary-v1",
            "status": "active-item-detail-trust-cta-after-build",
            "variants": ["detail_page_without_trust_panel", "trend_supply_watchlist_summary_with_copyable_owner_text"],
            "success_metric": "item-evidence-summary section views, source-jump clicks, evidence-summary copy results, source_domain clicks, item-detail shares, and repeat item-detail entrances once analytics export is connected",
            "hypothesis": "BSS owners and reps will trust and share item pages more when each detail page summarizes trend claim status, 14-day recency, supply validation, and watchlist references before the source list.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "timeframe-evidence-ladder-v1",
            "status": "active-site-ux-after-build",
            "variants": ["tabs_only_timeframe_navigation", "visible_evidence_window_ladder"],
            "success_metric": "growth_section_view timeframe-evidence-ladder-v1, cta_timeframe_evidence_ladder clicks, timeframe entrances via utm_medium=evidence_ladder, and repeat item-detail visits once analytics export is connected",
            "hypothesis": "Showing Weekly/Monthly/Quarterly/Yearly evidence coverage side by side should keep owners engaged during thin weekly evidence periods while preserving evidence discipline and creating measurable cross-window navigation.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "social-share-preview-card-v1",
            "status": "active-static-shareability-after-build",
            "variants": ["random_product_image_preview", "ranking_specific_top3_evidence_preview_card"],
            "success_metric": "UTM-attributed sessions from owner_share/x/email links, share/copy events, and repeat visits once analytics export is connected",
            "hypothesis": "Ranking-specific social preview images should make shared BSS owner links clearer and more trustworthy because previews show Top 3 item names plus trend/watchlist counts without unsupported claims.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "item-detail-share-card-v1",
            "status": "active-static-item-shareability-after-build",
            "variants": ["detail_pages_use_product_listing_og_image", "item_specific_evidence_status_og_twitter_card"],
            "success_metric": "item-detail UTM sessions from owner_share/x/email/message links, item_copy/message_copy events, item source-link clicks, and repeat item-detail entrances once analytics export is connected",
            "hypothesis": "Item-specific social preview cards should make shared BSS owner links more trustworthy because previews show the item name, display test, risk note, trend URL count, and WATCHLIST status instead of implying a vendor listing image is evidence.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "rss-owner-feed-v1",
            "status": "active-static-distribution-after-build",
            "variants": ["no_subscriber_feed", "weekly_owner_item_rss_feed_with_utm_links"],
            "success_metric": "utm_source=rss sessions, item-detail entrances, returning-owner visits, and share/copy events once analytics export is connected",
            "hypothesis": "A subscriber/crawler-friendly RSS feed should create another organic repeat-visit path for BSS owners and reps without requiring external SNS posting permissions.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "owner-feed-subscribe-v1",
            "status": "active-visible-repeat-visit-cta-after-build",
            "variants": ["hidden_rel_alternate_only", "visible_feed_subscribe_save_panel"],
            "success_metric": "growth_section_view owner-feed-subscribe-v1, cta_owner_feed_open clicks, feed_copy copy results, utm_source=rss sessions, and returning-owner visits once analytics export is connected",
            "hypothesis": "Making the feed path visible should increase repeat owner visits compared with an RSS feed that only exists in metadata and sitemap.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "owner-shortcut-save-v1",
            "status": "active-web-manifest-shortcut-after-build",
            "variants": ["manual_bookmark_without_manifest", "web_manifest_plus_visible_shortcut_copy_cta"],
            "success_metric": "utm_medium=shortcut and utm_source=pwa sessions, shortcut copy/open events, returning-owner visit_count, and repeat ranking entrances once analytics export is connected",
            "hypothesis": "Giving owners/reps an installable shortcut and copyable saved link should reduce friction to reopening the dashboard, supporting repeat visits toward 500/day without external posting permissions.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "owner-calendar-reminder-v1",
            "status": "active-calendar-retention-after-build",
            "variants": ["no_calendar_reminder", "weekly_ics_reminder_with_calendar_utm"],
            "success_metric": "owner-calendar-reminder section views, calendar file downloads/copy events, utm_source=calendar return visits, and repeat visitor rate once analytics export is connected",
            "hypothesis": "A weekly .ics reminder gives owners/reps a low-friction return path outside SNS and should improve repeat visits toward the 500/day goal once provider measurement is connected.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "ranking-card-evidence-badge-v1",
            "status": "active-ranking-list-trust-ux-after-build",
            "variants": ["status_visible_only_in_chips_or_detail", "card_level_trend_watchlist_badge"],
            "success_metric": "ranking-main-list item_card clicks, WATCHLIST card click quality, source-link clicks, share/copy events, and repeat visits once analytics export is connected",
            "hypothesis": "Visible Trend-backed/WATCHLIST badges on each ranking card should reduce black-box score confusion and make owner clicks more intentional without changing rank or evidence scoring.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "owner-print-sheet-v1",
            "status": "active-offline-share-sheet-after-build",
            "variants": ["dashboard_only_owner_sharing", "print_screenshot_owner_handout_with_utm_links"],
            "success_metric": "owner-print-sheet section views, owner-share-sheet page visits, print_sheet/owner_handout/category_lane UTM sessions, owner_print_sheet copy events, and repeat item-detail entrances once analytics export is connected",
            "hypothesis": "A print/screenshot-friendly handout should create practical offline and rep-distribution visits without external SNS credentials while preserving evidence discipline.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "link-destination-utm-context-v1",
            "status": "active-client-side-provider-ready-after-build",
            "variants": ["click_events_with_visible_href_only", "click_and_copy_events_with_link_destination_utm_fields"],
            "success_metric": "growth_click and growth_share_copy_result segmented by link_utm_source, link_utm_medium, link_utm_campaign, link_utm_content, destination_path, component_experiment_id, and item_id once analytics export is connected",
            "hypothesis": "BSS owner growth optimization needs destination-level UTM context on every clicked/copied link so owner_share, X, email, message, RSS, shortcut, calendar, focus-watchlist, and item-detail share paths can be compared without brittle URL parsing.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "direct-message-owner-share-v1",
            "status": "active-site-direct-share-after-build",
            "variants": ["x_email_copy_only", "sms_kakao_direct_message_copy_with_utm"],
            "success_metric": "utm_source=message sessions, share_*_message_copy results, sms_draft clicks, item-detail entrances, and returning-owner visits once analytics export is connected",
            "hypothesis": "SMS/Kakao-ready direct message copy should improve practical distribution to BSS owners and reps while remaining draft/copy-only and evidence-safe without external SNS credentials.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "native-mobile-share-v1",
            "status": "active-site-mobile-share-after-build",
            "variants": ["separate_channel_buttons_only", "native_phone_share_with_copy_fallback"],
            "success_metric": "growth_native_share_result, native_share UTM sessions, item-detail entrances, share/copy events, and returning-owner visits once analytics export is connected",
            "hypothesis": "Mobile BSS owners will forward/reopen item links more easily when a phone-native share sheet or copy fallback is available beside SMS/WhatsApp/X drafts, without granting external posting credentials.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "whatsapp-owner-share-v1",
            "status": "active-site-whatsapp-draft-after-build",
            "variants": ["sms_kakao_direct_message_only", "sms_kakao_plus_whatsapp_draft_with_utm"],
            "success_metric": "share_*_whatsapp_draft clicks, utm_source=message sessions, item-detail entrances, and returning-owner visits once analytics export is connected",
            "hypothesis": "Adding WhatsApp draft links gives owners/reps a mobile group-share path without auto-posting, improving distribution options toward the 500/day visit goal while preserving evidence-safe message copy.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "owner-5-minute-route-v1",
            "status": "active-site-ux-distribution-after-build",
            "variants": ["full_leaderboard_first", "copy_ready_three_step_store_route"],
            "success_metric": "growth_section_view owner-5-minute-route-v1, owner_route_item clicks, owner_route_copy results, route_copy UTM sessions, and item-detail entrances once analytics export is connected",
            "hypothesis": "A 5-minute owner route should convert more busy BSS owners/reps into item-detail visits and shares than asking them to interpret the full ranking first.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "category-landing-pages-v1",
            "status": "active-static-seo-shareability-after-build",
            "variants": ["ranking_anchor_only", "store_zone_category_landing_pages"],
            "success_metric": "utm_medium=category_nav/category_page sessions, category_copy_link share events, category ranking-card clicks, and repeat visits once analytics export is connected",
            "hypothesis": "Focused category pages should turn broad BSS store lanes into crawlable/shareable entry points while preserving item-only ranking discipline.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "category-brief-copy-v1",
            "status": "active-category-page-copy-ready-after-build",
            "variants": ["category_url_only_share", "copy_ready_store_zone_owner_brief"],
            "success_metric": "growth_section_view category-brief-copy-v1, category_brief_copy/email events, category_brief UTM sessions, item-card clicks from category pages, and repeat visits once analytics export is connected",
            "hypothesis": "Category pages should convert more sharing and repeat visits when each store-zone page offers a one-click brief with concrete item display/risk/evidence labels instead of only a URL.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "category-share-preview-card-v1",
            "status": "active-static-category-shareability-after-build",
            "variants": ["generic_weekly_share_image_on_category_pages", "store_zone_category_specific_og_twitter_cards"],
            "success_metric": "category_page UTM sessions, category_copy_link/share events, item-card clicks from category pages, and repeat visits once analytics export is connected",
            "hypothesis": "Store-zone-specific social preview cards should make category landing shares more trustworthy and relevant for BSS owners than the generic all-category ranking image.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "category-direct-mobile-share-v1",
            "status": "active-category-page-direct-mobile-share-after-build",
            "variants": ["category_x_email_copy_only", "category_sms_whatsapp_native_and_message_copy"],
            "success_metric": "category_message_copy, category_sms_draft, category_whatsapp_draft, category_native_share/native result events, daily-visits-500-category-direct-mobile-share UTM sessions, category page repeat visits, and downstream item-card clicks once analytics export is connected",
            "hypothesis": "Store-zone category pages should travel farther when a BSS owner or rep can forward the exact Wig/Lash/Nail/Jewelry lane by direct message or phone share, while copy keeps the rule that the category itself is not a trend claim.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "hero-owner-share-nudge-v1",
            "status": "active-homepage-distribution-after-build",
            "variants": ["share_actions_below_ranking_modules", "first_viewport_owner_quick_text_and_item_open"],
            "success_metric": "growth_section_view hero-owner-share-nudge-v1, cta_hero_owner_nudge_item clicks, weekly_hero_owner_text_copy results, native share results, and resulting item-detail/repeat visits once analytics export is connected",
            "hypothesis": "Putting one evidence-backed, copy-ready owner message in the homepage first viewport should improve distribution from very low traffic sessions without hiding evidence limits or relying on external SNS posting.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "ranking-first-layout-v1",
            "status": "active-site-ux-after-build",
            "variants": ["ops_panels_before_ranking", "top3_and_main_list_before_supporting_modules"],
            "success_metric": "first-session podium_card/item_card clicks, ranking-main-list section views, scroll depth to support modules, share/copy events, and repeat visits once analytics export is connected",
            "hypothesis": "A ranking-first layout should fit busy BSS owner behavior better by showing concrete product picks before secondary evidence, focus, share, feed, shortcut, and calendar panels.",
            "last_refreshed_at": now,
        })
        ensure_experiment(experiments, {
            "experiment_id": "ranking-item-click-attribution-v1",
            "status": "active-utm-context-after-build",
            "variants": ["untagged_internal_item_links", "podium_and_ranking_card_item_links_with_utm_context"],
            "success_metric": "item-detail exposures and visits segmented by utm_medium=podium_card vs ranking_card, item_card clicks, source-link clicks, and repeat visits once GA4/Vercel export access is connected",
            "hypothesis": "Adding UTM context to core ranking-card item links should make the 500/day growth loop more actionable by showing which concrete BSS product cards create item-detail interest, without changing evidence scoring or trend claims.",
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
            "traffic_measurement",
            "coverage_deltas",
            "collection_evidence_deltas",
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
                "focus_source": item.get("focus_source"),
                "collection_gap": item.get("collection_gap"),
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
                "focus_source": item.get("focus_source"),
                "collection_gap": item.get("collection_gap"),
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
