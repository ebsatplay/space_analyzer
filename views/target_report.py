"""대상지 보고서 - 주소/지역을 입력하면 조사 보고서를 Word로 만들어 준다.

실행: streamlit run app.py (메뉴에서 "대상지 보고서" 선택)
"""

import io
import os

import streamlit as st

from analysis.report_data import DEFAULT_MINUTES, DEFAULT_SPEED_KMH, collect_report_data
from analysis.report_docx import build_file_name, build_report
from analysis.survey_pdf import extract_pages, find_local_survey, select_relevant_text
from analysis.visitors import resolve_sigungu_cd
from services.kakao_service import find_location
from views._theme import apply_theme, page_header

apply_theme()
page_header("대상지 보고서", "분석 결과를 한 편의 조사 보고서로 묶어 드립니다")

st.caption(
    "주소나 지역명을 넣으면 생활권 인구·가구, 교육·학생, 주변 시설 현황을 모아 "
    "Word(.docx) 보고서로 만듭니다. 수치만 담고 해석·제언은 넣지 않습니다."
)

@st.cache_data(show_spinner="사회조사 보고서를 읽는 중...")
def load_survey_selection(source_key, file_bytes=None):
    """사회조사 PDF를 읽어 분석에 쓸 텍스트를 고른다 (결과를 캐시한다).

    캐시가 없으면 리런마다 PDF를 다시 파싱해서 화면이 멈춘 것처럼 보인다
    (파주 289쪽 보고서는 파싱에만 47초가 걸려 아래 버튼이 안 보인다).
    source_key는 경로+수정시각이거나 업로드 파일명+크기라서 내용이 바뀌면 다시 읽는다.
    """
    if file_bytes is not None:
        pages = extract_pages(io.BytesIO(file_bytes))
    else:
        pages = extract_pages(source_key[0])
    if not pages:
        return None
    return select_relevant_text(pages)


# 생성 중에 위젯을 건드리면 스크립트가 다시 돌아 같은 작업(유료 API 포함)이
# 두 번 실행된다. 그래서 생성 중에는 입력을 모두 잠근다.
is_generating = st.session_state.get("report_generating", False)

