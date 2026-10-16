"""지역아동센터·문화여가시설·공공시설개방 3종을 정제해서 저장하는 1회성 스크립트.

어린이·가족 공간 레퍼런스에 쓸 돌봄/여가/프로그램 공간 데이터다.
세 파일 모두 cp949이고 위경도를 직접 담고 있어 좌표 변환은 필요 없다.

정제하면서 걸리는 것 세 가지:
1. 지역아동센터의 현원수에 엑셀 날짜 일련번호가 섞여 들어왔다 (45,856 같은 값 3건).
   전국 정원 최대가 49명이라 60을 넘으면 값이 깨진 것으로 보고 비운다.
2. 문화여가시설은 같은 시설이 여러 번 들어 있다 (와이파이·주차장 여부만 다른 행).
   시설명+좌표 기준으로 중복을 없앤다 (24,537행 중 9,983행이 중복).
3. 공공시설개방의 유형 구분이 '회의실+강의실', '기타(대강당)'처럼 복합·자유 기술이다.
   정확히 일치시키는 대신 포함 문자열로 분류한다.

실행: python ingest/build_community_facilities.py
"""

import os
import re
import sys

import pandas as pd

CHILD_CENTER_RAW = "data/raw/child_center.csv"
CULTURE_RAW = "data/raw/culture_activity.csv"
PUBLIC_FACILITY_RAW = "data/raw/public_facility.csv"

CHILD_CENTER_PATH = "data/processed/child_centers.parquet"
CULTURE_PATH = "data/processed/culture_activity.parquet"
PUBLIC_FACILITY_PATH = "data/processed/public_facilities.parquet"

# 한국 영역 밖 좌표를 걸러내기 위한 범위
LAT_RANGE = (33.0, 39.0)
LON_RANGE = (124.0, 132.0)

# 지역아동센터 현원수 상한 (전국 정원 최대가 49명이라 이보다 크게 넘으면 값이 깨진 것)
MAX_PLAUSIBLE_ENROLLED = 60

# 공공시설개방 유형 분류 - 체육을 먼저 본다.
# '기타(다목적체육관)'처럼 '다목적'과 '체육관'이 같이 들어간 값이 있어서,
# 프로그램 공간을 먼저 보면 체육시설이 프로그램 공간으로 잘못 들어간다.
SPORTS_MARKERS = (
    "체육", "경기장", "구장", "수영장", "골프", "테니스", "축구", "농구",
    "배드민턴", "배드맨턴", "족구", "풋살", "야구", "헬스", "탁구", "배구",
    "스쿼시", "볼링", "당구", "씨름", "국궁", "론볼", "게이트볼", "운동장", "체조",
)
# 평생교육 프로그램을 돌릴 수 있는 실내 공간
PROGRAM_MARKERS = (
    "강의실", "강당", "다목적실", "회의실", "전시실", "세미나", "공연장",
    "소극장", "영화관", "동아리", "레크레이션", "교육장", "사랑방", "공유공간",
)

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _read_raw(path):
    try:
        return pd.read_csv(path, encoding="cp949", dtype=str)
    except FileNotFoundError:
        print(f"파일을 찾을 수 없습니다: {path}")
        return None


def _valid_coords(df, lat_column="위도", lon_column="경도"):
    """좌표를 숫자로 바꾸고 한국 영역 안에 있는 행만 남긴다."""
    lat = pd.to_numeric(df[lat_column], errors="coerce")
    lon = pd.to_numeric(df[lon_column], errors="coerce")
    keep = lat.between(*LAT_RANGE) & lon.between(*LON_RANGE)
    return df[keep].assign(lat=lat[keep], lon=lon[keep]), int((~keep).sum())


def classify_public_facility(facility_type):
    """개방시설 유형을 프로그램 공간 / 체육 / 기타로 나눈다."""
    text = str(facility_type or "")
    if any(marker in text for marker in SPORTS_MARKERS):
        return "체육"
    if any(marker in text for marker in PROGRAM_MARKERS):
        return "프로그램 공간"
    return "기타"


def build_child_centers(raw_path=CHILD_CENTER_RAW):
    """지역아동센터: 좌표 + 정원·현원 (아동 돌봄 수용 규모)."""
    raw = _read_raw(raw_path)
    if raw is None:
        return None, {}

    cleaned, dropped_coords = _valid_coords(raw)

    capacity = pd.to_numeric(cleaned["정원수"], errors="coerce")
    enrolled = pd.to_numeric(cleaned["현원수"], errors="coerce")

    # 깨진 현원수(엑셀 날짜 일련번호)를 비운다
    broken = enrolled > MAX_PLAUSIBLE_ENROLLED
    enrolled = enrolled.where(~broken)

    result = pd.DataFrame({
        "center_name": cleaned["센터명"].str.strip(),
        "sido_nm": cleaned["시도명"].str.strip(),
        "sigungu_nm": cleaned["시군구명"].str.strip(),
        "address": cleaned["소재지도로명주소"].fillna(cleaned["소재지지번주소"]).str.strip(),
        "lat": cleaned["lat"],
        "lon": cleaned["lon"],
        "capacity": capacity.astype("Int64"),
        "enrolled": enrolled.astype("Int64"),
        "operator_type": cleaned["운영기관유형"].str.strip(),
    }).reset_index(drop=True)

    stats = {
        "원본": len(raw),
        "좌표무효 제외": dropped_coords,
        "현원수 깨짐 비움": int(broken.sum()),
        "최종": len(result),
    }
    return result, stats


