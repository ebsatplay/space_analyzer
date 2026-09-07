"""KOSIS 주민등록인구 API를 호출해서 실제 응답 구조를 확인하는 프로브.

가공하지 않고 "실제로 무엇이 오는지"만 확인한다.

실행: python services/kosis_service.py
"""

import os
import sys
from urllib.parse import quote

import pandas as pd
import requests
from dotenv import load_dotenv

BASE_URL = (
    "https://kosis.kr/openapi/Param/statisticsParameterData.do"
    "?method=getList"
    "&apiKey={api_key}"
    "&itmId=T2+T3+T4+"
    "&objL1=00+11+12+26+27+28+29+30+31+36+41+51+43+44+52+46+47+48+50+"
    "&objL2=ALL&objL3=&objL4=&objL5=&objL6=&objL7=&objL8="
    "&format=json&jsonVD=Y&prdSe=M&newEstPrdCnt=3&orgId=101&tblId=DT_1B04005N"
)

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def probe_population():
    """KOSIS 인구 API를 호출해서 응답을 DataFrame으로 반환한다. 실패 시 None을 반환한다."""
    load_dotenv()
    api_key = os.getenv("KOSIS_API_KEY")

    if not api_key:
        print("KOSIS_API_KEY가 설정되어 있지 않습니다. .env 파일을 확인해주세요.")
        return None

    url = BASE_URL.format(api_key=quote(api_key, safe=""))

    try:
        response = requests.get(url, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"API 호출 중 네트워크 오류가 발생했습니다: {e}")
        return None

    if response.status_code != 200:
        print(f"HTTP 상태코드: {response.status_code}")
        print(f"응답 본문: {response.text}")
        return None

    try:
        data = response.json()
    except ValueError:
        print("응답이 JSON 형식이 아닙니다.")
        print(f"응답 본문: {response.text[:500]}")
        return None

    if isinstance(data, dict):
        print("API가 오류 응답을 반환했습니다:")
        print(data)
        return None

    return pd.DataFrame(data)


if __name__ == "__main__":
    df = probe_population()
    if df is not None:
        print(f"(1) 전체 행 개수: {len(df)}행")

        print("\n(2) 컬럼 목록:")
        print(df.columns.tolist())

        print("\n(3) 상위 10행:")
        print(df.head(10))
