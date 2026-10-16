"""생활권(원 안 행정동)에 인구 지표를 붙여서 합산한다.

실행(테스트): python -m analysis.area_profile
(다른 패키지의 living_area를 import하므로 python analysis/area_profile.py로 직접 실행하면 안 됨)
"""

import functools
import sys

import pandas as pd

from analysis.living_area import _haversine_km
from services.kakao_service import search_places_nearby

POPULATION_PATH = "data/processed/population.parquet"
HOUSEHOLDS_PATH = "data/processed/households.parquet"
MAPPING_PATH = "data/reference/adm_cd_mapping.csv"
SCHOOLS_PATH = "data/processed/schools.parquet"
STUDENTS_PATH = "data/processed/students.parquet"
SCHOOL_LEVELS = ["초등학교", "중학교", "고등학교"]
ELEMENTARY = "초등학교"

LIBRARIES_PATH = "data/processed/libraries.parquet"
LIBRARY_GROUPS = ["주요도서관", "작은도서관", "기타"]

TOURISM_PATH = "data/processed/tourism.parquet"

CLOSED_SCHOOLS_PATH = "data/processed/closed_schools.parquet"
CLOSED_SCHOOL_USAGE_STATUSES = ["미활용", "대부", "자체활용"]

# 카카오 키워드 검색용 카테고리별 검색어 (카테고리 하나에 여러 키워드로 검색 후 합침)
KAKAO_CATEGORY_KEYWORDS = {
    "관광명소": ["관광명소", "공원", "해수욕장"],
    "키즈카페": ["키즈카페", "실내놀이터"],
    "문화체험": ["박물관", "과학관", "미술관", "문화센터"],
    "집객시설": ["대형카페", "쇼핑몰"],
}
KAKAO_CATEGORIES = list(KAKAO_CATEGORY_KEYWORDS)

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def get_living_area_population(dongs, population_path=POPULATION_PATH, mapping_path=MAPPING_PATH):
    """생활권에 포함된 행정동의 인구를 합산한다.

    dongs: get_dongs_in_circle()이 반환하는 DataFrame (ADM_CD, ADM_NM 컬럼 필요).

    반환: dict
      - total, age_0_9, age_10_14, age_30_49: 생활권 합계
      - matched_count: 인구 데이터에 매칭된 행정동 개수
      - unmatched: 매칭 안 된 행정동의 [(ADM_CD, ADM_NM), ...] 목록
        (행정구역 개편 등으로 인구 데이터에 없는 동 - 조용히 0으로 처리하지 않고 그대로 알려준다)
    """
    if dongs.empty:
        return {
            "total": 0,
            "age_0_9": 0,
            "age_10_14": 0,
            "age_30_49": 0,
            "matched_count": 0,
            "unmatched": [],
        }

    mapping = pd.read_csv(mapping_path, dtype=str)
    population = pd.read_parquet(population_path)

    merged = dongs[["ADM_CD", "ADM_NM"]].merge(
        mapping[["adm_cd", "sgis_adm_cd"]],
        left_on="ADM_CD",
        right_on="sgis_adm_cd",
        how="left",
    )

    matched = merged[merged["adm_cd"].notna()]
    unmatched = list(
        merged.loc[merged["adm_cd"].isna(), ["ADM_CD", "ADM_NM"]].itertuples(index=False, name=None)
    )

    pop_matched = population[population["adm_cd"].isin(matched["adm_cd"])]

    return {
        "total": int(pop_matched["total"].sum()),
        "age_0_9": int(pop_matched["age_0_9"].sum()),
        "age_10_14": int(pop_matched["age_10_14"].sum()),
        "age_30_49": int(pop_matched["age_30_49"].sum()),
        "matched_count": len(matched),
        "unmatched": unmatched,
    }


