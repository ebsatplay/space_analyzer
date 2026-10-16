"""사회조사 보고서 PDF에서 분석에 쓸 부분만 뽑아내는 모듈.

보고서가 100~300페이지라 통째로 보내면 비싸다 (파주 302페이지 = 506,888토큰, 회당 약 $2.5).
그렇다고 목차·섹션 번호로 자르는 방식은 못 쓴다 - 지자체마다 보고서 양식이 달라서
고령군에서 되던 헤더 패턴이 파주에서는 거의 안 걸린다 (실측: 고령 10개 섹션 인식,
파주 4개). 그래서 양식에 기대지 않고 페이지별로 주제 키워드 점수를 매겨 고른다.

예산 안에 다 들어가면 통째로 보내고, 넘치면 점수 높은 페이지부터 담는다.

주의: PDF 표·단 구조 때문에 추출 텍스트에서 숫자 위치가 밀린다.
("비율은 로 경상북도, 10.1% (20.6%) 보다 낮게 10.5%p 나타났고")
숫자 자체는 다 들어 있지만 라벨과 떨어져 나오므로, 프롬프트에서 원문 문장을 그대로
인용하게 해서 사람이 검증할 수 있게 한다.
"""

import functools
import glob
import os
import re
import sys

from pypdf import PdfReader

# 주제별 키워드와 가중치. 어린이·가족 공간사업에 필요한 것 위주.
TOPIC_KEYWORDS = {
    "거주의향": (3, ["거주 의향", "거주의향", "계속 거주", "정주", "이주", "떠날", "전출", "전입"]),
    "가족·출산": (3, ["출산", "저출산", "가족관계", "결혼", "보육", "양육", "자녀 수"]),
    "교육·어린이": (3, ["교육비", "교육환경", "미취학", "공교육", "사교육", "돌봄", "학교생활"]),
    "주거·환경·교통": (2, ["주거환경", "교통수단", "대중교통", "환경 체감", "생활환경"]),
    "요약": (2, ["요약", "주요 결과", "주요결과"]),
    "복지·여가": (1, ["복지", "여가활동", "문화예술", "생활 인프라", "체육시설"]),
}

# 조사표(설문 문항 원본)는 응답 결과가 없어 분석에 쓸모가 적다. 점수를 깎는다.
NOISE_MARKERS = ["조 사 표", "조사표", "응답자 확인사항", "조사원 기입"]
NOISE_PENALTY = 5

# data/raw 에 미리 받아둔 사회조사 보고서를 찾을 때 쓰는 패턴
LOCAL_SURVEY_GLOB = "data/raw/survey_*.pdf"
# 지역명을 찾기 위해 읽을 앞쪽 페이지 수 (표지·속표지에 "OO군 사회조사"가 적혀 있다)
REGION_SCAN_PAGES = 4
REGION_PATTERN = re.compile(r"([가-힣]{2,6}[시군구])\s*사회조사")

# 기본 토큰 예산 (입력 기준). 고령군 전체가 82K라 통째로 들어가고, 파주처럼 큰 보고서는 잘린다.
DEFAULT_TOKEN_BUDGET = 150_000
# 토큰 추정용 - 한국어는 글자당 약 0.85토큰으로 나왔다 (고령 96,558자 -> 81,953토큰)
CHARS_PER_TOKEN = 1.18

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _detect_region_name(path):
    """보고서 앞쪽 페이지에서 'OO군 사회조사' 같은 표기를 찾아 지역명을 알아낸다.

    파일명이 로마자라(survey_goryeong_2025.pdf) 이름만으로는 지역을 알 수 없다.
    로마자 대응표를 따로 관리하면 지역이 늘 때마다 손봐야 하므로, 보고서 내용에서
    직접 읽는다 (앞 4페이지만 읽어 0.1초 안에 끝난다).
    """
    try:
        reader = PdfReader(path)
    except Exception:
        return None
    text = ""
    for page in reader.pages[:REGION_SCAN_PAGES]:
        text += page.extract_text() or ""
    found = REGION_PATTERN.findall(text)
    return found[0] if found else None


@functools.lru_cache(maxsize=1)
def index_local_surveys(pattern=LOCAL_SURVEY_GLOB):
    """data/raw 의 사회조사 PDF를 훑어 {지역명: 경로} 색인을 만든다 (한 번만 읽는다)."""
    index = {}
    for path in sorted(glob.glob(pattern)):
        region = _detect_region_name(path)
        if region:
            index[region] = path
    return index


