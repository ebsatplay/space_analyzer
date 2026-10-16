"""대상지 조사 보고서를 Word(.docx) 파일로 만든다.

analysis/report_data.py가 모은 데이터를 받아 서식을 입힌다.
표에는 헤더·단위·천단위 쉼표를 넣고, 각 섹션에 수치 기반 사실 서술과 출처를 붙인다.
해석·제언은 넣지 않는다 - 보고서에 들어갈 객관적 사실만 담는 것이 1단계 범위다.

실행(테스트): python -m analysis.report_docx
"""

import io as _io
import re
import sys
from datetime import date

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from analysis.area_profile import ELEMENTARY

BRAND_NAME = "공간 분석 랩"

# 한글이 깨지지 않도록 본문 폰트를 지정한다 (동아시아 폰트는 따로 지정해야 적용된다)
BODY_FONT = "맑은 고딕"
BODY_SIZE = Pt(10)
HEADING_COLOR = RGBColor(0x3E, 0x7C, 0x91)   # 앱 테마의 청록
MUTED_COLOR = RGBColor(0x8A, 0x81, 0x78)

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _set_font(run, size=BODY_SIZE, bold=False, color=None, font=BODY_FONT):
    """런 하나에 폰트를 입힌다 (동아시아 폰트까지 함께 지정)."""
    run.font.name = font
    run.font.size = size
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    # python-docx는 eastAsia 폰트를 따로 안 넣어줘서 직접 써야 한글에 적용된다
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font)


def _apply_base_style(document):
    """문서 기본 스타일을 한글 문서에 맞게 바꾼다."""
    style = document.styles["Normal"]
    style.font.name = BODY_FONT
    style.font.size = BODY_SIZE
    style.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)


def _add_heading(document, text, level=1):
    """제목을 넣는다 (Word 기본 Heading 스타일은 한글 폰트가 안 먹어서 직접 서식)."""
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(14 if level == 1 else 10)
    paragraph.paragraph_format.space_after = Pt(6)
    run = paragraph.add_run(text)
    _set_font(run, size=Pt(14 if level == 1 else 11.5), bold=True, color=HEADING_COLOR)
    return paragraph


def _add_body(document, text, size=BODY_SIZE, color=None, italic=False):
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(4)
    run = paragraph.add_run(text)
    _set_font(run, size=size, color=color)
    run.font.italic = italic
    return paragraph


def _add_source(document, text):
    """출처·기준 줄 (작고 흐린 글씨)."""
    return _add_body(document, text, size=Pt(8.5), color=MUTED_COLOR)


def _add_table(document, headers, rows, column_widths=None):
    """표를 넣는다. 헤더는 굵게, 숫자 열은 오른쪽 정렬한다."""
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    header_cells = table.rows[0].cells
    for cell, header in zip(header_cells, headers):
        cell.text = ""
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_font(paragraph.add_run(str(header)), size=Pt(9.5), bold=True)

    for row_values in rows:
        cells = table.add_row().cells
        for index, (cell, value) in enumerate(zip(cells, row_values)):
            cell.text = ""
            paragraph = cell.paragraphs[0]
            # 첫 열은 항목명이라 왼쪽, 나머지(수치)는 오른쪽 정렬
            paragraph.alignment = (
                WD_ALIGN_PARAGRAPH.LEFT if index == 0 else WD_ALIGN_PARAGRAPH.RIGHT
            )
            _set_font(paragraph.add_run(str(value)), size=Pt(9.5))

    if column_widths:
        for row in table.rows:
            for cell, width in zip(row.cells, column_widths):
                cell.width = width

    document.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


def _num(value):
    """천단위 쉼표."""
    return f"{value:,}"


def _ymd(value):
    """'20260820' -> '2026-08-20'."""
    text = str(value or "")
    if len(text) != 8 or not text.isdigit():
        return text
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _build_cover(document, overview):
    """표지 - 대상지명 + 작성일 + 브랜드."""
    for _ in range(6):
        document.add_paragraph()

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_font(title.add_run("대상지 조사 보고서"), size=Pt(26), bold=True, color=HEADING_COLOR)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_before = Pt(10)
    _set_font(subtitle.add_run(overview["place_name"]), size=Pt(18), bold=True)

    if overview.get("sigungu_nm"):
        region = document.add_paragraph()
        region.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_font(region.add_run(overview["sigungu_nm"]), size=Pt(11), color=MUTED_COLOR)

    for _ in range(8):
        document.add_paragraph()

    created = document.add_paragraph()
    created.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_font(created.add_run(f"작성일 {overview['created_on']}"), size=Pt(10.5))

    brand = document.add_paragraph()
    brand.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_font(brand.add_run(BRAND_NAME), size=Pt(12), bold=True, color=HEADING_COLOR)

    document.add_page_break()


