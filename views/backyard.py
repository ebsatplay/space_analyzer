"""배후권 비교 - 거리 기반 방문 가능권 시군구를 추출해서 지표별로 비교한다.

실행: streamlit run app.py (메뉴에서 "배후권 비교" 선택)
"""

import streamlit as st

from analysis.backyard import get_backyard_metrics
from analysis.living_area import calc_radius_km
from services.kakao_service import find_location
from views._theme import apply_theme, page_header, render_metric_cards

apply_theme()
page_header("배후권 비교", "이 시설에 올 만한 지역들을 비교")

st.warning(
    "⚠️ 이 결과는 실제 방문객 유입 데이터가 아니라, "
    "직선거리 기준으로 \"올 수 있을 만한\" 지역을 추정한 것입니다."
)

st.markdown('<div class="search-section-label">위치 검색</div>', unsafe_allow_html=True)
address = st.text_input(
    "시설 주소 또는 장소명",
    label_visibility="collapsed",
    placeholder="예: 포항시청, 고령군청, 파주놀이구름",
)

col1, col_custom, col2 = st.columns([2, 1, 2])
preset_minutes = col1.radio(
    "배후권 시간", [30, 60, 90, "직접 입력"],
    index=1,
    format_func=lambda m: m if isinstance(m, str) else f"{m}분",
    horizontal=True,
    key="backyard_minutes",
)
custom_minutes = col_custom.number_input(
    "직접 입력 (분)",
    min_value=1,
    max_value=240,
    value=45,
    step=5,
    key="backyard_minutes_custom",
    disabled=preset_minutes != "직접 입력",
    help="왼쪽에서 '직접 입력'을 고르면 이 값이 쓰입니다",
)
minutes = int(custom_minutes) if preset_minutes == "직접 입력" else int(preset_minutes)

speed_kmh = col2.slider(
    "평균 속도 (km/h)",
    min_value=20,
    max_value=50,
    value=30,
    key="backyard_speed",
    help="직선거리 환산용 평균 속도",
)

if st.button("배후권 분석", type="primary"):
    try:
        result = find_location(address)
    except Exception as e:
        st.error(f"검색 중 오류가 발생했습니다: {e}")
        result = None

    if result:
        candidates, method = result
        st.session_state["backyard_candidates"] = candidates
        st.session_state["backyard_method"] = method
        st.session_state.pop("backyard_selected_place", None)
    else:
        st.session_state["backyard_candidates"] = None
        st.warning("위치를 찾을 수 없습니다. 다른 주소나 장소명을 입력해보세요")

candidates = st.session_state.get("backyard_candidates")


if candidates:
    method = st.session_state.get("backyard_method", "")

    if len(candidates) == 1:
        selected = candidates[0]
    else:
        options = [f"{name} ({addr})" for name, addr, _lat, _lon in candidates]
        chosen = st.radio(
            "여러 곳이 검색되었습니다. 선택하세요", options, key="backyard_selected_place"
        )
        selected = candidates[options.index(chosen)]

    name, addr, lat, lon = selected
    st.success(f"[{method}] {name} ({addr}) - 위도: {lat}, 경도: {lon}")

    radius_km = calc_radius_km(speed_kmh, minutes)
    st.caption(f"📍 배후권 반경: 직선거리 기준 약 {radius_km:.1f}km ({minutes}분 × {speed_kmh}km/h)")

    # 지표별로 다시 계산하지 않도록 (위치, 반경) 기준으로 세션에 캐싱
    metrics_cache = st.session_state.setdefault("backyard_metrics_cache", {})
    cache_key = (round(lat, 5), round(lon, 5), round(radius_km, 2))

    if cache_key not in metrics_cache:
        status = st.empty()

        def on_progress(msg, _status=status):
            _status.info(msg)

        with st.spinner("배후권 지표를 계산하는 중..."):
            metrics_cache[cache_key] = get_backyard_metrics(lat, lon, radius_km, progress_callback=on_progress)
        status.empty()

    merged = metrics_cache[cache_key]

    if merged.empty:
        st.info("배후권 안에 시군구가 없습니다. 배후권 시간이나 속도를 늘려보세요.")
    else:
        st.subheader(f"배후권 시군구 비교 (총 {len(merged)}개)")

        tab_labels = ["🧒 어린이 인구", "🏫 초등학교", "🧸 키즈카페", "🏚️ 미활용 폐교", "📚 도서관"]
        tabs = st.tabs(tab_labels)

        with tabs[0]:
            render_metric_cards(merged, "age_0_9", "0~9세 어린이 인구", "명")
        with tabs[1]:
            render_metric_cards(merged, "elementary_count", "초등학교", "개")
        with tabs[2]:
            render_metric_cards(merged, "kids_cafe_count", "키즈카페", "개")
        with tabs[3]:
            render_metric_cards(merged, "unused_closed_school_count", "미활용 폐교", "개")
        with tabs[4]:
            render_metric_cards(merged, "library_count", "도서관", "개")
else:
    st.info("주소나 장소명을 입력하고 [배후권 분석]을 눌러주세요.")
