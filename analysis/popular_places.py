"""블로그·카페 글에서 자주 언급되는 공간을 추출·집계한다.

방법: 카카오 장소검색으로 그 지역의 공간 후보 목록을 뽑고, 같은 지역+목적으로
검색한 블로그/카페 글 텍스트에 각 공간명이 몇 번 등장하는지 센다.

실행(테스트): python -m analysis.popular_places
(services.kakao_service를 import하므로 python analysis/popular_places.py로 직접 실행하면 안 됨)
"""

import sys
from datetime import date

from services.kakao_service import find_location, search_blog_all, search_cafe, search_places_nearby

# 공간 후보를 찾을 때 쓰는 검색 키워드를 유형별로 묶는다.
# 유형은 화면 표시/필터에 쓰고, 키워드는 카카오 장소검색에 그대로 넘긴다.
# (같은 공간이 여러 키워드로 잡히면 먼저 나온 유형으로 확정된다 - 아래 순서가 우선순위)
CANDIDATE_KEYWORD_GROUPS = {
    "전시": ["전시", "전시회", "전시관", "미디어아트", "체험전"],
    "팝업": ["팝업", "팝업스토어"],
    "박물관": ["박물관"],
    "미술관": ["미술관"],
    "과학관": ["과학관"],
    "키즈카페": ["키즈카페"],
    "테마파크": ["테마파크"],
    "공원": ["공원"],
    "관광지": ["관광명소"],
}
CANDIDATE_SEARCH_RADIUS_M = 15000  # 지역 중심에서 공간 후보를 찾을 반경

BLOG_MAX_DOCS = 100
CAFE_MAX_DOCS = 50

# 이보다 짧은 공간명은 흔한 단어와 겹쳐 오탐(예: "공원"만으로 카운트)될 위험이 커서 제외한다
MIN_NAME_LENGTH = 2

TOTAL_STEPS = 4

# --- 글의 신뢰도 신호 판별용 단어 ---
# 협찬은 주로 이미지로 표기돼서 텍스트로는 일부만 잡힌다. 그래서 반대로 "자기 돈 내고 갔다"는
# 진짜 후기 신호도 함께 잡아서 신뢰도를 보완한다.
GENUINE_REVIEW_SIGNALS = [
    "내돈내산", "내돈", "협찬아님", "협찬 아님", "협찬x", "협찬X",
    "솔직후기", "솔직 후기", "재방문", "또갔", "또 갔", "단골",
]
AD_SIGNALS = [
    "제공받아", "제공 받아", "체험단", "원고료", "협찬", "소정의",
    "레뷰", "리뷰노트", "슈퍼멤버스", "대가를 받", "업체로부터",
]

# 정렬 점수에서 광고성 언급에 주는 가중치 (진짜후기/일반보다 덜 반영)
AD_MENTION_WEIGHT = 0.3

# --- 공간명 정규화(핵심 상호명 추출) 설정 ---
# 지도 등록명이 길면("우주떡집 X 토롱이 팝업 - ...") 블로그에선 짧게("우주떡집") 불려서
# 전체일치만 세면 크게 과소집계된다. 그래서 핵심 상호명을 뽑아 부분매칭도 한다.
# 다만 짧거나 흔한 이름으로 부분매칭하면 오탐이 급증하므로 아래 안전장치를 둔다.
NAME_SEPARATORS = ["X", "×", "-", ":", "/", "|"]

# 핵심명 뒤에 붙는 부속어 (떼어내야 블로그 표기와 맞는다)
NAME_SUFFIXES = [
    "팝업스토어", "팝업 스토어", "팝업", "스토어",
    "전시회", "전시관", "전시", "체험전", "특별전",
]

# [안전장치] 부분매칭을 허용할 최소 글자수 (이하면 전체일치만 사용)
MIN_PARTIAL_MATCH_LENGTH = 3

# [안전장치] 단독으로 쓰면 오탐 위험이 큰 흔한 일반명사 - 핵심명이 이것과 같으면 부분매칭 안 함
COMMON_WORDS = {
    "카페", "공원", "떡집", "박물관", "미술관", "과학관", "전시관", "체험관",
    "놀이터", "도서관", "센터", "광장", "시장", "마을", "거리", "스토어",
    "키즈카페", "테마파크", "관광지", "한옥마을", "휴게소", "식물원", "수목원",
}

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def classify_document(text):
    """글 텍스트를 신뢰도 신호로 분류한다.

    반환: "진짜후기" | "광고성" | "일반"

    진짜후기 신호와 광고성 신호가 함께 있으면 진짜후기를 우선한다
    ("협찬 아님", "협찬X"처럼 광고 단어를 부정하는 표현이 흔하기 때문).
    """
    if any(signal in text for signal in GENUINE_REVIEW_SIGNALS):
        return "진짜후기"
    if any(signal in text for signal in AD_SIGNALS):
        return "광고성"
    return "일반"


