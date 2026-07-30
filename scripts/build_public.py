#!/usr/bin/env python3
"""Copy the generated static site into ./public for Vercel."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"

COPY_PATHS = [
    "index.html",
    "assets",
    "rankings",
    "items",
]

PUBLIC_DATA_FILES = [
    "rankings.json",
    "operations_review.json",
    "next_loop_focus.json",
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


def copy_public_data() -> None:
    """Expose selected lightweight JSON artifacts for live verification/debugging."""
    data_dst = PUBLIC / "data"
    data_dst.mkdir(parents=True, exist_ok=True)
    for filename in PUBLIC_DATA_FILES:
        src = ROOT / "data" / filename
        if src.exists():
            shutil.copy2(src, data_dst / filename)


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
