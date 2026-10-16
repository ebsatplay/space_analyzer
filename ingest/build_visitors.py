"""한국관광공사 데이터랩 전국 방문자수를 받아 시군구 단위로 집계해 저장하는 1회성 스크립트.

이 API에는 시군구 필터가 없어서 조회할 때마다 전국을 받아야 한다 (하루 807행).
그래서 화면에서 매번 부르지 않고, 최신 가용 한 달치를 한 번 받아 시군구별로 집계해
data/processed/visitors_by_sigungu.parquet 에 캐싱한다.

데이터가 약 1개월 지연되므로 "최근 한 달"은 오늘 기준이 아니라 데이터가 들어와 있는
마지막 날짜를 찾아서 그로부터 거꾸로 한 달을 잡는다.

실행: python -m ingest.build_visitors
(services.tourism_service를 import하므로 python ingest/build_visitors.py로 직접 실행하면 안 됨)
"""

import os
import sys
from datetime import datetime, timedelta

import pandas as pd

from services.tourism_service import (
    TOU_DIV_LABELS,
    TourismApiError,
    fetch_nationwide_visitors,
    find_latest_available_ymd,
)

PROCESSED_PATH = "data/processed/visitors_by_sigungu.parquet"
SIGUNGU_NAMES_PATH = "data/reference/sigungu_names.csv"

# 최신 가용일로부터 거꾸로 며칠치를 모을지 (요일 편차가 생기지 않도록 7의 배수로 둔다)
COLLECT_DAYS = 28

# daywkDivCd: 1=월 ~ 7=일. 주말 유입형 판단을 추정이 아닌 측정으로 하기 위해 쪼갠다
WEEKEND_DAY_CODES = {"6", "7"}

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _date_range(latest_ymd, days):
    """최신 가용일에서 거꾸로 days일 구간의 (시작, 끝) YYYYMMDD를 만든다."""
    end = datetime.strptime(latest_ymd, "%Y%m%d").date()
    start = end - timedelta(days=days - 1)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def aggregate_by_sigungu(items, sigungu_names_df):
    """전국 원본 항목을 시군구 단위로 집계한다.

    원본은 (시군구 x 날짜 x 구분) 단위라 기간 합계로 접고, 외지인 비중을 계산한다.
    외지인 비중의 분모는 현지인+외지인+외국인 전체다.

    반환: DataFrame (sigungu_cd, sigungu_nm, visitors_local, visitors_outsider,
          visitors_foreign, visitors_total, outsider_ratio, days)
    """
    if not items:
        return pd.DataFrame()

    raw = pd.DataFrame(items)
    raw["sigungu_cd"] = raw["signguCode"].astype(str).str.strip()
    raw["div_label"] = raw["touDivCd"].astype(str).str.strip().map(TOU_DIV_LABELS)
    raw["visitor_count"] = pd.to_numeric(raw["touNum"], errors="coerce").fillna(0)

    # 매핑되지 않는 구분 코드가 생기면 조용히 버리지 않고 알린다
    unknown = raw[raw["div_label"].isna()]
    if len(unknown):
        print(f"알 수 없는 방문자 구분 코드 {unknown['touDivCd'].unique().tolist()} - {len(unknown)}행 제외")
        raw = raw[raw["div_label"].notna()]

    pivot = raw.pivot_table(
        index="sigungu_cd",
        columns="div_label",
        values="visitor_count",
        aggfunc="sum",
        fill_value=0,
    ).rename(columns={"현지인": "visitors_local", "외지인": "visitors_outsider", "외국인": "visitors_foreign"})

    for column in ("visitors_local", "visitors_outsider", "visitors_foreign"):
        if column not in pivot.columns:
            pivot[column] = 0.0

    days = raw.groupby("sigungu_cd")["baseYmd"].nunique().rename("days")
    api_names = raw.groupby("sigungu_cd")["signguNm"].first().rename("api_area_nm")

    # 주말/평일 외지인 "하루 평균"을 따로 낸다 (기간 합계로는 주말이 이틀뿐이라 비교가 안 된다)
    outsiders = raw[raw["div_label"] == "외지인"].copy()
    outsiders["is_weekend"] = outsiders["daywkDivCd"].astype(str).str.strip().isin(WEEKEND_DAY_CODES)
    daily = outsiders.groupby(["sigungu_cd", "is_weekend", "baseYmd"])["visitor_count"].sum()
    day_avg = daily.groupby(["sigungu_cd", "is_weekend"]).mean().unstack(fill_value=0)
    day_avg = day_avg.rename(columns={False: "outsider_weekday_avg", True: "outsider_weekend_avg"})
    for column in ("outsider_weekday_avg", "outsider_weekend_avg"):
        if column not in day_avg.columns:
            day_avg[column] = 0.0

    agg = pivot.join(days).join(api_names).join(day_avg).reset_index()

    # 원본 touNum이 소수라, 구분별로 먼저 정수로 반올림한 뒤 합계를 낸다.
    # (합계를 먼저 내고 각각 따로 반올림하면 화면에 찍히는 내역 합이 총계와 1명씩 틀어진다)
    for column in ("visitors_local", "visitors_outsider", "visitors_foreign"):
        agg[column] = agg[column].round().astype("int64")
    agg["visitors_total"] = (
        agg["visitors_local"] + agg["visitors_outsider"] + agg["visitors_foreign"]
    )

    # 방문자가 0인 시군구에서 0으로 나누지 않도록 분모를 NaN으로 바꿔 계산한다
    denominator = agg["visitors_total"].replace(0, float("nan"))
    agg["outsider_ratio"] = (agg["visitors_outsider"] / denominator * 100).round(1)

    # 주말 유입 배수: 주말 하루 평균 외지인 / 평일 하루 평균 외지인
    weekday_avg = agg["outsider_weekday_avg"].replace(0, float("nan"))
    agg["weekend_lift"] = (agg["outsider_weekend_avg"] / weekday_avg).round(2)

    # 우리 시군구 이름을 붙인다 (코드 체계가 같은 것을 프로브에서 확인했다)
    merged = sigungu_names_df.merge(agg, on="sigungu_cd", how="inner")

    for column in ("outsider_weekday_avg", "outsider_weekend_avg"):
        merged[column] = merged[column].round().astype("int64")

    columns = [
        "sigungu_cd", "sigungu_nm",
        "visitors_total", "visitors_local", "visitors_outsider", "visitors_foreign",
        "outsider_ratio", "outsider_weekday_avg", "outsider_weekend_avg", "weekend_lift",
        "days",
    ]
    return merged[columns].sort_values("sigungu_cd").reset_index(drop=True)


