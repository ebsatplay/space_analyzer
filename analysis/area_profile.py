"""생활권(원 안 행정동)에 인구 지표를 붙여서 합산한다.

실행(테스트): python -m analysis.area_profile
(다른 패키지의 living_area를 import하므로 python analysis/area_profile.py로 직접 실행하면 안 됨)
"""

import sys

import pandas as pd

from analysis.living_area import _haversine_km
from services.kakao_service import search_places_nearby

POPULATION_PATH = "data/processed/population.parquet"
MAPPING_PATH = "data/reference/adm_cd_mapping.csv"
SCHOOLS_PATH = "data/processed/schools.parquet"
SCHOOL_LEVELS = ["초등학교", "중학교", "고등학교"]

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


def get_facilities_in_circle(center_lat, center_lon, radius_km, schools_path=SCHOOLS_PATH):
    """생활권 원 안에 있는 학교를 학교급별로 정리해서 반환한다.

    반환: dict
      - counts: {"초등학교": N, "중학교": N, "고등학교": N}
      - schools: DataFrame (school_name, school_level, lat, lon, distance_km), 거리 가까운 순 정렬
    """
    schools = pd.read_parquet(schools_path)

    distance_km = _haversine_km(center_lat, center_lon, schools["lat"].values, schools["lon"].values)
    schools = schools.assign(distance_km=distance_km)

    in_circle = schools[schools["distance_km"] <= radius_km].sort_values("distance_km").reset_index(drop=True)

    level_counts = in_circle["school_level"].value_counts()
    counts = {level: int(level_counts.get(level, 0)) for level in SCHOOL_LEVELS}

    return {"counts": counts, "schools": in_circle}


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
