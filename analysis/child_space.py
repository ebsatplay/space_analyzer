"""어린이 공간 레퍼런스 - 생활권 시설을 어린이 공간사업 관점으로 재분류하고 밀도를 본다.

새 데이터를 받지 않고, 이미 생활권 화면이 모아 둔 시설들을 네 갈래로 다시 묶는다.
  직접 경쟁  키즈카페·실내놀이터 (카카오 실시간)
  공공 유사  어린이도서관·작은도서관·공공도서관 (공공데이터)
  체험 레퍼런스 박물관·과학관·미술관·문화센터 (카카오) + 공식 관광지 (공공데이터)
  부지 후보  미활용 폐교 (공공데이터)

밀도 판정에서 가장 조심할 것은 분모다. 어린이가 적은 지역은 "어린이 N명당 공간 1개"가
저절로 좋아 보인다 (전국 256개 시군구 중 54개가 이 패턴). 비율만 보고 "공간이 충분하다"로
읽으면 틀린다. 그래서 비율과 함께 어린이 수·공간 수의 절대 규모를 항상 같이 본다.

전국 기준선은 공공 시설로만 만든다. 키즈카페는 카카오 실시간이라 전국 집계를 낼 수 없어
(시군구마다 호출해야 함) 비교 기준에 넣으면 기준이 흔들린다.

실행(테스트): python -m analysis.child_space
"""

import functools
import sys

import pandas as pd

CHILD_SPACE_PATH = "data/processed/child_space_by_sigungu.parquet"

# 전국 분포에서 뽑은 판정 구간 (실측: Q1 389 / 중위 768 / Q3 1610 명per공간)
DENSITY_LABELS = {
    "여유": "어린이 대비 공간이 전국 상위권으로 많습니다",
    "적정": "어린이 대비 공간이 전국 중간 수준입니다",
    "부족": "어린이 대비 공간이 전국 하위권으로 적습니다",
}

# 카카오 키워드 검색은 시설의 부대시설까지 따로 등록된 것을 같이 돌려준다
# ('대가야박물관 주차장', '...(주차장 내) 전기차충전소'). 레퍼런스로 볼 공간이 아니라 뺀다.
FACILITY_NOISE_MARKERS = ("주차장", "충전소", "정류장", "매표소", "안내소", "화장실")


def _is_facility_noise(name):
    return any(marker in str(name) for marker in FACILITY_NOISE_MARKERS)


# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _read(path):
    try:
        return pd.read_parquet(path)
    except (FileNotFoundError, OSError):
        return None


@functools.lru_cache(maxsize=1)
def _load(path=CHILD_SPACE_PATH):
    return _read(path)


@functools.lru_cache(maxsize=1)
def get_nationwide_benchmarks(path=CHILD_SPACE_PATH):
    """전국 시군구 분포에서 판정 기준선을 뽑는다 (출장소 등 인구 0인 곳 제외)."""
    data = _load(path)
    if data is None or data.empty:
        return None

    real = data[data["population_total"] > 0]
    with_space = real[real["children_per_space"].notna()]
    if with_space.empty:
        return None

    return {
        "ratio_q1": float(with_space["children_per_space"].quantile(0.25)),
        "ratio_median": float(with_space["children_per_space"].median()),
        "ratio_q3": float(with_space["children_per_space"].quantile(0.75)),
        "children_q1": float(real["children_0_9"].quantile(0.25)),
        "spaces_q1": float(real["public_child_spaces"].quantile(0.25)),
        "sigungu_count": len(real),
    }


