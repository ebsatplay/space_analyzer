"""행안부 읍면동 인구 CSV를 정제해서 생활권 분석용 인구 지표로 저장하는 1회성 스크립트.

원본(cp949, 시도/시군구/읍면동 합계가 섞여 있음)에서 읍면동 레벨만 남기고,
행정동코드(adm_cd) 기준으로 연령대 지표를 만들어 data/processed/population.parquet 으로 저장한다.
원본 5세 구간 22개 컬럼도 함께 남겨둔다 (추후 다른 구간이 필요할 때를 대비).

실행: python ingest/build_population.py
"""

import os
import re
import sys

import pandas as pd

RAW_PATH_TEMPLATE = "data/raw/population_{base_ym}.csv"
PROCESSED_PATH = "data/processed/population.parquet"
SIGUNGU_NAMES_PATH = "data/reference/sigungu_names.csv"
BASE_YM = "202608"

ADM_CD_PATTERN = re.compile(r"\((\d{10})\)")

# 원본 CSV의 5세 구간 라벨 (계/남/여 공통)
AGE_BIN_LABELS = [
    "0~4세", "5~9세", "10~14세", "15~19세", "20~24세", "25~29세",
    "30~34세", "35~39세", "40~44세", "45~49세", "50~54세", "55~59세",
    "60~64세", "65~69세", "70~74세", "75~79세", "80~84세", "85~89세",
    "90~94세", "95~99세", "100세 이상",
]

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _to_int(series):
    """쉼표 섞인 문자열이든 이미 숫자든 정수로 통일해서 변환한다."""
    return series.astype(str).str.replace(",", "").astype(int)


def _age_col_name(bin_label):
    """'0~4세' -> 'age_0_4', '100세 이상' -> 'age_100_plus' 형태로 변환한다."""
    digits = re.findall(r"\d+", bin_label)
    if "이상" in bin_label:
        return f"age_{digits[0]}_plus"
    return f"age_{digits[0]}_{digits[1]}"


def load_and_clean(base_ym=BASE_YM):
    """원본 CSV를 읽어 읍면동 레벨만 남기고 adm_cd/adm_nm/인구 지표 컬럼을 만든다."""
    raw_path = RAW_PATH_TEMPLATE.format(base_ym=base_ym)
    try:
        df = pd.read_csv(raw_path, encoding="cp949")
    except FileNotFoundError:
        print(f"파일을 찾을 수 없습니다: {raw_path}")
        return None
    except Exception as e:
        print(f"CSV를 읽는 중 오류가 발생했습니다: {e}")
        return None

    df["adm_cd"] = df["행정구역"].str.extract(ADM_CD_PATTERN)
    df["adm_nm"] = (
        df["행정구역"].str.replace(ADM_CD_PATTERN, "", regex=True).str.strip().str.split().str[-1]
    )

    # 읍면동만 남긴다: 10자리 코드의 끝 5자리가 0이면 시도/시군구 합계 행
    # (시도는 끝 8자리, 시군구는 끝 5자리가 0이라 이 조건 하나로 둘 다 걸러진다)
    df = df[df["adm_cd"].str[-5:] != "00000"].reset_index(drop=True)

    year, month = base_ym[:4], base_ym[4:]
    prefix = f"{year}년{month}월_계_"

    age_cols = []
    for bin_label in AGE_BIN_LABELS:
        col_name = _age_col_name(bin_label)
        df[col_name] = _to_int(df[f"{prefix}{bin_label}"])
        age_cols.append(col_name)

    df["total"] = _to_int(df[f"{prefix}총인구수"])
    df["age_0_9"] = df["age_0_4"] + df["age_5_9"]
    df["age_30_49"] = df["age_30_34"] + df["age_35_39"] + df["age_40_44"] + df["age_45_49"]
    df["base_ym"] = base_ym

    other_age_cols = [c for c in age_cols if c != "age_10_14"]
    columns = [
        "adm_cd", "adm_nm", "base_ym",
        "total", "age_0_9", "age_10_14", "age_30_49",
    ] + other_age_cols
    return df[columns]


def save_processed(df, out_path=PROCESSED_PATH):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_parquet(out_path, index=False)
    return out_path


def build_sigungu_names(base_ym=BASE_YM):
    """원본 CSV의 시군구 합계 행에서 5자리 시군구코드-이름 쌍을 추출한다.

    (읍면동 데이터는 동 이름만 있고 시군구 이름이 없어서, 원본의 시군구 합계 행
    ("서울특별시 종로구 (1111000000)" 같은 행)에서 이름을 따로 뽑아둔다)
    """
    raw_path = RAW_PATH_TEMPLATE.format(base_ym=base_ym)
    try:
        df = pd.read_csv(raw_path, encoding="cp949", usecols=["행정구역"])
    except FileNotFoundError:
        print(f"파일을 찾을 수 없습니다: {raw_path}")
        return None
    except Exception as e:
        print(f"CSV를 읽는 중 오류가 발생했습니다: {e}")
        return None

    df["adm_cd"] = df["행정구역"].str.extract(ADM_CD_PATTERN)
    df["sigungu_nm"] = df["행정구역"].str.replace(ADM_CD_PATTERN, "", regex=True).str.strip()

    is_sido = df["adm_cd"].str[2:] == "00000000"
    is_sigungu = (df["adm_cd"].str[-5:] == "00000") & ~is_sido

    result = df[is_sigungu][["adm_cd", "sigungu_nm"]].copy()
    result["sigungu_cd"] = result["adm_cd"].str[:5]
    return result[["sigungu_cd", "sigungu_nm"]].reset_index(drop=True)


def save_sigungu_names(df, out_path=SIGUNGU_NAMES_PATH):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out_path


def main():
    df = load_and_clean()
    if df is None:
        return

    out_path = save_processed(df)

    print(f"저장 완료: {out_path}")
    print(f"\n읍면동 행 개수: {len(df)}개")
    print("\n상위 5행:")
    print(df.head())
    print(f"\ntotal 합계: {df['total'].sum():,}명")

    print("\n" + "=" * 40 + "\n")

    sigungu_names = build_sigungu_names()
    if sigungu_names is not None:
        out_path = save_sigungu_names(sigungu_names)
        print(f"저장 완료: {out_path}")
        print(f"\n시군구 개수: {len(sigungu_names)}개")
        print(sigungu_names.head())


if __name__ == "__main__":
    main()