def extract_core_name(place_name):
    """지도 등록명에서 매칭용 핵심 상호명을 뽑는다.

    예: "우주떡집 X 토롱이 팝업 - 우주떡집과 토롱이의 여름추억" -> "우주떡집"
        "오코루 팝업스토어" -> "오코루"

    부분매칭에 쓰기 부적절하면(너무 짧거나 흔한 일반명사) None을 반환한다.
    """
    core = place_name

    # 구분자 앞부분만 취한다 (구분자는 단어 경계로 쓰인 경우만 - "X"가 상호에 붙어있을 수 있어서)
    for sep in NAME_SEPARATORS:
        for pattern in (f" {sep} ", f" {sep}", f"{sep} "):
            if pattern in core:
                core = core.split(pattern)[0]
                break

    core = core.strip()

    # 뒤에 붙은 부속어를 떼어낸다 (긴 것부터 확인해야 "팝업스토어"가 "팝업"으로 잘리지 않는다)
    changed = True
    while changed:
        changed = False
        for suffix in NAME_SUFFIXES:
            if core.endswith(suffix) and len(core) > len(suffix):
                core = core[: -len(suffix)].strip()
                changed = True

    # [안전장치] 짧거나 흔한 일반명사면 부분매칭에 쓰지 않는다
    if len(core) < MIN_PARTIAL_MATCH_LENGTH:
        return None
    if core in COMMON_WORDS:
        return None
    if core == place_name:
        return None  # 원래 이름과 같으면 전체일치로 이미 세므로 중복 카운트 방지

    return core


def _collect_candidate_places(region_name, radius_m=CANDIDATE_SEARCH_RADIUS_M):
    """지역 중심 주변에서 관광/문화/키즈 관련 공간 후보를 모은다 (이름 기준 중복 제거)."""
    result = find_location(region_name)
    if not result:
        print(f"'{region_name}' 위치를 찾을 수 없습니다.")
        return []

    candidates, _method = result
    _center_name, _addr, center_lat, center_lon = candidates[0]

    seen = set()
    places = []
    for place_type, keywords in CANDIDATE_KEYWORD_GROUPS.items():
        for keyword in keywords:
            for place in search_places_nearby(keyword, center_lat, center_lon, radius_m):
                place_name, category_name, _address, lat, lon, distance = place

                if distance is None or distance > radius_m:
                    continue
                if len(place_name) < MIN_NAME_LENGTH:
                    continue
                if place_name in seen:
                    continue

                seen.add(place_name)
                places.append(
                    {
                        "name": place_name,
                        "place_type": place_type,
                        "category": category_name,
                        "lat": lat,
                        "lon": lon,
                    }
                )

    return places


