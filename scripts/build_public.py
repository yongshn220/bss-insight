#!/usr/bin/env python3
"""Copy the generated static site into ./public for Vercel."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PUBLIC = ROOT / "public"

COPY_PATHS = [
    "index.html",
    "robots.txt",
    "sitemap.xml",
    "assets",
    "rankings",
    "items",
]

PUBLIC_REVIEW_FIELDS = [
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

PUBLIC_COLLECTION_FIELDS = [
    "generated_at",
    "date",
    "source_health",
    "evidence_totals",
    "coverage_gaps",
    "source_cap_policy",
    "limitations",
    "next_actions",
]

PUBLIC_GROWTH_GOAL_FIELDS = [
    "goal_id",
    "created_at",
    "updated_at",
    "primary_goal",
    "measurement_status",
    "north_star",
    "growth_channels",
    "guardrails",
    "current_permissions",
    "analytics_providers",
    "sns_strategy",
    "needs_user_permission_or_credentials",
    "initial_experiments",
    "reporting",
]

PUBLIC_SNS_POSTING_RULE_FIELDS = [
    "updated_at",
    "goal_id",
    "status",
    "primary_channel",
    "posting_rule",
    "recommended_post_template",
    "weekly_thread_template",
    "measurement",
]

PUBLIC_MARKETING_FIELDS = [
    "updated_at",
    "goal_id",
    "status",
    "principle",
    "active_campaigns",
    "experiment_backlog",
    "permission_requests",
]

PUBLIC_NEXT_LOOP_FOCUS_FIELDS = [
    "updated_at",
    "source_review",
    "reason",
    "focus_items",
    "qa_focus",
]


def copy_path(name: str) -> None:
    src = ROOT / name
    dst = PUBLIC / name
    if not src.exists():
        raise FileNotFoundError(f"Missing generated path: {src}")
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def public_review_payload(review: dict[str, Any]) -> dict[str, Any]:
    payload = {field: review.get(field) for field in PUBLIC_REVIEW_FIELDS if field in review}
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


def public_collection_notes_payload(notes: dict[str, Any]) -> dict[str, Any]:
    return {field: notes.get(field) for field in PUBLIC_COLLECTION_FIELDS if field in notes}


def public_growth_goal_payload(goal: dict[str, Any]) -> dict[str, Any]:
    return {field: goal.get(field) for field in PUBLIC_GROWTH_GOAL_FIELDS if field in goal}


def public_marketing_payload(marketing: dict[str, Any]) -> dict[str, Any]:
    return {field: marketing.get(field) for field in PUBLIC_MARKETING_FIELDS if field in marketing}


def public_sns_posting_rules_payload(rules: dict[str, Any]) -> dict[str, Any]:
    return {field: rules.get(field) for field in PUBLIC_SNS_POSTING_RULE_FIELDS if field in rules}


def public_next_loop_focus_payload(focus: dict[str, Any]) -> dict[str, Any]:
    payload = {field: focus.get(field) for field in PUBLIC_NEXT_LOOP_FOCUS_FIELDS if field in focus}
    focus_items = payload.get("focus_items")
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


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def copy_public_data() -> None:
    """Expose only lightweight/sanitized JSON artifacts for live verification."""
    data_dst = PUBLIC / "data"
    data_dst.mkdir(parents=True, exist_ok=True)

    rankings_src = DATA_DIR / "rankings.json"
    if rankings_src.is_file() and not rankings_src.is_symlink():
        shutil.copy2(rankings_src, data_dst / "rankings.json")

    review = load_json(DATA_DIR / "operations_review.json")
    if review:
        write_json(data_dst / "operations_review_public.json", public_review_payload(review))

    collection_notes = load_json(DATA_DIR / "collection_notes.json")
    if collection_notes:
        write_json(data_dst / "collection_notes_public.json", public_collection_notes_payload(collection_notes))

    growth_goal = load_json(DATA_DIR / "growth_goal.json")
    if growth_goal:
        write_json(data_dst / "growth_goal_public.json", public_growth_goal_payload(growth_goal))

    marketing = load_json(DATA_DIR / "marketing_backlog.json")
    if marketing:
        write_json(data_dst / "marketing_backlog_public.json", public_marketing_payload(marketing))

    sns_rules = load_json(DATA_DIR / "sns_posting_rules.json")
    if sns_rules:
        write_json(data_dst / "sns_posting_rules_public.json", public_sns_posting_rules_payload(sns_rules))

    next_focus = load_json(DATA_DIR / "next_loop_focus.json")
    if next_focus:
        write_json(data_dst / "next_loop_focus_public.json", public_next_loop_focus_payload(next_focus))


def main() -> int:
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    PUBLIC.mkdir(parents=True)
    for path in COPY_PATHS:
        copy_path(path)
    copy_public_data()
    print(f"Built Vercel output: {PUBLIC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
