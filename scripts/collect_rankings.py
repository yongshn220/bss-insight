#!/usr/bin/env python3
"""Build item-first BSS beauty product trend rankings.

Public-data MVP: collects verifiable evidence from live public sources. Search
pages are never counted as evidence. Published Bing News/RSS URLs drive trend
movement; live BSS/wholesale product URLs validate retail availability but do
not by themselves create a weekly trend claim. TikTok/Pinterest/X/Reddit/
Amazon/Google Trends search pages remain watchlists until a specific post,
listing, thread, or numeric extract is captured.
"""
from __future__ import annotations

import datetime as dt
import email.utils
from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import json
import os
import re
import time
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RANKINGS_PATH = DATA_DIR / "rankings.json"
HISTORY_PATH = DATA_DIR / "ranking_history.json"
RUNS_DIR = DATA_DIR / "ranking_runs"
NEXT_LOOP_FOCUS_PATH = DATA_DIR / "next_loop_focus.json"
COLLECTION_NOTES_PATH = DATA_DIR / "collection_notes.json"
TIKTOK_SHOP_CACHE_PATH = DATA_DIR / "tiktok_shop_cache.json"

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
CURRENT_DATE = dt.date.today()
CURRENT_MONTH = CURRENT_DATE.month
APIFY_TIKTOK_ACTOR = "coregent~tiktok-shop-product-scraper"
SECRET_ENV_PATHS = [Path("/opt/data/.hermes/.env"), ROOT / ".env", ROOT / ".env.local"]
COLLECTION_HEALTH: dict[str, Any] = {}

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

CATEGORY_ANCHORS = {
    "wigs-hair-pieces": {"wig", "wigs", "lace", "frontal", "glueless", "ponytail"},
    "braiding-crochet-hair": {"braid", "braids", "braiding", "crochet", "loc", "locs", "twist", "twists"},
    "hair-care-styling": {"edge", "gel", "lace", "mousse", "oil", "conditioner", "scalp", "wig"},
    "lashes-brows": {"lash", "lashes", "cluster", "strip", "flare", "bond", "seal"},
    "nails": {"nail", "nails", "press", "coffin", "square", "chrome", "cuticle", "rhinestone"},
    "makeup-cosmetics": {"lip", "liner", "gloss", "powder", "eyeliner", "makeup", "cosmetic"},
    "tools-accessories": {"bonnet", "brush", "comb", "wig", "durag", "cap", "band", "pintail"},
    "jewelry-fashion-accessories": {"earring", "earrings", "hoop", "hoops", "necklace", "pendant", "anklet", "ring", "stud", "belly", "nose", "cuff", "cuffs", "jewelry"},
}

SHOPIFY_STORES = [
    {"id": "ebonyline", "name": "Ebonyline", "base_url": "https://www.ebonyline.com", "source_type": "bss_online_store"},
    {"id": "glamourtress", "name": "Glamourtress", "base_url": "https://www.glamourtress.com", "source_type": "bss_online_store"},
    {"id": "hairtobeauty", "name": "HairToBeauty", "base_url": "https://www.hairtobeauty.com", "source_type": "bss_online_store"},
    {"id": "wigtypes", "name": "WigTypes", "base_url": "https://www.wigtypes.com", "source_type": "bss_online_store"},
    {"id": "beautyofnewyork", "name": "Beauty of New York", "base_url": "https://www.beautyofnewyork.com", "source_type": "bss_online_store"},
    {"id": "wholesaleaccessorymarket", "name": "Wholesale Accessory Market", "base_url": "https://www.wholesaleaccessorymarket.com", "source_type": "wholesale"},
]


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
            item("wig-adhesive-glue", "Wig Adhesive Glue", ["wig adhesive", "lace adhesive", "lace bond adhesive", "wig adhesive glue", "lace wig glue", "waterproof wig glue"], 4, ALL_MONTHS, "잠금 또는 직원 시야 안 진열, remover와 함께 배치", "피부 반응/반품/사용법 설명 중요", "Wig adhesive glue is a high-intent purchase for longer-wear lace installs.", "wig adhesive glue lace install"),
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


def env_value(name: str) -> str:
    """Read a secret/config value without printing it or requiring shell sourcing."""
    if os.environ.get(name):
        return str(os.environ[name]).strip()
    for env_path in SECRET_ENV_PATHS:
        if not env_path.exists():
            continue
        try:
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def int_env(name: str, default: int, lower: int, upper: int) -> int:
    try:
        value = int(env_value(name) or default)
    except ValueError:
        value = default
    return max(lower, min(upper, value))


