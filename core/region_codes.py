"""인구 데이터(행안부 adm_cd, 10자리)와 경계 데이터(통계청 SGIS ADM_CD, 8자리)를
행정동 이름 기준으로 연결하는 매핑 로직.

배경: 두 코드 체계는 숫자로 변환 가능한 규칙이 없다 (STEP 4-C 사전분석 결과).
게다가 경계 데이터에는 시도/시군구 이름 컬럼 자체가 없고, 두 데이터의 시도 코드
번호 체계도 서로 다르다 (예: 인구 데이터는 광주+전남이 "전남광주통합특별시"로
합쳐져 있지만 경계 데이터는 그 이전 기준이라 따로 있음).

그래서 이름만으로, 시도 구분 없이 전국 단위로 다음 2단계를 거쳐 매칭한다:
1. 시군구 그룹 매칭: 각 데이터의 코드 앞 5자리(시도+시군구 그룹, 서로 다른 체계)별로
   정규화된 동 이름 집합을 만들고, 전국에서 그 집합이 가장 많이 겹치는 그룹끼리
   같은 시군구로 판단한다. (동명이인 방지 - "중앙동" 같은 이름이 여러 시군구에 있어도
   그 시군구에 속한 다른 동 이름들까지 함께 비교하기 때문에 엉뚱한 지역과 매칭되지 않는다)
2. 동 이름 매칭: 매칭된 시군구 그룹 안에서 정규화된 동 이름으로 최종 adm_cd <-> ADM_CD를 연결한다.
"""

import os
import re
import sys

import geopandas as gpd
import pandas as pd

POPULATION_PATH = "data/processed/population.parquet"
BOUNDARIES_PATH = "data/processed/dong_boundaries.parquet"
OUTPUT_PATH = "data/reference/adm_cd_mapping.csv"

MIN_GROUP_OVERLAP = 1  # 시군구 그룹으로 인정할 최소 동 이름 겹침 개수

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _normalize_common(name):
    """양쪽 데이터 공통 정규화: 앞뒤 공백 제거, 동 번호 구분자('·', '.') 제거.

    '종로1·2·3·4가동'(경계) vs '종로1.2.3.4가동'(인구), '탑·대성동'(경계) vs
    '탑대성동'(인구, 구분자 없음)처럼 구분자 표기 자체가 있다없다/문자가 다르므로
    아예 제거하고 비교한다.
    """
    return name.strip().replace("·", "").replace(".", "")


def normalize_population_adm_nm(name):
    """인구 데이터 전용: '제N동'의 '제'(서수 표기)를 제거한다 (예: '묵제1동'->'묵1동').

    행안부 인구 데이터는 동 이름과 무관하게 항상 '제'를 서수 마커로 붙인다
    (홍제동/거제동처럼 지명 자체가 '제'로 끝나도 '홍제제1동'처럼 '제'가 하나 더 붙는다).
    반면 경계 데이터는 이 마커를 아예 쓰지 않으므로('홍제1동'), 경계 쪽에 같은 규칙을
    적용하면 지명의 일부인 '제'까지 잘못 지워진다 ('홍제1동' -> '홍1동'). 그래서 이
    stripping은 인구 데이터에만 적용한다.
    """
    name = re.sub(r"제(\d)", r"\1", name)
    return _normalize_common(name)


def normalize_boundary_adm_nm(name):
    """경계 데이터 전용 정규화 (공통 정규화만 적용, '제' stripping 없음)."""
    return _normalize_common(name)


def _load_population():
    """인구 데이터를 읽고 출장소를 제외한다."""
    pop = pd.read_parquet(POPULATION_PATH)[["adm_cd", "adm_nm"]]
    pop = pop[~pop["adm_nm"].str.contains("출장소")].reset_index(drop=True)
    pop["norm"] = pop["adm_nm"].map(normalize_population_adm_nm)
    pop["group5"] = pop["adm_cd"].str[:5]
    return pop


