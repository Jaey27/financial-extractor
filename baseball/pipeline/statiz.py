"""스탯티즈(statiz.sporki.com) 수집·파싱 도구 — 보강용 (WAR, 은퇴 선수 투타·도루 등).

1차 데이터는 KBO 공식 기록 기반 kbo_statics.py를 씀. 이 모듈은 네트워크 허용 후 검증 필요.

웹 검색으로 존재를 확인한 URL 형태 (2026-10):
- 선수 연도별:  /player/?m=year&p_no={p_no}
- 시즌기록실:   /stats/?m=main&m2=batting&m3=default&so=WAR&ob=DESC&year=2024&lt=10100&reg=R&pr=50 ...

아직 확인 못 한 것 (→ `python -m pipeline.statiz`로 페이지 구조부터 확인):
- 표의 실제 컬럼명/구조, reg·pr 파라미터 의미(전체 선수 표시 여부, 페이지당 행 수),
  연도별 페이지에 퓨처스(2군)·포스트시즌 행이 섞이는지, 로그인 필요 여부.
그래서 파싱은 컬럼명 별칭(ALIASES)으로 찾고, 못 찾으면 실제 컬럼 목록을 담아 에러를 냄.
"""

from __future__ import annotations

import hashlib
import re
import time
from io import StringIO
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import requests
from bs4 import BeautifulSoup

from . import config
from .parse import parse_ip_outs

P_NO_RE = re.compile(r"p_no=(\d+)")
HAND_RE = re.compile(r"([좌우양])투([좌우양])타")
HAND_CODE = {"좌": "L", "우": "R", "양": "S"}


# ── 요청 + 캐시 ──────────────────────────────────────────


class Fetcher:
    """요청 간격을 지키고, 받은 HTML은 디스크에 캐시해 같은 URL은 다시 요청하지 않음."""

    def __init__(
        self,
        cache_dir: Path = config.RAW_DIR / "statiz",
        interval: float = config.REQUEST_INTERVAL_SEC,
    ):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.interval = interval
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.USER_AGENT

    def cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")

    def get(self, url: str, refresh: bool = False) -> str:
        path = self.cache_path(url)
        if path.exists() and not refresh:
            return path.read_text(encoding="utf-8")

        last_err: Exception | None = None
        for attempt in range(3):
            wait = self.interval * (attempt + 1) - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT_SEC)
                self._last = time.monotonic()
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = requests.HTTPError(f"HTTP {resp.status_code}: {url}")
                    continue
                resp.raise_for_status()
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                self._last = time.monotonic()
                last_err = e
        else:
            raise RuntimeError(f"요청 실패: {url}") from last_err

        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = "utf-8"
        html = resp.text
        path.write_text(html, encoding="utf-8")
        with open(self.cache_dir / "_index.tsv", "a", encoding="utf-8") as f:
            f.write(f"{path.name}\t{url}\n")
        return html


# ── URL ──────────────────────────────────────────────────


def player_year_url(p_no: int) -> str:
    return f"{config.STATIZ_BASE}/player/?m=year&p_no={p_no}"


def season_stats_url(kind: str, year: int, **extra) -> str:
    """시즌기록실 URL. kind = 'batting' | 'pitching'.

    reg='A'(전체 선수), pr=1000(한 페이지에 다 보이게)은 추정값 — probe로 확인 필요.
    """
    params = {
        "m": "main",
        "m2": kind,
        "m3": "default",
        "so": "WAR",
        "ob": "DESC",
        "year": year,
        "sy": year,
        "ey": year,
        "lt": "10100",
        "reg": "A",
        "pr": 1000,
    }
    params.update(extra)
    return f"{config.STATIZ_BASE}/stats/?{urlencode(params)}"


# ── 파싱 ─────────────────────────────────────────────────

