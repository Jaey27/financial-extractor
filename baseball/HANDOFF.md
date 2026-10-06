# HANDOFF — baseball by j

작성: 2026-10-06, 클라우드 세션(Claude Code on the web) → 로컬 이관용.
이 파일 하나만 읽으면 이어서 작업할 수 있게 정리함. 세부는 `docs/DESIGN.md`, `docs/DATA_SPEC.md`.

## 0. 지금 상태 한 줄

데이터 파이프라인과 카드 생성은 끝났고 (KBO 2010~2026, 타자 519명 3,721장 / 투수 439명 2,872장), 다음은 데이터 보강(은퇴 선수 도루·투타 등) → 타석 엔진임.

## 1. 목표와 요구사항 (원래 요청 정리)

- 비상업, 나와 친구 1명이 즐기는 야구 게임. 1단계 1P vs CPU, 가능하면 친구 PC와 1:1 대전.
- KBO 2010~2026, 1군 누적 100경기 이상 선수의 시즌별 카드. 투수는 100경기 또는 누적 150이닝 이상.
- 능력치는 타자·투수 각 5~10개. 좋으면 확률이 올라감. 타자가 투구 위치를 예측해 맞추면 안타·홈런 확률이 올라감.
- 시작: 팀 선택 → 연도별 / 연도 짬뽕 모드. "1인칭" ON이면 특정 선수 특정 시즌 카드가 내 이름으로 바뀜.
- 팀 이름·유니폼은 실제와 다르게 (저작권). 그래픽은 후순위, 설계와 데이터 먼저.

## 2. 확정된 결정

