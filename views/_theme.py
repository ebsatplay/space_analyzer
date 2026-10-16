"""모든 페이지가 공유하는 스타일과 헤더.

페이지마다 CSS를 복붙하지 않도록 한 곳에 모아둔다. 색/폰트를 바꿀 일이 있으면 여기만 고치면 된다.
"""

import streamlit as st

SHARED_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;600;700;800&family=Nanum+Gothic:wght@400;700;800&display=swap');

/* 폰트는 여기 한 줄만 고치면 전체에 반영된다.
   웹폰트가 늦게 뜨거나 막혀도 글자가 깨지지 않도록 OS 기본 고딕까지 폴백으로 둔다. */
:root {
    --brand-font: 'Noto Sans KR', 'Nanum Gothic', 'Malgun Gothic', '맑은 고딕',
                  'Apple SD Gothic Neo', sans-serif;
}

html, body, [class*="css"] {
    font-family: var(--brand-font);
}

/* Streamlit이 자체 스타일로 넣는 요소(위젯 라벨·버튼·표·탭 등)까지 같은 폰트로 맞춘다 */
html body, body *, .stMarkdown, .stMetric, .stDataFrame, .stButton > button,
div[data-testid="stWidgetLabel"], div[data-testid="stMetricValue"],
div[data-testid="stMetricLabel"], div[data-testid="stExpander"] summary,
input, textarea, select, button, h1, h2, h3, h4, h5, h6 {
    font-family: var(--brand-font);
}

.block-container {
    padding-top: 3rem;
    padding-bottom: 4rem;
}

h1, h2, h3 {
    font-family: var(--brand-font) !important;
    color: #4A4238 !important;
}

.app-title {
    font-family: var(--brand-font);
    font-size: 2.6rem;
    font-weight: 700;
    color: #4A4238;
    letter-spacing: 0.02em;
    line-height: 1.3;
    margin-bottom: 0.3rem;
}
.app-subtitle {
    font-family: var(--brand-font);
    font-weight: 300;
    color: #A79C8E;
    font-size: 1rem;
    letter-spacing: 0.04em;
    line-height: 1.5;
    margin-bottom: 2rem;
}

/* 사이드바 렌더 순서 조정.
   Streamlit은 사이드바를 [헤더 -> 네비게이션 -> 사용자 콘텐츠] 순서로 그려서,
   st.sidebar에 먼저 써도 로고가 메뉴 아래로 내려간다.
   flex order로 사용자 콘텐츠(로고)를 네비게이션 위로 올린다. */
[data-testid="stSidebarContent"] {
    display: flex;
    flex-direction: column;
}
[data-testid="stSidebarHeader"] { order: 0; }
[data-testid="stSidebarUserContent"] { order: 1; }
[data-testid="stSidebarNav"] { order: 2; }

/* 사이드바 상단 로고 (메뉴 위) */
.brand-logo {
    padding: 0.2rem 0 1rem;
    margin-bottom: 0.6rem;
    border-bottom: 1px solid #E7DFD3;
}
.brand-name {
    font-family: var(--brand-font);
    font-size: 1.55rem;
    font-weight: 800;
    color: #4A4238;
    letter-spacing: 0.01em;
    line-height: 1.25;
    margin-bottom: 0.25rem;
}
.brand-tagline {
    font-family: var(--brand-font);
    font-size: 0.78rem;
    font-weight: 300;
    color: #A79C8E;
    letter-spacing: 0.03em;
    line-height: 1.4;
}

/* 페이지마다 같은 자리에 오는 입력 영역 (메인 상단) */
.search-section-label {
    font-family: var(--brand-font);
    font-size: 1.05rem;
    font-weight: 700;
    color: #4A4238;
    margin-bottom: 0.2rem;
}

div[data-testid="stTextInput"] input {
    border-radius: 14px !important;
    border: 1px solid #E7DFD3 !important;
    padding: 10px 16px !important;
}

.stButton > button {
    background-color: #A8D5E2;
    color: #3E5C63;
    border: none;
    border-radius: 14px;
    padding: 0.5rem 1.6rem;
    font-weight: 600;
    box-shadow: 0 4px 12px rgba(168, 213, 226, 0.4);
}
.stButton > button:hover {
    background-color: #96CBDA;
    color: #2E464C;
}

div[data-testid="stAlert"] {
    border-radius: 16px;
}

