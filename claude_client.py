"""LLM API 모듈 — 3-tier: Groq (빠름) → Gemini (중급) → Claude (프리미엄)."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

try:
    from groq import Groq
except ImportError:
    Groq = None  # type: ignore

try:
    import google.generativeai as genai
except ImportError:
    genai = None

log = logging.getLogger(__name__)

# .env 로딩 (한글 경로 대응)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(str(_env_path), encoding="utf-8")
else:
    load_dotenv()

# fallback: .env 직접 읽기
def _read_env_key(key: str) -> str:
    val = os.getenv(key, "").strip()
    if val and val != f"여기에_{key}_입력":
        return val
    try:
        for line in _env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                v = line.split("=", 1)[1].strip()
                if v and "여기에" not in v:
                    return v
    except Exception:
        pass
    return ""

_anthropic_key = _read_env_key("ANTHROPIC_API_KEY")
_groq_key = _read_env_key("GROQ_API_KEY")
_gemini_key = _read_env_key("GEMINI_API_KEY")

# --- 클라이언트 초기화 ---
_claude_client = anthropic.Anthropic(api_key=_anthropic_key) if _anthropic_key else None

_groq_client = Groq(api_key=_groq_key) if (Groq and _groq_key) else None
GROQ_MODEL = "llama-3.3-70b-versatile"

_gemini_model = None
if genai and _gemini_key:
    genai.configure(api_key=_gemini_key)
    _gemini_model = genai.GenerativeModel(
        "gemini-2.5-flash",
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )

CLAUDE_MODEL = "claude-sonnet-4-20250514"

# Groq 입력 한도 (~12K TPM, 시스템프롬프트+출력 고려)
GROQ_MAX_INPUT_CHARS = 10000


# --- 용어 학습 DB ---

TERMS_DB_PATH = Path(__file__).parent / "terms_db.json"


def load_terms_db() -> dict:
    if TERMS_DB_PATH.exists():
        return json.loads(TERMS_DB_PATH.read_text(encoding="utf-8"))
    return {}


def save_terms_db(db: dict) -> None:
    TERMS_DB_PATH.write_text(
        json.dumps(db, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _terms_context() -> str:
    """학습된 용어를 시스템 프롬프트용 텍스트로 변환."""
    db = load_terms_db()
    if not db:
        return ""
    lines = ["\n=== 학습된 재무 용어 ==="]
    for term, info in db.items():
        desc = info.get("full_name", "")
        formula = info.get("formula", "")
        note = info.get("note", "")
        parts = [f"- {term}: {desc}"]
        if formula:
            parts.append(f"  계산: {formula}")
        if note:
            parts.append(f"  참고: {note}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


# --- 시스템 프롬프트 ---

SYSTEM_PROMPT = """너는 재무 데이터 추출 전문가야. 유저가 엑셀 데이터(TSV)와 자연어 요청을 보내면, 요청된 데이터를 추출하고 계산해서 JSON으로 반환해.

## 핵심 규칙

1. **반드시 JSON만 반환**해. 설명이나 마크다운 없이 순수 JSON만.
2. 엑셀에 직접 없는 지표라도 원본 데이터로 계산 가능하면 **직접 계산**해서 반환해:
   - Margin = Income / Revenue × 100
   - YoY Growth = (Current - Prior) / |Prior| × 100
   - QoQ Growth = (Current Q - Prior Q) / |Prior Q| × 100
   - % of Sales = 항목 / Sales(Revenue) × 100
   - EBITDA = Operating Income + D&A
   - Ratio = 분자 / 분모 × 100 (% 단위일 때)
3. 숫자 단위 기본값:
   - 금액: $m (백만 달러). 원본이 천 단위면 /1000 변환.
   - 비율/마진: % (소수점 첫째 자리, 예: 15.4). **% 값은 이미 퍼센트로 표현** (예: 6.6이면 6.6%이지, 0.066이 아님)
   - 유저가 별도 단위를 지정하면 그에 따라.
