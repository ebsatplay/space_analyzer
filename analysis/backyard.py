"""배후권(거리 기반 방문 가능권) 시군구 추출 + 인구 비교.

주의: 이건 실제 방문객 유입 데이터가 아니라, 직선거리 기준으로 "올 수 있을 만한"
지역을 추정한 것이다.

실행(테스트): python -m analysis.backyard
(다른 패키지의 living_area를 import하므로 python analysis/backyard.py로 직접 실행하면 안 됨)
"""

import sys

import geopandas as gpd
import pandas as pd

from analysis.living_area import _haversine_km
from services.kakao_service import search_places_nearby

BOUNDARIES_PATH = "data/processed/dong_boundaries.parquet"
POPULATION_PATH = "data/processed/population.parquet"
SCHOOLS_PATH = "data/processed/schools.parquet"
LIBRARIES_PATH = "data/processed/libraries.parquet"
CLOSED_SCHOOLS_PATH = "data/processed/closed_schools.parquet"
MAPPING_PATH = "data/reference/adm_cd_mapping.csv"
SIGUNGU_NAMES_PATH = "data/reference/sigungu_names.csv"

KIDS_CAFE_KEYWORDS = ["키즈카페", "실내놀이터"]
KIDS_CAFE_SEARCH_RADIUS_KM = 10  # 시군구 중심에서 키즈카페를 검색할 반경

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _sigungu_centroids(boundaries_path=BOUNDARIES_PATH):
    """경계 데이터를 시군구(SGIS 코드 앞 5자리) 단위로 묶어 대표 좌표를 계산한다.

    대표 좌표는 그 시군구에 속한 행정동들의 중심점(대표점) 평균이다.
    """
    gdf = gpd.read_parquet(boundaries_path)
    gdf = gdf.assign(group5=gdf["ADM_CD"].str[:5])

    points = gdf.geometry.representative_point()
    gdf = gdf.assign(pt_lat=points.y, pt_lon=points.x)

    return (
        gdf.groupby("group5")
        .agg(
            centroid_lat=("pt_lat", "mean"),
            centroid_lon=("pt_lon", "mean"),
            dong_count=("ADM_CD", "count"),
        )
        .reset_index()
    )


def _bnd_to_pop_group_map(mapping_path=MAPPING_PATH):
    """경계 시군구 그룹(SGIS 코드) <-> 인구 시군구코드(행안부 표준코드) 매핑을 만든다.

    STEP 4-C에서 만든 동 단위 매핑표(adm_cd_mapping.csv)를 시군구 단위로 다수결 집계해서 쓴다.
    """
    mapping = pd.read_csv(mapping_path, dtype=str)
    mapping = mapping.assign(
        bnd_group5=mapping["sgis_adm_cd"].str[:5],
        pop_group5=mapping["adm_cd"].str[:5],
    )
    return mapping.groupby("bnd_group5")["pop_group5"].agg(lambda s: s.value_counts().idxmax())


def get_backyard_sigungu(center_lat, center_lon, radius_km):
    """기준점에서 radius_km 이내에 대표 좌표가 들어오는 시군구를 거리순으로 반환한다.

    반환: DataFrame (sigungu_cd, sigungu_nm, centroid_lat, centroid_lon, distance_km)
    """
    centroids = _sigungu_centroids()
    group_map = _bnd_to_pop_group_map()
    names = pd.read_csv(SIGUNGU_NAMES_PATH, dtype=str)

    distance_km = _haversine_km(
        center_lat, center_lon, centroids["centroid_lat"].values, centroids["centroid_lon"].values
    )
    centroids = centroids.assign(distance_km=distance_km)

    in_range = centroids[centroids["distance_km"] <= radius_km].copy()
    in_range["sigungu_cd"] = in_range["group5"].map(group_map)
    in_range = in_range.dropna(subset=["sigungu_cd"])

    result = in_range.merge(names, on="sigungu_cd", how="left")
    result = result.sort_values("distance_km").reset_index(drop=True)
    return result[["sigungu_cd", "sigungu_nm", "centroid_lat", "centroid_lon", "distance_km"]]


