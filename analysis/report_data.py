"""대상지 보고서에 들어갈 데이터를 한 번에 모은다.

새로 계산하지 않고 기존 분석 모듈을 그대로 불러 쓴다 - 화면에 나오는 숫자와
보고서 숫자가 어긋나면 안 되기 때문이다.

1단계 범위: 개요 / 인구·가구 / 교육·학생 / 주변 시설.
(관광·트렌드·주민니즈·요약은 2단계)

실행(테스트): python -m analysis.report_data
"""

import sys
from datetime import date

from analysis.area_profile import (
    ELEMENTARY,
    KAKAO_CATEGORIES,
    get_closed_schools_in_circle,
    get_facilities_in_circle,
    get_libraries_in_circle,
    get_living_area_households,
    get_living_area_population,
    get_nationwide_child_ratio,
    get_nationwide_lower_grade_ratio,
    get_nearby_facilities_kakao,
    get_tourism_in_circle,
)
from analysis.child_space import (
    assess_density,
    classify_child_spaces,
    get_child_centers_in_circle,
    get_culture_in_circle,
    get_nationwide_benchmarks,
    get_public_facilities_in_circle,
)
from analysis.datalab import get_sigungu_datalab
from analysis.living_area import calc_radius_km, get_dongs_in_circle
from analysis.popular_places import get_popular_places
from analysis.region_news import get_region_news
from analysis.tourism_region import get_region_detail, summarize_level_and_trend
from analysis.visitors import get_sigungu_visitors, resolve_sigungu_cd

# 보고서 기본 생활권 (화면 기본값과 같게 맞춘다)
DEFAULT_SPEED_KMH = 30
DEFAULT_MINUTES = 30

# 보고서에 실을 유입/유출·뉴스·인기공간 상위 개수
TOP_FLOW_COUNT = 5
TOP_NEWS_COUNT = 8
TOP_PLACE_COUNT = 8

# 인기 공간 검색에 쓸 기본 목적 키워드 (어린이 공간사업이 우리 용도라 '어린이'로 둔다)
POPULAR_PURPOSE_KEYWORD = "어린이"

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _region_query_name(sigungu_nm, place_name):
    """뉴스·인기공간 검색에 쓸 지역명. 시군구명 뒷부분을 쓴다('경상북도 고령군' -> '고령군')."""
    if sigungu_nm:
        tokens = sigungu_nm.split()
        return " ".join(tokens[-2:]) if len(tokens) >= 3 else tokens[-1]
    return place_name


def _collect_tourism(sigungu_cd):
    """관광·방문 특성 - 방문자, 체류·숙박, 유입/유출, 유사지역.

    지역 상세(유입/유출·유사지역)는 datalab_{코드}_* 를 넣어 둔 지역에만 있다.
    없으면 registered=False로 표시해 보고서에서 '상세 미등록'으로 쓴다.
    """
    if not sigungu_cd:
        return {"available": False, "registered": False}

    visitors = get_sigungu_visitors(sigungu_cd)
    datalab = get_sigungu_datalab(sigungu_cd)
    detail = get_region_detail(sigungu_cd)

    return {
        "available": bool(visitors or datalab),
        "registered": detail is not None,
        "visitors": visitors,
        "datalab": datalab,
        "detail": detail,
        "level_trend_summary": summarize_level_and_trend(detail) if detail else None,
    }


def _collect_news(sigungu_nm, place_name):
    """지역 사업 뉴스. 카카오 호출이 많아(키워드 12개 x 3페이지) 선택했을 때만 부른다."""
    region = _region_query_name(sigungu_nm, place_name)
    try:
        result = get_region_news(region)
    except Exception as e:
        return {"region": region, "error": str(e), "items": []}
    return {
        "region": region,
        "items": result["items"][:TOP_NEWS_COUNT],
        "total": len(result["items"]),
        "meta": result["meta"],
        "error": None,
    }


