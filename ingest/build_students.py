"""학교 학생수(정보공시) 6개 CSV를 합쳐 학생수 지표를 만들고, 기존 학교 데이터에 연결하는 스크립트.

원본은 학교급별로 파일이 나뉘어 있고 학년 구조가 서로 다르다 (초등/그외 38컬럼,
중등/고등 29컬럼, 특수 77컬럼, 각종 78컬럼). 앞 9개 메타 컬럼과 뒤 2개는 6개 파일이
동일하므로, 공통 컬럼만 뽑아 하나로 합친다. 학생수 총계 컬럼명만 특수/각종에서
'총계 학생수'로 다르기 때문에 폴백 분기를 둔다.

학교 데이터(schools.parquet)와의 연결은 학교코드 체계가 달라서 이름으로 해야 한다.
게다가 schools.parquet 주소는 행정구역 개편 이전 기준이라 (전라남도/광주광역시가
'전남광주통합특별시'로 통합, 인천 서구/중구/동구가 서해구/검단구/제물포구/영종구로
재편) 시군구 이름이 그대로 맞지 않는다. 그래서 시군구 -> 시도 -> 전국 순으로
단계를 낮춰가며 매칭한다 (각 단계에서 후보가 유일할 때만 연결).

실행: python ingest/build_students.py
"""

import os
import re
import sys

import pandas as pd

RAW_PATH_TEMPLATE = "data/raw/students_{key}.csv"
PROCESSED_PATH = "data/processed/students.parquet"
BY_SIGUNGU_PATH = "data/processed/students_by_sigungu.parquet"
SCHOOLS_PATH = "data/processed/schools.parquet"
SIGUNGU_NAMES_PATH = "data/reference/sigungu_names.csv"

# 파일 키 -> 학교급 라벨
SOURCE_LABELS = {
    "elementary": "초등",
    "middle": "중등",
    "high": "고등",
    "special": "특수",
    "various": "각종",
    "etc": "그외",
}

# 학생수/학급수 총계 컬럼: 초등·중등·고등·그외는 '(계)', 특수·각종은 '총계'를 쓴다
TOTAL_STUDENT_COLS = ["학생수(계)", "총계 학생수"]
TOTAL_CLASS_COLS = ["학급수(계)", "총계 학급수"]

# 행정구역 개편으로 schools.parquet(개편 이전 주소)과 이름이 어긋나는 시도
SIDO_REMAP = {
    "전라남도": "전남광주통합특별시",
    "광주광역시": "전남광주통합특별시",
}

# schools.parquet의 school_level -> 학생수 데이터의 학교급코드
SCHOOL_LEVEL_TO_CODE = {
    "초등학교": "02",
    "중학교": "03",
    "고등학교": "04",
}

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _to_int(series):
    """쉼표 섞인 문자열/빈칸을 정수로 변환한다 (빈칸은 0)."""
    cleaned = series.astype(str).str.replace(",", "").str.strip()
    return pd.to_numeric(cleaned, errors="coerce").fillna(0).astype(int)


def _pick_col(df, candidates):
    """후보 컬럼명 중 실제로 존재하는 첫 번째를 돌려준다 (폴백 분기)."""
    for col in candidates:
        if col in df.columns:
            return col
    raise KeyError(f"다음 컬럼을 찾을 수 없습니다: {candidates}")


def normalize_school_name(name):
    """학교명 매칭용 정규화: 공백과 동 번호 구분자('·', '.')를 제거한다.

    인구/경계 데이터 매칭(core/region_codes.py)과 같은 방침이다. 학생수 데이터와
    학교 데이터는 같은 학교를 '종로1·2·3가' 식 구분자나 공백 유무만 다르게 적는
    경우가 있어서, 비교 전에 양쪽을 같은 모양으로 만든다.
    """
    if not isinstance(name, str):
        return None
    return name.strip().replace("·", "").replace(".", "").replace(" ", "")


