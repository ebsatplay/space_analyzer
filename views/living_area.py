"""생활권 분석 - 기준점 주변 N분 생활권의 인구·시설을 살펴본다.

실행: streamlit run app.py (메뉴에서 "생활권 분석" 선택)
"""

import math

import altair as alt
import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import folium_static

from analysis.area_profile import (
    ELEMENTARY,
    KAKAO_CATEGORIES,
    get_closed_schools_in_circle,
    get_facilities_in_circle,
    get_libraries_in_circle,
    get_living_area_population,
    get_nationwide_child_ratio,
    get_nationwide_lower_grade_ratio,
    get_nearby_facilities_kakao,
    get_tourism_in_circle,
)
from analysis.living_area import calc_radius_km, get_dong_geometries, get_dongs_in_circle

from analysis.datalab import (
    DATA_CAVEAT as DATALAB_CAVEAT,
    DATA_SOURCE as DATALAB_SOURCE,
    get_monthly_interest,
    get_search_rank_for_sigungu,
    get_search_rank_top,
    get_sigungu_datalab,
)
from analysis.child_space import (
    assess_density,
    classify_child_spaces,
    compare_with_similar,
    get_child_centers_in_circle,
    get_culture_in_circle,
    get_nationwide_benchmarks,
    get_public_facilities_in_circle,
    get_sigungu_child_space,
)
from analysis.tourism_region import (
    TREND_CAVEAT,
    get_region_detail,
    list_registered_regions,
    summarize_level_and_trend,
)
from analysis.visitors import DATA_CAVEAT, get_visitors_for_address, resolve_sigungu_cd
from analysis.region_news import (
    BUSINESS_KEYWORDS,
    RECENT_MONTHS,
    get_region_news,
    region_from_address,
)
from services.kakao_service import find_location
from analysis.backyard import get_backyard_metrics, get_backyard_sigungu
from views._theme import apply_theme, page_header, render_metric_cards

apply_theme()
page_header("생활권 분석", "걷고 머무는 시간으로 그려보는, 우리 동네의 반경")

st.markdown('<div class="search-section-label">위치 검색</div>', unsafe_allow_html=True)
search_col, button_col = st.columns([4, 1])
address = search_col.text_input(
    "기준 주소 또는 장소명",
    label_visibility="collapsed",
    placeholder="예: 포항시청, 고령군청, 경북 고령군 대가야읍",
)
if button_col.button("검색", use_container_width=True):
    try:
        result = find_location(address)
    except Exception as e:
        st.error(f"검색 중 오류가 발생했습니다: {e}")
        result = None

    if result:
        candidates, method = result
        st.session_state["candidates"] = candidates
        st.session_state["search_method"] = method
        st.session_state.pop("selected_place", None)
    else:
        st.session_state["candidates"] = None
        st.warning("위치를 찾을 수 없습니다. 다른 주소나 장소명을 입력해보세요")

candidates = st.session_state.get("candidates")
selected = None

if candidates:
    method = st.session_state.get("search_method", "")

    if len(candidates) == 1:
        selected = candidates[0]
    else:
        options = [f"{name} ({addr})" for name, addr, _lat, _lon in candidates]
        chosen = st.radio(
            "여러 곳이 검색되었습니다. 선택하세요",
            options,
            key="selected_place",
        )
        selected = candidates[options.index(chosen)]

    name, addr, lat, lon = selected
    st.success(f"[{method}] {name} ({addr}) - 위도: {lat}, 경도: {lon}")

