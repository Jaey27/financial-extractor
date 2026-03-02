"""Financial Chart Telegram Bot — fly.io 배포용.

역할:
1. Telegram 폴링: /search, /list, /today, /help 명령어 처리
2. HTTP 서버 (aiohttp, port 8080): app.py에서 차트 메타데이터 수신
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path

from aiohttp import web
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --- 로깅 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# --- 환경변수 ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
INDEX_SECRET = os.getenv("INDEX_SECRET", "")  # HTTP 인덱스 엔드포인트 인증용

# fly.io 볼륨 경로 (로컬이면 현재 폴더)
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
INDEX_PATH = DATA_DIR / "chart_index.json"

# --- 차트 인덱스 관리 ---


def _load_index() -> list[dict]:
    """chart_index.json 로드."""
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            log.warning("인덱스 파일 손상, 빈 배열로 초기화")
    return []


def _save_index(index: list[dict]) -> None:
    """chart_index.json 저장."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _search_index(keywords: list[str]) -> list[dict]:
    """키워드로 인덱스 검색. AND 조건, case-insensitive."""
    index = _load_index()
    keywords_lower = [k.lower() for k in keywords if k.strip()]
    if not keywords_lower:
        return index[-10:]  # 키워드 없으면 최근 10개

    results = []
    for entry in index:
        search_text = (
            f"{entry.get('company', '')} {entry.get('title', '')} "
            f"{entry.get('filename', '')} {entry.get('date', '')}"
        ).lower()
        if all(kw in search_text for kw in keywords_lower):
            results.append(entry)

    # 날짜 역순 정렬 (최신 먼저)
    results.sort(key=lambda e: e.get("date", ""), reverse=True)
    return results


# --- Telegram 명령어 핸들러 ---


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    count = len(_load_index())
    await update.message.reply_text(
        f"Financial Chart Bot\n"
        f"Chat ID: {chat_id}\n"
        f"저장된 차트: {count}개\n\n"
        f"/search <키워드> — 차트 검색\n"
        f"/list — 최근 차트\n"
        f"/today — 오늘 차트\n"
        f"/help — 도움말"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Financial Chart Bot 도움말</b>\n\n"
        "/search &lt;키워드&gt; — 차트 검색 (예: /search VIAV EBITDA)\n"
        "/list — 최근 차트 10개\n"
        "/today — 오늘 생성된 차트\n"
        "/start — 봇 상태\n\n"
        "키워드를 바로 입력해도 검색됩니다.",
        parse_mode="HTML",
    )


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """키워드로 차트 검색."""
    keywords = context.args or []
    if not keywords:
        await update.message.reply_text("사용법: /search <키워드>\n예: /search VIAV EBITDA")
        return
    await _do_search(update, keywords)


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """최근 차트 10개."""
    index = _load_index()
    if not index:
        await update.message.reply_text("저장된 차트가 없습니다.")
        return

    recent = sorted(index, key=lambda e: e.get("date", ""), reverse=True)[:10]
    await _send_chart_list(update, recent, "최근 차트")


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """오늘 생성된 차트."""
    today_str = date.today().strftime("%Y-%m-%d")
    index = _load_index()
    today_charts = [e for e in index if e.get("date", "") == today_str]

    if not today_charts:
        await update.message.reply_text(f"오늘({today_str}) 생성된 차트가 없습니다.")
        return

    await _send_chart_list(update, today_charts, f"오늘({today_str}) 차트")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """일반 텍스트 → 검색으로 처리."""
    text = update.message.text.strip()
    if not text:
        return
    keywords = text.split()
    await _do_search(update, keywords)


# --- 공통 검색/전송 로직 ---


async def _do_search(update: Update, keywords: list[str]) -> None:
    """검색 실행 + 결과 전송."""
    results = _search_index(keywords)
    if not results:
        await update.message.reply_text(
            f"'{' '.join(keywords)}' 검색 결과가 없습니다."
        )
        return

    await _send_chart_list(update, results, f"'{' '.join(keywords)}' 검색 결과")


