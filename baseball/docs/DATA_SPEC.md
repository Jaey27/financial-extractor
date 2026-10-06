# 데이터 스펙

최종 갱신: 2026-10-06

## 1. 수집 범위와 대상

- 기간: 2010~2026 KBO 1군 정규시즌. 2026은 시즌 진행 중이라 소스 기준 시각 값임 (`partial_season` 표시).
- 카드 대상: 기간 안 누적 출장 100경기 이상인 선수. 타자는 타자 출장(G), 투수는 등판(G)으로 각각 판단.
  대상 선수는 기간 안 모든 시즌에 카드가 생김 (표본 작은 시즌은 `small_sample` 표시 + 리그 평균 쪽 보정).
- 리그 평균·표준편차는 대상 여부와 상관없이 그 시즌 1군 전 선수로 계산함.
- 현재 결과 (소스 커밋 `4b4b7b5`, 2026-10-06 07:19 기준): 타자 519명 3,721장, 투수 324명 2,575장.

### 100경기 기준의 영향 (결정 필요)

선발투수는 시즌당 25~30경기라 2~3시즌 뛴 외국인 에이스가 대거 빠짐.
예: 헥터 2016~2018 90경기 582이닝, 데스파이네 2020~2022 98경기 559이닝, 2023 한 시즌만 뛴 페디도 제외.
`config.PITCHER_ALT_MIN_IP`로 이닝 보조 기준을 켤 수 있음.

| 투수 보조 기준 | 추가 인원 | 의미 |
|---|---|---|
| 없음 (현재) | 0 | 요청 기준 그대로 |
| 300이닝 | +25명 | 2~3시즌 선발 구제 |
| 150이닝 | +115명 | 한 시즌 풀타임 선발 구제 (타자 100경기 ≈ 한 시즌과 형평) |

## 2. 데이터 소스 비교 (2026-10-06 조사)

