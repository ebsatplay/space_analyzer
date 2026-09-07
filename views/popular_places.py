"""인기 공간 - 블로그·카페에 자주 언급되는 곳을 집계해서 보여준다.

실행: streamlit run app.py (메뉴에서 "인기 공간" 선택)
"""

import folium
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import folium_static

from analysis.popular_places import get_popular_places
from services.kakao_service import get_usage
from views._theme import apply_theme, page_header

PURPOSE_PRESETS = [
    "아이랑 가볼만한 곳",
    "키즈카페",
    "아이 체험",
    "실내 놀이",
    "데이트 추천",
    "가족 나들이",
    "직접 입력",
]

USAGE_WARN_RATIO = 0.8

# 도움말 문구 (평소엔 (?) 아이콘만 보이고, 누르면 말풍선으로 펼쳐진다)
HELP_RANKING = (
    "카카오 지도에서 이 지역 공간 목록을 확보하고, 블로그·카페 글에서 각 공간 언급 횟수를 "
    "집계한 순위입니다.\n\n"
    "**실제 방문객 수가 아닌 온라인 언급 빈도 기준**이라, 글이 많이 쓰인 곳일수록 높게 나옵니다."
)
HELP_GENUINE = (
    "'내돈내산' 등 자기 돈으로 방문한 신뢰 신호가 있는 글입니다.\n\n"
    "협찬은 주로 이미지로 표기돼 텍스트로는 일부만 구분됩니다."
)
HELP_AD = (
    "제공받아/체험단/레뷰 등 텍스트에 협찬 문구가 있는 글입니다.\n\n"
    "순위 집계 시 **가중치 0.3**으로 낮게 반영됩니다."
)
HELP_PERIOD = (
    "분석 시점 기준으로 카카오 검색에서 정확도순 상위 글을 가져옵니다 "
    "(블로그 최대 100건 + 카페 최대 50건).\n\n"
    "기간을 지정한 수집이 아니라 **검색 시점의 최신 노출 글 기준**이라, "
    "다시 분석하면 결과가 조금씩 달라질 수 있습니다."
)

apply_theme()
page_header("인기 공간", "블로그·카페에 자주 언급되는 곳")

st.warning(
    "⚠️ 블로그·카페 언급 횟수 기반이며, 실제 방문객 수가 아닙니다. "
    "글이 많이 쓰인 곳일수록 높게 나오는 점을 감안해서 참고해주세요."
)

usage = get_usage()
if usage["ratio"] >= USAGE_WARN_RATIO:
    st.error(
        f"🚨 카카오 API 일일 호출량이 한도의 {usage['ratio'] * 100:.0f}%에 도달했습니다 "
        f"({usage['count']:,} / {usage['limit']:,}건). 검색이 곧 제한될 수 있습니다."
    )

col1, col2 = st.columns(2)
region_name = col1.text_input("지역명", value="경주", help="예: 경주, 포항, 부산 해운대")
purpose_choice = col2.selectbox("목적 키워드", PURPOSE_PRESETS)

if purpose_choice == "직접 입력":
    purpose_keyword = st.text_input("목적 키워드 직접 입력", value="아이랑 가볼만한 곳")
else:
    purpose_keyword = purpose_choice

if st.button("인기 공간 분석", type="primary"):
    if not region_name.strip() or not purpose_keyword.strip():
        st.warning("지역명과 목적 키워드를 모두 입력해주세요.")
    else:
        progress_bar = st.progress(0, text="분석 준비 중...")

        def on_progress(step, total, label, _bar=progress_bar):
            _bar.progress(step / total, text=f"({step}/{total}) {label}")

        try:
            result = get_popular_places(region_name, purpose_keyword, progress_callback=on_progress)
        except Exception as e:
            st.error(f"분석 중 오류가 발생했습니다: {e}")
            result = None

        progress_bar.empty()

        if result is not None:
            st.session_state["popular_places_result"] = result
            st.session_state["popular_places_query"] = (region_name, purpose_keyword)

result = st.session_state.get("popular_places_result")

