"""어린이 공간 레퍼런스 - 공공 시설과 0~9세 인구로 시군구별 밀도 기준선을 만든다.

새 데이터를 받지 않고 이미 있는 것만 쓴다:
  libraries.parquet     어린이도서관 / 작은도서관 / 공공도서관
  closed_schools.parquet 미활용 폐교 (부지 후보)
  population.parquet    0~9세 인구

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
    closed_schools_path=CLOSED_SCHOOLS_PATH,
    population_path=POPULATION_PATH,
    sigungu_names_path=SIGUNGU_NAMES_PATH,
):
    """시군구별 어린이 공공공간 수와 0~9세 인구, 그리고 공간당 어린이 수를 만든다."""
    libraries = pd.read_parquet(libraries_path)
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
        .join(unused_counts)
        .join(child_population)
        .reset_index()
    )

    count_columns = [
        "child_library_count", "small_library_count",
        "public_library_count", "unused_school_count",
    ]
    for column in count_columns:
        result[column] = result[column].fillna(0).astype(int)
    result["children_0_9"] = result["children_0_9"].fillna(0).astype(int)
    result["population_total"] = result["population_total"].fillna(0).astype(int)

    # 공공 어린이 공간 = 어린이도서관 + 작은도서관 + 공공도서관
    # (작은도서관까지 넣는 이유: 생활밀착형이라 실제로 아이들이 쓰는 공간이기 때문)
    result["public_child_spaces"] = (
        result["child_library_count"] + result["small_library_count"] + result["public_library_count"]
    )

    # 공간당 어린이 수 - 공간이 0이면 나눌 수 없으므로 비운다 (0으로 두면 '아주 여유'로 오독된다)
    # NaN(float)으로 두어야 round가 동작한다 (pd.NA는 round를 지원하지 않는다)
    spaces = result["public_child_spaces"].replace(0, float("nan"))
    result["children_per_space"] = (result["children_0_9"] / spaces).round(0)

    columns = [
        "sigungu_cd", "sigungu_nm", "children_0_9", "population_total",
        "public_child_spaces", "child_library_count", "small_library_count",
        "public_library_count", "unused_school_count", "children_per_space",
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
    print(f"  공공 어린이 공간 {result['public_child_spaces'].sum():,}개 "
          f"(어린이도서관 {result['child_library_count'].sum()} / "
          f"작은도서관 {result['small_library_count'].sum()} / "
          f"공공도서관 {result['public_library_count'].sum()})")
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