def get_popular_places(region_name, purpose_keyword, progress_callback=None):
    """지역+목적 블로그/카페 글에서 자주 언급되는 공간을 언급 횟수 순으로 집계한다.

    progress_callback(step, total_steps, label)이 주어지면 각 단계마다 호출한다
    (Streamlit 진행률 표시 등에 사용).

    반환: dict
      - places: [{"name","place_type","category","lat","lon","mention_count",
                  "genuine_count","normal_count","ad_count","trust_score"}, ...]
        (진짜후기+일반 위주 점수 순으로 정렬)
      - meta: {"query","blog_count","cafe_count","candidate_count","mentioned_count",
               "searched_on","doc_type_counts","place_type_counts"}
    """
    query = f"{region_name} {purpose_keyword}"

    def report(step, label):
        if progress_callback:
            progress_callback(step, TOTAL_STEPS, label)

    report(1, "블로그 검색 중...")
    blog_items = search_blog_all(query, max_docs=BLOG_MAX_DOCS)

    report(2, "카페 검색 중...")
    cafe_result = search_cafe(query, size=CAFE_MAX_DOCS)
    cafe_items = cafe_result["items"] if cafe_result else []

    # 글 단위로 텍스트를 만들고 신뢰도 신호로 분류한다 (공간별 언급을 유형별로 나누기 위해)
    docs = [
        {"text": f"{item['title']} {item['contents']}"}
        for item in blog_items + cafe_items
    ]
    for doc in docs:
        doc["doc_type"] = classify_document(doc["text"])

    doc_type_counts = {
        "진짜후기": sum(1 for d in docs if d["doc_type"] == "진짜후기"),
        "일반": sum(1 for d in docs if d["doc_type"] == "일반"),
        "광고성": sum(1 for d in docs if d["doc_type"] == "광고성"),
    }

    meta = {
        "query": query,
        "blog_count": len(blog_items),
        "cafe_count": len(cafe_items),
        "candidate_count": 0,
        "mentioned_count": 0,
        "searched_on": date.today().isoformat(),
        "doc_type_counts": doc_type_counts,
    }

    if not any(doc["text"].strip() for doc in docs):
        print("블로그·카페 검색 결과가 없습니다.")
        return {"places": [], "meta": meta}

    report(3, "공간 후보 수집 중...")
    places = _collect_candidate_places(region_name)
    meta["candidate_count"] = len(places)

    if not places:
        print("공간 후보를 찾을 수 없습니다.")
        return {"places": [], "meta": meta}

    report(4, "언급 횟수 집계 중...")
    for place in places:
        # 지도 등록명이 길면 블로그에선 짧게 불리므로, 핵심 상호명으로도 센다.
        # 핵심명이 있으면 그걸로 세는 게 실제 언급을 더 잘 반영한다 (전체일치는 그 부분집합).
        core_name = extract_core_name(place["name"])
        match_name = core_name or place["name"]
        place["matched_by"] = "핵심명" if core_name else "전체명"
        place["core_name"] = core_name

        counts = {"진짜후기": 0, "일반": 0, "광고성": 0}
        for doc in docs:
            hits = doc["text"].count(match_name)
            if hits:
                counts[doc["doc_type"]] += hits

        place["genuine_count"] = counts["진짜후기"]
        place["normal_count"] = counts["일반"]
        place["ad_count"] = counts["광고성"]
        place["mention_count"] = sum(counts.values())
        # 광고성 언급은 가중치를 낮춰서 진짜후기+일반 위주로 순위를 매긴다
        place["trust_score"] = (
            counts["진짜후기"] + counts["일반"] + counts["광고성"] * AD_MENTION_WEIGHT
        )

    places.sort(key=lambda p: (p["trust_score"], p["genuine_count"]), reverse=True)
    meta["mentioned_count"] = sum(1 for p in places if p["mention_count"] > 0)

    # 언급된 공간을 유형별로 세어둔다 (화면에서 "전시 N곳" 식으로 보여주거나 필터에 쓸 수 있게)
    type_counts = {}
    for place in places:
        if place["mention_count"] > 0:
            type_counts[place["place_type"]] = type_counts.get(place["place_type"], 0) + 1
    meta["place_type_counts"] = type_counts

    return {"places": places, "meta": meta}


if __name__ == "__main__":
    region_name = "경주"
    purpose_keyword = "가족 나들이"

    def show_progress(step, total, label):
        print(f"  ({step}/{total}) {label}")

    result = get_popular_places(region_name, purpose_keyword, progress_callback=show_progress)
    places, meta = result["places"], result["meta"]

    print(f"\n검색어: {meta['query']} (검색 시점: {meta['searched_on']})")
    print(f"블로그 {meta['blog_count']}건 + 카페 {meta['cafe_count']}건")
    counts = meta["doc_type_counts"]
    print(f"글 분류: 진짜후기 {counts['진짜후기']}건 / 일반 {counts['일반']}건 / 광고성 {counts['광고성']}건")
    print(f"공간 후보 {meta['candidate_count']}곳 중 언급된 곳 {meta['mentioned_count']}곳")
    print(f"유형별 언급 공간: {meta['place_type_counts']}\n")

    print(f"{'공간명':<22} {'유형':<8} {'총':>4} {'진짜후기':>6} {'일반':>5} {'광고성':>6}")
    for place in places[:15]:
        if place["mention_count"] == 0:
            break
        print(
            f"{place['name']:<22} {place['place_type']:<8} {place['mention_count']:>4} "
            f"{place['genuine_count']:>6} {place['normal_count']:>5} {place['ad_count']:>6}"
        )