def get_living_area_households(dongs, households_path=HOUSEHOLDS_PATH, mapping_path=MAPPING_PATH):
    """생활권에 포함된 행정동의 세대수를 합산한다.

    인구와 같은 행안부 adm_cd 체계라 매핑 방식도 같다 (경계 ADM_CD -> adm_cd).
    가족 가구 비중은 동별 비율을 평균내지 않고 합산한 세대수로 다시 계산한다
    (동마다 세대 규모가 달라서 단순 평균은 작은 동에 과대 가중치를 준다).

    반환: dict (total_households, household_1_2, household_3_4, household_5plus,
                family_ratio, matched_count, unmatched)
    """
    empty = {
        "total_households": 0,
        "household_1_2": 0,
        "household_3_4": 0,
        "household_5plus": 0,
        "family_ratio": 0.0,
        "matched_count": 0,
        "unmatched": [],
    }
    if dongs.empty:
        return empty

    try:
        households = pd.read_parquet(households_path)
    except (FileNotFoundError, OSError):
        return empty

    mapping = pd.read_csv(mapping_path, dtype=str)
    merged = dongs[["ADM_CD", "ADM_NM"]].merge(
        mapping[["adm_cd", "sgis_adm_cd"]],
        left_on="ADM_CD",
        right_on="sgis_adm_cd",
        how="left",
    )
    matched = merged[merged["adm_cd"].notna()]
    unmatched = list(
        merged.loc[merged["adm_cd"].isna(), ["ADM_CD", "ADM_NM"]].itertuples(index=False, name=None)
    )

    subset = households[households["adm_cd"].isin(matched["adm_cd"])]
    total = int(subset["total_households"].sum())
    family = int(subset["household_3_4"].sum())

    return {
        "total_households": total,
        "household_1_2": int(subset["household_1_2"].sum()),
        "household_3_4": family,
        "household_5plus": int(subset["household_5plus"].sum()),
        "family_ratio": round(family / total * 100, 1) if total else 0.0,
        "matched_count": len(matched),
        "unmatched": unmatched,
    }


@functools.lru_cache(maxsize=1)
def get_nationwide_child_ratio(population_path=POPULATION_PATH):
    """전국 인구 중 0~9세 비중(%). 생활권 어린이 비율을 비교할 기준선으로 쓴다.

    농촌·인구소멸 지역은 이 값이 낮게 나오는데, 숫자만 보면 데이터 결함처럼
    보이기 때문에 "전국 평균 대비 얼마"로 읽히게 하려고 기준선을 함께 보여준다.
    """
    try:
        population = pd.read_parquet(population_path, columns=["total", "age_0_9"])
    except (FileNotFoundError, OSError):
        return None

    total = population["total"].sum()
    if not total:
        return None
    return float(population["age_0_9"].sum() / total * 100)


@functools.lru_cache(maxsize=1)
def get_nationwide_lower_grade_ratio(students_path=STUDENTS_PATH):
    """전국 초등학생 중 저학년(1~3학년) 비중(%). 생활권 값을 비교할 기준선으로 쓴다.

    파일을 매번 읽지 않도록 캐시한다 (갱신하면 앱 재시작이 필요하다).
    """
    try:
        students = pd.read_parquet(students_path, columns=["student_count", "student_grade_1_3"])
    except (FileNotFoundError, OSError):
        return None

    lower = students["student_grade_1_3"].dropna()
    if lower.empty:
        return None
    # 저학년 값이 있는 행(= 초등학교)만 분모로 쓴다
    elementary_total = students.loc[lower.index, "student_count"].sum()
    if not elementary_total:
        return None
    return float(lower.sum() / elementary_total * 100)