async def _send_chart_list(update: Update, charts: list[dict], title: str) -> None:
    """차트 목록을 텔레그램으로 전송."""
    if len(charts) <= 5:
        # 5개 이하: 이미지 직접 전송
        await update.message.reply_text(f"<b>{title}</b> ({len(charts)}개)", parse_mode="HTML")
        for entry in charts:
            file_id = entry.get("file_id", "")
            company = entry.get("company", "")
            chart_title = entry.get("title", "")
            chart_date = entry.get("date", "")
            caption = f"<b>{company}</b> — {chart_title}\n{chart_date}"

            try:
                await update.message.reply_photo(
                    photo=file_id,
                    caption=caption,
                    parse_mode="HTML",
                )
            except Exception as e:
                log.error(f"차트 전송 실패: {e}")
                await update.message.reply_text(f"전송 실패: {company} — {chart_title}")
    else:
        # 6개 이상: 목록 텍스트로 표시
        lines = [f"<b>{title}</b> ({len(charts)}개, 최대 20개 표시)\n"]
        for i, entry in enumerate(charts[:20], 1):
            company = entry.get("company", "")
            chart_title = entry.get("title", "")
            chart_date = entry.get("date", "")
            lines.append(f"{i}. <b>{company}</b> — {chart_title} ({chart_date})")

        lines.append("\n더 좁은 키워드로 검색하면 이미지를 직접 받을 수 있습니다.")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# --- HTTP 서버 (aiohttp) ---


async def handle_index_post(request: web.Request) -> web.Response:
    """app.py에서 차트 메타데이터 수신."""
    # 간단한 인증
    if INDEX_SECRET:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {INDEX_SECRET}":
            return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    required = ["company", "title", "date", "file_id"]
    if not all(data.get(k) for k in required):
        return web.json_response(
            {"error": f"Missing fields: {required}"}, status=400
        )

    # 중복 체크 (같은 file_id 이미 있으면 스킵)
    index = _load_index()
    if any(e.get("file_id") == data["file_id"] for e in index):
        return web.json_response({"status": "already_exists"})

    entry = {
        "company": data["company"],
        "title": data["title"],
        "date": data["date"],
        "file_id": data["file_id"],
        "filename": data.get("filename", ""),
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }
    index.append(entry)
    _save_index(index)

    log.info(f"인덱스 추가: {entry['company']} — {entry['title']}")
    return web.json_response({"status": "ok", "total": len(index)})


async def handle_health(request: web.Request) -> web.Response:
    """헬스체크 엔드포인트."""
    count = len(_load_index())
    return web.json_response({"status": "ok", "charts": count})


# --- 메인: 봇 + HTTP 서버 동시 실행 ---


async def run_http_server() -> None:
    """aiohttp 서버 시작 (port 8080)."""
    app = web.Application()
    app.router.add_post("/index", handle_index_post)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/", handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    log.info("HTTP 서버 시작: 0.0.0.0:8080")


def main() -> None:
    if not BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN 환경변수가 설정되지 않았습니다.")
        return

    # Telegram 봇 빌드
    tg_app = Application.builder().token(BOT_TOKEN).build()

    # 핸들러 등록
    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("help", cmd_help))
    tg_app.add_handler(CommandHandler("search", cmd_search))
    tg_app.add_handler(CommandHandler("list", cmd_list))
    tg_app.add_handler(CommandHandler("today", cmd_today))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # HTTP 서버를 봇 시작 전에 비동기로 실행
    async def post_init(app: Application) -> None:
        await run_http_server()
        if CHAT_ID:
            count = len(_load_index())
            try:
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"Financial Chart Bot 시작\n저장된 차트: {count}개",
                )
            except Exception as e:
                log.warning(f"시작 알림 실패: {e}")

    tg_app.post_init = post_init

    log.info("Financial Chart Bot 시작...")
    tg_app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
