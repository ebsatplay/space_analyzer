"""지역 사업 뉴스·이슈 수집 - 특정 지역에 어떤 사업/정책 이슈가 있는지 뉴스로 파악한다.

카카오에는 뉴스 전용 검색이 없어서(/v2/search/news 는 404) 웹문서 검색을 쓴다.
웹문서 검색은 그대로 쓰면 쓸 수 없는 수준이라 (사전 프로브 실측: "고령군 폐교 활용"
질의에서 지역명이 실제로 등장하는 결과가 20건 중 1~2건, 나머지는 "고령(老齡)" 기사이거나
다른 지역 기사) 아래 5단계 필터를 거친다:

1. 지역명 필터: 선택한 시군구명이 제목이나 본문에 실제로 등장하는 것만 남긴다.
   "고령"이 노인으로 잡히는 문제를 "고령군"처럼 행정 단위까지 붙여서 막는다.
2. 날짜 필터: 최근 12개월만. 영업 타이밍 포착용이라 오래된 기사는 신호가 아니다.
3. 비언론 도메인 제외: 위키·레포트 판매·논문·SEO 콘텐츠팜을 걷어낸다.
4. 제목 휴리스틱: 기사가 아닌 섹션 랜딩 페이지("재무과", "도민뉴스라인")를 걷어낸다.
5. 키워드 실제 포함: 카카오가 질의어를 느슨하게 매칭해서, 질의한 키워드가 한 번도
   나오지 않는 문서를 돌려준다. 키워드가 본문/제목에 실제로 있는지 직접 확인한다.

실행(테스트): python -m analysis.region_news
"""

import re
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from services.kakao_service import search_news

SIGUNGU_NAMES_PATH = "data/reference/sigungu_names.csv"

# 지역 + 각 키워드로 검색해서 합친다. 사업 추진 단계가 드러나는 "타이밍 신호어" 위주.
BUSINESS_KEYWORDS = [
    "공간사업",
    "유휴공간",
    "폐교 활용",
    "공모 선정",
    "타당성 용역",
    "생활SOC",
    "농촌공간정비",
    "도시재생",
    "복합문화공간",
    "아동친화",
    "어린이",
    "돌봄",
]

# 키워드당 수집 페이지 수 (1페이지 = 50건). 키워드 12개 x 3페이지 = 호출 36회
PAGES_PER_KEYWORD = 3
PAGE_SIZE = 50

RECENT_MONTHS = 12

# 기사가 아닌 사이트 (위키/레포트 판매/논문/블로그 플랫폼)
NON_NEWS_DOMAINS = [
    "namu.wiki",
    "wikipedia.org",
    "reportable.kr",
    "earticle.net",
    "tistory.com",
    "blog.",
    "cafe.",
    "post.naver.com",
    "brunch.co.kr",
    # 지역명을 끼워 양산하는 SEO 콘텐츠팜 - 고령군 실측에서 반복 등장한 도메인
    "dokdokplace.kr",
    "falltip.com",
    "infotipguide.com",
    "ezday.co.kr",
    "ggha.net",
    "soonwidot.co.kr",
    "dailautos.co.kr",
    "platformdodam.com",
    "dodam-platform.com",
    "goifuneral.co.kr",
    "weseb.com",
    "lapl.co.kr",
    "publicsensor.com",
    "allcompany.co.kr",
    "study-short-cut.com",
    "insureloanhub.com",
    "tripmate.co.kr",
    "bidnara.com",  # 입찰공고 모음 - 신호는 되지만 기사가 아니라 제외한다
]

# 도메인 모양만으로 걸러낼 수 있는 것들
# xn--: 한글 도메인(퓨니코드)은 실측에서 전부 SEO 양산 사이트였다
# wwv.: 'www' 오타를 노린 타이포스쿼팅
NON_NEWS_HOST_PREFIXES = ("wwv.",)
NON_NEWS_HOST_MARKERS = ("xn--",)