if result:
    region_name, purpose_keyword = st.session_state.get("popular_places_query", ("", ""))
    results = result["places"]
    meta = result["meta"]
    doc_counts = meta["doc_type_counts"]
    type_counts = meta.get("place_type_counts", {})
    type_summary = (
        " / ".join(f"{t} {n}곳" for t, n in sorted(type_counts.items(), key=lambda x: -x[1]))
        or "없음"
    )

    method_col, period_help_col = st.columns([10, 1])
    with period_help_col.popover("❓", help="분석 기간 기준 보기"):
        st.markdown(f"**분석 기간**\n\n검색 시점: {meta['searched_on']}\n\n{HELP_PERIOD}")

    with method_col.expander("📑 분석 방법 / 근거 보기"):
        st.markdown(
            f"""
- **검색 소스**: 블로그 {meta['blog_count']}건 + 카페 {meta['cafe_count']}건 (카카오 검색)
- **검색 키워드**: "{meta['query']}"
- **검색 시점**: {meta['searched_on']}
- **집계 방법**: 이 지역 공간 후보 {meta['candidate_count']}곳의 이름이 위 글들에 몇 번 등장하는지 카운트
- **글 신뢰도 분류**: 💚 진짜후기 {doc_counts['진짜후기']}건 / 일반 {doc_counts['일반']}건 / 📣 광고성 {doc_counts['광고성']}건
- **공간 유형**: {type_summary}
- **순위 기준**: 진짜후기 + 일반 언급 위주 (광고성 언급은 가중치를 낮춰 반영)

📌 **협찬은 주로 이미지로 표기되어 텍스트로는 일부만 잡힙니다.** 대신 '내돈내산' 등 진짜 후기 신호를
함께 집계해 신뢰도를 보완합니다.

📌 **임시 팝업·전시는 지도에 미등록이거나, 등록돼 있어도 글에서 다른 이름으로 불리면 누락될 수 있습니다.**
(팝업은 기간이 짧고 이름이 자주 바뀌어 특히 잡히기 어렵습니다.)

⚠️ **실제 방문객 수가 아닌 온라인 언급 빈도 기준**입니다. 블로그·카페 글이 많이 쓰인 곳일수록 높게 나옵니다.
"""
        )

    all_mentioned = [p for p in results if p["mention_count"] > 0]

    if not all_mentioned:
        st.info("블로그·카페 글에서 언급된 공간을 찾지 못했습니다. 다른 지역이나 키워드로 시도해보세요.")
    else:
        available_types = sorted({p["place_type"] for p in all_mentioned})
        selected_types = st.multiselect(
            "공간 유형 필터",
            available_types,
            default=available_types,
            help="특정 유형(예: 전시)만 골라서 볼 수 있습니다.",
        )
        mentioned = [p for p in all_mentioned if p["place_type"] in selected_types]

        if not mentioned:
            st.info("선택한 유형에 해당하는 공간이 없습니다. 유형을 다시 선택해주세요.")
            st.stop()

        TOP_COUNT = 15
        top_places = mentioned[:TOP_COUNT]
        top_place = top_places[0]

        title_col, help_col = st.columns([10, 1])
        title_col.subheader(f"'{region_name} {purpose_keyword}' 인기 공간 TOP {len(top_places)}")
        with help_col.popover("❓", help="순위 산출 방법 보기"):
            st.markdown(f"**인기 공간 순위란?**\n\n{HELP_RANKING}")

        signal_col1, signal_col2, signal_col3 = st.columns([1, 1, 6])
        with signal_col1.popover("💚 진짜후기 ❓"):
            st.markdown(f"**💚 진짜후기**\n\n{HELP_GENUINE}")
        with signal_col2.popover("📣 광고성 ❓"):
            st.markdown(f"**📣 광고성**\n\n{HELP_AD}")

        st.markdown(
            f'<div class="highlight-line">🏆 1위: {top_place["name"]} '
            f'(총 {top_place["mention_count"]}회 언급 · 진짜후기 {top_place["genuine_count"]} / '
            f'일반 {top_place["normal_count"]} / 광고성 {top_place["ad_count"]})</div>',
            unsafe_allow_html=True,
        )

        genuine_leader = max(top_places, key=lambda p: p["genuine_count"])
        if genuine_leader["genuine_count"] > 0:
            st.markdown(
                f'<div class="highlight-line">💚 내돈내산 후기가 가장 많은 곳: {genuine_leader["name"]} '
                f'(진짜후기 {genuine_leader["genuine_count"]}회 언급)</div>',
                unsafe_allow_html=True,
            )

        # 카드 HTML은 개행 없이 한 줄로 이어붙인다 (들여쓴 여러 줄이면 마크다운이 코드블록으로 오인식함)
        card_divs = []
        for rank, place in enumerate(top_places, start=1):
            is_top = rank == 1
            card_class = "place-card top" if is_top else "place-card"
            trophy = " 🏆" if is_top else ""
            badge = '<div class="trust-badge">💚 내돈내산 후기</div>' if place["genuine_count"] > 0 else ""
            card_divs.append(
                f'<div class="{card_class}">'
                f'<div class="place-rank">{rank}위{trophy} · {place["place_type"]}</div>'
                f'<div class="place-name">{place["name"]}</div>'
                f"{badge}"
                f'<div class="place-value">{place["mention_count"]}<span class="place-unit">회 언급</span></div>'
                f'<div class="mention-breakdown">'
                f'<span class="g">💚 진짜후기 {place["genuine_count"]}</span> · '
                f'일반 {place["normal_count"]} · '
                f'<span class="a">📣 광고성 {place["ad_count"]}</span>'
                f"</div>"
                f'<div class="place-category">{place["category"]}</div>'
                f"</div>"
            )
        st.markdown('<div class="place-grid">' + "".join(card_divs) + "</div>", unsafe_allow_html=True)

        st.subheader("지도")
        center_lat = sum(p["lat"] for p in top_places) / len(top_places)
        center_lon = sum(p["lon"] for p in top_places) / len(top_places)

        m = folium.Map(location=[center_lat, center_lon], zoom_start=12)
        cluster = MarkerCluster(name="인기 공간").add_to(m)

        for rank, place in enumerate(top_places, start=1):
            emoji = "🏆" if rank == 1 else "📍"
            icon_html = f'<div style="font-size: 20px; line-height: 1; text-align: center;">{emoji}</div>'
            folium.Marker(
                location=[place["lat"], place["lon"]],
                tooltip=f"{rank}위 {place['name']} ({place['mention_count']}회)",
                icon=folium.DivIcon(html=icon_html, icon_size=(24, 24), icon_anchor=(12, 20)),
            ).add_to(cluster)

        folium_static(m, width=None, height=420)
        st.caption("🏆 1위 · 📍 나머지 인기 공간 (숫자 원은 확대하면 펼쳐지는 클러스터입니다)")

        st.caption(
            f"※ 카카오 장소검색으로 찾은 이 지역 공간 후보 {len(results)}개 중, "
            f"블로그·카페 글에 실제로 언급된 {len(all_mentioned)}개를 집계했습니다"
            f"(선택한 유형: {len(mentioned)}개)."
        )
else:
    st.info("지역명과 목적 키워드를 정하고 [인기 공간 분석]을 눌러주세요.")