def classify_child_spaces(facilities, libraries, closed_schools, kakao_nearby, tourism_count):
    """생활권 시설을 어린이 공간 관점 네 갈래로 묶는다.

    인자는 생활권 화면이 이미 구해 둔 결과를 그대로 받는다 (추가 호출 없음).

    반환: dict - 유형별 {"count", "items", "source"}
    """
    library_rows = libraries.get("libraries")
    child_libraries, small_libraries, public_libraries = [], [], []
    if library_rows is not None and len(library_rows):
        for row in library_rows.itertuples(index=False):
            name = row.library_name
            if row.library_type == "어린이도서관" or "어린이" in str(name):
                child_libraries.append(name)
            elif row.group == "작은도서관":
                small_libraries.append(name)
            elif row.group == "주요도서관":
                public_libraries.append(name)

    kids_places = [
        place[0] for place in kakao_nearby["키즈카페"]["places"]
        if not _is_facility_noise(place[0])
    ]
    culture_places = [
        place[0] for place in kakao_nearby["문화체험"]["places"]
        if not _is_facility_noise(place[0])
    ]

    unused_rows = closed_schools.get("closed_schools")
    unused_names = []
    if unused_rows is not None and len(unused_rows):
        unused_names = unused_rows.loc[
            unused_rows["usage_status"] == "미활용", "name"
        ].tolist()

    return {
        "직접 경쟁": {
            "count": len(kids_places),
            "items": kids_places,
            "source": "카카오 장소검색 (실시간, 민간)",
            "note": "키즈카페·실내놀이터 - 같은 수요를 두고 겨루는 곳",
        },
        "공공 유사": {
            "count": len(child_libraries) + len(small_libraries) + len(public_libraries),
            "items": child_libraries + small_libraries + public_libraries,
            "child_library_count": len(child_libraries),
            "small_library_count": len(small_libraries),
            "public_library_count": len(public_libraries),
            "source": "공공데이터포털 표준데이터",
            "note": "어린이도서관·작은도서관·공공도서관 - 공공이 이미 하고 있는 것",
        },
        "체험 레퍼런스": {
            "count": len(culture_places) + tourism_count,
            "items": culture_places,
            "culture_count": len(culture_places),
            "tourism_count": tourism_count,
            "excluded_count": (
                len(kakao_nearby["문화체험"]["places"]) - len(culture_places)
            ),
            "source": "카카오 장소검색 + 공공데이터포털",
            "note": "박물관·과학관·문화센터 + 공식 관광지 - 프로그램을 참고할 곳",
        },
        "부지 후보": {
            "count": len(unused_names),
            "items": unused_names,
            "source": "공공데이터포털 (폐교재산 현황)",
            "note": "미활용 폐교 - 공간을 들일 수 있는 자리",
        },
    }


def assess_density(children_0_9, public_space_count, benchmarks=None):
    """어린이 수 대비 공공 공간 밀도를 전국 분포에 비춰 판정한다.

    반환: dict 또는 판정 불가 시 None
      - children_per_space: 공간 1개당 어린이 수 (공간이 0이면 None)
      - label: 여유 / 적정 / 부족
      - interpretation: 사업 관점 해석
      - small_demand / few_spaces: 분모·분자가 작아 비율이 왜곡될 수 있는 경우 True
      - caution: 왜곡 주의 문구 (해당될 때만)
    """
    benchmarks = benchmarks or get_nationwide_benchmarks()
    if benchmarks is None or children_0_9 is None:
        return None

    small_demand = children_0_9 <= benchmarks["children_q1"]
    few_spaces = public_space_count <= benchmarks["spaces_q1"]

    if public_space_count == 0:
        return {
            "children_per_space": None,
            "label": "부족",
            "interpretation": (
                "생활권 안에 공공 어린이 공간이 하나도 없습니다. "
                "어린이 수가 받쳐준다면 신규 진입 여지가 큽니다."
            ),
            "small_demand": small_demand,
            "few_spaces": True,
            "caution": (
                f"다만 0~9세가 {children_0_9:,}명으로 전국 하위권이라 "
                "수요 규모 자체는 작습니다."
            ) if small_demand else None,
            "benchmarks": benchmarks,
        }

    ratio = round(children_0_9 / public_space_count)

    if ratio <= benchmarks["ratio_q1"]:
        label = "여유"
        interpretation = (
            "어린이 대비 공간이 전국 상위권으로 많습니다. "
            "새로 짓기보다 기존 공간과 다른 성격으로 차별화하는 쪽이 낫습니다."
        )
    elif ratio >= benchmarks["ratio_q3"]:
        label = "부족"
        interpretation = (
            "어린이 대비 공간이 전국 하위권으로 적습니다. 신규 진입 기회가 있습니다."
        )
    else:
        label = "적정"
        interpretation = "어린이 대비 공간이 전국 중간 수준입니다."

    # 분모(어린이)가 작으면 비율이 저절로 좋아 보인다. 전국 256개 중 54개가 이 패턴이라
    # 비율만 보고 "충분하다"로 읽지 않도록 반드시 함께 알린다.
    caution = None
    if small_demand and label in ("여유", "적정"):
        caution = (
            f"0~9세가 {children_0_9:,}명으로 전국 하위 25%입니다. 비율이 좋아 보이는 것은 "
            "공간이 넉넉해서가 아니라 어린이가 적어 분모가 작기 때문입니다. "
            "수요 규모가 작다는 뜻이지 공간이 충분하다는 뜻은 아닙니다."
        )
    elif few_spaces and label in ("여유", "적정"):
        caution = (
            f"공공 공간이 {public_space_count}개뿐이라 비율이 안정적이지 않습니다 "
            "(한 곳만 늘거나 줄어도 크게 움직입니다)."
        )

    return {
        "children_per_space": ratio,
        "label": label,
        "interpretation": interpretation,
        "small_demand": small_demand,
        "few_spaces": few_spaces,
        "caution": caution,
        "benchmarks": benchmarks,
    }


