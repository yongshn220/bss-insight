#!/usr/bin/env python3
"""Build item-first BSS jewelry/accessory trend rankings.

Public-data MVP: uses Google News RSS for fetchable signals and keeps structured
reference links for TikTok, Pinterest, X/Twitter, Reddit, Amazon, Google Trends,
BSS online stores, and wholesale/vendor pages. The goal is ranking + evidence,
not a prose trend report.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import html
import json
import math
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RANKINGS_PATH = DATA_DIR / "rankings.json"
HISTORY_PATH = DATA_DIR / "ranking_history.json"
RUNS_DIR = DATA_DIR / "ranking_runs"

USER_AGENT = "Mozilla/5.0 (compatible; BSS-Retail-Trend-Rankings/0.1; +https://gns.local)"
CURRENT_DATE = dt.date.today()
CURRENT_MONTH = CURRENT_DATE.month

TIMEFRAMES = {
    "weekly": {"label": "Weekly", "days": 14, "description": "최근 2주 중심의 빠른 신호"},
    "monthly": {"label": "Monthly", "days": 45, "description": "최근 1~1.5개월의 반복 신호"},
    "quarterly": {"label": "Quarterly", "days": 120, "description": "분기 단위로 유지되는 흐름"},
    "yearly": {"label": "Yearly", "days": 365, "description": "연간 큰 방향과 기본 수요"},
}

MAGAZINE_PUBLISHERS = {
    "vogue", "elle", "harper", "bazaar", "glamour", "who what wear", "byrdie", "allure",
    "essence", "the cut", "instyle", "refinery29", "cosmopolitan", "people", "teen vogue",
}
GENERIC_RELEVANCE_TOKENS = {
    "jewelry", "jewellery", "fashion", "trend", "trends", "accessory", "accessories",
    "earring", "earrings", "necklace", "necklaces", "pendant", "pendants", "bracelet",
    "bracelets", "gold", "silver", "hair", "rings", "ring", "sets", "set", "small", "large",
}
ITEM_PHRASE_RULES = {
    "hair-beads": ["hair bead", "hair beads", "braid bead", "braid beads", "beads for braids"],
    "hair-charms": ["hair charm", "hair charms", "braid charm", "braid charms", "loc charm", "loc charms"],
    "charm-bracelets": ["charm bracelet", "charm bracelets"],
    "initial-pendant-necklaces": ["initial necklace", "initial pendant", "letter pendant"],
    "butterfly-pendant-necklaces": ["butterfly necklace", "butterfly pendant"],
    "heart-pendant-necklaces": ["heart necklace", "heart pendant"],
    "cross-pendant-necklaces": ["cross necklace", "cross pendant"],
    "layered-chain-necklaces": ["layered necklace", "layered chain"],
}

CATEGORIES: list[dict[str, Any]] = [
    {
        "id": "earrings",
        "name": "Earrings",
        "description": "BSS에서 가장 look completion이 빠른 귀걸이 카테고리",
        "items": [
            {"id": "gold-hoop-earrings", "name": "Gold Hoop Earrings", "aliases": ["gold hoops", "hoop earrings", "large gold hoops"], "bss_fit": 5, "season_months": [1,2,3,4,5,6,7,8,9,10,11,12], "display_tip": "계산대 근처와 front jewelry wall에 size ladder로 진열", "risk": "도난보다 사이즈/컬러 선택 폭 관리가 중요", "owner_message_en": "Gold hoops are an easy add-on that completes wigs, braids, ponytails, and everyday looks."},
            {"id": "bamboo-hoop-earrings", "name": "Bamboo / Door Knocker Hoops", "aliases": ["bamboo hoops", "door knocker earrings", "oversized bamboo earrings"], "bss_fit": 4, "season_months": [3,4,5,6,7,8,9,10], "display_tip": "urban/classic style 섹션으로 gold hoop 옆에 배치", "risk": "너무 큰 사이즈만 두면 회전이 느릴 수 있음", "owner_message_en": "Bamboo hoops give customers a bold urban look with strong visual impact."},
            {"id": "rhinestone-earrings", "name": "Rhinestone / Sparkle Earrings", "aliases": ["rhinestone earrings", "sparkle earrings", "crystal earrings"], "bss_fit": 4, "season_months": [2,3,4,5,6,11,12], "display_tip": "lash/nail/prom sign 근처, 직원 시야 안 작은 display", "risk": "작은 고광택 상품은 shrink 주의", "owner_message_en": "Sparkle earrings are perfect for prom, graduation, birthday, lash, and full glam looks."},
            {"id": "stud-earrings", "name": "Stud Earrings", "aliases": ["stud earrings", "small studs", "cz studs"], "bss_fit": 4, "season_months": [1,2,3,4,5,6,7,8,9,10,11,12], "display_tip": "계산대 counter tray 또는 carded display", "risk": "작아서 분실/도난 관리 필요", "owner_message_en": "Studs are simple replacement items customers can pick up anytime."},
            {"id": "statement-earrings", "name": "Statement Earrings", "aliases": ["statement earrings", "bold earrings", "large earrings"], "bss_fit": 3, "season_months": [3,4,5,6,7,11,12], "display_tip": "birthday/event look 섹션에 3~5 style만 선별", "risk": "취향 편차가 커서 과다 재고 주의", "owner_message_en": "Statement earrings work best as a small event and birthday look section."},
        ],
    },
    {
        "id": "necklaces-pendants",
        "name": "Necklaces & Pendants",
        "description": "faith, gift, birthday, personal style과 연결되는 목걸이/펜던트",
        "items": [
            {"id": "initial-pendant-necklaces", "name": "Initial Pendant Necklaces", "aliases": ["initial necklace", "initial pendant", "letter pendant necklace"], "bss_fit": 4, "season_months": [1,2,3,4,5,6,7,8,9,10,11,12], "display_tip": "A-Z letter를 과하게 깔지 말고 인기 이니셜 중심으로 carded display", "risk": "이니셜 재고 편차와 missing letters 관리", "owner_message_en": "Initial pendants feel personal, giftable, and easy to add to everyday outfits."},
            {"id": "cross-pendant-necklaces", "name": "Cross Pendant Necklaces", "aliases": ["cross necklace", "cross pendant", "faith necklace"], "bss_fit": 4, "season_months": [1,2,3,4,5,11,12], "display_tip": "church/event/classic jewelry 쪽에 gold/silver로 구분", "risk": "religious motif는 지역/고객층별 반응 차이", "owner_message_en": "Cross pendants connect with faith, gifts, church, and polished event looks."},
            {"id": "heart-pendant-necklaces", "name": "Heart Pendant Necklaces", "aliases": ["heart necklace", "heart pendant", "love necklace"], "bss_fit": 4, "season_months": [1,2,5,11,12], "display_tip": "Valentine, Mother’s Day, gift table에 seasonally 강조", "risk": "시즌 지나면 회전 둔화", "owner_message_en": "Heart pendants are simple giftable pieces for Valentine's, birthday, and everyday looks."},
            {"id": "butterfly-pendant-necklaces", "name": "Butterfly Pendant Necklaces", "aliases": ["butterfly necklace", "butterfly pendant", "y2k butterfly jewelry"], "bss_fit": 3, "season_months": [3,4,5,6,7,8], "display_tip": "young trend shopper 섹션에 silver/gold mixed로 소량", "risk": "micro-trend라 과다 재고 위험", "owner_message_en": "Butterfly pendants work for younger shoppers looking for a cute Y2K-style detail."},
            {"id": "layered-chain-necklaces", "name": "Layered Chain Necklaces", "aliases": ["layered necklace", "layered chain", "gold layered necklace"], "bss_fit": 3, "season_months": [3,4,5,6,7,8,11,12], "display_tip": "complete outfit / birthday look 섹션에 2~3 style만", "risk": "엉킴/포장 손상 주의", "owner_message_en": "Layered chains help customers finish birthday, vacation, and night-out outfits."},
        ],
    },
    {
        "id": "hair-jewelry",
        "name": "Hair Jewelry",
        "description": "braids, locs, protective style과 직접 연결되는 hair accessory jewelry",
        "items": [
            {"id": "braid-cuffs", "name": "Braid Cuffs", "aliases": ["braid cuffs", "hair cuffs", "gold braid cuffs"], "bss_fit": 5, "season_months": [3,4,5,6,7,8,9], "display_tip": "braid hair 쪽에는 sign, 실제 상품은 직원 시야 안 counter/front area", "risk": "작은 금속 상품이라 shrink 주의", "owner_message_en": "Braid cuffs let customers refresh knotless braids, box braids, and locs with a small add-on."},
            {"id": "hair-charms", "name": "Hair Charms", "aliases": ["hair charms", "braid charms", "loc charms"], "bss_fit": 4, "season_months": [3,4,5,6,7,8,9], "display_tip": "cuffs와 함께 gold/silver/charm motif별로 carded pack", "risk": "너무 많은 motif는 count 관리 어려움", "owner_message_en": "Hair charms add personality to braids and locs without changing the whole style."},
            {"id": "loc-jewelry", "name": "Loc Jewelry", "aliases": ["loc jewelry", "dreadlock jewelry", "loc cuffs"], "bss_fit": 4, "season_months": [1,2,3,4,5,6,7,8,9,10,11,12], "display_tip": "protective style / natural hair sign과 함께 소량", "risk": "지역별 loc 고객 비중 차이", "owner_message_en": "Loc jewelry is a small way for customers to personalize long-lasting styles."},
            {"id": "hair-beads", "name": "Hair Beads", "aliases": ["hair beads", "braid beads", "beads for braids"], "bss_fit": 4, "season_months": [5,6,7,8,9], "display_tip": "kids/back-to-school/vacation braid section으로 시즌 강조", "risk": "컬러/사이즈 SKU 증가 주의", "owner_message_en": "Hair beads are seasonal, fun add-ons for braids, kids styles, and vacation hair."},
        ],
    },
    {
        "id": "anklets-body",
        "name": "Anklets & Body Jewelry",
        "description": "summer, vacation, sandal, festival look과 연결되는 seasonal add-on",
        "items": [
            {"id": "anklets", "name": "Anklets", "aliases": ["anklets", "anklet jewelry", "gold anklet"], "bss_fit": 4, "season_months": [4,5,6,7,8], "display_tip": "계산대 근처 summer/vacation tray에 $2.99~$7.99 가격대", "risk": "시즌성 강함", "owner_message_en": "Anklets are easy summer add-ons for sandals, vacation, birthday, and nail looks."},
            {"id": "beaded-anklets", "name": "Beaded Anklets", "aliases": ["beaded anklet", "colorful anklet", "summer beaded anklet"], "bss_fit": 3, "season_months": [5,6,7,8], "display_tip": "vacation/sandal look과 묶어 소량 테스트", "risk": "컬러 취향 편차", "owner_message_en": "Beaded anklets add a playful summer and vacation detail."},
            {"id": "body-jewelry", "name": "Body Jewelry / Piercing", "aliases": ["body jewelry", "piercing jewelry", "belly ring"], "bss_fit": 3, "season_months": [4,5,6,7,8], "display_tip": "잠금 display 또는 직원 시야 안 carded display", "risk": "도난/shrink와 위생/반품 정책 명확화 필요", "owner_message_en": "Body jewelry is a niche but useful add-on for younger vacation and festival shoppers."},
            {"id": "toe-rings", "name": "Toe Rings", "aliases": ["toe rings", "foot jewelry", "sandal jewelry"], "bss_fit": 2, "season_months": [5,6,7,8], "display_tip": "anklet 옆에 아주 작게 테스트", "risk": "niche item이라 과다 재고 금지", "owner_message_en": "Toe rings are a small seasonal test next to anklets and sandal accessories."},
        ],
    },
    {
        "id": "rings-bracelets",
        "name": "Rings & Bracelets",
        "description": "nail look, hand styling, giftable small accessory",
        "items": [
            {"id": "ring-sets", "name": "Ring Sets", "aliases": ["ring sets", "stack rings", "fashion ring set"], "bss_fit": 3, "season_months": [1,2,3,4,5,6,7,8,11,12], "display_tip": "nail/lash 근처보다는 직원 시야 안 carded display", "risk": "도난과 사이즈 이슈", "owner_message_en": "Ring sets connect well with acrylic nails, selfies, and glam looks, but need shrink-aware display."},
            {"id": "stack-rings", "name": "Stack Rings", "aliases": ["stack rings", "stackable rings", "gold stack rings"], "bss_fit": 3, "season_months": [1,2,3,4,5,6,7,8,11,12], "display_tip": "ring set보다 적은 SKU로 carded pack 테스트", "risk": "사이즈/도난 관리", "owner_message_en": "Stack rings are a low-ticket way to pair with nail inspo and hand photos."},
            {"id": "charm-bracelets", "name": "Charm Bracelets", "aliases": ["charm bracelet", "gold charm bracelet", "fashion bracelet"], "bss_fit": 3, "season_months": [2,5,6,7,11,12], "display_tip": "giftable table이나 register add-on으로 소량", "risk": "motif별 회전 차이", "owner_message_en": "Charm bracelets are giftable add-ons for birthdays, holidays, and younger shoppers."},
        ],
    },
    {
        "id": "sets-occasion",
        "name": "Sets & Occasion Jewelry",
        "description": "church, event, prom, graduation, holiday에 맞춘 세트/occasion 상품",
        "items": [
            {"id": "pearl-jewelry-sets", "name": "Pearl Jewelry Sets", "aliases": ["pearl jewelry set", "pearl necklace earrings", "classic pearl set"], "bss_fit": 3, "season_months": [3,4,5,11,12], "display_tip": "church/event/mature customer section으로 깔끔하게", "risk": "젊은 trend item보다는 event 중심", "owner_message_en": "Pearl sets work for church, weddings, family events, and classic polished looks."},
            {"id": "rhinestone-necklace-sets", "name": "Rhinestone Necklace Sets", "aliases": ["rhinestone necklace set", "crystal jewelry set", "prom jewelry set"], "bss_fit": 3, "season_months": [2,3,4,5,6,11,12], "display_tip": "prom/graduation/holiday sign과 함께 high-visibility but staff-visible display", "risk": "도난과 파손 관리", "owner_message_en": "Rhinestone sets help shoppers finish prom, graduation, birthday, and holiday glam looks."},
        ],
    },
]


def flatten_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for cat in CATEGORIES:
        for item in cat["items"]:
            merged = dict(item)
            merged["category_id"] = cat["id"]
            merged["category_name"] = cat["name"]
            items.append(merged)
    return items


def fetch(url: str, timeout: int = 12) -> tuple[int | None, str, str | None]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(500_000)
            charset = resp.headers.get_content_charset() or "utf-8"
            return getattr(resp, "status", 200), raw.decode(charset, errors="replace"), None
    except Exception as exc:
        return None, "", f"{type(exc).__name__}: {exc}"


def google_news_rss(query: str, days: int, limit: int = 8) -> list[dict[str, Any]]:
    q = f"{query} when:{days}d"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    status, text, error = fetch(url)
    if error or not text:
        return [{"source_type": "news_magazine", "query": query, "url": url, "error": error or f"HTTP {status}"}]
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return [{"source_type": "news_magazine", "query": query, "url": url, "error": f"XML parse error: {exc}"}]
    items: list[dict[str, Any]] = []
    for node in root.findall("./channel/item")[:limit]:
        title = html.unescape((node.findtext("title") or "").strip())
        link = (node.findtext("link") or "").strip()
        pub = (node.findtext("pubDate") or "").strip()
        desc = re.sub("<.*?>", " ", html.unescape(node.findtext("description") or ""))
        desc = re.sub(r"\s+", " ", desc).strip()
        publisher = title.rsplit(" - ", 1)[-1] if " - " in title else ""
        lower_pub = publisher.lower()
        source_kind = "magazine" if any(m in lower_pub for m in MAGAZINE_PUBLISHERS) else "news"
        pub_date = None
        try:
            parsed = email.utils.parsedate_to_datetime(pub)
            pub_date = parsed.date().isoformat()
        except Exception:
            pass
        items.append({
            "source_type": "news_magazine",
            "source_kind": source_kind,
            "query": query,
            "title": title,
            "publisher": publisher,
            "url": link,
            "published": pub,
            "published_date": pub_date,
            "snippet": desc[:260],
        })
    return items


def qurl(base: str, query: str) -> str:
    return base + urllib.parse.quote_plus(query)


def manual_references(item: dict[str, Any]) -> list[dict[str, Any]]:
    query = item["name"]
    tag = re.sub(r"[^a-z0-9]", "", item["aliases"][0].lower())
    encoded = urllib.parse.quote_plus(query)
    return [
        {"source_type": "sns", "source_kind": "tiktok", "title": f"TikTok search: {query}", "url": f"https://www.tiktok.com/search?q={encoded}", "summary": "SNS short-video look and styling signal"},
        {"source_type": "sns", "source_kind": "tiktok_tag", "title": f"TikTok hashtag: #{tag}", "url": f"https://www.tiktok.com/tag/{tag}", "summary": "Hashtag watchlist for visual momentum"},
        {"source_type": "visual", "source_kind": "pinterest", "title": f"Pinterest search: {query}", "url": f"https://www.pinterest.com/search/pins/?q={encoded}", "summary": "Visual outfit/look signal"},
        {"source_type": "social", "source_kind": "x_twitter", "title": f"X/Twitter search: {query}", "url": f"https://twitter.com/search?q={encoded}&src=typed_query&f=live", "summary": "Real-time public conversation watchlist"},
        {"source_type": "community", "source_kind": "reddit", "title": f"Reddit search: {query}", "url": f"https://www.reddit.com/search/?q={encoded}", "summary": "Community discussion and customer language watchlist"},
        {"source_type": "marketplace", "source_kind": "amazon", "title": f"Amazon search: {query}", "url": f"https://www.amazon.com/s?k={encoded}", "summary": "Marketplace assortment/review signal"},
        {"source_type": "search_interest", "source_kind": "google_trends", "title": f"Google Trends: {query}", "url": f"https://trends.google.com/trends/explore?geo=US&q={encoded}", "summary": "Search interest reference link"},
        {"source_type": "bss_online_store", "source_kind": "samsbeauty", "title": f"SamsBeauty search: {query}", "url": f"https://www.samsbeauty.com/service/search?q={encoded}", "summary": "BSS online store category/assortment check"},
        {"source_type": "bss_online_store", "source_kind": "ebonyline", "title": f"Ebonyline search: {query}", "url": f"https://www.ebonyline.com/search?q={encoded}", "summary": "BSS online store category/assortment check"},
        {"source_type": "bss_online_store", "source_kind": "beauty_of_new_york", "title": f"Beauty of New York search: {query}", "url": f"https://www.beautyofnewyork.com/search?q={encoded}", "summary": "BSS online store category/assortment check"},
        {"source_type": "wholesale", "source_kind": "nihao", "title": f"Nihao Jewelry search: {query}", "url": f"https://www.nihaojewelry.com/search?q={encoded}", "summary": "Wholesale supply-side assortment check"},
        {"source_type": "wholesale", "source_kind": "judson", "title": f"Judson search: {query}", "url": f"https://www.judson.biz/search?q={encoded}", "summary": "Wholesale supply-side assortment check"},
    ]


def relevant_news(item: dict[str, Any], days: int) -> list[dict[str, Any]]:
    aliases = [item["name"], *item.get("aliases", [])]
    query = f"({aliases[0]}) jewelry trend OR TikTok OR Pinterest OR Amazon"
    results = google_news_rss(query, days=days, limit=8)
    keyword_blob = " ".join(a.lower() for a in aliases)
    kept = []
    for result in results:
        if result.get("error"):
            kept.append(result)
            continue
        hay = " ".join(str(result.get(k, "")).lower() for k in ["title", "snippet", "publisher"])
        # Keep only item-relevant results. A generic magazine jewelry article is useful
        # context, but it should not rank an item unless the item/alias appears.
        phrase_rules = ITEM_PHRASE_RULES.get(item["id"], [])
        if phrase_rules:
            if any(phrase in hay for phrase in phrase_rules):
                kept.append(result)
            continue
        raw_tokens = set(re.split(r"\W+", keyword_blob + " " + item["id"].replace("-", " ")))
        alias_tokens = [t for t in raw_tokens if len(t) >= 4 and t not in GENERIC_RELEVANCE_TOKENS]
        if not alias_tokens:
            alias_tokens = [t for t in raw_tokens if len(t) >= 4]
        if any(tok in hay or (tok.endswith("s") and tok[:-1] in hay) for tok in alias_tokens):
            kept.append(result)
    return kept[:6]


def previous_snapshot() -> dict[str, Any] | None:
    if not HISTORY_PATH.exists():
        return None
    try:
        history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    runs = history.get("runs", [])
    return runs[0] if runs else None


def previous_lookup(prev: dict[str, Any] | None, timeframe: str) -> dict[str, dict[str, Any]]:
    if not prev:
        return {}
    rows = prev.get("rankings", {}).get(timeframe, [])
    return {row.get("item_id"): row for row in rows}


def score_item(item: dict[str, Any], timeframe: str, news: list[dict[str, Any]], manual_refs: list[dict[str, Any]], prev_row: dict[str, Any] | None) -> dict[str, Any]:
    usable_news = [n for n in news if not n.get("error")]
    magazine_count = sum(1 for n in usable_news if n.get("source_kind") == "magazine")
    news_count = len(usable_news)
    source_types = {r["source_type"] for r in manual_refs} | ({"news_magazine"} if usable_news else set())
    diversity = len(source_types)
    seasonal = CURRENT_MONTH in set(item.get("season_months", []))
    bss_fit = int(item.get("bss_fit", 3))

    raw = 0
    raw += bss_fit * 8
    raw += min(24, news_count * 6)
    raw += min(8, magazine_count * 3)
    # Manual reference layers are useful, but mostly equal across items in this MVP;
    # keep their score modest so rankings are driven by item-specific evidence.
    raw += min(8, diversity)
    raw += 10 if seasonal else 0
    if timeframe == "weekly" and seasonal:
        raw += 4
    if item["category_id"] == "hair-jewelry" and CURRENT_MONTH in [6, 7, 8, 9]:
        raw += 4
    score = max(1, min(100, raw))

    previous_score = (prev_row or {}).get("score")
    previous_rank = (prev_row or {}).get("rank")
    if previous_score is None:
        momentum = "new"
        score_change = None
    else:
        score_change = round(score - float(previous_score), 1)
        if score_change >= 5:
            momentum = "rising"
        elif score_change <= -5:
            momentum = "falling"
        else:
            momentum = "stable"

    evidence_summary = []
    if usable_news:
        evidence_summary.append(f"뉴스/매거진 {news_count}개 신호")
    if magazine_count:
        evidence_summary.append(f"패션/뷰티 매거진 {magazine_count}개 포함")
    evidence_summary.append(f"참조 source layer {diversity}종")
    if seasonal:
        evidence_summary.append("현재 시즌 적합도 높음")
    evidence_summary.append(f"BSS 적합도 {bss_fit}/5")

    why = f"{item['name']}은 {item['category_name']} 카테고리에서 BSS 고객의 look completion/add-on 구매와 연결됩니다. " + \
        "; ".join(evidence_summary) + "."
    return {
        "item_id": item["id"],
        "item_name": item["name"],
        "category_id": item["category_id"],
        "category_name": item["category_name"],
        "score": round(score, 1),
        "momentum": momentum,
        "score_change": score_change,
        "previous_rank": previous_rank,
        "bss_fit": bss_fit,
        "seasonal_now": seasonal,
        "reason_summary": why,
        "evidence_summary": evidence_summary,
        "display_tip": item["display_tip"],
        "risk": item["risk"],
        "owner_message_en": item["owner_message_en"],
        "news_evidence": usable_news,
        "manual_references": manual_refs,
        "source_counts": {
            "news_magazine": news_count,
            "magazine": magazine_count,
            "manual_references": len(manual_refs),
            "source_layers": diversity,
        },
    }


def build_rankings() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    items = flatten_items()
    prev = previous_snapshot()
    output: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "date": CURRENT_DATE.isoformat(),
        "title": "BSS Item Trend Rankings",
        "methodology": {
            "summary": "Item-only rankings across weekly/monthly/quarterly/yearly windows using public signals and structured reference links.",
            "score_components": ["BSS fit", "news/magazine evidence", "source diversity", "seasonality", "historical momentum"],
            "limitations": [
                "TikTok/X/Amazon/Google Trends are included as public reference links in this MVP; deeper APIs/login can be added later.",
                "Rankings are directional trend intelligence for retail owners, not guaranteed sales forecasts.",
                "Historical movement becomes more meaningful after several scheduled runs.",
            ],
        },
        "categories": [{"id": c["id"], "name": c["name"], "description": c["description"]} for c in CATEGORIES],
        "timeframes": TIMEFRAMES,
        "rankings": {},
    }

    for timeframe, cfg in TIMEFRAMES.items():
        prev_by_item = previous_lookup(prev, timeframe)
        rows = []
        for item in items:
            news = relevant_news(item, days=cfg["days"])
            refs = manual_references(item)
            row = score_item(item, timeframe, news, refs, prev_by_item.get(item["id"]))
            rows.append(row)
        rows.sort(key=lambda r: (r["score"], r["source_counts"]["news_magazine"], r["bss_fit"]), reverse=True)
        for idx, row in enumerate(rows, start=1):
            row["rank"] = idx
            if row.get("previous_rank") is not None:
                row["rank_change"] = int(row["previous_rank"]) - idx
            else:
                row["rank_change"] = None
        output["rankings"][timeframe] = rows

    RANKINGS_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    run_path = RUNS_DIR / f"rankings-{CURRENT_DATE.isoformat()}.json"
    run_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    history = {"runs": []}
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = {"runs": []}
    compact = {
        "generated_at": output["generated_at"],
        "date": output["date"],
        "rankings": {
            tf: [{"item_id": r["item_id"], "item_name": r["item_name"], "rank": r["rank"], "score": r["score"], "category_id": r["category_id"]} for r in rows]
            for tf, rows in output["rankings"].items()
        },
    }
    history.setdefault("runs", []).insert(0, compact)
    history["runs"] = history["runs"][:104]
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> int:
    rankings = build_rankings()
    summary = {
        "generated_at": rankings["generated_at"],
        "items": sum(len(c["items"]) for c in CATEGORIES),
        "timeframes": list(TIMEFRAMES),
        "top_weekly": [
            {"rank": r["rank"], "item": r["item_name"], "score": r["score"], "category": r["category_name"]}
            for r in rankings["rankings"]["weekly"][:10]
        ],
        "path": str(RANKINGS_PATH),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
