"""대상지 보고서 - 주소/지역을 입력하면 조사 보고서를 Word로 만들어 준다.

실행: streamlit run app.py (메뉴에서 "대상지 보고서" 선택)
"""

import streamlit as st

from analysis.report_data import DEFAULT_MINUTES, DEFAULT_SPEED_KMH, collect_report_data
from analysis.report_docx import build_file_name, build_report
from analysis.survey_pdf import extract_pages, select_relevant_text
from services.kakao_service import find_location
from views._theme import apply_theme, page_header

apply_theme()
page_header("대상지 보고서", "분석 결과를 한 편의 조사 보고서로 묶어 드립니다")

st.caption(
    "주소나 지역명을 넣으면 생활권 인구·가구, 교육·학생, 주변 시설 현황을 모아 "
    "Word(.docx) 보고서로 만듭니다. 수치만 담고 해석·제언은 넣지 않습니다."
)

st.markdown('<div class="search-section-label">대상지 검색</div>', unsafe_allow_html=True)
search_col, button_col = st.columns([4, 1])
address_input = search_col.text_input(
    "주소 또는 지역명",
    placeholder="예: 고령군청, 경북 고령군 대가야읍",
    label_visibility="collapsed",
)
if button_col.button("검색", use_container_width=True):
    if not address_input.strip():
        st.warning("주소나 지역명을 입력해주세요.")
    else:
        result = find_location(address_input.strip())
        if result is None:
            st.error("위치를 찾지 못했습니다. 다른 주소나 장소명으로 시도해주세요.")
        else:
            candidates, method = result
            st.session_state["report_candidates"] = candidates
            st.session_state["report_method"] = method
            st.session_state.pop("report_data", None)

candidates = st.session_state.get("report_candidates")
selected = None
if candidates:
    method = st.session_state.get("report_method", "")
    if len(candidates) == 1:
        selected = candidates[0]
    else:
        options = [f"{name} ({addr})" for name, addr, _lat, _lon in candidates]
        chosen = st.selectbox("검색 결과에서 대상지를 골라주세요", options, key="report_pick")
        selected = candidates[options.index(chosen)]
    name, addr, lat, lon = selected
    st.success(f"[{method}] {name} ({addr}) - 위도: {lat}, 경도: {lon}")

if selected:
    name, addr, lat, lon = selected

    setting_col1, setting_col2 = st.columns(2)
    minutes = setting_col1.slider(
        "생활권 기준 (분)", min_value=5, max_value=60, value=DEFAULT_MINUTES, step=5
    )
    speed_kmh = setting_col2.slider(
        "환산 속도 (km/h)", min_value=10, max_value=60, value=DEFAULT_SPEED_KMH, step=5,
        help="직선거리 환산용 평균 속도",
    )

    st.markdown("**포함할 선택 항목**")
    st.caption(
        "아래 항목은 실시간 검색이나 AI 호출이 필요해 생성 시간이 늘어납니다. "
        "끄면 보고서에 '제외됨'으로 표기됩니다."
    )
    option_col1, option_col2 = st.columns(2)
    include_news = option_col1.checkbox(
        "🗞️ 지역 사업 뉴스",
        help="카카오 웹문서 검색 36회 (키워드 12개 × 3페이지). 1~2분 소요",
    )
    include_popular = option_col2.checkbox(
        "✨ 인기 공간 (블로그·카페)",
        help="블로그 100건 + 카페 50건 + 장소 후보 수집. 1~2분 소요",
    )

    survey_file = st.file_uploader(
        "🗣️ 사회조사 결과보고서 PDF (선택)",
        type="pdf",
        help="첨부하면 주민 니즈 섹션에 설문 응답(사실)이 들어갑니다. AI 호출 비용이 발생합니다.",
    )

    survey_text = None
    if survey_file is not None:
        try:
            survey_pages = extract_pages(survey_file)
        except Exception as e:
            st.error(f"PDF를 읽지 못했습니다: {e}")
            survey_pages = []
        if survey_pages:
            survey_selected = select_relevant_text(survey_pages)
            survey_text = survey_selected["text"]
            st.caption(
                f"설문 PDF: 텍스트 {survey_selected['total_pages']}쪽 중 "
                f"{survey_selected['selected_pages']}쪽 분석 "
                f"(추정 {survey_selected['estimated_tokens']:,}토큰)"
            )
        else:
            st.warning("PDF에서 텍스트를 찾지 못했습니다 (스캔 이미지 PDF는 분석 불가).")

    if st.button("📄 보고서 생성", type="primary"):
        progress_bar = st.progress(0.0, text="보고서 데이터를 모으는 중...")

        def on_progress(step, total, label, _bar=progress_bar):
            _bar.progress(step / total, text=f"({step}/{total}) {label}")

        try:
            data = collect_report_data(
                name, addr, lat, lon,
                minutes=minutes, speed_kmh=speed_kmh,
                include_news=include_news,
                include_popular=include_popular,
                survey_text=survey_text,
                progress_callback=on_progress,
            )
        except Exception as e:
            progress_bar.empty()
            st.error(f"데이터를 모으는 중 오류가 발생했습니다: {e}")
            st.stop()

        progress_bar.progress(1.0, text="Word 보고서를 만드는 중...")
        try:
            content = build_report(data)
        except Exception as e:
            progress_bar.empty()
            st.error(f"보고서를 만드는 중 오류가 발생했습니다: {e}")
            st.stop()
        progress_bar.empty()

        st.session_state["report_data"] = {
            "data": data,
            "content": content,
            "file_name": build_file_name(name, data["overview"]["created_on"]),
        }

