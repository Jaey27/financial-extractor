"""데이터 파이프라인 전역 설정. 기준값은 여기서만 바꾼다."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # baseball/
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"  # 원본 HTML 캐시 (git 제외)
PROCESSED_DIR = DATA_DIR / "processed"  # 정규화된 시즌 기록 CSV
CARDS_DIR = DATA_DIR / "cards"  # 게임이 읽는 카드 JSON
FRANCHISES_PATH = DATA_DIR / "franchises.json"

BATTING_CSV = PROCESSED_DIR / "batting_seasons.csv"
PITCHING_CSV = PROCESSED_DIR / "pitching_seasons.csv"
SOURCE_META_JSON = PROCESSED_DIR / "source_meta.json"

# ── 1차 소스: KBO_statics (KBO 공식 기록을 매일 수집해 커밋하는 공개 repo) ──
KBO_STATICS_REPO = "https://github.com/PsyproLEE/kbo_statics"
KBO_STATICS_DIR = RAW_DIR / "kbo_statics"

# ── 수집 범위 ────────────────────────────────────────────
YEAR_START = 2010
YEAR_END = 2026

# 카드 대상: YEAR_START~YEAR_END 1군 정규시즌 누적 출장 경기수.
# 타자는 타자 출장(G), 투수는 등판(G)으로 각각 판단.
MIN_CAREER_GAMES = 100
# 투수 보조 기준. 예: 300 → 누적 300이닝 이상이면 100경기 미만이어도 포함
# (1~2시즌만 뛴 외국인 선발 구제용). None이면 사용 안 함.
PITCHER_ALT_MIN_IP: float | None = None

# ── 보강 소스: 스탯티즈 (네트워크 허용 후 사용) ──────────────
STATIZ_BASE = "https://statiz.sporki.com"
REQUEST_INTERVAL_SEC = 3.0  # 개인용이라도 서버 부담 없게 넉넉히
REQUEST_TIMEOUT_SEC = 30
USER_AGENT = "Mozilla/5.0 (personal non-commercial KBO hobby project; low-rate)"

# ── 능력치 스케일 ────────────────────────────────────────
# 시즌별 리그 평균 = RATING_MEAN, 1 표준편차 = RATING_SD
RATING_MEAN = 50
RATING_SD = 15
RATING_MIN = 1
RATING_MAX = 99

# 시즌별 리그 평균/표준편차를 계산할 모집단 기준
POOL_MIN_PA = 100
POOL_MIN_TBF = 100

# 이 표본 미만이면 카드에 small_sample 표시
SMALL_SAMPLE_PA = 50
SMALL_SAMPLE_TBF = 50

# 작은 표본 보정 강도: rate = (x + k * 리그평균) / (n + k)
# 카드는 '그 시즌의 재현'이 목적이라 일부러 약하게 잡음 (튜닝 대상).
SHRINK_K = {
    # 타자
    "avg": 80,
    "so_pa": 60,
    "ubb_pa": 60,
    "hr_pa": 80,
    "iso": 80,
    "babip": 100,
    "spd": 50,
    "sb_att": 30,
    "sb_pct": 10,
    # 투수
    "p_so": 70,
    "p_bb": 100,
    "p_hr": 150,
    "p_babip": 100,
}