def _load_boundaries():
    """경계 데이터를 읽는다."""
    bnd = gpd.read_parquet(BOUNDARIES_PATH)[["ADM_CD", "ADM_NM"]]
    bnd["norm"] = bnd["ADM_NM"].map(normalize_boundary_adm_nm)
    bnd["group5"] = bnd["ADM_CD"].str[:5]
    return bnd


def _match_sigungu_groups(pop, bnd):
    """동 이름 집합이 가장 많이 겹치는 조합으로 시군구 그룹을 짝짓는다.

    반환: (pop_group5 -> bnd_group5 매핑 dict, [(pop_group5, bnd_group5, overlap개수), ...] 약한 매칭 목록)
    """
    pop_groups = pop.groupby("group5")["norm"].apply(set)
    bnd_groups = bnd.groupby("group5")["norm"].apply(set)

    group_map = {}
    weak_matches = []
    for pop_g5, pop_names in pop_groups.items():
        bnd_g5, overlap = max(
            ((g, len(names & pop_names)) for g, names in bnd_groups.items()),
            key=lambda pair: pair[1],
        )
        if overlap < MIN_GROUP_OVERLAP:
            continue
        group_map[pop_g5] = bnd_g5
        if overlap < 3:
            weak_matches.append((pop_g5, bnd_g5, overlap))

    return group_map, weak_matches


def build_mapping():
    """adm_cd <-> ADM_CD 매핑 결과와 검증 정보를 담은 dict를 반환한다."""
    pop = _load_population()
    bnd = _load_boundaries()

    group_map, weak_group_matches = _match_sigungu_groups(pop, bnd)

    pop["bnd_group5"] = pop["group5"].map(group_map)
    bnd_renamed = bnd.rename(columns={"group5": "bnd_group5"})

    merged = pop.merge(bnd_renamed, on=["bnd_group5", "norm"], how="left")

    matched = merged[merged["ADM_CD"].notna()].copy()
    unmatched_pop = merged[merged["ADM_CD"].isna()][["adm_cd", "adm_nm"]]

    matched_adm_cds = set(matched["ADM_CD"])
    unmatched_bnd = bnd[~bnd["ADM_CD"].isin(matched_adm_cds)][["ADM_CD", "ADM_NM"]]

    mapping = matched[["adm_cd", "adm_nm", "ADM_CD", "ADM_NM"]].rename(
        columns={"ADM_CD": "sgis_adm_cd", "ADM_NM": "sgis_adm_nm"}
    )

    return {
        "mapping": mapping.reset_index(drop=True),
        "unmatched_population": unmatched_pop.reset_index(drop=True),
        "unmatched_boundaries": unmatched_bnd.reset_index(drop=True),
        "weak_group_matches": weak_group_matches,
        "population_row_count": len(pop),
    }


def save_mapping(mapping, out_path=OUTPUT_PATH):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    mapping.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out_path


if __name__ == "__main__":
    result = build_mapping()
    mapping = result["mapping"]
    unmatched_pop = result["unmatched_population"]
    unmatched_bnd = result["unmatched_boundaries"]
    total = result["population_row_count"]

    match_rate = len(mapping) / total * 100

    print(f"매칭 성공: {len(mapping)} / {total} ({match_rate:.1f}%)")

    if result["weak_group_matches"]:
        print(f"\n약한 시군구 그룹 매칭 (동 이름 겹침 3개 미만) {len(result['weak_group_matches'])}건:")
        for pop_g5, bnd_g5, overlap in result["weak_group_matches"]:
            print(f"  인구그룹 {pop_g5} <-> 경계그룹 {bnd_g5} (겹침 {overlap}개)")

    print(f"\n미매칭 - 인구 쪽 ({len(unmatched_pop)}개):")
    for _, row in unmatched_pop.iterrows():
        print(f"  {row['adm_cd']}  {row['adm_nm']}")

    print(f"\n미매칭 - 경계 쪽 ({len(unmatched_bnd)}개):")
    for _, row in unmatched_bnd.iterrows():
        print(f"  {row['ADM_CD']}  {row['ADM_NM']}")

    out_path = save_mapping(mapping)
    print(f"\n매핑표 저장 완료: {out_path}")
