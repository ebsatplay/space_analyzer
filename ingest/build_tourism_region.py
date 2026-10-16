"""한국관광 데이터랩 지역별 상세 CSV를 지역코드별로 정제해 저장하는 스크립트.

data/raw/datalab_{시군구코드}_*.csv 를 글롭으로 찾아 처리하므로, 새 지역을 추가하려면
그 코드로 된 파일 5종을 넣고 다시 실행하기만 하면 된다 (코드 수정 불필요).

파일 5종의 모양이 서로 달라서 성격별로 나눠 담는다:
  tourism_region.parquet          지역당 1행 - 지표 증감률(추세)
  tourism_region_linked.parquet   지역당 40행 - 유입/유출 연계지역
  tourism_region_similar.parquet  지역당 3행 - 유사지역

정제할 때 걸리는 것 두 가지:
1. similar_region.csv는 컬럼명이 뒤집혀 있다. '유사지역명'에 조회한 지역이(고령군이
   세 번) 들어가고, '기준지역명'에 실제 비교 대상이 들어간다 (4개 지역 모두 동일).
   컬럼명을 믿지 말고 내용 기준으로 읽는다.
2. linked_region.csv는 구분 코드에 따라 상대 지역이 어느 컬럼에 있는지가 바뀐다.
   유입(1)이면 '유입지역명'이 상대(출발지), 유출(2)이면 '유출지역명'이 상대(도착지)다.
   지역명 앞뒤에 공백이 섞여 있어 정리해야 한다.

실행: python ingest/build_tourism_region.py
"""

import glob
import os
import re
import sys

import pandas as pd

RAW_GLOB = "data/raw/datalab_*_visitor.csv"
RAW_PATH_TEMPLATE = "data/raw/datalab_{code}_{kind}.csv"
SIGUNGU_NAMES_PATH = "data/reference/sigungu_names.csv"

REGION_PATH = "data/processed/tourism_region.parquet"
LINKED_PATH = "data/processed/tourism_region_linked.parquet"
SIMILAR_PATH = "data/processed/tourism_region_similar.parquet"

# 지역 코드 폴더명에서 'nationwide' 같은 비(非)코드를 걸러내기 위한 패턴
REGION_CODE_PATTERN = re.compile(r"datalab_(\d{5})_visitor\.csv$")

# diagnosis.csv의 지표명 -> 저장 컬럼명 (전부 전년동기 대비 증감률 %)
DIAGNOSIS_METRICS = {
    "방문자유입": "visitor_growth_pct",
    "숙박방문자 비율": "lodging_growth_pct",
    "체류시간": "stay_time_growth_pct",
    "목적지 검색량": "search_growth_pct",
    "관광소비": "spending_growth_pct",
}

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def discover_region_codes(pattern=RAW_GLOB):
    """data/raw/ 에 있는 datalab_{코드}_visitor.csv 에서 지역 코드를 찾아낸다."""
    codes = []
    for path in sorted(glob.glob(pattern)):
        matched = REGION_CODE_PATTERN.search(os.path.basename(path))
        if matched:
            codes.append(matched.group(1))
    return codes


def _read_raw(code, kind):
    """지역별 원본 CSV를 읽는다 (전부 utf-8-sig). 컬럼명 앞뒤 공백도 정리한다."""
    path = RAW_PATH_TEMPLATE.format(code=code, kind=kind)
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    except FileNotFoundError:
        return None
    df.columns = [column.strip() for column in df.columns]
    return df


