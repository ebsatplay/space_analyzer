"""데이터 관리 - 원본 데이터 갱신 현황판 + 갱신 흐름(팝업).

관리자용 설정 화면. 분석 기능이 쓰는 원본 데이터가 최신인지 확인하고 갱신한다.

실행: streamlit run app.py (메뉴에서 "데이터 관리" 선택)
"""

import io
import json
import os
import re
import shutil
import zipfile
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from ingest.build_boundaries import PROCESSED_PATH as BOUNDARIES_PROCESSED_PATH
from ingest.build_boundaries import load_boundaries
from ingest.build_boundaries import save_processed as save_boundaries
from ingest.build_facilities import (
    CLOSED_SCHOOLS_PROCESSED_PATH,
    CLOSED_SCHOOLS_RAW_PATH,
    LIBRARIES_PROCESSED_PATH,
    LIBRARIES_RAW_PATH,
    SCHOOLS_PROCESSED_PATH,
    SCHOOLS_RAW_PATH,
    TOURISM_PROCESSED_PATH,
    TOURISM_RAW_PATH,
    build_closed_schools,
    build_libraries,
    build_schools,
    build_tourism,
)
from ingest.build_facilities import save_processed as save_facility
from ingest.build_population import load_and_clean as load_clean_population
from ingest.build_population import save_processed as save_population
from views._theme import apply_theme, page_header

DATA_STATUS_PATH = "data/processed/data_status.json"

CYCLE_LABELS = {"monthly": "1개월", "biannual": "6개월", "yearly": "1년"}
CYCLE_DAYS = {"monthly": 30, "biannual": 182, "yearly": 365}

# Streamlit Community Cloud는 저장소를 /mount/src 아래에 배포한다.
# DEPLOY_ENV를 직접 지정할 수도 있게 해서(예: 다른 호스팅) 판별을 명시적으로 덮어쓸 수 있다.
CLOUD_MOUNT_PATH = "/mount/src"


def is_cloud_environment():
    """배포(웹) 환경이면 True. 로컬 실행이면 False."""
    declared = os.getenv("DEPLOY_ENV", "").strip().lower()
    if declared in {"cloud", "production", "prod"}:
        return True
    if declared in {"local", "dev", "development"}:
        return False
    return os.path.isdir(CLOUD_MOUNT_PATH)


apply_theme()
page_header("데이터 관리", "원본 데이터가 언제 적용됐고, 갱신이 필요한지 한눈에 확인")

if is_cloud_environment():
    st.warning(
        "⚠️ 배포(웹) 환경에서는 업로드 갱신이 일시적이며, 앱 재시작 시 초기화됩니다. "
        "실제 데이터 갱신은 로컬에서 하고 저장소에 반영해주세요."
    )