def _build_overview(document, overview):
    """1. 대상지 개요."""
    _add_heading(document, "1. 대상지 개요")

    rows = [
        ("대상지", overview["place_name"]),
        ("주소", overview["address"] or "-"),
        ("행정구역", overview["sigungu_nm"] or "확인 불가"),
        ("좌표", f"위도 {overview['lat']:.6f} / 경도 {overview['lon']:.6f}"),
        (
            "분석 생활권",
            f"{overview['minutes']}분 (평균 {overview['speed_kmh']}km/h 환산, "
            f"직선 반경 약 {overview['radius_km']:.1f}km)",
        ),
        ("포함 행정동", f"{overview['dong_count']}개"),
    ]
    _add_table(document, ["구분", "내용"], rows)

    if overview["dong_names"]:
        # 다른 시군구에 같은 이름의 동이 있으면 목록에 같은 이름이 두 번 나온다
        # (예: 고령군 덕곡면 / 합천군 덕곡면). 중복처럼 보이지 않게 개수를 붙인다.
        from collections import Counter

        name_counts = Counter(overview["dong_names"])
        labels = [
            name if count == 1 else f"{name} {count}곳"
            for name, count in name_counts.items()
        ]
        _add_body(document, f"포함 행정동: {', '.join(labels)}")

    _add_source(
        document,
        "※ 생활권은 기준점에서 설정한 이동시간을 직선거리로 환산한 원이며, "
        "실제 도로 이동거리와는 다릅니다. 행정동 경계는 통계청 SGIS 기준입니다.",
    )


def _build_population(document, data):
    """2. 인구·가구 현황."""
    _add_heading(document, "2. 인구·가구 현황")

    population = data["population"]
    households = data["households"]

    _add_heading(document, "2-1. 인구", level=2)
    rows = [
        ("총인구", _num(population["total"]), "명"),
        ("0~9세 (어린이)", _num(population["age_0_9"]), "명"),
        ("10~14세", _num(population["age_10_14"]), "명"),
        ("30~49세 (가족수요층)", _num(population["age_30_49"]), "명"),
        ("어린이 비율 (0~9세)", f"{data['child_ratio']}", "%"),
    ]
    _add_table(document, ["구분", "값", "단위"], rows)

    nationwide = data.get("nationwide_child_ratio")
    sentences = [
        f"생활권 총인구는 {_num(population['total'])}명이며, "
        f"0~9세 어린이 인구는 {_num(population['age_0_9'])}명({data['child_ratio']}%)입니다."
    ]
    if nationwide:
        gap = data["child_ratio"] - nationwide
        sentences.append(
            f"어린이 비율은 전국 평균 {nationwide:.1f}% 대비 {gap:+.1f}%p입니다."
        )
    _add_body(document, " ".join(sentences))

    if population["unmatched"]:
        _add_body(
            document,
            f"※ 행정구역 개편 등으로 인구 데이터에 포함되지 않은 행정동이 "
            f"{len(population['unmatched'])}개 있어 실제보다 적게 집계되었을 수 있습니다.",
            size=Pt(9),
            color=MUTED_COLOR,
        )

    _add_heading(document, "2-2. 가구", level=2)
    rows = [
        ("전체 세대", _num(households["total_households"]), "세대"),
        ("1~2인 세대 (소형)", _num(households["household_1_2"]), "세대"),
        ("3~4인 세대 (가족 가구)", _num(households["household_3_4"]), "세대"),
        ("5인 이상 세대", _num(households["household_5plus"]), "세대"),
        ("가족 가구 비중 (3~4인)", f"{households['family_ratio']}", "%"),
    ]
    _add_table(document, ["구분", "값", "단위"], rows)

    _add_body(
        document,
        f"생활권 전체 세대는 {_num(households['total_households'])}세대이며, "
        f"어린이 수요층에 해당하는 3~4인 가족 가구는 "
        f"{_num(households['household_3_4'])}세대({households['family_ratio']}%)입니다.",
    )

    _add_source(
        document,
        "※ 출처: 행정안전부 주민등록 인구통계·세대원수별 세대수 (읍면동 단위, 월 단위 갱신). "
        "가족 가구 비중은 생활권 전체 세대를 분모로 다시 계산한 값입니다.",
    )