BATTING_ALIASES = {
    "year": ["연도", "년도", "시즌", "Year"],
    "team": ["팀", "소속", "Team"],
    "pos": ["포지션", "POS"],
    "G": ["G", "경기", "출장"],
    "PA": ["PA", "타석"],
    "AB": ["AB", "타수"],
    "R": ["R", "득점"],
    "H": ["H", "안타"],
    "2B": ["2B", "2루타"],
    "3B": ["3B", "3루타"],
    "HR": ["HR", "홈런"],
    "RBI": ["RBI", "타점"],
    "SB": ["SB", "도루"],
    "CS": ["CS", "도루실패", "도실"],
    "BB": ["BB", "볼넷"],
    "IBB": ["IBB", "IB", "고의4구", "고의사구"],
    "HBP": ["HBP", "HP", "사구", "몸에맞는공"],
    "SO": ["SO", "K", "삼진"],
    "GDP": ["GDP", "GIDP", "병살", "병살타"],
    "SH": ["SH", "희타", "희생번트"],
    "SF": ["SF", "희비", "희생플라이"],
    "WAR": ["WAR"],
}

PITCHING_ALIASES = {
    "year": ["연도", "년도", "시즌", "Year"],
    "team": ["팀", "소속", "Team"],
    "G": ["G", "경기", "출장"],
    "GS": ["GS", "선발"],
    "W": ["W", "승"],
    "L": ["L", "패"],
    "SV": ["SV", "S", "세이브"],
    "HLD": ["HLD", "HD", "홀드"],
    "IP": ["IP", "이닝"],
    "TBF": ["TBF", "BF", "타자", "상대타자"],
    "H": ["H", "피안타"],
    "HR": ["HR", "피홈런"],
    "BB": ["BB", "볼넷"],
    "IBB": ["IBB", "IB", "고의4구", "고의사구"],
    "HBP": ["HBP", "HP", "사구"],
    "SO": ["SO", "K", "삼진", "탈삼진"],
    "R": ["R", "실점"],
    "ER": ["ER", "자책", "자책점"],
    "WAR": ["WAR"],
}

REQUIRED = {
    "batting": ["year", "team", "G", "PA", "AB", "H", "HR", "BB", "SO"],
    "pitching": ["year", "team", "G", "IP", "H", "HR", "BB", "SO"],
}

def _norm(name) -> str:
    return re.sub(r"\s+", "", str(name)).upper()


def player_links(html: str) -> dict[int, str]:
    """페이지 안 선수 링크 → {p_no: 이름}. 표 구조와 무관하게 동작."""
    soup = BeautifulSoup(html, "lxml")
    out: dict[int, str] = {}
    for a in soup.find_all("a", href=True):
        m = P_NO_RE.search(a["href"])
        name = a.get_text(strip=True)
        if m and name:
            out.setdefault(int(m.group(1)), name)
    return out


def html_tables(html: str) -> list[pd.DataFrame]:
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:  # 표 없음
        return []
    for df in tables:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [str(c[-1]) for c in df.columns]
        else:
            df.columns = [str(c) for c in df.columns]
    return tables


def find_columns(columns, aliases: dict[str, list[str]]) -> dict[str, str]:
    """표 컬럼명 → 표준 컬럼명 매핑 (대소문자·공백 무시, 별칭 순서대로 우선)."""
    lookup = {}
    for c in columns:
        lookup.setdefault(_norm(c), c)
    mapping = {}
    for std, names in aliases.items():
        for n in names:
            if _norm(n) in lookup:
                mapping[std] = lookup[_norm(n)]
                break
    return mapping


def classify_table(df: pd.DataFrame) -> str | None:
    cols = {_norm(c) for c in df.columns}
    if cols & {"IP", "이닝"}:
        return "pitching"
    if cols & {"PA", "타석"}:
        return "batting"
    return None