4. **음수 값 처리 (매우 중요!)**:
   - **음수 값(-0.04, -15.3 등)은 절대 생략하거나 건너뛰지 마.** 그대로 음수로 반환해.
   - 엑셀에서 (괄호)로 표시된 값 = 음수. 예: (0.04) → -0.04, (1,234) → -1234
   - 하이픈("-")이 값으로 쓰인 경우 = 0 또는 N/A. 숫자 앞의 "-"는 마이너스 부호.
   - 적자/손실도 정확히 음수로 반환: EPS -$0.04 → -0.04, Net Loss -$50M → -50
5. 기간 헤더 축약:
   - Annual: FY2030E → 30E, FY2024A → 24A
   - Quarterly: 1Q2026E → 1Q26E, 3Q2024A → 3Q24A
6. 모르는 용어가 있으면 `needs_clarification` 필드를 true로 설정하고, 최선의 추측을 함께 반환해.
7. **요청이 모호하거나 정확히 어떤 항목인지 불확실하면, 관련된 데이터를 최대한 많이 추출해.** 예: "segment revenue"라고 하면 해당 세그먼트의 Revenue, Revenue % Change, Operating Profit, OPM 등 관련 지표를 함께 반환.
8. **회사명/티커**: 엑셀에서 회사명이나 티커를 최대한 찾아서 company 필드에 넣어. 시트명, 헤더, 파일 구조 등에서 힌트를 찾아.

## JSON 응답 스키마

```json
{
  "company": "종목 티커 또는 회사명",
  "title": "차트 제목 (영문, 기간 포함 예: Adjusted EBITDA and Margin (1Q24-4Q25))",
  "periods": ["1Q21", "2Q21", ...],
  "series": [
    {
      "name": "시리즈 이름 (영문)",
      "values": [15.4, 23.1, ...],
      "unit": "이 시리즈의 단위 ($m 또는 % 또는 x)",
      "render_type": "bar 또는 line",
      "line_style": "solid 또는 dashed"
    }
  ],
  "unit": "메인 단위 (전체가 같은 단위일 때만)",
  "chart_type": "line 또는 bar 또는 stacked_bar 또는 combo",
  "table_data": {
    "headers": ["", "1Q21", "2Q21", ...],
    "rows": [
      ["항목명", "15.4%", "23.1%", ...]
    ]
  },
  "needs_clarification": false,
  "unclear_terms": []
}
```

## 차트 타입 판단 기준
- 같은 단위의 시계열 추이 → line
- 항목 간 비교 → bar
- 구성비(mix) → stacked_bar
- **단위가 다른 시리즈가 섞여 있으면 → combo** (예: EBITDA $m + Margin %)
  - combo일 때: 금액 시리즈는 render_type: "bar", 비율 시리즈는 render_type: "line"
  - 좌축 = 금액($m), 우축 = 비율(%)
- 유저가 명시하면 그에 따라

## 시리즈별 unit과 render_type (매우 중요!)
- **각 시리즈마다 반드시 unit 필드를 개별 지정해** (예: "$m", "%", "x")
- **각 시리즈마다 반드시 render_type 필드를 지정해** ("bar" 또는 "line")
- 금액 ($m): render_type = "bar"
- 비율/마진/% change: render_type = "line"
- 금액 시리즈와 % 시리즈가 섞여 있으면 반드시 chart_type = "combo"로 설정