| 항목 | 결정 | 근거·위치 |
|---|---|---|
| 1차 데이터 소스 | [PsyproLEE/KBO_statics](https://github.com/PsyproLEE/KBO_statics) (KBO 공식 기록실을 매일 수집해 JSON으로 커밋하는 공개 repo) | 스탯티즈·KBO 공식이 클라우드에서 차단돼서 채택. `docs/DATA_SPEC.md` 2장 |
| 스탯티즈 | 보강용 (WAR 등). `pipeline/statiz.py`는 실제 페이지로 검증 안 된 뼈대 | |
| 대상 기준 | 타자 누적 100경기, 투수 100경기 또는 150이닝 | `pipeline/config.py` |
| 능력치 | 같은 시즌 리그 대비 z → 50 + 15z, 1~99 (시대 효과 제거) | `pipeline/ratings.py` |
| 엔진 입력 | 능력치가 아니라 시대 중립 비율(`rates`) + odds ratio 결합 | `docs/DESIGN.md` 4장 |
| 노림수 공정성 | 아무렇게나 고르면 기대 보정 = 1 → 카드 기록 재현, 잘 읽으면 초과 성과 | `docs/DESIGN.md` 4.6 |
| 개발 방식 | 로컬 중심 개발, GitHub는 private 백업 + 최종 배포 | 이번 이관 |
| 생성 데이터 | repo public인 동안 git 제외 (`baseball/.gitignore`). private 전환 후 커밋해도 됨 | |
| 기존 코드 | repo 루트의 financial-extractor 코드(Streamlit 앱, 텔레그램 봇)는 손대지 않음 | 맥미니에서 쓰는 중일 수 있어서 |

## 3. 숫자 (소스 커밋 `4b4b7b5`, 2026-10-06 07:19 기준)

- 표준 시즌 기록: 타자 5,866행, 투수 4,241행 (2010~2026 1군 전 선수).
- 대상: 타자 519명 → 카드 3,721장 / 투수 439명 → 카드 2,872장.
- 도루 기록 있는 타자 시즌: 2,044 / 5,866 (현역만 있음).
- 2026은 시즌 진행 중 값. `--update` 후 재생성하면 숫자가 조금 바뀜.

## 4. 로컬 셋업 (맥미니 기준)

선행: GitHub에서 repo 이름 `baseball-by-j`로 변경 + private 전환
(Settings 페이지: https://github.com/Jaey27/financial-extractor/settings — 이름 변경 후 주소는 자동 리다이렉트됨).

방법 A — git으로 받기 (이름 바꾸기 전이면 주소의 `baseball-by-j` 대신 `financial-extractor`)
```bash
git clone -b claude/vigilant-bell-nc4qgw https://github.com/Jaey27/baseball-by-j.git
cd baseball-by-j/baseball
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pipeline.kbo_statics --update   # 소스 받기/최신화 → data/processed/
python -m pipeline.build_cards            # → data/cards/
python -m pipeline.export_excel           # → data/exports/kbo_cards_2010_2026.xlsx
python -m unittest discover -s tests -t . # 15개 통과해야 정상
```
- PR [Jaey27/financial-extractor#1](https://github.com/Jaey27/financial-extractor/pull/1)(draft)을 main에 머지한 뒤 main에서 받아도 됨.

방법 B — 묶음 파일(zip)
- 클라우드 세션에서 보낸 `baseball_by_j_handoff_2026-10-06.zip`을 풀면 코드 + 문서 + 생성 데이터(CSV·카드 JSON·엑셀)가 다 들어 있음.
- git 이력은 없으니, 이어서 개발하려면 방법 A로 받고 zip의 `data/`만 복사하는 걸 추천함 (data는 어차피 위 명령으로 몇 초면 재생성됨).

Windows(jae27)에서 할 경우 `python3` 대신 `py`, venv 활성화는 `.venv\Scripts\activate`.

## 5. 파일 지도

```
baseball/
├── HANDOFF.md            ← 이 파일
├── README.md
├── docs/DESIGN.md        게임 설계 (모드, 1인칭, 타석 엔진, 기술 구조, 로드맵)
├── docs/DATA_SPEC.md     소스 비교, 표준 CSV 스키마, 능력치 산식, 카드 JSON, 검증, 남은 공백
├── data/franchises.json  실제 팀 표기 ↔ 프랜차이즈 id ↔ 가상 팀명(임시값, 바꿔도 됨)
├── pipeline/
│   ├── config.py         모든 기준값 (기간, 100경기/150이닝, 스케일, 보정 강도)
│   ├── kbo_statics.py    KBO_statics JSON → data/processed/*.csv (+ source_meta.json)
│   ├── ratings.py        시즌 기록 → 능력치·엔진용 비율
│   ├── build_cards.py    CSV → data/cards/{batters,pitchers,rosters,league_env}.json
│   ├── export_excel.py   카드 → 엑셀 (타자/투수/설명 시트)
│   ├── statiz.py         스탯티즈 보강용 뼈대 (미검증)
│   ├── parse.py, teams.py
└── tests/test_pipeline.py  가상 선수 데이터로 15개 테스트
```

## 6. 다음 할 일 (우선순위)

1. 데이터 보강 — 로컬은 네트워크 제한이 없으니 KBO 공식 기록실에서 직접 수집.
   - 은퇴 선수 도루(SB/CS)·투타·포지션: 은퇴 선수 페이지 `https://www.koreabaseball.com/Record/Retire/Hitter.aspx?playerId={id}` (투수는 `Retire/Pitcher.aspx`).
     이 URL은 KBO_statics 데이터의 `detailUrl`에 들어 있는 형태임. 연도별 표에 SB/CS가 있는지, 프로필 구조가 현역 페이지와 같은지는 첫 1~2명으로 확인부터.
   - 현역 프로필은 `.player_basic` 또는 `.player_info` 안의 "포지션: 외야수(우투좌타)" 형식 (KBO_statics `scraper/scrape_kbo.py` 참고).
   - 투수 선발등판(GS): `https://www.koreabaseball.com/Record/Player/PitcherBasic/Detail1.aspx` (시즌·팀 선택이 ASP.NET 포스트백 → KBO_statics `scraper/scrape_history.py`의 `postback`/`season_players` 방식 참고).
   - 요청 간격 넉넉히 (config `REQUEST_INTERVAL_SEC = 3`), HTML 캐시 후 파싱. 보강 결과는 표준 CSV 컬럼(SB, CS, bats, throws, pos, GS)에 채우고 `build_cards` 재실행.
2. 사람 검증 — 팀별 아무 시즌 1개씩, 5명을 KBO 공식 기록실 값과 대조.
3. 타석 엔진 프로토타입 — `docs/DESIGN.md` 4장. CLI로 한 타석·한 경기 시뮬 + 캘리브레이션 테스트(예: 2014 서건창 vs 리그 평균 투수 수만 타석 → 타율·삼진율·볼넷율이 실제 근처).
4. 경기 진행(이닝, 교체, 투구수, 주루) + 1P vs CPU 텍스트 UI.
5. 웹 UI → 1:1 온라인 → 그래픽.

## 7. 열린 결정사항

- 로스터 인원 (제안: 타자 13 + 투수 13), 드래프트 모드 포함 여부.
- 기술 구조: 엔진 TypeScript(브라우저·서버 공용) + 웹 UI로 갈지.
- OVR에 주루 일부 반영할지 (지금은 타격 득점가치만 → 2014 서건창 OVR 73).
- 가상 팀명·색 확정 (`data/franchises.json`).
- 배포: 맥미니에서 게임 서버 + 친구는 Tailscale 등으로 접속 (추천). GitHub Pages는 private repo에서 쓰려면 유료 플랜이 필요하고, 사이트 자체는 공개라 실명 데이터에 부적합.

## 8. 알려진 한계·주의

- 시즌 중 트레이드: KBO 공식 기록은 시즌 합계를 한 팀으로 표기 → 연도별 로스터에 그 팀으로만 들어감.
- 투수 역할(SP/RP/CL)은 GS가 없어서 경기당 투구수로 추정 (50구 이상 SP, 10세이브 이상 CL).
- 수비 능력치는 아직 없음 (`defense: null`).
- KBO_statics는 개인 repo이고 LICENSE 파일이 없음 → 개인용으로만 쓰고 재배포 안 함. 갱신이 멈추면 위 6-1처럼 KBO 공식 기록실 직접 수집으로 대체.
- Baseball-Reference는 데이터 정책상 AI 프롬프트 사용 금지 → 쓰지 않음.
- 할루시네이션 금지 원칙: 문서·답변의 수치는 파이프라인 산출물이나 출처 링크로만. 새 소스를 붙이면 잘 알려진 기록 대조 + 소스 교차검증부터.

## 9. 로컬 Claude Code 첫 프롬프트 (복붙용)

```
baseball/HANDOFF.md 를 먼저 읽고 이어서 작업해줘.
1) 파이프라인 재실행 + 테스트로 셋업 확인 (숫자가 HANDOFF 3장과 크게 다르면 이유부터 알려줘)
2) 6장 1번 데이터 보강: KBO 공식 은퇴 선수 페이지 1~2명으로 구조 확인 → SB/CS·투타·포지션 수집기 작성 → 투수 GS 수집
3) 끝나면 build_cards 재실행, 바뀐 숫자와 검증 결과를 HANDOFF.md 3장에 갱신
답변은 한국어 ~함/~임체, 굵은 글씨 없이. 수치는 반드시 산출물이나 출처로 확인된 것만.
```
