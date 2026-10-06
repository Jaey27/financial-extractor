# baseball by j

KBO 2010~2026 시즌 선수 카드로 하는 2인용 수 싸움 야구 게임. 비상업·개인용.

- 이어서 작업할 때 먼저 읽을 것: [HANDOFF.md](HANDOFF.md)
- 게임 설계: [docs/DESIGN.md](docs/DESIGN.md)
- 데이터 소스·산식·검증: [docs/DATA_SPEC.md](docs/DATA_SPEC.md)

## 현재 상태 (2026-10-06)

- 데이터: KBO 공식 기록 기반 2010~2026 시즌 기록 → 누적 100경기 이상 타자 519명(카드 3,721장), 100경기 또는 150이닝 이상 투수 439명(카드 2,872장).
- 2026은 시즌 진행 중 값 (시즌 종료 후 재생성).
- 다음: 데이터 보강(은퇴 선수 도루·투타 등) → 타석 엔진.

## 데이터 만들기

```bash
cd baseball
pip install -r requirements.txt
python -m pipeline.kbo_statics      # 소스 받기 → data/processed/*.csv
python -m pipeline.build_cards      # 능력치 계산 → data/cards/*.json
python -m pipeline.export_excel     # 엑셀 → data/exports/kbo_cards_2010_2026.xlsx
python -m unittest discover -s tests -t .
```

기준값(기간, 100경기, 능력치 스케일 등)은 `pipeline/config.py`, 팀 표시 이름은 `data/franchises.json`에서 바꿈.

## 폴더

```
baseball/
├── docs/            설계·데이터 문서
├── data/
│   ├── franchises.json   실제 구단 ↔ 가상 팀명
│   ├── raw/              소스 캐시 (git 제외)
│   ├── processed/        표준 시즌 기록 CSV (repo private 전환 전까지 git 제외)
│   ├── cards/            게임 카드 JSON (〃)
│   └── exports/          엑셀 (〃)
├── pipeline/        수집·정규화·능력치·카드 생성
└── tests/
```