def _sido_from_office(office):
    """'대구광역시교육청' -> '대구광역시', '전남광주통합특별시교육청(광주)' -> '전남광주통합특별시'."""
    if not isinstance(office, str):
        return None
    name = re.sub(r"\(.*?\)", "", office).strip()
    return name[: -len("교육청")] if name.endswith("교육청") else name


def _sido_from_sigungu(sigungu_nm):
    """'경상북도 포항시 북구' -> '경상북도' (시군구명의 첫 토큰이 시도)."""
    if not isinstance(sigungu_nm, str):
        return None
    return sigungu_nm.split()[0]


def load_sigungu_names(path=SIGUNGU_NAMES_PATH):
    """시군구 코드-이름 표를 읽는다 (인구 데이터에서 만들어 둔 것)."""
    return pd.read_csv(path, dtype=str)


def sigungu_from_address(address, sigungu_names):
    """주소 앞부분에서 시군구 이름을 찾아낸다.

    '경상북도 포항시 북구'처럼 3토큰짜리 시군구가 있어서 긴 쪽부터 맞춰본다.
    개편 이전 시도명은 SIDO_REMAP으로 현재 이름으로 바꿔서 비교한다.
    """
    if not isinstance(address, str):
        return None
    tokens = address.split()
    if tokens and tokens[0] in SIDO_REMAP:
        tokens[0] = SIDO_REMAP[tokens[0]]
    for size in (3, 2, 1):
        if len(tokens) >= size:
            candidate = " ".join(tokens[:size])
            if candidate in sigungu_names:
                return candidate
    return None


def _lower_grade_sum(df, source_key):
    """초등 저학년(1~3학년) 학생수 합. 어린이 공간사업 수요층 지표용.

    초등 파일에만 만든다. '그외'(제과/영화 등 학교급코드 07·08)는 컬럼 구조가
    초등과 같지만 초등학생이 아니라서 제외하고, 특수/각종은 학년 컬럼이
    '유초등부-1학년'/'초등부-1학년'처럼 구조가 달라서 여기서는 비우고 둔다.
    """
    if source_key != "elementary":
        return pd.Series(pd.NA, index=df.index, dtype="Int64")
    total = sum(_to_int(df[f"{grade}학년 학생수"]) for grade in (1, 2, 3))
    return total.astype("Int64")


def load_and_merge_students():
    """6개 학생수 CSV를 공통 컬럼으로 합친다 (제외여부=Y 행은 버린다).

    반환: (통합 DataFrame, 파일별 요약 DataFrame)
    """
    frames = []
    summary = []
    for key, label in SOURCE_LABELS.items():
        raw_path = RAW_PATH_TEMPLATE.format(key=key)
        try:
            raw = pd.read_csv(raw_path, encoding="utf-8-sig", dtype=str)
        except FileNotFoundError:
            print(f"파일을 찾을 수 없습니다: {raw_path}")
            return None, None
        except Exception as e:
            print(f"CSV를 읽는 중 오류가 발생했습니다({raw_path}): {e}")
            return None, None

        student_col = _pick_col(raw, TOTAL_STUDENT_COLS)
        class_col = _pick_col(raw, TOTAL_CLASS_COLS)

        df = pd.DataFrame({
            "school_code": raw["정보공시 학교코드"].str.strip(),
            "school_name": raw["학교명"].str.strip(),
            "sigungu_nm": raw["지역"].str.strip(),
            "school_level_code": raw["학교급코드"].str.strip(),
            "school_level": label,
            "establishment": raw["설립구분"].str.strip(),
            "student_count": _to_int(raw[student_col]),
            "class_count": _to_int(raw[class_col]),
            "student_grade_1_3": _lower_grade_sum(raw, key),
            "teacher_count": _to_int(raw["교사수"]),
            "sido_edu_office": raw["시도교육청"].str.strip(),
            "edu_support_office": raw["교육지원청"].str.strip(),
            "source": key,
        })

        # 제외여부=Y는 위탁교육 등으로 학생수가 원적교에 반영된 행이라 학교 수에서 뺀다
        excluded = raw["제외여부"].str.strip().eq("Y")
        df = df[~excluded].reset_index(drop=True)

        summary.append({
            "source": key,
            "label": label,
            "원본행": len(raw),
            "제외여부Y": int(excluded.sum()),
            "학교수": len(df),
            "학생수합": int(df["student_count"].sum()),
            "총계컬럼": student_col,
        })
        frames.append(df)

    merged = pd.concat(frames, ignore_index=True)
    return merged, pd.DataFrame(summary)


