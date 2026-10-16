"""Claude API로 사회조사 보고서에서 주민 니즈를 뽑아내는 서비스.

공식 Anthropic SDK를 쓴다 (x-api-key / anthropic-version 헤더는 SDK가 알아서 붙인다).
키는 .env의 ANTHROPIC_API_KEY를 쓰고, SDK가 환경변수에서 알아서 읽는다.

환각 방지가 이 모듈의 핵심이다. 보고서를 요약하는 일은 "그럴듯한 수치를 지어내기" 쉬운
작업이라, 프롬프트에서 다음을 강하게 못박는다:
  - 제공된 내용에 있는 것만 쓸 것
  - 수치를 지어내지 말 것, 없으면 "해당 내용 없음"
  - 각 항목에 보고서의 실제 수치와 원문 문장을 근거로 달 것

PDF 추출 텍스트는 표·단 구조 때문에 숫자가 라벨과 떨어져 나온다
("비율은 로 경상북도, 10.1% (20.6%) 보다 낮게 10.5%p 나타났고").
그래서 원문 문장을 그대로 인용하게 하고, 숫자-라벨 대응이 모호하면 그렇게 밝히게 한다.

실행(테스트): python -m services.ai_service
"""

import os
import sys
from datetime import datetime

import anthropic
from dotenv import load_dotenv

MODEL = "claude-opus-5-5"

# 응답을 끝까지 받기 위한 상한. 고령군 실측에서 15,308토큰이 나와 16,000으로는 아슬아슬해
# 넉넉히 잡았다 (모델 출력 상한은 128K). 스트리밍이라 큰 값도 타임아웃 걱정이 없다.
MAX_TOKENS = 32_000

# 비용 로그용 단가 ($/1M 토큰). Opus 계열 기준이며, 요금이 바뀌면 여기만 고치면 된다.
# (Models API는 단가를 주지 않아서 코드에 둔다 - 청구서로 한 번 검증하는 것을 권한다)
PRICE_INPUT_PER_MTOK = 5.0
PRICE_OUTPUT_PER_MTOK = 25.0

COST_LOG_PATH = "data/reference/ai_usage.jsonl"