def get_sigungu_child_space(sigungu_cd, path=CHILD_SPACE_PATH):
    """시군구 단위 어린이 공간 현황 (유사지역 비교용)."""
    data = _load(path)
    if data is None:
        return None
    matched = data[data["sigungu_cd"] == str(sigungu_cd)]
    if matched.empty:
        return None
    row = matched.iloc[0]
    ratio = row["children_per_space"]
    return {
        "sigungu_cd": row["sigungu_cd"],
        "sigungu_nm": row["sigungu_nm"],
        "children_0_9": int(row["children_0_9"]),
        "public_child_spaces": int(row["public_child_spaces"]),
        "child_library_count": int(row["child_library_count"]),
        "small_library_count": int(row["small_library_count"]),
        "public_library_count": int(row["public_library_count"]),
        "unused_school_count": int(row["unused_school_count"]),
        "children_per_space": None if pd.isna(ratio) else int(ratio),
    }


def compare_with_similar(sigungu_cd, similar_region_names, path=CHILD_SPACE_PATH):
    """유사 지역들과 어린이 공간 현황을 나란히 놓는다.

    similar_region_names: tourism_region의 유사지역 이름 목록 ('충청북도 보은군' 형태)

    반환: DataFrame (sigungu_nm, children_0_9, public_child_spaces, children_per_space, 구분)
    """
    data = _load(path)
    if data is None:
        return None

    names = list(similar_region_names or [])
    subset = data[
        (data["sigungu_cd"] == str(sigungu_cd)) | (data["sigungu_nm"].isin(names))
    ].copy()
    if subset.empty:
        return None

    subset["구분"] = subset["sigungu_cd"].eq(str(sigungu_cd)).map({True: "우리 지역", False: "유사 지역"})
    columns = ["구분", "sigungu_nm", "children_0_9", "public_child_spaces", "children_per_space"]
    # 우리 지역이 맨 위에 오게 정렬한다
    return subset.sort_values(["구분", "children_per_space"], ascending=[False, True])[columns]


def main():
    benchmarks = get_nationwide_benchmarks()
    if benchmarks is None:
        print(f"{CHILD_SPACE_PATH} 가 없습니다. python -m ingest.build_child_space 를 먼저 실행하세요.")
        return

    print(f"전국 {benchmarks['sigungu_count']}개 시군구 기준선")
    print(f"  공간당 어린이 수: 여유 {benchmarks['ratio_q1']:.0f}명 이하 / "
          f"중위 {benchmarks['ratio_median']:.0f}명 / 부족 {benchmarks['ratio_q3']:.0f}명 이상")
    print(f"  수요 규모가 작다고 보는 선: 0~9세 {benchmarks['children_q1']:,.0f}명 이하")
    print(f"  공간 수가 적다고 보는 선: {benchmarks['spaces_q1']:.0f}개 이하")

    for code in ("47830", "41480", "47130", "11110"):
        current = get_sigungu_child_space(code)
        if current is None:
            continue
        print(f"\n{'=' * 70}")
        print(f"  {current['sigungu_nm']} ({code})")
        print("=" * 70)
        print(f"  0~9세 {current['children_0_9']:,}명 / 공공 어린이공간 {current['public_child_spaces']}개"
              f" (어린이도서관 {current['child_library_count']} · "
              f"작은도서관 {current['small_library_count']} · 공공도서관 {current['public_library_count']})")
        print(f"  미활용 폐교(부지 후보) {current['unused_school_count']}개")

        assessment = assess_density(
            current["children_0_9"], current["public_child_spaces"], benchmarks
        )
        ratio_text = (
            f"{assessment['children_per_space']:,}명/공간"
            if assessment["children_per_space"] is not None
            else "공간 없음"
        )
        print(f"  -> [{assessment['label']}] {ratio_text}")
        print(f"     {assessment['interpretation']}")
        if assessment["caution"]:
            print(f"     ⚠️ {assessment['caution']}")


if __name__ == "__main__":
    main()