st.markdown('<div class="search-section-label">대상지 검색</div>', unsafe_allow_html=True)
search_col, button_col = st.columns([4, 1])
address_input = search_col.text_input(
    "주소 또는 지역명",
    placeholder="예: 고령군청, 경북 고령군 대가야읍",
    label_visibility="collapsed",
    disabled=is_generating,
)
if button_col.button("검색", use_container_width=True, disabled=is_generating):
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

    setting_col1, setting_col2, setting_col3 = st.columns([2, 1, 2])
    minutes = setting_col1.slider(
        "생활권 기준 (분)", min_value=5, max_value=120, value=DEFAULT_MINUTES, step=5,
        key="report_minutes",
        disabled=is_generating,
    )
    # 슬라이더 눈금(5분 단위)에 없는 값을 쓰고 싶을 때 쓰는 칸
    custom_minutes = setting_col2.number_input(
        "직접 입력 (분)",
        min_value=0,
        max_value=180,
        value=0,
        step=1,
        key="report_minutes_custom",
        help="0이면 왼쪽 슬라이더 값을 씁니다",
        disabled=is_generating,
    )
    if custom_minutes:
        minutes = int(custom_minutes)

    speed_kmh = setting_col3.slider(
        "환산 속도 (km/h)", min_value=10, max_value=60, value=DEFAULT_SPEED_KMH, step=5,
        help="직선거리 환산용 평균 속도",
        key="report_speed",
        disabled=is_generating,
    )
    st.caption(f"적용: {minutes}분 · 평균 {speed_kmh}km/h")

    st.markdown("**포함할 선택 항목**")
    st.caption(
        "아래 항목은 실시간 검색이나 AI 호출이 필요해 생성 시간이 늘어납니다. "
        "끄면 보고서에 '제외됨'으로 표기됩니다."
    )
    option_col1, option_col2 = st.columns(2)
    include_news = option_col1.checkbox(
        "🗞️ 지역 사업 뉴스",
        help="카카오 웹문서 검색 36회 (키워드 12개 × 3페이지). 1~2분 소요",
        disabled=is_generating,
    )
    include_popular = option_col2.checkbox(
        "✨ 인기 공간 (블로그·카페)",
        help="블로그 100건 + 카페 50건 + 장소 후보 수집. 1~2분 소요",
        disabled=is_generating,
    )

    # 주소에서 시군구를 알아내 data/raw 에 받아둔 사회조사 보고서를 먼저 찾는다.
    # 장소명(예: '파주놀이구름')으로는 지역을 알 수 없어 주소를 쓴다.
    _sigungu_cd, sigungu_nm = resolve_sigungu_cd(addr)
    local_survey_path, local_survey_region = find_local_survey(sigungu_nm or name)

    survey_source = None
    if local_survey_path:
        use_local = st.checkbox(
            f"🗣️ 사회조사 보고서 자동 사용 ({local_survey_region})",
            value=True,
            help="data/raw 에 받아둔 보고서를 씁니다. 끄면 직접 올릴 수 있습니다.",
            disabled=is_generating,
        )
        if use_local:
            st.success(
                f"이 지역은 사회조사 자료가 준비되어 있어 자동 분석합니다 "
                f"({os.path.basename(local_survey_path)}). 업로드하지 않으셔도 됩니다."
            )
            survey_source = local_survey_path
        else:
            survey_source = st.file_uploader(
                "🗣️ 사회조사 결과보고서 PDF",
                type="pdf",
                help="자동 사용을 끄고 다른 보고서를 올릴 때 씁니다.",
                disabled=is_generating,
            )
    else:
        survey_source = st.file_uploader(
            "🗣️ 사회조사 결과보고서 PDF (선택)",
            type="pdf",
            help="첨부하면 주민 니즈 섹션에 설문 응답(사실)이 들어갑니다. AI 호출 비용이 발생합니다.",
            disabled=is_generating,
        )

    # PDF 파싱은 버튼을 누른 뒤에만 한다 (파주 289쪽은 45초가 걸려서,
    # 미리 읽으면 슬라이더를 건드릴 때마다 화면이 멈춘 것처럼 보인다)
    if survey_source is not None:
        if isinstance(survey_source, str):
            st.caption(
                f"사회조사 보고서는 생성 버튼을 누른 뒤 읽습니다 "
                f"({os.path.basename(survey_source)})."
            )
        else:
            st.caption("업로드한 사회조사 보고서는 생성 버튼을 누른 뒤 읽습니다.")

    clicked = st.button(
        "📄 보고서 생성",
        type="primary",
        disabled=is_generating,
        help="누르면 데이터 수집·AI 분석·지도/차트 생성이 시작됩니다",
    )
    if clicked and not is_generating:
        # 실제 작업은 다음 리런에서 한다. 그래야 버튼이 '생성 중'으로 잠긴 상태가
        # 먼저 그려져서, 사용자가 안 눌린 줄 알고 다시 누르는 일이 없다.
        st.session_state["report_generating"] = True
        st.session_state.pop("report_data", None)
        st.rerun()

    if is_generating:
        st.warning(
            "⏳ **보고서를 만드는 중입니다.** 버튼을 다시 누르지 않으셔도 됩니다. "
            "선택 항목에 따라 수 분이 걸릴 수 있습니다."
        )

        with st.status("보고서 생성 중...", expanded=True) as status:
            survey_text = None
            if survey_source is not None:
                status.update(label="사회조사 보고서를 읽는 중...")
                try:
                    if isinstance(survey_source, str):
                        # 경로는 수정시각까지 키에 넣어 파일이 바뀌면 다시 읽게 한다
                        cache_key = (survey_source, os.path.getmtime(survey_source))
                        survey_selected = load_survey_selection(cache_key)
                    else:
                        data_bytes = survey_source.getvalue()
                        cache_key = (survey_source.name, len(data_bytes))
                        survey_selected = load_survey_selection(
                            cache_key, file_bytes=data_bytes
                        )
                except Exception as e:
                    st.error(f"PDF를 읽지 못했습니다: {e}")
                    survey_selected = None

                if survey_selected:
                    survey_text = survey_selected["text"]
                    st.write(
                        f"설문 PDF: 텍스트 {survey_selected['total_pages']}쪽 중 "
                        f"{survey_selected['selected_pages']}쪽 분석 "
                        f"(추정 {survey_selected['estimated_tokens']:,}토큰)"
                    )
                else:
                    st.warning(
                        "PDF에서 텍스트를 찾지 못해 주민 니즈 섹션 없이 진행합니다."
                    )

            def on_progress(step, total, label, _status=status):
                _status.update(label=f"({step}/{total}) {label}")

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
                status.update(label="데이터 수집 실패", state="error")
                st.session_state["report_generating"] = False
                st.error(f"데이터를 모으는 중 오류가 발생했습니다: {e}")
                st.stop()

            def on_visual(message, _status=status):
                _status.update(label=message)

            try:
                content = build_report(data, progress_callback=on_visual)
            except Exception as e:
                status.update(label="보고서 생성 실패", state="error")
                st.session_state["report_generating"] = False
                st.error(f"보고서를 만드는 중 오류가 발생했습니다: {e}")
                st.stop()

            status.update(label="보고서 생성 완료", state="complete", expanded=False)

        st.session_state["report_data"] = {
            "data": data,
            "content": content,
            "file_name": build_file_name(name, data["overview"]["created_on"]),
        }
        # 잠금을 풀고 결과 화면으로 넘어간다 (버튼이 다시 눌리는 상태로 돌아온다)
        st.session_state["report_generating"] = False
        st.toast("보고서가 완성됐습니다. 아래에서 내려받으세요.", icon="📄")
        st.rerun()

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