def backfill_sigungu(students, schools, sigungu_names):
    """지역(시군구)이 빈 행을 보정한다.

    원본에 지역이 비어 있는 신설·이전 학교가 19건 있다. 두 가지 단서를 쓴다:
    1. 같은 학교명이 schools.parquet에 유일하게 있으면 그 주소의 시군구를 쓴다.
    2. 그래도 못 찾으면 교육지원청 이름에 들어 있는 시군구 이름을 쓴다.
    둘 다 시도교육청이 가리키는 시도와 일치할 때만 받아들인다 (같은 이름의 학교가
    다른 시도에 있는 경우를 막는다 - 예: '광성고등학교'는 인천과 서울 양쪽에 있다).

    반환: (보정된 students, 보정 내역 DataFrame)
    """
    missing = students["sigungu_nm"].isna() | students["sigungu_nm"].eq("")
    if not missing.any():
        return students, pd.DataFrame()

    schools = schools.copy()
    schools["sigungu_nm"] = schools["address"].map(
        lambda a: sigungu_from_address(a, sigungu_names)
    )
    schools["norm_name"] = schools["school_name"].map(normalize_school_name)
    # 이름이 전국에서 유일한 학교만 단서로 쓴다 (동명 학교는 어느 쪽인지 알 수 없다)
    by_name = (
        schools.dropna(subset=["sigungu_nm"])
        .drop_duplicates("norm_name", keep=False)
        .set_index("norm_name")["sigungu_nm"]
    )

    name_to_sigungu = {}
    for sigungu_nm in sigungu_names:
        tail = sigungu_nm.split()[-1]
        stem = tail[:-1]  # '달성군' -> '달성'
        if len(stem) >= 2:
            name_to_sigungu.setdefault(stem, []).append(sigungu_nm)

    def from_office(office):
        if not isinstance(office, str):
            return None
        hits = {s for stem, cands in name_to_sigungu.items() if stem in office for s in cands}
        return hits.pop() if len(hits) == 1 else None

    rows = []
    for idx in students.index[missing]:
        row = students.loc[idx]
        expected_sido = _sido_from_office(row["sido_edu_office"])
        candidate = by_name.get(normalize_school_name(row["school_name"]))
        how = "학교주소"
        if candidate is None or _sido_from_sigungu(candidate) != expected_sido:
            candidate = from_office(row["edu_support_office"])
            how = "교육지원청"
        if candidate is not None and _sido_from_sigungu(candidate) != expected_sido:
            candidate = None
        if candidate is not None:
            students.loc[idx, "sigungu_nm"] = candidate
        rows.append({
            "school_name": row["school_name"],
            "edu_support_office": row["edu_support_office"],
            "보정결과": candidate if candidate is not None else "(실패)",
            "방법": how if candidate is not None else "-",
            "student_count": row["student_count"],
        })

    return students, pd.DataFrame(rows)


