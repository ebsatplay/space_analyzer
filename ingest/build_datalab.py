"""한국관광 데이터랩에서 내려받은 전국 CSV 9개를 정제해서 저장하는 1회성 스크립트.

데이터랩은 지표마다 파일이 따로 떨어지고 모양도 달라서, 성격별로 묶어 저장한다.

  시군구 단위 (어느 지역을 넣어도 자동으로 나오는 것)
    datalab_sigungu.parquet   <- visitor + stay

  전국 맥락 (지역과 무관하게 참고하는 것)
    datalab_sido.parquet         <- search_count + top_region + spending (시도 단위)
    datalab_monthly.parquet      <- interest + trend (월별 시계열)
    datalab_search_rank.parquet  <- 전국 관광지 검색순위 TOP 100
    datalab_age.parquet          <- 연령대별 방문집중지역

정제할 때 걸리는 것 세 가지:
1. 데이터랩 시군구 데이터는 분구를 합친 "시" 단위다 (포항시 남구/북구가 아니라 포항시).
   우리 sigungu_names.csv에는 모 시 행(47110 경상북도 포항시)이 있어서 그쪽에 붙인다.
   대신 구 단위 코드로 조회할 때는 모 시로 폴백해야 한다 (analysis/datalab.py 참고).
2. visitor/stay의 시도명이 행정구역 개편 이전 표기다 (광주광역시/전라남도). 우리 데이터는
   전남광주통합특별시로 통합되어 있어 리맵한다.
3. 세종특별자치시는 시군구명이 비어 있거나 시도명과 같게 들어온다.

실행: python -m ingest.build_datalab
(analysis.visitors를 import하므로 python ingest/build_datalab.py로 직접 실행하면 안 됨)
"""

import os
import sys

import pandas as pd

RAW_PATH_TEMPLATE = "data/raw/datalab_nationwide_{name}.csv"
SIGUNGU_NAMES_PATH = "data/reference/sigungu_names.csv"

SIGUNGU_PATH = "data/processed/datalab_sigungu.parquet"
SIDO_PATH = "data/processed/datalab_sido.parquet"
MONTHLY_PATH = "data/processed/datalab_monthly.parquet"
SEARCH_RANK_PATH = "data/processed/datalab_search_rank.parquet"
AGE_PATH = "data/processed/datalab_age.parquet"

# 데이터랩은 광주/전남 통합을 "통합 이후" 와 "통합 이전"을 각각 다른 시도 라벨로 나눠
# 담고 있다. 셋을 다 더해야 전국 비율 합이 100.0이 되므로(실측 확인) 겹치지 않는
# 기간 분할이다. 그래서 이름만 바꿔 붙이면 같은 시군구가 둘로 들어와 이중계상된다.
# 통합 이름으로 모아 기간을 합치는 방식으로 재구성한다.
MERGED_SIDO = "전남광주통합특별시"
PRE_MERGER_SIDOS = ("광주광역시", "전라남도")

# spending의 '유형별 대분류' -> 저장 컬럼명
SPENDING_CATEGORIES = {
    "관광지출액": "spending_total",
    "쇼핑업": "spending_shopping",
    "식음료업": "spending_food",
    "운송업": "spending_transport",
    "여가서비스업": "spending_leisure",
    "의료웰니스업": "spending_wellness",
    "숙박업": "spending_lodging",
    "여행업": "spending_travel",
}

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _read_raw(name):
    """데이터랩 원본 CSV를 읽는다 (전부 utf-8-sig)."""
    path = RAW_PATH_TEMPLATE.format(name=name)
    try:
        return pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    except FileNotFoundError:
        print(f"파일을 찾을 수 없습니다: {path}")
        return None