| 소스 | 범위 | 장점 | 한계 | 이 클라우드 환경 접근 |
|---|---|---|---|---|
| [KBO_statics](https://github.com/PsyproLEE/KBO_statics) (GitHub 공개 repo) — 1차 채택 | 1982~2026, 시즌별 1군 전 선수 | KBO 공식 기록을 매일 자동 수집해 JSON으로 커밋. 지금 바로 사용 가능 | 도루·투타·포지션은 현역만, 선발등판(GS) 없음, WAR 없음. 개인 repo라 갱신 중단 위험 | 가능 (git) |
| [KBO 공식 기록실](https://www.koreabaseball.com/Record/Player/HitterBasic/Basic1.aspx) | 1982~ | 원 출처. 선수별 연도별 기록([예시](https://www.koreabaseball.com/Record/Player/HitterDetail/Total.aspx?playerId=75847)), 주루·수비 기록 페이지 따로 있음 | ASP.NET 포스트백이라 수집이 번거로움, 고급 지표 없음 | 차단 |
| [스탯티즈](https://statiz.sporki.com/stats/?m=main&m2=pitching) | 1982~ | WAR 등 세이버 지표, 선수별 연도별 페이지([예시](https://statiz.sporki.com/player/?m=year&p_no=10590)) | 표 구조·로그인 필요 여부 미확인, 이용약관 확인 필요 | 차단 |
| [Baseball-Reference](https://www.baseball-reference.com/register/korean-baseball-league-stats.shtml) | 1982~2026 (페이지 표기) | 영문, 선수별 커리어 | [분당 20회 넘으면 차단](https://www.sports-reference.com/bot-traffic.html), [데이터 정책](https://www.sports-reference.com/data_use.html)상 경쟁 DB 구축·AI 학습/프롬프트 사용 금지 → 이 프로젝트엔 부적합 | 차단 |
| [FanGraphs KBO](https://www.fangraphs.com/leaders/international/kbo) | [2002~](https://blogs.fangraphs.com/introducing-kbo-stats-on-fangraphs/) | 2020~21은 [구종·구속·헛스윙률·타구 데이터](https://blogs.fangraphs.com/instagraphs/new-and-updated-kbo-data-now-available/)까지 있음 | 2022년 이후 갱신 여부 미확인 | 차단 |
| [MyKBOStats](https://mykbostats.com/stats) | 2026 시즌 확인 | 영문 팬 사이트, 선수별 시즌 기록 | 비공식, 과거 시즌 범위 미확인 | 차단 |
| [KBReport](http://www.kbreport.com/leader/main) | 상세 2013~2020 + 역대 1982~2012 (검색 요약 기준) | 세이버 지표 | 최근 시즌 갱신 여부 미확인 | 차단 |
| [야구나라](https://www.yagoonara.com/teams) | 범위 미확인 | 선수별 정규시즌 기록 페이지 | 원 출처 미확인 | 차단 |
| Kaggle ([타자 2018~2024](https://www.kaggle.com/datasets/clementmsika/kbo-player-performance-dataset-2018-2024) 등) | 부분 | 파일 다운로드 | 기간·항목이 부분적, 로그인 필요 | 차단 |

정리:
- 기본 기록(타석·안타·홈런·삼진·볼넷·이닝 등)은 KBO_statics로 충분함 (원 출처 KBO 공식).
- 빠진 것(은퇴 선수 도루·투타·포지션, 선발등판, 수비)은 KBO 공식 기록실이나 스탯티즈에서 보강해야 함.
  방법은 셋 중 하나: 이 클라우드 환경 네트워크 허용 목록에 도메인 추가 / GitHub Actions에서 수집 / 맥미니에서 실행.

## 3. 파이프라인

```
python -m pipeline.kbo_statics      # 소스 받기(git clone) → data/processed/*.csv
python -m pipeline.build_cards      # CSV → data/cards/*.json (능력치 계산)
python -m pipeline.export_excel     # 카드 → data/exports/kbo_cards_2010_2026.xlsx
```

소스 최신화는 `python -m pipeline.kbo_statics --update`. 전체 실행 수 초.
`pipeline/statiz.py`는 스탯티즈 보강용 뼈대 (네트워크 허용 후 `python -m pipeline.statiz`로 페이지 구조부터 확인).

## 4. 표준 시즌 기록 CSV (`data/processed/`)

한 행 = 선수 1명의 한 시즌. 소스가 달라도 이 형태로 맞추면 이후 단계는 그대로 씀.

- 공통: `player_id`(KBO 선수 ID), `name`, `year`, `team`(원본 팀 표기)
- 타자 (`batting_seasons.csv`): `G PA AB R H 2B 3B HR RBI SAC SF BB IBB HBP SO GDP SB CS pos throws bats`
- 투수 (`pitching_seasons.csv`): `G W L SV HLD CG SHO QS BSV TBF NP H 2B 3B HR BB IBB HBP SO R ER WP BK IP_outs throws`
- `IP_outs`: 이닝을 아웃카운트로 저장 (192 2/3이닝 = 578). 소수점 표기 혼동 방지.
- 시즌 중 트레이드: KBO 공식 기록은 시즌 합계를 한 팀으로 표기함 (소스 안 교차검증 결과). 그래서 연도별 로스터에는 그 팀으로만 들어감.
- 엑셀에서 한글 안 깨지게 `utf-8-sig`로 저장.

## 5. 능력치 산식 (`pipeline/ratings.py`)

공통 규칙
- 같은 시즌 리그 대비 z-score → 능력치 = 50 + 15 × z, 1~99로 자름. 시대 효과(타고투저 등)가 빠짐.
- 리그 평균은 그 시즌 모집단(타자 100타석+, 투수 상대타자 100명+)의 합계 비율.
- 작은 표본 보정: 비율 = (기록 + k × 리그평균) / (표본 + k). k는 `config.SHRINK_K` (시즌 재현이 목적이라 약하게 잡음).
- 소스에 없는 기록은 결측 유지 → 해당 능력치는 None (0으로 채우지 않음).

타자 (분모: 타석 PA, 별도 표기 제외)

| 능력치 | 지표 | 엔진에서 쓰는 곳 |
|---|---|---|
| 정확도 | 타율 H/AB | 표시용 대표 지표 |
| 컨택 | 삼진율 SO/PA (낮을수록 높음) | 헛스윙·삼진 확률 |
| 파워 | 홈런율 HR/PA 60% + 순장타율 ISO 40% | 장타·홈런 확률 |
| 선구안 | 고의4구 제외 볼넷율 | 볼 스윙(체이스) 확률, 볼넷 |
| 타구질 | BABIP (H-HR)/(AB-SO-HR+SF) | 인플레이 타구의 안타 확률 |
| 주루 | 3루타율 + 득점율 + 병살 억제 + 도루 시도율 (있는 것만) | 추가 진루, 내야안타 |
| 도루능력 | 도루 시도율 + 성공률 (도루 기록 있을 때만) | 도루 시도·성공 |
| 수비 | 미정 (데이터 보강 후) | 수비 범위·실책 |
| OVR | 득점가치 wOBA류 가중합 | 카드 등급 |

투수 (분모: 상대타자 TBF)

| 능력치 | 지표 | 엔진에서 쓰는 곳 |
|---|---|---|
| 구위 | 탈삼진율 | 헛스윙 유도 |
| 제구 | (볼넷-고의4구+사구)/TBF (낮을수록 높음) | 목표 지점 대비 탄착 오차 |
| 무브먼트 | 피홈런율 (낮을수록 높음) | 정타·장타 억제 |
| 피안타억제 | 인플레이 피안타율 (낮을수록 높음) | 인플레이 타구 아웃 확률 |
| 체력 | 경기당 투구수 × 0.95 + 5 (투구수 없으면 아웃카운트로) | 투구수 한도, 피로 |
| OVR | FIP류 75% + 피안타억제 25% | 카드 등급 |

역할: 경기당 투구수 50구 이상 = SP, 아니고 10세이브 이상 = CL, 나머지 RP (소스에 GS가 없어서 추정).

엔진용 비율(`rates`): 같은 z를 2010~2026 평균 리그 환경에 다시 입힌 값. 엔진은 능력치가 아니라 이 비율로 확률을 계산함 → 설계 문서 참고.

## 6. 카드 JSON (`data/cards/`)

```jsonc
// batters.json 한 장 (실제 생성 결과)
{
  "card_id": "B78168-2014", "player_id": "78168", "name": "서건창", "year": 2014,
  "teams": [{"team": "넥센", "G": 128, "franchise": "heroes"}],
  "bats": "L", "throws": "R", "pos": "내야수",
  "small_sample": false, "partial_season": false,
  "line": {"G": 128, "PA": 616, "AB": 543, "H": 201, "2B": 41, "3B": 17, "HR": 7, "RBI": 67,
           "BB": 59, "SO": 47, "SB": 48, "CS": 17, "AVG": 0.37, "OBP": 0.438, "SLG": 0.547, "OPS": 0.985},
  "ratings": {"accuracy": 84, "contact": 79, "power": 45, "eye": 51, "babip": 79,
              "speed": 98, "steal": 66, "ovr": 73, "defense": null},
  "rates": {"so": 0.0813, "bb": 0.1052, "hr": 0.0116, "babip": 0.3684, "double_share": 0.1963,
            "triple_share": 0.0625, "sb_att": 0.225, "sb_pct": 0.7032}
}
```

- `rosters.json`: `{프랜차이즈: {연도: {batters: [...], pitchers: [...]}}}` (OVR 순). 연도별 모드 로스터.
- `league_env.json`: 시즌별 지표 평균·표준편차 + 엔진 기준 환경(`reference`).
- 프랜차이즈 ↔ 실제 팀 표기 ↔ 게임 표시 이름은 `data/franchises.json` 하나에서 관리.

## 7. 검증

자동 (커밋 전 매번)
- 단위 테스트: `cd baseball && python -m unittest discover -s tests -t .` (가상 선수 데이터)
- 소스 내부 교차검증: 현역 선수 상세 페이지 연도별 기록 vs 시즌 기록실 → 2010~2025 2,833개 시즌 G·PA·H·HR·SO(투수 G·IP·SO·TBF)와 팀 전부 일치.
- 잘 알려진 기록 대조: 2014 서건창 201안타 .370, 2014 박병호 52홈런, 2015 박병호 53홈런, 2015 테임즈 47홈런 .381, 2010 류현진 ERA 1.82 192⅔이닝, 2010 이대호 44홈런 .364 → 일치.

사람 (데이터 확정 전 1회)
- 팀별로 아무 시즌 1개씩 골라 KBO 공식 기록실 값과 5명 대조.
- 2026은 시즌 종료 후 `--update`로 다시 생성하고 확정치로 교체.

## 8. 남은 공백

| 항목 | 현재 | 보강 방법 |
|---|---|---|
| 은퇴 선수 도루(SB/CS) | 없음 → 도루능력 None, 주루는 나머지 지표로 계산 | KBO 공식 주루 기록 페이지 또는 스탯티즈 |
| 은퇴 선수 투타·포지션 | 없음 | KBO 공식 선수 상세(은퇴 선수 페이지) 또는 스탯티즈 |
| 투수 선발등판(GS) | 없음 → 투구수로 역할 추정 | KBO 공식 투수 세부 기록 |
| 수비 | 없음 | 스탯티즈 수비 지표 또는 포지션 기본값 |
| WAR | 없음 | 스탯티즈 (선택) |
| 구종·구속 | 없음 | FanGraphs 2020~21 정도만 확인됨. 게임에선 기본 구종 세트로 시작 |