def _to_num(series):
    return pd.to_numeric(series.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def _clean_name(value):
    """'대구광역시 달성군 ' -> '대구광역시 달성군' (앞뒤 공백 제거, 내부 공백은 하나로)."""
    if not isinstance(value, str):
        return None
    return " ".join(value.split())


def build_region_metrics(code, sigungu_names):
    """한 지역의 지표 증감률(추세)을 1행으로 만든다.

    diagnosis가 5개 지표를 다 담고 있고, stay/visitor는 그중 일부를 중복해서 담는다.
    겹치는 값이 어긋나면 조용히 넘기지 않고 알린다 (기간이 다른 파일이 섞인 신호).

    반환: (dict, 경고 리스트) 또는 파일이 없으면 (None, [])
    """
    diagnosis = _read_raw(code, "diagnosis")
    stay = _read_raw(code, "stay")
    visitor = _read_raw(code, "visitor")
    if diagnosis is None or visitor is None:
        return None, []

    warnings = []

    metrics = dict(zip(diagnosis["지표명"].str.strip(), _to_num(diagnosis["지표 증감률"])))
    unknown = sorted(set(metrics) - set(DIAGNOSIS_METRICS))
    if unknown:
        warnings.append(f"diagnosis에 모르는 지표가 있습니다 (저장되지 않음): {unknown}")

    row = {"region_cd": code}
    for label, column in DIAGNOSIS_METRICS.items():
        row[column] = metrics.get(label)

    visitor_row = visitor.iloc[0]
    row["region_nm"] = _clean_name(visitor_row["기초지자체명"])
    row["sido_nm"] = _clean_name(visitor_row["광역지자체명"])
    row["sido_growth_pct"] = float(_to_num(visitor["광역지자체 증감률"]).iloc[0])

    # visitor의 기초 증감률은 diagnosis의 '방문자유입'과 같아야 한다
    visitor_growth = float(_to_num(visitor["기초지자체 증감률"]).iloc[0])
    if row["visitor_growth_pct"] is not None and abs(visitor_growth - row["visitor_growth_pct"]) > 0.05:
        warnings.append(
            f"visitor({visitor_growth})와 diagnosis 방문자유입({row['visitor_growth_pct']})이 다릅니다"
        )

    # stay의 두 값도 diagnosis와 같아야 한다
    if stay is not None:
        stay_row = stay.iloc[0]
        pairs = (
            ("숙박방문자 증감률", "lodging_growth_pct"),
            ("체류시간 증감률", "stay_time_growth_pct"),
        )
        for raw_column, column in pairs:
            if raw_column not in stay.columns:
                continue
            stay_value = float(_to_num(stay[raw_column]).iloc[0])
            if row[column] is not None and abs(stay_value - row[column]) > 0.05:
                warnings.append(f"stay({raw_column}={stay_value})와 diagnosis({row[column]})가 다릅니다")

    # 우리 코드 체계의 이름도 붙여둔다 (화면에서 쓰는 이름과 맞추기 위해)
    matched = sigungu_names[sigungu_names["sigungu_cd"] == code]
    row["sigungu_nm"] = matched.iloc[0]["sigungu_nm"] if len(matched) else None
    if row["sigungu_nm"] is None:
        warnings.append(f"sigungu_names.csv에 코드 {code}가 없습니다")
    elif row["region_nm"] and row["region_nm"] not in row["sigungu_nm"]:
        # 파일 안의 지역명이 코드가 가리키는 지역과 다르면 파일명을 잘못 붙였을 가능성이 높다
        warnings.append(
            f"파일 내용은 '{row['region_nm']}'인데 코드 {code}는 "
            f"'{row['sigungu_nm']}'입니다. 파일명 코드를 확인해주세요"
        )

    return row, warnings


def build_linked(code):
    """한 지역의 유입/유출 연계지역을 긴 형태로 만든다.

    유입(1)은 '유입지역명'이, 유출(2)은 '유출지역명'이 상대 지역이다.
    """
    linked = _read_raw(code, "linked_region")
    if linked is None:
        return None

    division_column = [c for c in linked.columns if c.startswith("유입/유출")]
    if not division_column:
        print(f"  {code}: linked_region에 구분 코드 컬럼이 없습니다")
        return None
    division = linked[division_column[0]].astype(str).str.strip()

    inflow = division == "1"
    counterpart = linked["유입지역명"].where(inflow, linked["유출지역명"])
    base_region = linked["유출지역명"].where(inflow, linked["유입지역명"])

    result = pd.DataFrame({
        "region_cd": code,
        "direction": inflow.map({True: "유입", False: "유출"}),
        "counterpart_nm": counterpart.map(_clean_name),
        "base_region_nm": base_region.map(_clean_name),
        "ratio": _to_num(linked[[c for c in linked.columns if "비율" in c][0]]),
    })

    # 방향별로 비율 높은 순 순위를 매긴다
    result["rank"] = (
        result.groupby("direction")["ratio"].rank(method="first", ascending=False).astype(int)
    )
    return result.sort_values(["direction", "rank"]).reset_index(drop=True)


def build_similar(code):
    """한 지역의 유사지역을 만든다.

    컬럼명이 뒤집혀 있어서 내용으로 판단한다: 한 값만 반복되는 쪽이 조회한 지역이고,
    값이 모두 다른 쪽이 실제 유사지역이다.
    """
    similar = _read_raw(code, "similar_region")
    if similar is None:
        return None

    left = similar["유사지역명"].map(_clean_name)
    right = similar["기준지역명"].map(_clean_name)
    # 반복되는 쪽 = 조회한 지역, 다양한 쪽 = 유사지역
    if left.nunique() <= right.nunique():
        base_region, peers = left, right
    else:
        base_region, peers = right, left

    return pd.DataFrame({
        "region_cd": code,
        "base_region_nm": base_region,
        "similar_region_nm": peers,
        "rank": range(1, len(peers) + 1),
    })


def save_processed(df, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_parquet(out_path, index=False)
    return out_path


def main():
    codes = discover_region_codes()
    if not codes:
        print(f"지역 파일을 찾지 못했습니다: {RAW_GLOB}")
        return

    print(f"발견한 지역 코드 {len(codes)}개: {codes}")
    sigungu_names = pd.read_csv(SIGUNGU_NAMES_PATH, dtype=str)

    rows, linked_frames, similar_frames, all_warnings = [], [], [], []
    for code in codes:
        row, warnings = build_region_metrics(code, sigungu_names)
        if row is None:
            print(f"  {code}: diagnosis 또는 visitor 파일이 없어 건너뜁니다")
            continue
        rows.append(row)
        all_warnings.extend(f"{code}: {w}" for w in warnings)

        linked = build_linked(code)
        if linked is not None:
            linked_frames.append(linked)
        similar = build_similar(code)
        if similar is not None:
            similar_frames.append(similar)

    if not rows:
        print("정제할 지역이 없습니다")
        return

    region = pd.DataFrame(rows)
    columns = [
        "region_cd", "region_nm", "sigungu_nm", "sido_nm",
        "visitor_growth_pct", "lodging_growth_pct", "stay_time_growth_pct",
        "search_growth_pct", "spending_growth_pct", "sido_growth_pct",
    ]
    region = region[columns].sort_values("region_cd").reset_index(drop=True)
    save_processed(region, REGION_PATH)

    print(f"\n저장 완료: {REGION_PATH}")
    print(f"  지역 {len(region)}개")
    print(region.to_string(index=False))

    if all_warnings:
        print("\n[확인 필요]")
        for warning in all_warnings:
            print(f"  - {warning}")

    if linked_frames:
        linked = pd.concat(linked_frames, ignore_index=True)
        save_processed(linked, LINKED_PATH)
        print(f"\n저장 완료: {LINKED_PATH}")
        print(f"  {len(linked)}행 (지역 {linked['region_cd'].nunique()}개 x 방향 2 x 상위 20)")
        for code in linked["region_cd"].unique():
            subset = linked[linked["region_cd"] == code]
            top_in = subset[(subset["direction"] == "유입") & (subset["rank"] <= 3)]
            print(f"  {code} 유입 TOP3: "
                  + ", ".join(f"{r.counterpart_nm} {r.ratio}%" for r in top_in.itertuples(index=False)))

    if similar_frames:
        similar = pd.concat(similar_frames, ignore_index=True)
        save_processed(similar, SIMILAR_PATH)
        print(f"\n저장 완료: {SIMILAR_PATH}")
        print(f"  {len(similar)}행")
        for code in similar["region_cd"].unique():
            peers = similar[similar["region_cd"] == code]["similar_region_nm"].tolist()
            print(f"  {code}: {', '.join(peers)}")


if __name__ == "__main__":
    main()