def _to_num(series):
    """'4.6323778443E10' 같은 지수 표기까지 숫자로 바꾼다."""
    return pd.to_numeric(series.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def _full_region_name(sido_series, sigungu_series):
    """'시도 시군구' 전체 이름을 만든다 (통합 시도명으로 모으고 세종 예외 처리).

    광주/전남은 통합 이전 라벨을 통합 이름으로 바꿔 같은 시군구끼리 모이게 한다.
    모인 행들은 기간이 겹치지 않으므로 뒤에서 합산한다.
    """
    sido = sido_series.fillna("").str.strip().replace(
        {name: MERGED_SIDO for name in PRE_MERGER_SIDOS}
    )
    sigungu = sigungu_series.fillna("").str.strip()
    return [
        sido_name if (not sigungu_name or sigungu_name == sido_name) else f"{sido_name} {sigungu_name}"
        for sido_name, sigungu_name in zip(sido, sigungu)
    ]


def _merged_sido_totals(visitor_raw):
    """통합 시도(광주+전남)의 시도 방문자수/비율을 기간 합으로 재구성한다.

    데이터랩은 같은 지역을 '전남광주통합특별시'(통합 이후)와 '광주광역시'/'전라남도'
    (통합 이전) 라벨로 쪼개 담는다. 시군구별 비율의 분모가 되는 시도 합계도 세 라벨을
    모두 더해야 실제 기간 전체 값이 된다.

    반환: {"count": 시도 방문자수 합, "ratio": 시도 방문자 비율 합}
    """
    labels = (MERGED_SIDO,) + PRE_MERGER_SIDOS
    sido = visitor_raw.assign(
        sido_nm=visitor_raw["광역지자체명"].str.strip(),
        count=_to_num(visitor_raw["광역지자체 방문자 수"]),
        ratio=_to_num(visitor_raw["광역지자체 방문자 비율"]),
    )
    sido = sido[sido["sido_nm"].isin(labels)].groupby("sido_nm").first()
    return {"count": float(sido["count"].sum()), "ratio": float(sido["ratio"].sum())}


def _collapse_periods(visitor, merged_sido_total):
    """시군구별로 여러 기간 행을 하나로 합친다.

    방문자수는 기간이 겹치지 않으니 더한다. 비율은 그대로 더할 수 없다 - 원본의
    '기초지자체 방문자 비율'은 그 시도 시군구 방문자수 합계를 분모로 한 시도 내 몫이다
    (실측: 시도별로 기초 비율 합계가 100.0). 그래서 합친 뒤 분모를 다시 구해 계산한다.
    """
    grouped = visitor.groupby("region_nm", as_index=False).agg(
        visitor_count=("visitor_count", "sum"),
        sido_visitor_count=("sido_visitor_count", "sum"),
        sido_visitor_ratio=("sido_visitor_ratio", "sum"),
        rows=("visitor_count", "size"),
    )
    grouped["period_merged"] = grouped["rows"] > 1

    # 시도 방문자수/비율은 전국 기준 값이라 기간을 더하는 것이 맞다. 다만 합쳐진
    # 지역(광주/전남)은 세 라벨 전체의 합으로 바꿔야 27개 시군구가 같은 값을 갖는다.
    collapsed = grouped["period_merged"]
    grouped.loc[collapsed, "sido_visitor_count"] = merged_sido_total["count"]
    grouped.loc[collapsed, "sido_visitor_ratio"] = merged_sido_total["ratio"]

    # 시도 내 몫을 다시 계산한다 (분모 = 같은 시도 시군구 방문자수 합계)
    grouped["sido_nm"] = grouped["region_nm"].str.split().str[0]
    sido_sum = grouped.groupby("sido_nm")["visitor_count"].transform("sum")
    grouped["visitor_ratio"] = (grouped["visitor_count"] / sido_sum.replace(0, float("nan")) * 100).round(1)

    return grouped.drop(columns=["rows", "sido_nm"])


def _collapse_stay_periods(stay):
    """체류시간·숙박일수는 평균값이라 기간 행이 여러 개면 더하지 않고 평균을 낸다.

    광주/전남의 두 기간 값은 거의 같아서(목포시 1572분 vs 1559분) 단순 평균으로 충분하다.
    """
    return stay.groupby("region_nm", as_index=False).agg(
        avg_stay_minutes=("avg_stay_minutes", "mean"),
        avg_stay_nights=("avg_stay_nights", "mean"),
    )


def build_sigungu(sigungu_names_df):
    """visitor + stay를 시군구 단위로 합친다 (sigungu_cd로 연결되게).

    반환: (DataFrame, 미매칭 지역명 리스트)
    """
    visitor = _read_raw("visitor")
    stay = _read_raw("stay")
    if visitor is None or stay is None:
        return None, []

    visitor = visitor.assign(
        region_nm=_full_region_name(visitor["광역지자체명"], visitor["기초지자체명"]),
        sido_visitor_count=_to_num(visitor["광역지자체 방문자 수"]),
        sido_visitor_ratio=_to_num(visitor["광역지자체 방문자 비율"]),
        visitor_count=_to_num(visitor["기초지자체 방문자 수"]),
        visitor_ratio=_to_num(visitor["기초지자체 방문자 비율"]),
    )
    stay = stay.assign(
        region_nm=_full_region_name(stay["시도명"], stay["시군구명"]),
        avg_stay_minutes=_to_num(stay["평균 체류시간"]),
        avg_stay_nights=_to_num(stay["평균 숙박일수"]),
    )

    # 광주/전남은 기간이 나뉘어 들어오므로 시군구별로 합쳐 하나로 만든다
    visitor_merged_sido_total = _merged_sido_totals(_read_raw("visitor"))
    visitor = _collapse_periods(visitor, visitor_merged_sido_total)
    stay = _collapse_stay_periods(stay)

    merged = visitor[[
        "region_nm", "visitor_count", "visitor_ratio",
        "sido_visitor_count", "sido_visitor_ratio", "period_merged",
    ]].merge(
        stay[["region_nm", "avg_stay_minutes", "avg_stay_nights"]],
        on="region_nm",
        how="outer",
    )

    named = sigungu_names_df.rename(columns={"sigungu_nm": "region_nm"})
    result = named.merge(merged, on="region_nm", how="inner")

    unmatched = sorted(set(merged["region_nm"]) - set(result["region_nm"]))

    result = result.rename(columns={"region_nm": "sigungu_nm"})
    columns = [
        "sigungu_cd", "sigungu_nm",
        "avg_stay_minutes", "avg_stay_nights",
        "visitor_count", "visitor_ratio",
        "sido_visitor_count", "sido_visitor_ratio",
        "period_merged",
    ]
    return result[columns].sort_values("sigungu_cd").reset_index(drop=True), unmatched


def build_sido():
    """시도 단위 지표 3개(검색건수/방문자 증가율/관광지출액)를 한 표로 합친다."""
    search_count = _read_raw("search_count")
    top_region = _read_raw("top_region")
    spending = _read_raw("spending")
    if search_count is None or top_region is None or spending is None:
        return None

    search = search_count.assign(
        sido_nm=search_count["시도명"].str.strip(),
        search_count=_to_num(search_count["검색건수"]),
    )[["sido_nm", "search_count"]]

    growth = top_region.assign(
        sido_nm=top_region["시도명"].str.strip(),
        visitor_growth_pct=_to_num(top_region["증가율(%)"]),
    )[["sido_nm", "visitor_growth_pct"]]

    # spending은 (시도 x 유형) 긴 형태라 유형을 컬럼으로 펼친다
    spending = spending.assign(
        sido_nm=spending["시도명"].str.strip(),
        category=spending["유형별 대분류"].str.strip(),
        amount=_to_num(spending["관광지출액"]),
    )
    unknown = sorted(set(spending["category"]) - set(SPENDING_CATEGORIES))
    if unknown:
        print(f"spending에 모르는 유형이 있습니다 (컬럼으로 저장되지 않음): {unknown}")
    wide = (
        spending.pivot_table(index="sido_nm", columns="category", values="amount", aggfunc="sum")
        .rename(columns=SPENDING_CATEGORIES)
        .reset_index()
    )

    result = search.merge(growth, on="sido_nm", how="outer").merge(wide, on="sido_nm", how="outer")

    ordered = ["sido_nm", "search_count", "visitor_growth_pct"] + [
        column for column in SPENDING_CATEGORIES.values() if column in result.columns
    ]
    return result[ordered].sort_values("sido_nm").reset_index(drop=True)


def build_monthly():
    """월별 시계열 2개(관심도 / 방문자·지출 추세)를 기준연월로 합친다.

    두 파일의 기간이 달라서(관심도 24개월, 추세 12개월) outer join으로 둘 다 살린다.
    """
    interest = _read_raw("interest")
    trend = _read_raw("trend")
    if interest is None or trend is None:
        return None

    interest = interest.assign(
        base_ym=interest["기준년(월)"].str.strip(),
        interest_index=_to_num(interest["관심도"]),
    )[["base_ym", "interest_index"]]

    trend = trend.assign(
        base_ym=trend["기준연월"].str.strip(),
        visitor_count=_to_num(trend["방문자수"]),
        visitor_count_prev=_to_num(trend["전년동기 방문자수"]),
        visitor_growth_pct=_to_num(trend["방문자수 증감률"]),
        spending=_to_num(trend["관광지출액"]),
        spending_prev=_to_num(trend["전년동기 관광지출액"]),
        spending_growth_pct=_to_num(trend["관광지출액 증감률"]),
    )[[
        "base_ym", "visitor_count", "visitor_count_prev", "visitor_growth_pct",
        "spending", "spending_prev", "spending_growth_pct",
    ]]

    result = interest.merge(trend, on="base_ym", how="outer")
    return result.sort_values("base_ym").reset_index(drop=True)


def build_search_rank(sigungu_names_df):
    """전국 관광지 검색순위 TOP 100. 주소에서 시군구코드를 뽑아 지역 조회가 되게 한다."""
    search_rank = _read_raw("search_rank")
    if search_rank is None:
        return None

    # 주소 해석은 방문자 모듈과 같은 로직을 쓴다 (카카오식 줄인 시도명 '경북'까지 처리)
    from analysis.visitors import resolve_sigungu_cd

    result = search_rank.assign(
        rank=_to_num(search_rank["순위"]).astype("Int64"),
        sido_nm=search_rank["시도명"].str.strip(),
        place_name=search_rank["관광지명"].str.strip(),
        address=search_rank["주소"].str.strip(),
        category_mid=search_rank["중분류"].str.strip(),
        category_sub=search_rank["소분류"].str.strip(),
    )

    resolved = [resolve_sigungu_cd(address, sigungu_names_df) for address in result["address"]]
    result["sigungu_cd"] = [code for code, _ in resolved]
    result["sigungu_nm"] = [name for _, name in resolved]

    columns = [
        "rank", "place_name", "sido_nm", "sigungu_cd", "sigungu_nm",
        "address", "category_mid", "category_sub",
    ]
    return result[columns].sort_values("rank").reset_index(drop=True)


def build_age():
    """연령대별 방문집중지역. 지역명 뒤 공백이 섞여 있어 정리해서 저장한다."""
    age = _read_raw("age")
    if age is None:
        return None

    result = age.assign(
        popular_age_group=age["인기연령대"].str.strip(),
        region_nm=age["방문집중지역"].str.strip(),
        age_band=age["연령"].str.strip(),
        male_ratio=_to_num(age["남성 방문자 비율"]),
        female_ratio=_to_num(age["여성 방문자 비율"]),
    )
    result["total_ratio"] = (result["male_ratio"] + result["female_ratio"]).round(1)

    columns = [
        "popular_age_group", "region_nm", "age_band",
        "male_ratio", "female_ratio", "total_ratio",
    ]
    return result[columns].reset_index(drop=True)


def save_processed(df, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_parquet(out_path, index=False)
    return out_path


def main():
    sigungu_names = pd.read_csv(SIGUNGU_NAMES_PATH, dtype=str)

    print("## 1. 시군구 단위 (visitor + stay)")
    sigungu, unmatched = build_sigungu(sigungu_names)
    if sigungu is None:
        return
    save_processed(sigungu, SIGUNGU_PATH)
    print(f"저장 완료: {SIGUNGU_PATH}")
    print(f"  시군구 {len(sigungu)}개 (우리 코드 {len(sigungu_names)}개 중)")
    if unmatched:
        print(f"  미매칭 {len(unmatched)}개: {unmatched}")
    print(f"  체류시간 전국 평균 {sigungu['avg_stay_minutes'].mean():.0f}분 "
          f"(중위 {sigungu['avg_stay_minutes'].median():.0f}분)")
    print(f"  숙박일수 전국 평균 {sigungu['avg_stay_nights'].mean():.2f}일 "
          f"(중위 {sigungu['avg_stay_nights'].median():.2f}일)")
    print("  상위 3행:")
    print(sigungu.head(3).to_string(index=False))

    print("\n## 2. 시도 단위 (검색건수 + 증가율 + 지출액)")
    sido = build_sido()
    if sido is not None:
        save_processed(sido, SIDO_PATH)
        print(f"저장 완료: {SIDO_PATH}")
        print(f"  시도 {len(sido)}개 / 컬럼 {len(sido.columns)}개")
        print(sido.head(3).to_string(index=False))

    print("\n## 3. 월별 시계열 (관심도 + 방문자·지출 추세)")
    monthly = build_monthly()
    if monthly is not None:
        save_processed(monthly, MONTHLY_PATH)
        print(f"저장 완료: {MONTHLY_PATH}")
        print(f"  개월 {len(monthly)}개 ({monthly['base_ym'].min()} ~ {monthly['base_ym'].max()})")
        print(f"  관심도 있는 달 {monthly['interest_index'].notna().sum()}개 / "
              f"추세 있는 달 {monthly['visitor_count'].notna().sum()}개")
        print(monthly.tail(4).to_string(index=False))

    print("\n## 4. 검색순위 TOP 100")
    search_rank = build_search_rank(sigungu_names)
    if search_rank is not None:
        save_processed(search_rank, SEARCH_RANK_PATH)
        print(f"저장 완료: {SEARCH_RANK_PATH}")
        resolved = search_rank["sigungu_cd"].notna().sum()
        print(f"  {len(search_rank)}곳 / 주소에서 시군구코드 해석 {resolved}곳")
        if resolved < len(search_rank):
            print("  해석 실패:")
            print(search_rank[search_rank["sigungu_cd"].isna()][
                ["rank", "place_name", "address"]
            ].to_string(index=False))
        print(search_rank.head(3).to_string(index=False))

    print("\n## 5. 연령대별 방문집중지역")
    age = build_age()
    if age is not None:
        save_processed(age, AGE_PATH)
        print(f"저장 완료: {AGE_PATH}")
        print(f"  {len(age)}행 (지역 {age['region_nm'].nunique()}개 x 연령 {age['age_band'].nunique()}개)")
        print(age.head(3).to_string(index=False))

    print("\n## 고령군 자동 연결 확인")
    goryeong = sigungu[sigungu["sigungu_cd"] == "47830"]
    print(goryeong.to_string(index=False) if len(goryeong) else "  (없음)")


if __name__ == "__main__":
    main()