## 시리즈 line_style
- 첫 번째 라인 시리즈: solid
- 두 번째 라인 시리즈: dashed
- 세 번째 이후: solid, dashed 번갈아
"""


# --- API 호출 ---

_last_provider = "none"  # 마지막 사용된 provider 추적
# "groq_only" | "gemini_only" | "auto" | "claude_only"
_api_mode = "auto"


def get_last_provider() -> str:
    return _last_provider


def set_api_mode(mode: str) -> None:
    """API 모드 설정: groq_only / gemini_only / auto / claude_only"""
    global _api_mode
    _api_mode = mode


def get_api_mode() -> str:
    return _api_mode


def _call_groq(system: str, prompt: str, max_tokens: int = 2000) -> str:
    """Groq API (Llama 3.3 70B) 호출. JSON mode 강제."""
    if not _groq_client:
        raise RuntimeError("Groq 클라이언트 없음. GROQ_API_KEY를 확인하세요.")

    groq_max = min(max_tokens, 2000)  # Groq 출력 토큰 제한

    response = _groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=groq_max,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or ""


def _call_gemini(system: str, prompt: str, max_tokens: int = 4000) -> str:
    """Gemini 2.0 Flash API 호출. JSON mode 강제 (response_mime_type)."""
    if not _gemini_model:
        raise RuntimeError("Gemini 클라이언트 없음. GEMINI_API_KEY를 확인하세요.")

    full_prompt = f"{system}\n\n---\n\n{prompt}"

    for attempt in range(3):
        try:
            response = _gemini_model.generate_content(full_prompt)
            return response.text or ""
        except Exception as e:
            err_str = str(e).lower()
            if ("429" in err_str or "resource" in err_str or "quota" in err_str) and attempt < 2:
                wait_sec = 10 * (attempt + 1)
                log.warning(f"Gemini rate limit, {wait_sec}초 대기 (시도 {attempt+1}/3)")
                time.sleep(wait_sec)
            else:
                raise
    return ""


def _call_claude(system: str, prompt: str, max_tokens: int = 4000) -> str:
    """Claude API 호출. 429 시 재시도."""
    if not _claude_client:
        raise RuntimeError("Claude 클라이언트 없음. ANTHROPIC_API_KEY를 확인하세요.")

    for attempt in range(3):
        try:
            response = _claude_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except anthropic.RateLimitError:
            if attempt < 2:
                time.sleep(30 * (attempt + 1))
            else:
                raise
    return ""


def _try_provider(call_fn, name: str, system: str, prompt: str, max_tokens: int) -> tuple[str | None, str]:
    """개별 provider 시도. (결과 or None, 에러메시지) 반환."""
    for attempt in range(2):
        try:
            result = call_fn(system, prompt, max_tokens)
            test = _parse_json_response(result)
            if "error" not in test:
                return result, ""
            else:
                err = f"JSON 파싱 실패 (시도 {attempt+1}/2)"
                log.warning(f"{name} {err}")
                if attempt < 1:
                    time.sleep(2)
        except Exception as e:
            err = f"{e}"
            log.warning(f"{name} 실패: {err} (시도 {attempt+1}/2)")
            if attempt < 1:
                time.sleep(2)
    return None, err


def _call_api(system: str, prompt: str, max_tokens: int = 4000) -> str:
    """API 모드에 따라 호출. provider를 _last_provider에 기록."""
    global _last_provider
    prompt_len = len(system) + len(prompt)

    # --- Claude Only ---
    if _api_mode == "claude_only":
        if not _claude_client:
            raise RuntimeError("Claude API 키가 없습니다. .env에 ANTHROPIC_API_KEY를 설정하세요.")
        _last_provider = "Claude"
        return _call_claude(system, prompt, max_tokens)

    # --- Groq Only ---
    if _api_mode == "groq_only":
        if not _groq_client:
            raise RuntimeError("Groq API 키가 없습니다. .env에 GROQ_API_KEY를 설정하세요.")
        result, err = _try_provider(_call_groq, "Groq", system, prompt, max_tokens)
        if result is not None:
            _last_provider = "Groq"
            return result
        raise RuntimeError(f"Groq 실패: {err}")

    # --- Gemini Only ---
    if _api_mode == "gemini_only":
        if not _gemini_model:
            raise RuntimeError("Gemini API 키가 없습니다. .env에 GEMINI_API_KEY를 설정하세요.")
        result, err = _try_provider(_call_gemini, "Gemini", system, prompt, max_tokens)
        if result is not None:
            _last_provider = "Gemini"
            return result
        raise RuntimeError(f"Gemini 실패: {err}")

    # --- Auto 모드: Groq → Gemini → Claude cascade ---
    errors: list[str] = []

    # 1단계: Groq (데이터가 작을 때만 시도)
    if _groq_client and prompt_len <= GROQ_MAX_INPUT_CHARS:
        result, err = _try_provider(_call_groq, "Groq", system, prompt, max_tokens)
        if result is not None:
            _last_provider = "Groq"
            return result
        errors.append(f"Groq: {err}")
        log.info("Groq 실패 → Gemini로 전환")
    elif _groq_client:
        log.info(f"데이터 크기 {prompt_len:,}자 > Groq 한도 {GROQ_MAX_INPUT_CHARS:,}자 → Groq 건너뜀")

    # 2단계: Gemini
    if _gemini_model:
        result, err = _try_provider(_call_gemini, "Gemini", system, prompt, max_tokens)
        if result is not None:
            _last_provider = "Gemini"
            return result
        errors.append(f"Gemini: {err}")
        log.info("Gemini 실패 → Claude로 전환")

    # 3단계: Claude
    if _claude_client:
        _last_provider = "Claude"
        return _call_claude(system, prompt, max_tokens)

    # 전부 실패
    err_summary = " / ".join(errors) if errors else "사용 가능한 API 없음"
    raise RuntimeError(f"모든 API 실패: {err_summary}\n→ .env에 API 키를 확인하세요.")


# --- 1차 호출: 구조 파악 ---

def analyze_structure(structure_summary: str) -> dict:
    """엑셀 구조를 분석하여 어떤 시트에 어떤 데이터가 있는지 파악."""

    prompt = f"""다음 엑셀의 구조를 분석해줘. 각 시트에 어떤 재무 데이터가 있고, 기간 범위가 어떻게 되는지 파악해.

