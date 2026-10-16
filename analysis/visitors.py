"""시군구 관광 방문자수 프로파일 - 외지인 비중과 주말 유입 배수로 지역 성격을 가른다.

데이터는 ingest/build_visitors.py가 만들어 둔 visitors_by_sigungu.parquet을 읽는다
(한국관광공사 데이터랩 API에는 시군구 필터가 없어서 전국을 받아 캐싱해 둔 것).

판단 기준을 임의의 숫자로 두지 않고 전국 269개 시군구의 사분위에서 뽑는다.
"외지인 비중 50%"가 높은 건지 낮은 건지는 전국 분포를 봐야 알 수 있기 때문이다
(실측 분포: 외지인 비중 중위 41.4%, 1사분위 35.6%, 3사분위 47.8%).

실행(테스트): python -m analysis.visitors
"""

import functools
import sys

import pandas as pd

VISITORS_PATH = "data/processed/visitors_by_sigungu.parquet"
SIGUNGU_NAMES_PATH = "data/reference/sigungu_names.csv"

# 방문자 데이터의 성격 - 화면에 그대로 띄워 오해를 막는다
DATA_CAVEAT = (
    "방문자는 해당 지역에 일상권을 벗어나 머문 사람으로, 관광객과 유사하나 동일하지 않습니다. "
    "이동통신 기반 추정치이며 약 1개월 지연됩니다."
)

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def _load_visitors(visitors_path=VISITORS_PATH):
    """방문자 집계를 읽는다 (없으면 None). 파일을 매번 읽지 않도록 캐시한다."""
    try:
        return pd.read_parquet(visitors_path)
    except (FileNotFoundError, OSError):
        return None


@functools.lru_cache(maxsize=1)
def get_nationwide_quartiles(visitors_path=VISITORS_PATH):
    """전국 외지인 비중/주말 배수의 사분위를 돌려준다 (판단 기준선).

    반환: dict 또는 데이터가 없으면 None
    """
    visitors = _load_visitors(visitors_path)
    if visitors is None or visitors.empty:
        return None

    return {
        "outsider_ratio_q1": float(visitors["outsider_ratio"].quantile(0.25)),
        "outsider_ratio_median": float(visitors["outsider_ratio"].median()),
        "outsider_ratio_q3": float(visitors["outsider_ratio"].quantile(0.75)),
        "weekend_lift_q1": float(visitors["weekend_lift"].quantile(0.25)),
        "weekend_lift_median": float(visitors["weekend_lift"].median()),
        "weekend_lift_q3": float(visitors["weekend_lift"].quantile(0.75)),
        "sigungu_count": len(visitors),
    }


def _sido_matches(address_sido, sigungu_sido):
    """주소의 줄인 시도명이 시군구명의 시도 부분과 같은 곳을 가리키는지 본다.

    카카오 주소는 시도를 줄여 쓴다("경북 고령군"). 줄임말의 글자가 전체 이름 안에
    순서대로 들어 있으면 같은 시도로 본다 ('경북' -> '경상북도', '강원' -> '강원특별자치도').
    """
    position = 0
    for char in address_sido:
        position = sigungu_sido.find(char, position)
        if position < 0:
            return False
        position += 1
    return True


def resolve_sigungu_cd(address, sigungu_names_df=None):
    """주소에서 시군구코드(5자리)를 찾아낸다.

    이름만으로는 안 된다 - '중구'는 서울/부산/대구/인천/대전/울산에 모두 있어서
    시도까지 함께 맞춰야 한다. 시군구 이름 뒷부분으로 후보를 찾고, 주소 첫 토큰의
    시도명으로 후보를 좁힌다.

    반환: (sigungu_cd, sigungu_nm) 또는 못 찾으면 (None, None)
    """
    if not isinstance(address, str) or not address.strip():
        return None, None

    if sigungu_names_df is None:
        sigungu_names_df = pd.read_csv(SIGUNGU_NAMES_PATH, dtype=str)

    tokens = address.split()
    if not tokens:
        return None, None
    address_sido = tokens[0]

    candidates = []
    for row in sigungu_names_df.itertuples(index=False):
        name_tokens = row.sigungu_nm.split()
        if len(name_tokens) >= 3:
            tail = " ".join(name_tokens[-2:])
        elif len(name_tokens) == 2:
            tail = name_tokens[-1]
        else:
            tail = row.sigungu_nm
        if tail not in address:
            continue
        sigungu_sido = name_tokens[0]
        if len(name_tokens) > 1 and not _sido_matches(address_sido, sigungu_sido):
            continue
        candidates.append((len(tail), row.sigungu_cd, row.sigungu_nm))

    if not candidates:
        return None, None

    # 뒷부분이 긴 쪽을 택한다 ('포항시 북구'가 '북구'보다 구체적)
    candidates.sort(reverse=True)
    return candidates[0][1], candidates[0][2]


