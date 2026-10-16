"""지역별 관광 상세 - 유입/유출, 유사지역, 그리고 "수준 + 추세"를 함께 읽는다.

데이터 성격이 둘로 나뉘는 것이 핵심이다.
  수준(절대값): 한국관광공사 API·데이터랩 전국 집계에서 온 값. 전국 몇 위권인지.
  추세(증감률): 데이터랩 지역 상세에서 온 전년동기 대비 변화율. 좋아지는 중인지.

둘을 따로 보면 오독하기 쉽다. 고령군은 체류시간 수준이 전국 중위보다 6.5시간 짧지만
추세는 +1.4%라, "수준은 낮지만 개선 중"이 맞는 읽기다. 추세만 보면 좋은 지역으로,
수준만 보면 가망 없는 지역으로 잘못 읽힌다.

지역 상세는 datalab_{코드}_* 파일을 넣고 ingest/build_tourism_region.py를 돌린 지역만
있다. 없는 지역은 전국 기본 지표만 보여주고 상세는 미등록으로 안내한다.

실행(테스트): python -m analysis.tourism_region
"""

import functools
import sys

import pandas as pd

from analysis.datalab import get_sigungu_datalab

REGION_PATH = "data/processed/tourism_region.parquet"
LINKED_PATH = "data/processed/tourism_region_linked.parquet"
SIMILAR_PATH = "data/processed/tourism_region_similar.parquet"

DATA_SOURCE = "한국관광 데이터랩 (한국관광공사)"
TREND_CAVEAT = "증감률은 전년동기 대비이며, 수준(절대값)과는 다른 이야기를 합니다."

# 수준과 추세를 모두 가진 지표 (수준 키, 추세 키, 라벨, 단위)
LEVEL_TREND_METRICS = [
    ("stay_vs_median", "stay_time_growth_pct", "체류시간", "시간"),
    ("nights_vs_median", "lodging_growth_pct", "숙박", "일"),
]

# 추세만 있는 지표 (전국 절대 비교값이 없는 것들)
TREND_ONLY_METRICS = [
    ("visitor_growth_pct", "방문자 유입"),
    ("search_growth_pct", "목적지 검색량"),
    ("spending_growth_pct", "관광소비"),
]

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _read(path):
    try:
        return pd.read_parquet(path)
    except (FileNotFoundError, OSError):
        return None


@functools.lru_cache(maxsize=1)
def _load_region(path=REGION_PATH):
    return _read(path)


@functools.lru_cache(maxsize=1)
def _load_linked(path=LINKED_PATH):
    return _read(path)


@functools.lru_cache(maxsize=1)
def _load_similar(path=SIMILAR_PATH):
    return _read(path)


def has_region_detail(sigungu_cd, path=REGION_PATH):
    """그 지역의 상세 데이터가 등록되어 있는지."""
    region = _load_region(path)
    if region is None:
        return False
    return str(sigungu_cd) in set(region["region_cd"])


def list_registered_regions(path=REGION_PATH):
    """상세가 등록된 지역 목록 (화면 안내용)."""
    region = _load_region(path)
    if region is None or region.empty:
        return []
    return list(zip(region["region_cd"], region["sigungu_nm"].fillna(region["region_nm"])))


def _verdict(level, trend):
    """수준과 추세를 묶어 한 줄 판정을 만든다 (4분면).

    level: 전국 중위 대비 차이 (양수면 전국 중위보다 높음)
    trend: 전년동기 대비 증감률 (양수면 개선)
    """
    if level is None or trend is None or pd.isna(level) or pd.isna(trend):
        return None
    high = level >= 0
    rising = trend > 0
    if high and rising:
        return "높고 더 오르는 중"
    if high and not rising:
        return "높지만 둔화"
    if not high and rising:
        return "낮지만 개선 중"
    return "낮고 약화"