def normalize_season_table(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    """연도별 표 → 표준 컬럼 DataFrame. 통산/합계 등 연도가 아닌 행과 범위 밖 연도는 제거."""
    aliases = BATTING_ALIASES if kind == "batting" else PITCHING_ALIASES
    df = df.loc[:, ~df.columns.duplicated()]  # 같은 이름 컬럼은 첫 번째만
    mapping = find_columns(df.columns, aliases)
    missing = [c for c in REQUIRED[kind] if c not in mapping]
    if missing:
        raise ValueError(
            f"{kind} 표에서 필수 컬럼 {missing}을 못 찾음. 실제 컬럼: {list(df.columns)}"
        )
    out = pd.DataFrame({std: df[src] for std, src in mapping.items()})
    out["year"] = pd.to_numeric(
        out["year"].astype(str).str.extract(r"((?:19|20)\d{2})")[0], errors="coerce"
    )
    out = out[out["year"].between(config.YEAR_START, config.YEAR_END)].copy()
    out["year"] = out["year"].astype(int)

    if kind == "pitching":
        out["IP_outs"] = out.pop("IP").map(parse_ip_outs)
    text_cols = {"year", "team", "pos"}
    for c in out.columns:
        if c not in text_cols and c != "IP_outs":
            out[c] = pd.to_numeric(
                out[c].astype(str).str.replace(",", "", regex=False), errors="coerce"
            )
    return out.reset_index(drop=True)


def parse_hands(html: str) -> tuple[str | None, str | None]:
    """'우투좌타' 같은 표기 → (throws, bats). 없으면 (None, None)."""
    m = HAND_RE.search(BeautifulSoup(html, "lxml").get_text(" "))
    if not m:
        return None, None
    return HAND_CODE[m.group(1)], HAND_CODE[m.group(2)]


def parse_player_year_page(html: str) -> dict[str, pd.DataFrame | None | str]:
    """선수 연도별 페이지 → {'batting': df|None, 'pitching': df|None, 'throws', 'bats'}.

    같은 종류 표가 여러 개면 표준 컬럼이 가장 많이 매칭되는 표를 씀.
    """
    best: dict[str, tuple[int, pd.DataFrame]] = {}
    for df in html_tables(html):
        kind = classify_table(df)
        if kind is None:
            continue
        aliases = BATTING_ALIASES if kind == "batting" else PITCHING_ALIASES
        score = len(find_columns(df.columns, aliases))
        if kind not in best or score > best[kind][0]:
            best[kind] = (score, df)
    throws, bats = parse_hands(html)
    result: dict = {"throws": throws, "bats": bats}
    for kind in ("batting", "pitching"):
        result[kind] = normalize_season_table(best[kind][1], kind) if kind in best else None
    return result


def describe_page(html: str, url: str = "", max_tables: int = 8) -> str:
    """probe용: 페이지에 어떤 표·컬럼·선수 링크가 있는지 사람이 읽을 요약."""
    lines = [f"=== {url}", f"HTML 길이: {len(html):,}자"]
    if "로그인" in html:
        lines.append("※ '로그인' 문구 있음 — 로그인 필요 페이지인지 확인할 것")
    links = player_links(html)
    lines.append(f"선수 링크(p_no): {len(links)}개  예: {list(links.items())[:5]}")
    tables = html_tables(html)
    lines.append(f"표: {len(tables)}개")
    for i, df in enumerate(tables[:max_tables]):
        lines.append(f"--- 표 {i}: {df.shape}, 분류={classify_table(df)}")
        lines.append(f"컬럼: {list(df.columns)}")
        lines.append(df.head(3).to_string(max_cols=30, max_colwidth=20))
    throws, bats = parse_hands(html)
    lines.append(f"투타: throws={throws}, bats={bats}")
    return "\n".join(lines)


if __name__ == "__main__":
    # 구조 확인용: python -m pipeline.statiz [URL ...]
    import sys

    fetcher = Fetcher()
    targets = sys.argv[1:] or [
        season_stats_url("batting", 2015),
        player_year_url(10590),  # 웹 검색으로 URL 확인된 선수 페이지
    ]
    for url in targets:
        print(describe_page(fetcher.get(url), url))