report = st.session_state.get("report_data")
if report:
    data = report["data"]
    overview = data["overview"]
    population = data["population"]
    households = data["households"]
    facilities = data["facilities"]

    st.divider()
    st.success(f"'{overview['place_name']}' 보고서가 준비됐습니다.")

    st.download_button(
        "⬇️ Word 보고서 내려받기 (.docx)",
        data=report["content"],
        file_name=report["file_name"],
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        type="primary",
    )
    st.caption(f"파일명: {report['file_name']} ({len(report['content']):,} bytes)")

    st.subheader("보고서에 담긴 내용")
    summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
    summary_col1.metric("총인구", f"{population['total']:,}명")
    summary_col2.metric("0~9세 어린이", f"{population['age_0_9']:,}명")
    summary_col3.metric("전체 세대", f"{households['total_households']:,}세대")
    summary_col4.metric("재학 학생", f"{facilities['students_total']:,}명")

    st.markdown(
        f"""
**1. 대상지 개요** — {overview['sigungu_nm'] or '행정구역 확인 불가'} ·
{overview['minutes']}분 생활권(반경 {overview['radius_km']:.1f}km) · 행정동 {overview['dong_count']}개

**2. 인구·가구 현황** — 어린이 비율 {data['child_ratio']}% ·
가족 가구 비중 {households['family_ratio']}%

**3. 교육·학생 현황** — 학교 {sum(facilities['counts'].values())}개 ·
저학년(초1~3) {facilities['students_grade_1_3']:,}명

**4. 주변 시설 현황** — {' · '.join(f"{k} {v['count']}개" for k, v in data['child_spaces'].items())}
"""
    )

    tourism = data.get("tourism") or {}
    visitors = tourism.get("visitors")
    datalab = tourism.get("datalab")
    if visitors or datalab:
        parts = []
        if visitors:
            parts.append(f"외지인 비중 {visitors['outsider_ratio']:.1f}%")
            parts.append(f"주말 유입 {visitors['weekend_lift']:.2f}배")
        if datalab:
            parts.append(f"체류 {datalab['avg_stay_hours']}시간")
            parts.append(f"숙박 {datalab['avg_stay_nights']:.2f}일")
        detail_note = (
            "유입·유출·유사지역 포함"
            if tourism.get("registered")
            else "유입·유출·유사지역 상세 미등록"
        )
        st.markdown(f"**5. 관광·방문 특성** — {' · '.join(parts)} ({detail_note})")
    else:
        st.markdown("**5. 관광·방문 특성** — 방문 데이터 집계 대상 아님")

    news = data.get("news")
    popular = data.get("popular")
    if news is None and popular is None:
        st.markdown("**6. 지역 트렌드·이슈** — 생성 시 미선택 (보고서에 제외됨으로 표기)")
    else:
        parts = []
        if news is not None:
            parts.append(
                f"사업 뉴스 {news['total']}건" if not news.get("error") else "뉴스 조회 실패"
            )
        if popular is not None:
            parts.append(
                f"인기 공간 {popular['total']}곳"
                if not popular.get("error")
                else "인기 공간 조회 실패"
            )
        st.markdown(f"**6. 지역 트렌드·이슈** — {' · '.join(parts)}")

    survey = data.get("survey")
    if survey is None:
        st.markdown("**7. 주민 니즈** — 사회조사 보고서 미첨부")
    elif survey.get("error"):
        st.markdown(f"**7. 주민 니즈** — 분석 실패: {survey['error']}")
    else:
        st.markdown(
            f"**7. 주민 니즈** — 사회조사 응답 포함 "
            f"(미확인 항목 {len(survey['not_found'])}건 · "
            f"주의사항 {len(survey['data_caveats'])}건 · "
            f"AI 비용 ${survey['cost']['total_cost']:.4f})"
        )

    st.markdown("**8. 종합 요약** — 위 수치를 한 장으로 정리")

    if data["density"]:
        density = data["density"]
        ratio = density["children_per_space"]
        st.markdown(
            f"**어린이 공간 밀도** — [{density['label']}] "
            + (f"어린이 {ratio:,}명당 공간 1개" if ratio is not None else "공간 없음")
        )

    st.caption(
        "※ 보고서에는 각 섹션마다 데이터 표·사실 서술·출처가 들어 있습니다. "
        "수치만 담고 해석·제언은 넣지 않습니다 (AI 사회조사 분석도 '사실' 영역만 포함)."
    )
else:
    if not candidates:
        st.info("주소나 지역명을 검색해주세요.")