def get_region_detail(sigungu_cd, top_n=5):
    """지역 상세(지표 추세 + 유입/유출 + 유사지역)와 수준·추세 결합 판정을 돌려준다.

    반환: dict 또는 상세가 등록되지 않은 지역이면 None
    """
    region = _load_region()
    if region is None:
        return None

    code = str(sigungu_cd)
    matched = region[region["region_cd"] == code]
    if matched.empty:
        return None
    row = matched.iloc[0]

    # 수준(절대값)은 데이터랩 전국 집계에서 가져온다
    level = get_sigungu_datalab(code)

    metrics = []
    for level_key, trend_key, label, unit in LEVEL_TREND_METRICS:
        trend_value = row[trend_key]
        level_value = level.get(level_key) if level else None
        # 체류시간 수준은 분 단위라 시간으로 바꿔 보여준다
        if level_key == "stay_vs_median" and level_value is not None:
            level_value = round(level_value / 60, 1)
        metrics.append({
            "label": label,
            "unit": unit,
            "level_vs_median": level_value,
            "trend_pct": None if pd.isna(trend_value) else float(trend_value),
            "verdict": _verdict(level_value, trend_value),
        })

    trends = [
        {"label": label, "trend_pct": None if pd.isna(row[key]) else float(row[key])}
        for key, label in TREND_ONLY_METRICS
    ]

    linked = _load_linked()
    inflow, outflow = [], []
    if linked is not None:
        subset = linked[linked["region_cd"] == code]
        inflow = subset[(subset["direction"] == "유입") & (subset["rank"] <= top_n)].to_dict("records")
        outflow = subset[(subset["direction"] == "유출") & (subset["rank"] <= top_n)].to_dict("records")

    similar = _load_similar()
    peers = []
    if similar is not None:
        peers = similar[similar["region_cd"] == code]["similar_region_nm"].tolist()

    return {
        "region_cd": code,
        "region_nm": row["sigungu_nm"] or row["region_nm"],
        "sido_nm": row["sido_nm"],
        "sido_growth_pct": float(row["sido_growth_pct"]),
        "metrics": metrics,
        "trends": trends,
        "inflow": inflow,
        "outflow": outflow,
        "similar_regions": peers,
        "level": level,
    }


def summarize_level_and_trend(detail):
    """'수준은 낮지만 추세는 개선' 같은 한 줄 요약을 만든다.

    반환: 문자열 또는 판정할 지표가 없으면 None
    """
    if detail is None:
        return None
    judged = [metric for metric in detail["metrics"] if metric["verdict"]]
    if not judged:
        return None

    rising = [m for m in judged if m["trend_pct"] and m["trend_pct"] > 0]
    low = [m for m in judged if m["level_vs_median"] is not None and m["level_vs_median"] < 0]

    if low and len(rising) == len(judged):
        return (
            f"{', '.join(m['label'] for m in low)} 수준은 전국 중위보다 낮지만 "
            "추세는 모두 개선 중입니다"
        )
    if not low and len(rising) == len(judged):
        return "수준도 전국 중위 이상이고 추세도 오르는 중입니다"
    if low and not rising:
        return f"{', '.join(m['label'] for m in low)} 수준이 낮고 추세도 약화되고 있습니다"
    return " · ".join(f"{m['label']} {m['verdict']}" for m in judged)


def main():
    registered = list_registered_regions()
    if not registered:
        print(f"{REGION_PATH} 가 없습니다. python ingest/build_tourism_region.py 를 먼저 실행하세요.")
        return

    print(f"상세 등록 지역 {len(registered)}개: "
          + ", ".join(f"{code} {name}" for code, name in registered))

    for code, _name in registered:
        detail = get_region_detail(code)
        print(f"\n{'=' * 72}")
        print(f"  {detail['region_nm']} ({code})")
        print("=" * 72)

        summary = summarize_level_and_trend(detail)
        if summary:
            print(f"  요약: {summary}")

        print("  [수준 + 추세]")
        for metric in detail["metrics"]:
            level_text = (
                f"전국 중위 대비 {metric['level_vs_median']:+}{metric['unit']}"
                if metric["level_vs_median"] is not None
                else "수준 비교 불가"
            )
            print(f"    {metric['label']:<5} 수준: {level_text:<24} "
                  f"추세: {metric['trend_pct']:+.1f}%  -> {metric['verdict']}")

        print("  [추세만]")
        for trend in detail["trends"]:
            print(f"    {trend['label']:<10} {trend['trend_pct']:+.1f}%")
        print(f"    (시도 {detail['sido_nm']} 방문자 증가율 {detail['sido_growth_pct']:+.1f}%)")

        print("  [어디서 오나 - 유입 TOP5]")
        for item in detail["inflow"]:
            print(f"    {item['rank']}. {item['counterpart_nm']} {item['ratio']}%")
        print("  [어디로 가나 - 유출 TOP5]")
        for item in detail["outflow"]:
            print(f"    {item['rank']}. {item['counterpart_nm']} {item['ratio']}%")
        print(f"  [유사지역] {', '.join(detail['similar_regions'])}")

    print(f"\n미등록 지역 예시 (47113 포항시 북구): "
          f"{'등록됨' if has_region_detail('47113') else '미등록 -> 전국 기본만 표시'}")


if __name__ == "__main__":
    main()
