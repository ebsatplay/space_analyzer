"""네이버 검색 API로 블로그 검색이 되는지 확인하는 프로브.

실행: python services/naver_service.py
"""

import html
import os
import re
import sys

import requests
from dotenv import load_dotenv

BLOG_SEARCH_URL = "https://openapi.naver.com/v1/search/blog.json"

TAG_PATTERN = re.compile(r"<[^>]+>")

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _clean_text(text):
    """<b> 태그와 HTML 엔티티를 제거해서 깔끔한 텍스트로 만든다."""
    return html.unescape(TAG_PATTERN.sub("", text))


def search_blog(query, display=100):
    """네이버 블로그 검색을 호출해서 결과를 반환한다.

    반환: dict {"total": 전체 결과 수, "items": [{"title", "description", "link"}, ...]}
    실패 시 None을 반환한다.
    """
    load_dotenv()
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("NAVER_CLIENT_ID/NAVER_CLIENT_SECRET이 설정되어 있지 않습니다. .env 파일을 확인해주세요.")
        return None

    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {"query": query, "display": display, "sort": "sim"}

    try:
        response = requests.get(BLOG_SEARCH_URL, headers=headers, params=params, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"API 호출 중 네트워크 오류가 발생했습니다: {e}")
        return None

    if response.status_code != 200:
        print(f"HTTP 상태코드: {response.status_code}")
        print(f"응답 본문: {response.text}")
        return None

    data = response.json()
    items = [
        {
            "title": _clean_text(item["title"]),
            "description": _clean_text(item["description"]),
            "link": item["link"],
        }
        for item in data.get("items", [])
    ]

    return {"total": data.get("total", 0), "items": items}


if __name__ == "__main__":
    result = search_blog("경주 아이랑 가볼만한 곳")

    if result:
        print(f"전체 결과 수: {result['total']:,}건")
        print(f"\n상위 5개 글 제목:")
        for item in result["items"][:5]:
            print(f"  - {item['title']}")