def get_facilities_in_circle(center_lat, center_lon, radius_km, schools_path=SCHOOLS_PATH):
    """생활권 원 안에 있는 학교를 학교급별로 정리해서 반환한다.

    반환: dict
      - counts: {"초등학교": N, "중학교": N, "고등학교": N}
      - students: {"초등학교": N, "중학교": N, "고등학교": N} (학교급별 학생수 합)
      - students_total: 생활권 전체 학생수
      - students_grade_1_3: 초등 저학년(1~3학년) 학생수 - 어린이 공간 수요 지표
      - matched: {"초등학교": N, ...} 학생수가 연결된 학교 수 (학교 수와 다르면 일부 누락)
      - matched_total: 학생수가 연결된 학교 수 합계
      - schools: DataFrame (school_name, school_level, lat, lon, distance_km), 거리 가까운 순 정렬
    """
    schools = pd.read_parquet(schools_path)

    distance_km = _haversine_km(center_lat, center_lon, schools["lat"].values, schools["lon"].values)
    schools = schools.assign(distance_km=distance_km)

    in_circle = schools[schools["distance_km"] <= radius_km].sort_values("distance_km").reset_index(drop=True)

    level_counts = in_circle["school_level"].value_counts()
    counts = {level: int(level_counts.get(level, 0)) for level in SCHOOL_LEVELS}

    # 학생수는 교명 매칭으로 붙인 값이라 일부 학교(폐교/분교/교명변경)는 비어 있다.
    # 합계는 비어 있는 학교를 빼고 더하고, 연결된 학교 수를 따로 알려준다.
    if "student_count" in in_circle.columns:
        by_level = in_circle.groupby("school_level")["student_count"]
        students = {level: int(by_level.sum().get(level, 0)) for level in SCHOOL_LEVELS}
        matched = {level: int(by_level.count().get(level, 0)) for level in SCHOOL_LEVELS}
        students_total = int(in_circle["student_count"].sum())
        matched_total = int(in_circle["student_count"].count())
    else:
        students = {level: 0 for level in SCHOOL_LEVELS}
        matched = dict(students)
        students_total = 0
        matched_total = 0

    if "student_grade_1_3" in in_circle.columns:
        students_grade_1_3 = int(in_circle["student_grade_1_3"].sum())
    else:
        students_grade_1_3 = 0

    return {
        "counts": counts,
        "students": students,
        "students_total": students_total,
        "students_grade_1_3": students_grade_1_3,
        "matched": matched,
        "matched_total": matched_total,
        "schools": in_circle,
    }


def get_libraries_in_circle(center_lat, center_lon, radius_km, libraries_path=LIBRARIES_PATH):
    """생활권 원 안에 있는 도서관을 그룹별(주요도서관/작은도서관/기타)로 정리해서 반환한다.

    반환: dict
      - counts: {"주요도서관": N, "작은도서관": N, "기타": N}
      - libraries: DataFrame (library_name, library_type, group, lat, lon, distance_km),
        거리 가까운 순 정렬
    """
    libraries = pd.read_parquet(libraries_path)

    distance_km = _haversine_km(center_lat, center_lon, libraries["lat"].values, libraries["lon"].values)
    libraries = libraries.assign(distance_km=distance_km)

    in_circle = (
        libraries[libraries["distance_km"] <= radius_km].sort_values("distance_km").reset_index(drop=True)
    )

    group_counts = in_circle["group"].value_counts()
    counts = {group: int(group_counts.get(group, 0)) for group in LIBRARY_GROUPS}

    return {"counts": counts, "libraries": in_circle}


def get_tourism_in_circle(center_lat, center_lon, radius_km, tourism_path=TOURISM_PATH):
    """생활권 원 안에 있는 관광지를 거리순으로 정리해서 반환한다.

    반환: dict
      - count: 개수
      - tourism: DataFrame (name, category, lat, lon, distance_km), 거리 가까운 순 정렬
    """
    tourism = pd.read_parquet(tourism_path)

    distance_km = _haversine_km(center_lat, center_lon, tourism["lat"].values, tourism["lon"].values)
    tourism = tourism.assign(distance_km=distance_km)

    in_circle = tourism[tourism["distance_km"] <= radius_km].sort_values("distance_km").reset_index(drop=True)

    return {"count": len(in_circle), "tourism": in_circle}


def get_closed_schools_in_circle(center_lat, center_lon, radius_km, closed_schools_path=CLOSED_SCHOOLS_PATH):
    """생활권 원 안에 있는 폐교를 활용현황별(미활용/대부/자체활용)로 정리해서 반환한다.

    미활용 폐교는 사업 후보지 관점에서 특히 중요하다.

    반환: dict
      - counts: {"미활용": N, "대부": N, "자체활용": N}
      - closed_schools: DataFrame (name, grade, usage_status, year, lat, lon, distance_km),
        거리 가까운 순 정렬
    """
    closed_schools = pd.read_parquet(closed_schools_path)

    distance_km = _haversine_km(
        center_lat, center_lon, closed_schools["lat"].values, closed_schools["lon"].values
    )
    closed_schools = closed_schools.assign(distance_km=distance_km)

    in_circle = (
        closed_schools[closed_schools["distance_km"] <= radius_km]
        .sort_values("distance_km")
        .reset_index(drop=True)
    )

    status_counts = in_circle["usage_status"].value_counts()
    counts = {status: int(status_counts.get(status, 0)) for status in CLOSED_SCHOOL_USAGE_STATUSES}

    return {"counts": counts, "closed_schools": in_circle}