def attach_student_counts(schools, students, sigungu_names):
    """schools.parquet에 student_count를 붙인다 (시군구+학교명 -> 시도+학교명 -> 전국 순).

    학교코드 체계가 서로 달라서 이름으로 매칭한다. 단계를 낮춰가는 이유는
    schools.parquet 주소가 행정구역 개편 이전 기준이라, 개편으로 쪼개지거나 합쳐진
    시군구(인천 서구 -> 서해구/검단구 등)에서는 시군구 이름이 맞지 않기 때문이다.
    어느 단계든 후보가 여러 개면 연결하지 않는다 (동명 학교 오매칭 방지).

    반환: (student_count/student_grade_1_3/match_level이 붙은 schools, 단계별 매칭 건수 dict)
    """
    schools = schools.copy()
    schools["sigungu_nm"] = schools["address"].map(
        lambda a: sigungu_from_address(a, sigungu_names)
    )
    schools["sido_nm"] = schools["sigungu_nm"].map(_sido_from_sigungu)
    schools["norm_name"] = schools["school_name"].map(normalize_school_name)
    schools["level_code"] = schools["school_level"].map(SCHOOL_LEVEL_TO_CODE)

    src = students.copy()
    src["norm_name"] = src["school_name"].map(normalize_school_name)
    src["sido_nm"] = src["sigungu_nm"].map(_sido_from_sigungu)

    def unique_lookup(keys, value_col):
        """주어진 키 조합으로 학생수를 찾는 표를 만든다 (키가 유일한 것만)."""
        grouped = src.dropna(subset=keys).groupby(keys, dropna=True)
        counts = grouped[value_col].agg(["size", "sum"])
        unique = counts[counts["size"] == 1]["sum"]
        return unique

    tiers = [
        ("시군구+학교명", ["sigungu_nm", "norm_name"], ["sigungu_nm", "norm_name"]),
        ("시도+학교명", ["sido_nm", "norm_name"], ["sido_nm", "norm_name"]),
        ("전국 학교명", ["norm_name"], ["norm_name"]),
    ]

    schools["student_count"] = pd.NA
    schools["student_grade_1_3"] = pd.NA
    schools["match_level"] = pd.NA
    stats = {}
    for label, src_keys, school_keys in tiers:
        todo = schools["student_count"].isna()
        if not todo.any():
            stats[label] = 0
            continue
        if len(school_keys) == 1:
            index = pd.Index(schools.loc[todo, school_keys[0]])
        else:
            index = pd.MultiIndex.from_frame(schools.loc[todo, school_keys])

        found = pd.Series(index.map(unique_lookup(src_keys, "student_count")), index=schools.index[todo])
        schools.loc[todo, "student_count"] = found
        # 저학년은 초등학교에만 값이 있어서, 중·고교는 매칭돼도 비어 있는 것이 정상이다
        lower = pd.Series(
            index.map(unique_lookup(src_keys, "student_grade_1_3")), index=schools.index[todo]
        )
        schools.loc[todo, "student_grade_1_3"] = lower

        newly = found.notna()
        schools.loc[found.index[newly], "match_level"] = label
        stats[label] = int(newly.sum())

    schools["student_count"] = pd.to_numeric(schools["student_count"]).astype("Int64")
    schools["student_grade_1_3"] = pd.to_numeric(schools["student_grade_1_3"]).astype("Int64")
    return schools, stats


def aggregate_by_sigungu(students, sigungu_names_df):
    """학생수를 시군구 단위로 합산한다 (보고서/배후권 비교용).

    반환: DataFrame (sigungu_cd, sigungu_nm, students_total, students_elementary,
          students_middle, students_high, students_grade_1_3, school_count)
    """
    valid = students.dropna(subset=["sigungu_nm"])
    valid = valid[valid["sigungu_nm"] != ""]

    by_level = (
        valid.pivot_table(
            index="sigungu_nm",
            columns="school_level",
            values="student_count",
            aggfunc="sum",
            fill_value=0,
        )
        .rename(columns={
            "초등": "students_elementary",
            "중등": "students_middle",
            "고등": "students_high",
            "특수": "students_special",
            "각종": "students_various",
            "그외": "students_etc",
        })
    )
    totals = valid.groupby("sigungu_nm").agg(
        students_total=("student_count", "sum"),
        students_grade_1_3=("student_grade_1_3", "sum"),
        school_count=("school_code", "size"),
    )
    agg = totals.join(by_level).reset_index()

    # sigungu_names와 조인해 시군구코드를 붙인다 (지역 이름은 100% 일치하는 것을 확인했다)
    result = sigungu_names_df.merge(agg, on="sigungu_nm", how="inner")

    level_cols = [
        "students_elementary", "students_middle", "students_high",
        "students_special", "students_various", "students_etc",
    ]
    for col in level_cols:
        if col not in result.columns:
            result[col] = 0
        result[col] = result[col].fillna(0).astype(int)
    result["students_grade_1_3"] = result["students_grade_1_3"].fillna(0).astype(int)

    columns = ["sigungu_cd", "sigungu_nm", "students_total", "students_grade_1_3",
               "school_count"] + level_cols
    return result[columns].sort_values("sigungu_cd").reset_index(drop=True)


