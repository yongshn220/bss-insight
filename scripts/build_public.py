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
    "good_points",
    "improvement_points",
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
