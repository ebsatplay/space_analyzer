"""주민 니즈 분석 - 사회조사 보고서 PDF를 올리면 Claude가 주민 니즈를 뽑아낸다.

실행: streamlit run app.py (메뉴에서 "주민 니즈 분석" 선택)
"""

import streamlit as st

from analysis.survey_pdf import (
    DEFAULT_TOKEN_BUDGET,
    extract_pages,
    select_relevant_text,
)
from services.ai_service import (
    MODEL,
    PRICE_INPUT_PER_MTOK,
    PRICE_OUTPUT_PER_MTOK,
    AiServiceError,
    analyze_survey_pdf,
)
from views._theme import apply_theme, page_header

apply_theme()
page_header("주민 니즈 분석", "사회조사 보고서에서 주민이 무엇을 원하는지 읽어냅니다")

st.caption(
    "지자체 사회조사 결과보고서 PDF를 올리면 거주의향·가족/출산·교육·주거 항목을 "
    f"뽑아 어린이·가족 공간사업 시사점까지 정리합니다. (모델: {MODEL})"
)

input_col, budget_col = st.columns([3, 1])
region_name = input_col.text_input(
    "대상지",
    placeholder="예: 고령군, 파주시",
    help="보고서의 지역명을 적어주세요. 분석 결과에 지역명으로 쓰입니다.",
)
token_budget = budget_col.number_input(
    "토큰 예산",
    min_value=20_000,
    max_value=800_000,
    value=DEFAULT_TOKEN_BUDGET,
    step=10_000,
    help="보고서가 이 예산을 넘으면 관련도 높은 페이지만 골라 보냅니다.",
)

uploaded = st.file_uploader("사회조사 보고서 PDF", type="pdf")

if uploaded is not None and region_name.strip():
    with st.spinner("PDF에서 텍스트를 뽑는 중..."):
        try:
            pages = extract_pages(uploaded)
        except Exception as e:
            st.error(f"PDF를 읽지 못했습니다: {e}")
            st.stop()

    if not pages:
        st.error(
            "텍스트가 있는 페이지를 찾지 못했습니다. 스캔 이미지로만 된 PDF는 분석할 수 없습니다."
        )
        st.stop()

    selected = select_relevant_text(pages, token_budget=int(token_budget))

    info_col1, info_col2, info_col3 = st.columns(3)
    info_col1.metric("텍스트 있는 페이지", f"{selected['total_pages']}쪽")
    info_col2.metric("분석에 보낼 페이지", f"{selected['selected_pages']}쪽")
    info_col3.metric("추정 입력 토큰", f"{selected['estimated_tokens']:,}")

    estimated_cost = selected["estimated_tokens"] / 1_000_000 * PRICE_INPUT_PER_MTOK
    st.caption(
        f"예상 입력 비용 약 ${estimated_cost:.3f} "
        f"(입력 ${PRICE_INPUT_PER_MTOK}/1M · 출력 ${PRICE_OUTPUT_PER_MTOK}/1M 기준, "
        "출력 비용은 응답 길이에 따라 추가됩니다)"
    )
    if selected["topics"]:
        st.caption(f"확인된 주제: {' · '.join(selected['topics'])}")
    if selected["truncated"]:
        st.warning(
            f"보고서가 토큰 예산({int(token_budget):,})을 넘어 관련도 높은 "
            f"{selected['selected_pages']}쪽만 골라 보냅니다. "
            "빠진 내용은 분석에 반영되지 않습니다 - 예산을 올리면 더 많이 담깁니다."
        )

    if st.button("🤖 주민 니즈 분석 실행", type="primary"):
        with st.spinner(f"Claude가 '{region_name}' 보고서를 읽는 중... (1~3분 걸릴 수 있습니다)"):
            try:
                result, cost = analyze_survey_pdf(selected["text"], region_name.strip())
            except AiServiceError as e:
                st.error(str(e))
                st.stop()
        st.session_state["survey_result"] = {
            "region_name": region_name.strip(),
            "result": result,
            "cost": cost,
            "selected": selected,
            "file_name": uploaded.name,
        }

