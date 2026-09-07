"""통계청 공식 행정동 경계 shapefile을 읽어서 앱에서 쓸 형태로 준비하는 1회성 스크립트.

원본(EPSG:5179, 131MB)을 EPSG:4326으로 변환하고 geometry를 단순화해서
data/processed/ 에 GeoParquet으로 저장한다. (pyarrow가 이미 설치되어 있어
추가 의존성 없이 쓸 수 있고, gpkg보다 용량이 작고 읽기도 빠르다)

실행: python ingest/build_boundaries.py
"""

import os
import sys

import geopandas as gpd

SHP_PATH = "data/raw/bnd_dong_00_2025_2Q.shp"
PROCESSED_PATH = "data/processed/dong_boundaries.parquet"
SIMPLIFY_TOLERANCE_DEG = 0.0001  # 약 11m, EPSG:4326 기준

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_boundaries(shp_path=SHP_PATH):
    """원본 shapefile을 읽는다. 실패 시 None을 반환한다."""
    try:
        return gpd.read_file(shp_path)
    except FileNotFoundError:
        print(f"파일을 찾을 수 없습니다: {shp_path}")
        return None
    except Exception as e:
        print(f"shapefile을 읽는 중 오류가 발생했습니다: {e}")
        return None


def save_processed(gdf, out_path=PROCESSED_PATH):
    """EPSG:4326으로 변환 + geometry 단순화 후 GeoParquet으로 저장한다."""
    gdf_4326 = gdf.to_crs(epsg=4326)
    gdf_4326["geometry"] = gdf_4326["geometry"].simplify(
        SIMPLIFY_TOLERANCE_DEG, preserve_topology=True
    )

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    gdf_4326.to_parquet(out_path)
    return out_path


def main():
    gdf = load_boundaries()
    if gdf is None:
        return

    print(f"(1) 전체 행정동 개수: {len(gdf)}개")

    print("\n(2) 컬럼 목록:")
    print(gdf.columns.tolist())

    print("\n(3) 상위 5개 행 (속성만):")
    print(gdf.drop(columns="geometry").head())

    print(f"\n(4) 현재 좌표계(CRS): {gdf.crs}")

    print("\n(5) EPSG:4326 변환 + 단순화 후 저장 중...")
    out_path = save_processed(gdf)

    original_mb = os.path.getsize(SHP_PATH) / (1024 * 1024)
    saved_mb = os.path.getsize(out_path) / (1024 * 1024)
    print(f"저장 완료: {out_path}")
    print(f"원본 .shp: {original_mb:.1f}MB -> 저장된 .parquet: {saved_mb:.1f}MB")


if __name__ == "__main__":
    main()
