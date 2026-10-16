"""한국관광공사 데이터랩 '지역별(시군구) 일자별 방문자수' API 조회.

데이터는 시군구별로 현지인(a)/외지인(b)/외국인(c)로 나뉘어 들어온다.
공간사업 수요를 볼 때 "외지인이 찾아오는 곳인지, 주민이 쓰는 곳인지"를 가르는 데 쓴다.

주의할 점 두 가지 (프로브 실측):
1. 이 엔드포인트에는 시군구 필터 파라미터가 없다. signguCode/signguCd/areaCd를
   넘기면 모두 INVALID_REQUEST_PARAMETER_ERROR로 거부된다. 그래서 전국(하루 807행)을
   받아서 코드로 직접 걸러야 한다. 기간을 길게 잡으면 받는 양이 날짜수에 비례해 늘어난다.
2. 데이터가 약 1개월 지연된다 (2026-10-16 기준 최신 2026-09-16). 최근 날짜를 넣으면
   오류 대신 빈 결과(totalCount=0)가 온다.

응답의 signguCode는 행안부 5자리 시군구코드로, data/reference/sigungu_names.csv의
sigungu_cd와 같은 체계다 (고령군=47830 일치 확인).

실행(테스트): python -m services.tourism_service
"""

import os
import sys
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

from services.config import get_secret

VISITOR_API_URL = "https://apis.data.go.kr/B551011/DataLabService/locgoRegnVisitrDDList"

MOBILE_OS = "ETC"
MOBILE_APP = "SpaceAnalyzer"

# 하루치가 전국 807행(270개 시군구 x 3구분)이라 넉넉히 받는다
ROWS_PER_PAGE = 1000
MAX_PAGES = 50

# 방문자 구분: 응답은 "현지인(a)" 처럼 코드가 붙어 오므로 코드로 매핑한다
TOU_DIV_LABELS = {"1": "현지인", "2": "외지인", "3": "외국인"}

load_dotenv()

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class TourismApiError(Exception):
    """공공데이터포털이 오류 코드를 돌려준 경우."""


def _api_key():
    key = get_secret("DATA_GO_KR_KEY")
    if not key:
        print("DATA_GO_KR_KEY가 설정되어 있지 않습니다. 로컬은 .env, 배포는 Streamlit secrets를 확인해주세요.")
    return key


def _request_page(service_key, start_ymd, end_ymd, page_no, pre_encoded):
    """한 페이지를 요청해서 (항목 리스트, totalCount)를 돌려준다.

    pre_encoded=False면 디코딩 키를 params로 넘겨 requests가 URL 인코딩하게 한다.
    True면 이미 인코딩된 키로 보기 때문에 url에 직접 붙여 재인코딩을 막는다
    (포털이 내려주는 인코딩 키에는 %2B 같은 문자가 들어 있어서, 그대로 params로
    넘기면 이중 인코딩되어 SERVICE_KEY_IS_NOT_REGISTERED_ERROR가 난다).
    """
    params = {
        "MobileOS": MOBILE_OS,
        "MobileApp": MOBILE_APP,
        "_type": "json",
        "numOfRows": ROWS_PER_PAGE,
        "pageNo": page_no,
        "startYmd": start_ymd,
        "endYmd": end_ymd,
    }

    if pre_encoded:
        url = f"{VISITOR_API_URL}?serviceKey={service_key}"
    else:
        url = VISITOR_API_URL
        params["serviceKey"] = service_key

    try:
        response = requests.get(url, params=params, timeout=40)
    except requests.RequestException as e:
        raise TourismApiError(f"요청 실패: {e}") from e

    # 키가 틀리면 포털이 403을 준다. HTTPError로 새어나가면 호출부가 두 종류의 예외를
    # 잡아야 하고, 아래 디코딩/인코딩 키 재시도도 걸리지 않아서 여기서 변환한다.
    if not response.ok:
        raise TourismApiError(f"HTTP {response.status_code}: {response.text[:200]}")

    try:
        payload = response.json()
    except ValueError:
        # 키가 아예 등록되지 않은 경우 등은 XML 에러 문서가 오기도 한다
        raise TourismApiError(f"JSON이 아닌 응답: {response.text[:200]}")

    # 포털 공통 에러는 response 래퍼 없이 resultCode/resultMsg만 온다
    if "response" not in payload:
        raise TourismApiError(
            f"{payload.get('resultCode', '?')} {payload.get('resultMsg', payload)}"
        )

    header = payload["response"].get("header", {})
    if header.get("resultCode") not in ("0000", "00"):
        raise TourismApiError(f"{header.get('resultCode')} {header.get('resultMsg')}")

    body = payload["response"].get("body", {})
    total_count = int(body.get("totalCount") or 0)

    items = body.get("items") or {}
    if not items:
        return [], total_count

    item = items.get("item") or []
    if isinstance(item, dict):  # 결과가 1건이면 리스트가 아니라 dict로 온다
        item = [item]
    return item, total_count