def save_processed(df, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_parquet(out_path, index=False)
    return out_path


def main():
    students, summary = load_and_merge_students()
    if students is None:
        return

    sigungu_names_df = load_sigungu_names()
    sigungu_names = set(sigungu_names_df["sigungu_nm"])
    schools = pd.read_parquet(SCHOOLS_PATH)

    print("## 1. 6개 파일 통합")
    print(summary.to_string(index=False))

    students, backfilled = backfill_sigungu(students, schools, sigungu_names)
    if len(backfilled):
        ok = (backfilled["보정결과"] != "(실패)").sum()
        print(f"\n지역 결측 보정: {ok}/{len(backfilled)}건 성공")
        print(backfilled.to_string(index=False))

    still_missing = students["sigungu_nm"].isna() | students["sigungu_nm"].eq("")
    out_path = save_processed(students, PROCESSED_PATH)
    print(f"\n저장 완료: {out_path}")
    print(f"  학교 수: {len(students):,}개  |  학생수 합계: {int(students['student_count'].sum()):,}명")
    print(f"  지역 미보정 잔여: {int(still_missing.sum())}건 "
          f"(학생 {int(students.loc[still_missing, 'student_count'].sum()):,}명)")
    lower = students["student_grade_1_3"].dropna()
    print(f"  초등 저학년(1~3학년) 합계: {int(lower.sum()):,}명 ({len(lower):,}개 초등학교)")
    print("\n상위 5행:")
    print(students[[
        "school_code", "school_name", "sigungu_nm", "school_level",
        "student_count", "student_grade_1_3",
    ]].head().to_string(index=False))

    print("\n" + "=" * 70 + "\n")
    print("## 2. schools.parquet에 학생수 연결")
    schools_with_counts, stats = attach_student_counts(schools, students, sigungu_names)
    matched = schools_with_counts["student_count"].notna()
    total = len(schools_with_counts)
    for label, count in stats.items():
        print(f"  {label:<12} {count:>6,}건")
    print(f"\n  매칭률: {matched.sum():,}/{total:,} = {matched.mean() * 100:.1f}%")
    print(f"  미매칭: {int((~matched).sum()):,}개")
    print(f"  연결된 학생수 합계: {int(schools_with_counts['student_count'].sum()):,}명")

    unmatched = schools_with_counts[~matched]
    if len(unmatched):
        print("\n  미매칭 학교 예시 10개:")
        print(unmatched[["school_name", "school_level", "address"]].head(10).to_string(index=False))

    out_path = save_processed(
        schools_with_counts.drop(columns=["norm_name", "level_code"]), SCHOOLS_PATH
    )
    print(f"\n저장 완료: {out_path} (student_count/student_grade_1_3/match_level/sigungu_nm/sido_nm 컬럼 추가)")

    print("\n" + "=" * 70 + "\n")
    print("## 3. 시군구 단위 집계")
    by_sigungu = aggregate_by_sigungu(students, sigungu_names_df)
    out_path = save_processed(by_sigungu, BY_SIGUNGU_PATH)
    print(f"저장 완료: {out_path}")
    print(f"  시군구 수: {len(by_sigungu)}개 / sigungu_names {len(sigungu_names_df)}개")
    print(f"  학생수 합계: {int(by_sigungu['students_total'].sum()):,}명")
    print("\n학생수 상위 5개 시군구:")
    print(by_sigungu.nlargest(5, "students_total")[[
        "sigungu_cd", "sigungu_nm", "students_total",
        "students_elementary", "students_middle", "students_high", "students_grade_1_3",
    ]].to_string(index=False))


if __name__ == "__main__":
    main()