def _build_education(document, data):
    """3. 교육·학생 현황."""
    _add_heading(document, "3. 교육·학생 현황")

    facilities = data["facilities"]
    counts = facilities["counts"]
    students = facilities["students"]

    rows = []
    for level in ("초등학교", "중학교", "고등학교"):
        rows.append(
            (
                level,
                _num(counts[level]),
                _num(students[level]) if counts[level] else "-",
            )
        )
    rows.append(("합계", _num(sum(counts.values())), _num(facilities["students_total"])))
    _add_table(document, ["학교급", "학교 수(개)", "재학 학생수(명)"], rows)

    lower = facilities["students_grade_1_3"]
    elementary = students["초등학교"]
    sentences = [
        f"생활권 내 학교는 {sum(counts.values())}개이며 재학 학생은 "
        f"{_num(facilities['students_total'])}명입니다."
    ]
    if elementary:
        sentences.append(
            f"이 중 초등 저학년(1~3학년)은 {_num(lower)}명으로 "
            f"초등학생 {_num(elementary)}명의 {data['lower_grade_ratio']}%입니다."
        )
        nationwide = data.get("nationwide_lower_grade_ratio")
        if nationwide:
            sentences.append(f"전국 평균 저학년 비중은 {nationwide:.1f}%입니다.")
    _add_body(document, " ".join(sentences))

    unmatched = sum(counts.values()) - facilities["matched_total"]
    if unmatched:
        _add_body(
            document,
            f"※ 생활권 학교 {sum(counts.values())}개 중 {unmatched}개는 학생수가 연결되지 "
            "않아(분교·폐교·교명 변경 등) 위 합계에서 빠져 있습니다.",
            size=Pt(9),
            color=MUTED_COLOR,
        )

    _add_source(
        document,
        "※ 출처: 학교 위치는 공공데이터포털 전국초중등학교위치표준데이터, "
        "학생수는 학교알리미 정보공시 자료입니다. "
        "학교와 학생수는 학교코드 체계가 달라 학교명으로 연결했습니다.",
    )


def _build_facilities(document, data):
    """4. 주변 시설 현황 - 어린이 공간 레퍼런스 + 밀도·포화도."""
    _add_heading(document, "4. 주변 시설 현황")

    child_spaces = data["child_spaces"]

    _add_heading(document, "4-1. 어린이 공간 레퍼런스", level=2)
    rows = [(name, _num(group["count"])) for name, group in child_spaces.items()]
    _add_table(document, ["유형", "개수(개)"], rows)

    care = child_spaces["공공 돌봄·교육"]
    program = child_spaces["프로그램 운영 공간"]
    site = child_spaces["부지 후보"]

    _add_body(
        document,
        f"생활권 내 공공 돌봄·교육 공간은 {care['count']}개"
        f"(어린이도서관 {care['child_library_count']}개, "
        f"작은도서관 {care['small_library_count']}개, "
        f"공공도서관 {care['public_library_count']}개, "
        f"지역아동센터 {care['child_center_count']}개)입니다.",
    )
    if care["child_center_count"]:
        _add_body(
            document,
            f"지역아동센터 아동 돌봄 수용 규모는 정원 {_num(care['child_center_capacity'])}명, "
            f"현원 {_num(care['child_center_enrolled'])}명입니다.",
        )
    _add_body(
        document,
        f"평생교육 프로그램을 운영할 수 있는 개방 공간(강의실·강당·다목적실·회의실·전시실)은 "
        f"{program['count']}개이며, 공간을 들일 수 있는 부지 후보는 {site['count']}개"
        f"(미활용 폐교 {site['unused_school_count']}개, "
        f"수용 200명 이상 개방시설 {site['large_facility_count']}개)입니다.",
    )

    if site["items"]:
        _add_body(document, f"부지 후보: {', '.join(site['items'][:10])}")

    _add_source(
        document,
        "※ 출처: 직접 경쟁(키즈카페·실내놀이터)은 카카오 장소검색 실시간 결과이며, "
        "나머지는 공공데이터포털 표준데이터(도서관·지역아동센터·문화여가시설·"
        "공공시설개방·폐교재산)입니다.",
    )

    density = data.get("density")
    if not density:
        return

    _add_heading(document, "4-2. 어린이 공간 밀도·포화도", level=2)
    benchmarks = data.get("benchmarks") or {}
    ratio = density["children_per_space"]
    rows = [
        ("생활권 0~9세 인구", _num(data["population"]["age_0_9"]), "명"),
        ("공공 돌봄·교육 공간", _num(care["count"]), "개"),
        ("공간 1개당 어린이", _num(ratio) if ratio is not None else "-", "명"),
    ]
    if benchmarks:
        rows.append(("전국 중위 (공간당 어린이)", _num(round(benchmarks["ratio_median"])), "명"))
    _add_table(document, ["구분", "값", "단위"], rows)

    if ratio is not None:
        sentence = (
            f"공공 돌봄·교육 공간 1개당 어린이는 {_num(ratio)}명으로 "
            f"전국 {benchmarks.get('sigungu_count', 0)}개 시군구 분포에서 "
            f"'{density['label']}' 구간에 해당합니다."
        )
    else:
        sentence = "생활권 내 공공 돌봄·교육 공간이 없어 공간당 어린이 수를 계산할 수 없습니다."
    _add_body(document, sentence)

    # 판정이 왜곡될 수 있는 경우는 보고서에도 반드시 남긴다 (사실이자 한계)
    if density.get("caution"):
        _add_body(document, f"※ {density['caution']}", size=Pt(9), color=MUTED_COLOR)
    if density.get("coverage_note"):
        _add_body(document, f"※ {density['coverage_note']}", size=Pt(9), color=MUTED_COLOR)

    if benchmarks:
        _add_source(
            document,
            f"※ 판정 구간은 전국 {benchmarks['sigungu_count']}개 시군구 분포의 사분위 기준입니다 "
            f"(여유 {benchmarks['ratio_q1']:.0f}명 이하 / 중위 {benchmarks['ratio_median']:.0f}명 / "
            f"부족 {benchmarks['ratio_q3']:.0f}명 이상). "
            "분자는 생활권 원 안의 공간 수, 분모는 생활권 0~9세 인구이며 "
            "비교 기준선은 시군구 단위라 단위가 완전히 같지는 않습니다.",
        )


