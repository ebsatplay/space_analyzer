"""보고서에 넣을 지도·차트 이미지를 만든다.

지도는 staticmap으로 OSM 타일을 받아 그린다 (브라우저/selenium 없이 되고 한글 지명이
타일에 들어 있다). 차트는 matplotlib으로 그린다.

차트 설계 (시각화 가이드 기준):
  - 두 차트 모두 '범주별 크기'라 막대를 쓴다. 계열이 하나뿐이라 범례는 두지 않고
    제목이 계열을 설명한다. 막대마다 값을 직접 붙여 색에만 의존하지 않게 한다.
  - 색은 앱 차트와 같은 #1D8FB5 하나만 쓴다 (명도·채도·대비 검증 통과).
  - 격자는 옅게, 위·오른쪽 축선은 지운다.

한글 폰트는 맑은 고딕을 쓴다. 지정하지 않으면 matplotlib이 네모(두부)로 그린다.
"""

import io as _io
import math
import sys

import matplotlib

matplotlib.use("Agg")  # 화면 없는 환경에서 그리기 위해 백엔드를 먼저 고정한다
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

BRAND_COLOR = "#1D8FB5"
CENTER_COLOR = "#C94D63"
SCHOOL_COLOR = "#5C8A6B"
SITE_COLOR = "#B87332"

GRID_COLOR = "#E1E0D9"
TEXT_COLOR = "#4A4238"
MUTED_COLOR = "#8A8178"

# 폰트 경고를 매 차트마다 찍지 않도록 한 번만 남긴다
_FONT_WARNED = False

MAP_SIZE = (960, 640)
MAP_TILE_URL = "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"
# OSM 타일 이용 정책은 앱을 식별할 수 있는 User-Agent를 요구한다. staticmap 기본값은
# 'StaticMap'이라 차단될 수 있어서 직접 지정한다 (배포 환경에서 특히 위험하다).
MAP_USER_AGENT = "SpaceAnalysisLab/1.0 (+https://github.com/sooave00/space_analyzer)"
# 원을 선분으로 근사할 때 쓰는 각도 간격
CIRCLE_STEP_DEG = 5
# 지도에 찍을 시설 마커 상한 (너무 많으면 지도가 가려진다)
MAX_MARKERS = 40

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# 배포(리눅스)에는 packages.txt 로 fonts-nanum 을 깔아 NanumGothic 계열이 생긴다.
# 로컬 윈도우는 맑은 고딕, 맥은 AppleGothic 을 쓴다.
#
# packages.txt 에는 패키지명만 한 줄씩 적는다 (주석을 지원하는지 확실하지 않아
# 설명을 넣지 않는다). fonts-nanum-coding 은 Debian 저장소에 없어서 배포가 실패한다
# - 코딩용 고정폭 폰트라 차트에는 쓰이지도 않으므로 넣지 말 것.
KOREAN_FONT_CANDIDATES = (
    "Malgun Gothic",
    "NanumGothic",
    "NanumBarunGothic",
    "NanumSquare",
    "Noto Sans KR",
    "Noto Sans CJK KR",
    "AppleGothic",
    "Gulim",
)


def _korean_font():
    """설치된 한글 폰트 중 쓸 수 있는 것을 고른다 (없으면 None)."""
    available = {font.name for font in fm.fontManager.ttflist}
    for candidate in KOREAN_FONT_CANDIDATES:
        if candidate in available:
            return candidate
    return None


def _apply_chart_style():
    """차트 공통 스타일. 한글 폰트를 지정하지 않으면 글자가 네모(두부)로 나온다.

    폰트를 못 찾으면 예외 없이 조용히 깨지므로(차트는 그려지는데 글자만 네모),
    한 번 경고를 남겨 배포 환경에서 바로 알 수 있게 한다.
    """
    font = _korean_font()
    if font:
        plt.rcParams["font.family"] = font
    else:
        global _FONT_WARNED
        if not _FONT_WARNED:
            print(
                "한글 폰트를 찾지 못했습니다. 차트의 한글이 네모로 나옵니다. "
                "배포 환경이라면 packages.txt 에 fonts-nanum 이 있는지 확인하세요."
            )
            _FONT_WARNED = True
    plt.rcParams["axes.unicode_minus"] = False  # 음수 기호가 깨지는 것을 막는다
    plt.rcParams["figure.dpi"] = 150


