"""Financial Data Extractor — Streamlit 메인 앱."""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from io import BytesIO
from pathlib import Path

import httpx
import streamlit as st
from dotenv import load_dotenv

# .env 로딩 (로컬)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(str(_env_path), encoding="utf-8")

# Streamlit Cloud secrets → 환경변수 (배포 환경)
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

log = logging.getLogger(__name__)

# 텔레그램 설정
_TG_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TG_CHAT_ID = os.getenv("CHAT_ID", "")
_FLY_BOT_URL = os.getenv("FLY_BOT_URL", "")
_INDEX_SECRET = os.getenv("INDEX_SECRET", "")

from excel_parser import parse_excel, get_structure_summary, get_full_sheet_data
from claude_client import (
    analyze_structure,
    extract_data,
    load_terms_db,
    save_terms_db,
    get_last_provider,
    set_api_mode,
)
from chart_generator import generate_chart

# --- 경로 ---
OUTPUT_DIR = Path(__file__).parent / "output"

# Gemini 2.0 Flash: 1M 토큰 컨텍스트 → 넉넉하게 설정
MAX_CHARS_FOR_API = 120000  # ~30K 토큰 데이터 (Gemini 기준 충분)


def _select_relevant_sheets(
    user_request: str,
    structure_info: dict,
    sheets: dict,
) -> list[str]:
    """유저 요청과 관련된 시트만 선별. 토큰 한도 초과 시 축소."""
    request_lower = user_request.lower()
    all_names = list(sheets.keys())

    if not structure_info or "sheets" not in structure_info:
        return all_names[:2]  # 구조 정보 없으면 처음 2개만

    # 각 시트별 관련도 점수 계산
    scored: list[tuple[str, int]] = []
    for s_info in structure_info["sheets"]:
        name = s_info.get("name", "")
        if name not in sheets:
            continue
        score = 0
        # 시트 설명/항목과 요청 키워드 매칭
        desc = (s_info.get("description", "") + " " + s_info.get("data_type", "")).lower()
        items = " ".join(s_info.get("key_items", [])).lower()
        search_text = f"{name} {desc} {items}".lower()

        # 요청 단어가 시트 정보에 포함되면 점수 부여
        for word in request_lower.split():
            if len(word) >= 2 and word in search_text:
                score += 10
        # IS(Income Statement)는 revenue/margin 등에 기본 매칭
        if s_info.get("data_type", "").upper() == "IS":
            score += 3  # 기본 가산 (가장 많이 쓰이는 시트)
        if "segment" in request_lower and "segment" in search_text:
            score += 20
        scored.append((name, score))

    # 점수 높은 순 정렬
    scored.sort(key=lambda x: x[1], reverse=True)

    # 관련 시트 선택 (점수 > 0 우선, 없으면 상위 2개)
    relevant = [name for name, sc in scored if sc > 0]
    if not relevant:
        relevant = [name for name, _ in scored[:2]]

    # 토큰 한도 체크: 초과하면 시트 수 줄이기
    selected: list[str] = []
    total_chars = 0
    for name in relevant:
        sheet_chars = len(sheets[name]["full"])
        if total_chars + sheet_chars > MAX_CHARS_FOR_API and selected:
            break  # 이미 1개 이상 있으면 중단
        selected.append(name)
        total_chars += sheet_chars

    if not selected:
        selected = all_names[:1]

    # 단일 시트인데도 한도 초과 시 → 시트 데이터 자체를 잘라서 저장
    for name in selected:
        full_data = sheets[name]["full"]
        if len(full_data) > MAX_CHARS_FOR_API:
            lines = full_data.split("\n")
            trimmed: list[str] = []
            char_count = 0
            for line in lines:
                if char_count + len(line) > MAX_CHARS_FOR_API:
                    break
                trimmed.append(line)
                char_count += len(line) + 1
            sheets[name]["full_trimmed"] = "\n".join(trimmed)

    return selected

# --- 텔레그램 전송 ---