def _build_footer_note(document):
    """맨 뒤 안내 - 1단계 범위와 데이터 기준."""
    document.add_page_break()
    _add_heading(document, "보고서 안내")
    _add_body(
        document,
        "이 보고서는 공개 데이터를 기준점 주변 생활권으로 집계한 결과입니다. "
        "수치는 모두 원본 데이터에서 계산한 값이며, 해석이나 사업 제언은 담고 있지 않습니다.",
    )
    _add_body(
        document,
        "지역 사업 뉴스와 인기 공간은 실시간 검색 항목이라 보고서 생성 시 선택한 경우에만 "
        "들어갑니다. 주민 니즈는 사회조사 보고서를 첨부한 경우에만 들어갑니다.",
        color=MUTED_COLOR,
    )
    _add_source(
        document,
        f"{BRAND_NAME} · 데이터 기준일은 각 섹션의 출처 표기를 참고하세요.",
    )


def _build_tourism(document, data):
    """5. 관광·방문 특성."""
    _add_heading(document, "5. 관광·방문 특성")

    tourism = data.get("tourism") or {}
    if not tourism.get("available"):
        _add_body(document, "이 대상지는 관광 방문 데이터 집계 대상이 아닙니다.")
        _add_source(
            document,
            "※ 한국관광공사 데이터랩은 출장소 등 일부 지역을 집계하지 않습니다.",
        )
        return

    visitors = tourism.get("visitors")
    datalab = tourism.get("datalab")

    if visitors:
        _add_heading(document, "5-1. 방문자 구성", level=2)
        rows = [
            ("전체 방문자", _num(visitors["visitors_total"]), "명"),
            ("현지인", _num(visitors["visitors_local"]), "명"),
            ("외지인", _num(visitors["visitors_outsider"]), "명"),
            ("외국인", _num(visitors["visitors_foreign"]), "명"),
            ("외지인 비중", f"{visitors['outsider_ratio']:.1f}", "%"),
            ("주말 유입 배수", f"{visitors['weekend_lift']:.2f}", "배"),
        ]
        _add_table(document, ["구분", "값", "단위"], rows)

        quartiles = visitors.get("quartiles") or {}
        sentences = [
            f"기준 기간({_ymd(visitors['base_start_ymd'])} ~ "
            f"{_ymd(visitors['base_end_ymd'])}, "
            f"{visitors['days']}일) 방문자는 {_num(visitors['visitors_total'])}명이며 "
            f"외지인 비중은 {visitors['outsider_ratio']:.1f}%입니다."
        ]
        if quartiles:
            sentences.append(
                f"전국 {quartiles['sigungu_count']}개 시군구 중위 "
                f"{quartiles['outsider_ratio_median']:.1f}% 대비 "
                f"{visitors['outsider_ratio'] - quartiles['outsider_ratio_median']:+.1f}%p입니다."
            )
        sentences.append(
            f"외지인 하루 평균은 평일 {_num(visitors['outsider_weekday_avg'])}명, "
            f"주말 {_num(visitors['outsider_weekend_avg'])}명으로 "
            f"{visitors['weekend_lift']:.2f}배입니다."
        )
        _add_body(document, " ".join(sentences))

        if visitors.get("pattern"):
            _add_body(
                document,
                f"전국 분포 기준 구분: {visitors['pattern']['label']}",
            )

        _add_source(
            document,
            "※ 출처: 한국관광공사 데이터랩 지역별 방문자수. 방문자는 해당 지역에 일상권을 "
            "벗어나 머문 사람으로 관광객과 유사하나 동일하지 않습니다. "
            "이동통신 기반 추정치이며 약 1개월 지연됩니다.",
        )

    if datalab:
        _add_heading(document, "5-2. 체류·숙박", level=2)
        quartiles = datalab.get("quartiles") or {}
        rows = [
            ("평균 체류시간", f"{datalab['avg_stay_hours']}", "시간"),
            ("평균 숙박일수", f"{datalab['avg_stay_nights']:.2f}", "일"),
        ]
        if quartiles:
            rows.append(
                ("전국 중위 체류시간", f"{quartiles['stay_minutes_median'] / 60:.1f}", "시간")
            )
            rows.append(("전국 중위 숙박일수", f"{quartiles['stay_nights_median']:.2f}", "일"))
        _add_table(document, ["구분", "값", "단위"], rows)

        if quartiles:
            _add_body(
                document,
                f"평균 체류시간은 {datalab['avg_stay_hours']}시간으로 전국 중위 "
                f"{quartiles['stay_minutes_median'] / 60:.1f}시간 대비 "
                f"{datalab['stay_vs_median'] / 60:+.1f}시간이며, 평균 숙박일수는 "
                f"{datalab['avg_stay_nights']:.2f}일로 중위 대비 "
                f"{datalab['nights_vs_median']:+.2f}일입니다.",
            )

        notes = []
        if datalab.get("fallback_from"):
            notes.append(
                f"데이터랩은 분구를 합친 시 단위로 제공하므로 {datalab['sigungu_nm']} 전체 값입니다"
            )
        if datalab.get("period_merged"):
            notes.append("행정구역 통합 지역이라 통합 전후 기간을 합산한 값입니다")
        if notes:
            _add_body(document, f"※ {' · '.join(notes)}", size=Pt(9), color=MUTED_COLOR)

        _add_source(document, "※ 출처: 한국관광공사 데이터랩 시군구별 체류시간·숙박일수.")

    detail = tourism.get("detail")
    if not tourism.get("registered") or detail is None:
        _add_heading(document, "5-3. 유입·유출 지역 및 유사 지역", level=2)
        _add_body(
            document,
            "이 대상지는 지역 상세 데이터(유입·유출, 유사 지역)가 아직 등록되지 않았습니다.",
        )
        _add_source(
            document,
            "※ 데이터랩 지역 상세는 지역별로 따로 내려받아 등록해야 하며, "
            "현재는 일부 지역만 등록되어 있습니다.",
        )
        return

    _add_heading(document, "5-3. 유입·유출 지역", level=2)
    inflow = detail.get("inflow") or []
    outflow = detail.get("outflow") or []
    rows = []
    for index in range(max(len(inflow), len(outflow))):
        rows.append(
            (
                f"{index + 1}위",
                inflow[index]["counterpart_nm"] if index < len(inflow) else "-",
                f"{inflow[index]['ratio']}%" if index < len(inflow) else "-",
                outflow[index]["counterpart_nm"] if index < len(outflow) else "-",
                f"{outflow[index]['ratio']}%" if index < len(outflow) else "-",
            )
        )
    _add_table(document, ["순위", "유입 지역", "비율", "유출 지역", "비율"], rows)

    if inflow:
        top_names = ", ".join(f"{item['counterpart_nm']} {item['ratio']}%" for item in inflow[:3])
        _add_body(document, f"유입 상위 지역은 {top_names} 순입니다.")

    if detail.get("similar_regions"):
        _add_heading(document, "5-4. 관광 성격이 유사한 지역", level=2)
        _add_body(document, f"{detail['region_nm']} ≈ {' · '.join(detail['similar_regions'])}")
        _add_source(
            document,
            "※ 데이터랩이 관광 지표(방문자·체류·소비)가 유사하다고 묶은 지역입니다.",
        )


