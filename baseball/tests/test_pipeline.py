"""파이프라인 단위 테스트. 선수 데이터는 전부 가상(테스트용)임.

    cd baseball && python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import unittest

import pandas as pd

from pipeline import config
from pipeline.build_cards import build
from pipeline.kbo_statics import parse_profile
from pipeline.parse import format_ip, parse_ip_outs, to_num
from pipeline.statiz import normalize_season_table, player_links
from pipeline.teams import franchise_for, load_franchises


def fake_batting() -> pd.DataFrame:
    rows = []
    for year in (2014, 2019):
        for i in range(12):
            pa = 300 + 30 * i
            bb = int(pa * (0.12 - 0.005 * i))
            ab = pa - bb - 5
            rows.append({
                "player_id": f"9{i:03d}", "name": f"가상타자{i:02d}", "year": year,
                "team": "KIA" if i % 2 else "삼성",
                "G": 60 + i, "PA": pa, "AB": ab, "R": 40, "H": int(ab * (0.300 - 0.005 * i)),
                "2B": 20, "3B": 2, "HR": 5 + i, "RBI": 40, "SAC": 1, "SF": 1,
                "BB": bb, "IBB": 1, "HBP": 3, "SO": int(pa * (0.10 + 0.01 * i)), "GDP": 5,
                # 짝수 번호만 도루 기록 있음 (현역/은퇴 혼재 상황 재현)
                "SB": float(i) if i % 2 == 0 else None, "CS": 1.0 if i % 2 == 0 else None,
            })
    # 소표본 시즌이 섞인 선수: 2014 15경기 20타석, 2019 100경기
    rows.append({"player_id": "9900", "name": "가상소표본", "year": 2014, "team": "넥센",
                 "G": 15, "PA": 20, "AB": 18, "R": 2, "H": 9, "2B": 1, "3B": 0, "HR": 2,
                 "RBI": 4, "SAC": 0, "SF": 0, "BB": 2, "IBB": 0, "HBP": 0, "SO": 3, "GDP": 0})
    rows.append({"player_id": "9900", "name": "가상소표본", "year": 2019, "team": "키움",
                 "G": 100, "PA": 400, "AB": 360, "R": 50, "H": 100, "2B": 20, "3B": 1, "HR": 10,
                 "RBI": 50, "SAC": 2, "SF": 3, "BB": 30, "IBB": 1, "HBP": 5, "SO": 70, "GDP": 8})
    # 누적 경기 미달 선수: 리그 평균 계산에는 들어가지만 카드는 안 만들어짐
    rows.append({"player_id": "9901", "name": "가상미달", "year": 2019, "team": "SSG",
                 "G": 30, "PA": 120, "AB": 110, "R": 10, "H": 25, "2B": 5, "3B": 0, "HR": 2,
                 "RBI": 10, "SAC": 0, "SF": 1, "BB": 8, "IBB": 0, "HBP": 1, "SO": 30, "GDP": 2})
    return pd.DataFrame(rows)


def fake_pitching() -> pd.DataFrame:
    # 선발은 시즌당 28경기라 4시즌은 뛰어야 누적 100경기를 넘음
    rows = []
    for year in (2014, 2015, 2016, 2019):
        for i in range(10):
            starter = i < 5
            g = 28 if starter else 60
            outs = 480 if starter else 180
            tbf = outs + 150 if starter else outs + 60
            rows.append({
                "player_id": f"8{i:03d}", "name": f"가상투수{i:02d}", "year": year,
                "team": "LG" if i % 2 else "두산",
                "G": g, "W": 8, "L": 6, "SV": 25 if i == 9 else 0, "HLD": 0, "TBF": tbf,
                "NP": g * (95 if starter else 17), "IP_outs": outs,
                "H": int(tbf * 0.24), "HR": 5 + i, "BB": int(tbf * (0.06 + 0.005 * i)),
                "IBB": 0, "HBP": 3, "SO": int(tbf * (0.25 - 0.01 * i)), "R": 50, "ER": 45,
            })
    return pd.DataFrame(rows)


class TestParse(unittest.TestCase):
    def test_ip_outs(self):
        cases = {"192 2/3": 578, "44 1/3": 133, "0": 0, "123.1": 370, "10.0": 30,
                 "123⅔": 371, "⅓": 1, "2/3": 2, "-": None, "": None}
        for text, outs in cases.items():
            self.assertEqual(parse_ip_outs(text), outs, text)
        self.assertEqual(format_ip(578), "192 2/3")
        self.assertEqual(format_ip(30), "10")

    def test_to_num(self):
        self.assertEqual(to_num("1,234"), 1234.0)
        self.assertIsNone(to_num("-"))
        self.assertEqual(to_num("0.350"), 0.35)

    def test_profile(self):
        self.assertEqual(parse_profile("외야수(우투좌타)"), {"pos": "외야수", "throws": "R", "bats": "L"})
        self.assertEqual(parse_profile("투수(좌투좌타)")["throws"], "L")
        self.assertIsNone(parse_profile(None)["pos"])


class TestTeams(unittest.TestCase):
    def test_franchise_for(self):
        fr = load_franchises()
        expect = {"KIA": "gwangju", "SSG": "incheon", "SK": "incheon", "넥센": "heroes",
                  "키움": "heroes", "kt": "suwon", "두산": "jamsil_a", "LG": "jamsil_b",
                  "15KIA": "gwangju", "없는팀": None}
        for team, fid in expect.items():
            self.assertEqual(franchise_for(team, fr), fid, team)


class TestStatizParsing(unittest.TestCase):
    # 실제 스탯티즈 HTML이 아니라 파서 동작만 보는 가짜 HTML
    HTML = """
    <table><thead><tr><th>연도</th><th>팀</th><th>G</th><th>타석</th><th>타수</th><th>안타</th>
    <th>홈런</th><th>볼넷</th><th>삼진</th></tr></thead><tbody>
    <tr><td>2015</td><td>가상팀</td><td>100</td><td>400</td><td>350</td><td>100</td><td>10</td><td>40</td><td>60</td></tr>
    <tr><td>통산</td><td></td><td>100</td><td>400</td><td>350</td><td>100</td><td>10</td><td>40</td><td>60</td></tr>
    </tbody></table><a href="/player/?m=year&p_no=123">가상선수</a>"""

    def test_normalize_drops_total_row(self):
        df = pd.read_html(__import__("io").StringIO(self.HTML))[0]
        out = normalize_season_table(df, "batting")
        self.assertEqual(len(out), 1)
        self.assertEqual(int(out.loc[0, "PA"]), 400)

    def test_player_links(self):
        self.assertEqual(player_links(self.HTML), {123: "가상선수"})


class TestBuildCards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(fake_batting(), fake_pitching(), load_franchises(), {2019})
        cls.bat = {c["card_id"]: c for c in cls.result["batters"]}
        cls.pit = {c["card_id"]: c for c in cls.result["pitchers"]}

    def test_eligibility(self):
        self.assertIn("B9900-2014", self.bat)  # 누적 115경기 → 대상
        self.assertNotIn("B9901-2019", self.bat)  # 누적 30경기 → 제외
        self.assertEqual(self.result["eligible"]["batters"], 13)

    def test_small_sample_flag(self):
        self.assertTrue(self.bat["B9900-2014"]["small_sample"])
        self.assertFalse(self.bat["B9900-2019"]["small_sample"])

    def test_ratings_in_range(self):
        for card in list(self.bat.values()) + list(self.pit.values()):
            for k, v in card["ratings"].items():
                if v is not None:
                    self.assertTrue(config.RATING_MIN <= v <= config.RATING_MAX, (card["card_id"], k, v))
            for k, v in card["rates"].items():
                if v is not None and k not in ("np_per_g", "outs_per_g"):
                    self.assertTrue(0 <= v <= 1, (card["card_id"], k, v))

    def test_contact_follows_strikeouts(self):
        # 삼진율이 가장 낮은 가상타자00의 컨택이 가장 높아야 함
        same_year = [c for c in self.bat.values() if c["year"] == 2014 and c["player_id"].startswith("90")]
        best = max(same_year, key=lambda c: c["ratings"]["contact"])
        self.assertEqual(best["player_id"], "9000")

    def test_missing_steals_stay_missing(self):
        self.assertIsNone(self.bat["B9001-2014"]["ratings"]["steal"])  # 도루 기록 없음
        self.assertIsNotNone(self.bat["B9001-2014"]["ratings"]["speed"])  # 3루타·득점 등으로 계산
        self.assertIsNotNone(self.bat["B9002-2014"]["ratings"]["steal"])

    def test_pitcher_roles_and_stamina(self):
        sp, rp, cl = self.pit["P8000-2014"], self.pit["P8006-2014"], self.pit["P8009-2014"]
        self.assertEqual((sp["role"], rp["role"], cl["role"]), ("SP", "RP", "CL"))
        self.assertGreater(sp["ratings"]["stamina"], rp["ratings"]["stamina"])
        self.assertGreater(self.pit["P8000-2014"]["ratings"]["stuff"], self.pit["P8004-2014"]["ratings"]["stuff"])

    def test_rosters_and_partial(self):
        self.assertIn("B9900-2019", self.result["rosters"]["heroes"]["2019"]["batters"])
        self.assertTrue(self.bat["B9900-2019"]["partial_season"])
        self.assertFalse(self.bat["B9900-2014"]["partial_season"])
        self.assertEqual(self.result["unmapped_teams"], {})

    def test_line_math(self):
        line = self.bat["B9900-2019"]["line"]
        self.assertEqual(line["AVG"], round(100 / 360, 3))
        self.assertEqual(self.pit["P8000-2014"]["line"]["IP"], "160")


if __name__ == "__main__":
    unittest.main()
