"""표준 시즌 기록 CSV → 게임 카드 JSON.

    python -m pipeline.build_cards

산출물 (data/cards/):
  batters.json / pitchers.json  카드 목록 (대상 선수만)
  rosters.json                  {프랜차이즈: {연도: {batters, pitchers}}} — 연도별 모드용
  league_env.json               시즌별 리그 평균/표준편차 + 엔진 기준 환경
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from . import config
from .parse import format_ip
from .ratings import rate_batters, rate_pitchers
from .teams import franchise_for, load_franchises

BAT_COUNTS = ["G", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SAC", "SF",
              "BB", "IBB", "HBP", "SO", "GDP", "SB", "CS"]
PIT_COUNTS = ["G", "W", "L", "SV", "HLD", "CG", "SHO", "QS", "BSV", "TBF", "NP",
              "H", "2B", "3B", "HR", "BB", "IBB", "HBP", "SO", "R", "ER", "WP", "BK", "IP_outs"]
BAT_RATINGS = ["accuracy", "contact", "power", "eye", "babip", "speed", "steal", "ovr"]
PIT_RATINGS = ["stuff", "control", "movement", "hit_suppression", "stamina", "ovr"]


def py(v):
    """numpy/pandas 값 → JSON 값 (결측은 None)."""
    if v is None or v is pd.NA:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        if math.isnan(v):
            return None
        return int(v) if float(v).is_integer() else round(float(v), 4)
    return v


def ratio(a, b, digits=3):
    a, b = py(a), py(b)
    return None if a is None or not b else round(a / b, digits)


def load_csv(path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", dtype={"player_id": str})


def aggregate_seasons(df: pd.DataFrame, counts: list[str]) -> tuple[pd.DataFrame, dict]:
    """(선수, 연도)별 합산 + 팀 목록. 한 시즌에 여러 팀 행이 있는 소스도 처리."""
    present = [c for c in counts if c in df.columns]
    df = df.copy()
    for c in present:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    keys = ["player_id", "year"]
    agg = df.groupby(keys, as_index=False)[present].sum(min_count=1)
    meta_cols = [c for c in ("name", "pos", "bats", "throws") if c in df.columns]
    meta = df.groupby(keys, as_index=False)[meta_cols].first()
    teams: dict = defaultdict(list)
    for r in df.itertuples(index=False):
        teams[(r.player_id, int(r.year))].append({"team": r.team, "G": py(r.G)})
    return agg.merge(meta, on=keys), teams


def eligible_ids(df: pd.DataFrame, kind: str) -> set[str]:
    """YEAR_START~YEAR_END 누적 출장 MIN_CAREER_GAMES 이상 (투수는 이닝 보조 기준 선택)."""
    in_range = df[df["year"].between(config.YEAR_START, config.YEAR_END)]
    games = in_range.groupby("player_id")["G"].sum()
    ok = set(games[games >= config.MIN_CAREER_GAMES].index)
    if kind == "pitching" and config.PITCHER_ALT_MIN_IP:
        ip = in_range.groupby("player_id")["IP_outs"].sum() / 3
        ok |= set(ip[ip >= config.PITCHER_ALT_MIN_IP].index)
    return ok


def batter_card(r, teams, partial_years) -> dict:
    tb = r["H"] + r["2B"] + 2 * r["3B"] + 3 * r["HR"]
    obp_den = r["AB"] + r["BB"] + zero(r.get("HBP")) + zero(r.get("SF"))
    obp = ratio(r["H"] + r["BB"] + zero(r.get("HBP")), obp_den)
    slg = ratio(tb, r["AB"])
    return {
        "card_id": f"B{r['player_id']}-{int(r['year'])}",
        "player_id": r["player_id"],
        "name": r["name"],
        "year": int(r["year"]),
        "teams": teams,
        "bats": py(r.get("bats")),
        "throws": py(r.get("throws")),
        "pos": py(r.get("pos")),
        "small_sample": bool(py(r["PA"]) is None or r["PA"] < config.SMALL_SAMPLE_PA),
        "partial_season": int(r["year"]) in partial_years,
        "line": {
            **{k: py(r.get(k)) for k in ("G", "PA", "AB", "H", "2B", "3B", "HR", "RBI",
                                         "BB", "SO", "SB", "CS")},
            "AVG": ratio(r["H"], r["AB"]),
            "OBP": obp,
            "SLG": slg,
            "OPS": None if obp is None or slg is None else round(obp + slg, 3),
        },
        "ratings": {k: py(r[f"r_{k}"]) for k in BAT_RATINGS} | {"defense": None},
        "rates": {k: py(r[f"n_{k}"]) for k in ("so", "bb", "hr", "babip", "double_share",
                                               "triple_share", "sb_att", "sb_pct")},
    }


def pitcher_card(r, teams, partial_years) -> dict:
    outs = py(r["IP_outs"])
    return {
        "card_id": f"P{r['player_id']}-{int(r['year'])}",
        "player_id": r["player_id"],
        "name": r["name"],
        "year": int(r["year"]),
        "teams": teams,
        "throws": py(r.get("throws")),
        "role": r["role"],
        "small_sample": bool(py(r["TBF"]) is None or r["TBF"] < config.SMALL_SAMPLE_TBF),
        "partial_season": int(r["year"]) in partial_years,
        "line": {
            **{k: py(r.get(k)) for k in ("G", "W", "L", "SV", "HLD", "TBF", "SO", "BB", "HR", "NP")},
            "IP": format_ip(outs),
            "ERA": ratio(r["ER"] * 27, outs, 2) if outs else None,
            "WHIP": ratio((r["H"] + r["BB"]) * 3, outs, 2) if outs else None,
        },
        "ratings": {k: py(r[f"r_{k}"]) for k in PIT_RATINGS},
        "rates": {k: py(r[f"n_{k}"]) for k in ("so", "bb", "hr", "babip")}
        | {"np_per_g": py(r["np_per_g"]), "outs_per_g": py(r["outs_per_g"])},
    }


def zero(v) -> float:
    v = py(v)
    return 0.0 if v is None else v


def build(bat_raw: pd.DataFrame, pit_raw: pd.DataFrame, franchises: list[dict],
          partial_years: set[int] = frozenset()) -> dict:
    """카드·로스터·리그 환경을 만들어 dict로 반환 (파일 쓰기는 main에서)."""
    bat, bat_teams = aggregate_seasons(bat_raw, BAT_COUNTS)
    pit, pit_teams = aggregate_seasons(pit_raw, PIT_COUNTS)
    bat_rated, bat_env = rate_batters(bat)
    pit_rated, pit_env = rate_pitchers(pit)
    bat_ok, pit_ok = eligible_ids(bat, "batting"), eligible_ids(pit, "pitching")

    unmapped: Counter = Counter()

    def with_franchise(team_list):
        out = []
        for t in team_list:
            fid = franchise_for(t["team"], franchises)
            if fid is None:
                unmapped[t["team"]] += 1
            out.append({**t, "franchise": fid})
        return out

    batters = [
        batter_card(r, with_franchise(bat_teams[(r["player_id"], int(r["year"]))]), partial_years)
        for r in bat_rated[bat_rated["player_id"].isin(bat_ok)].to_dict("records")
    ]
    pitchers = [
        pitcher_card(r, with_franchise(pit_teams[(r["player_id"], int(r["year"]))]), partial_years)
        for r in pit_rated[pit_rated["player_id"].isin(pit_ok)].to_dict("records")
    ]

    rosters: dict = defaultdict(lambda: defaultdict(lambda: {"batters": [], "pitchers": []}))
    for kind, cards in (("batters", batters), ("pitchers", pitchers)):
        for card in sorted(cards, key=lambda c: -(c["ratings"]["ovr"] or 0)):
            for t in card["teams"]:
                if t["franchise"]:
                    rosters[t["franchise"]][str(card["year"])][kind].append(card["card_id"])

    return {
        "batters": batters,
        "pitchers": pitchers,
        "rosters": json.loads(json.dumps(rosters)),
        "league_env": {"batting": bat_env, "pitching": pit_env},
        "eligible": {"batters": len(bat_ok), "pitchers": len(pit_ok)},
        "unmapped_teams": dict(unmapped),
    }


def main() -> None:
    bat_raw = load_csv(config.BATTING_CSV)
    pit_raw = load_csv(config.PITCHING_CSV)
    meta = json.loads(config.SOURCE_META_JSON.read_text(encoding="utf-8")) \
        if config.SOURCE_META_JSON.exists() else {}
    result = build(bat_raw, pit_raw, load_franchises(), set(meta.get("partial_years", [])))

    config.CARDS_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("batters", "pitchers", "rosters", "league_env"):
        (config.CARDS_DIR / f"{name}.json").write_text(
            json.dumps(result[name], ensure_ascii=False, indent=1), encoding="utf-8")

    alt = f" 또는 {config.PITCHER_ALT_MIN_IP:g}이닝+" if config.PITCHER_ALT_MIN_IP else ""
    print(f"대상 선수(누적 {config.MIN_CAREER_GAMES}경기+{alt}): 타자 {result['eligible']['batters']}명, "
          f"투수 {result['eligible']['pitchers']}명")
    print(f"카드: 타자 {len(result['batters']):,}장, 투수 {len(result['pitchers']):,}장 → {config.CARDS_DIR}")
    if result["unmapped_teams"]:
        print(f"※ 프랜차이즈 매핑 안 된 팀 표기: {result['unmapped_teams']} → data/franchises.json에 추가")


if __name__ == "__main__":
    main()
