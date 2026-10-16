"""어린이 공간 레퍼런스 - 공공 시설과 0~9세 인구로 시군구별 밀도 기준선을 만든다.

새 데이터를 받지 않고 이미 있는 것만 쓴다:
  libraries.parquet       어린이도서관 / 작은도서관 / 공공도서관
  child_centers.parquet   지역아동센터 (아동 돌봄)
  public_facilities.parquet 공공시설개방 중 프로그램 공간 (평생교육 운영 가능)
  closed_schools.parquet  미활용 폐교 (부지 후보)
  population.parquet      0~9세 인구

키즈카페는 카카오 실시간 검색이라 전국 집계를 만들 수 없다 (시군구마다 호출해야 함).
그래서 전국 비교 기준선은 공공 시설로만 만들고, 민간 경쟁(키즈카페)은 생활권 화면에서
실시간 개수로만 보여준다. 둘을 섞으면 비교 기준이 흔들린다.

실행: python -m ingest.build_child_space
(analysis.backyard를 import하므로 python ingest/build_child_space.py로 직접 실행하면 안 됨)
"""

import os
import sys

import pandas as pd

from analysis.backyard import _assign_sigungu_to_points

LIBRARIES_PATH = "data/processed/libraries.parquet"
CHILD_CENTERS_PATH = "data/processed/child_centers.parquet"
PUBLIC_FACILITIES_PATH = "data/processed/public_facilities.parquet"
CLOSED_SCHOOLS_PATH = "data/processed/closed_schools.parquet"
POPULATION_PATH = "data/processed/population.parquet"
SIGUNGU_NAMES_PATH = "data/reference/sigungu_names.csv"
OUTPUT_PATH = "data/processed/child_space_by_sigungu.parquet"

# 어린이도서관 판별: 유형이 '어린이도서관'이거나 이름에 '어린이'가 들어간 경우.
# 유형만 보면 전국 31곳뿐이지만, 이름에 '어린이'가 든 곳이 154곳이라 많이 놓친다.
CHILD_LIBRARY_TYPE = "어린이도서관"
CHILD_NAME_MARKER = "어린이"

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def classify_libraries(libraries):
    """도서관을 어린이도서관 / 작은도서관 / 공공도서관으로 나눈다.

    어린이도서관이 작은도서관과 겹칠 수 있어 어린이 판정을 먼저 한다 (중복 집계 방지).
    """
    is_child = (
        libraries["library_type"].eq(CHILD_LIBRARY_TYPE)
        | libraries["library_name"].str.contains(CHILD_NAME_MARKER, na=False)
    )
    is_small = ~is_child & libraries["group"].eq("작은도서관")
    is_public = ~is_child & ~is_small & libraries["group"].eq("주요도서관")

    return libraries.assign(
        child_library=is_child,
        small_library=is_small,
        public_library=is_public,
    )