/* KPI 카드 (생활권 분석) */
.kpi-card {
    border-radius: 20px;
    padding: 28px 18px;
    text-align: center;
    box-shadow: 0 8px 22px rgba(168, 213, 226, 0.28);
    margin-bottom: 1.2rem;
}
.kpi-blue {
    background: linear-gradient(135deg, #EAF5F8 0%, #DCEEF3 100%);
    border: 1px solid #CDE7EE;
}
.kpi-pink {
    background: linear-gradient(135deg, #FBF0F0 0%, #F5E2E2 100%);
    border: 1px solid #F0D9D9;
}
.kpi-green {
    background: linear-gradient(135deg, #EFF5EE 0%, #E3EDE0 100%);
    border: 1px solid #D6E6D2;
}
.kpi-amber {
    background: linear-gradient(135deg, #F7F0E6 0%, #F0E4D0 100%);
    border: 1px solid #E8D5B7;
}
.kpi-lavender {
    background: linear-gradient(135deg, #EEF0F9 0%, #E4E7F5 100%);
    border: 1px solid #D3D8ED;
}
.kpi-teal {
    background: linear-gradient(135deg, #E9F4F3 0%, #DCEEEC 100%);
    border: 1px solid #C7E3E0;
}
.kpi-rose {
    background: linear-gradient(135deg, #FBEBEC 0%, #F6DBDD 100%);
    border: 2px solid #E0637A;
}
.kpi-violet {
    background: linear-gradient(135deg, #F0EBF7 0%, #E6DCF2 100%);
    border: 1px solid #D8C7EA;
}
.kpi-tangerine {
    background: linear-gradient(135deg, #FBEEDF 0%, #F6E0C7 100%);
    border: 1px solid #ECCB9E;
}
.kpi-red {
    background: linear-gradient(135deg, #FBEAE9 0%, #F6D6D4 100%);
    border: 2px solid #D9534F;
}
.kpi-label {
    font-family: var(--brand-font);
    font-size: 0.9rem;
    font-weight: 500;
    color: #8A8178;
    margin-bottom: 10px;
    letter-spacing: 0.02em;
}
.kpi-value {
    font-family: var(--brand-font);
    font-size: 2.1rem;
    font-weight: 700;
    line-height: 1.2;
}
.kpi-blue .kpi-value { color: #3E7C91; }
.kpi-pink .kpi-value { color: #C97B8E; }
.kpi-green .kpi-value { color: #5C8A6B; }
.kpi-amber .kpi-value { color: #A97C50; }
.kpi-lavender .kpi-value { color: #5D69A8; }
.kpi-teal .kpi-value { color: #3E8C82; }
.kpi-rose .kpi-value { color: #C94D63; }
.kpi-violet .kpi-value { color: #6F4F96; }
.kpi-tangerine .kpi-value { color: #B87332; }
.kpi-red .kpi-value { color: #C0392B; }
.kpi-unit {
    font-family: var(--brand-font);
    font-size: 1.05rem;
    font-weight: 400;
    margin-left: 2px;
}
/* 카드 값 아래 보조 한 줄 (예: 학교 개수 아래 학생수) */
.kpi-sub {
    font-family: var(--brand-font);
    font-size: 0.88rem;
    font-weight: 500;
    color: #8A8178;
    margin-top: 8px;
    letter-spacing: 0.01em;
}

/* 강조 한 줄 (배후권/인기공간의 요약 라인) */
.highlight-line {
    font-family: var(--brand-font);
    font-size: 1.15rem;
    font-weight: 700;
    color: #C94D63;
    background: linear-gradient(135deg, #FBEBEC 0%, #F6DBDD 100%);
    border: 1px solid #F0C7CC;
    border-radius: 14px;
    padding: 14px 20px;
    margin: 1rem 0 1.4rem;
}

/* 지역/공간 비교 카드 (배후권 비교, 인기 공간) */
.region-grid, .place-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(215px, 1fr));
    gap: 1.2rem;
    margin-bottom: 1.4rem;
}
.region-card, .place-card {
    border-radius: 20px;
    padding: 24px 22px;
    box-shadow: 0 8px 22px rgba(168, 213, 226, 0.28);
    background: linear-gradient(135deg, #EAF5F8 0%, #DCEEF3 100%);
    border: 1px solid #CDE7EE;
}
.region-card.top, .place-card.top {
    background: linear-gradient(135deg, #FBEBEC 0%, #F6DBDD 100%);
    border: 2px solid #E0637A;
}
.region-rank, .place-rank {
    font-family: var(--brand-font);
    font-size: 0.82rem;
    font-weight: 600;
    color: #8A8178;
    margin-bottom: 4px;
    letter-spacing: 0.02em;
}
.region-card.top .region-rank, .place-card.top .place-rank { color: #C94D63; }
.region-name, .place-name {
    font-family: var(--brand-font);
    font-size: 1.2rem;
    font-weight: 700;
    color: #4A4238;
    line-height: 1.3;
    margin-bottom: 2px;
}
.place-name { margin-bottom: 10px; }
.region-distance {
    font-size: 0.8rem;
    color: #8A8178;
    margin-bottom: 14px;
}
.region-main-label {
    font-family: var(--brand-font);
    font-size: 0.85rem;
    color: #8A8178;
    margin-bottom: 2px;
}
.region-main-value, .place-value {
    font-family: var(--brand-font);
    font-size: 2.3rem;
    font-weight: 700;
    line-height: 1.15;
    color: #3E7C91;
}
.region-card.top .region-main-value, .place-card.top .place-value { color: #C94D63; }
.region-main-unit, .place-unit {
    font-family: var(--brand-font);
    font-size: 1rem;
    font-weight: 400;
    margin-left: 2px;
}
.place-category {
    font-size: 0.78rem;
    color: #8A8178;
    margin-top: 10px;
    line-height: 1.4;
}

/* AI 해석 영역 - 객관적 사실과 절대 혼동되지 않도록 시각적으로 확실히 가른다 */
.ai-opinion-banner {
    background: linear-gradient(135deg, #F3EFFA 0%, #E9E1F5 100%);
    border: 2px dashed #A98BD0;
    border-radius: 14px;
    padding: 12px 16px;
    margin-bottom: 10px;
    font-family: var(--brand-font);
    font-size: 0.88rem;
    line-height: 1.6;
    color: #5B4A7A;
}
.ai-opinion-banner b {
    color: #6F4F96;
}
.ai-opinion-body {
    border-left: 4px solid #A98BD0;
    padding-left: 14px;
}

/* 지역 사업 뉴스 목록 */
.news-item {
    background: linear-gradient(135deg, #FDFBF7 0%, #F7F2E9 100%);
    border: 1px solid #EBE2D2;
    border-radius: 14px;
    padding: 14px 16px;
    margin-bottom: 10px;
}
.news-meta {
    font-family: var(--brand-font);
    font-size: 0.78rem;
    color: #8A8178;
    margin-bottom: 6px;
}
.news-title {
    font-family: var(--brand-font);
    font-size: 0.98rem;
    font-weight: 600;
    line-height: 1.45;
}
.news-title a {
    color: #4A4238;
    text-decoration: none;
    border-bottom: 1px solid rgba(74, 66, 56, 0.25);
}
.news-title a:hover {
    color: #3E7C91;
    border-bottom-color: #3E7C91;
}
.news-keywords {
    margin-top: 8px;
}
.news-keyword {
    display: inline-block;
    background: #EAF5F8;
    border: 1px solid #CDE7EE;
    color: #3E7C91;
    font-family: var(--brand-font);
    font-size: 0.72rem;
    font-weight: 700;
    border-radius: 999px;
    padding: 2px 9px;
    margin-right: 5px;
}

/* 신뢰도 배지 / 언급 분해 (인기 공간) */
.trust-badge {
    display: inline-block;
    background: #E3EDE0;
    border: 1px solid #A9CBA0;
    color: #4A7C4E;
    font-size: 0.74rem;
    font-weight: 700;
    border-radius: 999px;
    padding: 3px 9px;
    margin-bottom: 8px;
}
.mention-breakdown {
    margin-top: 10px;
    padding-top: 8px;
    border-top: 1px solid rgba(74, 66, 56, 0.1);
    font-size: 0.78rem;
    line-height: 1.7;
    color: #6B6459;
}
.mention-breakdown .g { color: #4A7C4E; font-weight: 600; }
.mention-breakdown .a { color: #B0783C; font-weight: 600; }

/* 데이터 관리 상태 카드 */
.status-card {
    border-radius: 20px;
    padding: 22px 24px;
    box-shadow: 0 8px 22px rgba(168, 213, 226, 0.28);
    margin-bottom: 0.8rem;
    min-height: 168px;
}
.status-fresh {
    background: linear-gradient(135deg, #EFF5EE 0%, #E3EDE0 100%);
    border: 1px solid #D6E6D2;
}
.status-stale {
    background: linear-gradient(135deg, #FBEAE9 0%, #F6D6D4 100%);
    border: 2px solid #D9534F;
}
.status-name {
    font-family: var(--brand-font);
    font-size: 1.3rem;
    font-weight: 700;
    color: #4A4238;
    margin-bottom: 6px;
}
.status-meta {
    font-family: var(--brand-font);
    font-size: 0.9rem;
    color: #8A8178;
    margin-bottom: 4px;
}
.status-badge {
    font-family: var(--brand-font);
    font-weight: 700;
    font-size: 0.95rem;
    margin-top: 8px;
}
.status-fresh .status-badge { color: #5C8A6B; }
.status-stale .status-badge { color: #C0392B; }

@media (max-width: 640px) {
    div[data-testid="stHorizontalBlock"] {
        flex-direction: column;
    }
}

/* 지도 클릭 시 브라우저 기본 focus outline(네모 테두리) 제거 */
iframe,
iframe:focus,
.folium-map,
.folium-map:focus,
[class*="stCustomComponent"],
[class*="stCustomComponent"]:focus {
    outline: none !important;
}
</style>
"""


BRAND_NAME = "공간 분석 랩"
BRAND_TAGLINE = "공간 입지·트렌드 인사이트"


def render_brand_logo():
    """사이드바 맨 위에 서비스 로고를 그린다 (메뉴보다 위에 오도록 먼저 호출)."""
    st.sidebar.markdown(
        f'<div class="brand-logo">'
        f'<div class="brand-name">{BRAND_NAME}</div>'
        f'<div class="brand-tagline">{BRAND_TAGLINE}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def apply_theme():
    """공통 스타일을 적용한다. 각 페이지 맨 위에서 한 번 호출한다."""
    st.markdown(SHARED_CSS, unsafe_allow_html=True)


def render_metric_cards(df, value_col, label, unit, top_count=6, area_label="배후권"):
    """지표 하나를 기준으로 지역 카드를 그린다. 1위 카드는 강조색으로 표시한다.

    배후권 비교와 생활권의 확장 지역 비교가 같은 카드를 쓰므로 여기에 둔다.
    area_label은 "배후권"/"확장 지역"처럼 부르는 이름만 바꿀 때 쓴다.
    """
    sorted_df = df.sort_values(value_col, ascending=False).reset_index(drop=True)
    top_row = sorted_df.iloc[0]

    if top_row[value_col] == 0:
        st.info(f"{area_label} 안에 {label}(이)가 없습니다.")
    else:
        st.markdown(
            f'<div class="highlight-line">💡 {label} 최다: {top_row["sigungu_nm"]} '
            f'(약 {top_row[value_col]:,.0f}{unit})</div>',
            unsafe_allow_html=True,
        )

    card_divs = []
    for rank, row in enumerate(sorted_df.head(top_count).itertuples(index=False), start=1):
        is_top = rank == 1
        card_class = "region-card top" if is_top else "region-card"
        trophy = " 🏆" if is_top else ""
        value = getattr(row, value_col)
        card_divs.append(
            f'<div class="{card_class}">'
            f'<div class="region-rank">{rank}위{trophy}</div>'
            f'<div class="region-name">{row.sigungu_nm}</div>'
            f'<div class="region-distance">거리 약 {row.distance_km:.1f}km</div>'
            f'<div class="region-main-label">{label}</div>'
            f'<div class="region-main-value">{value:,.0f}'
            f'<span class="region-main-unit">{unit}</span></div>'
            f"</div>"
        )
    st.markdown('<div class="region-grid">' + "".join(card_divs) + "</div>", unsafe_allow_html=True)

    if len(sorted_df) > top_count:
        st.caption(
            f"{label} 상위 {top_count}개만 카드로 표시했습니다 "
            f"({area_label} 전체 {len(sorted_df)}개 중)."
        )


def page_header(title, subtitle):
    """페이지 제목/부제를 같은 모양으로 그린다."""
    st.markdown(
        f'<div class="app-title">{title}</div>'
        f'<div class="app-subtitle">{subtitle}</div>',
        unsafe_allow_html=True,
    )