def save_processed(df, out_path=PROCESSED_PATH):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_parquet(out_path, index=False)
    return out_path


def main():
    print("데이터가 들어와 있는 최신 날짜를 찾는 중...")
    latest_ymd = find_latest_available_ymd()
    if latest_ymd is None:
        print("최근 90일 안에 데이터가 있는 날짜를 찾지 못했습니다")
        return

    start_ymd, end_ymd = _date_range(latest_ymd, COLLECT_DAYS)
    print(f"최신 가용일: {latest_ymd} (오늘로부터 약 {(datetime.now().date() - datetime.strptime(latest_ymd, '%Y%m%d').date()).days}일 지연)")
    print(f"수집 구간: {start_ymd} ~ {end_ymd} ({COLLECT_DAYS}일)")

    def on_progress(received, total):
        print(f"  수집 {received:,}/{total:,}행")

    try:
        items, total_count = fetch_nationwide_visitors(
            start_ymd, end_ymd, progress_callback=on_progress
        )
    except TourismApiError as e:
        print(f"API 오류: {e}")
        return

    print(f"\n전국 {len(items):,}행 수집 완료 (totalCount={total_count:,})")

    sigungu_names = pd.read_csv(SIGUNGU_NAMES_PATH, dtype=str)
    agg = aggregate_by_sigungu(items, sigungu_names)
    if agg.empty:
        print("집계할 데이터가 없습니다")
        return

    agg["base_start_ymd"] = start_ymd
    agg["base_end_ymd"] = end_ymd

    out_path = save_processed(agg)
    print(f"저장 완료: {out_path}")
    print(f"\n시군구 수: {len(agg)}개 / sigungu_names {len(sigungu_names)}개")
    print(f"전국 방문자 합계: {agg['visitors_total'].sum():,}명")
    print(f"  현지인 {agg['visitors_local'].sum():,}명 / 외지인 {agg['visitors_outsider'].sum():,}명 "
          f"/ 외국인 {agg['visitors_foreign'].sum():,}명")
    print(f"외지인 비중 중위값: {agg['outsider_ratio'].median():.1f}%")

    print("\n상위 5행:")
    print(agg.head().to_string(index=False))

    print("\n외지인 비중 상위 5개 시군구:")
    print(agg.nlargest(5, "outsider_ratio")[
        ["sigungu_cd", "sigungu_nm", "visitors_total", "outsider_ratio"]
    ].to_string(index=False))

    print("\n외지인 비중 하위 5개 시군구 (생활밀착형):")
    print(agg.nsmallest(5, "outsider_ratio")[
        ["sigungu_cd", "sigungu_nm", "visitors_total", "outsider_ratio"]
    ].to_string(index=False))

    goryeong = agg[agg["sigungu_cd"] == "47830"]
    if len(goryeong):
        print("\n고령군:")
        print(goryeong.to_string(index=False))


if __name__ == "__main__":
    main()
