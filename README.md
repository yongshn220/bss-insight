# GNS BSS Trend Ranking

Beauty Supply Store(BSS) retail 사장님이 바로 이해할 수 있도록 만든 **item-only trend ranking dashboard**입니다. 리포트형 글보다 온라인 스토어/랭킹 페이지처럼 카테고리별 아이템 순위를 보여주는 것이 목적입니다.

## 핵심 방향

- Ranking 대상은 **item만** 사용합니다.
- 화면은 `Weekly`, `Monthly`, `Quarterly`, `Yearly` 탭으로 나눕니다.
- 카테고리는 온라인 스토어처럼 분리합니다.
  - Earrings
  - Necklaces & Pendants
  - Hair Jewelry
  - Anklets & Body Jewelry
  - Rings & Bracelets
  - Sets & Occasion Jewelry
- 각 item은 rank, score, momentum, 근거 요약, source layer, retail display tip, risk/caution, owner message를 가집니다.
- 공개 접근 가능한 source부터 사용합니다. TikTok/X/Amazon/Google Trends/Reddit/BSS stores는 MVP 단계에서 reference/watchlist 링크로 붙이고, Google News/RSS는 실제 fetch합니다.

## 구조

```text
assets/style.css                UI 스타일
scripts/collect_rankings.py     공개 데이터 기반 ranking data 생성
scripts/build_site.py           정적 HTML 생성
scripts/build_public.py         Vercel용 public/ 출력 생성
scripts/run_weekly_update.py    ranking data 생성 + site build 실행
data/rankings.json              최신 ranking data
data/ranking_history.json       ranking history snapshot
package.json                    Vercel build command
vercel.json                     Vercel output config
```

로컬 preview용 HTML은 `index.html`, `rankings/`, `items/`에 생성됩니다. Vercel 배포용 산출물은 `public/`에 복사됩니다.

## 로컬 실행

```bash
cd /opt/data/gns_research_hub
npm run build
python3 -m http.server 8765
```

브라우저에서:

```text
http://127.0.0.1:8765/index.html
http://127.0.0.1:8765/rankings/weekly.html
```

## Vercel 배포

Vercel Git import 또는 Vercel CLI에서 이 repo를 사용합니다.

```bash
npm run build
```

Vercel 설정:

```text
Build Command: npm run build
Output Directory: public
```

## 데이터/점수 주의사항

현재 score는 public-data MVP 기준의 방향성 점수입니다. 실제 판매 예측이 아니라, BSS retail owner가 볼 만한 item signal을 빠르게 정리하기 위한 ranking입니다.

향후 강화 우선순위:

1. Google Trends 실제 수치 연동
2. Reddit API/search parsing
3. Amazon search/ranking/review signal 강화
4. TikTok/X source 강화
5. BSS online store category scraping 강화
6. 누적 ranking history 기반 momentum 개선