def _build_trends(document, data):
    """6. 지역 트렌드·이슈 - 선택했을 때만 내용이 들어간다."""
    _add_heading(document, "6. 지역 트렌드·이슈")

    news = data.get("news")
    popular = data.get("popular")

    if news is None and popular is None:
        _add_body(
            document,
            "지역 사업 뉴스와 인기 공간은 실시간 검색이 필요해 이번 보고서에서는 제외했습니다. "
            "보고서 생성 시 해당 항목을 선택하면 포함됩니다.",
        )
        return

    if news is not None:
        _add_heading(document, "6-1. 지역 사업 뉴스", level=2)
        if news.get("error"):
            _add_body(document, f"뉴스를 가져오지 못했습니다: {news['error']}")
        elif not news["items"]:
            _add_body(
                document,
                f"최근 12개월 내 '{news['region']}' 관련 사업 뉴스를 찾지 못했습니다.",
            )
        else:
            rows = [
                (
                    article["published"].strftime("%Y-%m-%d"),
                    article["title"][:60],
                    article["source"],
                    ", ".join(article["matched_keywords"][:2]),
                )
                for article in news["items"]
            ]
            _add_table(document, ["날짜", "제목", "출처", "검색 키워드"], rows)
            _add_body(
                document,
                f"최근 12개월 내 '{news['region']}' 관련 사업 뉴스는 {news['total']}건이며 "
                f"위는 최신 {len(news['items'])}건입니다.",
            )
        _add_source(
            document,
            "※ 출처: 카카오 웹문서 검색. 뉴스 전용 검색이 없어 웹문서에서 지역명·날짜·"
            "도메인·키워드 포함 여부로 걸러낸 결과이며, 언론 기사 외 보도자료가 섞일 수 있습니다.",
        )

    if popular is not None:
        _add_heading(document, "6-2. 인기 공간 (블로그·카페 언급)", level=2)
        if popular.get("error"):
            _add_body(document, f"인기 공간을 가져오지 못했습니다: {popular['error']}")
        elif not popular["items"]:
            _add_body(
                document,
                f"'{popular['region']} {popular['keyword']}' 검색 글에서 언급된 공간을 "
                "찾지 못했습니다.",
            )
        else:
            rows = [
                (
                    f"{index}위",
                    place["name"][:40],
                    place["place_type"],
                    _num(place["mention_count"]),
                    _num(place["genuine_count"]),
                )
                for index, place in enumerate(popular["items"], start=1)
            ]
            _add_table(
                document, ["순위", "공간명", "유형", "언급(회)", "진짜후기(회)"], rows
            )
            meta = popular.get("meta") or {}
            _add_body(
                document,
                f"'{popular['region']} {popular['keyword']}' 검색 글 "
                f"{meta.get('blog_count', 0) + meta.get('cafe_count', 0)}건에서 "
                f"{popular['total']}곳이 언급됐으며 위는 상위 {len(popular['items'])}곳입니다.",
            )
        _add_source(
            document,
            "※ 출처: 카카오 블로그·카페 검색. 실제 방문객 수가 아니라 온라인에서 글이 많이 "
            "쓰인 정도이며, 검색 빅데이터와는 다른 지표입니다.",
        )