def _collect_popular(sigungu_nm, place_name):
    """목적별 인기 공간 (블로그·카페 언급). 문서를 150건 읽어와 무겁다."""
    region = _region_query_name(sigungu_nm, place_name)
    try:
        result = get_popular_places(region, POPULAR_PURPOSE_KEYWORD)
    except Exception as e:
        return {"region": region, "error": str(e), "items": []}

    mentioned = [place for place in result["places"] if place["mention_count"] > 0]
    return {
        "region": region,
        "keyword": POPULAR_PURPOSE_KEYWORD,
        "items": mentioned[:TOP_PLACE_COUNT],
        "total": len(mentioned),
        "meta": result["meta"],
        "error": None,
    }


def _collect_survey(survey_text, region_name):
    """사회조사 보고서 AI 분석. 보고서에는 '사실' 영역만 싣는다 (해석은 제외)."""
    from services.ai_service import AiServiceError, analyze_survey_pdf

    try:
        result, cost = analyze_survey_pdf(survey_text, region_name, label=f"report:{region_name}")
    except AiServiceError as e:
        return {"region_name": region_name, "error": str(e)}
    return {
        "region_name": region_name,
        "facts_markdown": result["facts_markdown"],
        "not_found": result["not_found"],
        "data_caveats": result["data_caveats"],
        "cost": cost,
        "error": None,
    }


def collect_report_data(
    place_name,
    address,
    lat,
    lon,
    minutes=DEFAULT_MINUTES,
    speed_kmh=DEFAULT_SPEED_KMH,
    include_news=False,
    include_popular=False,
    survey_text=None,
    progress_callback=None,
):
    """대상지 한 곳의 보고서 데이터를 모은다.

    place_name / address / lat / lon: 위치 검색 결과 (views에서 넘겨받는다)
    include_news / include_popular: 실시간 호출이 무거운 항목이라 선택해서 켠다
      (뉴스는 카카오 36회, 인기공간은 블로그·카페 150건 + 장소 후보 수집)
    survey_text: 사회조사 보고서에서 뽑은 텍스트 (있으면 AI로 주민 니즈를 분석한다)

    반환: dict - 보고서 섹션별로 쓸 수 있게 정리된 데이터
    """
    def report(step, total, label):
        if progress_callback:
            progress_callback(step, total, label)

    # 선택 항목 수에 따라 전체 단계 수가 달라진다
    total_steps = 7 + sum([bool(include_news), bool(include_popular), bool(survey_text)])
    radius_km = calc_radius_km(speed_kmh=speed_kmh, minutes=minutes)

    report(1, total_steps, "생활권 행정동 확인 중...")
    dongs = get_dongs_in_circle(lat, lon, radius_km)
    sigungu_cd, sigungu_nm = resolve_sigungu_cd(address)

    report(2, total_steps, "인구·세대 집계 중...")
    population = get_living_area_population(dongs)
    households = get_living_area_households(dongs)

    report(3, total_steps, "학교·학생 집계 중...")
    facilities = get_facilities_in_circle(lat, lon, radius_km)

    report(4, total_steps, "공공시설 조회 중...")
    libraries = get_libraries_in_circle(lat, lon, radius_km)
    tourism = get_tourism_in_circle(lat, lon, radius_km)
    closed_schools = get_closed_schools_in_circle(lat, lon, radius_km)
    child_centers = get_child_centers_in_circle(lat, lon, radius_km)
    culture = get_culture_in_circle(lat, lon, radius_km)
    public_facilities = get_public_facilities_in_circle(lat, lon, radius_km)

    report(5, total_steps, "주변 시설 검색 중 (카카오)...")
    kakao = get_nearby_facilities_kakao(lat, lon, min(radius_km * 1000, 20000))

    report(6, total_steps, "어린이 공간 분류·밀도 계산 중...")
    child_spaces = classify_child_spaces(
        facilities,
        libraries,
        closed_schools,
        kakao,
        tourism["count"],
        child_centers=child_centers,
        culture=culture,
        public_facilities=public_facilities,
    )
    benchmarks = get_nationwide_benchmarks()
    density = assess_density(
        population["age_0_9"],
        child_spaces["공공 돌봄·교육"]["count"],
        benchmarks,
        child_center_count=child_spaces["공공 돌봄·교육"]["child_center_count"],
    )

    report(7, total_steps, "관광·방문 특성 조회 중...")
    tourism_profile = _collect_tourism(sigungu_cd)

    step = 7
    news = None
    if include_news:
        step += 1
        report(step, total_steps, "지역 사업 뉴스 검색 중...")
        news = _collect_news(sigungu_nm, place_name)

    popular = None
    if include_popular:
        step += 1
        report(step, total_steps, "인기 공간 분석 중 (블로그·카페)...")
        popular = _collect_popular(sigungu_nm, place_name)

    survey = None
    if survey_text:
        step += 1
        report(step, total_steps, "사회조사 보고서 AI 분석 중...")
        survey = _collect_survey(survey_text, sigungu_nm or place_name)

    child_ratio = (
        population["age_0_9"] / population["total"] * 100 if population["total"] else 0.0
    )
    elementary_students = facilities["students"][ELEMENTARY]
    lower_grade_ratio = (
        facilities["students_grade_1_3"] / elementary_students * 100
        if elementary_students
        else 0.0
    )

    return {
        "overview": {
            "place_name": place_name,
            "address": address,
            "lat": lat,
            "lon": lon,
            "sigungu_cd": sigungu_cd,
            "sigungu_nm": sigungu_nm,
            "minutes": minutes,
            "speed_kmh": speed_kmh,
            "radius_km": radius_km,
            "dong_count": len(dongs),
            "dong_names": dongs["ADM_NM"].tolist() if not dongs.empty else [],
            "created_on": date.today().isoformat(),
        },
        "population": population,
        "households": households,
        "child_ratio": round(child_ratio, 1),
        "nationwide_child_ratio": get_nationwide_child_ratio(),
        "facilities": facilities,
        "lower_grade_ratio": round(lower_grade_ratio, 1),
        "nationwide_lower_grade_ratio": get_nationwide_lower_grade_ratio(),
        "child_spaces": child_spaces,
        "density": density,
        "benchmarks": benchmarks,
        "kakao_counts": {category: kakao[category]["count"] for category in KAKAO_CATEGORIES},
        "tourism": tourism_profile,
        "news": news,
        "popular": popular,
        "survey": survey,
    }