def _region_stem(name):
    """'경기도 파주시' -> '파주', '고령군' -> '고령' (끝의 시/군/구와 시도명을 떼어낸다)."""
    text = str(name or "").strip()
    if not text:
        return ""
    tail = text.split()[-1]
    return tail[:-1] if tail and tail[-1] in "시군구" else tail


def find_local_survey(region_name, pattern=LOCAL_SURVEY_GLOB):
    """해당 지역의 사회조사 PDF가 data/raw 에 있으면 경로를 돌려준다.

    region_name은 '파주시', '경기도 파주시', '파주' 어느 형태로 와도 맞춘다.

    반환: (경로, 보고서에 적힌 지역명) 또는 없으면 (None, None)
    """
    index = index_local_surveys(pattern)
    if not index:
        return None, None

    stem = _region_stem(region_name)
    if not stem:
        return None, None

    for detected, path in index.items():
        if _region_stem(detected) == stem:
            return path, detected
    return None, None


def extract_pages(file_or_path):
    """PDF에서 페이지별 텍스트를 뽑는다.

    file_or_path: 경로 문자열 또는 업로드된 파일 객체(st.file_uploader 결과)

    반환: [(페이지번호, 텍스트), ...] - 텍스트가 빈 페이지(표지·이미지)는 뺀다
    """
    reader = PdfReader(file_or_path)
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append((index, text))
    return pages


def score_page(text):
    """페이지가 분석 주제에 얼마나 맞는지 점수를 낸다 (키워드 등장 횟수 x 가중치)."""
    score = 0
    matched_topics = set()
    for topic, (weight, keywords) in TOPIC_KEYWORDS.items():
        hits = sum(text.count(keyword) for keyword in keywords)
        if hits:
            score += hits * weight
            matched_topics.add(topic)
    for marker in NOISE_MARKERS:
        if marker in text:
            score -= NOISE_PENALTY
    return score, matched_topics


def estimate_tokens(text):
    """글자 수로 토큰을 어림잡는다 (실제 과금 전 화면에 보여주기 위한 추정)."""
    return int(len(text) / CHARS_PER_TOKEN)


def select_relevant_text(pages, token_budget=DEFAULT_TOKEN_BUDGET):
    """예산에 맞춰 보낼 텍스트를 고른다.

    전체가 예산 안에 들어가면 그대로 쓰고, 넘치면 점수 높은 페이지부터 담는다.
    고른 페이지는 원래 순서대로 이어 붙인다 (보고서 흐름을 유지해야 맥락이 산다).

    반환: dict
      - text: 모델에 보낼 텍스트 (페이지 번호 주석 포함)
      - selected_pages / total_pages: 고른 페이지 수와 전체 페이지 수
      - truncated: 예산 때문에 잘렸는지
      - estimated_tokens: 추정 입력 토큰
      - topics: 고른 페이지에서 걸린 주제 목록
    """
    budget_chars = int(token_budget * CHARS_PER_TOKEN)
    total_chars = sum(len(text) for _, text in pages)

    if total_chars <= budget_chars:
        chosen = list(pages)
        truncated = False
    else:
        scored = []
        for page_no, text in pages:
            score, topics = score_page(text)
            scored.append((score, page_no, text, topics))
        scored.sort(key=lambda item: (-item[0], item[1]))

        chosen, used = [], 0
        for score, page_no, text, _topics in scored:
            if score <= 0:
                continue
            if used + len(text) > budget_chars:
                continue
            chosen.append((page_no, text))
            used += len(text)
        chosen.sort(key=lambda item: item[0])
        truncated = True

    topics = set()
    for _page_no, text in chosen:
        topics |= score_page(text)[1]

    # 모델이 근거를 짚을 수 있게 페이지 번호를 함께 넣는다
    body = ("\n\n").join(
        f"[p.{page_no}]\n{text}" for page_no, text in chosen
    )

    return {
        "text": body,
        "selected_pages": len(chosen),
        "total_pages": len(pages),
        "truncated": truncated,
        "estimated_tokens": estimate_tokens(body),
        "topics": sorted(topics),
    }