def get_nearby_facilities_kakao(center_lat, center_lon, radius_m):
    """카카오 키워드 검색으로 기준점 주변 4개 카테고리 시설을 모아서 반환한다.

    카테고리별로 여러 키워드를 검색해서 합치고, (이름, 좌표) 기준 중복을 제거한 뒤
    카카오가 가끔 주는 반경 밖 결과를 distance 기준으로 걸러낸다.

    반환: {카테고리: {"count": N, "places": [(이름, 카테고리명, 주소, 위도, 경도, 거리), ...]}}
    각 카테고리의 places는 거리 가까운 순으로 정렬된다.
    """
    result = {}

    for category, keywords in KAKAO_CATEGORY_KEYWORDS.items():
        seen = set()
        places = []

        for keyword in keywords:
            for place in search_places_nearby(keyword, center_lat, center_lon, radius_m):
                place_name, category_name, address_name, lat, lon, distance = place

                if distance is None or distance > radius_m:
                    continue

                dedup_key = (place_name, round(lat, 6), round(lon, 6))
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                places.append(place)

        places.sort(key=lambda p: p[5])
        result[category] = {"count": len(places), "places": places}

    return result


if __name__ == "__main__":
    from analysis.living_area import get_dongs_in_circle

    center_lat, center_lon, radius_km = 36.019, 129.343, 10.0

    dongs = get_dongs_in_circle(center_lat, center_lon, radius_km)
    profile = get_living_area_population(dongs)

    print(f"포항시청 좌표({center_lat}, {center_lon}) 기준 반경 {radius_km}km 생활권 인구")
    print(f"매칭된 행정동: {profile['matched_count']} / {len(dongs)}개")
    print(f"총인구: {profile['total']:,}명")
    print(f"0~9세: {profile['age_0_9']:,}명")
    print(f"10~14세: {profile['age_10_14']:,}명")
    print(f"30~49세: {profile['age_30_49']:,}명")
    if profile["unmatched"]:
        print(f"\n인구 미매칭 행정동 {len(profile['unmatched'])}개:")
        for adm_cd, adm_nm in profile["unmatched"]:
            print(f"  {adm_cd}  {adm_nm}")

    facilities = get_facilities_in_circle(center_lat, center_lon, radius_km)
    print(f"\n생활권 학교: 초 {facilities['counts']['초등학교']}개 / "
          f"중 {facilities['counts']['중학교']}개 / 고 {facilities['counts']['고등학교']}개")
    print("\n가까운 순 10개:")
    print(facilities["schools"].head(10))

    libraries = get_libraries_in_circle(center_lat, center_lon, radius_km)
    print(f"\n생활권 도서관: 주요도서관 {libraries['counts']['주요도서관']}개 / "
          f"작은도서관 {libraries['counts']['작은도서관']}개 / 기타 {libraries['counts']['기타']}개")
    print("\n가까운 순 10개:")
    print(libraries["libraries"].head(10))

    tourism = get_tourism_in_circle(center_lat, center_lon, radius_km)
    print(f"\n생활권 관광지: {tourism['count']}개")
    print("\n가까운 순 10개:")
    print(tourism["tourism"].head(10))

    closed_schools = get_closed_schools_in_circle(center_lat, center_lon, radius_km)
    print(f"\n생활권 폐교: 미활용 {closed_schools['counts']['미활용']}개 / "
          f"대부 {closed_schools['counts']['대부']}개 / 자체활용 {closed_schools['counts']['자체활용']}개")
    print(closed_schools["closed_schools"].head(10))

    print("\n" + "=" * 40)
    print("카카오 키워드 검색 - 포항시청 반경 5000m")
    print("=" * 40)

    nearby = get_nearby_facilities_kakao(36.019, 129.343, 5000)
    for category, data in nearby.items():
        print(f"\n[{category}] {data['count']}개")
        for place_name, category_name, address_name, lat, lon, distance in data["places"][:3]:
            print(f"  - {place_name} ({category_name}) {address_name} - {distance:.0f}m")

    tourist_spot_names = [p[0] for p in nearby["관광명소"]["places"]]
    found = any("환호해맞이공원" in n for n in tourist_spot_names)
    print(f"\n환호해맞이공원 포함 여부: {found}")
