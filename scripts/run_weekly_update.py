#!/usr/bin/env python3
"""Run one BSS item ranking update and print a concise summary."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=600)
    if result.returncode != 0:
        raise SystemExit(f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result.stdout.strip()


def main() -> None:
    collect_out = run(["python3", "scripts/collect_rankings.py"])
    build_out = run(["python3", "scripts/build_site.py"])
    public_out = run(["python3", "scripts/build_public.py"])
    rankings = json.loads((ROOT / "data" / "rankings.json").read_text(encoding="utf-8"))
    weekly = rankings.get("rankings", {}).get("weekly", [])[:10]
    print("BSS Item Rankings update completed.")
    print(f"Site root: {ROOT}")
    print(f"Generated at: {rankings.get('generated_at')}")
    print("Top weekly items:")
    for row in weekly:
        counts = row.get("source_counts", {})
        print(
            f"- #{row['rank']} {row['item_name']} | score={row['score']} | "
            f"category={row['category_name']} | momentum={row['momentum']} | "
            f"trend_urls={counts.get('trend_evidence', 0)} | "
            f"store_urls={counts.get('retail_product_evidence', 0)}"
        )
    print("Generated pages:")
    print("- index.html")
    print("- rankings/weekly.html")
    print("- rankings/monthly.html")
    print("- rankings/quarterly.html")
    print("- rankings/yearly.html")
    print("- items/*.html")


if __name__ == "__main__":
    main()