# 응답 스키마 - 사실과 해석을 모델 응답 단계에서 아예 다른 필드로 받는다.
# 마크다운 한 덩어리로 받아 뒤에서 쪼개면 경계가 흐려져서, 보고서에 AI 의견이 섞여
# 들어갈 수 있다. 스키마로 갈라두면 화면에서도 섞일 수가 없다.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "facts_markdown": {
            "type": "string",
            "description": (
                "보고서에 실제로 있는 수치·응답만. 해석·추론·평가·제언을 한 줄도 넣지 말 것. "
                "각 항목에 수치와 [p.N] 페이지, 원문 인용을 붙일 것."
            ),
        },
        "not_found": {
            "type": "array",
            "items": {"type": "string"},
            "description": "요청한 항목 중 보고서에 내용이 없는 것들",
        },
        "data_caveats": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "수치를 읽을 때 주의할 점 (조사 대상 범위, 표본 크기, "
                "숫자-라벨 대응이 불명확한 항목 등). 이것도 보고서에 근거한 사실만."
            ),
        },
        "interpretation_markdown": {
            "type": "string",
            "description": (
                "AI의 해석·시사점. 어떤 수치에서 나온 판단인지 반드시 밝힐 것. "
                "보고서가 직접 말하지 않은 내용임을 분명히 할 것."
            ),
        },
    },
    "required": ["facts_markdown", "not_found", "data_caveats", "interpretation_markdown"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """당신은 지방자치단체 사회조사 보고서를 읽고 주민 니즈를 정리하는 분석가입니다.

이 작업의 결과물은 **공공 보고서에 들어갑니다.** 그래서 "보고서에 실제로 있는 사실"과
"당신의 해석"을 절대 섞으면 안 됩니다. 둘을 서로 다른 필드로 나눠서 답하세요.

## facts_markdown - 객관적 사실만
- 보고서에 실제로 적힌 수치·응답만 쓰세요.
- 모든 내용에 수치와 [p.N] 페이지를 붙이고, 근거가 된 원문 문장을 그대로 인용하세요.
- **해석·추론·평가·제언을 한 줄도 넣지 마세요.** "~로 보인다", "~가 필요하다",
  "~를 시사한다", "상대적 약점이다" 같은 표현은 전부 금지입니다.
- 비교는 보고서가 직접 제시한 비교(예: 시군 vs 도 평균)만 그대로 옮기세요.
  당신이 새로 만든 비교나 순위 평가는 넣지 마세요.
- 보고서에 없는 숫자는 절대 쓰지 마세요. 지어내는 것이 가장 나쁜 실패입니다.

## not_found - 보고서에 없는 항목
- 요청받았지만 보고서에 내용이 없는 항목을 적으세요. 빈칸을 그럴듯한 내용으로 메우지 마세요.

## data_caveats - 수치를 읽을 때 주의할 점
- 조사 대상 범위, 표본 크기 안내, 숫자-라벨 대응이 불명확한 항목 등.
- 이것도 보고서에 근거한 사실만 쓰세요.

## interpretation_markdown - 당신의 해석 (참고용)
- 여기에만 해석·시사점을 쓰세요.
- 각 해석마다 어떤 수치에서 나온 판단인지 밝히세요.
- 보고서가 직접 말하지 않은 내용이면 그렇다고 분명히 적으세요.

PDF에서 뽑은 텍스트라서 표와 단 구조 때문에 숫자가 설명과 떨어져 나오는 경우가 있습니다
(예: "비율은 로 경상북도, 10.1% (20.6%) 보다 낮게 10.5%p 나타났고").
이럴 때는 원문을 그대로 인용하고, 어떤 숫자가 어떤 항목인지 확실하지 않으면
data_caveats에 "수치 대응 불명확"으로 적으세요. 추측해서 정리하지 마세요."""

USER_PROMPT_TEMPLATE = """다음은 {region_name} 사회조사 결과보고서에서 뽑은 내용입니다.

아래 항목을 정리하되, **사실과 해석을 반드시 다른 필드로 나눠서** 답해주세요.

facts_markdown 에 담을 항목 (보고서 수치만, 해석 금지):
1. 거주 의향 - 계속 거주/부정 응답 비율, 세부 특성별 차이
2. 가족·출산 - 출산 계획, 저출산 원인, 주민이 필요하다고 답한 출산·양육 지원 정책
3. 교육·어린이 - 자녀 유무·자녀 수, 교육비, 교육환경 만족도 수치
4. 주거·환경·교통 - 만족도 수치
5. 여가·문화 - 어린이·가족 관련 응답이 있으면

interpretation_markdown 에 담을 것:
- 위 수치들이 어린이·가족 공간사업에 시사하는 바 (당신의 해석)
- 각 해석이 어느 수치에서 나왔는지 명시
- 보고서가 직접 다루지 않은 추론이면 그렇다고 명시

---
보고서 내용:

{report_text}"""

load_dotenv()

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class AiServiceError(Exception):
    """Claude API 호출이 실패한 경우."""


def _client():
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise AiServiceError("ANTHROPIC_API_KEY가 설정되어 있지 않습니다. .env 파일을 확인해주세요.")
    return anthropic.Anthropic()


def calculate_cost(usage):
    """호출 1회 비용을 계산한다 (캐시 읽기/쓰기는 단가가 달라 따로 세지 않고 입력에 합산)."""
    input_tokens = usage.input_tokens + (getattr(usage, "cache_read_input_tokens", 0) or 0)
    output_tokens = usage.output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_cost": input_tokens / 1_000_000 * PRICE_INPUT_PER_MTOK,
        "output_cost": output_tokens / 1_000_000 * PRICE_OUTPUT_PER_MTOK,
        "total_cost": (
            input_tokens / 1_000_000 * PRICE_INPUT_PER_MTOK
            + output_tokens / 1_000_000 * PRICE_OUTPUT_PER_MTOK
        ),
    }


def log_usage(label, cost, path=COST_LOG_PATH):
    """호출당 토큰·비용을 한 줄씩 적는다 (누적 비용을 나중에 확인할 수 있게)."""
    import json

    os.makedirs(os.path.dirname(path), exist_ok=True)
    record = {"at": datetime.now().isoformat(timespec="seconds"), "label": label, "model": MODEL}
    record.update(cost)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def call_claude(system_prompt, user_prompt, label="call", max_tokens=MAX_TOKENS, schema=None):
    """Claude를 한 번 호출하고 (텍스트, 비용)을 돌려준다.

    입력이 길어서(사회조사 보고서는 수만 토큰) 스트리밍으로 받는다 - 논스트리밍은
    HTTP 타임아웃에 걸릴 수 있다. 모델이 adaptive thinking만 지원해서 thinking은
    따로 끄거나 켜지 않고 기본값에 맡긴다.

    schema를 주면 structured outputs로 받아 응답이 그 스키마를 지키도록 강제한다.
    """
    client = _client()
    extra = {}
    if schema is not None:
        extra["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            **extra,
        ) as stream:
            response = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise AiServiceError(f"API 키 인증 실패: {e}") from e
    except anthropic.RateLimitError as e:
        raise AiServiceError(f"호출 한도 초과 - 잠시 후 다시 시도해주세요: {e}") from e
    except anthropic.APIStatusError as e:
        raise AiServiceError(f"API 오류 ({e.status_code}): {e}") from e
    except anthropic.APIConnectionError as e:
        raise AiServiceError(f"네트워크 오류: {e}") from e

    # 정책상 거절된 경우 content를 읽기 전에 먼저 확인한다
    if response.stop_reason == "refusal":
        raise AiServiceError("모델이 요청을 거절했습니다 (안전 정책).")

    text = "".join(block.text for block in response.content if block.type == "text")
    cost = calculate_cost(response.usage)
    log_usage(label, cost)

    if response.stop_reason == "max_tokens":
        text += (
            "\n\n---\n⚠️ 출력 길이 제한에 걸려 내용이 중간에 끊겼습니다. "
            "핵심 섹션만 올리거나 분량을 줄여 다시 시도해주세요."
        )

    return text, cost