def _figure_to_png(figure):
    buffer = _io.BytesIO()
    figure.savefig(buffer, format="png", bbox_inches="tight", facecolor="white")
    plt.close(figure)
    buffer.seek(0)
    return buffer.getvalue()


def _circle_points(lat, lon, radius_km):
    """반경 원을 선분 좌표로 바꾼다 (staticmap에 원 그리기가 없어서 선으로 그린다)."""
    points = []
    for degree in range(0, 361, CIRCLE_STEP_DEG):
        angle = math.radians(degree)
        delta_lat = radius_km / 111.0 * math.cos(angle)
        delta_lon = radius_km / (111.0 * math.cos(math.radians(lat))) * math.sin(angle)
        points.append((lon + delta_lon, lat + delta_lat))
    return points


def render_living_area_map(lat, lon, radius_km, schools=None, sites=None):
    """생활권 지도 - 기준점 + 생활권 원 + 학교·부지 후보 마커.

    타일 서버를 쓰므로 네트워크가 막히면 None을 돌려준다 (보고서는 지도 없이 진행).
    """
    try:
        from staticmap import CircleMarker, Line, StaticMap

        area_map = StaticMap(
            MAP_SIZE[0],
            MAP_SIZE[1],
            url_template=MAP_TILE_URL,
            headers={"User-Agent": MAP_USER_AGENT},
        )
        area_map.add_line(Line(_circle_points(lat, lon, radius_km), BRAND_COLOR, 3))

        if schools is not None and len(schools):
            # 거리순 앞에서 자르면 중심에만 뭉쳐 "중심에만 학교가 있다"로 잘못 읽힌다.
            # 반경 전체에 고르게 보이도록 일정 간격으로 솎아낸다.
            step = max(1, len(schools) // MAX_MARKERS)
            for row in schools.iloc[::step].head(MAX_MARKERS).itertuples(index=False):
                area_map.add_marker(CircleMarker((row.lon, row.lat), SCHOOL_COLOR, 7))

        if sites is not None and len(sites):
            for row in sites.head(MAX_MARKERS).itertuples(index=False):
                area_map.add_marker(CircleMarker((row.lon, row.lat), SITE_COLOR, 9))

        # 기준점은 맨 마지막에 찍어야 다른 마커에 가리지 않는다
        area_map.add_marker(CircleMarker((lon, lat), "#FFFFFF", 16))
        area_map.add_marker(CircleMarker((lon, lat), CENTER_COLOR, 12))

        return _figure_png_from_image(area_map.render())
    except Exception as e:
        print(f"지도 생성 실패 (지도 없이 진행합니다): {type(e).__name__}: {e}")
        return None


def _figure_png_from_image(image):
    buffer = _io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.getvalue()


def _style_axes(axes, horizontal=False):
    """격자는 옅게, 위·오른쪽 축선은 지운다 (데이터가 주인공이 되게).

    눈금은 정수로만 찍고 천단위 쉼표를 붙인다 - 사람·개수는 소수점이 없는 값이라
    기본 눈금(0.0, 2.5, 5.0...)은 틀린 인상을 준다.
    """
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    axes.spines["left"].set_color(GRID_COLOR)
    axes.spines["bottom"].set_color(GRID_COLOR)
    axes.tick_params(colors=MUTED_COLOR, labelsize=9, length=0)

    value_axis = axes.xaxis if horizontal else axes.yaxis
    value_axis.set_major_locator(MaxNLocator(integer=True, nbins=6))
    value_axis.set_major_formatter(FuncFormatter(lambda v, _pos: f"{int(v):,}"))

    if horizontal:
        axes.xaxis.grid(True, color=GRID_COLOR, linewidth=0.8)
        axes.yaxis.grid(False)
    else:
        axes.yaxis.grid(True, color=GRID_COLOR, linewidth=0.8)
        axes.xaxis.grid(False)
    axes.set_axisbelow(True)


def render_age_chart(population):
    """연령별 인구 막대그래프 (세로). 범주가 3개뿐이라 세로 막대가 읽기 좋다."""
    _apply_chart_style()

    labels = ["0~9세\n(어린이)", "10~14세", "30~49세\n(가족수요층)"]
    values = [
        population.get("age_0_9", 0),
        population.get("age_10_14", 0),
        population.get("age_30_49", 0),
    ]

    figure, axes = plt.subplots(figsize=(6.2, 3.2))
    bars = axes.bar(labels, values, color=BRAND_COLOR, width=0.52)
    _style_axes(axes)

    # 막대마다 값을 직접 붙인다 (색만으로 읽게 두지 않는다)
    headroom = max(values) * 0.08 if max(values) else 1
    for bar, value in zip(bars, values):
        axes.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + headroom * 0.3,
            f"{value:,}",
            ha="center",
            va="bottom",
            fontsize=10,
            color=TEXT_COLOR,
            fontweight="bold",
        )
    axes.set_ylim(0, max(values) + headroom * 2 if max(values) else 1)
    axes.set_title(
        "연령대별 인구 (명)", fontsize=12, color=TEXT_COLOR, fontweight="bold", pad=12
    )

    return _figure_to_png(figure)