def load_json_file(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def parse_iso_datetime(value: object) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(dt.UTC)
    except ValueError:
        return None


def clean_error_summary(value: object, limit: int = 700) -> str:
    """Return a short, non-secret operational error summary for public diagnostics."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for secret_name in ("APIFY_TOKEN", "APIFY_API_TOKEN"):
        secret = env_value(secret_name)
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text[:limit]


def set_source_health(source_id: str, status: str, **fields: Any) -> None:
    """Track collection-source health without storing tokens or raw credentials."""
    safe_fields = {key: value for key, value in fields.items() if value not in (None, "")}
    COLLECTION_HEALTH[source_id] = {
        "status": status,
        "observed_at": utc_now(),
        **safe_fields,
    }


def source_health(source_id: str) -> dict[str, Any]:
    value = COLLECTION_HEALTH.get(source_id, {})
    return value if isinstance(value, dict) else {}


_NEXT_LOOP_FOCUS_CACHE: dict[str, Any] | None = None


def load_next_loop_focus() -> dict[str, Any]:
    """Read post-QA review focus from the previous loop, if available."""
    global _NEXT_LOOP_FOCUS_CACHE
    cached = _NEXT_LOOP_FOCUS_CACHE
    if cached is not None:
        return cached
    if not NEXT_LOOP_FOCUS_PATH.exists():
        _NEXT_LOOP_FOCUS_CACHE = {}
        return {}
    try:
        loaded = json.loads(NEXT_LOOP_FOCUS_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        loaded = {}
    _NEXT_LOOP_FOCUS_CACHE = loaded if isinstance(loaded, dict) else {}
    return _NEXT_LOOP_FOCUS_CACHE


def next_loop_focus_queries(row: dict[str, Any]) -> list[str]:
    """Return feedback queries generated after the previous Playwright QA review."""
    focus = load_next_loop_focus()
    max_queries = int_env("NEXT_LOOP_FOCUS_QUERIES_PER_ITEM", 2, 0, 6)
    if max_queries <= 0:
        return []
    focus_items = focus.get("focus_items", []) if isinstance(focus, dict) else []
    if not isinstance(focus_items, list):
        return []
    item_id = row.get("id")
    output: list[str] = []
    seen: set[str] = set()
    for item in focus_items:
        if not isinstance(item, dict) or item.get("item_id") != item_id:
            continue
        queries = item.get("queries", [])
        if not isinstance(queries, list):
            continue
        for query in queries:
            if isinstance(query, str) and query.strip() and query not in seen:
                output.append(query.strip())
                seen.add(query.strip())
            if len(output) >= max_queries:
                return output
    return output


def focus_item_ids() -> set[str]:
    """Item ids that the previous QA/review loop explicitly asked us to probe."""
    focus = load_next_loop_focus()
    focus_items = focus.get("focus_items", []) if isinstance(focus, dict) else []
    if not isinstance(focus_items, list):
        return set()
    return {
        str(item.get("item_id"))
        for item in focus_items
        if isinstance(item, dict) and item.get("item_id")
    }


def needs_alias_product_probe(row: dict[str, Any]) -> bool:
    """Decide when product/supply collectors should try fallback aliases.

    Most items keep a single keyword to avoid noisy marketplace matches and API
    cost. Feedback-focus items and jewelry/body-jewelry SKUs are the exception:
    the first exact phrase can be too narrow (for example, gauge/material/body-
    piercing word order or charm/metal wording), so alternate item aliases are
    safer than broad search pages.
    Wig adhesive is another strict exception: BSS stores often title the shelf as
    "lace adhesive", "wig adhesive", or "lace bond adhesive" rather than
    the full item name, and the primary phrase alone created a live-product gap.
    V-part/leave-out wigs are also strict exceptions because marketplace titles
    often omit "human hair" while still describing the same concrete wig type.
    """
    item_id = str(row.get("id") or "")
    if item_id in focus_item_ids():
        return True
    blob = " ".join(str(row.get(key, "")) for key in ("id", "name", "search_context")).lower()
    if row.get("category_id") == "hair-care-styling" and any(token in blob for token in ("adhesive", "glue", "lace bond")):
        return True
    if row.get("category_id") == "wigs-hair-pieces" and any(token in blob for token in ("v part", "v-part", "leave out", "leave-out")):
        return True
    if row.get("category_id") == "braiding-crochet-hair":
        return any(token in blob for token in ("marley", "kinky", "boho", "crochet", "twist", "loc"))
    if row.get("category_id") != "jewelry-fashion-accessories":
        return False
    # Jewelry listings often reorder the exact item phrase. Example observed in
    # the 2026-08-08 refresh: "butterfly charm anklet" missed live supply while
    # the stricter alias "gold butterfly anklet" matched a concrete HairToBeauty
    # product URL. These aliases remain supply-validation probes only; they must
    # still pass evidence_relevance and never create a trend claim.
    return any(
        token in blob
        for token in (
            "nose", "belly", "navel", "piercing", "gauge", "14g", "20g",
            "anklet", "pendant", "necklace", "cuff", "cuffs", "stackable",
            "stud", "studs", "hoop", "hoops", "rhinestone", "butterfly",
        )
    )


def product_search_queries(row: dict[str, Any], max_queries: int = 3) -> list[str]:
    """Concrete product search terms for live listing collectors.

    Generated search URLs remain watchlist-only. These queries are used only by
    collectors that must return concrete product/listing URLs; matches still pass
    evidence_relevance before they count as supply validation.
    """
    aliases = [str(alias).strip() for alias in row.get("aliases", []) if str(alias).strip()]
    primary = aliases[0] if aliases else str(row.get("name") or "").strip()
    candidates = [primary]
    if needs_alias_product_probe(row):
        candidates.extend([str(row.get("name") or "").strip(), *aliases[1:]])
    output: list[str] = []
    seen: set[str] = set()
    for query in candidates:
        key = query.lower()
        if query and key not in seen:
            output.append(query)
            seen.add(key)
        if len(output) >= max_queries:
            break
    return output


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
        desc = strip_markup(node.findtext("description") or "")
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
            "source_layer": "published_news",
            "query": query,
            "title": title,
            "publisher": publisher,
            "url": link,
            "published": pub,
            "published_date": pub_date,
            "date_kind": "published",
            "snippet": desc[:260],
        })
    return items


def watchlist_links(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Reference/search links for follow-up only; never counted as evidence."""
    query = row["name"]
    encoded = urllib.parse.quote_plus(query)
    tag = re.sub(r"[^a-z0-9]", "", row["aliases"][0].lower())
    refs = [
        ("sns", "tiktok", f"TikTok search: {query}", f"https://www.tiktok.com/search?q={encoded}", "Watchlist only — not counted until a specific post/video URL is captured."),
        ("sns", "tiktok_tag", f"TikTok hashtag: #{tag}", f"https://www.tiktok.com/tag/{tag}", "Watchlist only — hashtag page is not evidence by itself."),
        ("visual", "pinterest", f"Pinterest search: {query}", f"https://www.pinterest.com/search/pins/?q={encoded}", "Watchlist only — pin-level URLs should be captured in a deeper run."),
        ("social", "x_twitter", f"X/Twitter search: {query}", f"https://twitter.com/search?q={encoded}&src=typed_query&f=live", "Watchlist only — tweet/post URLs are required for evidence."),
        ("community", "reddit", f"Reddit search: {query}", f"https://www.reddit.com/search/?q={encoded}", "Watchlist only — thread URLs are required for evidence."),
        ("marketplace", "amazon", f"Amazon search: {query}", f"https://www.amazon.com/s?k={encoded}", "Watchlist only — product/listing URLs are required for evidence."),
        ("marketplace", "walmart", f"Walmart search: {query}", f"https://www.walmart.com/search?q={encoded}", "Watchlist only — listing URLs are required for evidence."),
        ("search_interest", "google_trends", f"Google Trends: {query}", f"https://trends.google.com/trends/explore?geo=US&q={encoded}", "Watchlist only — numeric trend extracts are required for scoring."),
        ("bss_online_store", "samsbeauty", f"SamsBeauty search: {query}", f"https://www.samsbeauty.com/service/search?q={encoded}", "Watchlist only — product/category URLs should be captured in a deeper run."),
        ("bss_online_store", "ebonyline", f"Ebonyline search: {query}", f"https://www.ebonyline.com/search?q={encoded}", "Watchlist only — product/category URLs should be captured in a deeper run."),
        ("bss_online_store", "beauty_of_new_york", f"Beauty of New York search: {query}", f"https://www.beautyofnewyork.com/search?q={encoded}", "Watchlist only — product/category URLs should be captured in a deeper run."),
        ("bss_online_store", "wigtypes", f"WigTypes search: {query}", f"https://www.wigtypes.com/search?q={encoded}", "Watchlist only — product/category URLs should be captured in a deeper run."),
        ("wholesale", "faire", f"Faire wholesale search: {query}", f"https://www.faire.com/search?q={encoded}", "Watchlist only — vendor listing URLs are required for evidence."),
        ("wholesale", "fashiongo", f"FashionGo search: {query}", f"https://www.fashiongo.net/search?q={encoded}", "Watchlist only — vendor listing URLs are required for evidence."),
    ]
    if row["category_id"] == "jewelry-fashion-accessories":
        refs.extend([
            ("wholesale", "nihao", f"Nihao Jewelry search: {query}", f"https://www.nihaojewelry.com/search?q={encoded}", "Watchlist only — jewelry listing URLs are required for evidence."),
            ("wholesale", "judson", f"Judson search: {query}", f"https://www.judson.biz/search?q={encoded}", "Watchlist only — jewelry listing URLs are required for evidence."),
        ])
    return [
        {"source_type": source_type, "source_kind": kind, "title": title, "url": url, "summary": summary, "evidence_status": "watchlist_only"}
        for source_type, kind, title, url, summary in refs
    ]


def important_tokens(row: dict[str, Any]) -> list[str]:
    blob = " ".join([row["name"], row["id"].replace("-", " "), *row.get("aliases", [])]).lower()
    tokens = {t for t in re.split(r"\W+", blob) if len(t) >= 4 and t not in GENERIC_RELEVANCE_TOKENS}
    # If an item is mostly generic words, keep longer generic-but-specific compounds.
    if not tokens:
        tokens = {t for t in re.split(r"\W+", blob) if len(t) >= 5}
    return sorted(tokens)


def normalized_word_tokens(value: str) -> set[str]:
    """Tokenize source text for relevance checks without substring false positives.

    The earlier substring check allowed glue -> glueless, which could make a wig
    listing look like wig-adhesive evidence. Whole-token matching preserves broad
    item-type matching while keeping supply validation honest.
    """
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def token_forms(token: str) -> set[str]:
    token = token.lower().strip()
    forms = {token}
    if token.endswith("ies") and len(token) > 4:
        forms.add(token[:-3] + "y")
    if token.endswith("s") and len(token) > 4:
        forms.add(token[:-1])
    else:
        forms.add(token + "s")
    return {form for form in forms if form}


def token_matches_word(token: str, hay_tokens: set[str]) -> bool:
    return any(form in hay_tokens for form in token_forms(token))


def parse_signal_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            parsed = dt.datetime.strptime(value, fmt)
            return parsed.date()
        except ValueError:
            continue
    try:
        return email.utils.parsedate_to_datetime(value).date()
    except Exception:
        return None


def is_within_days(source: dict[str, Any], days: int) -> bool:
    signal_date = parse_signal_date(source.get("published_date") or source.get("seendate") or source.get("published"))
    if signal_date is None:
        return days >= 365
    return (CURRENT_DATE - signal_date).days <= days


def strip_markup(value: str) -> str:
    text = re.sub("<.*?>", " ", html.unescape(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def evidence_relevance(row: dict[str, Any], source: dict[str, Any]) -> str | None:
    hay = " ".join(str(source.get(k, "")).lower() for k in ["title", "snippet", "body", "domain", "publisher", "vendor"])
    phrases = [a.lower() for a in [row["name"], *row.get("aliases", [])] if len(a) >= 4]
    if any(phrase in hay for phrase in phrases):
        return "exact_phrase"
    tokens = important_tokens(row)
    if not tokens:
        return None
    hay_tokens = normalized_word_tokens(hay)
    token_match_count = sum(1 for tok in tokens if token_matches_word(tok, hay_tokens))
    category_id = str(row.get("category_id") or "")
    anchor_match = any(anchor in hay_tokens for anchor in CATEGORY_ANCHORS.get(category_id, set()))
    # Many BSS item names contain generic category words that were stripped from
    # important_tokens. One distinctive token plus a category anchor is enough
    # for live product/listing evidence; published trend claims still keep the
    # relevance label visible in score_breakdown. Use whole-token matching so
    # "glue" does not match "glueless" and accidentally count wigs as adhesive.
    if token_match_count >= 2 or (token_match_count >= 1 and anchor_match):
        return "item_type"
    return None


def evidence_match(row: dict[str, Any], source: dict[str, Any]) -> bool:
    relevance = evidence_relevance(row, source)
    if relevance:
        source["evidence_relevance"] = relevance
        return True
    return False


def canonical_news_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if "bing.com" in parsed.netloc and "apiclick" in parsed.path:
        target = urllib.parse.parse_qs(parsed.query).get("url", [""])[0]
        if target:
            return target
    return url


def domain_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc.removeprefix("www.")


def rss_child_text(node: ET.Element, suffix: str) -> str:
    for child in list(node):
        if child.tag.lower().endswith(suffix.lower()) and child.text:
            return child.text.strip()
    return ""


def product_image_url(product: dict[str, Any]) -> str:
    image = product.get("image") or product.get("featured_image")
    if isinstance(image, str):
        return image
    if isinstance(image, dict):
        return str(image.get("url") or image.get("src") or "")
    return ""


def category_visual_url(row: dict[str, Any]) -> str:
    return f"/assets/category-{row['category_id']}.svg"


def bing_news_articles(row: dict[str, Any], days: int = 365, limit: int = 8) -> list[dict[str, Any]]:
    query = str(row.get("focus_query") or row["aliases"][0])
    url = "https://www.bing.com/news/search?" + urllib.parse.urlencode({"q": query, "format": "rss"})
    status, text, error = fetch(url, timeout=10)
    if error or not text:
        return [{"source_type": "news_magazine", "source_kind": "bing_news", "query": query, "url": url, "error": error or f"HTTP {status}"}]
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return [{"source_type": "news_magazine", "source_kind": "bing_news", "query": query, "url": url, "error": f"XML parse error: {exc}"}]
    articles: list[dict[str, Any]] = []
    for node in root.findall(".//item")[:limit]:
        title = html.unescape((node.findtext("title") or "").strip())
        link = canonical_news_url((node.findtext("link") or "").strip())
        pub = (node.findtext("pubDate") or "").strip()
        desc = strip_markup(node.findtext("description") or "")
        pub_date = parse_signal_date(pub)
        source = rss_child_text(node, "Source") or domain_from_url(link) or "Bing News"
        image_url = rss_child_text(node, "Image")
        signal = {
            "source_type": "news_magazine",
            "source_kind": "bing_news",
            "source_layer": "published_news",
            "query": query,
            "title": title,
            "publisher": source,
            "domain": domain_from_url(link) or source,
            "url": link,
            "published": pub,
            "published_date": pub_date.isoformat() if pub_date else "",
            "date_kind": "published",
            "snippet": desc[:320],
            "image_url": image_url,
            "image_source": source if image_url else "",
            "evidence_status": "verified_url",
        }
        if is_within_days(signal, days) and evidence_match(row, signal):
            articles.append(signal)
    return articles


def gdelt_articles(row: dict[str, Any], days: int = 365, limit: int = 8) -> list[dict[str, Any]]:
    query_terms = " OR ".join(f'"{alias}"' for alias in [row["aliases"][0], row["name"]])
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode({
        "query": query_terms,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(limit),
        "sort": "HybridRel",
        "timespan": f"{days}d",
    })
    status, text, error = fetch(url, timeout=8)
    if error or not text:
        return [{"source_type": "article", "source_kind": "gdelt", "query": query_terms, "url": url, "error": error or f"HTTP {status}"}]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return [{"source_type": "article", "source_kind": "gdelt", "query": query_terms, "url": url, "error": f"JSON parse error: {exc}"}]
    articles = []
    seen_urls: set[str] = set()
    for article in payload.get("articles", [])[:limit]:
        article_url = article.get("url") or ""
        if not article_url or article_url in seen_urls:
            continue
        seen_urls.add(article_url)
        signal = {
            "source_type": "article",
            "source_kind": "gdelt",
            "source_layer": "published_news",
            "query": query_terms,
            "title": html.unescape(article.get("title") or ""),
            "domain": article.get("domain") or "",
            "publisher": article.get("domain") or "",
            "url": article_url,
            "seendate": article.get("seendate") or "",
            "published_date": (parse_signal_date(article.get("seendate")) or CURRENT_DATE).isoformat(),
            "date_kind": "published",
            "snippet": html.unescape(article.get("socialimage") or article.get("language") or ""),
            "evidence_status": "verified_url",
        }
        if evidence_match(row, signal):
            articles.append(signal)
    return articles


def google_news_articles(row: dict[str, Any], days: int = 365, limit: int = 5) -> list[dict[str, Any]]:
    # Secondary source; Google News can rate-limit, so errors are recorded but not fatal.
    primary = row["aliases"][0]
    query = str(row.get("focus_query") or f'"{primary}" {row.get("search_context", "beauty supply")}')
    results = google_news_rss(query, days=days, limit=limit)
    articles = []
    for result in results:
        if result.get("error"):
            continue
        result = dict(result)
        result["evidence_status"] = "verified_url"
        if evidence_match(row, result):
            articles.append(result)
    return articles


def source_sort_date(source: dict[str, Any]) -> str:
    return str(source.get("published_date") or source.get("observed_date") or source.get("seendate") or "")


def is_published_evidence(source: dict[str, Any]) -> bool:
    return source.get("date_kind") == "published" or source.get("source_type") in {"article", "news_magazine"}


def is_retail_product_evidence(source: dict[str, Any]) -> bool:
    return source.get("source_type") in {"bss_online_store", "wholesale", "marketplace_product"}


def shopify_product_search(row: dict[str, Any], store: dict[str, str], query: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
    query = query or row["aliases"][0]
    url = store["base_url"].rstrip("/") + "/search/suggest.json?" + urllib.parse.urlencode({
        "q": query,
        "resources[type]": "product",
        "resources[limit]": str(limit),
    })
    time.sleep(0.2)
    status, text, error = fetch(url, timeout=8)
    if error or not text:
        return [{"source_type": store["source_type"], "source_kind": store["id"], "query": query, "url": url, "error": error or f"HTTP {status}"}]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return [{"source_type": store["source_type"], "source_kind": store["id"], "query": query, "url": url, "error": f"JSON parse error: {exc}"}]
    evidence: list[dict[str, Any]] = []
    for product in payload.get("resources", {}).get("results", {}).get("products", [])[:limit]:
        product_url = urllib.parse.urljoin(store["base_url"], str(product.get("url") or ""))
        title = html.unescape(str(product.get("title") or "").strip())
        body = strip_markup(str(product.get("body") or ""))
        image_url = product_image_url(product)
        signal = {
            "source_type": store["source_type"],
            "source_kind": store["id"],
            "source_layer": "retail_product_url" if store["source_type"] == "bss_online_store" else "wholesale_product_url",
            "query": query,
            "title": title,
            "publisher": store["name"],
            "domain": domain_from_url(store["base_url"]),
            "vendor": product.get("vendor") or "",
            "url": product_url,
            "observed_date": CURRENT_DATE.isoformat(),
            "date_kind": "observed_live_product",
            "snippet": body[:320],
            "price": str(product.get("price") or product.get("price_min") or ""),
            "available": bool(product.get("available")),
            "image_url": image_url,
            "image_source": store["name"] if image_url else "",
            "evidence_status": "verified_url",
        }
        if product_url and title and evidence_match(row, signal):
            evidence.append(signal)
    return evidence


def retail_product_evidence(row: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    queries = product_search_queries(row, max_queries=3)
    for store in SHOPIFY_STORES:
        if store["source_type"] == "wholesale" and row.get("category_id") not in {"jewelry-fashion-accessories", "tools-accessories", "nails"}:
            continue
        for query in queries:
            found_for_store = False
            for src in shopify_product_search(row, store, query=query, limit=3):
                if not src.get("error"):
                    evidence.append(src)
                    found_for_store = True
            # Alias fallback is only needed when a store returns no relevant
            # concrete product URL for the primary phrase; once we have a store
            # match, stop probing that store to keep collection cheap/noise-light.
            if found_for_store:
                break
    return evidence


def apify_tiktok_source_keywords(product: dict[str, Any]) -> list[str]:
    raw = product.get("sourceKeywords") or product.get("sourceKeyword") or product.get("keywords") or []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(value) for value in raw if value]
    return []


def apify_tiktok_product_signal(product: dict[str, Any], row: dict[str, Any], query: str, *, allow_keyword_fallback: bool = True) -> dict[str, Any] | None:
    product_url = str(product.get("productUrl") or product.get("url") or "")
    title = html.unescape(str(product.get("productTitle") or product.get("title") or product.get("name") or "").strip())
    if not product_url or not title:
        return None
    images = product.get("imageUrls") or product.get("images") or []
    image_url = ""
    if isinstance(images, list) and images:
        image_url = str(images[0] or "")
    elif isinstance(images, str):
        image_url = images
    sale_price = product.get("salePrice") or product.get("price") or product.get("priceRangeMin") or ""
    currency = product.get("currency") or "USD"
    sold_count = product.get("soldCount")
    rating = product.get("ratingAverage") or product.get("rating")
    summary_parts = []
    if sold_count not in (None, ""):
        summary_parts.append(f"sold_count={sold_count}")
    if rating not in (None, ""):
        summary_parts.append(f"rating={rating}")
    if product.get("analysisReason"):
        summary_parts.append(str(product.get("analysisReason")))
    description = strip_markup(str(product.get("productDescription") or ""))
    if description:
        summary_parts.append(description[:180])
    signal = {
        "source_type": "marketplace_product",
        "source_kind": "tiktok_shop_apify",
        "source_layer": "social_commerce_product_url",
        "query": query,
        "title": title,
        "publisher": product.get("sellerName") or product.get("storeName") or "TikTok Shop",
        "domain": "shop.tiktok.com",
        "vendor": product.get("sellerName") or product.get("storeName") or "",
        "url": product_url,
        "observed_date": CURRENT_DATE.isoformat(),
        "scraped_at": product.get("scrapedAt") or "",
        "date_kind": "observed_live_product",
        "snippet": " · ".join(summary_parts)[:360],
        "price": str(sale_price),
        "currency": currency,
        "sold_count": sold_count,
        "rating": rating,
        "rating_count": product.get("ratingCount"),
        "review_count": product.get("reviewCount"),
        "seller_id": product.get("sellerId") or "",
        "seller_url": product.get("sellerUrl") or "",
        "product_id": product.get("productId") or "",
        "image_url": image_url,
        "image_source": "TikTok Shop" if image_url else "",
        "evidence_status": "verified_url",
    }
    if evidence_match(row, signal):
        return signal
    if not allow_keyword_fallback:
        return None
    # A TikTok Shop primary-keyword result is still useful social-commerce supply
    # data, but keep the weaker relevance label visible in the data/score details.
    # Fallback alias probes stay strict so broader aliases do not inflate coverage.
    signal["evidence_relevance"] = "keyword_search_result"
    return signal


def tiktok_shop_cache_max_age_days() -> int:
    return int_env("TIKTOK_SHOP_CACHE_MAX_AGE_DAYS", 7, 1, 45)


def count_tiktok_sources(evidence_by_item: dict[str, list[dict[str, Any]]]) -> int:
    return sum(len(sources) for sources in evidence_by_item.values())


def write_tiktok_shop_cache(evidence_by_item: dict[str, list[dict[str, Any]]]) -> None:
    """Persist last successful TikTok Shop listing URLs for transparent fallback.

    The cache contains only public product/listing fields already safe for the
    dashboard. It is used when the upstream Apify actor fails or when a
    successful actor run drops an item that had a recent listing capture. The UI
    keeps showing that supply signal while clearly labeling it as cached, never
    as fresh trend evidence.
    """
    evidence_by_item = {
        item_id: [dict(src) for src in sources if isinstance(src, dict) and src.get("url")]
        for item_id, sources in evidence_by_item.items()
        if sources
    }
    evidence_by_item = {item_id: sources for item_id, sources in evidence_by_item.items() if sources}
    if not evidence_by_item:
        return
    payload = {
        "updated_at": utc_now(),
        "date": CURRENT_DATE.isoformat(),
        "source_kind": "tiktok_shop_apify",
        "cache_policy": {
            "max_age_days": tiktok_shop_cache_max_age_days(),
            "purpose": "Use only as labeled social-commerce supply fallback after an Apify actor failure; never use as published trend evidence.",
        },
        "totals": {
            "items": len(evidence_by_item),
            "urls": count_tiktok_sources(evidence_by_item),
        },
        "evidence_by_item": evidence_by_item,
    }
    TIKTOK_SHOP_CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_tiktok_shop_cache() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    payload = load_json_file(TIKTOK_SHOP_CACHE_PATH, {})
    if not isinstance(payload, dict):
        return {}, {"cache_status": "missing"}
    updated_at = parse_iso_datetime(payload.get("updated_at"))
    cache_age_days = None
    if updated_at:
        cache_age_days = max(0, (dt.datetime.now(dt.UTC) - updated_at).days)
    else:
        cache_date = parse_signal_date(str(payload.get("date") or ""))
        if cache_date:
            cache_age_days = max(0, (CURRENT_DATE - cache_date).days)
    max_age = tiktok_shop_cache_max_age_days()
    if cache_age_days is None:
        return {}, {"cache_status": "invalid_date", "cache_path": str(TIKTOK_SHOP_CACHE_PATH)}
    if cache_age_days > max_age:
        return {}, {
            "cache_status": "expired",
            "cache_path": str(TIKTOK_SHOP_CACHE_PATH),
            "cache_updated_at": payload.get("updated_at"),
            "cache_age_days": cache_age_days,
            "cache_max_age_days": max_age,
        }
    raw_items = payload.get("evidence_by_item", {})
    if not isinstance(raw_items, dict):
        return {}, {"cache_status": "invalid_payload", "cache_path": str(TIKTOK_SHOP_CACHE_PATH)}
    evidence_by_item: dict[str, list[dict[str, Any]]] = {}
    for item_id, sources in raw_items.items():
        if not isinstance(sources, list):
            continue
        cached_sources = []
        for source in sources:
            if not isinstance(source, dict) or not source.get("url"):
                continue
            cached = dict(source)
            cached.setdefault("source_type", "marketplace_product")
            cached.setdefault("source_kind", "tiktok_shop_apify")
            cached["source_layer"] = "social_commerce_product_url_cached"
            cached["date_kind"] = "observed_cached_product"
            cached["evidence_status"] = "cached_verified_url"
            cached["cache_status"] = "reused_after_apify_failure"
            cached["cache_updated_at"] = payload.get("updated_at")
            cached["cache_age_days"] = cache_age_days
            cached["cache_source"] = str(TIKTOK_SHOP_CACHE_PATH.relative_to(ROOT))
            cached_sources.append(cached)
        if cached_sources:
            evidence_by_item[str(item_id)] = cached_sources
    return evidence_by_item, {
        "cache_status": "usable" if evidence_by_item else "empty",
        "cache_path": str(TIKTOK_SHOP_CACHE_PATH.relative_to(ROOT)),
        "cache_updated_at": payload.get("updated_at"),
        "cache_age_days": cache_age_days,
        "cache_max_age_days": max_age,
        "cached_items": len(evidence_by_item),
        "cached_evidence_urls": count_tiktok_sources(evidence_by_item),
    }


def apify_payload(keywords: list[str], per_query: int, max_total: int) -> dict[str, Any]:
    """Build an Apify TikTok Shop actor payload for a keyword batch."""
    return {
        "keywords": keywords,
        "countries": ["US"],
        "maxResultsPerQuery": per_query,
        "maxResultsTotal": max(1, max_total),
        "deduplicateProducts": True,
        "includeSummary": False,
        "includeProductDetails": False,
        "includeReviews": False,
    }


def run_apify_tiktok_actor(token: str, payload: dict[str, Any], timeout: int, max_attempts: int) -> tuple[list[Any] | None, str, int]:
    """Run the Apify actor without leaking credentials in errors or stdout."""
    url = f"https://api.apify.com/v2/acts/{APIFY_TIKTOK_ACTOR}/run-sync-get-dataset-items"
    products: list[Any] | None = None
    last_error = ""
    attempts_used = 0
    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                parsed = json.loads(resp.read().decode("utf-8"))
            if isinstance(parsed, list):
                products = parsed
                last_error = ""
                break
            last_error = f"Unexpected Apify response type: {type(parsed).__name__}"
        except urllib.error.HTTPError as exc:
            body = exc.read(1500).decode("utf-8", errors="replace")
            last_error = f"HTTP {exc.code} {exc.reason}: {body}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < max_attempts:
            time.sleep(min(18, 4 * attempt))
    return products, clean_error_summary(last_error), attempts_used


def chunked(values: list[str], size: int, max_chunks: int) -> list[list[str]]:
    """Return bounded keyword chunks for cron-safe fallback actor runs."""
    size = max(1, size)
    max_chunks = max(1, max_chunks)
    chunks = [values[idx: idx + size] for idx in range(0, len(values), size)]
    return [chunk for chunk in chunks[:max_chunks] if chunk]


def dedupe_apify_products(products: list[Any]) -> list[Any]:
    """Deduplicate Apify products while preserving source keyword coverage."""
    output: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for product in products:
        if not isinstance(product, dict):
            output.append(product)
            continue
        url = str(product.get("productUrl") or product.get("url") or product.get("productId") or "")
        keywords = ",".join(sorted(k.lower() for k in apify_tiktok_source_keywords(product)))
        key = (url, keywords)
        if key in seen:
            continue
        seen.add(key)
        output.append(product)
    return output


def apify_sharded_fallback(
    token: str,
    keywords: list[str],
    per_query: int,
    full_max_total: int,
    full_error: str,
) -> tuple[list[Any] | None, dict[str, Any]]:
    """Recover fresh TikTok Shop URLs with smaller actor batches after a full-run failure.

    The collector previously fell straight back to cache when the single large
    actor payload failed. Smaller keyword shards can salvage fresh social-commerce
    supply URLs for the owner dashboard while TikTok Shop remains supply-only and
    never trend-scoring.
    """
    enabled = (env_value("APIFY_TIKTOK_SHARD_FALLBACK_ENABLED") or "1").lower() not in {"0", "false", "no"}
    if not enabled or not keywords:
        return None, {"shard_fallback_status": "disabled" if not enabled else "no_keywords"}

    shard_size = int_env("APIFY_TIKTOK_SHARD_FALLBACK_SIZE", 20, 5, 50)
    max_shards = int_env("APIFY_TIKTOK_SHARD_FALLBACK_MAX_SHARDS", 5, 1, 10)
    shard_timeout = int_env("APIFY_TIKTOK_SHARD_FALLBACK_TIMEOUT_SECS", 120, 45, 300)
    shards = chunked(keywords, shard_size, max_shards)
    collected: list[Any] = []
    errors: list[str] = []
    attempts = 0
    succeeded = 0

    for shard in shards:
        shard_max_total = min(full_max_total, max(1, len(shard) * per_query))
        products, error, used = run_apify_tiktok_actor(
            token,
            apify_payload(shard, per_query, shard_max_total),
            timeout=shard_timeout,
            max_attempts=1,
        )
        attempts += used
        if products is None:
            errors.append(error or "unknown shard failure")
            continue
        succeeded += 1
        collected.extend(products)

    meta = {
        "full_actor_status": "failed",
        "full_error_summary": clean_error_summary(full_error),
        "shard_fallback_status": "success" if collected and not errors else ("partial_success" if collected else "failed"),
        "shard_size": shard_size,
        "shards_requested": len(shards),
        "shards_succeeded": succeeded,
        "shards_failed": len(errors),
        "shard_attempts": attempts,
        "shard_keywords_requested": sum(len(shard) for shard in shards),
        "shard_error_summary": clean_error_summary(" | ".join(errors[:3])) if errors else "",
    }
    if not collected:
        return None, meta
    return dedupe_apify_products(collected), meta


def apify_tiktok_shop_evidence(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    token = env_value("APIFY_TOKEN") or env_value("APIFY_API_TOKEN")
    enabled = (env_value("APIFY_TIKTOK_ENABLED") or "1").lower() not in {"0", "false", "no"}
    if not token or not enabled:
        set_source_health(
            "apify_tiktok_shop",
            "skipped",
            configured=bool(token),
            enabled=enabled,
            reason="APIFY token not configured or APIFY_TIKTOK_ENABLED disabled",
        )
        return {}
    per_query = int_env("APIFY_TIKTOK_MAX_RESULTS_PER_QUERY", 1, 1, 5)
    timeout = int_env("APIFY_TIKTOK_TIMEOUT_SECS", 300, 60, 900)
    max_attempts = int_env("APIFY_TIKTOK_MAX_ATTEMPTS", 2, 1, 4)
    keywords: list[str] = []
    rows_by_keyword: dict[str, tuple[dict[str, Any], bool]] = {}
    expanded_keyword_items = 0
    for row in rows:
        row_keywords = product_search_queries(row, max_queries=3)
        if len(row_keywords) > 1:
            expanded_keyword_items += 1
        for idx, keyword in enumerate(row_keywords):
            key = keyword.lower()
            if key in rows_by_keyword:
                continue
            keywords.append(keyword)
            # Only the primary query keeps the historical keyword-search fallback.
            # Alias probes must relevance-match the listing title/snippet/vendor.
            rows_by_keyword[key] = (row, idx == 0)
    max_total = int_env("APIFY_TIKTOK_MAX_RESULTS_TOTAL", max(1, len(keywords) * per_query), 1, 250)
    products, last_error, attempts_used = run_apify_tiktok_actor(
        token,
        apify_payload(keywords, per_query, max_total),
        timeout=timeout,
        max_attempts=max_attempts,
    )
    fallback_meta: dict[str, Any] = {}
    full_run_failed = products is None
    if full_run_failed:
        products, fallback_meta = apify_sharded_fallback(token, keywords, per_query, max_total, last_error)
        attempts_used += int(fallback_meta.get("shard_attempts") or 0)
    if products is None:
        cached_evidence, cache_meta = load_tiktok_shop_cache()
        if cached_evidence:
            set_source_health(
                "apify_tiktok_shop",
                "failed_using_cache",
                configured=True,
                enabled=True,
                attempts=attempts_used,
                keywords_requested=len(keywords),
                expanded_keyword_items=expanded_keyword_items,
                max_results_total=max_total,
                current_actor_status="failed",
                error_summary=clean_error_summary(last_error),
                **fallback_meta,
                retry_rule="APIFY_TIKTOK_MAX_ATTEMPTS controls re-runs after transient upstream/risk-control failures.",
                cache_policy="cached TikTok Shop URLs are supply fallback only and are labeled; they never create trend movement.",
                **cache_meta,
            )
            return cached_evidence
        set_source_health(
            "apify_tiktok_shop",
            "failed",
            configured=True,
            enabled=True,
            attempts=attempts_used,
            keywords_requested=len(keywords),
            expanded_keyword_items=expanded_keyword_items,
            max_results_total=max_total,
            error_summary=clean_error_summary(last_error),
            **fallback_meta,
            retry_rule="APIFY_TIKTOK_MAX_ATTEMPTS controls re-runs after transient upstream/risk-control failures.",
            **cache_meta,
        )
        return {}
    evidence_by_item: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for product in products:
        if not isinstance(product, dict) or product.get("errorType"):
            continue
        matched_rows = []
        for keyword in apify_tiktok_source_keywords(product):
            match = rows_by_keyword.get(keyword.lower())
            if match:
                row, is_primary_query = match
                matched_rows.append((keyword, row, is_primary_query))
        if not matched_rows:
            continue
        for keyword, row, is_primary_query in matched_rows:
            signal = apify_tiktok_product_signal(product, row, keyword, allow_keyword_fallback=is_primary_query)
            if not signal:
                continue
            dedupe_key = (row["id"], signal["url"])
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            evidence_by_item.setdefault(row["id"], []).append(signal)
    fresh_evidence_urls = sum(len(sources) for sources in evidence_by_item.values())
    cached_evidence, cache_meta = load_tiktok_shop_cache()
    target_item_ids = [str(row.get("id") or "") for row in rows if row.get("id")]
    missing_item_ids = [item_id for item_id in target_item_ids if item_id not in evidence_by_item]
    partial_cached_items = 0
    partial_cached_urls = 0
    if cached_evidence and missing_item_ids:
        for item_id in missing_item_ids:
            sources = cached_evidence.get(item_id, [])
            if not sources:
                continue
            recovered_sources = []
            for source in sources:
                cached = dict(source)
                cached["source_layer"] = "social_commerce_product_url_cached"
                cached["date_kind"] = "observed_cached_product"
                cached["evidence_status"] = "cached_verified_url"
                cached["cache_status"] = "reused_after_partial_apify_success"
                cached["cache_reason"] = "actor_success_but_item_missing_from_current_dataset"
                recovered_sources.append(cached)
            if recovered_sources:
                evidence_by_item[item_id] = recovered_sources
                partial_cached_items += 1
                partial_cached_urls += len(recovered_sources)
    evidence_urls = sum(len(sources) for sources in evidence_by_item.values())
    if evidence_urls:
        write_tiktok_shop_cache(evidence_by_item)
    status = "success_sharded_after_full_failure" if full_run_failed and fresh_evidence_urls else ("success" if fresh_evidence_urls else "success_empty")
    if partial_cached_items:
        status = "success_sharded_with_partial_cache" if full_run_failed and fresh_evidence_urls else "success_with_partial_cache"
    current_actor_status = "success"
    if full_run_failed and fresh_evidence_urls:
        current_actor_status = "success_sharded_after_full_failure"
    if partial_cached_items and fresh_evidence_urls:
        current_actor_status = "success_partial_sharded" if full_run_failed else "success_partial"
    elif partial_cached_items:
        current_actor_status = "success_empty"
    set_source_health(
        "apify_tiktok_shop",
        status,
        configured=True,
        enabled=True,
        attempts=attempts_used,
        keywords_requested=len(keywords),
        expanded_keyword_items=expanded_keyword_items,
        products_returned=len(products),
        items_with_evidence=len(evidence_by_item),
        evidence_urls=evidence_urls,
        fresh_evidence_urls=fresh_evidence_urls,
        partial_cached_items=partial_cached_items,
        partial_cached_evidence_urls=partial_cached_urls,
        current_actor_status=current_actor_status,
        cache_policy="Partial cached TikTok Shop URLs are supply fallback only and are labeled; they never create trend movement." if partial_cached_items else "cache not used",
        max_results_total=max_total,
        **fallback_meta,
        **(cache_meta if partial_cached_items else {}),
    )
    return evidence_by_item


def cap_verified_sources(deduped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep dated trend evidence from being displaced by fresh product URLs.

    Product/listing URLs use today's observed_date, so a single mixed recency sort
    can push older but still valid published trend URLs out of the per-item cap.
    Search/watchlist URLs remain excluded; this only changes which captured,
    concrete URLs survive into rankings.json.
    """
    published_cap = int_env("SOURCE_CAP_PUBLISHED_PER_ITEM", 8, 1, 20)
    retail_cap = int_env("SOURCE_CAP_RETAIL_PER_ITEM", 10, 1, 24)
    total_cap = int_env("SOURCE_CAP_TOTAL_PER_ITEM", 14, 4, 32)
    published: list[dict[str, Any]] = []
    retail: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for src in deduped:
        if is_published_evidence(src):
            published.append(src)
        elif is_retail_product_evidence(src):
            retail.append(src)
        else:
            other.append(src)
    prioritized = published[:published_cap] + retail[:retail_cap] + other
    return prioritized[:total_cap]


def collect_verified_evidence(row: dict[str, Any]) -> list[dict[str, Any]]:
    sources = []
    errors = []

    def add_news_results(query_row: dict[str, Any], *, feedback_query: str = "", always_secondary: bool = False) -> None:
        local_sources: list[dict[str, Any]] = []
        # Bing News RSS is the primary public source because it returns concrete article URLs and dates reliably.
        # Google News is secondary and can rate-limit; it is used after weak Bing coverage, and always for
        # feedback-focus queries because those are intentionally narrow next-loop probes.
        for fn in (bing_news_articles,):
            results = fn(query_row, days=365)
            for src in results:
                if src.get("error"):
                    errors.append(src)
                else:
                    if feedback_query:
                        src["feedback_focus_query"] = feedback_query
                    local_sources.append(src)
        if len(local_sources) < 2 or always_secondary:
            for fn in (google_news_articles,):
                results = fn(query_row, days=365)
                for src in results:
                    if src.get("error"):
                        errors.append(src)
                    else:
                        if feedback_query:
                            src["feedback_focus_query"] = feedback_query
                        local_sources.append(src)
        sources.extend(local_sources)

    add_news_results(row)
    for query in next_loop_focus_queries(row):
        focused_row = dict(row)
        focused_row["focus_query"] = query
        add_news_results(focused_row, feedback_query=query, always_secondary=True)
    sources.extend(retail_product_evidence(row))
    deduped = []
    seen = set()
    for src in sources:
        url = src.get("url")
        if url and url not in seen:
            seen.add(url)
            deduped.append(src)
    deduped.sort(key=source_sort_date, reverse=True)
    # Keep fetch errors only in collection notes, not as evidence. Published URLs
    # get first claim on the cap; supply URLs stay visible but never create trend movement.
    return cap_verified_sources(deduped)


def collect_all_evidence(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    evidence_by_item: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_map = {executor.submit(collect_verified_evidence, row): row for row in rows}
        for future in as_completed(future_map):
            row = future_map[future]
            try:
                evidence_by_item[row["id"]] = future.result()
            except Exception as exc:
                evidence_by_item[row["id"]] = [{"source_type": "collection_error", "source_kind": "error", "error": f"{type(exc).__name__}: {exc}"}]
    for item_id, sources in apify_tiktok_shop_evidence(rows).items():
        existing = evidence_by_item.setdefault(item_id, [])
        seen = {src.get("url") for src in existing if src.get("url")}
        for src in sources:
            if src.get("url") and src.get("url") not in seen:
                existing.append(src)
                seen.add(src.get("url"))
        existing.sort(key=source_sort_date, reverse=True)
    return evidence_by_item


def evidence_collection_totals(evidence_by_item: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows = list(evidence_by_item.values())
    all_sources = [src for sources in rows for src in sources if isinstance(src, dict)]
    cached_tiktok_sources = [
        src
        for src in all_sources
        if src.get("source_kind") == "tiktok_shop_apify" and src.get("cache_status")
    ]
    return {
        "items_requested": sum(len(c["items"]) for c in CATEGORIES),
        "items_with_any_verified_url": sum(1 for sources in rows if any(src.get("url") and not src.get("error") for src in sources)),
        "items_with_published_trend_url": sum(1 for sources in rows if any(is_published_evidence(src) and not src.get("error") for src in sources)),
        "items_with_retail_product_url": sum(1 for sources in rows if any(is_retail_product_evidence(src) and not src.get("error") for src in sources)),
        "items_with_tiktok_shop_url": sum(1 for sources in rows if any(src.get("source_kind") == "tiktok_shop_apify" for src in sources)),
        "items_with_cached_tiktok_shop_url": sum(1 for sources in rows if any(src.get("source_kind") == "tiktok_shop_apify" and src.get("cache_status") for src in sources)),
        "verified_urls_total": sum(1 for src in all_sources if src.get("url") and not src.get("error")),
        "published_trend_urls_total": sum(1 for src in all_sources if is_published_evidence(src) and not src.get("error")),
        "retail_product_urls_total": sum(1 for src in all_sources if is_retail_product_evidence(src) and not src.get("error")),
        "cached_tiktok_shop_urls_total": len(cached_tiktok_sources),
        "collection_error_records": sum(1 for src in all_sources if src.get("error")),
    }


def coverage_gap_summary(evidence_by_item: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Summarize item/category evidence gaps for the next operator loop.

    This is diagnostic only: missing-gap records do not change scores and do not
    turn generated search probes into evidence. The goal is to make avoidable
    blind spots (for example one missing TikTok Shop listing, or a zero-trend
    category) visible in both internal and sanitized public collection notes so
    the next autonomous run can target a concrete fix instead of repeating a
    vague "improve evidence" reminder.
    """
    rows = flatten_items()
    categories: dict[str, dict[str, Any]] = {}
    missing_trend_items: list[dict[str, Any]] = []
    missing_tiktok_items: list[dict[str, Any]] = []
    missing_retail_items: list[dict[str, Any]] = []

    for row in rows:
        item_id = str(row.get("id") or "")
        category_id = str(row.get("category_id") or "")
        category_name = str(row.get("category_name") or category_id or "Uncategorized")
        sources = [src for src in evidence_by_item.get(item_id, []) if isinstance(src, dict)]
        has_trend = any(is_published_evidence(src) and not src.get("error") for src in sources)
        has_retail = any(is_retail_product_evidence(src) and not src.get("error") for src in sources)
        has_tiktok = any(src.get("source_kind") == "tiktok_shop_apify" and not src.get("error") for src in sources)

        cat = categories.setdefault(category_id, {
            "category_id": category_id,
            "category_name": category_name,
            "items": 0,
            "trend_items": 0,
            "retail_product_items": 0,
            "tiktok_shop_items": 0,
        })
        cat["items"] += 1
        cat["trend_items"] += 1 if has_trend else 0
        cat["retail_product_items"] += 1 if has_retail else 0
        cat["tiktok_shop_items"] += 1 if has_tiktok else 0

        item_gap = {
            "item_id": item_id,
            "item_name": row.get("name"),
            "category_id": category_id,
            "category_name": category_name,
        }
        if not has_trend:
            missing_trend_items.append(item_gap)
        if not has_tiktok:
            missing_tiktok_items.append(item_gap)
        if not has_retail:
            missing_retail_items.append(item_gap)

    weak_categories = []
    for cat in categories.values():
        total = max(1, int(cat.get("items") or 0))
        weak_categories.append({
            **cat,
            "trend_ratio": round(int(cat.get("trend_items") or 0) / total, 2),
            "tiktok_shop_ratio": round(int(cat.get("tiktok_shop_items") or 0) / total, 2),
            "retail_product_ratio": round(int(cat.get("retail_product_items") or 0) / total, 2),
        })
    weak_categories.sort(key=lambda cat: (cat["trend_ratio"], cat["tiktok_shop_ratio"], cat["category_name"]))

    return {
        "summary": {
            "published_trend_missing_items": len(missing_trend_items),
            "tiktok_shop_missing_items": len(missing_tiktok_items),
            "retail_product_missing_items": len(missing_retail_items),
            "zero_trend_categories": sum(1 for cat in weak_categories if int(cat.get("trend_items") or 0) == 0),
        },
        "weak_categories": weak_categories,
        "missing_published_trend_items": missing_trend_items[:24],
        "missing_tiktok_shop_items": missing_tiktok_items[:12],
        "missing_retail_product_items": missing_retail_items[:12],
        "discipline_note": "Gap records are diagnostics only; search/watchlist URLs remain non-scoring and trend claims still require dated captured URLs.",
    }


def collection_next_actions(totals: dict[str, Any], gaps: dict[str, Any] | None = None) -> list[str]:
    actions = []
    gaps = gaps or {}
    gap_summary = gaps.get("summary", {}) if isinstance(gaps, dict) else {}
    apify = source_health("apify_tiktok_shop")
    apify_status = apify.get("status")
    if apify_status == "success_sharded_after_full_failure":
        shards = apify.get("shards_succeeded") or apify.get("shards_requested") or "n/a"
        actions.append(
            f"TikTok Shop full actor run failed, but sharded fallback recovered fresh supply URLs through {shards} shard(s). 다음 run에서 full-payload failure가 반복되면 shard size/actor limit를 조정합니다."
        )
    elif apify_status == "success_sharded_with_partial_cache":
        cached_items = int(apify.get("partial_cached_items") or 0)
        actions.append(
            f"TikTok Shop sharded fallback recovered fresh URLs but {cached_items}개 item은 최근 cache를 supply fallback으로 표시했습니다. 다음 run에서 missing shard/query를 재확인합니다."
        )
    elif apify_status == "success_with_partial_cache":
        cached_items = int(apify.get("partial_cached_items") or 0)
        actions.append(
            f"TikTok Shop actor는 성공했지만 {cached_items}개 item이 이번 dataset에서 빠져 최근 cache를 supply fallback으로 표시했습니다. 다음 run에서 해당 item의 fresh listing capture를 재확인합니다."
        )
    elif apify_status == "failed_using_cache":
        actions.append("TikTok Shop actor는 실패했지만 최근 성공 cache를 supply fallback으로 사용했습니다. 다음 run에서 actor/upstream 재시도 후 cache freshness를 갱신해야 합니다.")
    elif apify_status in {"failed", "success_empty", "skipped"}:
        actions.append("TikTok Shop 수집 상태를 다음 run에서 먼저 확인: actor/upstream throttle이면 재시도, token/enablement 문제면 env 복구.")
    if int(totals.get("items_with_published_trend_url") or 0) < 12:
        actions.append("published/date-bearing source 보강: weak category별 item-specific article/post/thread/listing URL capture 우선.")
    missing_trend_count = int(gap_summary.get("published_trend_missing_items") or 0)
    if missing_trend_count:
        weakest = [
            str(cat.get("category_name"))
            for cat in gaps.get("weak_categories", [])[:3]
            if isinstance(cat, dict)
        ] if isinstance(gaps, dict) else []
        actions.append(
            f"published trend URL gap {missing_trend_count}개 item 유지: "
            + (", ".join(weakest) if weakest else "weakest categories")
            + "부터 item-level dated source capture를 보강합니다."
        )
    zero_trend_categories = [
        str(cat.get("category_name"))
        for cat in gaps.get("weak_categories", [])[:4]
        if isinstance(cat, dict) and int(cat.get("trend_items") or 0) == 0
    ] if isinstance(gaps, dict) else []
    if zero_trend_categories:
        actions.append(
            "zero-trend category 유지: "
            + ", ".join(zero_trend_categories)
            + ". 다음 run은 broad category가 아니라 item-level dated URL capture를 우선합니다."
        )
    missing_tiktok = gaps.get("missing_tiktok_shop_items", []) if isinstance(gaps, dict) else []
    if missing_tiktok:
        names = ", ".join(
            str(item.get("item_name") or item.get("item_id"))
            for item in missing_tiktok[:3]
            if isinstance(item, dict)
        )
        actions.append(
            f"TikTok Shop social-commerce coverage gap {gap_summary.get('tiktok_shop_missing_items', len(missing_tiktok))}개: "
            f"{names}. strict alias/query 보강은 supply validation용이며 trend claim으로 승격하지 않습니다."
        )
    if int(totals.get("items_with_retail_product_url") or 0) < int(totals.get("items_requested") or 0):
        actions.append("BSS/wholesale product URL coverage 보강: jewelry/nails/tools처럼 Shopify suggest가 약한 category에 vendor-specific collector 필요.")
    return actions or ["현재 collection health에 즉시 조치가 필요한 source outage는 없습니다."]


def source_cap_policy() -> dict[str, Any]:
    """Expose the verified-source cap policy without leaking env/secrets."""
    return {
        "policy_id": "trend_preserving_verified_source_cap_v1",
        "published_first": True,
        "published_per_item_cap": int_env("SOURCE_CAP_PUBLISHED_PER_ITEM", 8, 1, 20),
        "retail_per_item_cap": int_env("SOURCE_CAP_RETAIL_PER_ITEM", 10, 1, 24),
        "total_pre_tiktok_per_item_cap": int_env("SOURCE_CAP_TOTAL_PER_ITEM", 14, 4, 32),
        "purpose": "Keep dated article/post/news URLs in rankings.json before same-day product/listing URLs can fill the per-item cap; supply URLs remain validation only and do not create trend movement.",
    }


def write_collection_notes(evidence_by_item: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    totals = evidence_collection_totals(evidence_by_item)
    gaps = coverage_gap_summary(evidence_by_item)
    notes = {
        "generated_at": utc_now(),
        "date": CURRENT_DATE.isoformat(),
        "source_health": COLLECTION_HEALTH,
        "evidence_totals": totals,
        "coverage_gaps": gaps,
        "source_cap_policy": source_cap_policy(),
        "limitations": [
            "collection notes는 source/API health와 URL coverage 진단용이며, 검색 URL을 evidence로 승격하지 않습니다.",
            "TikTok Shop product URLs는 social-commerce supply validation이며 published/date-bearing trend claim을 만들지 않습니다.",
            "Published trend URLs are preserved before product/listing URL caps so older dated sources are not hidden by same-day supply validation.",
            "error_summary에는 token/key 값을 저장하지 않도록 redaction을 적용합니다.",
        ],
        "next_actions": collection_next_actions(totals, gaps),
    }
    COLLECTION_NOTES_PATH.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    return notes


def retail_signal_sentence(row: dict[str, Any], trend_evidence: list[dict[str, Any]], retail_evidence: list[dict[str, Any]], timeframe: str) -> str:
    category_notes = {
        "wigs-hair-pieces": "wig 고객의 install 편의성, lace 자연스러움, 가격대 선택 신호를 봅니다",
        "braiding-crochet-hair": "protective style 예약/시즌 수요와 반복 구매 가능성을 봅니다",
        "hair-care-styling": "wig/braid 관리에 붙는 소모성 add-on인지 봅니다",
        "lashes-brows": "DIY glam·event look과 front-end impulse 구매 가능성을 봅니다",
        "nails": "salon 대체/DIY nail-art 수요와 작은 add-on 가능성을 봅니다",
        "makeup-cosmetics": "lip/eye/complexion 반복 구매와 shade relevance를 봅니다",
        "tools-accessories": "핵심 hair 제품에 붙는 attach-rate와 소모품성을 봅니다",
        "jewelry-fashion-accessories": "BSS checkout/front wall에서 look-completion add-on으로 팔 수 있는지 봅니다",
    }
    category_note = category_notes.get(row["category_id"], "BSS retail fit을 봅니다")
    if trend_evidence:
        lead = trend_evidence[0]
        title = lead.get("title") or lead.get("domain") or "verified source"
        date = lead.get("published_date") or lead.get("seendate") or "date n/a"
        publisher = lead.get("publisher") or lead.get("domain") or "source"
        return f"{date} 발행된 {publisher}의 '{title}' 등 {len(trend_evidence)}개 발행 URL이 item 신호를 뒷받침합니다. {category_note}."
    if retail_evidence:
        lead = retail_evidence[0]
        store = lead.get("publisher") or lead.get("domain") or "BSS/wholesale/marketplace source"
        title = lead.get("title") or row["name"]
        cached_count = sum(1 for src in retail_evidence if src.get("cache_status"))
        cache_note = ""
        if cached_count:
            cache_note = f" 이 중 {cached_count}개 TikTok Shop URL은 current actor failure 때문에 이전 성공 capture cache로 라벨링했습니다."
        return f"발행일 있는 trend URL은 아직 없지만 {store}의 상품 URL('{title}') 등 {len(retail_evidence)}개 listing을 확인했습니다.{cache_note} TikTok Shop/marketplace listing은 trend claim이 아니라 social-commerce supply/availability 신호로만 사용합니다. {category_note}."
    if timeframe == "weekly":
        return f"최근 14일 내 item-specific 발행 URL 또는 실제 상품 URL이 없어 이번 주 트렌드 주장으로 올리지 않고 watchlist로만 표시합니다. {category_note}."
    return f"이 기간에 item-specific 실제 URL 근거가 부족합니다. 순위는 BSS 적합도와 시즌성 기반의 watchlist 성격이며, 트렌드 주장으로 해석하면 안 됩니다."


def previous_snapshot() -> dict[str, Any] | None:
    if not HISTORY_PATH.exists():
        return None
    try:
        history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    runs = history.get("runs", [])
    # Ignore same-day rebuilds while developing/deploying. Movement should compare
    # against the previous research run date, not an earlier build from today.
    for run in runs:
        if run.get("date") and run.get("date") < CURRENT_DATE.isoformat():
            return run
    return None


def previous_lookup(prev: dict[str, Any] | None, timeframe: str) -> dict[str, dict[str, Any]]:
    if not prev:
        return {}
    rows = prev.get("rankings", {}).get(timeframe, [])
    return {row.get("item_id"): row for row in rows}


def classify_momentum(score: float, trend_count: int, recent_trend_count: int, retail_count: int, prev_row: dict[str, Any] | None) -> tuple[str, float | None, str]:
    previous_score = (prev_row or {}).get("score")
    previous_counts = (prev_row or {}).get("source_counts") or {}
    previous_trend = previous_counts.get("trend_evidence", previous_counts.get("news_magazine"))
    if previous_score is None:
        if recent_trend_count:
            return "new_shift", None, "새 run에서 최근 발행 URL 근거가 잡힌 item"
        if trend_count:
            return "new", None, "새 run에서 발행일 있는 실제 URL 근거가 있는 item"
        if retail_count:
            return "watchlist", None, "실제 상품 URL은 확인했지만 발행일 있는 trend 근거가 없어 watchlist"
        return "watchlist", None, "실제 URL 근거가 아직 없어 watchlist로만 표시"
    score_change = round(score - float(previous_score), 1)
    if not trend_count:
        return "watchlist", score_change, "발행일 있는 trend 근거가 없어 변화 주장 금지"
    if recent_trend_count and (previous_trend in (None, 0) or score_change >= 4):
        return "new_shift", score_change, "최근 발행 URL 근거가 추가되어 주간 변화 후보"
    if score_change >= 5:
        return "accelerating", score_change, "발행 근거와 점수 상승폭이 함께 커진 가속 후보"
    if score_change <= -5:
        return "cooling", score_change, "발행 근거/점수 하락폭이 커서 cooling 후보"
    return "stable", score_change, "발행 근거는 있으나 이전 run 대비 큰 변화는 없음"


def choose_item_image(row: dict[str, Any], trend_evidence: list[dict[str, Any]], retail_evidence: list[dict[str, Any]]) -> dict[str, str]:
    for src in retail_evidence:
        if src.get("image_url"):
            return {
                "image_url": str(src["image_url"]),
                "image_source": str(src.get("publisher") or src.get("domain") or "BSS product page"),
                "image_status": "verified_product_image",
            }
    for src in trend_evidence:
        if src.get("image_url"):
            return {
                "image_url": str(src["image_url"]),
                "image_source": str(src.get("publisher") or src.get("domain") or "published source"),
                "image_status": "published_source_image",
            }
    return {
        "image_url": category_visual_url(row),
        "image_source": "Category visual placeholder",
        "image_status": "category_visual",
    }


def score_item(row: dict[str, Any], timeframe: str, all_evidence: list[dict[str, Any]], watchlist: list[dict[str, Any]], prev_row: dict[str, Any] | None) -> dict[str, Any]:
    published_all = [src for src in all_evidence if not src.get("error") and is_published_evidence(src)]
    trend_evidence = [src for src in published_all if is_within_days(src, TIMEFRAMES[timeframe]["days"])]
    recent_trend = [src for src in trend_evidence if is_within_days(src, 14)]
    retail_evidence = [src for src in all_evidence if not src.get("error") and is_retail_product_evidence(src)]
    verified = trend_evidence + retail_evidence
    article_count = len(trend_evidence)
    tiktok_shop_count = sum(1 for src in retail_evidence if src.get("source_kind") == "tiktok_shop_apify")
    cached_tiktok_shop_count = sum(
        1
        for src in retail_evidence
        if src.get("source_kind") == "tiktok_shop_apify" and src.get("cache_status")
    )
    source_types = {src.get("source_type") for src in verified if src.get("source_type")}
    trend_domains = {src.get("domain") or src.get("publisher") for src in trend_evidence if src.get("domain") or src.get("publisher")}
    retail_domains = {src.get("domain") or src.get("publisher") for src in retail_evidence if src.get("domain") or src.get("publisher")}
    seasonal = CURRENT_MONTH in set(row.get("season_months", []))
    bss_fit = int(row.get("bss_fit", 3))

    exact_count = sum(1 for src in trend_evidence if src.get("evidence_relevance") == "exact_phrase")
    item_type_count = sum(1 for src in trend_evidence if src.get("evidence_relevance") == "item_type")
    recent_exact_count = sum(1 for src in recent_trend if src.get("evidence_relevance") == "exact_phrase")
    retail_exact_count = sum(1 for src in retail_evidence if src.get("evidence_relevance") == "exact_phrase")
    trend_score = min(42, exact_count * 13 + item_type_count * 8 + len(trend_domains) * 3)
    recency_score = min(20, recent_exact_count * 11 + (len(recent_trend) - recent_exact_count) * 7)
    retail_score = min(16, retail_exact_count * 4 + (len(retail_evidence) - retail_exact_count) * 2 + len(retail_domains) * 2)
    if timeframe == "weekly":
        retail_score = min(retail_score, 8)
    elif timeframe == "monthly":
        retail_score = min(retail_score, 10)
    bss_score = bss_fit * 5
    season_score = 7 if seasonal else 0
    specificity_score = 6
    raw = trend_score + recency_score + retail_score + bss_score + season_score + specificity_score
    # Published/date-bearing evidence is required for trend-level scores. Store
    # product URLs keep useful items visible but cannot make a weekly trend alone.
    if not trend_evidence:
        raw = min(raw, 46 if retail_evidence else 34)
    score = max(1, min(100, raw))

    momentum, score_change, change_note = classify_momentum(score, len(trend_evidence), len(recent_trend), len(retail_evidence), prev_row)
    previous_rank = (prev_row or {}).get("rank")

    evidence_summary = []
    if trend_evidence:
        evidence_summary.append(f"발행일 있는 trend URL {len(trend_evidence)}개")
        if recent_trend:
            evidence_summary.append(f"최근 14일 발행 근거 {len(recent_trend)}개")
        if exact_count:
            evidence_summary.append(f"정확 phrase match {exact_count}개")
        if item_type_count:
            evidence_summary.append(f"item-type/adjacent match {item_type_count}개")
        if trend_domains:
            evidence_summary.append(f"서로 다른 publisher/domain {len(trend_domains)}개")
        top_titles = [src.get("title") for src in trend_evidence[:2] if src.get("title")]
        if top_titles:
            evidence_summary.append("대표 trend 근거: " + " / ".join(top_titles))
    else:
        evidence_summary.append("발행일 있는 trend URL 없음 — 주간 변화 claim 금지")
    if retail_evidence:
        stores = sorted({src.get("publisher") or src.get("domain") for src in retail_evidence if src.get("publisher") or src.get("domain")})
        label = f"BSS/wholesale/marketplace 실제 상품 URL {len(retail_evidence)}개"
        if tiktok_shop_count:
            label += f" · TikTok Shop {tiktok_shop_count}개"
            if cached_tiktok_shop_count:
                label += f" (cached fallback {cached_tiktok_shop_count}개)"
        evidence_summary.append(label + (f" ({', '.join(stores[:3])})" if stores else ""))
    evidence_summary.append(f"BSS 적합도 {bss_fit}/5")
    if seasonal:
        evidence_summary.append("현재 시즌 적합")

    reason = retail_signal_sentence(row, trend_evidence, retail_evidence, timeframe)
    image = choose_item_image(row, trend_evidence, retail_evidence)

    return {
        "item_id": row["id"],
        "item_name": row["name"],
        "category_id": row["category_id"],
        "category_name": row["category_name"],
        "score": round(score, 1),
        "momentum": momentum,
        "score_change": score_change,
        "change_note": change_note,
        "previous_rank": previous_rank,
        "bss_fit": bss_fit,
        "seasonal_now": seasonal,
        "reason_summary": reason,
        "evidence_summary": evidence_summary,
        "display_tip": row["display_tip"],
        "risk": row["risk"],
        "owner_message_en": row["owner_message_en"],
        "image_url": image["image_url"],
        "image_source": image["image_source"],
        "image_status": image["image_status"],
        "image_alt": f"{row['name']} visual",
        "verified_evidence": verified,
        "trend_evidence": trend_evidence,
        "retail_product_evidence": retail_evidence,
        "news_evidence": trend_evidence,
        "watchlist_links": watchlist,
        "manual_references": watchlist,
        "score_breakdown": {
            "trend_evidence": trend_score,
            "recency": recency_score,
            "retail_product_urls": retail_score,
            "bss_fit": bss_score,
            "seasonality": season_score,
            "specificity": specificity_score,
            "cap_applied_without_trend_evidence": not bool(trend_evidence),
        },
        "source_counts": {
            "verified_evidence": len(verified),
            "trend_evidence": len(trend_evidence),
            "recent_trend_evidence": len(recent_trend),
            "recent_evidence": len(recent_trend),
            "retail_product_evidence": len(retail_evidence),
            "tiktok_shop_product_evidence": tiktok_shop_count,
            "cached_tiktok_shop_product_evidence": cached_tiktok_shop_count,
            "article_evidence": article_count,
            "unique_domains": len(trend_domains | retail_domains),
            "unique_trend_domains": len(trend_domains),
            "unique_retail_domains": len(retail_domains),
            "exact_evidence": exact_count,
            "item_type_evidence": item_type_count,
            "retail_exact_evidence": retail_exact_count,
            "watchlist_links": len(watchlist),
            "source_layers": len(source_types),
            "manual_references": len(watchlist),
            "news_magazine": article_count,
        },
    }


def build_rankings() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    rows = flatten_items()
    prev = previous_snapshot()
    evidence_by_item = collect_all_evidence(rows)
    collection_notes = write_collection_notes(evidence_by_item)
    output: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "date": CURRENT_DATE.isoformat(),
        "title": "BSS Beauty Product Trend Rankings",
        "collection_health": collection_notes,
        "methodology": {
            "summary": "Item-only rankings across the broader BSS beauty market. Search/watchlist pages are separated from evidence; published URLs drive trend movement, while live BSS/wholesale/TikTok Shop product URLs validate retail availability and social-commerce supply only.",
            "score_components": ["published trend URL evidence", "recent published evidence", "BSS/wholesale/TikTok Shop product URLs", "BSS fit", "seasonality", "item specificity", "historical movement"],
            "quality_rules": [
                "출처 없는 주장은 trend claim으로 표시하지 않는다.",
                "TikTok/Pinterest/X/Reddit/Amazon/Google Trends/BSS search pages are watchlist links only unless a specific post/listing/article URL is captured.",
                "Apify TikTok Shop product URLs are concrete marketplace/listing evidence; sold counts and seller signals are useful, but they do not create a weekly trend shift without published/date-bearing evidence.",
                "BSS/wholesale product pages are verified supply evidence, but they do not create a weekly trend shift without published/date-bearing evidence.",
                "Weekly movement is NEW SHIFT / ACCELERATING / STABLE / COOLING / WATCHLIST based on published evidence recency and previous run comparison.",
            ],
            "limitations": [
                "Bing News RSS is used for concrete article URLs/dates; BSS/wholesale stores are queried through public product suggest endpoints where available.",
                "TikTok Shop product listings are collected through the authenticated Apify actor when APIFY_TOKEN is configured; TikTok videos, Reddit, Google Trends, and some store layers still require deeper authenticated/API collection for post/thread/metric-level evidence.",
                "Items with no published trend URL evidence are capped and labeled WATCHLIST, not treated as weekly market shifts.",
                "Historical movement becomes stronger after several scheduled evidence-based runs.",
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
            watchlist = watchlist_links(row)
            ranked.append(score_item(row, timeframe, evidence_by_item.get(row["id"], []), watchlist, prev_by_item.get(row["id"])))
        ranked.sort(
            key=lambda r: (
                r["source_counts"]["recent_trend_evidence"],
                r["source_counts"]["trend_evidence"],
                r["source_counts"]["retail_product_evidence"],
                r["score"],
                r["bss_fit"],
                r["item_name"],
            ),
            reverse=True,
        )
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
                {
                    "item_id": r["item_id"],
                    "item_name": r["item_name"],
                    "rank": r["rank"],
                    "score": r["score"],
                    "category_id": r["category_id"],
                    "momentum": r.get("momentum"),
                    "source_counts": r.get("source_counts", {}),
                }
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