def _send_chart_to_telegram(
    png_bytes: bytes, company: str, title: str, filename: str
) -> None:
    """차트를 텔레그램으로 전송 + fly.io 봇에 인덱스 등록. 실패해도 무시."""
    if not _TG_BOT_TOKEN or not _TG_CHAT_ID:
        return  # 토큰/챗ID 없으면 스킵

    try:
        # 1) Telegram sendPhoto API
        caption = f"<b>{company}</b> — {title}"
        resp = httpx.post(
            f"https://api.telegram.org/bot{_TG_BOT_TOKEN}/sendPhoto",
            data={"chat_id": _TG_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
            files={"photo": (filename, BytesIO(png_bytes), "image/png")},
            timeout=30,
        )
        resp_data = resp.json()

        if not resp_data.get("ok"):
            log.warning(f"텔레그램 전송 실패: {resp_data}")
            return

        # 2) file_id 추출
        photo_sizes = resp_data.get("result", {}).get("photo", [])
        file_id = photo_sizes[-1]["file_id"] if photo_sizes else ""

        # 3) fly.io 봇에 인덱스 등록
        if _FLY_BOT_URL and file_id:
            today_str = date.today().strftime("%Y-%m-%d")
            headers = {}
            if _INDEX_SECRET:
                headers["Authorization"] = f"Bearer {_INDEX_SECRET}"
            httpx.post(
                f"{_FLY_BOT_URL}/index",
                json={
                    "company": company,
                    "title": title,
                    "date": today_str,
                    "file_id": file_id,
                    "filename": filename,
                },
                headers=headers,
                timeout=10,
            )
    except Exception as e:
        log.warning(f"텔레그램/인덱스 전송 실패 (무시): {e}")


# --- 페이지 설정 ---
st.set_page_config(
    page_title="Financial Data Extractor",
    page_icon="📊",
    layout="wide",
)

st.title("Financial Data Extractor")

# --- 세션 초기화 ---
if "sheets" not in st.session_state:
    st.session_state.sheets = None
if "structure_info" not in st.session_state:
    st.session_state.structure_info = None
if "history" not in st.session_state:
    st.session_state.history = []
if "file_name" not in st.session_state:
    st.session_state.file_name = None


# --- 사이드바: 파일 업로드 ---
with st.sidebar:
    # API 모드 선택
    api_mode = st.radio(
        "API 모드",
        options=["auto", "groq_only", "gemini_only", "claude_only"],
        format_func=lambda m: {
            "auto": "⚡ Auto (Groq → Gemini → Claude)",
            "groq_only": "🟢 Groq Only (무료, 빠름)",
            "gemini_only": "🟡 Gemini Only (무료, 중급)",
            "claude_only": "🔴 Claude Only (유료, 정확)",
        }[m],
        index=0,
        help="Auto: 간단한 건 Groq, 실패 시 Gemini, 그래도 실패 시 Claude",
        key="api_mode",
    )
    set_api_mode(api_mode)

    # --- 회계연도 설정 ---
    st.divider()
    st.header("회계연도 설정")

    fy_mode = st.radio(
        "기간 기준",
        ["CY (Calendar Year)", "FY (Fiscal Year)"],
        index=0,
        help="엑셀 데이터의 기간 표기 기준",
        key="fy_mode",
    )

    fy_context = ""
    if fy_mode.startswith("FY"):
        fy_start_month = st.selectbox(
            "FY 시작월",
            options=list(range(1, 13)),
            format_func=lambda m: f"{m}월",
            index=6,  # 기본 7월 (많은 기업이 7월 시작)
            help="회계연도가 시작되는 달 (예: 7월이면 FY Q1 = Jul~Sep)",
            key="fy_start_month",
        )

        # FY↔CY 분기 매핑 자동 생성
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        mapping_lines = []
        for q in range(4):
            start_m = (fy_start_month - 1 + q * 3) % 12
            end_m = (start_m + 2) % 12
            # CY 분기 계산
            cy_q = (start_m // 3) + 1
            fy_label = f"Q{q+1}FY"
            cy_label = f"Q{cy_q}CY"
            months = f"{month_names[start_m]}~{month_names[end_m]}"
            mapping_lines.append(f"  {fy_label} = {months} = {cy_label}")

        fy_end_month = (fy_start_month - 2) % 12 + 1
        fy_context = (
            f"이 파일은 Fiscal Year 기준. FY 시작월: {fy_start_month}월, FY 종료월: {fy_end_month}월\n"
            f"FY↔CY 분기 매핑:\n" + "\n".join(mapping_lines) + "\n"
            f"주의: 유저가 '1Q26FY'라고 하면 CY와 다를 수 있음. 엑셀 헤더의 날짜/월 표기를 보고 정확한 기간을 매칭해."
        )

        # 매핑 표시
        st.caption("FY↔CY 매핑:")
        for line in mapping_lines:
            st.caption(line)
    else:
        fy_context = "이 파일은 Calendar Year 기준. 1Q = Jan~Mar, 2Q = Apr~Jun, 3Q = Jul~Sep, 4Q = Oct~Dec."

    st.session_state.fy_context = fy_context

    st.divider()
    st.header("엑셀 파일 업로드")
    uploaded_file = st.file_uploader(
        "IB 리서치 모델 (.xlsx)",
        type=["xlsx"],
        key="file_uploader",
    )

    if uploaded_file is not None:
        # 새 파일이면 세션 초기화
        if st.session_state.file_name != uploaded_file.name:
            st.session_state.file_name = uploaded_file.name
            st.session_state.history = []
            st.session_state.sheets = None
            st.session_state.structure_info = None

            with st.spinner("엑셀 구조 분석 중... (rate limit 시 최대 30초 대기)"):
                file_bytes = uploaded_file.read()
                sheets = parse_excel(file_bytes)
                st.session_state.sheets = sheets

                # Claude 1차 호출: 구조 파악
                try:
                    summary = get_structure_summary(sheets, uploaded_file.name)
                    structure_info = analyze_structure(summary)
                    st.session_state.structure_info = structure_info
                except Exception as e:
                    st.session_state.structure_info = {"error": str(e)}
                    st.error(f"구조 분석 실패: {e}")

        # 구조 정보 표시
        if st.session_state.structure_info:
            info = st.session_state.structure_info
            if "error" not in info:
                company = info.get("company", "")
                unknown_names = {"", "unknown", "알수없음", "none", "n/a"}
                if company.lower().strip() in unknown_names:
                    st.warning("기업명을 인식하지 못했습니다.")
                    user_company = st.text_input(
                        "기업 티커 입력",
                        placeholder="예: MOG, AAPL, 삼성전자",
                        key="company_override",
                    )
                    if user_company.strip():
                        st.session_state.structure_info["company"] = user_company.strip()
                        company = user_company.strip()
                        st.success(f"분석 완료: **{company}**")
                else:
                    st.success(f"분석 완료: **{company}**")
                for sheet in info.get("sheets", []):
                    with st.expander(f"{sheet['name']} ({sheet.get('data_type', '')})"):
                        st.text(f"기간: {sheet.get('period_range', 'N/A')}")
                        st.text(f"유형: {sheet.get('period_type', 'N/A')}")
                        items = sheet.get("key_items", [])
                        if items:
                            st.text(f"주요 항목: {', '.join(items[:10])}")
            else:
                st.error(f"구조 분석 실패: {info['error']}")

    # 용어 DB 관리
    st.divider()
    st.header("학습된 용어")
    terms = load_terms_db()
    if terms:
        for term, info in terms.items():
            st.caption(f"**{term}**: {info.get('full_name', '')}")
    else:
        st.caption("아직 학습된 용어가 없습니다.")


# --- 메인: 요청 입력 ---

if st.session_state.sheets is None:
    st.info("왼쪽에서 엑셀 파일을 업로드하세요.")
else:
    # 입력 영역
    user_request = st.text_input(
        "요청",
        placeholder="예: OPEX / Capex % of sales 1Q21~4Q25",
        label_visibility="collapsed",
    )

    # 시트 선택 영역
    sheets = st.session_state.sheets
    info = st.session_state.structure_info
    all_sheet_names = list(sheets.keys())

    # 시트별 요약 정보 (선택 도움용)
    sheet_labels = {}
    if info and "sheets" in info:
        for s_info in info.get("sheets", []):
            name = s_info.get("name", "")
            dtype = s_info.get("data_type", "")
            ptype = s_info.get("period_type", "")
            prange = s_info.get("period_range", "")
            label_parts = [dtype, ptype, prange]
            sheet_labels[name] = f"{name} ({', '.join(p for p in label_parts if p)})"

    # 자동 추천 시트 계산 (요청이 있을 때만)
    if user_request.strip():
        auto_sheets = _select_relevant_sheets(user_request, info, sheets)
    else:
        auto_sheets = all_sheet_names[:1]

    # 자동 추천이 바뀌면 세션에 반영 (요청 변경 시)
    if "prev_request" not in st.session_state:
        st.session_state.prev_request = ""
    if user_request != st.session_state.prev_request:
        st.session_state.prev_request = user_request
        st.session_state.sheet_selector = auto_sheets  # 위젯 key와 동일하게

    col_sheet, col_btn = st.columns([5, 1])
    with col_sheet:
        selected_sheets = st.multiselect(
            "분석할 시트",
            options=all_sheet_names,
            format_func=lambda n: sheet_labels.get(n, n),
            key="sheet_selector",
        )
    with col_btn:
        st.write("")  # 세로 정렬용 빈 줄
        run_btn = st.button("추출", type="primary", use_container_width=True)

    # 선택 시트 크기 표시
    if selected_sheets:
        total_chars = sum(len(sheets[n]["full"]) for n in selected_sheets if n in sheets)
        st.caption(f"📋 {len(selected_sheets)}개 시트 선택 ({total_chars:,}자)")

    # 추출 실행
    if run_btn and user_request.strip() and selected_sheets:
        with st.spinner("데이터 추출 중... (rate limit 시 최대 30초 대기)"):
            # 선택 시트에 토큰 제한 적용
            for name in selected_sheets:
                full_data = sheets[name]["full"]
                if len(full_data) > MAX_CHARS_FOR_API:
                    lines = full_data.split("\n")
                    trimmed: list[str] = []
                    char_count = 0
                    for line in lines:
                        if char_count + len(line) > MAX_CHARS_FOR_API:
                            break
                        trimmed.append(line)
                        char_count += len(line) + 1
                    sheets[name]["full_trimmed"] = "\n".join(trimmed)

            sheet_data = get_full_sheet_data(sheets, selected_sheets)

            # Claude 2차 호출: 데이터 추출
            try:
                fy_ctx = st.session_state.get("fy_context", "")
                result = extract_data(sheet_data, user_request, info, fy_context=fy_ctx)
            except Exception as e:
                result = {"error": str(e)}

        if "error" in result:
            st.error(f"추출 실패: {result['error']}")
            if "raw_response" in result:
                with st.expander("원본 응답"):
                    st.code(result["raw_response"])
        else:
            # 용어 확인 필요 여부 체크
            if result.get("needs_clarification"):
                unclear = result.get("unclear_terms", [])
                st.warning(f"확인이 필요한 용어: {', '.join(unclear) if unclear else '응답을 확인하세요'}")

            # 히스토리에 추가 (provider 정보 포함)
            st.session_state.history.append({
                "request": user_request,
                "data": result,
                "provider": get_last_provider(),
            })

    # --- 히스토리 렌더링 (최신이 위) ---
    st.divider()

    for idx, item in enumerate(reversed(st.session_state.history)):
        real_idx = len(st.session_state.history) - 1 - idx
        data = item["data"]
        request = item["request"]

        provider = item.get("provider", "")
        provider_badge = f" `{provider}`" if provider else ""
        st.subheader(f"{request}{provider_badge}")

        # 차트 생성
        try:
            png_bytes, filename = generate_chart(data, OUTPUT_DIR)

            # 차트 표시
            st.image(png_bytes, use_container_width=True)

            # 다운로드 + 텔레그램 전송 버튼
            tg_key = f"tg_sent_{real_idx}"
            col_dl, col_tg = st.columns([3, 1])
            with col_dl:
                st.download_button(
                    label=f"PNG 저장: {filename}",
                    data=png_bytes,
                    file_name=filename,
                    mime="image/png",
                    key=f"download_{real_idx}",
                )
            with col_tg:
                if tg_key in st.session_state:
                    st.button("✅ 전송됨", key=f"tg_done_{real_idx}", disabled=True)
                else:
                    if st.button("📤 텔레그램", key=f"tg_btn_{real_idx}"):
                        company = data.get("company", "Unknown")
                        chart_title = data.get("title", "chart")
                        _send_chart_to_telegram(png_bytes, company, chart_title, filename)
                        st.session_state[tg_key] = True
                        st.rerun()
        except Exception as e:
            st.error(f"차트 생성 실패: {e}")

        # 텍스트 표
        table = data.get("table_data")
        if table:
            headers = table.get("headers", [])
            rows = table.get("rows", [])
            if headers and rows:
                # 마크다운 테이블 생성
                md_lines = ["| " + " | ".join(str(h) for h in headers) + " |"]
                md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                for row in rows:
                    md_lines.append("| " + " | ".join(str(v) for v in row) + " |")
                st.markdown("\n".join(md_lines))

        # JSON 원본 (접기)
        with st.expander("원본 JSON"):
            st.json(data)

        st.divider()