def analyze_survey_pdf(pdf_text, region_name, label=None):
    """사회조사 보고서 텍스트에서 주민 니즈를 뽑아낸다 (사실과 해석을 분리해서).

    pdf_text: analysis.survey_pdf.select_relevant_text()가 만든 텍스트
              (페이지 번호 [p.N] 주석이 들어 있어야 근거 표기가 가능하다)

    반환: (dict, 비용 dict)
      dict = {facts_markdown, not_found, data_caveats, interpretation_markdown}
    실패 시 AiServiceError를 올린다.
    """
    import json

    if not pdf_text or not pdf_text.strip():
        raise AiServiceError("보고서에서 추출된 텍스트가 없습니다 (이미지로만 된 PDF일 수 있습니다).")

    user_prompt = USER_PROMPT_TEMPLATE.format(
        region_name=region_name, report_text=pdf_text
    )
    text, cost = call_claude(
        SYSTEM_PROMPT,
        user_prompt,
        label=label or f"survey:{region_name}",
        schema=RESPONSE_SCHEMA,
    )

    try:
        parsed = json.loads(text)
    except ValueError as e:
        # 출력 길이 제한에 걸리면 JSON이 중간에 끊겨 파싱이 깨진다
        raise AiServiceError(
            f"응답을 해석하지 못했습니다 (출력이 중간에 끊겼을 수 있습니다): {e}"
        ) from e

    # 스키마가 보장하지만, 필드가 비어 있어도 화면이 깨지지 않게 기본값을 채운다
    return {
        "facts_markdown": parsed.get("facts_markdown", ""),
        "not_found": parsed.get("not_found", []),
        "data_caveats": parsed.get("data_caveats", []),
        "interpretation_markdown": parsed.get("interpretation_markdown", ""),
    }, cost


def main():
    print("1) API 연결 테스트")
    try:
        text, cost = call_claude(
            "You are a helpful assistant.", "Hello", label="connection-test", max_tokens=64
        )
    except AiServiceError as e:
        print(f"  실패: {e}")
        return
    print(f"  응답: {text.strip()[:80]}")
    print(f"  토큰 in={cost['input_tokens']} out={cost['output_tokens']} "
          f"비용 ${cost['total_cost']:.6f}")

    print("\n2) 고령군 사회조사 보고서 분석")
    from analysis.survey_pdf import extract_pages, select_relevant_text

    pages = extract_pages("data/raw/survey_goryeong_2025.pdf")
    selected = select_relevant_text(pages)
    print(f"  페이지 {selected['selected_pages']}/{selected['total_pages']} "
          f"(잘림={selected['truncated']}) 추정 {selected['estimated_tokens']:,}토큰")
    print(f"  주제: {', '.join(selected['topics'])}")

    try:
        result, cost = analyze_survey_pdf(selected["text"], "고령군", label="test:goryeong")
    except AiServiceError as e:
        print(f"  실패: {e}")
        return

    print(f"\n  토큰 in={cost['input_tokens']:,} out={cost['output_tokens']:,} "
          f"비용 ${cost['total_cost']:.4f}")

    print("\n" + "=" * 70)
    print("[영역 1] 주민 설문 결과 (객관적 사실)")
    print("=" * 70)
    print(result["facts_markdown"])

    if result["not_found"]:
        print("\n--- 보고서에 없는 항목 ---")
        for item in result["not_found"]:
            print(f"  - {item}")

    if result["data_caveats"]:
        print("\n--- 수치 해석 시 주의 ---")
        for item in result["data_caveats"]:
            print(f"  - {item}")

    print("\n" + "=" * 70)
    print("[영역 2] AI 참고 의견 (보고서의 객관적 사실이 아님)")
    print("=" * 70)
    print(result["interpretation_markdown"])


if __name__ == "__main__":
    main()
