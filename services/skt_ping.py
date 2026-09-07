"""SKT API를 딱 1번만 호출해서 실제 응답을 날것 그대로 확인하는 최소 테스트.

실행: python services/skt_ping.py
"""

import os
import sys

import requests
from dotenv import load_dotenv

API_URL = "https://apis.openapi.sk.com/puzzle/place/meta/pois"

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    load_dotenv()
    app_key = os.getenv("SKT_APP_KEY") or ""

    print(f"키 길이: {len(app_key)}자")

    headers = {
        "appkey": app_key,
        "Accept": "application/json",
    }
    params = {
        "offset": 0,
        "limit": 5,
    }

    try:
        response = requests.get(API_URL, headers=headers, params=params, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"API 호출 중 네트워크 오류가 발생했습니다: {e}")
        return

    print(f"HTTP 상태코드: {response.status_code}")
    print("응답 본문:")
    print(response.text)


if __name__ == "__main__":
    main()