def fetch_nationwide_visitors(start_ymd, end_ymd, service_key=None, progress_callback=None):
    """해당 기간 전국 방문자수 원본 항목을 모두 받아온다 (시군구 필터가 없는 API라서).

    하루치가 807행이므로 한 달이면 2만 4천여 행이 되고, ROWS_PER_PAGE 단위로 페이징한다.
    키는 디코딩 키를 params로 넘겨 requests가 인코딩하게 하고, 그게 거부되면
    인코딩 키로 보고 한 번 더 시도한다.

    반환: (항목 리스트, totalCount)
    실패 시 TourismApiError를 올린다.
    """
    service_key = service_key or _api_key()
    if not service_key:
        raise TourismApiError("DATA_GO_KR_KEY가 설정되어 있지 않습니다")

    last_error = None

    # 디코딩 키 -> 인코딩 키 순으로 시도한다 (어느 형태를 받았는지 알 수 없으므로)
    for pre_encoded in (False, True):
        collected = []
        total_count = 0
        try:
            for page_no in range(1, MAX_PAGES + 1):
                items, total_count = _request_page(
                    service_key, start_ymd, end_ymd, page_no, pre_encoded
                )
                collected.extend(items)
                if progress_callback:
                    progress_callback(len(collected), total_count)
                if not items or len(collected) >= total_count:
                    break
            return collected, total_count
        except TourismApiError as e:
            last_error = e
            continue

    raise last_error


def find_latest_available_ymd(service_key=None, max_lookback_days=90):
    """데이터가 들어와 있는 가장 최근 날짜를 찾는다.

    이 API는 약 1개월 지연되고, 지연 구간을 조회하면 오류 대신 totalCount=0이 온다.
    그래서 오늘부터 하루씩 거슬러 올라가며 데이터가 있는 첫 날짜를 찾는다.

    반환: "YYYYMMDD" 또는 찾지 못하면 None
    """
    service_key = service_key or _api_key()
    if not service_key:
        return None

    for days_back in range(1, max_lookback_days + 1):
        ymd = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d")
        try:
            _, total_count = _request_page(service_key, ymd, ymd, 1, pre_encoded=False)
        except TourismApiError:
            continue
        if total_count:
            return ymd
    return None


def get_visitor_count(signgu_code, start_ymd, end_ymd, service_key=None):
    """시군구 방문자수를 날짜·구분별로 조회한다.

    signgu_code: 행안부 5자리 시군구코드 (sigungu_names.csv의 sigungu_cd와 같은 체계)
    start_ymd, end_ymd: "YYYYMMDD"

    이 API에는 시군구 필터가 없어서 전국을 받아 signgu_code로 직접 걸러낸다.
    키는 디코딩 키를 params로 넘겨 requests가 인코딩하게 하고, 그게 거부되면
    인코딩 키로 보고 한 번 더 시도한다.

    반환: dict
      - items: [{"signgu_code","area_nm","tou_div_nm","visitor_count","base_ymd"}, ...]
        날짜순 정렬
      - totals: {"현지인": N, "외지인": N, "외국인": N} 기간 합계
      - meta: 조회 조건과 수집 건수
    실패 시 TourismApiError를 올린다.
    """
    service_key = service_key or _api_key()
    if not service_key:
        return None

    collected, total_count = fetch_nationwide_visitors(start_ymd, end_ymd, service_key)

    rows = []
    for item in collected:
        if str(item.get("signguCode", "")).strip() != str(signgu_code):
            continue
        div_code = str(item.get("touDivCd", "")).strip()
        rows.append({
            "signgu_code": item.get("signguCode", ""),
            "area_nm": item.get("signguNm", ""),
            # 응답 touDivNm은 "현지인(a)" 형태라 코드 기준 라벨을 쓰고, 원문도 남긴다
            "tou_div_nm": TOU_DIV_LABELS.get(div_code, item.get("touDivNm", "")),
            "tou_div_nm_raw": item.get("touDivNm", ""),
            "visitor_count": float(item.get("touNum") or 0),
            "base_ymd": item.get("baseYmd", ""),
        })

    rows.sort(key=lambda row: (row["base_ymd"], row["tou_div_nm"]))

    totals = {label: 0.0 for label in TOU_DIV_LABELS.values()}
    for row in rows:
        if row["tou_div_nm"] in totals:
            totals[row["tou_div_nm"]] += row["visitor_count"]

    return {
        "items": rows,
        "totals": totals,
        "meta": {
            "signgu_code": str(signgu_code),
            "area_nm": rows[0]["area_nm"] if rows else "",
            "start_ymd": start_ymd,
            "end_ymd": end_ymd,
            "nationwide_rows": len(collected),
            "matched_rows": len(rows),
            "total_count": total_count,
        },
    }


def main():
    signgu_code = "47830"  # 경상북도 고령군
    # 데이터가 약 1개월 지연되므로 최신 가용 구간으로 조회한다
    start_ymd, end_ymd = "20260910", "20260916"

    print(f"고령군({signgu_code}) 방문자수 조회: {start_ymd} ~ {end_ymd}")
    try:
        result = get_visitor_count(signgu_code, start_ymd, end_ymd)
    except TourismApiError as e:
        print(f"API 오류: {e}")
        return
    if result is None:
        return

    meta = result["meta"]
    print(f"\n전국 {meta['nationwide_rows']:,}행 수집 -> {meta['area_nm']} {meta['matched_rows']}행")

    print("\n날짜별:")
    for row in result["items"]:
        print(f"  {row['base_ymd']} {row['tou_div_nm']:<4} {row['visitor_count']:>12,.0f}명")

    totals = result["totals"]
    period_total = sum(totals.values())
    print("\n기간 합계:")
    for label, value in totals.items():
        share = value / period_total * 100 if period_total else 0
        print(f"  {label:<4} {value:>12,.0f}명 ({share:4.1f}%)")
    print(f"  {'합계':<4} {period_total:>12,.0f}명")


if __name__ == "__main__":
    main()