if selected:
    name, addr, lat, lon = selected

    st.subheader("N분 생활권")
    preset_col, custom_col, speed_col = st.columns([2, 1, 2])
    preset_minutes = preset_col.radio(
        "이동시간", [10, 20, 30, "직접 입력"],
        index=1,
        format_func=lambda m: m if isinstance(m, str) else f"{m}분",
        key="living_area_minutes",
        horizontal=True,
    )
    # 버튼에 없는 시간을 쓰고 싶을 때를 위해 직접 입력 칸을 둔다
    custom_minutes = custom_col.number_input(
        "직접 입력 (분)",
        min_value=1,
        max_value=180,
        value=25,
        step=5,
        key="living_area_minutes_custom",
        disabled=preset_minutes != "직접 입력",
        help="왼쪽에서 '직접 입력'을 고르면 이 값이 쓰입니다",
    )
    minutes = int(custom_minutes) if preset_minutes == "직접 입력" else int(preset_minutes)

    speed_kmh = speed_col.slider(
        "평균 속도 (km/h)",
        min_value=20,
        max_value=50,
        value=30,
        key="living_area_speed",
        help="직선거리 환산용 평균 속도",
    )
    radius_km = calc_radius_km(speed_kmh, minutes)
    st.caption(f"적용: {minutes}분 · 평균 {speed_kmh}km/h · 직선 반경 약 {radius_km:.1f}km")

    dongs = get_dongs_in_circle(lat, lon, radius_km)
    dong_geometries = get_dong_geometries(dongs["ADM_CD"].tolist())
    facilities = get_facilities_in_circle(lat, lon, radius_km)
    libraries_nearby = get_libraries_in_circle(lat, lon, radius_km)
    tourism_nearby = get_tourism_in_circle(lat, lon, radius_km)
    closed_schools_nearby = get_closed_schools_in_circle(lat, lon, radius_km)

    radius_m = min(radius_km * 1000, 20000)
    kakao_cache = st.session_state.setdefault("kakao_cache", {})
    kakao_cache_key = (round(lat, 5), round(lon, 5), round(radius_m))
    if kakao_cache_key not in kakao_cache:
        with st.spinner("카카오에서 주변 시설을 검색하는 중..."):
            kakao_cache[kakao_cache_key] = get_nearby_facilities_kakao(lat, lon, radius_m)
    kakao_nearby = kakao_cache[kakao_cache_key]

    st.caption("지도에 표시할 시설 (기본: 학교·도서관·폐교만 켜짐)")
    tg1, tg2, tg3, tg4, tg5, tg6, tg7 = st.columns(7)
    show_layers = {
        "학교": tg1.checkbox("🏫 학교", value=True, key="show_school"),
        "도서관": tg2.checkbox("📚 도서관", value=True, key="show_library"),
        "폐교": tg3.checkbox("🏚️ 폐교", value=True, key="show_closed_school"),
        "관광명소": tg4.checkbox("🎡 관광명소", value=False, key="show_kakao_tourist"),
        "키즈카페": tg5.checkbox("🧸 키즈카페", value=False, key="show_kakao_kids"),
        "문화체험": tg6.checkbox("🏛️ 문화체험", value=False, key="show_kakao_culture"),
        "집객시설": tg7.checkbox("🛍️ 집객시설", value=False, key="show_kakao_crowd"),
    }

    m = folium.Map(location=[lat, lon], zoom_start=13)

    # 외부 CDN 이미지에 의존하지 않도록 순수 CSS로 그리는 마커 (기본 아이콘은 이미지 로드 실패 시 깨져 보임)
    center_icon = folium.DivIcon(
        html=(
            '<div style="'
            "width: 20px; height: 20px;"
            "background-color: #C97B8E;"
            "border: 3px solid #FAF7F2;"
            "border-radius: 50%;"
            'box-shadow: 0 2px 8px rgba(0,0,0,0.35);"></div>'
        ),
        icon_size=(20, 20),
        icon_anchor=(10, 10),
    )
    folium.Marker(
        [lat, lon],
        tooltip=name,
        popup=folium.Popup(name, max_width=300),
        icon=center_icon,
    ).add_to(m)
    folium.Circle(
        location=[lat, lon],
        radius=radius_km * 1000,
        color="blue",
        fill=True,
        fill_opacity=0.2,
        tooltip=f"직선거리 기준 약 {radius_km:.1f} km 범위",
    ).add_to(m)

    if not dong_geometries.empty:
        folium.GeoJson(
            dong_geometries,
            style_function=lambda _feature: {
                "fillColor": "orange",
                "color": "orange",
                "weight": 1,
                "fillOpacity": 0.25,
            },
            tooltip=folium.GeoJsonTooltip(fields=["ADM_NM"], aliases=["행정동"]),
        ).add_to(m)

    def emoji_icon(emoji):
        html = f'<div style="font-size: 20px; line-height: 1; text-align: center;">{emoji}</div>'
        return folium.DivIcon(html=html, icon_size=(24, 24), icon_anchor=(12, 20))

    if show_layers["학교"]:
        school_cluster = MarkerCluster(name="학교").add_to(m)
        for _, school in facilities["schools"].iterrows():
            folium.Marker(
                location=[school["lat"], school["lon"]],
                tooltip=school["school_name"],
                icon=emoji_icon("🏫"),
            ).add_to(school_cluster)

    if show_layers["도서관"]:
        library_cluster = MarkerCluster(name="도서관").add_to(m)
        for _, library in libraries_nearby["libraries"].iterrows():
            folium.Marker(
                location=[library["lat"], library["lon"]],
                tooltip=library["library_name"],
                icon=emoji_icon("📚"),
            ).add_to(library_cluster)

    # 미활용 폐교는 "사업 후보지"라 눈에 띄게 강조 (클러스터에 묻히지 않도록 항상 개별 표시)
    if show_layers["폐교"]:
        unused_icon_html = (
            '<div style="'
            "width: 30px; height: 30px;"
            "background-color: #F3D4D4;"
            "border: 2px solid #D9534F;"
            "border-radius: 50%;"
            "display: flex; align-items: center; justify-content: center;"
            "font-size: 17px; line-height: 1;"
            'box-shadow: 0 2px 8px rgba(217, 83, 79, 0.55);">🏚️</div>'
        )
        unused_icon = folium.DivIcon(html=unused_icon_html, icon_size=(30, 30), icon_anchor=(15, 15))
        muted_icon_html = '<div style="font-size: 20px; line-height: 1; opacity: 0.4;">🏫</div>'
        muted_icon = folium.DivIcon(html=muted_icon_html, icon_size=(24, 24), icon_anchor=(12, 20))

        closed_schools_df = closed_schools_nearby["closed_schools"]
        unused_df = closed_schools_df[closed_schools_df["usage_status"] == "미활용"]
        other_df = closed_schools_df[closed_schools_df["usage_status"] != "미활용"]

        for _, school in unused_df.iterrows():
            folium.Marker(
                location=[school["lat"], school["lon"]],
                tooltip=f"{school['name']} (미활용, {school['year']}년 폐교)",
                icon=unused_icon,
            ).add_to(m)

        if not other_df.empty:
            other_cluster = MarkerCluster(name="폐교(대부/자체활용)").add_to(m)
            for _, school in other_df.iterrows():
                folium.Marker(
                    location=[school["lat"], school["lon"]],
                    tooltip=f"{school['name']} ({school['usage_status']}, {school['year']}년 폐교)",
                    icon=muted_icon,
                ).add_to(other_cluster)

    # 공식 지정 관광지(STEP 5-C)는 항상 표시 - 카카오 관광명소와 구분되는 별도 이모지
    if not tourism_nearby["tourism"].empty:
        tourism_cluster = MarkerCluster(name="관광지(공식)").add_to(m)
        for _, spot in tourism_nearby["tourism"].iterrows():
            folium.Marker(
                location=[spot["lat"], spot["lon"]],
                tooltip=spot["name"],
                icon=emoji_icon("🏞️"),
            ).add_to(tourism_cluster)

    kakao_emojis = {
        "관광명소": "🎡",
        "키즈카페": "🧸",
        "문화체험": "🏛️",
        "집객시설": "🛍️",
    }
    for category, data in kakao_nearby.items():
        if not show_layers.get(category):
            continue
        cluster = MarkerCluster(name=category).add_to(m)
        for place_name, category_name, address_name, place_lat, place_lon, distance in data["places"]:
            folium.Marker(
                location=[place_lat, place_lon],
                tooltip=place_name,
                icon=emoji_icon(kakao_emojis[category]),
            ).add_to(cluster)

    # 반경이 화면에 딱 맞게 보이도록 위도/경도 범위를 계산해서 자동 줌 조정
    delta_lat = radius_km / 111
    delta_lon = radius_km / (111 * math.cos(math.radians(lat)))
    bounds = [[lat - delta_lat, lon - delta_lon], [lat + delta_lat, lon + delta_lon]]
    m.fit_bounds(bounds)

    # folium_static은 클릭 이벤트를 아예 캡처하지 않는 정적 렌더링이라 클릭 시 사각형이 생기지 않음
    # (width=None이면 st_folium의 use_container_width=True와 동일하게 화면 폭에 맞춰짐)
    folium_static(m, width=None, height=420)
    st.caption(f"📍 직선거리 기준 약 {radius_km:.1f} km 범위 (실제 도로 이동거리와 다를 수 있음)")
    st.caption(
        "🏫 학교 · 📚 도서관 · 🏞️ 관광지(공식) · 🏚️ 폐교(미활용, 강조) 　 "
        "카카오 실시간: 🎡 관광명소 · 🧸 키즈카페 · 🏛️ 문화체험 · 🛍️ 집객시설"
    )
    st.caption("숫자 원은 확대하면 개별 마커로 펼쳐지는 클러스터입니다")

    st.subheader("생활권 인구")

    profile = get_living_area_population(dongs)
    child_ratio = profile["age_0_9"] / profile["total"] * 100 if profile["total"] else 0

    def kpi_card(col, label, value, unit, accent, sub=None):
        sub_html = f'<div class="kpi-sub">{sub}</div>' if sub else ""
        col.markdown(
            f"""
            <div class="kpi-card kpi-{accent}">
                <div class="kpi-label">{label}</div>
                <div class="kpi-value">{value}<span class="kpi-unit">{unit}</span></div>
                {sub_html}
            </div>
            """,
            unsafe_allow_html=True,
        )

    nationwide_child_ratio = get_nationwide_child_ratio()
    if nationwide_child_ratio and profile["total"]:
        gap = child_ratio - nationwide_child_ratio
        child_sub = f"전국 평균 {nationwide_child_ratio:.1f}% 대비 {gap:+.1f}%p"
    else:
        child_sub = None

    row1_col1, row1_col2, row1_col3 = st.columns(3)
    kpi_card(row1_col1, "총인구", f"{profile['total']:,}", "명", "blue")
    kpi_card(row1_col2, "0~9세 (어린이)", f"{profile['age_0_9']:,}", "명", "pink")
    kpi_card(row1_col3, "어린이 비율", f"{child_ratio:.1f}", "%", "pink", sub=child_sub)

    row2_col1, row2_col2 = st.columns(2)
    kpi_card(row2_col1, "10~14세", f"{profile['age_10_14']:,}", "명", "blue")
    kpi_card(row2_col2, "30~49세 (가족수요층)", f"{profile['age_30_49']:,}", "명", "blue")

    st.caption("※ 30~49세는 가족수요층 대리지표이며 실제 부모를 의미하지 않음")

    if profile["unmatched"]:
        st.warning(
            f"일부 동은 최근 행정구역 개편으로 인구 데이터 미포함 ({len(profile['unmatched'])}개)"
        )

    st.subheader("생활권 교육시설")

    counts = facilities["counts"]
    students = facilities["students"]
    edu_col1, edu_col2, edu_col3 = st.columns(3)
    for col, level in (
        (edu_col1, ELEMENTARY), (edu_col2, "중학교"), (edu_col3, "고등학교")
    ):
        sub = f"{students[level]:,}명" if counts[level] else "해당 학교 없음"
        kpi_card(col, level, f"{counts[level]}", "개", "green", sub=sub)

    students_total = facilities["students_total"]
    lower = facilities["students_grade_1_3"]
    # 저학년 비중은 초등학생을 분모로 본다 (중·고 학생을 섞으면 지역 학령구조가 흐려진다)
    elementary = students[ELEMENTARY]
    lower_ratio = lower / elementary * 100 if elementary else 0

    stu_col1, stu_col2 = st.columns(2)
    kpi_card(stu_col1, "전체 학생수", f"{students_total:,}", "명", "green")
    kpi_card(
        stu_col2,
        "저학년 (초1~3) 학생수",
        f"{lower:,}",
        "명",
        "pink",
        # 분모를 함께 보여준다 (초등학생이 수십 명인 농촌 생활권에서 비율만 보면 오해하기 쉽다)
        sub=f"초등학생 {elementary:,}명 중 {lower_ratio:.1f}%" if elementary else None,
    )

    nationwide_ratio = get_nationwide_lower_grade_ratio()
    benchmark = f"(전국 평균 {nationwide_ratio:.1f}%)" if nationwide_ratio else ""
    st.caption(
        "※ 저학년(초1~3)은 어린이 공간의 주 이용연령대로, 수요 규모를 가늠하는 핵심 지표입니다. "
        f"초등학생 중 저학년 비중{benchmark}이 낮으면 학령인구가 줄어드는 지역으로 볼 수 있습니다"
    )

    # 학생수는 교명 매칭으로 붙인 값이라 폐교/분교/교명변경 학교는 비어 있을 수 있다
    school_total = sum(counts.values())
    unmatched_schools = school_total - facilities["matched_total"]
    if unmatched_schools:
        st.caption(
            f"※ 생활권 학교 {school_total}개 중 {unmatched_schools}개는 학생수 미연결 "
            f"(분교·폐교·교명 변경 등)이라 위 학생수 합계에서 빠져 있습니다"
        )

    st.subheader("생활권 폐교 (활용 검토)")

    closed_counts = closed_schools_nearby["counts"]
    closed_total = sum(closed_counts.values())

    if closed_total == 0:
        st.info("생활권 내 폐교 없음")
    else:
        closed_col1, closed_col2 = st.columns(2)
        kpi_card(closed_col1, "전체 폐교", f"{closed_total}", "개", "amber")
        kpi_card(closed_col2, "미활용 (사업 후보)", f"{closed_counts['미활용']}", "개", "red")
        st.caption(f"대부 {closed_counts['대부']}개 · 자체활용 {closed_counts['자체활용']}개")

        if closed_counts["미활용"] > 0:
            unused_names = closed_schools_nearby["closed_schools"].loc[
                closed_schools_nearby["closed_schools"]["usage_status"] == "미활용", "name"
            ].tolist()
            st.markdown(
                f'<div class="highlight-line">🏚️ 미활용 폐교 {closed_counts["미활용"]}곳이 '
                f"사업 후보지로 바로 검토 가능합니다</div>",
                unsafe_allow_html=True,
            )
            shown = unused_names[:10]
            more_suffix = f" 외 {len(unused_names) - 10}곳" if len(unused_names) > 10 else ""
            st.caption(f"🏚️ 미활용: {', '.join(shown)}{more_suffix}")
        else:
            st.caption("※ 생활권 폐교가 모두 활용 중이라 유휴 공간 후보는 없습니다")

    st.subheader("생활권 문화시설")

    library_counts = libraries_nearby["counts"]
    if library_counts["주요도서관"] == 0 and library_counts["작은도서관"] == 0:
        st.info("이 생활권에는 도서관이 없습니다 (어린이 실내활동 공간이 비어 있는 지역)")
    else:
        culture_col1, culture_col2 = st.columns(2)
        kpi_card(culture_col1, "공공·어린이도서관", f"{library_counts['주요도서관']}", "개", "amber")
        kpi_card(culture_col2, "작은도서관", f"{library_counts['작은도서관']}", "개", "amber")

    st.subheader("생활권 관광자원")

    tourism_count = tourism_nearby["count"]
    if tourism_count == 0:
        st.info("이 생활권에는 공식 지정 관광지가 없습니다 (생활밀착형에 가까움)")
    else:
        tourism_col, _blank_col1, _blank_col2 = st.columns(3)
        kpi_card(tourism_col, "관광지", f"{tourism_count}", "개", "lavender")

        spot_names = tourism_nearby["tourism"]["name"].tolist()
        shown = spot_names[:10]
        more_suffix = f" 외 {len(spot_names) - 10}곳" if len(spot_names) > 10 else ""
        st.caption(f"📍 {', '.join(shown)}{more_suffix}")

    st.subheader("관광 방문 현황")

    visitors, visitors_sigungu_nm = get_visitors_for_address(addr)
    if visitors is None:
        if visitors_sigungu_nm is None:
            st.info("검색한 위치의 주소에서 시군구를 알아내지 못해 방문자 데이터를 찾을 수 없습니다")
        else:
            st.info(
                f"'{visitors_sigungu_nm}'은 방문자 통계 집계 대상이 아닙니다 "
                "(출장소 등 일부 지역은 한국관광공사 데이터랩에 포함되지 않습니다)"
            )
    else:
        pattern = visitors["pattern"]
        quartiles = visitors["quartiles"]

        if pattern is not None:
            st.markdown(
                f'<div class="highlight-line">🧭 외지인 비중 {visitors["outsider_ratio"]:.1f}% · '
                f'[{pattern["label"]}] {pattern["detail"]}</div>',
                unsafe_allow_html=True,
            )

        visitor_col1, visitor_col2, visitor_col3 = st.columns(3)
        kpi_card(
            visitor_col1,
            "전체 방문자",
            f"{visitors['visitors_total']:,}",
            "명",
            "teal",
            sub=f"{visitors['days']}일 누적",
        )
        kpi_card(
            visitor_col2,
            "외지인 비중",
            f"{visitors['outsider_ratio']:.1f}",
            "%",
            "lavender",
            sub=(
                f"전국 중위 {quartiles['outsider_ratio_median']:.1f}% 대비 "
                f"{visitors['outsider_ratio'] - quartiles['outsider_ratio_median']:+.1f}%p"
                if quartiles
                else None
            ),
        )
        kpi_card(
            visitor_col3,
            "주말 유입 배수",
            f"{visitors['weekend_lift']:.2f}",
            "배",
            "tangerine",
            sub=(
                f"평일 {visitors['outsider_weekday_avg']:,}명 → "
                f"주말 {visitors['outsider_weekend_avg']:,}명"
            ),
        )

        st.caption(
            f"현지인 {visitors['visitors_local']:,}명 · "
            f"외지인 {visitors['visitors_outsider']:,}명 · "
            f"외국인 {visitors['visitors_foreign']:,}명"
        )

        base_start = visitors["base_start_ymd"]
        base_end = visitors["base_end_ymd"]
        st.caption(
            f"※ 기준 기간: {base_start[:4]}-{base_start[4:6]}-{base_start[6:]} ~ "
            f"{base_end[:4]}-{base_end[4:6]}-{base_end[6:]} ({visitors['days']}일) · "
            f"{DATA_CAVEAT}"
        )
        if quartiles:
            st.caption(
                f"※ '{pattern['label']}' 판단은 전국 {quartiles['sigungu_count']}개 시군구 분포 기준입니다 "
                f"(외지인 비중 3사분위 {quartiles['outsider_ratio_q3']:.1f}%, "
                f"주말 배수 3사분위 {quartiles['weekend_lift_q3']:.2f}배 이상이면 상위권)"
            )

    # 체류시간·숙박일수는 데이터랩 쪽 지표라 위 방문자수(API)와 출처가 다르다
    datalab_sigungu_cd, datalab_sigungu_nm = resolve_sigungu_cd(addr)
    datalab = get_sigungu_datalab(datalab_sigungu_cd) if datalab_sigungu_cd else None

    if datalab is not None:
        stay_quartiles = datalab["quartiles"]
        stay_col1, stay_col2 = st.columns(2)
        kpi_card(
            stay_col1,
            "평균 체류시간",
            f"{datalab['avg_stay_hours']}",
            "시간",
            "violet",
            sub=(
                f"전국 중위 {stay_quartiles['stay_minutes_median'] / 60:.1f}시간 대비 "
                f"{datalab['stay_vs_median'] / 60:+.1f}시간"
                if stay_quartiles
                else None
            ),
        )
        kpi_card(
            stay_col2,
            "평균 숙박일수",
            f"{datalab['avg_stay_nights']:.2f}",
            "일",
            "violet",
            sub=(
                f"전국 중위 {stay_quartiles['stay_nights_median']:.2f}일 대비 "
                f"{datalab['nights_vs_median']:+.2f}일"
                if stay_quartiles
                else None
            ),
        )

        notes = [f"※ 체류·숙박은 {DATALAB_SOURCE} 기준 ({datalab['sigungu_nm']})"]
        if datalab["fallback_from"]:
            notes.append(
                "데이터랩은 분구를 합친 시 단위로 제공하므로 구가 아닌 "
                f"{datalab['sigungu_nm']} 전체 값입니다"
            )
        if datalab["period_merged"]:
            notes.append("행정구역 통합 지역이라 통합 전후 기간을 합산한 값입니다")
        st.caption(" · ".join(notes))

        rank_hits = get_search_rank_for_sigungu(datalab["sigungu_cd"])
        if len(rank_hits):
            places = ", ".join(
                f"{row.rank}위 {row.place_name}({row.category_mid})"
                for row in rank_hits.sort_values("rank").itertuples(index=False)
            )
            st.markdown(
                f'<div class="highlight-line">🔍 전국 관광지 검색순위 TOP 100에 '
                f"이 지역이 있습니다 - {places}</div>",
                unsafe_allow_html=True,
            )

    st.subheader("생활권 주변 시설 (카카오)")

    kakao_counts = {category: kakao_nearby[category]["count"] for category in KAKAO_CATEGORIES}
    kids_count = kakao_counts["키즈카페"]

    if not any(kakao_counts.values()):
        # 4개 카테고리가 모두 0이면 실제로 없는 것인지 검색이 실패한 것인지 구분되지 않는다
        st.warning(
            "카카오 검색 결과가 없습니다. 정말 주변 시설이 없는 지역일 수도 있지만, "
            "API 키 설정이나 일일 호출량 한도 문제일 수도 있어 확인이 필요합니다."
        )
    else:
        kakao_col1, kakao_col2, kakao_col3, kakao_col4 = st.columns(4)
        kpi_card(kakao_col1, "관광명소", f"{kakao_counts['관광명소']}", "개", "teal")
        kpi_card(
            kakao_col2,
            "키즈카페 (경쟁시설)",
            f"{kids_count}",
            "개",
            "rose",
            sub="경쟁시설 없음" if kids_count == 0 else None,
        )
        kpi_card(kakao_col3, "문화체험", f"{kakao_counts['문화체험']}", "개", "violet")
        kpi_card(kakao_col4, "집객시설", f"{kakao_counts['집객시설']}", "개", "tangerine")

        if kids_count == 0:
            st.info(
                "생활권 내 키즈카페가 없습니다. 어린이 실내공간 수요를 받아줄 민간시설이 "
                "없다는 뜻이라, 공공 어린이 공간의 필요도가 높은 지역으로 볼 수 있습니다."
            )

    st.caption("※ 카카오 실시간 검색 결과이며, 앞의 인구/학교/도서관/관광지와 달리 매번 최신 상태를 반영합니다")

    st.subheader("지역 관광 상세")

    region_detail = get_region_detail(datalab_sigungu_cd) if datalab_sigungu_cd else None

    if region_detail is None:
        registered = list_registered_regions()
        registered_text = (
            " · ".join(f"{name}" for _code, name in registered) if registered else "없음"
        )
        st.info(
            "이 지역은 상세 데이터가 아직 등록되지 않았습니다 (추후 추가 예정). "
            "위의 전국 기준 지표만 참고해주세요." + "\n\n" +
            f"현재 등록된 지역: {registered_text}"
        )
    else:
        summary = summarize_level_and_trend(region_detail)
        if summary:
            st.markdown(
                f'<div class="highlight-line">📈 {region_detail["region_nm"]} · {summary}</div>',
                unsafe_allow_html=True,
            )

        st.caption(
            "아래 증감률은 전년동기 대비 **추세**입니다. 위 카드의 체류시간·숙박일수 "
            "**수준**(전국 중위 대비)과 함께 봐야 합니다 - 수준이 낮아도 추세가 오르면 "
            "개선 중인 지역입니다."
        )

        metric_cols = st.columns(len(region_detail["metrics"]))
        for col, metric in zip(metric_cols, region_detail["metrics"]):
            if metric["level_vs_median"] is None:
                sub = metric["verdict"]
            else:
                sub = (
                    f"수준 {metric['level_vs_median']:+}{metric['unit']}"
                    f" · {metric['verdict']}"
                )
            kpi_card(
                col,
                f"{metric['label']} 추세",
                f"{metric['trend_pct']:+.1f}",
                "%",
                "teal" if (metric["trend_pct"] or 0) > 0 else "amber",
                sub=sub,
            )

        trend_cols = st.columns(len(region_detail["trends"]))
        for col, trend in zip(trend_cols, region_detail["trends"]):
            kpi_card(
                col,
                f"{trend['label']} 추세",
                f"{trend['trend_pct']:+.1f}",
                "%",
                "lavender",
            )
        st.caption(
            f"※ 참고: {region_detail['sido_nm']} 전체 방문자 증가율 "
            f"{region_detail['sido_growth_pct']:+.1f}%"
        )

        flow_col1, flow_col2 = st.columns(2)
        with flow_col1:
            st.markdown("**🚗 어디서 오나 (유입 TOP 5)**")
            for item in region_detail["inflow"]:
                st.markdown(
                    f"{item['rank']}. {item['counterpart_nm']} &nbsp; **{item['ratio']}%**",
                    unsafe_allow_html=True,
                )
        with flow_col2:
            st.markdown("**🚗 어디로 가나 (유출 TOP 5)**")
            for item in region_detail["outflow"]:
                st.markdown(
                    f"{item['rank']}. {item['counterpart_nm']} &nbsp; **{item['ratio']}%**",
                    unsafe_allow_html=True,
                )

        st.caption(f"※ 출처: {DATALAB_SOURCE} · {TREND_CAVEAT}")
        st.caption("※ 관광 성격이 비슷한 지역은 아래 '유사 레퍼런스'에서 봅니다")

    st.subheader("유사 레퍼런스 (참고할 지역·시설)")

    st.caption(
        "벤치마킹할 **지역**과, 생활권 안에서 이미 같은 수요를 받고 있는 **시설**을 모았습니다. "
        "출처가 서로 달라 기준도 다릅니다 - 아래 각 항목에 표기했습니다."
    )

    st.markdown("**🔗 관광 성격이 비슷한 지역**")
    if region_detail is not None and region_detail["similar_regions"]:
        st.markdown(
            f"{region_detail['region_nm']} ≈ "
            + " · ".join(region_detail["similar_regions"])
        )
        st.caption(
            f"기준: {DATALAB_SOURCE}이 관광 지표(방문자·체류·소비)가 유사하다고 묶은 지역입니다. "
            "사업 사례·성과를 비교할 후보로 쓰세요."
        )
    else:
        st.caption(
            "이 지역은 유사 지역 데이터가 등록되지 않았습니다 "
            "(데이터랩 지역 상세가 등록된 지역에서만 제공)"
        )

    st.markdown("**🏢 생활권 내 어린이 공간 레퍼런스**")
    st.caption(
        "앞 섹션들에 흩어져 있던 시설을 어린이 공간사업 관점으로 다시 묶었습니다 "
        "(새 데이터가 아니라 같은 수치의 재분류입니다)."
    )

    child_centers_nearby = get_child_centers_in_circle(lat, lon, radius_km)
    culture_nearby = get_culture_in_circle(lat, lon, radius_km)
    public_facilities_nearby = get_public_facilities_in_circle(lat, lon, radius_km)

    child_spaces = classify_child_spaces(
        facilities,
        libraries_nearby,
        closed_schools_nearby,
        kakao_nearby,
        tourism_count,
        child_centers=child_centers_nearby,
        culture=culture_nearby,
        public_facilities=public_facilities_nearby,
    )
    space_icons = {
        "직접 경쟁": ("🎯", "rose"),
        "공공 돌봄·교육": ("🏛️", "amber"),
        "가족 여가": ("🎪", "teal"),
        "프로그램 운영 공간": ("📚", "lavender"),
        "체험 레퍼런스": ("🔬", "violet"),
        "부지 후보": ("🏚️", "green"),
    }
    group_items = list(child_spaces.items())
    for row_start in range(0, len(group_items), 3):
        row_groups = group_items[row_start:row_start + 3]
        space_cols = st.columns(3)
        for col, (group_name, group) in zip(space_cols, row_groups):
            icon, accent = space_icons[group_name]
            kpi_card(col, f"{icon} {group_name}", f"{group['count']}", "개", accent)

    for group_name, group in child_spaces.items():
        icon, _accent = space_icons[group_name]
        with st.expander(f"{icon} {group_name} {group['count']}개 — {group['note']}"):
            if not group["items"]:
                st.caption("생활권 안에 해당 시설이 없습니다")
            else:
                shown = group["items"][:15]
                st.markdown(" · ".join(shown))
                if len(group["items"]) > 15:
                    st.caption(f"외 {len(group['items']) - 15}곳")
            if group_name == "공공 돌봄·교육":
                st.caption(
                    f"어린이도서관 {group['child_library_count']}개 · "
                    f"작은도서관 {group['small_library_count']}개 · "
                    f"공공도서관 {group['public_library_count']}개 · "
                    f"지역아동센터 {group['child_center_count']}개"
                )
                if group["child_center_count"]:
                    st.caption(
                        f"🧒 지역아동센터 아동 돌봄 수용 규모: 정원 "
                        f"{group['child_center_capacity']:,}명 / 현원 "
                        f"{group['child_center_enrolled']:,}명"
                    )
            if group_name == "가족 여가" and group["breakdown"]:
                st.caption(
                    " · ".join(f"{k} {v}개" for k, v in group["breakdown"].items())
                )
            if group_name == "프로그램 운영 공간":
                st.caption(
                    f"같은 개방시설 중 체육시설은 {group['sports_count']}개입니다 "
                    "(프로그램 공간에는 넣지 않았습니다)"
                )
            if group_name == "부지 후보":
                st.caption(
                    f"미활용 폐교 {group['unused_school_count']}개 · "
                    f"수용 200명 이상 개방시설 {group['large_facility_count']}개"
                )
            if group_name == "체험 레퍼런스":
                excluded = group.get("excluded_count", 0)
                excluded_text = (
                    f" · 주차장·충전소 등 부대시설 {excluded}개 제외" if excluded else ""
                )
                st.caption(
                    f"카카오 문화체험 {group['culture_count']}개 + "
                    f"공식 관광지 {group['tourism_count']}개{excluded_text} "
                    "(관광지는 목록이 위 '생활권 관광자원'에 있습니다)"
                )
            st.caption(f"출처: {group['source']}")

    st.markdown("**📐 어린이 공간 밀도·포화도**")

    benchmarks = get_nationwide_benchmarks()
    circle_public_spaces = child_spaces["공공 돌봄·교육"]["count"]
    circle_children = profile["age_0_9"]
    density = assess_density(
        circle_children,
        circle_public_spaces,
        benchmarks,
        child_center_count=child_spaces["공공 돌봄·교육"]["child_center_count"],
    )

    if density is None:
        st.info("밀도 기준선 데이터가 없습니다 (python -m ingest.build_child_space 실행 필요)")
    else:
        ratio_text = (
            f"{density['children_per_space']:,}" if density["children_per_space"] is not None else "-"
        )
        st.markdown(
            f'<div class="highlight-line">📐 [{density["label"]}] '
            f"어린이 {ratio_text}명당 공공 어린이공간 1개 · {density['interpretation']}</div>",
            unsafe_allow_html=True,
        )

        density_col1, density_col2, density_col3 = st.columns(3)
        kpi_card(density_col1, "생활권 0~9세", f"{circle_children:,}", "명", "pink")
        kpi_card(density_col2, "공공 어린이공간", f"{circle_public_spaces}", "개", "amber")
        kpi_card(
            density_col3,
            "공간당 어린이",
            ratio_text,
            "명",
            "blue",
            sub=(
                f"전국 중위 {benchmarks['ratio_median']:,.0f}명 "
                f"(여유 {benchmarks['ratio_q1']:,.0f} / 부족 {benchmarks['ratio_q3']:,.0f})"
            ),
        )

        if density["caution"]:
            st.warning(f"⚠️ {density['caution']}")
        if density.get("coverage_note"):
            st.warning(f"📋 {density['coverage_note']}")

        st.caption(
            f"기준: 전국 {benchmarks['sigungu_count']}개 시군구 분포의 사분위입니다. "
            "분자는 **생활권 원 안**의 공공 돌봄·교육 공간 수(도서관 + 지역아동센터), "
            "분모는 **생활권 0~9세 인구**입니다. "
            "비교 기준선은 시군구 단위라 단위가 완전히 같지는 않습니다 (비율끼리의 비교)."
        )
        st.caption(
            "※ 키즈카페는 카카오 실시간 검색이라 전국 집계를 낼 수 없어 밀도 계산에서 "
            "제외했습니다. 민간 경쟁 규모는 위 '🎯 직접 경쟁' 개수로 보세요."
        )

    if region_detail is not None and region_detail["similar_regions"]:
        st.markdown("**⚖️ 유사 지역과 비교 (시군구 단위)**")
        comparison = compare_with_similar(
            datalab_sigungu_cd, region_detail["similar_regions"]
        )
        if comparison is None or comparison.empty:
            st.caption("유사 지역의 어린이 공간 데이터를 찾지 못했습니다")
        else:
            table = comparison.rename(columns={
                "sigungu_nm": "시군구",
                "children_0_9": "0~9세",
                "public_child_spaces": "공공 어린이공간",
                "children_per_space": "공간당 어린이",
            })
            st.dataframe(table, hide_index=True, use_container_width=True)
            st.caption(
                "생활권(원)이 아니라 **시군구 전체** 기준입니다. "
                "유사 지역은 관광 지표로 묶인 곳이라 어린이 공간 사정은 다를 수 있습니다."
            )

    st.subheader("인기·트렌드")

    st.caption(
        "인기를 재는 방법이 셋이고 각각 답하는 질문이 다릅니다. "
        "**검색 빅데이터**(전국에서 어디를 많이 찾나)와 "
        "**블로그·카페 언급**(이 지역에서 무엇이 회자되나)은 서로 다른 신호입니다."
    )

    st.markdown("**📈 전국 관심도 월별 추이 — 계절성**")
    st.caption(
        "기준: 데이터랩 **검색 빅데이터**(전국 단위 상대지수). "
        "\"언제 사람들이 국내관광에 관심을 갖나\"에 답합니다 - 개장·행사 시기 잡을 때 씁니다."
    )

    monthly = get_monthly_interest()
    if monthly is None:
        st.info("전국 관광 트렌드 데이터가 없습니다 (python -m ingest.build_datalab 실행 필요)")
    else:
        chart_data = monthly.dropna(subset=["interest_index"]).copy()
        # 'YYYYMM' -> 월 단위 날짜로 바꿔 시간축이 제대로 눕게 한다
        chart_data["month"] = pd.to_datetime(chart_data["base_ym"], format="%Y%m")

        # 한 계열이라 범례 없이 색 하나만 쓴다 (제목이 계열을 설명)
        line_color = "#1D8FB5"
        hover = alt.selection_point(
            fields=["month"], nearest=True, on="pointerover", empty=False, clear="pointerout"
        )
        base = alt.Chart(chart_data).encode(
            x=alt.X(
                "month:T",
                title=None,
                axis=alt.Axis(format="%y.%m", tickCount=8, grid=False,
                              labelColor="#898781", domainColor="#C3C2B7", tickColor="#C3C2B7"),
            ),
            y=alt.Y(
                "interest_index:Q",
                title="관심도 지수",
                axis=alt.Axis(grid=True, gridColor="#E1E0D9", gridWidth=1,
                              labelColor="#898781", titleColor="#898781", domain=False, ticks=False),
            ),
        )
        line = base.mark_line(color=line_color, strokeWidth=2)
        points = base.mark_circle(color=line_color, size=64, opacity=0).encode(
            opacity=alt.condition(hover, alt.value(1), alt.value(0)),
            tooltip=[
                alt.Tooltip("month:T", title="기준월", format="%Y-%m"),
                alt.Tooltip("interest_index:Q", title="관심도 지수"),
                alt.Tooltip("visitor_growth_pct:Q", title="방문자 증감률(%)"),
            ],
        ).add_params(hover)
        rule = base.mark_rule(color="#C3C2B7", strokeWidth=1).transform_filter(hover)

        st.altair_chart(
            (line + rule + points).properties(height=260, background="#FCFCFB"),
            use_container_width=True,
        )

        latest = chart_data.iloc[-1]
        peak = chart_data.loc[chart_data["interest_index"].idxmax()]
        st.caption(
            f"국내관광 관심도(상대지수) {chart_data['base_ym'].min()} ~ {chart_data['base_ym'].max()} · "
            f"최고 {peak['base_ym']} {peak['interest_index']:.0f} · "
            f"최근 {latest['base_ym']} {latest['interest_index']:.0f}"
        )
        st.caption(
            "※ 관심도는 절대 검색량이 아니라 기간 내 상대지수(0~100)이며, "
            "가장 최근 달은 집계가 덜 찬 상태일 수 있습니다"
        )

        with st.expander("📊 월별 수치 표로 보기"):
            table = monthly.rename(columns={
                "base_ym": "기준연월",
                "interest_index": "관심도 지수",
                "visitor_count": "방문자수",
                "visitor_growth_pct": "방문자 증감률(%)",
                "spending": "관광지출액",
                "spending_growth_pct": "지출 증감률(%)",
            })
            st.dataframe(
                table[["기준연월", "관심도 지수", "방문자수", "방문자 증감률(%)",
                       "관광지출액", "지출 증감률(%)"]],
                hide_index=True,
                use_container_width=True,
            )

    st.markdown("**📊 전국 검색순위 TOP — 큰 그림**")
    st.caption(
        "기준: 데이터랩 **검색 빅데이터**(전국 관광지 순위). "
        "\"전국에서 어디를 많이 찾나\"에 답합니다 - 우리 지역이 들어 있는지, "
        "어떤 유형이 상위인지 보는 용도입니다. 이 지역 맞춤 추천은 아닙니다."
    )

    rank_top = get_search_rank_top(10)
    if rank_top is not None:
        with st.expander("전국 관광지 검색순위 TOP 10 펼쳐보기"):
            rank_table = rank_top.rename(columns={
                "rank": "순위",
                "place_name": "관광지명",
                "sido_nm": "시도",
                "category_mid": "중분류",
                "category_sub": "소분류",
            })
            st.dataframe(
                rank_table[["순위", "관광지명", "시도", "중분류", "소분류"]],
                hide_index=True,
                use_container_width=True,
            )
            st.caption("전국 TOP 100 중 상위 10곳입니다")

    st.caption(f"※ 위 두 항목 출처: {DATALAB_SOURCE} · {DATALAB_CAVEAT}")

    st.markdown("**🔍 목적별 인기공간 — 이 지역 맞춤**")
    st.caption(
        "기준: 카카오 **블로그·카페 언급**(검색 빅데이터가 아님). "
        "\"이 지역에서 아이랑 갈 만한 곳으로 무엇이 회자되나\"에 답합니다. "
        "실제 방문객 수가 아니라 온라인에서 글이 많이 쓰인 정도이고, "
        "**월별 언급 변화(↑뜨는 곳/↓지는 곳)**까지 볼 수 있습니다."
    )
    region_label = region_detail["region_nm"] if region_detail else (datalab_sigungu_nm or name)
    st.info(
        f"왼쪽 메뉴의 **인기 공간**에서 '{region_label}' + 목적 키워드(예: 어린이, 가족 나들이)로 "
        "분석하면 언급 순위와 월별 변화를 볼 수 있습니다. "
        "블로그·카페를 150건씩 읽어오는 작업이라 별도 화면으로 두었습니다."
    )

    st.subheader("확장 지역 비교")

    st.caption(
        "생활권 원에 **중심점이 들어오는 시군구**를 모아 지표별로 비교합니다. "
        "대상지 한 곳만 보는 것이 아니라 '어디까지 같은 생활권으로 묶이는지'를 보는 용도입니다."
    )

    # 생활권 반경을 그대로 쓰면 10~30분으로는 걸치는 시군구가 거의 없다.
    # 반대로 생활권 분을 60분으로 올리면 위 섹션들(인구·시설)까지 다른 범위가 되어버린다.
    # 그래서 이 섹션만 쓰는 시간을 따로 둔다.
    expand_col1, expand_col2 = st.columns([1, 2])
    expand_minutes = expand_col1.number_input(
        "확장 범위 (분)",
        min_value=5,
        max_value=240,
        value=max(minutes, 60),
        step=5,
        key="expand_minutes",
        help="이 섹션에만 쓰는 시간입니다. 위 생활권 설정은 그대로 둡니다",
    )
    expand_radius_km = calc_radius_km(speed_kmh, int(expand_minutes))
    expand_col2.caption(
        f"확장 반경: 직선거리 기준 약 {expand_radius_km:.1f}km "
        f"({int(expand_minutes)}분 × {speed_kmh}km/h)"
    )

    expand_preview = get_backyard_sigungu(lat, lon, expand_radius_km)
    if expand_preview.empty:
        st.info(
            f"확장 반경 {expand_radius_km:.1f}km 안에 중심점이 들어오는 시군구가 없습니다. "
            "확장 범위를 늘려보세요."
        )
    else:
        st.markdown(
            f'<div class="highlight-line">🗺️ 확장 지역 {len(expand_preview)}개 · '
            + " · ".join(
                f"{row.sigungu_nm.split()[-1]}({row.distance_km:.0f}km)"
                for row in expand_preview.head(8).itertuples(index=False)
            )
            + ("" if len(expand_preview) <= 8 else f" 외 {len(expand_preview) - 8}개")
            + "</div>",
            unsafe_allow_html=True,
        )

        expand_cache = st.session_state.setdefault("expand_metrics_cache", {})
        expand_key = (round(lat, 5), round(lon, 5), round(expand_radius_km, 2))

        if expand_key not in expand_cache:
            st.caption(
                "지표 비교는 시군구마다 카카오 키즈카페 검색이 필요해 버튼을 눌러야 실행됩니다 "
                f"(현재 {len(expand_preview)}개 지역)."
            )
            if st.button("📊 확장 지역 지표 비교", key="expand_run"):
                status = st.empty()

                def on_expand_progress(message, _status=status):
                    _status.info(message)

                with st.spinner("확장 지역 지표를 계산하는 중..."):
                    expand_cache[expand_key] = get_backyard_metrics(
                        lat, lon, expand_radius_km, progress_callback=on_expand_progress
                    )
                status.empty()
                st.rerun()

        expanded = expand_cache.get(expand_key)
        if expanded is not None and not expanded.empty:
            st.markdown(f"**확장 지역 시군구 비교 (총 {len(expanded)}개)**")
            expand_tabs = st.tabs(
                ["🧒 어린이 인구", "🏫 초등학교", "🧸 키즈카페", "🏚️ 미활용 폐교", "📚 도서관"]
            )
            with expand_tabs[0]:
                render_metric_cards(
                    expanded, "age_0_9", "0~9세 어린이 인구", "명", area_label="확장 지역"
                )
            with expand_tabs[1]:
                render_metric_cards(
                    expanded, "elementary_count", "초등학교", "개", area_label="확장 지역"
                )
            with expand_tabs[2]:
                render_metric_cards(
                    expanded, "kids_cafe_count", "키즈카페", "개", area_label="확장 지역"
                )
            with expand_tabs[3]:
                render_metric_cards(
                    expanded, "unused_closed_school_count", "미활용 폐교", "개",
                    area_label="확장 지역",
                )
            with expand_tabs[4]:
                render_metric_cards(
                    expanded, "library_count", "도서관", "개", area_label="확장 지역"
                )
            st.caption(
                "※ 시군구 중심점 기준이라 원에 걸치기만 한 지역은 빠질 수 있습니다. "
                "어린이 인구·초등학교·폐교·도서관은 공공데이터, 키즈카페는 카카오 실시간 검색입니다."
            )

    st.subheader("지역 사업 뉴스·이슈")

    region_name = region_from_address(addr)
    if region_name is None:
        st.info("검색한 위치의 주소에서 시군구를 알아내지 못해 뉴스를 찾을 수 없습니다")
    else:
        news_cache = st.session_state.setdefault("region_news_cache", {})
        st.caption(
            f"'{region_name}' + 사업 키워드 {len(BUSINESS_KEYWORDS)}개로 최근 "
            f"{RECENT_MONTHS}개월 기사를 찾습니다 (카카오 호출이 많아 버튼을 눌러야 실행됩니다)"
        )

        if region_name not in news_cache:
            if st.button(f"🗞️ '{region_name}' 사업 뉴스 검색", key="region_news_run"):
                progress_bar = st.progress(0.0, text="뉴스 검색 준비 중...")

                def on_progress(index, total, keyword, _bar=progress_bar):
                    _bar.progress(index / total, text=f"({index}/{total}) '{keyword}' 검색 중...")

                news_cache[region_name] = get_region_news(
                    region_name, progress_callback=on_progress
                )
                progress_bar.empty()
                st.rerun()

        news = news_cache.get(region_name)
        if news is not None:
            news_meta = news["meta"]
            news_items = news["items"]

            with st.expander("📑 수집·필터 내역 보기"):
                dropped = news_meta["dropped"]
                st.markdown(
                    f"""
- **검색 질의**: "{region_name}" + 키워드 {len(news_meta['keywords'])}개
  ({', '.join(news_meta['keywords'])})
- **카카오 호출**: {news_meta['api_calls']}회 (키워드당 {news_meta['api_calls'] // len(news_meta['keywords'])}페이지)
- **수집 {news_meta['collected']:,}건 → 최종 {news_meta['kept']}건**
- **걸러낸 내역**: 지역명 불일치 {dropped['지역명']:,} · {RECENT_MONTHS}개월 초과 {dropped['날짜']:,}
  · 비언론 도메인 {dropped['도메인']} · 섹션 페이지 {dropped['제목']} · 키워드 미포함 {dropped['키워드']}

📌 카카오에는 뉴스 전용 검색이 없어 **웹문서 검색**을 씁니다. "고령"이 노인(高齡)으로
잡히거나 다른 지역 기사가 섞여 들어오기 때문에, 지역명이 실제로 등장하는 글만 남기는
필터가 가장 많은 양을 걸러냅니다.

⚠️ 언론 기사 외에 보도자료·공고가 섞일 수 있고, 반대로 지역명을 줄여 쓴 기사
("고령군" 대신 "고령")는 누락될 수 있습니다.
"""
                )

            if not news_items:
                st.info(
                    f"최근 {RECENT_MONTHS}개월 내 '{region_name}' 관련 사업 뉴스가 없습니다. "
                    "사업 이슈가 활발하지 않은 지역이거나, 기사에서 지역명을 다르게 "
                    "표기했을 수 있습니다."
                )
            else:
                st.markdown(
                    f'<div class="highlight-line">🗞️ 최근 {RECENT_MONTHS}개월 '
                    f"'{region_name}' 관련 사업 뉴스 {len(news_items)}건</div>",
                    unsafe_allow_html=True,
                )

                NEWS_SHOW_COUNT = 20
                item_divs = []
                for article in news_items[:NEWS_SHOW_COUNT]:
                    badges = "".join(
                        f'<span class="news-keyword">{keyword}</span>'
                        for keyword in article["matched_keywords"]
                    )
                    item_divs.append(
                        '<div class="news-item">'
                        f'<div class="news-meta">{article["published"].strftime("%Y-%m-%d")}'
                        f' · {article["source"]}</div>'
                        f'<div class="news-title">'
                        f'<a href="{article["url"]}" target="_blank">{article["title"]}</a></div>'
                        f'<div class="news-keywords">{badges}</div>'
                        "</div>"
                    )
                st.markdown("".join(item_divs), unsafe_allow_html=True)

                if len(news_items) > NEWS_SHOW_COUNT:
                    st.caption(f"※ 최신 {NEWS_SHOW_COUNT}건만 표시 (총 {len(news_items)}건)")

                if st.button("🔄 다시 검색", key="region_news_refresh"):
                    news_cache.pop(region_name, None)
                    st.rerun()

    st.subheader(f"생활권 포함 행정동 (총 {len(dongs)}개)")
    if dongs.empty:
        st.info("반경 안에 포함된 행정동이 없습니다.")
    else:
        table = dongs.rename(columns={"ADM_NM": "행정동명", "distance_km": "거리(km)"})[
            ["행정동명", "거리(km)"]
        ]
        table.insert(0, "순번", range(1, len(table) + 1))
        table["거리(km)"] = table["거리(km)"].round(2)
        st.dataframe(table, hide_index=True, use_container_width=True)
else:
    st.info("기준 주소나 장소명을 검색해주세요.")