def _build_survey(document, data):
    """7. 주민 니즈 - AI가 뽑은 '사실' 영역만 싣는다 (해석은 제외)."""
    _add_heading(document, "7. 주민 니즈 (사회조사)")

    survey = data.get("survey")
    if survey is None:
        _add_body(
            document,
            "사회조사 결과보고서가 첨부되지 않았습니다. 해당 지자체의 사회조사 보고서 "
            "PDF를 첨부하면 거주의향·가족/출산·교육·주거 항목의 주민 응답을 함께 실을 수 "
            "있습니다.",
        )
        _add_source(document, "※ 사회조사 보고서는 지자체 누리집에서 내려받을 수 있습니다.")
        return

    if survey.get("error"):
        _add_body(document, f"사회조사 분석에 실패했습니다: {survey['error']}")
        return

    _add_body(
        document,
        f"{survey['region_name']} 사회조사 결과보고서에서 추출한 주민 응답입니다. "
        "아래 내용은 보고서에 기재된 수치·응답만 담고 있으며, 각 항목의 [p.N]은 "
        "원본 보고서 페이지입니다.",
    )

    _add_markdown_block(document, survey["facts_markdown"])

    if survey.get("not_found"):
        _add_heading(document, "7-1. 사회조사에서 확인되지 않은 항목", level=2)
        for item in survey["not_found"]:
            _add_bullet(document, item)

    if survey.get("data_caveats"):
        _add_heading(document, "7-2. 수치를 읽을 때 주의할 점", level=2)
        for item in survey["data_caveats"]:
            _add_bullet(document, item)

    _add_source(
        document,
        "※ 위 내용은 AI가 원본 보고서에서 추출한 것이며, 수치는 원문에서 확인 후 "
        "인용하시기 바랍니다. AI의 해석·시사점은 보고서에 포함하지 않았습니다.",
    )


def _add_bullet(document, text, size=BODY_SIZE):
    """글머리 기호 문단."""
    paragraph = document.add_paragraph(style="List Bullet")
    paragraph.paragraph_format.space_after = Pt(2)
    _add_inline_runs(paragraph, text, size=size)
    return paragraph