# 기사 제목이 아닌 것 (게시판 ID, 연도만, 부서명 같은 섹션 랜딩 페이지)
SECTION_TITLE_PATTERNS = [
    re.compile(r"^[0-9a-f]{12,}$", re.I),       # 25c7a12eda6eb09e116692f2ae260005
    re.compile(r"^BBS[_-]", re.I),              # BBS_0000193
    re.compile(r"^[\d\s\-.]+$"),                 # "2026", "2026-10"
    re.compile(r"^.{0,6}(과|실|팀|센터)$"),      # "재무과", "기획실"
]

# 제목에 공백이 전혀 없고 짧으면 기사 제목이 아니라 사이트/섹션 이름일 가능성이 높다
MAX_NO_SPACE_TITLE_LENGTH = 12

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_sigungu_names(path=SIGUNGU_NAMES_PATH):
    """시군구 이름 목록을 읽는다 (인구 데이터에서 만들어 둔 것)."""
    return pd.read_csv(path, dtype=str)["sigungu_nm"].tolist()


def region_from_address(address, sigungu_names=None):
    """주소에서 뉴스 검색에 쓸 지역명을 뽑는다.

    카카오 주소는 시도를 줄여 쓰기 때문에("경북 고령군 대가야읍") 시도명으로는 맞출 수
    없다. 그래서 sigungu_names.csv의 시군구 이름 뒷부분과 맞춰본다.
    '경상북도 고령군' -> '고령군', '경상북도 포항시 북구' -> '포항시 북구'
    ('북구'만 쓰면 다른 광역시의 북구 기사까지 걸려서 시 이름을 붙여둔다)

    반환: 지역명 문자열, 못 찾으면 None
    """
    if not isinstance(address, str):
        return None

    if sigungu_names is None:
        sigungu_names = load_sigungu_names()

    # 뒤 토큰이 긴 것부터 맞춰본다 ('포항시 북구'가 '포항시'보다 먼저 걸리도록)
    tails = set()
    for name in sigungu_names:
        tokens = name.split()
        if len(tokens) >= 3:
            tails.add(" ".join(tokens[-2:]))
        elif len(tokens) == 2:
            tails.add(tokens[-1])
        else:
            tails.add(name)

    for tail in sorted(tails, key=len, reverse=True):
        if tail in address:
            return tail
    return None