def build_culture_activity(raw_path=CULTURE_RAW):
    """문화여가시설: 중복을 없애고 카테고리로 분류 (가족 여가)."""
    raw = _read_raw(raw_path)
    if raw is None:
        return None, {}

    cleaned, dropped_coords = _valid_coords(raw)

    # 와이파이·주차장 여부만 다른 중복 행이 많아 시설명+좌표로 하나만 남긴다
    before = len(cleaned)
    cleaned = cleaned.drop_duplicates(subset=["시설명", "위도", "경도"], keep="first")

    result = pd.DataFrame({
        "facility_name": cleaned["시설명"].str.strip(),
        "category1": cleaned["카테고리1"].str.strip(),
        "category2": cleaned["카테고리2"].str.strip(),
        "category3": cleaned["카테고리3"].str.strip(),
        "sido_nm": cleaned["시도 명칭"].str.strip(),
        "sigungu_nm": cleaned["시군구 명칭"].str.strip(),
        "address": cleaned["도로명주소"].fillna(cleaned["지번주소"]).str.strip(),
        "lat": cleaned["lat"],
        "lon": cleaned["lon"],
    }).reset_index(drop=True)

    stats = {
        "원본": len(raw),
        "좌표무효 제외": dropped_coords,
        "중복 제외": before - len(cleaned),
        "최종": len(result),
    }
    return result, stats


def build_public_facilities(raw_path=PUBLIC_FACILITY_RAW):
    """공공시설개방: 유형별로 프로그램 공간 / 체육 / 기타로 나눈다."""
    raw = _read_raw(raw_path)
    if raw is None:
        return None, {}

    cleaned, dropped_coords = _valid_coords(raw)

    facility_type = cleaned["개방시설유형구분"].fillna("").str.strip()
    result = pd.DataFrame({
        "facility_name": cleaned["개방시설명"].str.strip(),
        "place_name": cleaned["개방장소명"].str.strip(),
        "facility_type": facility_type,
        "facility_group": facility_type.map(classify_public_facility),
        # 소수로 들어온 값이 하나 있어(125.03) 반올림한 뒤 정수로 바꾼다
        "capacity": pd.to_numeric(cleaned["수용가능인원수"], errors="coerce")
        .round()
        .astype("Int64"),
        "area": pd.to_numeric(cleaned["면적"], errors="coerce"),
        "paid": cleaned["유료사용여부"].str.strip(),
        "address": cleaned["소재지도로명주소"].fillna(cleaned["소재지지번주소"]).str.strip(),
        "manager": cleaned["관리기관명"].str.strip(),
        "lat": cleaned["lat"],
        "lon": cleaned["lon"],
    }).reset_index(drop=True)

    stats = {
        "원본": len(raw),
        "좌표무효 제외": dropped_coords,
        "최종": len(result),
    }
    return result, stats


def save_processed(df, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_parquet(out_path, index=False)
    return out_path


def main():
    print("## 1. 지역아동센터")
    centers, stats = build_child_centers()
    if centers is not None:
        save_processed(centers, CHILD_CENTER_PATH)
        print(f"저장 완료: {CHILD_CENTER_PATH}")
        print(f"  {stats}")
        print(f"  정원 합계 {int(centers['capacity'].sum()):,}명 / "
              f"현원 합계 {int(centers['enrolled'].sum()):,}명")
        print(f"  정원 결측 {int(centers['capacity'].isna().sum())}개 / "
              f"현원 결측 {int(centers['enrolled'].isna().sum())}개")
        print(centers.head(3).to_string(index=False))

    print("\n## 2. 문화여가시설")
    culture, stats = build_culture_activity()
    if culture is not None:
        save_processed(culture, CULTURE_PATH)
        print(f"저장 완료: {CULTURE_PATH}")
        print(f"  {stats}")
        print(f"  카테고리2 분포: {culture['category2'].value_counts().to_dict()}")
        print(culture.head(3).to_string(index=False))

    print("\n## 3. 공공시설개방")
    facilities, stats = build_public_facilities()
    if facilities is not None:
        save_processed(facilities, PUBLIC_FACILITY_PATH)
        print(f"저장 완료: {PUBLIC_FACILITY_PATH}")
        print(f"  {stats}")
        print(f"  분류: {facilities['facility_group'].value_counts().to_dict()}")
        print("\n  프로그램 공간 유형 상위 10:")
        program = facilities[facilities["facility_group"] == "프로그램 공간"]
        print(program["facility_type"].value_counts().head(10).to_string())
        print("\n  기타로 남은 유형 상위 10 (분류 보완 여지 확인):")
        others = facilities[facilities["facility_group"] == "기타"]
        print(others["facility_type"].value_counts().head(10).to_string())


if __name__ == "__main__":
    main()