def _add_inline_runs(paragraph, text, size=BODY_SIZE, color=None):
    """**굵게** 표시를 런으로 나눠 넣는다 (마크다운 기호가 그대로 보이지 않게)."""
    for index, chunk in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if not chunk:
            continue
        run = paragraph.add_run(chunk)
        # split 결과에서 홀수 번째가 ** ** 안에 있던 부분이다
        _set_font(run, size=size, bold=index % 2 == 1, color=color)


def _add_markdown_block(document, markdown_text):
    """AI가 돌려준 마크다운을 Word 요소로 옮긴다.

    사회조사 분석 결과에 제목·목록·표·인용이 섞여 있어서 최소한의 변환이 필요하다.
    완전한 마크다운 파서가 아니라 실제로 나오는 형태(제목/목록/표/인용/본문)만 다룬다.
    """
    lines = (markdown_text or "").splitlines()
    table_buffer = []

    def flush_table():
        """모아둔 표 줄들을 Word 표로 만든다."""
        if not table_buffer:
            return
        parsed = []
        for row in table_buffer:
            cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
            # |---|---| 구분선은 건너뛴다
            if all(set(cell) <= set("-: ") for cell in cells):
                continue
            parsed.append([cell.replace("**", "") for cell in cells])
        table_buffer.clear()
        if len(parsed) >= 2:
            width = max(len(row) for row in parsed)
            headers = parsed[0] + [""] * (width - len(parsed[0]))
            rows = [row + [""] * (width - len(row)) for row in parsed[1:]]
            _add_table(document, headers, rows)
        elif parsed:
            _add_body(document, " / ".join(parsed[0]))

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("|"):
            table_buffer.append(stripped)
            continue
        flush_table()

        if not stripped:
            continue
        if stripped.startswith("####"):
            _add_heading(document, stripped.lstrip("#").strip(), level=2)
        elif stripped.startswith("###"):
            _add_heading(document, stripped.lstrip("#").strip(), level=2)
        elif stripped.startswith("##"):
            _add_heading(document, stripped.lstrip("#").strip(), level=2)
        elif stripped.startswith("#"):
            _add_heading(document, stripped.lstrip("#").strip(), level=2)
        elif stripped.startswith(">"):
            # 원문 인용 - 작고 흐리게 들여써서 본문과 구분한다
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.left_indent = Inches(0.3)
            paragraph.paragraph_format.space_after = Pt(2)
            _add_inline_runs(
                paragraph, stripped.lstrip("> ").strip(), size=Pt(8.5), color=MUTED_COLOR
            )
        elif stripped.startswith(("- ", "* ")):
            _add_bullet(document, stripped[2:].strip())
        elif stripped.startswith("---"):
            continue
        else:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(4)
            _add_inline_runs(paragraph, stripped)

    flush_table()


