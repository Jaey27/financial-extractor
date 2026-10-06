"""카드 JSON → 사람이 보는 엑셀 (타자/투수/설명 시트).

    python -m pipeline.export_excel
"""

from __future__ import annotations

import json

import pandas as pd

from . import config

EXPORT_PATH = config.DATA_DIR / "exports" / f"kbo_cards_{config.YEAR_START}_{config.YEAR_END}.xlsx"

BAT_LINE = [("G", "경기"), ("PA", "타석"), ("AB", "타수"), ("H", "안타"), ("2B", "2루타"),
            ("3B", "3루타"), ("HR", "홈런"), ("RBI", "타점"), ("BB", "볼넷"), ("SO", "삼진"),
            ("SB", "도루"), ("CS", "도루실패"), ("AVG", "타율"), ("OBP", "출루율"),
            ("SLG", "장타율"), ("OPS", "OPS")]
BAT_RATINGS = [("accuracy", "정확도"), ("contact", "컨택"), ("power", "파워"), ("eye", "선구안"),
               ("babip", "타구질"), ("speed", "주루"), ("steal", "도루능력"), ("ovr", "OVR")]
PIT_LINE = [("G", "경기"), ("W", "승"), ("L", "패"), ("SV", "세이브"), ("HLD", "홀드"),
            ("IP", "이닝"), ("TBF", "상대타자"), ("SO", "탈삼진"), ("BB", "볼넷"), ("HR", "피홈런"),
            ("NP", "투구수"), ("ERA", "ERA"), ("WHIP", "WHIP")]
PIT_RATINGS = [("stuff", "구위"), ("control", "제구"), ("movement", "무브먼트"),
               ("hit_suppression", "피안타억제"), ("stamina", "체력"), ("ovr", "OVR")]


def _rows(cards, line_cols, rating_cols, extra):
    for c in cards:
        row = {"연도": c["year"], "선수ID": c["player_id"], "이름": c["name"],
               "팀(실제)": "/".join(t["team"] for t in c["teams"])}
        row.update(extra(c))
        row.update({ko: c["line"].get(k) for k, ko in line_cols})
        row.update({ko: c["ratings"].get(k) for k, ko in rating_cols})
        row["소표본"] = "Y" if c["small_sample"] else ""
        row["진행중시즌"] = "Y" if c["partial_season"] else ""
        yield row


def main() -> None:
    batters = json.loads((config.CARDS_DIR / "batters.json").read_text(encoding="utf-8"))
    pitchers = json.loads((config.CARDS_DIR / "pitchers.json").read_text(encoding="utf-8"))
    meta = json.loads(config.SOURCE_META_JSON.read_text(encoding="utf-8"))

    bat = pd.DataFrame(_rows(batters, BAT_LINE, BAT_RATINGS,
                             lambda c: {"투타": f"{c['throws']}투{c['bats']}타" if c["bats"] else None}))
    pit = pd.DataFrame(_rows(pitchers, PIT_LINE, PIT_RATINGS,
                             lambda c: {"역할": c["role"], "투": c["throws"]}))
    bat = bat.sort_values(["연도", "OVR"], ascending=[True, False])
    pit = pit.sort_values(["연도", "OVR"], ascending=[True, False])

    notes = pd.DataFrame({"항목": [
        "데이터 출처", "원 출처", "소스 커밋", "기준 시각", "대상", "진행 중 시즌",
        "능력치 스케일", "정확도/컨택/파워/선구안/타구질", "주루/도루능력", "구위/제구/무브먼트/피안타억제",
        "체력/역할", "OVR", "소표본", "결측",
    ], "내용": [
        meta["source"], meta["original_source"], meta["source_commit"], meta["source_updated_at"],
        f"{config.YEAR_START}~{config.YEAR_END} 1군 정규시즌 누적 {config.MIN_CAREER_GAMES}경기 이상"
        + (f" (투수는 또는 누적 {config.PITCHER_ALT_MIN_IP:g}이닝 이상)" if config.PITCHER_ALT_MIN_IP else "")
        + " 선수의 전 시즌",
        ", ".join(map(str, meta["partial_years"])) or "없음",
        f"같은 시즌 리그 평균={config.RATING_MEAN}, 1표준편차={config.RATING_SD} (1~99). 시대 효과 제거",
        "타율 / 삼진 억제 / 홈런·순장타율 / 고의4구 제외 볼넷 / 인플레이 타구 안타율(BABIP)",
        "3루타·득점·병살 억제·도루 시도 / 도루 시도율·성공률",
        "탈삼진 / 볼넷·사구 억제 / 피홈런 억제 / 인플레이 피안타 억제 (모두 상대타자 대비)",
        "경기당 투구수 기준 (선발 90구+ ≈ 90~99). 경기당 50구 이상=SP, 10세이브 이상=CL",
        "타자: 득점가치(wOBA류) / 투수: FIP류 75% + 피안타억제 25%",
        "타자 50타석·투수 상대타자 50명 미만 — 리그 평균 쪽으로 보정됨",
        ", ".join(f"{k}: {v}" for k, v in meta["missing_fields"].items()),
    ]})

    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(EXPORT_PATH, engine="openpyxl") as xw:
        bat.to_excel(xw, sheet_name="타자", index=False)
        pit.to_excel(xw, sheet_name="투수", index=False)
        notes.to_excel(xw, sheet_name="설명", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "D2" if ws.title != "설명" else "A2"
            for col_cells in ws.columns:
                width = max(len(str(c.value or "")) for c in col_cells[:200])
                ws.column_dimensions[col_cells[0].column_letter].width = min(max(width + 2, 6), 60)
    print(f"타자 {len(bat):,}행 / 투수 {len(pit):,}행 → {EXPORT_PATH}")


if __name__ == "__main__":
    main()
