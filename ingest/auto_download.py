"""data.go.kr 표준데이터를 URL 호출로 자동 다운로드하는 기능. 검증용.

실행: python ingest/auto_download.py
"""

import sys

import pandas as pd
import requests

STANDARD_DOWNLOAD_URL = "https://www.data.go.kr/download/standard.json"

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def download_standard_data(public_data_pk, svc_table_nm, col_list, total_count=None, per_page=10000, page=1):
    """data.go.kr 표준데이터를 URL 호출로 받아 DataFrame으로 변환한다.

    실패(빈 응답/오류) 시 None을 반환한다.
    """
    params = {
        "publicDataPk": public_data_pk,
        "colNmList": ",".join(col_list),
        "svcTableNm": svc_table_nm,
        "perPage": per_page,
        "page": page,
    }
    if total_count is not None:
        params["totalCount"] = total_count

    try:
        response = requests.get(STANDARD_DOWNLOAD_URL, params=params, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"API 호출 중 네트워크 오류가 발생했습니다: {e}")
        return None

    if response.status_code != 200:
        print(f"HTTP 상태코드: {response.status_code}")
        print(f"응답 본문: {response.text[:500]}")
        return None

    if not response.text.strip():
        print("응답 본문이 비어 있습니다 (호출은 됐지만 데이터가 오지 않음).")
        return None

    try:
        data = response.json()
    except ValueError:
        print("응답이 JSON 형식이 아닙니다.")
        print(f"응답 본문: {response.text[:500]}")
        return None

    records = data.get("field3") or data.get("data") or data.get("resultList") or data
    if not isinstance(records, list):
        print("예상한 리스트 형태의 데이터가 아닙니다. 응답 구조를 확인해주세요:")
        print(data if isinstance(data, dict) and len(str(data)) < 1000 else str(data)[:500])
        return None

    return pd.DataFrame(records)


if __name__ == "__main__":
    # 기존 data/raw/closed_schools.csv와 동일한 컬럼 (폐교 표준데이터)
    closed_school_cols = [
        "시도교육청코드", "시도교육청명", "교육지원청코드", "교육지원청명",
        "시도코드", "시도명", "시군구코드", "시군구명",
        "폐교명", "폐교연도", "학교급구분명", "활용현황구분명",
        "건물연면적", "대지", "담당자 부서명", "담당자 전화번호",
        "소재지도로명주소", "소재지지번주소",
        "데이터기준일자", "제공기관코드", "제공기관명",
    ]

    df = download_standard_data(
        public_data_pk="15107729",
        svc_table_nm="tn_pubr_public_cls_co_svc",
        col_list=closed_school_cols,
        total_count=1194,
        per_page=10000,
        page=1,
    )

    if df is not None:
        print(f"다운로드 성공: {len(df)}행")
        print("\n컬럼 목록:")
        print(df.columns.tolist())
        print("\n상위 5행:")
        print(df.head())

        try:
            existing = pd.read_csv("data/raw/closed_schools.csv", encoding="cp949")
            print(f"\n기존 data/raw/closed_schools.csv 행 수: {len(existing)} (비교용)")
        except FileNotFoundError:
            pass
