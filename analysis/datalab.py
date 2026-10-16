"""한국관광 데이터랩 지표 조회 - 지역 체류/숙박과 전국 관광 맥락.

ingest/build_datalab.py가 만들어 둔 parquet들을 읽는다.

조회할 때 주의할 점: 데이터랩 시군구 데이터는 분구를 합친 "시" 단위다
(포항시 남구/북구가 아니라 포항시). 그래서 구 단위 코드(47113 포항시 북구)로 찾으면
없고, 모 시 코드(47110 포항시)로 폴백해야 한다.

실행(테스트): python -m analysis.datalab
"""

import functools
import sys

import pandas as pd

SIGUNGU_PATH = "data/processed/datalab_sigungu.parquet"
SIDO_PATH = "data/processed/datalab_sido.parquet"
MONTHLY_PATH = "data/processed/datalab_monthly.parquet"
SEARCH_RANK_PATH = "data/processed/datalab_search_rank.parquet"
SIGUNGU_NAMES_PATH = "data/reference/sigungu_names.csv"

# 출처·한계를 화면에 그대로 띄워 오해를 막는다
DATA_SOURCE = "한국관광 데이터랩 (한국관광공사)"
DATA_CAVEAT = (
    "데이터랩 지표는 이동통신·카드 기반 추정치이며, 증감률은 전년동기 대비입니다. "
    "시군구 지표는 분구를 합친 시 단위로 제공되어 구별로는 나뉘지 않습니다."
)

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _read(path):
    try:
        return pd.read_parquet(path)
    except (FileNotFoundError, OSError):
        return None


@functools.lru_cache(maxsize=1)
def _load_sigungu(path=SIGUNGU_PATH):
    return _read(path)


@functools.lru_cache(maxsize=1)
def _load_monthly(path=MONTHLY_PATH):
    return _read(path)


@functools.lru_cache(maxsize=1)
def _load_search_rank(path=SEARCH_RANK_PATH):
    return _read(path)


@functools.lru_cache(maxsize=1)
def _load_sido(path=SIDO_PATH):
    return _read(path)


@functools.lru_cache(maxsize=1)
def _parent_city_codes(path=SIGUNGU_NAMES_PATH):
    """구 단위 코드 -> 모 시 코드 매핑 ('경상북도 포항시 북구' 47113 -> 47110).

    데이터랩이 분구를 합쳐 제공하기 때문에, 구 단위로 조회할 때 쓸 폴백 표가 필요하다.
    """
    try:
        names = pd.read_csv(path, dtype=str)
    except (FileNotFoundError, OSError):
        return {}

    by_name = dict(zip(names["sigungu_nm"], names["sigungu_cd"]))
    mapping = {}
    for name, code in by_name.items():
        tokens = name.split()
        if len(tokens) < 3:
            continue
        parent_name = " ".join(tokens[:-1])  # '경상북도 포항시 북구' -> '경상북도 포항시'
        parent_code = by_name.get(parent_name)
        if parent_code:
            mapping[code] = parent_code
    return mapping


@functools.lru_cache(maxsize=1)
def get_nationwide_stay_quartiles(path=SIGUNGU_PATH):
    """전국 체류시간/숙박일수의 사분위 (지역 값을 비교할 기준선)."""
    sigungu = _load_sigungu(path)
    if sigungu is None or sigungu.empty:
        return None
    return {
        "stay_minutes_median": float(sigungu["avg_stay_minutes"].median()),
        "stay_minutes_q3": float(sigungu["avg_stay_minutes"].quantile(0.75)),
        "stay_nights_median": float(sigungu["avg_stay_nights"].median()),
        "stay_nights_q3": float(sigungu["avg_stay_nights"].quantile(0.75)),
        "sigungu_count": len(sigungu),
    }


def get_sigungu_datalab(sigungu_cd, path=SIGUNGU_PATH):
    """시군구 체류/숙박/방문자 지표를 돌려준다 (구 단위면 모 시로 폴백).

    반환: dict 또는 데이터가 없으면 None.
      fallback_from: 구 코드로 찾아서 모 시 값을 쓴 경우 원래 코드가 담긴다
    """
    sigungu = _load_sigungu(path)
    if sigungu is None:
        return None

    code = str(sigungu_cd)
    matched = sigungu[sigungu["sigungu_cd"] == code]

    fallback_from = None
    if matched.empty:
        parent_code = _parent_city_codes().get(code)
        if parent_code:
            matched = sigungu[sigungu["sigungu_cd"] == parent_code]
            fallback_from = code
    if matched.empty:
        return None

    row = matched.iloc[0]
    quartiles = get_nationwide_stay_quartiles(path)

    stay_minutes = float(row["avg_stay_minutes"])
    result = {
        "sigungu_cd": row["sigungu_cd"],
        "sigungu_nm": row["sigungu_nm"],
        "avg_stay_minutes": stay_minutes,
        "avg_stay_hours": round(stay_minutes / 60, 1),
        "avg_stay_nights": float(row["avg_stay_nights"]),
        "visitor_count": int(row["visitor_count"]),
        "visitor_ratio": float(row["visitor_ratio"]),
        "sido_visitor_count": int(row["sido_visitor_count"]),
        "sido_visitor_ratio": float(row["sido_visitor_ratio"]),
        "period_merged": bool(row["period_merged"]),
        "fallback_from": fallback_from,
        "quartiles": quartiles,
    }

    if quartiles:
        result["stay_vs_median"] = round(stay_minutes - quartiles["stay_minutes_median"], 0)
        result["nights_vs_median"] = round(
            result["avg_stay_nights"] - quartiles["stay_nights_median"], 2
        )
    return result


