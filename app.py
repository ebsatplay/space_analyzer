"""공간 분석 랩 - 진입점.

실제 화면은 views/ 아래에 있고, 여기서는 로고와 메뉴(네비게이션)만 구성한다.
분석 기능 3개와 관리자용 설정을 섹션으로 나눠서 보여준다.

실행: streamlit run app.py
"""

import streamlit as st

from views._theme import BRAND_NAME, apply_theme, render_brand_logo

st.set_page_config(page_title=BRAND_NAME, page_icon="🔬", layout="wide")

# 로고는 메뉴보다 위에 와야 하므로 st.navigation()보다 먼저 그린다
apply_theme()
render_brand_logo()

pages = {
    "분석": [
        st.Page("views/living_area.py", title="생활권 분석", icon="🏘️", default=True),
        st.Page("views/backyard.py", title="배후권 비교", icon="🗺️"),
        st.Page("views/popular_places.py", title="인기 공간", icon="✨"),
    ],
    "설정": [
        st.Page("views/data_management.py", title="데이터 관리", icon="⚙️"),
    ],
}

st.navigation(pages).run()
