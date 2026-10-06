"""KBO_statics(공개 GitHub repo) JSON → 표준 시즌 기록 CSV.

출처: https://github.com/PsyproLEE/kbo_statics
  KBO 공식 홈페이지(koreabaseball.com) 기록실을 매일 수집해 JSON으로 커밋하는 repo.
  - season/{연도}.json : 1982~직전 시즌, 그 시즌 1군 전 선수 타자/투수 기록 (도루·선발등판 없음)
  - hitters.json / pitchers.json : 진행 중 시즌 (meta.json의 updatedAt 시점)
  - careers.json / players.json : 현역(최근 시즌 로스터) 선수만 — 연도별 도루(SB/CS), 투타, 포지션

    python -m pipeline.kbo_statics            # 소스가 없으면 git clone 후 CSV 생성
    python -m pipeline.kbo_statics --update   # 소스 최신화 후 CSV 생성
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

import pandas as pd

from . import config
from .parse import parse_ip_outs, to_num

DATA_SUBDIR = Path("web/public/data")

BAT_STATS = ["G", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SAC", "SF",
             "BB", "IBB", "HBP", "SO", "GDP"]
PIT_STATS = ["G", "W", "L", "SV", "HLD", "CG", "SHO", "QS", "BSV", "TBF", "NP",
             "H", "2B", "3B", "HR", "BB", "IBB", "HBP", "SO", "R", "ER", "WP", "BK"]

HAND = {"좌": "L", "우": "R", "양": "S"}
POS_RE = re.compile(r"^(?P<pos>[^(]+)\((?P<t>[좌우양])투(?P<b>[좌우양])타\)")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def ensure_source(update: bool = False) -> Path:
    """KBO_statics를 data/raw/kbo_statics에 받아 두고 데이터 폴더 경로를 돌려줌."""
    src = config.KBO_STATICS_DIR
    if not (src / ".git").exists():
        src.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--depth", "1", config.KBO_STATICS_REPO, str(src))
    elif update:
        _git("-C", str(src), "fetch", "--depth", "1", "origin")
        _git("-C", str(src), "reset", "--hard", "FETCH_HEAD")
    return src / DATA_SUBDIR


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_profile(position: str | None) -> dict:
    """'외야수(우투좌타)' → {'pos': '외야수', 'throws': 'R', 'bats': 'L'}."""
    m = POS_RE.match(position or "")
    if not m:
        return {"pos": None, "throws": None, "bats": None}
    return {"pos": m["pos"].strip(), "throws": HAND[m["t"]], "bats": HAND[m["b"]]}


def career_steals(careers: dict) -> dict[tuple[str, int], tuple[float | None, float | None]]:
    """careers.json(현역만) → {(playerId, 연도): (SB, CS)}."""
    out = {}
    for pid, roles in careers.items():
        for row in roles.get("hitter", {}).get("rows", []):
            year = to_num(row.get("연도"))
            if year is not None:
                out[(pid, int(year))] = (to_num(row.get("SB")), to_num(row.get("CS")))
    return out


def season_sources(data_dir: Path, meta: dict) -> list[tuple[int, list, list, bool]]:
    """(연도, 타자 rows, 투수 rows, 진행중 여부) 목록. 범위 안 연도가 빠지면 에러."""
    out = []
    for year in range(config.YEAR_START, config.YEAR_END + 1):
        path = data_dir / "season" / f"{year}.json"
        if path.exists():
            d = _load(path)
            out.append((year, d["hitters"], d["pitchers"], False))
        elif year == int(meta.get("season", 0)):
            out.append((year, _load(data_dir / "hitters.json"), _load(data_dir / "pitchers.json"), True))
        else:
            raise FileNotFoundError(f"{year}년 데이터가 소스에 없음: {path}")
    return out


def build_frames(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    meta = _load(data_dir / "meta.json")
    players = _load(data_dir / "players.json")
    steals = career_steals(_load(data_dir / "careers.json"))
    profiles = {pid: parse_profile(p.get("position")) for pid, p in players.items()}

    bat_rows, pit_rows, partial_years = [], [], []
    for year, hitters, pitchers, partial in season_sources(data_dir, meta):
        if partial:
            partial_years.append(year)
        for r in hitters:
            pid = r["playerId"]
            row = {"player_id": pid, "name": r["선수명"], "year": year, "team": r["팀명"]}
            row.update({c: to_num(r.get(c)) for c in BAT_STATS})
            row["SB"], row["CS"] = steals.get((pid, year), (None, None))
            row.update(profiles.get(pid, {}))
            bat_rows.append(row)
        for r in pitchers:
            pid = r["playerId"]
            row = {"player_id": pid, "name": r["선수명"], "year": year, "team": r["팀명"]}
            row.update({c: to_num(r.get(c)) for c in PIT_STATS})
            row["IP_outs"] = parse_ip_outs(r.get("IP"))
            prof = profiles.get(pid, {})
            row["throws"] = prof.get("throws")
            pit_rows.append(row)

    bat = pd.DataFrame(bat_rows)
    pit = pd.DataFrame(pit_rows)
    for df, kind in ((bat, "타자"), (pit, "투수")):
        dup = df.duplicated(["player_id", "year"]).sum()
        if dup:
            raise ValueError(f"{kind} (선수, 연도) 중복 {dup}건 — 소스 구조가 바뀌었는지 확인 필요")

    meta_out = {
        "source": config.KBO_STATICS_REPO,
        "source_commit": _git("-C", str(config.KBO_STATICS_DIR), "rev-parse", "HEAD")
        if (config.KBO_STATICS_DIR / ".git").exists() else None,
        "source_updated_at": meta.get("updatedAt"),
        "original_source": meta.get("source"),
        "years": [config.YEAR_START, config.YEAR_END],
        "partial_years": partial_years,
        "missing_fields": {
            "SB/CS": "현역(소스 players.json 수록) 선수만 있음",
            "bats/throws/pos": "현역 선수만 있음",
            "GS(선발등판)": "없음 — NP/G(경기당 투구수)로 선발/불펜 추정",
        },
    }
    return bat, pit, meta_out


def main() -> None:
    ap = argparse.ArgumentParser(description="KBO_statics → 표준 시즌 기록 CSV")
    ap.add_argument("--update", action="store_true", help="소스 repo 최신화")
    ap.add_argument("--data-dir", type=Path, help="이미 받아 둔 KBO_statics의 web/public/data 경로")
    args = ap.parse_args()

    data_dir = args.data_dir or ensure_source(update=args.update)
    bat, pit, meta = build_frames(data_dir)

    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: 엑셀에서 바로 열어도 한글 안 깨지게
    bat.to_csv(config.BATTING_CSV, index=False, encoding="utf-8-sig")
    pit.to_csv(config.PITCHING_CSV, index=False, encoding="utf-8-sig")
    config.SOURCE_META_JSON.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"소스: {meta['source']} @ {meta['source_commit']} (갱신 {meta['source_updated_at']})")
    print(f"타자 {len(bat):,}행 / 투수 {len(pit):,}행 → {config.PROCESSED_DIR}")
    per_year = Counter(bat["year"]), Counter(pit["year"])
    for year in sorted(per_year[0]):
        flag = " (진행 중)" if year in meta["partial_years"] else ""
        print(f"  {year}: 타자 {per_year[0][year]:>3} / 투수 {per_year[1][year]:>3}{flag}")
    print(f"도루 기록 있는 타자 시즌: {bat['SB'].notna().sum():,} / {len(bat):,}")


if __name__ == "__main__":
    main()
