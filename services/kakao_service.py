"""카카오 로컬 API로 주소/장소를 좌표(위도/경도)로 변환하는 기능. 첫 검증용.

실행: python services/kakao_service.py
"""

import html
import json
import os
import re
import sys
from datetime import date

import requests
from dotenv import load_dotenv

ADDRESS_API_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KEYWORD_API_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
BLOG_SEARCH_URL = "https://dapi.kakao.com/v2/search/blog"
CAFE_SEARCH_URL = "https://dapi.kakao.com/v2/search/cafe"

TAG_PATTERN = re.compile(r"<[^>]+>")

# 카카오 API 일일 호출 한도 (앱 설정에 따라 다르므로, 실제 한도에 맞춰 조정해서 쓴다)
DAILY_CALL_LIMIT = 100000
USAGE_PATH = "data/reference/kakao_usage.json"

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _load_usage(path=USAGE_PATH):
    """오늘자 호출 사용량을 읽는다. 날짜가 바뀌었으면 0부터 시작한다."""
    today = date.today().isoformat()
    try:
        with open(path, encoding="utf-8") as f:
            usage = json.load(f)
        if usage.get("date") == today:
            return usage
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {"date": today, "count": 0}


def _record_call(path=USAGE_PATH):
    """호출 1건을 기록한다 (날짜별 누적)."""
    usage = _load_usage(path)
    usage["count"] += 1
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(usage, f, ensure_ascii=False)
    except OSError:
        pass  # 사용량 기록 실패가 검색 자체를 막지 않도록 조용히 넘어간다
    return usage


def get_usage(path=USAGE_PATH):
    """오늘 호출 사용량 현황을 반환한다.

    반환: {"date", "count", "limit", "ratio"} (ratio는 한도 대비 사용 비율 0~1)
    """
    usage = _load_usage(path)
    return {
        "date": usage["date"],
        "count": usage["count"],
        "limit": DAILY_CALL_LIMIT,
        "ratio": usage["count"] / DAILY_CALL_LIMIT if DAILY_CALL_LIMIT else 0,
    }


def _request(url, params):
    """카카오 로컬 API를 한 번 호출해서 응답 JSON 전체(documents, meta)를 반환한다.

    실패 시 None을 반환한다.
    """
    load_dotenv()
    api_key = os.getenv("KAKAO_REST_KEY")

    if not api_key:
        print("KAKAO_REST_KEY가 설정되어 있지 않습니다. .env 파일을 확인해주세요.")
        return None

    headers = {"Authorization": f"KakaoAK {api_key}"}
    _record_call()

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"API 호출 중 네트워크 오류가 발생했습니다: {e}")
        return None

    if response.status_code != 200:
        print(f"HTTP 상태코드: {response.status_code}")
        print(f"응답 본문: {response.text}")
        return None

    return response.json()


def _search(url, query):
    """카카오 로컬 API를 호출해서 documents 리스트를 반환한다. 실패 시 None을 반환한다."""
    data = _request(url, {"query": query})
    if data is None:
        return None
    return data.get("documents", [])


def address_to_coord(address):
    """주소를 (위도, 경도, 정제된 주소)로 변환한다. 실패 시 None을 반환한다."""
    documents = _search(ADDRESS_API_URL, address)
    if not documents:
        print("주소를 찾을 수 없습니다")
        return None

    doc = documents[0]
    return float(doc["y"]), float(doc["x"]), doc["address_name"]


def search_places(keyword):
    """키워드(장소명)로 검색해서 최대 10개의 결과 리스트를 반환한다.

    각 항목은 (장소명, 주소, 위도, 경도) 튜플이다. 실패 시 빈 리스트를 반환한다.
    """
    documents = _search(KEYWORD_API_URL, keyword)
    if not documents:
        print("검색 결과를 찾을 수 없습니다")
        return []

    return [
        (doc["place_name"], doc["address_name"], float(doc["y"]), float(doc["x"]))
        for doc in documents[:10]
    ]


MAX_NEARBY_PAGES = 3  # 카카오 페이지당 최대 15개 x 3페이지 = 최대 45개


