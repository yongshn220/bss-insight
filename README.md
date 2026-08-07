# GNS BSS Trend Ranking

Beauty Supply Store(BSS) retail 사장님이 바로 이해할 수 있도록 만든 **item-only trend ranking dashboard**입니다. 리포트형 글보다 온라인 스토어/랭킹 페이지처럼 카테고리별 아이템 순위를 보여주는 것이 목적입니다.

## 핵심 방향

- Ranking 대상은 **item만** 사용합니다. Jewelry만이 아니라 BSS 시장의 wigs, braiding hair, hair care, lashes, nails, cosmetics, tools/accessories, jewelry를 모두 포함합니다.
- Rank에 올라오는 항목은 `piercing`, `hair care` 같은 broad category가 아니라 `20G Surgical Steel Nose Stud`, `Glueless Pre-Cut HD Lace Wig`, `52 Inch Pre-Stretched Braiding Hair`처럼 실제 매장에서 SKU/상품군으로 테스트할 수 있는 구체적 제품 단위여야 합니다.
- 화면은 `Weekly`, `Monthly`, `Quarterly`, `Yearly` 탭으로 나눕니다.
- 카테고리는 온라인 스토어처럼 분리합니다.
  - Wigs & Hair Pieces
  - Braiding & Crochet Hair
  - Hair Care & Styling
  - Lashes & Brows
  - Nails
  - Makeup & Cosmetics
  - Tools & Accessories
  - Jewelry & Fashion Accessories
- 각 item은 rank, score, momentum, 근거 요약, source layer, retail display tip, risk/caution, owner message를 가집니다.
- 공개 접근 가능한 source부터 사용합니다. Bing News RSS처럼 **발행일 있는 실제 URL**은 trend movement에 반영하고, Ebonyline/Glamourtress/HairToBeauty/WigTypes/Beauty of New York 등 **실제 BSS 상품 URL**은 supply/availability 근거로만 분리해 표시합니다.
- TikTok/X/Amazon/Google Trends/Reddit/BSS stores 검색 URL은 **watchlist only**로 분리합니다. 특정 post/listing/article URL이 잡히기 전에는 evidence로 세지 않습니다.
- 발행일 있는 trend URL이 없는 항목은 trend claim으로 표시하지 않고 `WATCHLIST`로 낮춰 표시합니다. Live product URL만으로는 “이번 주 변화”를 만들지 않습니다.

## 구조

```text
assets/style.css                UI 스타일
scripts/collect_rankings.py     공개 데이터 기반 ranking data 생성
scripts/build_site.py           정적 HTML 생성
scripts/build_public.py         Vercel용 public/ 출력 생성
scripts/run_weekly_update.py    ranking data 생성 + site build 실행
scripts/review_rankings.py      Playwright QA 후 좋은 점/개선점/다음 loop focus 생성
data/rankings.json              최신 ranking data
data/ranking_history.json       ranking history snapshot
data/operations_review.json     최신 post-QA review
data/next_loop_focus.json       다음 collection loop에 적용할 focus queries
data/growth_goal.json           500 average daily visits goal, analytics providers, growth guardrails
data/marketing_backlog.json     owner-share/SNS campaign drafts and experiments
data/sns_posting_rules.json     X/xurl posting rule, frequency limits, guardrails, UTM template
public/data/operations_review_public.json  live verification용 sanitized review output
public/data/growth_goal_public.json        sanitized growth/analytics status
public/data/sns_posting_rules_public.json  sanitized SNS posting rule
package.json                    Vercel build command
vercel.json                     Vercel output config
```

로컬 preview용 HTML은 `index.html`, `rankings/`, `items/`에 생성됩니다. Vercel 배포용 산출물은 `public/`에 복사됩니다.

## 로컬 실행

```bash
cd /opt/data/gns_research_hub
npm run refresh
python3 -m http.server 8765
```

브라우저에서:

```text
http://127.0.0.1:8765/index.html
http://127.0.0.1:8765/rankings/weekly.html
```

## Playwright 버그/작동 테스트

첫 실행 또는 브라우저 캐시가 없을 때만 Chromium을 설치합니다.

```bash
npm install
npm run test:e2e:install
```

실제 검증은 아래 명령으로 실행합니다. `npm run build`를 먼저 돌린 뒤 local static server를 띄우고, desktop/mobile Chromium에서 페이지 렌더링, 탭/카테고리 이동, item detail click-through/back navigation, internal link/hash anchor, client-side error/404를 함께 확인합니다.

```bash
npm run test:e2e
```

최종 QA가 통과하면 아래 review script를 실행해 이번 run의 좋은 부분, 개선해야 할 부분, 다음 loop에서 더 깊게 볼 item/query를 기록합니다. 다음 `collect_rankings.py` 실행은 `data/next_loop_focus.json`을 읽어 약한 item에 focus query를 추가 적용합니다. Review script는 QA 이후 stale public artifact가 생기지 않도록 `public/data/operations_review_public.json`도 즉시 갱신합니다.

```bash
python3 scripts/review_rankings.py --playwright-summary "Playwright passed"
```

QA와 review를 한 번에 실행할 때:

```bash
npm run test:e2e:review
```

headed browser로 확인할 때:

```bash
npm run test:e2e:headed
```

## Vercel 배포

Vercel Git import 또는 Vercel CLI에서 이 repo를 사용합니다.

```bash
npm run refresh   # evidence 수집 + local/public build
npm run build     # committed data로 정적 사이트만 build
```

Vercel 설정:

```text
Build Command: npm run build
Output Directory: public
```

## Growth / analytics / SNS 운영

- Vercel Web Analytics는 project `gns_research_hub`에서 활성화하고, live에서는 `/_vercel/insights/script.js`를 통해 `growth.js` custom event를 받을 수 있게 합니다.
- GA4는 `G-SW7HBY6WRE` measurement ID를 모든 generated page `<head>`에 삽입합니다.
- `assets/growth.js`는 `growth_exposure`, `growth_click`, `growth_share_copy_result`를 local event buffer, Vercel Analytics(`window.va`), GA4(`gtag`)로 fan-out합니다.
- SNS 기본 채널은 X/Twitter이며, posting rule은 `data/sns_posting_rules.json`에 기록합니다. 실제 external posting은 xurl CLI 설치와 OAuth auth가 완료된 뒤 rule 범위 안에서만 진행합니다.

## 데이터/점수 주의사항

현재 score는 public-data MVP 기준의 방향성 점수입니다. 실제 판매 예측이 아니라, BSS retail owner가 볼 만한 item signal을 빠르게 정리하기 위한 ranking입니다. 단, 검색 링크 개수는 score에 반영하지 않고, 발행일 있는 trend URL, 최근성, BSS/wholesale live product URL, BSS 적합도, 시즌성을 분리해 반영합니다.

신뢰성 규칙:

- `NEW SHIFT`, `ACCELERATING`, `STABLE`, `COOLING` 같은 movement는 발행일 있는 trend URL과 이전 run 비교가 있을 때만 붙입니다.
- BSS/wholesale live product URL은 “실제 판매/공급 확인”으로 유용하지만, 그 자체로 “이번 주 뜬 trend”라고 표시하지 않습니다.
- item-specific 발행 URL이 부족하면 score를 cap하고 `WATCHLIST`로 표시합니다.

향후 강화 우선순위:

1. Google Trends 실제 수치 연동
2. Reddit API/search parsing
3. Amazon search/ranking/review signal 강화
4. TikTok/X source 강화 — 검색 URL이 아니라 개별 post/video URL + 날짜 저장
5. BSS online store category/new-arrival scraping 강화
6. 누적 ranking history 기반 momentum 개선
