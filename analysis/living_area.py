"""생활권(N분 거리) 반경 계산."""

import functools
import sys

import geopandas as gpd
import numpy as np

BOUNDARIES_PATH = "data/processed/dong_boundaries.parquet"
EARTH_RADIUS_KM = 6371.0088

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def _load_boundaries(boundaries_path):
    """행정동 경계 parquet을 읽는다. 같은 경로에 대해서는 캐시된 결과를 재사용한다."""
    return gpd.read_parquet(boundaries_path)


def calc_radius_km(speed_kmh, minutes):
    """평균속도(km/h)와 이동시간(분)으로 직선거리 기준 반경(km)을 계산한다."""
    return speed_kmh * (minutes / 60)


def _haversine_km(lat1, lon1, lat2, lon2):
    """두 위경도 지점 사이의 직선거리(km)를 하버사인 공식으로 계산한다."""
    lat1_rad, lon1_rad = np.radians(lat1), np.radians(lon1)
    lat2_rad, lon2_rad = np.radians(lat2), np.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2) ** 2
    return EARTH_RADIUS_KM * 2 * np.arcsin(np.sqrt(a))


def get_dongs_in_circle(center_lat, center_lon, radius_km, boundaries_path=BOUNDARIES_PATH):
    """기준점에서 radius_km 이내에 대표점이 있는 행정동을 골라낸다.

    반환: ADM_CD, ADM_NM, distance_km 컬럼을 가진 DataFrame (거리 가까운 순 정렬).
    """
    gdf = _load_boundaries(boundaries_path)
    centers = gdf.geometry.representative_point()

    distance_km = _haversine_km(center_lat, center_lon, centers.y.values, centers.x.values)

    result = gdf[["ADM_CD", "ADM_NM"]].copy()
    result["distance_km"] = distance_km
    result = result[result["distance_km"] <= radius_km]
    return result.sort_values("distance_km").reset_index(drop=True)


def get_dong_geometries(adm_cds, boundaries_path=BOUNDARIES_PATH):
    """주어진 ADM_CD 목록에 해당하는 행정동의 경계(geometry)를 반환한다."""
    gdf = _load_boundaries(boundaries_path)
    return gdf[gdf["ADM_CD"].isin(adm_cds)][["ADM_CD", "ADM_NM", "geometry"]]


if __name__ == "__main__":
    center_lat, center_lon, radius_km = 36.019, 129.343, 6.5

    dongs = get_dongs_in_circle(center_lat, center_lon, radius_km)
    print(f"포항시청 좌표({center_lat}, {center_lon}) 기준 반경 {radius_km}km 이내 행정동: {len(dongs)}개")
    print(dongs)
