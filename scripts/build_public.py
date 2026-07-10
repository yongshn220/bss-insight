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


def main() -> int:
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    PUBLIC.mkdir(parents=True)
    for path in COPY_PATHS:
        copy_path(path)
    print(f"Built Vercel output: {PUBLIC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