def _build_summary(document, data):
    """8. 종합 요약 - 각 섹션 핵심 수치를 한 장으로. 사실만, 평가·제언 없이."""
    document.add_page_break()
    _add_heading(document, "8. 종합 요약")

    overview = data["overview"]
    population = data["population"]
    households = data["households"]
    facilities = data["facilities"]
    child_spaces = data["child_spaces"]
    density = data.get("density")
    tourism = data.get("tourism") or {}

    _add_body(
        document,
        f"{overview['place_name']} 기준 {overview['minutes']}분 생활권"
        f"(반경 약 {overview['radius_km']:.1f}km, 행정동 {overview['dong_count']}개)의 "
        "핵심 수치입니다.",
    )

    rows = [
        ("인구", "총인구", _num(population["total"]), "명"),
        ("인구", "0~9세 어린이", _num(population["age_0_9"]), "명"),
        ("인구", "어린이 비율", f"{data['child_ratio']}", "%"),
        ("인구", "30~49세 (가족수요층)", _num(population["age_30_49"]), "명"),
        ("가구", "전체 세대", _num(households["total_households"]), "세대"),
        ("가구", "가족 가구 비중 (3~4인)", f"{households['family_ratio']}", "%"),
        ("교육", "학교 수", _num(sum(facilities["counts"].values())), "개"),
        ("교육", "재학 학생수", _num(facilities["students_total"]), "명"),
        ("교육", "초등 저학년 (1~3학년)", _num(facilities["students_grade_1_3"]), "명"),
    ]
    for name, group in child_spaces.items():
        rows.append(("시설", name, _num(group["count"]), "개"))
    if density and density["children_per_space"] is not None:
        rows.append(("시설", "공간 1개당 어린이", _num(density["children_per_space"]), "명"))

    visitors = tourism.get("visitors")
    if visitors:
        rows.append(("관광", "전체 방문자", _num(visitors["visitors_total"]), "명"))
        rows.append(("관광", "외지인 비중", f"{visitors['outsider_ratio']:.1f}", "%"))
        rows.append(("관광", "주말 유입 배수", f"{visitors['weekend_lift']:.2f}", "배"))
    datalab = tourism.get("datalab")
    if datalab:
        rows.append(("관광", "평균 체류시간", f"{datalab['avg_stay_hours']}", "시간"))
        rows.append(("관광", "평균 숙박일수", f"{datalab['avg_stay_nights']:.2f}", "일"))

    news = data.get("news")
    if news and not news.get("error"):
        rows.append(("트렌드", "최근 12개월 사업 뉴스", _num(news["total"]), "건"))
    popular = data.get("popular")
    if popular and not popular.get("error"):
        rows.append(("트렌드", "블로그·카페 언급 공간", _num(popular["total"]), "곳"))

    survey = data.get("survey")
    if survey and not survey.get("error"):
        rows.append(("주민 니즈", "사회조사 분석", "첨부 보고서 기준", "-"))

    _add_table(document, ["구분", "항목", "값", "단위"], rows)

    # 전국 대비 위치를 숫자로만 적는다 (좋다/나쁘다 평가는 쓰지 않는다)
    comparisons = []
    nationwide_child = data.get("nationwide_child_ratio")
    if nationwide_child:
        comparisons.append(
            f"어린이 비율 {data['child_ratio']}% (전국 평균 {nationwide_child:.1f}%)"
        )
    nationwide_lower = data.get("nationwide_lower_grade_ratio")
    if nationwide_lower and facilities["students"][ELEMENTARY]:
        comparisons.append(
            f"초등 저학년 비중 {data['lower_grade_ratio']}% (전국 평균 {nationwide_lower:.1f}%)"
        )
    benchmarks = data.get("benchmarks")
    if benchmarks and density and density["children_per_space"] is not None:
        comparisons.append(
            f"공간 1개당 어린이 {_num(density['children_per_space'])}명 "
            f"(전국 중위 {benchmarks['ratio_median']:.0f}명)"
        )
    if visitors and visitors.get("quartiles"):
        comparisons.append(
            f"외지인 비중 {visitors['outsider_ratio']:.1f}% "
            f"(전국 중위 {visitors['quartiles']['outsider_ratio_median']:.1f}%)"
        )
    if datalab and datalab.get("quartiles"):
        comparisons.append(
            f"평균 체류시간 {datalab['avg_stay_hours']}시간 "
            f"(전국 중위 {datalab['quartiles']['stay_minutes_median'] / 60:.1f}시간)"
        )

    if comparisons:
        _add_heading(document, "8-1. 전국 대비 위치", level=2)
        for item in comparisons:
            _add_bullet(document, item)

    _add_source(
        document,
        "※ 위 수치는 본문 각 섹션에서 그대로 가져온 값이며, 출처와 기준은 해당 섹션의 "
        "표기를 따릅니다. 이 요약에는 해석·평가·제언이 포함되어 있지 않습니다.",
    )


def build_report(data):
    """보고서 데이터를 받아 .docx 바이트를 만든다 (Streamlit 다운로드에 바로 쓸 수 있게)."""
    document = Document()
    _apply_base_style(document)

    _build_cover(document, data["overview"])
    _build_overview(document, data["overview"])
    _build_population(document, data)
    _build_education(document, data)
    _build_facilities(document, data)
    _build_tourism(document, data)
    _build_trends(document, data)
    _build_survey(document, data)
    _build_summary(document, data)
    _build_footer_note(document)

    buffer = _io.BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def build_file_name(place_name, created_on=None):
    """다운로드 파일명 - 공백은 밑줄로 바꾼다."""
    created_on = created_on or date.today().isoformat()
    safe_name = "_".join(str(place_name).split())
    return f"대상지보고서_{safe_name}_{created_on}.docx"


def main():
    from dotenv import load_dotenv

    from analysis.report_data import collect_report_data

    load_dotenv()
    data = collect_report_data(
        "고령군청",
        "경북 고령군 대가야읍 지산리 190",
        35.726065320875,
        128.262895757565,
        progress_callback=lambda i, n, label: print(f"  ({i}/{n}) {label}"),
    )
    content = build_report(data)
    out_path = build_file_name(data["overview"]["place_name"])
    with open(out_path, "wb") as f:
        f.write(content)
    print(f"저장 완료: {out_path} ({len(content):,} bytes)")


if __name__ == "__main__":
    main()