{structure_summary}

다음 JSON 형식으로 반환해:
{{
  "company": "종목명/티커 (파악 가능하면)",
  "sheets": [
    {{
      "name": "시트명",
      "description": "이 시트의 내용 요약",
      "data_type": "IS/BS/CF/Segment/Valuation/기타",
      "period_type": "annual/quarterly/both",
      "period_range": "시작~끝 (예: 1Q21~4Q25)",
      "header_row": 헤더가_있는_행번호,
      "key_items": ["Revenue", "EBITDA", ...]
    }}
  ]
}}"""

    sys_prompt = SYSTEM_PROMPT + _terms_context()
    text = _call_api(sys_prompt, prompt, max_tokens=2000)
    return _parse_json_response(text)


# --- 2차 호출: 데이터 추출 ---

def extract_data(
    sheet_data: str,
    user_request: str,
    structure_info: dict,
    fy_context: str = "",
) -> dict:
    """유저 요청에 따라 데이터를 추출하고 JSON으로 반환."""

    company = structure_info.get("company", "Unknown")

    # FY/CY 컨텍스트가 있으면 프롬프트에 포함
    fy_section = f"\n회계연도 정보:\n{fy_context}\n" if fy_context else ""

    prompt = f"""회사: {company}
{fy_section}
엑셀 데이터:
{sheet_data}

유저 요청: {user_request}

위 데이터에서 유저가 요청한 내용을 추출/계산해서 JSON 스키마에 맞춰 반환해.
- 엑셀에 직접 없는 지표도 원본 데이터로 계산 가능하면 직접 계산해.
- 기간 범위가 요청에 명시되어 있으면 그 범위만, 없으면 가용한 전체 기간을 사용해.
- values 배열의 각 값은 소수점 첫째 자리까지 (% 단위일 때).
- "Adj" = "Adjusted" = "Non-GAAP"임을 인식해. 엑셀에서 Non-GAAP으로 표기된 항목이 Adj에 해당.
- 엑셀 헤더의 날짜/월 표기(Jan, Feb, Q1, Q2 등)를 보고 정확한 기간을 매칭해.
- **음수 값(-0.04 등)은 절대 생략하지 말고 그대로 반환해.** 괄호 표기 (0.04) = -0.04."""

    sys_prompt = SYSTEM_PROMPT + _terms_context()
    text = _call_api(sys_prompt, prompt, max_tokens=4000)
    return _parse_json_response(text)


# --- JSON 파싱 ---

def _parse_json_response(text: str) -> dict:
    """LLM 응답에서 JSON을 추출."""
    text = text.strip()

    # 코드블록 안에 있을 경우 추출
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    # 중괄호 범위 추출
    if not text.startswith("{"):
        brace_start = text.find("{")
        if brace_start != -1:
            brace_end = text.rfind("}")
            if brace_end != -1:
                text = text[brace_start : brace_end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        return {"error": f"JSON 파싱 실패: {e}", "raw_response": text}