def load_data_status(path=DATA_STATUS_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        st.error(f"파일을 찾을 수 없습니다: {path}")
        return []
    except json.JSONDecodeError as e:
        st.error(f"data_status.json 형식이 잘못됐습니다: {e}")
        return []


def update_status_entry(name, path=DATA_STATUS_PATH, **fields):
    """data_status.json에서 이름이 일치하는 항목의 필드를 갱신해서 저장한다."""
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    for item in items:
        if item["데이터명"] == name:
            item.update(fields)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def update_population(base_ym, uploaded_file):
    """업로드된 인구 CSV를 저장 → 정제 → data_status.json 갱신까지 처리한다.

    반환: {"success": True} 또는 {"success": False, "error": "..."}
    """
    if not re.fullmatch(r"\d{6}", base_ym):
        return {"success": False, "error": "기준연월은 YYYYMM 형식(예: 202609)으로 입력해주세요."}

    raw_path = f"data/raw/population_{base_ym}.csv"
    try:
        os.makedirs(os.path.dirname(raw_path), exist_ok=True)
        with open(raw_path, "wb") as f:
            f.write(uploaded_file.getvalue())
    except OSError as e:
        return {"success": False, "error": f"파일을 저장하는 중 오류가 발생했습니다: {e}"}

    try:
        df = load_clean_population(base_ym)
    except Exception:
        df = None

    if df is None or df.empty:
        return {
            "success": False,
            "error": (
                f"업로드한 파일을 정제하는 데 실패했습니다. "
                f"기준연월({base_ym})이 실제 파일 내용과 맞는지, "
                f"CSV 형식(cp949 인코딩, 컬럼 구성)이 올바른지 확인해주세요."
            ),
        }

    save_population(df)

    today_str = date.today().strftime("%Y-%m-%d")
    update_status_entry("인구", 기준연월=base_ym, 적용일자=today_str)

    return {"success": True}


def _reference_year_month(raw_path):
    """CSV의 '데이터기준일자' 컬럼 중 가장 최근 값을 YYYYMM으로 반환한다.

    컬럼이 없거나 읽기 실패하면 오늘 날짜의 YYYYMM을 반환한다.
    """
    try:
        df = pd.read_csv(raw_path, encoding="cp949", usecols=["데이터기준일자"])
        max_date = str(df["데이터기준일자"].max())
        return max_date[:7].replace("-", "")
    except (ValueError, KeyError, FileNotFoundError):
        return date.today().strftime("%Y%m")


def _update_facility(display_name, raw_path, build_fn, processed_path, uploaded_file):
    """학교/도서관/관광지 공통 갱신 로직: 저장 → 정제 → parquet 저장 → 상태 갱신."""
    try:
        os.makedirs(os.path.dirname(raw_path), exist_ok=True)
        with open(raw_path, "wb") as f:
            f.write(uploaded_file.getvalue())
    except OSError as e:
        return {"success": False, "error": f"파일을 저장하는 중 오류가 발생했습니다: {e}"}

    try:
        df = build_fn()
    except Exception:
        df = None

    if df is None or df.empty:
        return {
            "success": False,
            "error": (
                "업로드한 파일을 정제하는 데 실패했습니다. "
                "CSV 형식(cp949 인코딩, 컬럼 구성)이 원본과 같은지 확인해주세요."
            ),
        }

    save_facility(df, processed_path)

    base_ym = _reference_year_month(raw_path)
    today_str = date.today().strftime("%Y-%m-%d")
    update_status_entry(display_name, 기준연월=base_ym, 적용일자=today_str)

    return {"success": True, "base_ym": base_ym}


def update_schools(uploaded_file):
    """업로드된 학교 CSV를 저장 → 정제 → data_status.json 갱신까지 처리한다."""
    return _update_facility("학교", SCHOOLS_RAW_PATH, build_schools, SCHOOLS_PROCESSED_PATH, uploaded_file)


def update_libraries(uploaded_file):
    """업로드된 도서관 CSV를 저장 → 정제 → data_status.json 갱신까지 처리한다."""
    return _update_facility(
        "도서관", LIBRARIES_RAW_PATH, build_libraries, LIBRARIES_PROCESSED_PATH, uploaded_file
    )


def update_tourism(uploaded_file):
    """업로드된 관광지 CSV를 저장 → 정제 → data_status.json 갱신까지 처리한다."""
    return _update_facility("관광지", TOURISM_RAW_PATH, build_tourism, TOURISM_PROCESSED_PATH, uploaded_file)


SIMPLE_UPDATE_HANDLERS = {
    "학교": update_schools,
    "도서관": update_libraries,
    "관광지": update_tourism,
}


def update_closed_schools(uploaded_file, progress_callback=None):
    """업로드된 폐교 CSV를 저장 → 카카오 좌표변환(1,194건, 수 분 소요) → 정제 →
    data_status.json 갱신까지 처리한다.

    좌표가 원본에 없어서 학교/도서관/관광지보다 오래 걸린다.
    progress_callback(i, total, success, fail)을 넘기면 변환 중 매 행마다 호출된다.
    """
    raw_path = CLOSED_SCHOOLS_RAW_PATH
    try:
        os.makedirs(os.path.dirname(raw_path), exist_ok=True)
        with open(raw_path, "wb") as f:
            f.write(uploaded_file.getvalue())
    except OSError as e:
        return {"success": False, "error": f"파일을 저장하는 중 오류가 발생했습니다: {e}"}

    try:
        df = build_closed_schools(raw_path, progress_callback=progress_callback)
    except Exception:
        df = None

    if df is None or df.empty:
        return {
            "success": False,
            "error": (
                "업로드한 파일을 정제하는 데 실패했습니다. "
                "CSV 형식(cp949 인코딩, 컬럼 구성)이 원본과 같은지 확인해주세요."
            ),
        }

    save_facility(df, CLOSED_SCHOOLS_PROCESSED_PATH)

    base_ym = _reference_year_month(raw_path)
    today_str = date.today().strftime("%Y-%m-%d")
    update_status_entry("폐교", 기준연월=base_ym, 적용일자=today_str)

    return {"success": True, "base_ym": base_ym}


BOUNDARY_REQUIRED_EXTS = [".shp", ".dbf", ".shx", ".prj"]
BOUNDARY_OPTIONAL_EXTS = [".cpg"]


def update_boundaries(uploaded_zip):
    """업로드된 zip에서 행정동 경계 SHP 세트를 찾아 저장 → 변환/단순화 → data_status.json 갱신한다.

    zip 안에 폴더가 섞여 있어도 'bnd_dong'으로 시작하는 .shp와 그 짝(.dbf/.shx/.prj, 있으면 .cpg)을
    찾아서 data/raw/ 로 옮긴다.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(uploaded_zip.getvalue()))
    except zipfile.BadZipFile:
        return {
            "success": False,
            "error": "올바른 zip 파일이 아닙니다. 공공데이터포털에서 받은 zip 파일을 그대로 올려주세요.",
        }

    shp_entries = [
        name
        for name in zf.namelist()
        if re.search(r"bnd_dong.*\.shp$", os.path.basename(name), re.IGNORECASE)
    ]
    if not shp_entries:
        return {
            "success": False,
            "error": "zip 안에서 'bnd_dong'으로 시작하는 행정동 경계 SHP 파일(.shp)을 찾을 수 없습니다.",
        }

    shp_entry = shp_entries[0]
    stem = shp_entry[: -len(".shp")]
    basename_stem = os.path.basename(stem)

    entries_in_zip = {}
    missing = []
    for ext in BOUNDARY_REQUIRED_EXTS:
        candidate = stem + ext
        if candidate in zf.namelist():
            entries_in_zip[ext] = candidate
        else:
            missing.append(basename_stem + ext)

    if missing:
        return {
            "success": False,
            "error": (
                f"SHP 세트가 완전하지 않습니다. 다음 파일이 zip 안에 없습니다: {', '.join(missing)}. "
                "공공데이터포털에서 받은 zip을 수정하지 말고 그대로 올려주세요."
            ),
        }

    for ext in BOUNDARY_OPTIONAL_EXTS:
        candidate = stem + ext
        if candidate in zf.namelist():
            entries_in_zip[ext] = candidate

    try:
        os.makedirs("data/raw", exist_ok=True)
        for ext, zip_path in entries_in_zip.items():
            dest_path = f"data/raw/{basename_stem}{ext}"
            with zf.open(zip_path) as src, open(dest_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
    except OSError as e:
        return {"success": False, "error": f"파일을 저장하는 중 오류가 발생했습니다: {e}"}

    shp_path = f"data/raw/{basename_stem}.shp"

    try:
        gdf = load_boundaries(shp_path)
    except Exception:
        gdf = None

    if gdf is None or gdf.empty:
        return {
            "success": False,
            "error": "SHP 파일을 읽는 데 실패했습니다. 파일이 손상되지 않았는지 확인해주세요.",
        }

    save_boundaries(gdf, BOUNDARIES_PROCESSED_PATH)

    if "BASE_DATE" in gdf.columns:
        base_ym = str(gdf["BASE_DATE"].max())[:6]
    else:
        base_ym = date.today().strftime("%Y%m")

    today_str = date.today().strftime("%Y-%m-%d")
    update_status_entry("경계", 기준연월=base_ym, 적용일자=today_str)

    return {"success": True, "base_ym": base_ym}


@st.dialog("데이터 갱신", width="large")
def open_update_dialog(item):
    name = item["데이터명"]
    st.markdown(f"### {name}")

    st.markdown("**1단계 · 최신 데이터 받기**")
    st.markdown(item.get("download_guide", "안내가 등록되어 있지 않습니다."))
    st.link_button("📥 사이트 열기", item["다운로드URL"])

    st.divider()
    st.markdown("**2단계 · 받은 파일 올리기**")

    if name == "인구":
        default_ym = date.today().strftime("%Y%m")
        base_ym = st.text_input(
            "기준연월 (YYYYMM) - 업로드한 파일이 다루는 연월을 확인해주세요",
            value=default_ym,
            key="population_base_ym",
        )
        uploaded = st.file_uploader("CSV 파일 업로드", type="csv", key="population_upload")

        if uploaded is not None:
            if st.button("갱신 실행", type="primary", key="population_run"):
                with st.spinner("업로드한 파일로 데이터를 갱신하는 중..."):
                    result = update_population(base_ym, uploaded)

                if result["success"]:
                    st.success(f"✓ 갱신 완료! ({base_ym[:4]}년 {base_ym[4:]}월 기준으로 업데이트됨)")
                    if st.button("닫기", key="population_close"):
                        st.rerun()
                else:
                    st.error(result["error"])

    elif name in SIMPLE_UPDATE_HANDLERS:
        uploaded = st.file_uploader("CSV 파일 업로드", type="csv", key=f"{name}_upload")

        if uploaded is not None:
            if st.button("갱신 실행", type="primary", key=f"{name}_run"):
                with st.spinner("업로드한 파일로 데이터를 갱신하는 중..."):
                    result = SIMPLE_UPDATE_HANDLERS[name](uploaded)

                if result["success"]:
                    base_ym = result.get("base_ym", "")
                    ym_label = f"{base_ym[:4]}년 {base_ym[4:]}월 기준으로 " if base_ym else ""
                    st.success(f"✓ 갱신 완료! ({ym_label}업데이트됨)")
                    if st.button("닫기", key=f"{name}_close"):
                        st.rerun()
                else:
                    st.error(result["error"])

    elif name == "폐교":
        st.caption("⏱️ 좌표가 없는 원본이라 주소 1,194건을 카카오로 변환합니다 (약 6~7분 소요)")
        uploaded = st.file_uploader("CSV 파일 업로드", type="csv", key="closed_schools_upload")

        if uploaded is not None:
            if st.button("갱신 실행", type="primary", key="closed_schools_run"):
                with st.spinner("폐교 주소를 좌표로 변환 중... 몇 분 걸릴 수 있어요"):
                    progress_bar = st.progress(0, text="변환 준비 중...")

                    def on_progress(i, total, success, fail, _bar=progress_bar):
                        _bar.progress(
                            i / total,
                            text=f"주소 좌표 변환 중... ({i}/{total}건, 성공 {success} · 실패 {fail})",
                        )

                    result = update_closed_schools(uploaded, progress_callback=on_progress)
                    progress_bar.empty()

                if result["success"]:
                    base_ym = result.get("base_ym", "")
                    ym_label = f"{base_ym[:4]}년 {base_ym[4:]}월 기준으로 " if base_ym else ""
                    st.success(f"✓ 갱신 완료! ({ym_label}업데이트됨)")
                    if st.button("닫기", key="closed_schools_close"):
                        st.rerun()
                else:
                    st.error(result["error"])

    elif name == "경계":
        st.caption("📦 공공데이터포털에서 받은 zip 파일을 그대로 올리세요 (.shp/.dbf/.shx/.prj 세트가 안에 들어있어야 합니다)")
        uploaded_zip = st.file_uploader("zip 파일 업로드", type="zip", key="boundaries_upload")

        if uploaded_zip is not None:
            if st.button("갱신 실행", type="primary", key="boundaries_run"):
                with st.spinner("zip에서 경계 파일을 찾아 변환하는 중..."):
                    result = update_boundaries(uploaded_zip)

                if result["success"]:
                    base_ym = result.get("base_ym", "")
                    ym_label = f"{base_ym[:4]}년 {base_ym[4:]}월 기준으로 " if base_ym else ""
                    st.success(f"✓ 갱신 완료! ({ym_label}업데이트됨)")
                    if st.button("닫기", key="boundaries_close"):
                        st.rerun()
                else:
                    st.error(result["error"])

    else:
        st.info("이 데이터는 아직 자동 정제가 연결되지 않았습니다. (다음 단계에서 추가 예정)")


items = load_data_status()

if not items:
    st.info("등록된 데이터 현황이 없습니다.")
else:
    today = date.today()
    cols = st.columns(3)

    for i, item in enumerate(items):
        applied_date = datetime.strptime(item["적용일자"], "%Y-%m-%d").date()
        cycle = item["갱신주기"]
        cycle_days = CYCLE_DAYS.get(cycle, 365)
        due_date = applied_date + timedelta(days=cycle_days)
        is_stale = today >= due_date

        year_month = f"{item['기준연월'][:4]}년 {item['기준연월'][4:]}월"
        badge = "⚠️ 갱신 권장" if is_stale else "✓ 최신"
        card_class = "status-stale" if is_stale else "status-fresh"

        col = cols[i % 3]
        col.markdown(
            f"""
            <div class="status-card {card_class}">
                <div class="status-name">{item['데이터명']}</div>
                <div class="status-meta">기준연월: {year_month}</div>
                <div class="status-meta">적용일: {item['적용일자']}</div>
                <div class="status-meta">갱신주기: {CYCLE_LABELS.get(cycle, cycle)}</div>
                <div class="status-badge">{badge}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if is_stale:
            if col.button("🔄 갱신하기", key=f"update_btn_{item['데이터명']}", use_container_width=True):
                open_update_dialog(item)

    st.caption(
        "※ 적용일자 + 갱신주기가 오늘보다 지나면 '갱신 권장'으로 표시됩니다. "
        "갱신하기 → 파일 업로드까지 완료하면 자동으로 최신 상태가 됩니다."
    )