def _parse_datetime(value):
    """카카오 datetime('2026-10-16T09:42:20.000+09:00')을 datetime으로 바꾼다."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_non_news_domain(url):
    lowered = url.lower()
    if any(domain in lowered for domain in NON_NEWS_DOMAINS):
        return True
    host = lowered.split("//")[-1].split("/")[0]
    if host.startswith(NON_NEWS_HOST_PREFIXES):
        return True
    return any(marker in host for marker in NON_NEWS_HOST_MARKERS)


def _keyword_appears(keyword, title, contents):
    """질의한 키워드가 글에 실제로 들어 있는지 확인한다.

    카카오 웹문서 검색은 질의어를 느슨하게 매칭해서, "공간사업"으로 검색해도 그 말이
    한 번도 안 나오는 문서를 돌려준다 ("팰리세이드 신차 장기렌트 고령군" 같은 SEO 문서가
    지역명만 걸려서 들어온다). 그래서 키워드가 실제로 있는지 직접 확인한다.
    공백은 무시하고 비교한다 ("폐교 활용" <-> "폐교활용").
    """
    text = f"{title} {contents}"
    if keyword in text:
        return True
    return keyword.replace(" ", "") in text.replace(" ", "")


def _is_section_title(title):
    """기사 제목이 아니라 섹션/사이트 이름으로 보이는지 판단한다."""
    stripped = title.strip()
    if not stripped:
        return True
    if any(pattern.match(stripped) for pattern in SECTION_TITLE_PATTERNS):
        return True
    # 공백 없는 짧은 제목은 사이트명/부서명일 가능성이 높다 ("도민뉴스라인", "로컬(LOCAL)세계")
    return " " not in stripped and len(stripped) <= MAX_NO_SPACE_TITLE_LENGTH


def _source_from_url(url):
    """url에서 출처(도메인)를 꺼낸다. 'www.', 'm.' 접두어는 떼고 보여준다."""
    host = url.split("//")[-1].split("/")[0]
    for prefix in ("www.", "m.", "v."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def get_region_news(
    region_name,
    keywords=None,
    recent_months=RECENT_MONTHS,
    pages_per_keyword=PAGES_PER_KEYWORD,
    progress_callback=None,
):
    """지역명 + 사업 키워드 프리셋으로 뉴스를 모아 4단계 필터를 거쳐 돌려준다.

    같은 기사가 여러 키워드에 걸리므로 url 기준으로 합치고, 어떤 키워드로 걸렸는지
    matched_keywords에 모아둔다 (화면에서 "공모 선정" 같은 배지로 보여주기 위해).

    반환: dict
      - items: [{"title","contents","url","source","published","matched_keywords"}, ...]
        최신순 정렬
      - meta: 수집/필터 단계별 건수 (어디서 얼마나 걸러졌는지 화면에서 설명하기 위해)
    """
    if keywords is None:
        keywords = BUSINESS_KEYWORDS

    cutoff = datetime.now(timezone.utc) - timedelta(days=round(recent_months * 30.4))

    collected = 0
    by_url = {}
    dropped = {"지역명": 0, "날짜": 0, "도메인": 0, "제목": 0, "키워드": 0}

    for index, keyword in enumerate(keywords, start=1):
        if progress_callback:
            progress_callback(index, len(keywords), keyword)

        for page in range(1, pages_per_keyword + 1):
            result = search_news(f"{region_name} {keyword}", size=PAGE_SIZE, page=page)
            if result is None:
                break

            for item in result["items"]:
                collected += 1

                # 1. 지역명 필터 (필수) - "고령"이 노인으로 잡히는 것을 막는 핵심 단계
                if region_name not in item["title"] and region_name not in item["contents"]:
                    dropped["지역명"] += 1
                    continue

                # 2. 날짜 필터 - 영업 타이밍용이라 오래된 기사는 신호가 아니다
                published = _parse_datetime(item["datetime"])
                if published is None or published < cutoff:
                    dropped["날짜"] += 1
                    continue

                # 3. 비언론 도메인 제외
                if _is_non_news_domain(item["url"]):
                    dropped["도메인"] += 1
                    continue

                # 4. 제목 휴리스틱 - 섹션 랜딩 페이지 제외
                if _is_section_title(item["title"]):
                    dropped["제목"] += 1
                    continue

                # 5. 키워드 실제 포함 - 카카오가 느슨하게 매칭해서 보낸 문서를 걷어낸다
                if not _keyword_appears(keyword, item["title"], item["contents"]):
                    dropped["키워드"] += 1
                    continue

                existing = by_url.get(item["url"])
                if existing is None:
                    by_url[item["url"]] = {
                        "title": item["title"],
                        "contents": item["contents"],
                        "url": item["url"],
                        "source": _source_from_url(item["url"]),
                        "published": published,
                        "matched_keywords": [keyword],
                    }
                elif keyword not in existing["matched_keywords"]:
                    existing["matched_keywords"].append(keyword)

            if result["is_end"]:
                break

    items = sorted(by_url.values(), key=lambda news: news["published"], reverse=True)

    return {
        "items": items,
        "meta": {
            "region_name": region_name,
            "keywords": list(keywords),
            "collected": collected,
            "kept": len(items),
            "dropped": dropped,
            "recent_months": recent_months,
            "api_calls": len(keywords) * pages_per_keyword,
        },
    }


def main():
    region_name = "고령군"
    print(f'"{region_name}" 지역 사업 뉴스 검색 (키워드 {len(BUSINESS_KEYWORDS)}개)')

    def report(index, total, keyword):
        print(f"  ({index}/{total}) {keyword}")

    result = get_region_news(region_name, progress_callback=report)
    meta = result["meta"]

    print(f"\n수집 {meta['collected']}건 -> 최종 {meta['kept']}건")
    print(f"걸러낸 내역: {meta['dropped']}")
    print(f"API 호출: {meta['api_calls']}회\n")

    for news in result["items"][:15]:
        badges = " ".join(f"[{keyword}]" for keyword in news["matched_keywords"])
        print(f"{news['published'].strftime('%Y-%m-%d')} | {news['source']}")
        print(f"  {news['title']}")
        print(f"  {badges}")


if __name__ == "__main__":
    main()