def search_places_nearby(keyword, center_lat, center_lon, radius_m):
    """기준 좌표 주변 radius_m(m) 이내에서 키워드로 장소를 검색한다 (최대 45개, 페이지네이션).

    반환: (장소명, 카테고리, 주소, 위도, 경도, 거리(m)) 튜플의 리스트. 실패 시 빈 리스트.
    """
    all_documents = []

    for page in range(1, MAX_NEARBY_PAGES + 1):
        params = {
            "query": keyword,
            "x": center_lon,
            "y": center_lat,
            "radius": min(radius_m, 20000),
            "page": page,
        }
        data = _request(KEYWORD_API_URL, params)
        if data is None:
            break

        all_documents.extend(data.get("documents", []))

        if data.get("meta", {}).get("is_end", True):
            break

    if not all_documents:
        print("검색 결과를 찾을 수 없습니다")
        return []

    return [
        (
            doc["place_name"],
            doc["category_name"],
            doc["address_name"],
            float(doc["y"]),
            float(doc["x"]),
            float(doc["distance"]) if doc.get("distance") else None,
        )
        for doc in all_documents
    ]


def _clean_text(text):
    """<b> 태그와 HTML 엔티티를 제거해서 깔끔한 텍스트로 만든다."""
    return html.unescape(TAG_PATTERN.sub("", text))


def _search_documents(url, query, size, page, name_field):
    """블로그/카페 검색 공통 로직. 실패 시 None을 반환한다.

    반환: {"total_count": N, "is_end": bool, "items": [{"title","contents","url",name_field}, ...]}
    """
    params = {"query": query, "size": min(size, 50), "sort": "accuracy", "page": page}
    data = _request(url, params)
    if data is None:
        return None

    items = [
        {
            "title": _clean_text(doc["title"]),
            "contents": _clean_text(doc["contents"]),
            "url": doc["url"],
            name_field: doc.get(name_field, ""),
        }
        for doc in data.get("documents", [])
    ]
    meta = data.get("meta", {})

    return {
        "total_count": meta.get("total_count", 0),
        "is_end": meta.get("is_end", True),
        "items": items,
    }


def search_blog(query, size=50, page=1):
    """카카오 블로그 검색. 실패 시 None을 반환한다.

    반환: {"total_count", "is_end", "items": [{"title","contents","url","blogname"}, ...]}
    """
    return _search_documents(BLOG_SEARCH_URL, query, size, page, "blogname")


def search_cafe(query, size=50, page=1):
    """카카오 카페 검색. 실패 시 None을 반환한다.

    반환: {"total_count", "is_end", "items": [{"title","contents","url","cafename"}, ...]}
    """
    return _search_documents(CAFE_SEARCH_URL, query, size, page, "cafename")


def search_blog_all(query, max_docs=100):
    """블로그 검색을 여러 페이지 모아서 최대 max_docs개까지 반환한다.

    반환: [{"title","contents","url","blogname"}, ...] (실패/결과없음 시 빈 리스트)
    """
    all_items = []
    page = 1

    while len(all_items) < max_docs:
        remaining = max_docs - len(all_items)
        result = search_blog(query, size=min(50, remaining), page=page)
        if result is None:
            break

        all_items.extend(result["items"])

        if result["is_end"] or not result["items"]:
            break
        page += 1

    return all_items[:max_docs]


def find_location(text):
    """주소검색을 먼저 시도하고 실패하면 키워드검색을 시도한다.

    반환: (candidates, 방식) 또는 둘 다 실패 시 None.
    candidates는 (장소명, 주소, 위도, 경도) 튜플의 리스트.
    방식은 "주소검색" 또는 "키워드검색".
    """
    result = address_to_coord(text)
    if result:
        latitude, longitude, refined_address = result
        return [(refined_address, refined_address, latitude, longitude)], "주소검색"

    places = search_places(text)
    if places:
        return places, "키워드검색"

    return None


if __name__ == "__main__":
    test_inputs = [
        "경기도 파주시 와석순환로 500",
        "포항 우현더힐",
        "포항시청",
    ]

    for text in test_inputs:
        print(f"--- {text} ---")
        result = find_location(text)
        if result:
            candidates, method = result
            print(f"[{method}] {len(candidates)}개 결과")
            for name, addr, lat, lon in candidates:
                print(f"  - {name} ({addr}) 위도: {lat}, 경도: {lon}")
        print()

    print("--- 포항시청 반경 5000m 이내 '키즈카페' 검색 ---")
    nearby = search_places_nearby("키즈카페", 36.019, 129.343, 5000)
    print(f"{len(nearby)}개 결과")
    for place_name, category_name, address_name, lat, lon, distance in nearby[:10]:
        print(f"  - {place_name} ({address_name}) 거리: {distance}m")

    print("\n--- '경주 아이랑 가볼만한 곳' 블로그 검색 ---")
    blog_result = search_blog("경주 아이랑 가볼만한 곳")
    if blog_result:
        print(f"total_count: {blog_result['total_count']:,}건")
        print("\n상위 5개 글 제목:")
        for item in blog_result["items"][:5]:
            print(f"  - {item['title']}")
