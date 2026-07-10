#!/usr/bin/env python3
"""Build item-first BSS beauty product trend rankings.

Public-data MVP: fetches Google News RSS where possible and attaches structured
reference links for TikTok, Pinterest, X/Twitter, Reddit, Amazon, Google Trends,
BSS online stores, and wholesale/vendor pages. Rankings cover the broader Beauty
Supply Store market, not only jewelry. Ranked entries are specific product/item
types rather than broad categories.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import html
import json
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

USER_AGENT = "Mozilla/5.0 (compatible; BSS-Beauty-Trend-Rankings/0.2; +https://gns.local)"
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
    "beauty independent", "happi", "global cosmetic industry", "modern salon", "behindthechair",
}

GENERIC_RELEVANCE_TOKENS = {
    "beauty", "supply", "store", "stores", "trend", "trends", "tiktok", "amazon", "reddit",
    "hair", "wig", "wigs", "lace", "braid", "braids", "braiding", "human", "synthetic",
    "lash", "lashes", "nail", "nails", "makeup", "cosmetic", "cosmetics", "jewelry", "jewellery",
    "gold", "silver", "black", "brown", "deep", "long", "short", "large", "small", "set", "sets",
    "pack", "kit", "piece", "pieces", "inch", "inches", "style", "styles", "product", "products",
}


def item(
    id: str,
    name: str,
    aliases: list[str],
    bss_fit: int,
    season_months: list[int],
    display_tip: str,
    risk: str,
    owner_message_en: str,
    search_context: str,
) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "aliases": aliases,
        "bss_fit": bss_fit,
        "season_months": season_months,
        "display_tip": display_tip,
        "risk": risk,
        "owner_message_en": owner_message_en,
        "search_context": search_context,
    }


ALL_MONTHS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
SPRING_SUMMER = [3, 4, 5, 6, 7, 8]
SUMMER_BACK_TO_SCHOOL = [5, 6, 7, 8, 9]
HOLIDAY_EVENT = [2, 3, 4, 5, 6, 11, 12]

CATEGORIES: list[dict[str, Any]] = [
    {
        "id": "wigs-hair-pieces",
        "name": "Wigs & Hair Pieces",
        "description": "lace wig, glueless wig, ponytail 등 BSS 핵심 고관여 제품",
        "items": [
            item("glueless-pre-cut-hd-lace-wig", "Glueless Pre-Cut HD Lace Wig", ["glueless pre cut lace wig", "pre cut HD lace wig", "glueless HD lace wig"], 5, ALL_MONTHS, "wig wall 상단/신상품 구역에 glueless, pre-cut, HD lace 키워드를 크게 표기", "가격대가 높아 반품/착용 흔적/컬러 선택 관리 필요", "Glueless pre-cut lace wigs reduce install time and appeal to customers who want a salon-style look at home.", "wig beauty supply lace wig install"),
            item("13x4-hd-lace-frontal-wig", "13x4 HD Lace Frontal Wig", ["13x4 HD lace frontal wig", "13x4 lace front wig", "HD lace frontal wig"], 5, ALL_MONTHS, "human hair/lace front 섹션에서 density, length, parting space 비교가 보이게 진열", "고가 SKU라 도난·반품·컬러 재고 리스크 큼", "13x4 HD lace frontals remain a core premium wig option for customers who want a natural hairline.", "lace frontal wig human hair"),
            item("v-part-human-hair-wig", "V-Part Human Hair Wig", ["V part human hair wig", "v part wig", "leave out wig"], 4, ALL_MONTHS, "protective style과 natural leave-out look 사이 선택지로 설명 카드 배치", "leave-out 관리가 필요한 제품이라 staff 설명 필요", "V-part wigs are useful for customers who want a natural blend without a full lace install.", "v part wig natural leave out"),
            item("synthetic-lace-front-wig", "Synthetic Lace Front Wig", ["synthetic lace front wig", "synthetic wig lace front", "affordable lace front wig"], 5, ALL_MONTHS, "가격 민감 고객용 value wig wall에서 길이/컬러별 bestseller 표시", "컬러·스타일 수가 많아 dead stock 관리 필요", "Synthetic lace front wigs offer fast style changes at lower price points.", "synthetic lace front wig affordable"),
            item("drawstring-ponytail-extension", "Drawstring Ponytail Extension", ["drawstring ponytail extension", "synthetic drawstring ponytail", "curly drawstring ponytail"], 4, SPRING_SUMMER, "quick style / event look 코너에 claw clip, gel, edge brush와 함께 묶음 진열", "텍스처 매칭 실패 시 반품/불만 가능", "Drawstring ponytails are quick add-ons for customers who need a fast event or vacation hairstyle.", "drawstring ponytail extension quick hairstyle"),
        ],
    },
    {
        "id": "braiding-crochet-hair",
        "name": "Braiding & Crochet Hair",
        "description": "braiding hair, crochet hair, protective style용 반복 구매 제품",
        "items": [
            item("52-inch-pre-stretched-braiding-hair", "52 Inch Pre-Stretched Braiding Hair", ["52 inch pre stretched braiding hair", "pre stretched braiding hair 52 inch", "kanekalon pre stretched hair"], 5, SUMMER_BACK_TO_SCHOOL, "braid hair aisle에서 length/color 가격 비교가 즉시 보이게 bulk 진열", "컬러/길이 SKU 폭이 넓어 재고 회전 체크 필요", "Pre-stretched braiding hair is a repeat-purchase staple for box braids, knotless braids, and back-to-school styles.", "pre stretched braiding hair knotless braids"),
            item("human-hair-boho-braiding-bundles", "Human Hair Boho Braiding Bundles", ["human hair boho braiding hair", "boho braiding human hair bundles", "human hair curls for boho braids"], 5, SPRING_SUMMER, "boho/knotless braid sign 아래 premium add-on bundle로 분리", "가격대가 높고 품질 차이가 커서 supplier/return 관리 중요", "Human hair boho braid bundles support the curly, bohemian braid look customers are asking for.", "boho braids human hair curls"),
            item("water-wave-crochet-hair", "Water Wave Crochet Hair", ["water wave crochet hair", "water wave crochet braids", "crochet water wave hair"], 4, SPRING_SUMMER, "crochet hair wall에서 wave texture sample을 전면에 노출", "텍스처 사진과 실제 제품 차이 관리", "Water wave crochet hair gives customers a fast vacation-ready protective style.", "water wave crochet hair protective style"),
            item("butterfly-locs-crochet-hair", "Butterfly Locs Crochet Hair", ["butterfly locs crochet hair", "distressed butterfly locs", "butterfly loc crochet packs"], 4, SPRING_SUMMER, "loc/crochet 섹션에서 distressed texture를 visual card로 보여주기", "trend성 강해 과다 재고 주의", "Butterfly locs remain a recognizable protective style for younger shoppers and vacation looks.", "butterfly locs crochet hair"),
            item("passion-twist-crochet-hair", "Passion Twist Crochet Hair", ["passion twist crochet hair", "passion twists hair", "crochet passion twist"], 4, SUMMER_BACK_TO_SCHOOL, "spring twist/marley twist와 texture 비교 섹션 구성", "유사 texture SKU와 중복 재고 주의", "Passion twist crochet hair is a convenient protective style option with a soft, textured finish.", "passion twist crochet hair"),
            item("marley-twist-hair", "Marley Twist Hair", ["marley twist hair", "marley braiding hair", "afro kinky marley hair"], 4, ALL_MONTHS, "natural texture/protective style 섹션에서 staple로 유지", "지역별 natural hair 고객 비중에 따라 회전 차이", "Marley hair is a staple for twists, faux locs, and natural-texture protective styles.", "marley twist hair beauty supply"),
        ],
    },
    {
        "id": "hair-care-styling",
        "name": "Hair Care & Styling",
        "description": "edge control, lace spray, oil, mousse 등 BSS 소모성/반복 구매 제품",
        "items": [
            item("24-hour-edge-control-gel", "24 Hour Edge Control Gel", ["24 hour edge control", "edge control gel", "strong hold edge control"], 5, ALL_MONTHS, "계산대/gel aisle 양쪽에 travel size와 regular size를 함께 진열", "흰 잔여물/flake claim이 구매 반품 이유가 될 수 있음", "A strong edge control gel is a repeat add-on for wigs, braids, ponytails, and everyday styling.", "edge control gel black hair"),
            item("lace-melting-spray", "Lace Melting Spray", ["lace melting spray", "wig melting spray", "lace melt spray"], 5, ALL_MONTHS, "lace wig 구매 동선 옆에 melting band, wig cap과 bundle 제안", "접착력/피부 민감도 claim 과장 금지", "Lace melting spray is an install add-on that helps customers finish glueless and lace wig looks.", "lace melting spray wig install"),
            item("wig-adhesive-glue", "Wig Adhesive Glue", ["wig adhesive glue", "lace wig glue", "waterproof wig glue"], 4, ALL_MONTHS, "잠금 또는 직원 시야 안 진열, remover와 함께 배치", "피부 반응/반품/사용법 설명 중요", "Wig adhesive glue is a high-intent purchase for longer-wear lace installs.", "wig adhesive glue lace install"),
            item("braid-foaming-mousse", "Foaming Mousse for Braids", ["braid mousse", "foaming mousse for braids", "wrap mousse braids"], 5, SUMMER_BACK_TO_SCHOOL, "braiding hair aisle 끝cap에 edge control, oil sheen과 함께 묶음", "끈적임/flake claim 관리", "Braid mousse helps customers maintain knotless braids, box braids, twists, and loc styles.", "braid mousse knotless braids maintenance"),
            item("rosemary-mint-scalp-oil", "Rosemary Mint Scalp Oil", ["rosemary mint scalp oil", "rosemary hair oil", "mint scalp oil"], 4, ALL_MONTHS, "scalp care/hair growth 관심 제품으로 hair oil shelf eye-level에 배치", "성장 효능 과장 금지, scalp comfort 중심 설명", "Rosemary mint scalp oil taps into scalp-care and hair-growth interest while remaining a low-ticket repeat item.", "rosemary mint scalp oil hair growth"),
            item("leave-in-conditioner-spray", "Leave-In Conditioner Spray", ["leave in conditioner spray", "moisturizing leave in spray", "detangling leave in conditioner"], 4, ALL_MONTHS, "natural hair/moisture aisle에서 detangling brush와 함께 노출", "브랜드별 성분/향 선호 차이", "Leave-in spray is a practical repeat product for moisture, detangling, and protective-style prep.", "leave in conditioner spray natural hair"),
        ],
    },
    {
        "id": "lashes-brows",
        "name": "Lashes & Brows",
        "description": "strip lash, cluster lash, lash bond 등 BSS front-end add-on 제품",
        "items": [
            item("25mm-mink-strip-lashes", "25mm Mink Strip Lashes", ["25mm mink lashes", "dramatic strip lashes", "mink strip lashes"], 5, HOLIDAY_EVENT, "checkout/front cosmetic area에 length별 good/better/best로 진열", "스타일 취향 편차와 포장 훼손 주의", "25mm lashes are a visible glam add-on for birthday, prom, nightlife, and full-face looks.", "25mm mink lashes beauty supply"),
            item("cluster-lash-extension-kit", "Cluster Lash Extension Kit", ["cluster lash kit", "DIY lash extension kit", "individual cluster lashes kit"], 4, ALL_MONTHS, "DIY lash sign과 bond/seal을 같이 묶어 basket 구성", "사용법 미숙으로 불만 가능, 설명 카드 필요", "Cluster lash kits let customers try a salon-inspired lash look at home.", "cluster lash extension kit DIY"),
            item("individual-flare-lashes", "Individual Flare Lashes", ["individual flare lashes", "individual lashes", "lash flares"], 4, ALL_MONTHS, "strip lash와 구분해 natural/full volume 단계별 표시", "접착제와 함께 팔아야 구매 완성도 높음", "Individual flare lashes serve customers who want more control than a strip lash.", "individual flare lashes beauty supply"),
            item("lash-bond-and-seal", "Lash Bond and Seal", ["lash bond and seal", "bond and seal lashes", "cluster lash bond"], 4, ALL_MONTHS, "cluster lash kit 바로 옆에 필수 add-on으로 배치", "눈 주변 제품이라 안전/사용법 주의", "Bond and seal is a necessary companion product for DIY cluster lash shoppers.", "lash bond and seal cluster lashes"),
        ],
    },
    {
        "id": "nails",
        "name": "Nails",
        "description": "press-on nail, nail charm, chrome powder 등 빠른 beauty add-on 제품",
        "items": [
            item("long-coffin-press-on-nails", "Long Coffin Press-On Nails", ["long coffin press on nails", "coffin press ons", "long press on nails"], 4, HOLIDAY_EVENT, "lash/cosmetic area 근처에 shape별 top seller row 구성", "사이즈/접착력 불만과 포장 훼손 관리", "Long coffin press-ons give customers an instant glam nail look without a salon visit.", "long coffin press on nails"),
            item("short-square-press-on-nails", "Short Square Press-On Nails", ["short square press on nails", "short press ons", "square press on nails"], 4, ALL_MONTHS, "everyday/work-friendly nail option으로 long style과 분리", "너무 trend형 디자인만 두면 회전 둔화", "Short square press-ons are practical for customers who want wearable everyday nails.", "short square press on nails"),
            item("rhinestone-nail-charms", "Rhinestone Nail Charms", ["rhinestone nail charms", "nail rhinestones", "3D nail charms"], 3, HOLIDAY_EVENT, "nail glue, press-on nail 옆 작은 잠금/직원 시야 display", "작은 고마진 상품이라 shrink 주의", "Rhinestone nail charms connect with glam, prom, birthday, and DIY nail-art customers.", "rhinestone nail charms DIY nail art"),
            item("chrome-nail-powder", "Chrome Nail Powder", ["chrome nail powder", "mirror chrome powder nails", "chrome powder for nails"], 3, ALL_MONTHS, "DIY nail art shelf에 applicator/gel top coat와 함께", "사용법 설명 없으면 구매 장벽 높음", "Chrome powder supports metallic and glazed nail looks customers see on social media.", "chrome nail powder glazed nails"),
            item("cuticle-oil-pen", "Cuticle Oil Pen", ["cuticle oil pen", "nail cuticle oil pen", "portable cuticle oil"], 3, ALL_MONTHS, "checkout add-on 또는 nail tool 옆 low-ticket item", "향/성분별 회전 차이", "Cuticle oil pens are low-ticket repeat items for press-on and natural nail maintenance.", "cuticle oil pen nail care"),
        ],
    },
    {
        "id": "makeup-cosmetics",
        "name": "Makeup & Cosmetics",
        "description": "lip, eye, complexion 중심 BSS front-end 반복 구매 제품",
        "items": [
            item("clear-squeeze-tube-lip-gloss", "Clear Squeeze Tube Lip Gloss", ["clear squeeze tube lip gloss", "clear lip gloss tube", "beauty supply lip gloss"], 4, ALL_MONTHS, "계산대 impulse tray에 여러 향/finish를 작게 테스트", "누수/포장 sticky 이슈 관리", "Clear lip gloss is a low-ticket impulse item with broad customer appeal.", "clear lip gloss beauty supply"),
            item("brown-lip-liner-pencil", "Brown Lip Liner Pencil", ["brown lip liner", "dark brown lip liner", "lip liner pencil brown"], 4, ALL_MONTHS, "lip gloss 옆에 shade ladder로 진열해 combo 구매 유도", "shade mismatch와 tester 위생 관리", "Brown lip liner pairs with gloss and nude lip looks that remain popular in beauty supply stores.", "brown lip liner gloss combo"),
            item("deep-shade-setting-powder", "Deep Shade Setting Powder", ["deep setting powder", "translucent setting powder deep skin", "banana setting powder deep"], 3, ALL_MONTHS, "complexion shelf에서 shade visibility를 높이고 tester 정책 명확화", "shade range 부족 시 고객 불만", "Deep shade setting powder is important for complexion inclusivity and full-face makeup shoppers.", "setting powder deep skin tone"),
            item("waterproof-black-eyeliner-pencil", "Waterproof Black Eyeliner Pencil", ["waterproof black eyeliner pencil", "black eyeliner pencil", "waterproof eyeliner"], 4, ALL_MONTHS, "lash/eye section에서 lash glue, mascara와 함께 반복 구매 item으로 유지", "저가 SKU는 품질 편차 주의", "Black waterproof eyeliner is a staple add-on for lash and full-face looks.", "waterproof black eyeliner pencil"),
        ],
    },
    {
        "id": "tools-accessories",
        "name": "Tools & Accessories",
        "description": "bonnet, edge brush, wig grip, melting band 등 attach-rate 높은 보조 제품",
        "items": [
            item("extra-large-satin-bonnet", "Extra Large Satin Bonnet", ["extra large satin bonnet", "XL satin bonnet", "satin bonnet for braids"], 5, ALL_MONTHS, "braid/wig checkout path에 size별로 걸어 보호용 add-on 강조", "size/elastic quality 불만 관리", "XL satin bonnets protect braids, wigs, locs, and natural styles overnight.", "extra large satin bonnet braids"),
            item("edge-brush-comb-set", "Edge Brush & Comb Set", ["edge brush and comb", "edge control brush", "baby hair brush"], 5, ALL_MONTHS, "edge control 바로 옆에 2~3 price point로 배치", "저가 대량 상품이라 shrink/카운트 관리", "Edge brushes are small essentials that attach naturally to edge control and wig installs.", "edge brush comb edge control"),
            item("wig-grip-band", "Wig Grip Band", ["wig grip band", "velvet wig grip", "non slip wig band"], 4, ALL_MONTHS, "wig cap, melting band, lace spray와 같은 install accessory bay에 배치", "피부색/사이즈 옵션 부족 주의", "Wig grip bands help customers secure wigs without relying only on glue.", "wig grip band non slip"),
            item("elastic-melting-band", "Elastic Melting Band", ["lace melting band", "elastic melting band", "wig melt band"], 5, ALL_MONTHS, "lace melting spray와 바로 옆에 묶어 필수 install tool로 제안", "작은 상품이라 도난/분실 관리", "Melting bands are a small but important companion item for lace wig installs.", "lace melting band wig install"),
            item("rat-tail-comb-metal-pintail", "Rat Tail Comb with Metal Pintail", ["rat tail comb metal pintail", "metal tail comb", "parting comb"], 4, ALL_MONTHS, "braiding/tools aisle에서 parting, install prep 용도로 표시", "저가 상품이라 margin/packaging 관리", "Metal pintail combs are staple tools for parting braids, wigs, and styling prep.", "rat tail comb metal pintail"),
            item("durag-wave-cap", "Durag / Wave Cap", ["durag wave cap", "silky durag", "wave cap"], 4, ALL_MONTHS, "men's grooming/wave product 옆에 color와 material별로 진열", "색상 과다 재고와 포장 훼손 주의", "Durags and wave caps are repeat accessories for wave maintenance and protective styling.", "durag wave cap beauty supply"),
        ],
    },
    {
        "id": "jewelry-fashion-accessories",
        "name": "Jewelry & Fashion Accessories",
        "description": "BSS checkout/front wall에서 add-on으로 팔 수 있는 구체적 jewelry item",
        "items": [
            item("50mm-gold-hoop-earrings", "50mm Gold Hoop Earrings", ["50mm gold hoop earrings", "large gold hoops", "gold hoop earrings 50mm"], 5, ALL_MONTHS, "front jewelry wall에서 30/50/70mm size ladder로 진열", "도난보다 size/color mix와 재고 count 관리가 중요", "50mm gold hoops are an easy add-on that completes wigs, braids, ponytails, and everyday looks.", "50mm gold hoop earrings beauty supply"),
            item("gold-braid-cuffs-12-pack", "Gold Braid Cuffs 12-Pack", ["gold braid cuffs 12 pack", "braid cuffs gold", "hair cuffs for braids"], 5, SUMMER_BACK_TO_SCHOOL, "braid hair 쪽에는 sign, 실제 상품은 직원 시야 안 counter/front area", "작은 금속 상품이라 shrink 주의", "Gold braid cuffs let customers refresh knotless braids, box braids, and locs with a small add-on.", "gold braid cuffs knotless braids"),
            item("a-z-initial-pendant-necklace", "A-Z Initial Pendant Necklace", ["initial pendant necklace", "letter pendant necklace", "A-Z initial necklace"], 4, ALL_MONTHS, "A-Z 전체보다 인기 이니셜/금은 컬러 중심으로 carded display", "이니셜별 missing stock과 slow letters 관리", "Initial pendants feel personal, giftable, and easy to add to everyday outfits.", "initial pendant necklace gift"),
            item("rhinestone-stud-earrings-6mm", "6mm Rhinestone Stud Earrings", ["6mm rhinestone stud earrings", "CZ stud earrings 6mm", "rhinestone studs"], 4, HOLIDAY_EVENT, "lash/nail/prom sign 근처, 직원 시야 안 작은 display", "작은 고광택 상품은 shrink 주의", "6mm rhinestone studs are simple sparkle add-ons for glam, prom, and everyday looks.", "rhinestone stud earrings 6mm"),
            item("20g-surgical-steel-nose-stud", "20G Surgical Steel Nose Stud", ["20G surgical steel nose stud", "nose stud 20 gauge", "surgical steel nose piercing stud"], 3, ALL_MONTHS, "body jewelry를 broad category로 두지 말고 gauge/material별 잠금 display", "위생/반품 정책과 도난 관리 필수", "20G nose studs are specific replacement items for customers who already wear nose jewelry.", "20G surgical steel nose stud"),
            item("14g-belly-button-ring", "14G Belly Button Ring", ["14G belly button ring", "belly ring 14 gauge", "navel ring 14G"], 3, SPRING_SUMMER, "summer/body jewelry section에서 gauge/material 표기를 명확히", "위생/반품/도난 관리", "14G belly rings are seasonal body-jewelry add-ons for summer and vacation shoppers.", "14G belly button ring"),
            item("gold-stackable-ring-set", "Gold Stackable Ring Set", ["gold stackable ring set", "stack rings gold", "fashion ring set gold"], 3, HOLIDAY_EVENT, "nail look과 연결하되 직원 시야 안 carded display", "사이즈/도난 관리", "Gold stackable ring sets pair well with acrylic nails, selfies, and glam looks.", "gold stackable ring set nails"),
            item("butterfly-charm-anklet", "Butterfly Charm Anklet", ["butterfly charm anklet", "gold butterfly anklet", "summer charm anklet"], 3, SPRING_SUMMER, "summer/vacation tray에 sandal, toe ring과 함께 소량 테스트", "시즌성 강하고 small item shrink 주의", "Butterfly charm anklets are small summer add-ons for sandal, vacation, and birthday looks.", "butterfly charm anklet summer"),
        ],
    },
]


def flatten_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for cat in CATEGORIES:
        for raw_item in cat["items"]:
            merged = dict(raw_item)
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


def manual_references(row: dict[str, Any]) -> list[dict[str, Any]]:
    query = row["name"]
    encoded = urllib.parse.quote_plus(query)
    tag = re.sub(r"[^a-z0-9]", "", row["aliases"][0].lower())
    refs = [
        ("sns", "tiktok", f"TikTok search: {query}", f"https://www.tiktok.com/search?q={encoded}", "Short-video demand/look signal"),
        ("sns", "tiktok_tag", f"TikTok hashtag: #{tag}", f"https://www.tiktok.com/tag/{tag}", "Hashtag watchlist for visual momentum"),
        ("visual", "pinterest", f"Pinterest search: {query}", f"https://www.pinterest.com/search/pins/?q={encoded}", "Visual styling and product-language signal"),
        ("social", "x_twitter", f"X/Twitter search: {query}", f"https://twitter.com/search?q={encoded}&src=typed_query&f=live", "Real-time public conversation watchlist"),
        ("community", "reddit", f"Reddit search: {query}", f"https://www.reddit.com/search/?q={encoded}", "Community discussion and problem language"),
        ("marketplace", "amazon", f"Amazon search: {query}", f"https://www.amazon.com/s?k={encoded}", "Marketplace assortment/review signal"),
        ("marketplace", "walmart", f"Walmart search: {query}", f"https://www.walmart.com/search?q={encoded}", "Mass-market pricing and assortment reference"),
        ("search_interest", "google_trends", f"Google Trends: {query}", f"https://trends.google.com/trends/explore?geo=US&q={encoded}", "Search interest reference"),
        ("bss_online_store", "samsbeauty", f"SamsBeauty search: {query}", f"https://www.samsbeauty.com/service/search?q={encoded}", "BSS online store category/assortment check"),
        ("bss_online_store", "ebonyline", f"Ebonyline search: {query}", f"https://www.ebonyline.com/search?q={encoded}", "BSS online store category/assortment check"),
        ("bss_online_store", "beauty_of_new_york", f"Beauty of New York search: {query}", f"https://www.beautyofnewyork.com/search?q={encoded}", "BSS online store category/assortment check"),
        ("bss_online_store", "wigtypes", f"WigTypes search: {query}", f"https://www.wigtypes.com/search?q={encoded}", "Wigs/hair BSS online assortment check"),
        ("wholesale", "faire", f"Faire wholesale search: {query}", f"https://www.faire.com/search?q={encoded}", "Wholesale/vendor assortment check"),
        ("wholesale", "fashiongo", f"FashionGo search: {query}", f"https://www.fashiongo.net/search?q={encoded}", "Wholesale/vendor assortment check"),
    ]
    if row["category_id"] == "jewelry-fashion-accessories":
        refs.extend([
            ("wholesale", "nihao", f"Nihao Jewelry search: {query}", f"https://www.nihaojewelry.com/search?q={encoded}", "Jewelry wholesale assortment check"),
            ("wholesale", "judson", f"Judson search: {query}", f"https://www.judson.biz/search?q={encoded}", "Jewelry wholesale assortment check"),
        ])
    return [
        {"source_type": source_type, "source_kind": kind, "title": title, "url": url, "summary": summary}
        for source_type, kind, title, url, summary in refs
    ]


def important_tokens(row: dict[str, Any]) -> list[str]:
    blob = " ".join([row["name"], row["id"].replace("-", " "), *row.get("aliases", [])]).lower()
    tokens = {t for t in re.split(r"\W+", blob) if len(t) >= 4 and t not in GENERIC_RELEVANCE_TOKENS}
    # If an item is mostly generic words, keep longer generic-but-specific compounds.
    if not tokens:
        tokens = {t for t in re.split(r"\W+", blob) if len(t) >= 5}
    return sorted(tokens)


def relevant_news(row: dict[str, Any], days: int) -> list[dict[str, Any]]:
    primary = row["aliases"][0]
    query = f'"{primary}" OR "{row["name"]}" {row.get("search_context", "beauty supply")}'
    results = google_news_rss(query, days=days, limit=8)
    phrases = [a.lower() for a in [row["name"], *row.get("aliases", [])] if len(a) >= 4]
    tokens = important_tokens(row)
    kept = []
    for result in results:
        if result.get("error"):
            kept.append(result)
            continue
        hay = " ".join(str(result.get(k, "")).lower() for k in ["title", "snippet", "publisher"])
        phrase_match = any(phrase in hay for phrase in phrases)
        token_match_count = sum(1 for tok in tokens if tok in hay or (tok.endswith("s") and tok[:-1] in hay))
        if phrase_match or token_match_count >= min(2, max(1, len(tokens))):
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


def score_item(row: dict[str, Any], timeframe: str, news: list[dict[str, Any]], refs: list[dict[str, Any]], prev_row: dict[str, Any] | None) -> dict[str, Any]:
    usable_news = [n for n in news if not n.get("error")]
    magazine_count = sum(1 for n in usable_news if n.get("source_kind") == "magazine")
    news_count = len(usable_news)
    source_types = {r["source_type"] for r in refs} | ({"news_magazine"} if usable_news else set())
    diversity = len(source_types)
    seasonal = CURRENT_MONTH in set(row.get("season_months", []))
    bss_fit = int(row.get("bss_fit", 3))

    raw = 0
    raw += bss_fit * 9
    raw += min(24, news_count * 6)
    raw += min(8, magazine_count * 3)
    raw += min(10, diversity)
    raw += 10 if seasonal else 0
    if timeframe == "weekly" and seasonal:
        raw += 3
    if row["category_id"] in {"wigs-hair-pieces", "braiding-crochet-hair", "hair-care-styling", "tools-accessories"}:
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
        evidence_summary.append(f"뉴스/매거진 {news_count}개 item-specific 신호")
    if magazine_count:
        evidence_summary.append(f"패션/뷰티/업계 매거진 {magazine_count}개 포함")
    evidence_summary.append(f"참조 source layer {diversity}종")
    if seasonal:
        evidence_summary.append("현재 시즌 적합도 높음")
    evidence_summary.append(f"BSS 적합도 {bss_fit}/5")

    reason = (
        f"{row['name']}은 {row['category_name']} 카테고리의 구체적 제품 단위 item입니다. "
        + "; ".join(evidence_summary)
        + ". broad category가 아니라 실제 매장에서 SKU/상품군으로 테스트할 수 있는 단위로 랭킹했습니다."
    )

    return {
        "item_id": row["id"],
        "item_name": row["name"],
        "category_id": row["category_id"],
        "category_name": row["category_name"],
        "score": round(score, 1),
        "momentum": momentum,
        "score_change": score_change,
        "previous_rank": previous_rank,
        "bss_fit": bss_fit,
        "seasonal_now": seasonal,
        "reason_summary": reason,
        "evidence_summary": evidence_summary,
        "display_tip": row["display_tip"],
        "risk": row["risk"],
        "owner_message_en": row["owner_message_en"],
        "news_evidence": usable_news,
        "manual_references": refs,
        "source_counts": {
            "news_magazine": news_count,
            "magazine": magazine_count,
            "manual_references": len(refs),
            "source_layers": diversity,
        },
    }


def build_rankings() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    rows = flatten_items()
    prev = previous_snapshot()
    output: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "date": CURRENT_DATE.isoformat(),
        "title": "BSS Beauty Product Trend Rankings",
        "methodology": {
            "summary": "Item-only rankings across the broader BSS beauty market: wigs, braiding hair, hair care, lashes, nails, cosmetics, tools/accessories, and jewelry.",
            "score_components": ["BSS fit", "item-specific news/magazine evidence", "source diversity", "seasonality", "historical momentum"],
            "limitations": [
                "TikTok/X/Amazon/Google Trends/Reddit/BSS stores are attached as public reference links in this MVP; deeper APIs/login can be added later.",
                "Rankings are directional retail intelligence, not guaranteed sales forecasts.",
                "Historical movement becomes more meaningful after several scheduled runs with the expanded product universe.",
            ],
        },
        "categories": [{"id": c["id"], "name": c["name"], "description": c["description"]} for c in CATEGORIES],
        "timeframes": TIMEFRAMES,
        "rankings": {},
    }

    for timeframe, cfg in TIMEFRAMES.items():
        prev_by_item = previous_lookup(prev, timeframe)
        ranked = []
        for row in rows:
            news = relevant_news(row, days=cfg["days"])
            refs = manual_references(row)
            ranked.append(score_item(row, timeframe, news, refs, prev_by_item.get(row["id"])))
        ranked.sort(key=lambda r: (r["score"], r["source_counts"]["news_magazine"], r["bss_fit"], r["item_name"]), reverse=True)
        for idx, ranked_row in enumerate(ranked, start=1):
            ranked_row["rank"] = idx
            ranked_row["rank_change"] = None if ranked_row.get("previous_rank") is None else int(ranked_row["previous_rank"]) - idx
        output["rankings"][timeframe] = ranked

    RANKINGS_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUNS_DIR / f"rankings-{CURRENT_DATE.isoformat()}.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

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
            tf: [
                {"item_id": r["item_id"], "item_name": r["item_name"], "rank": r["rank"], "score": r["score"], "category_id": r["category_id"]}
                for r in ranked_rows
            ]
            for tf, ranked_rows in output["rankings"].items()
        },
    }
    history.setdefault("runs", []).insert(0, compact)
    history["runs"] = history["runs"][:104]
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> int:
    rankings = build_rankings()
    top = [
        {"rank": r["rank"], "item": r["item_name"], "score": r["score"], "category": r["category_name"]}
        for r in rankings["rankings"]["weekly"][:12]
    ]
    print(json.dumps({
        "generated_at": rankings["generated_at"],
        "items": sum(len(c["items"]) for c in CATEGORIES),
        "categories": [c["name"] for c in CATEGORIES],
        "timeframes": list(TIMEFRAMES),
        "top_weekly": top,
        "path": str(RANKINGS_PATH),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