analysis = st.session_state.get("survey_result")
if analysis:
    result = analysis["result"]
    st.divider()

    # ───────────── 영역 1: 객관적 사실 (메인) ─────────────
    st.subheader(f"📊 {analysis['region_name']} 주민 설문 결과")
    st.caption(
        "보고서에 실제로 있는 수치·응답만 담았습니다. AI의 해석은 들어 있지 않습니다. "
        "각 항목의 [p.N]은 보고서 페이지이니 원문 대조에 쓰시면 됩니다."
    )

    if result["facts_markdown"].strip():
        st.markdown(result["facts_markdown"])
    else:
        st.warning("보고서에서 해당 항목의 수치를 찾지 못했습니다.")

    if result["not_found"]:
        with st.expander(f"📭 보고서에 없는 항목 {len(result['not_found'])}건"):
            for item in result["not_found"]:
                st.markdown(f"- {item}")
            st.caption("요청한 항목 중 이 보고서가 다루지 않은 것들입니다.")

    if result["data_caveats"]:
        with st.expander(f"⚠️ 수치를 읽을 때 주의할 점 {len(result['data_caveats'])}건", expanded=True):
            for item in result["data_caveats"]:
                st.markdown(f"- {item}")
            st.caption("조사 대상 범위·표본 크기 등 보고서가 밝힌 한계입니다 (이것도 사실입니다).")

    st.caption(
        f"출처: {analysis['region_name']} 사회조사 결과보고서 ({analysis['file_name']}) · "
        "수치는 원문에서 확인 후 인용하세요"
    )

    # ───────────── 영역 2: AI 해석 (분리, 접어둠) ─────────────
    st.divider()
    st.markdown(
        '<div class="ai-opinion-banner">※ 아래는 <b>AI의 해석</b>이며 '
        "보고서의 객관적 사실이 아닙니다. 참고용으로만 보시고, "
        "보고서에 그대로 옮겨 쓰지 마세요.</div>",
        unsafe_allow_html=True,
    )

    with st.expander("💡 AI 참고 의견 보기 (해석 · 사업 시사점)"):
        st.markdown(
            '<div class="ai-opinion-body">', unsafe_allow_html=True
        )
        if result["interpretation_markdown"].strip():
            st.markdown(result["interpretation_markdown"])
        else:
            st.caption("AI 해석이 생성되지 않았습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        st.caption(
            "위 내용은 영역 1의 수치에서 AI가 끌어낸 판단입니다. "
            "보고서가 직접 말한 것이 아니므로 근거로 인용할 수 없습니다."
        )

    # ───────────── 분석 조건·비용 ─────────────
    cost = analysis["cost"]
    selected = analysis["selected"]
    with st.expander("📑 분석 조건·비용 보기"):
        st.markdown(
            f"""
- **원본 파일**: {analysis['file_name']}
- **모델**: {MODEL}
- **보낸 분량**: {selected['selected_pages']}/{selected['total_pages']}쪽
  {'(토큰 예산 때문에 일부만 전송)' if selected['truncated'] else '(전체 전송)'}
- **실제 토큰**: 입력 {cost['input_tokens']:,} / 출력 {cost['output_tokens']:,}
- **이번 호출 비용**: ${cost['total_cost']:.4f}
  (입력 ${cost['input_cost']:.4f} + 출력 ${cost['output_cost']:.4f})

📌 사실과 해석은 모델 응답 단계에서 **서로 다른 필드로 받습니다**(structured outputs).
마크다운 한 덩어리로 받아 나중에 쪼개는 방식이 아니라서, 영역 1에 AI 의견이 섞여
들어갈 수 없습니다.

📌 PDF 표·단 구조 때문에 추출 텍스트에서 숫자가 설명과 떨어져 나오는 경우가 있습니다.
그런 항목은 위 '수치를 읽을 때 주의할 점'에 표시됩니다.
"""
        )
elif uploaded is None or not region_name.strip():
    st.info("대상지를 입력하고 사회조사 보고서 PDF를 올려주세요.")