def render_facility_chart(child_spaces):
    """어린이 공간 레퍼런스 유형별 개수 (가로). 범주명이 길어 가로 막대로 둔다."""
    _apply_chart_style()

    names = list(child_spaces.keys())
    values = [group["count"] for group in child_spaces.values()]

    # 가로 막대는 위에서 아래로 읽히므로 순서를 뒤집어 큰 값이 위로 가게 한다
    order = sorted(range(len(values)), key=lambda i: values[i])
    names = [names[i] for i in order]
    values = [values[i] for i in order]

    figure, axes = plt.subplots(figsize=(6.2, 3.4))
    bars = axes.barh(names, values, color=BRAND_COLOR, height=0.56)
    _style_axes(axes, horizontal=True)

    headroom = max(values) * 0.1 if max(values) else 1
    for bar, value in zip(bars, values):
        axes.text(
            bar.get_width() + headroom * 0.2,
            bar.get_y() + bar.get_height() / 2,
            f"{value:,}",
            ha="left",
            va="center",
            fontsize=10,
            color=TEXT_COLOR,
            fontweight="bold",
        )
    axes.set_xlim(0, max(values) + headroom * 2 if max(values) else 1)
    axes.set_title(
        "어린이 공간 레퍼런스 유형별 개수 (개)", fontsize=12, color=TEXT_COLOR,
        fontweight="bold", pad=12,
    )

    return _figure_to_png(figure)


def render_household_chart(households):
    """세대원수별 세대수 (가로). 가족 가구 비중을 눈으로 보게 한다."""
    _apply_chart_style()

    names = ["5인 이상", "3~4인\n(가족 가구)", "1~2인\n(소형)"]
    values = [
        households.get("household_5plus", 0),
        households.get("household_3_4", 0),
        households.get("household_1_2", 0),
    ]

    figure, axes = plt.subplots(figsize=(6.2, 2.8))
    bars = axes.barh(names, values, color=BRAND_COLOR, height=0.52)
    _style_axes(axes, horizontal=True)

    headroom = max(values) * 0.1 if max(values) else 1
    for bar, value in zip(bars, values):
        axes.text(
            bar.get_width() + headroom * 0.2,
            bar.get_y() + bar.get_height() / 2,
            f"{value:,}",
            ha="left",
            va="center",
            fontsize=10,
            color=TEXT_COLOR,
            fontweight="bold",
        )
    axes.set_xlim(0, max(values) + headroom * 2 if max(values) else 1)
    axes.set_title(
        "세대원수별 세대수 (세대)", fontsize=12, color=TEXT_COLOR, fontweight="bold", pad=12
    )

    return _figure_to_png(figure)


def main():
    """샘플 데이터로 이미지 3종을 만들어 눈으로 확인한다."""
    population = {"age_0_9": 2048, "age_10_14": 1708, "age_30_49": 11052}
    households = {"household_1_2": 26215, "household_3_4": 4595, "household_5plus": 539}
    child_spaces = {
        "직접 경쟁": {"count": 0},
        "공공 돌봄·교육": {"count": 12},
        "가족 여가": {"count": 16},
        "프로그램 운영 공간": {"count": 0},
        "체험 레퍼런스": {"count": 17},
        "부지 후보": {"count": 4},
    }

    for name, content in (
        ("_chart_age.png", render_age_chart(population)),
        ("_chart_household.png", render_household_chart(households)),
        ("_chart_facility.png", render_facility_chart(child_spaces)),
    ):
        with open(name, "wb") as f:
            f.write(content)
        print(f"{name}: {len(content):,} bytes")

    map_png = render_living_area_map(37.7240, 126.7640, 30.0)
    if map_png:
        with open("_map_living_area.png", "wb") as f:
            f.write(map_png)
        print(f"_map_living_area.png: {len(map_png):,} bytes")


if __name__ == "__main__":
    main()