def classify_visitor_pattern(outsider_ratio, weekend_lift, quartiles):
    """외지인 비중과 주말 배수를 전국 분포에 비춰 지역 성격을 한 줄로 설명한다.

    반환: dict (label, detail) 또는 판단 불가 시 None
    """
    if quartiles is None or outsider_ratio is None or pd.isna(outsider_ratio):
        return None

    high_outsider = outsider_ratio >= quartiles["outsider_ratio_q3"]
    low_outsider = outsider_ratio <= quartiles["outsider_ratio_q1"]
    weekend_driven = (
        weekend_lift is not None
        and not pd.isna(weekend_lift)
        and weekend_lift >= quartiles["weekend_lift_q3"]
    )

    if high_outsider and weekend_driven:
        label = "주말 유입형"
        detail = "외부에서 주말에 찾아오는 지역 - 관광 연계 공간사업에 유리합니다"
    elif high_outsider:
        label = "외부 유입형"
        detail = "외지인 비중이 전국 상위권이라 외부 방문 수요가 꾸준한 지역입니다"
    elif weekend_driven:
        label = "주말 집중형"
        detail = "평소는 생활권이지만 주말에 외부 방문이 뛰는 지역입니다"
    elif low_outsider:
        label = "생활밀착형"
        detail = "방문 대부분이 현지인이라 주민 생활시설 성격이 강한 지역입니다"
    else:
        label = "혼합형"
        detail = "외지인 비중과 주말 유입이 모두 전국 중간 수준입니다"

    return {"label": label, "detail": detail}


def get_sigungu_visitors(sigungu_cd, visitors_path=VISITORS_PATH):
    """시군구 방문자 프로파일을 돌려준다.

    반환: dict (방문자수/비중/주말배수/판단/기준기간) 또는 데이터가 없으면 None
    """
    visitors = _load_visitors(visitors_path)
    if visitors is None:
        return None

    matched = visitors[visitors["sigungu_cd"] == str(sigungu_cd)]
    if matched.empty:
        return None

    row = matched.iloc[0]
    quartiles = get_nationwide_quartiles(visitors_path)
    pattern = classify_visitor_pattern(
        float(row["outsider_ratio"]), float(row["weekend_lift"]), quartiles
    )

    return {
        "sigungu_cd": row["sigungu_cd"],
        "sigungu_nm": row["sigungu_nm"],
        "visitors_total": int(row["visitors_total"]),
        "visitors_local": int(row["visitors_local"]),
        "visitors_outsider": int(row["visitors_outsider"]),
        "visitors_foreign": int(row["visitors_foreign"]),
        "outsider_ratio": float(row["outsider_ratio"]),
        "outsider_weekday_avg": int(row["outsider_weekday_avg"]),
        "outsider_weekend_avg": int(row["outsider_weekend_avg"]),
        "weekend_lift": float(row["weekend_lift"]),
        "days": int(row["days"]),
        "base_start_ymd": row["base_start_ymd"],
        "base_end_ymd": row["base_end_ymd"],
        "pattern": pattern,
        "quartiles": quartiles,
    }


def get_visitors_for_address(address, visitors_path=VISITORS_PATH):
    """주소 -> 시군구코드 -> 방문자 프로파일까지 한 번에 처리한다.

    반환: (프로파일 또는 None, 찾아낸 시군구명 또는 None)
    """
    sigungu_cd, sigungu_nm = resolve_sigungu_cd(address)
    if sigungu_cd is None:
        return None, None
    return get_sigungu_visitors(sigungu_cd, visitors_path), sigungu_nm


def main():
    quartiles = get_nationwide_quartiles()
    if quartiles is None:
        print(f"{VISITORS_PATH} 가 없습니다. python -m ingest.build_visitors 를 먼저 실행하세요.")
        return

    print(f"전국 {quartiles['sigungu_count']}개 시군구 기준선")
    print(f"  외지인 비중: 1사분위 {quartiles['outsider_ratio_q1']:.1f}% / "
          f"중위 {quartiles['outsider_ratio_median']:.1f}% / 3사분위 {quartiles['outsider_ratio_q3']:.1f}%")
    print(f"  주말 배수:   1사분위 {quartiles['weekend_lift_q1']:.2f} / "
          f"중위 {quartiles['weekend_lift_median']:.2f} / 3사분위 {quartiles['weekend_lift_q3']:.2f}")

    for address in (
        "경북 고령군 대가야읍 지산리 190",
        "경북 포항시 북구 중앙로 123",
        "서울 중구 세종대로 110",
        "부산 중구 중앙대로 120",
        "경기 가평군 가평읍 석봉로 181",
    ):
        profile, sigungu_nm = get_visitors_for_address(address)
        print(f"\n{address}")
        if profile is None:
            print(f"  -> 시군구: {sigungu_nm or '(못 찾음)'} / 방문자 데이터 없음")
            continue
        pattern = profile["pattern"]
        print(f"  -> {profile['sigungu_nm']} ({profile['sigungu_cd']})")
        print(f"     기간 {profile['base_start_ymd']}~{profile['base_end_ymd']} ({profile['days']}일)")
        print(f"     전체 {profile['visitors_total']:,}명 "
              f"= 현지인 {profile['visitors_local']:,} + 외지인 {profile['visitors_outsider']:,} "
              f"+ 외국인 {profile['visitors_foreign']:,}")
        print(f"     외지인 비중 {profile['outsider_ratio']:.1f}% | 주말 배수 {profile['weekend_lift']:.2f}배 "
              f"(평일 {profile['outsider_weekday_avg']:,} -> 주말 {profile['outsider_weekend_avg']:,})")
        print(f"     판단: [{pattern['label']}] {pattern['detail']}")


if __name__ == "__main__":
    main()
