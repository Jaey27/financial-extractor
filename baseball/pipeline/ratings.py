"""시즌 기록 → 능력치(1~99) + 엔진용 비율.

- 능력치: 같은 시즌 리그 대비 z-score를 RATING_MEAN ± RATING_SD 스케일로 변환.
  시즌 안에서만 비교하므로 타고투저·공인구 변화 같은 시대 효과가 빠짐 → 연도 짬뽕 모드가 공정해짐.
- 엔진용 비율(n_*): 같은 z를 '전 기간 평균 리그 환경'에 다시 입힌 값 (시대 중립 비율).
- 작은 표본: rate = (x + k*리그평균) / (n + k) 로 리그 평균 쪽으로 당김 (k는 config.SHRINK_K).
- 소스에 없는 기록(예: 은퇴 선수 도루)은 0이 아니라 결측으로 두고, 그 능력치는 None.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from . import config

Expr = Callable[[pd.DataFrame], pd.Series]
K = config.SHRINK_K


def col(df: pd.DataFrame, name: str) -> pd.Series:
    """컬럼 → float Series. 컬럼이 없으면 전부 결측."""
    if name not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[name], errors="coerce").astype(float)


def zcol(df: pd.DataFrame, name: str) -> pd.Series:
    """기록 안 됐으면 0으로 봐도 되는 보조 컬럼(IBB, HBP, SF, GDP 등)."""
    return col(df, name).fillna(0.0)


@dataclass(frozen=True)
class Metric:
    key: str
    num: Expr
    den: Expr
    k: float


def compute_metric(df: pd.DataFrame, m: Metric, pool: pd.Series, env: dict) -> None:
    """시즌별 리그 평균 대비 보정 비율(`{key}_rate`)과 z(`{key}_z`)를 df에 추가."""
    num = m.num(df).astype(float)
    den = m.den(df).astype(float).clip(lower=0)
    valid = num.notna() & den.notna()
    rate = pd.Series(np.nan, index=df.index)
    z = pd.Series(np.nan, index=df.index)
    for year, idx in df.groupby("year").groups.items():
        v, n, d = valid.loc[idx], num.loc[idx], den.loc[idx]
        p = v & pool.loc[idx] & (d > 0)
        if p.sum() < 5:  # 모집단이 너무 작으면 그 시즌 기록 있는 선수 전체로
            p = v & (d > 0)
        if p.sum() == 0:
            continue
        lg = n[p].sum() / d[p].sum()
        r = ((n + m.k * lg) / (d + m.k)).where(v)
        sd = float(r[p].std(ddof=0))
        rate.loc[idx] = r
        z.loc[idx] = (r - lg) / sd if sd > 1e-12 else (r - lg) * 0
        env.setdefault(int(year), {})[m.key] = {"mean": float(lg), "sd": sd}
    df[f"{m.key}_rate"] = rate
    df[f"{m.key}_z"] = z


def composite(df: pd.DataFrame, parts: dict[str, float], pool: pd.Series) -> pd.Series:
    """여러 z의 가중 평균을 시즌별로 다시 표준화. 결측 z는 빼고 가중치를 다시 나눔."""
    total = pd.Series(0.0, index=df.index)
    wsum = pd.Series(0.0, index=df.index)
    for key, w in parts.items():
        z = df[f"{key}_z"]
        total += (w * z).fillna(0.0)
        wsum += z.notna() * abs(w)
    c = (total / wsum).where(wsum > 0)
    out = pd.Series(np.nan, index=df.index)
    for _, idx in df.groupby("year").groups.items():
        ci = c.loc[idx]
        p = pool.loc[idx] & ci.notna()
        if p.sum() < 5:
            p = ci.notna()
        if p.sum() == 0:
            continue
        mean, sd = ci[p].mean(), ci[p].std(ddof=0)
        out.loc[idx] = (ci - mean) / sd if sd > 1e-12 else (ci - mean) * 0
    return out


def to_rating(z: pd.Series) -> pd.Series:
    r = (config.RATING_MEAN + config.RATING_SD * z).round()
    return r.clip(config.RATING_MIN, config.RATING_MAX).astype("Int64")


def add_neutral_rates(df: pd.DataFrame, keys: list[str], env: dict) -> dict:
    """z를 전 기간 평균 리그 환경(평균의 평균, 표준편차의 평균)에 입혀 `n_{key}` 추가."""
    ref = {}
    for key in keys:
        stats = [e[key] for e in env.values() if key in e]
        ref[key] = {
            "mean": float(np.mean([s["mean"] for s in stats])),
            "sd": float(np.mean([s["sd"] for s in stats])),
        }
        df[f"n_{key}"] = (ref[key]["mean"] + df[f"{key}_z"] * ref[key]["sd"]).clip(0, 1)
    return ref


# ── 타자 ─────────────────────────────────────────────────


def _singles(d):
    return col(d, "H") - col(d, "2B") - col(d, "3B") - col(d, "HR")


BATTER_METRICS = [
    Metric("avg", lambda d: col(d, "H"), lambda d: col(d, "AB"), K["avg"]),
    Metric("so", lambda d: col(d, "SO"), lambda d: col(d, "PA"), K["so_pa"]),
    Metric("ubb", lambda d: col(d, "BB") - zcol(d, "IBB"), lambda d: col(d, "PA"), K["ubb_pa"]),
    Metric("bb", lambda d: col(d, "BB") - zcol(d, "IBB") + zcol(d, "HBP"),
           lambda d: col(d, "PA"), K["ubb_pa"]),
    Metric("hr", lambda d: col(d, "HR"), lambda d: col(d, "PA"), K["hr_pa"]),
    Metric("iso", lambda d: col(d, "2B") + 2 * col(d, "3B") + 3 * col(d, "HR"),
           lambda d: col(d, "AB"), K["iso"]),
    Metric("babip", lambda d: col(d, "H") - col(d, "HR"),
           lambda d: col(d, "AB") - col(d, "SO") - col(d, "HR") + zcol(d, "SF"), K["babip"]),
    Metric("double_share", lambda d: col(d, "2B"), lambda d: col(d, "H") - col(d, "HR"), 30),
    Metric("triple_share", lambda d: col(d, "3B"), lambda d: col(d, "H") - col(d, "HR"), 30),
    Metric("t_rate", lambda d: col(d, "3B"),
           lambda d: col(d, "AB") - col(d, "SO") - col(d, "HR"), K["spd"]),
    Metric("run_rate", lambda d: (col(d, "R") - col(d, "HR")).clip(lower=0),
           lambda d: col(d, "H") + col(d, "BB") + zcol(d, "HBP") - col(d, "HR"), K["spd"]),
    Metric("gdp_rate", lambda d: col(d, "GDP"),
           lambda d: col(d, "AB") - col(d, "SO") - col(d, "HR"), K["spd"]),
    Metric("sb_att", lambda d: col(d, "SB") + col(d, "CS"),
           lambda d: _singles(d) + col(d, "BB") + zcol(d, "HBP"), K["sb_att"]),
    Metric("sb_pct", lambda d: col(d, "SB"), lambda d: col(d, "SB") + col(d, "CS"), K["sb_pct"]),
    # 득점 가치 근사(wOBA류). 시즌별 z로만 쓰므로 계수의 절대값보다 비율이 중요.
    Metric("woba", lambda d: 0.70 * (col(d, "BB") - zcol(d, "IBB")) + 0.72 * zcol(d, "HBP")
           + 0.90 * _singles(d) + 1.25 * col(d, "2B") + 1.60 * col(d, "3B") + 2.00 * col(d, "HR"),
           lambda d: col(d, "PA"), K["so_pa"]),
]

BATTER_NEUTRAL = ["so", "bb", "hr", "babip", "double_share", "triple_share", "sb_att", "sb_pct"]


def rate_batters(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = df.reset_index(drop=True)
    pool = col(df, "PA").fillna(0) >= config.POOL_MIN_PA
    env: dict = {}
    for m in BATTER_METRICS:
        compute_metric(df, m, pool, env)
    df["r_accuracy"] = to_rating(df["avg_z"])
    df["r_contact"] = to_rating(-df["so_z"])
    df["r_eye"] = to_rating(df["ubb_z"])
    df["r_power"] = to_rating(composite(df, {"hr": 0.6, "iso": 0.4}, pool))
    df["r_babip"] = to_rating(df["babip_z"])
    df["r_speed"] = to_rating(
        composite(df, {"t_rate": 1, "run_rate": 1, "gdp_rate": -1, "sb_att": 1}, pool))
    df["r_steal"] = to_rating(composite(df, {"sb_att": 1, "sb_pct": 1}, pool))
    df["r_ovr"] = to_rating(df["woba_z"])
    ref = add_neutral_rates(df, BATTER_NEUTRAL, env)
    return df, {"by_year": env, "reference": ref}


# ── 투수 ─────────────────────────────────────────────────


def tbf(d: pd.DataFrame) -> pd.Series:
    """상대 타자 수. 없으면 아웃카운트+피안타+볼넷+사구로 추정."""
    est = col(d, "IP_outs") + col(d, "H") + col(d, "BB") + zcol(d, "HBP")
    return col(d, "TBF").fillna(est)


PITCHER_METRICS = [
    Metric("so", lambda d: col(d, "SO"), tbf, K["p_so"]),
    Metric("bb", lambda d: col(d, "BB") - zcol(d, "IBB") + zcol(d, "HBP"), tbf, K["p_bb"]),
    Metric("hr", lambda d: col(d, "HR"), tbf, K["p_hr"]),
    Metric("babip", lambda d: col(d, "H") - col(d, "HR"),
           lambda d: tbf(d) - col(d, "SO") - col(d, "BB") - zcol(d, "HBP") - col(d, "HR"),
           K["p_babip"]),
    # FIP류: 수비와 무관한 결과(HR, 볼넷·사구, 삼진)만으로 본 실점 억제력
    Metric("fip", lambda d: 13 * col(d, "HR")
           + 3 * (col(d, "BB") - zcol(d, "IBB") + zcol(d, "HBP")) - 2 * col(d, "SO"),
           tbf, K["p_bb"]),
]

PITCHER_NEUTRAL = ["so", "bb", "hr", "babip"]

# 선발 판정: 경기당 투구수가 이 이상이면 선발 (GS 기록이 소스에 없어서 추정)
STARTER_MIN_NP_PER_G = 50
STARTER_MIN_OUTS_PER_G = 9  # 투구수도 없을 때


def rate_pitchers(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = df.reset_index(drop=True)
    pool = tbf(df).fillna(0) >= config.POOL_MIN_TBF
    env: dict = {}
    for m in PITCHER_METRICS:
        compute_metric(df, m, pool, env)
    df["r_stuff"] = to_rating(df["so_z"])
    df["r_control"] = to_rating(-df["bb_z"])
    df["r_movement"] = to_rating(-df["hr_z"])
    df["r_hit_suppression"] = to_rating(-df["babip_z"])
    df["r_ovr"] = to_rating(composite(df, {"fip": -0.75, "babip": -0.25}, pool))

    games = col(df, "G").where(col(df, "G") > 0)
    np_per_g = col(df, "NP") / games
    outs_per_g = col(df, "IP_outs") / games
    # 체력: 경기당 투구수 기준 절대 스케일 (선발 90~100구 ≈ 90~99, 1이닝 불펜 ≈ 20)
    stamina = (np_per_g * 0.95 + 5).fillna(outs_per_g * 5.0 + 5)
    df["r_stamina"] = stamina.round().clip(20, config.RATING_MAX).astype("Int64")
    df["np_per_g"] = np_per_g
    df["outs_per_g"] = outs_per_g
    starter = (np_per_g >= STARTER_MIN_NP_PER_G).where(np_per_g.notna(),
                                                       outs_per_g >= STARTER_MIN_OUTS_PER_G)
    closer = zcol(df, "SV") >= 10
    df["role"] = np.where(starter.fillna(False), "SP", np.where(closer, "CL", "RP"))
    ref = add_neutral_rates(df, PITCHER_NEUTRAL, env)
    return df, {"by_year": env, "reference": ref}