def build_child_space(
    libraries_path=LIBRARIES_PATH,
    child_centers_path=CHILD_CENTERS_PATH,
    public_facilities_path=PUBLIC_FACILITIES_PATH,
    closed_schools_path=CLOSED_SCHOOLS_PATH,
    population_path=POPULATION_PATH,
    sigungu_names_path=SIGUNGU_NAMES_PATH,
):
    """시군구별 어린이 공공공간 수와 0~9세 인구, 그리고 공간당 어린이 수를 만든다."""
    libraries = pd.read_parquet(libraries_path)
    child_centers = pd.read_parquet(child_centers_path)
    public_facilities = pd.read_parquet(public_facilities_path)
    closed_schools = pd.read_parquet(closed_schools_path)
    population = pd.read_parquet(population_path)
    sigungu_names = pd.read_csv(sigungu_names_path, dtype=str)

    libraries = classify_libraries(libraries)
    libraries = _assign_sigungu_to_points(libraries).dropna(subset=["sigungu_cd"])
    library_counts = libraries.groupby("sigungu_cd").agg(
        child_library_count=("child_library", "sum"),
        small_library_count=("small_library", "sum"),
        public_library_count=("public_library", "sum"),
    )

    # 지역아동센터 - 아동 돌봄 공간이라 공공 어린이 공간에 포함한다
    centers = _assign_sigungu_to_points(child_centers).dropna(subset=["sigungu_cd"])
    center_counts = centers.groupby("sigungu_cd").agg(
        child_center_count=("center_name", "size"),
        child_center_capacity=("capacity", "sum"),
        child_center_enrolled=("enrolled", "sum"),
    )

    # 공공시설개방 중 프로그램 공간 - 평생교육 프로그램을 돌릴 수 있는 자리
    program_spaces = public_facilities[public_facilities["facility_group"] == "프로그램 공간"]
    program_spaces = _assign_sigungu_to_points(program_spaces).dropna(subset=["sigungu_cd"])
    program_counts = program_spaces.groupby("sigungu_cd").size().rename("program_space_count")

    unused = closed_schools[closed_schools["usage_status"] == "미활용"]
    unused = _assign_sigungu_to_points(unused).dropna(subset=["sigungu_cd"])
    unused_counts = unused.groupby("sigungu_cd").size().rename("unused_school_count")

    # 인구는 읍면동 단위라 시군구(코드 앞 5자리)로 합친다
    population = population.assign(sigungu_cd=population["adm_cd"].str[:5])
    child_population = population.groupby("sigungu_cd").agg(
        children_0_9=("age_0_9", "sum"),
        population_total=("total", "sum"),
    )

    result = (
        sigungu_names.set_index("sigungu_cd")
        .join(library_counts)
        .join(center_counts)
        .join(program_counts)
        .join(unused_counts)
        .join(child_population)
        .reset_index()
    )

    count_columns = [
        "child_library_count", "small_library_count",
        "public_library_count", "child_center_count",
        "child_center_capacity", "child_center_enrolled",
        "program_space_count", "unused_school_count",
    ]
    for column in count_columns:
        result[column] = result[column].fillna(0).astype(int)
    result["children_0_9"] = result["children_0_9"].fillna(0).astype(int)
    result["population_total"] = result["population_total"].fillna(0).astype(int)

    # 도서관만으로 센 값도 남긴다. 지역아동센터 데이터는 지자체가 제출한 곳만 들어 있어서
    # (제공기관 124곳 / 229개 시군구 중 109곳이 0개) 전국 비교의 공정한 분모가 못 된다.
    # 구미시는 어린이가 26,151명인데 센터가 0개로 나오는데, 없는 게 아니라 미제출이다.
    result["library_spaces"] = (
        result["child_library_count"]
        + result["small_library_count"]
        + result["public_library_count"]
    )

    # 공공 돌봄·교육 공간 = 도서관 + 지역아동센터
    # (작은도서관까지 넣는 이유: 생활밀착형이라 실제로 아이들이 쓰는 공간이기 때문.
    #  지역아동센터는 방과후 돌봄 공간이라 어린이 수요를 직접 받는다)
    result["public_child_spaces"] = result["library_spaces"] + result["child_center_count"]

    # 센터가 0개인 곳은 "없다"와 "제출을 안 했다"를 구분할 수 없다. 화면에서 밀도를
    # 해석할 때 이 플래그를 보고 과소집계 가능성을 알린다.
    result["child_center_reported"] = result["child_center_count"] > 0

    # 공간당 어린이 수 - 공간이 0이면 나눌 수 없으므로 비운다 (0으로 두면 '아주 여유'로 오독된다)
    # NaN(float)으로 두어야 round가 동작한다 (pd.NA는 round를 지원하지 않는다)
    spaces = result["public_child_spaces"].replace(0, float("nan"))
    result["children_per_space"] = (result["children_0_9"] / spaces).round(0)

    # 전국 비교용 - 도서관만 기준 (모든 시군구가 같은 조건)
    library_spaces = result["library_spaces"].replace(0, float("nan"))
    result["children_per_library_space"] = (result["children_0_9"] / library_spaces).round(0)

    columns = [
        "sigungu_cd", "sigungu_nm", "children_0_9", "population_total",
        "public_child_spaces", "library_spaces",
        "child_library_count", "small_library_count",
        "public_library_count", "child_center_count", "child_center_capacity",
        "child_center_enrolled", "child_center_reported",
        "program_space_count", "unused_school_count",
        "children_per_space", "children_per_library_space",
    ]
    return result[columns].sort_values("sigungu_cd").reset_index(drop=True)


def save_processed(df, out_path=OUTPUT_PATH):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_parquet(out_path, index=False)
    return out_path


def main():
    result = build_child_space()
    out_path = save_processed(result)

    print(f"저장 완료: {out_path}")
    print(f"  시군구 {len(result)}개")

    print("\n전국 합계:")
    print(f"  0~9세 인구 {result['children_0_9'].sum():,}명")
    print(f"  공공 돌봄·교육 공간 {result['public_child_spaces'].sum():,}개 "
          f"(어린이도서관 {result['child_library_count'].sum()} / "
          f"작은도서관 {result['small_library_count'].sum()} / "
          f"공공도서관 {result['public_library_count'].sum()} / "
          f"지역아동센터 {result['child_center_count'].sum()})")
    print(f"  지역아동센터 정원 {result['child_center_capacity'].sum():,}명 / "
          f"현원 {result['child_center_enrolled'].sum():,}명")
    print(f"  프로그램 운영 공간 {result['program_space_count'].sum():,}개")
    real = result[result["population_total"] > 0]
    print(f"  지역아동센터 데이터가 있는 시군구 {int(real['child_center_reported'].sum())}"
          f"/{len(real)}개 (나머지는 미제출 또는 없음 - 구분 불가)")
    print(f"  미활용 폐교 {result['unused_school_count'].sum():,}개")

    valid = result[result["children_per_space"].notna()]
    print("\n공간당 어린이 수 분포 (명/공간):")
    print(valid["children_per_space"].describe(percentiles=[.25, .5, .75]).round(0).to_string())

    print("\n공간이 0개인 시군구: "
          f"{int((result['public_child_spaces'] == 0).sum())}개")
    print(f"어린이가 0명인 시군구: {int((result['children_0_9'] == 0).sum())}개 (출장소 등)")

    for code in ("47830", "41480", "47130", "11110"):
        row = result[result["sigungu_cd"] == code]
        if len(row):
            r = row.iloc[0]
            ratio = r["children_per_space"]
            ratio_text = f"{ratio:,.0f}명/공간" if pd.notna(ratio) else "공간 없음"
            print(f"  {code} {r['sigungu_nm']}: 0~9세 {r['children_0_9']:,}명 / "
                  f"공공공간 {r['public_child_spaces']}개 -> {ratio_text} "
                  f"(미활용 폐교 {r['unused_school_count']}개)")


if __name__ == "__main__":
    main()