def get_monthly_interest(path=MONTHLY_PATH):
    """월별 국내관광 관심도·방문자 추세를 돌려준다 (계절성 차트용).

    반환: DataFrame (base_ym, interest_index, visitor_count, ...) 또는 None
    """
    monthly = _load_monthly(path)
    if monthly is None or monthly.empty:
        return None
    return monthly.copy()


def get_search_rank_top(limit=10, path=SEARCH_RANK_PATH):
    """전국 관광지 검색순위 상위 N곳."""
    search_rank = _load_search_rank(path)
    if search_rank is None or search_rank.empty:
        return None
    return search_rank.nsmallest(limit, "rank").copy()


def get_search_rank_for_sigungu(sigungu_cd, path=SEARCH_RANK_PATH):
    """해당 시군구(또는 그 안의 구)가 검색순위 TOP에 있으면 그 항목들을 돌려준다.

    데이터랩 TOP 100은 구 단위 주소까지 들어 있어서, 모 시 코드로 조회하면 그 시
    안의 모든 구를 포함해서 찾는다 (포항시 -> 포항시 남구·북구 항목까지).

    반환: DataFrame (없으면 빈 DataFrame)
    """
    search_rank = _load_search_rank(path)
    if search_rank is None or search_rank.empty:
        return pd.DataFrame()

    code = str(sigungu_cd)
    codes = {code}
    # 구 코드로 들어오면 모 시도 함께 본다
    parent = _parent_city_codes().get(code)
    if parent:
        codes.add(parent)
    # 모 시 코드로 들어오면 그 시의 구들도 함께 본다
    codes.update(
        child for child, parent_code in _parent_city_codes().items() if parent_code == code
    )

    return search_rank[search_rank["sigungu_cd"].isin(codes)].copy()


def get_sido_datalab(sido_nm, path=SIDO_PATH):
    """시도 단위 지표(검색건수/방문자 증가율/관광지출액)를 돌려준다."""
    sido = _load_sido(path)
    if sido is None or sido.empty:
        return None
    matched = sido[sido["sido_nm"] == sido_nm]
    if matched.empty:
        return None
    return matched.iloc[0].to_dict()


def main():
    quartiles = get_nationwide_stay_quartiles()
    if quartiles is None:
        print(f"{SIGUNGU_PATH} 가 없습니다. python -m ingest.build_datalab 를 먼저 실행하세요.")
        return

    print(f"전국 {quartiles['sigungu_count']}개 시군구 기준선")
    print(f"  체류시간 중위 {quartiles['stay_minutes_median']:.0f}분 "
          f"({quartiles['stay_minutes_median'] / 60:.1f}시간) / 3사분위 {quartiles['stay_minutes_q3']:.0f}분")
    print(f"  숙박일수 중위 {quartiles['stay_nights_median']:.2f}일 / 3사분위 {quartiles['stay_nights_q3']:.2f}일")

    for code, label in (("47830", "고령군"), ("47113", "포항시 북구(구 단위 -> 폴백)"), ("11110", "서울 종로구")):
        profile = get_sigungu_datalab(code)
        print(f"\n[{label}] 코드 {code}")
        if profile is None:
            print("  데이터 없음")
            continue
        print(f"  -> {profile['sigungu_nm']} ({profile['sigungu_cd']})"
              + (f"  * {profile['fallback_from']} -> 모 시로 폴백" if profile["fallback_from"] else ""))
        print(f"     체류시간 {profile['avg_stay_minutes']:.0f}분({profile['avg_stay_hours']}시간) "
              f"| 전국 중위 대비 {profile['stay_vs_median']:+.0f}분")
        print(f"     숙박일수 {profile['avg_stay_nights']:.2f}일 | 중위 대비 {profile['nights_vs_median']:+.2f}일")
        print(f"     방문자 {profile['visitor_count']:,}명 (시도 내 {profile['visitor_ratio']:.1f}%)")
        hits = get_search_rank_for_sigungu(profile["sigungu_cd"])
        if len(hits):
            for hit in hits.itertuples(index=False):
                print(f"     검색순위 TOP100: {hit.rank}위 {hit.place_name} ({hit.category_mid})")
        else:
            print("     검색순위 TOP100 해당 없음")

    monthly = get_monthly_interest()
    print(f"\n월별 시계열 {len(monthly)}개월 ({monthly['base_ym'].min()} ~ {monthly['base_ym'].max()})")
    recent = monthly.dropna(subset=["interest_index"]).tail(6)
    print("  최근 관심도:", ", ".join(f"{r.base_ym} {r.interest_index:.0f}" for r in recent.itertuples()))

    top = get_search_rank_top(5)
    print("\n검색순위 TOP 5:")
    for row in top.itertuples(index=False):
        print(f"  {row.rank}위 {row.place_name} ({row.sido_nm} · {row.category_mid}/{row.category_sub})")


if __name__ == "__main__":
    main()