def main():
    from dotenv import load_dotenv

    load_dotenv()
    data = collect_report_data(
        "고령군청",
        "경북 고령군 대가야읍 지산리 190",
        35.726065320875,
        128.262895757565,
        progress_callback=lambda i, n, label: print(f"  ({i}/{n}) {label}"),
    )

    overview = data["overview"]
    print(f"\n대상지: {overview['place_name']} ({overview['sigungu_nm']})")
    print(f"  생활권 {overview['minutes']}분 / 반경 {overview['radius_km']:.1f}km / "
          f"행정동 {overview['dong_count']}개")
    print(f"  인구 {data['population']['total']:,}명 "
          f"(0~9세 {data['population']['age_0_9']:,}명, {data['child_ratio']}%)")
    print(f"  세대 {data['households']['total_households']:,}세대 "
          f"(가족가구 비중 {data['households']['family_ratio']}%)")
    counts = data["facilities"]["counts"]
    print(f"  학교 {sum(counts.values())}개 / 학생 {data['facilities']['students_total']:,}명 "
          f"(저학년 {data['facilities']['students_grade_1_3']:,}명)")
    for name, group in data["child_spaces"].items():
        print(f"  {name}: {group['count']}개")
    if data["density"]:
        print(f"  밀도 판정: [{data['density']['label']}] "
              f"{data['density']['children_per_space']}명/공간")


if __name__ == "__main__":
    main()