def get_sigungu_population(sigungu_cds, population_path=POPULATION_PATH):
    """주어진 시군구코드(5자리) 목록의 인구를 population.parquet에서 시군구 단위로 합산한다.

    반환: DataFrame (sigungu_cd, total, age_0_9, age_10_14, age_30_49, child_ratio)
    """
    population = pd.read_parquet(population_path)
    population = population.assign(sigungu_cd=population["adm_cd"].str[:5])

    subset = population[population["sigungu_cd"].isin(sigungu_cds)]

    agg = (
        subset.groupby("sigungu_cd")
        .agg(
            total=("total", "sum"),
            age_0_9=("age_0_9", "sum"),
            age_10_14=("age_10_14", "sum"),
            age_30_49=("age_30_49", "sum"),
        )
        .reset_index()
    )
    agg["child_ratio"] = (agg["age_0_9"] / agg["total"] * 100).round(1)
    return agg


def _assign_sigungu_to_points(df, lat_col="lat", lon_col="lon", boundaries_path=BOUNDARIES_PATH):
    """포인트(위경도)마다 그 지점이 속한 행정동을 찾아 시군구코드(sigungu_cd)를 붙인다.

    행정동 경계 폴리곤 안에 포인트가 들어있는지로 판정한다 (공간조인).
    """
    bnd = gpd.read_parquet(boundaries_path)[["ADM_CD", "geometry"]]
    group_map = _bnd_to_pop_group_map()
    bnd = bnd.assign(bnd_group5=bnd["ADM_CD"].str[:5])
    bnd = bnd.assign(sigungu_cd=bnd["bnd_group5"].map(group_map))
    bnd = bnd.dropna(subset=["sigungu_cd"])[["sigungu_cd", "geometry"]]

    points = gpd.GeoDataFrame(
        df.copy(),
        geometry=gpd.points_from_xy(df[lon_col], df[lat_col]),
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(points, bnd, how="left", predicate="within")
    return joined.drop(columns=["geometry", "index_right"], errors="ignore")


def get_sigungu_school_counts(sigungu_cds, level="초등학교", schools_path=SCHOOLS_PATH):
    """주어진 시군구코드 목록에서 학교급(기본 초등학교) 개수를 센다.

    반환: DataFrame (sigungu_cd, elementary_count)
    """
    schools = pd.read_parquet(schools_path)
    assigned = _assign_sigungu_to_points(schools)
    subset = assigned[assigned["sigungu_cd"].isin(sigungu_cds) & (assigned["school_level"] == level)]

    counts = subset.groupby("sigungu_cd").size()
    counts = counts.reindex(sigungu_cds, fill_value=0)
    return counts.reset_index(name="elementary_count").rename(columns={"index": "sigungu_cd"})


def get_sigungu_library_counts(sigungu_cds, libraries_path=LIBRARIES_PATH):
    """주어진 시군구코드 목록에서 도서관 개수를 센다.

    반환: DataFrame (sigungu_cd, library_count)
    """
    libraries = pd.read_parquet(libraries_path)
    assigned = _assign_sigungu_to_points(libraries)
    subset = assigned[assigned["sigungu_cd"].isin(sigungu_cds)]

    counts = subset.groupby("sigungu_cd").size()
    counts = counts.reindex(sigungu_cds, fill_value=0)
    return counts.reset_index(name="library_count").rename(columns={"index": "sigungu_cd"})


def get_sigungu_unused_closed_school_counts(sigungu_cds, closed_schools_path=CLOSED_SCHOOLS_PATH):
    """주어진 시군구코드 목록에서 미활용 폐교 개수를 센다.

    반환: DataFrame (sigungu_cd, unused_closed_school_count)
    """
    closed_schools = pd.read_parquet(closed_schools_path)
    assigned = _assign_sigungu_to_points(closed_schools)
    subset = assigned[
        assigned["sigungu_cd"].isin(sigungu_cds) & (assigned["usage_status"] == "미활용")
    ]

    counts = subset.groupby("sigungu_cd").size()
    counts = counts.reindex(sigungu_cds, fill_value=0)
    return counts.reset_index(name="unused_closed_school_count").rename(columns={"index": "sigungu_cd"})


def get_sigungu_kids_cafe_counts(backyard_df):
    """배후권 시군구마다 중심 좌표에서 카카오로 키즈카페를 검색해서 개수를 센다.

    backyard_df: get_backyard_sigungu()가 반환하는 DataFrame (sigungu_cd, centroid_lat, centroid_lon 필요).
    시군구 개수만큼 카카오 API를 호출하므로 시간이 걸릴 수 있다.

    반환: DataFrame (sigungu_cd, kids_cafe_count)
    """
    rows = []
    for row in backyard_df.itertuples(index=False):
        radius_m = KIDS_CAFE_SEARCH_RADIUS_KM * 1000
        seen = set()
        count = 0
        for keyword in KIDS_CAFE_KEYWORDS:
            for place in search_places_nearby(keyword, row.centroid_lat, row.centroid_lon, radius_m):
                place_name, _category, _address, lat, lon, distance = place
                if distance is None or distance > radius_m:
                    continue
                key = (place_name, round(lat, 6), round(lon, 6))
                if key in seen:
                    continue
                seen.add(key)
                count += 1
        rows.append({"sigungu_cd": row.sigungu_cd, "kids_cafe_count": count})

    return pd.DataFrame(rows)


def get_backyard_metrics(center_lat, center_lon, radius_km, progress_callback=None):
    """배후권 시군구별 5개 지표(어린이 인구/초등학교/키즈카페/미활용폐교/도서관)를 한 번에 계산한다.

    progress_callback(label)이 주어지면 각 지표 계산 단계마다 호출한다 (진행 상황 표시용).

    반환: DataFrame (sigungu_cd, sigungu_nm, distance_km, centroid_lat, centroid_lon,
                     age_0_9, elementary_count, kids_cafe_count,
                     unused_closed_school_count, library_count)
    """
    backyard = get_backyard_sigungu(center_lat, center_lon, radius_km)
    if backyard.empty:
        return backyard

    sigungu_cds = backyard["sigungu_cd"].tolist()

    if progress_callback:
        progress_callback("어린이 인구 계산 중...")
    pop = get_sigungu_population(sigungu_cds)[["sigungu_cd", "age_0_9"]]

    if progress_callback:
        progress_callback("초등학교 집계 중...")
    schools = get_sigungu_school_counts(sigungu_cds)

    if progress_callback:
        progress_callback("도서관 집계 중...")
    libraries = get_sigungu_library_counts(sigungu_cds)

    if progress_callback:
        progress_callback("미활용 폐교 집계 중...")
    closed = get_sigungu_unused_closed_school_counts(sigungu_cds)

    if progress_callback:
        progress_callback("키즈카페 검색 중 (카카오 API, 시군구마다 호출)...")
    kids_cafe = get_sigungu_kids_cafe_counts(backyard)

    result = backyard
    for df in (pop, schools, kids_cafe, closed, libraries):
        result = result.merge(df, on="sigungu_cd", how="left")

    return result


if __name__ == "__main__":
    from analysis.living_area import calc_radius_km

    center_lat, center_lon = 36.019, 129.343
    radius_km = calc_radius_km(speed_kmh=30, minutes=60)

    print(f"포항시청 좌표({center_lat}, {center_lon}) 기준 1시간(30km/h) 배후권 반경 {radius_km:.1f}km")

    backyard = get_backyard_sigungu(center_lat, center_lon, radius_km)
    print(f"\n배후권 시군구: {len(backyard)}개")
    print(backyard)

    pop = get_sigungu_population(backyard["sigungu_cd"].tolist())
    merged = backyard.merge(pop, on="sigungu_cd", how="left")
    print("\n인구 비교:")
    print(merged[["sigungu_nm", "distance_km", "total", "age_0_9", "child_ratio", "age_30_49"]])
