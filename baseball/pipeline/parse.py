"""소스 공통 파싱 유틸."""

from __future__ import annotations

import math
import re

_IP_FRAC = {"⅓": 1, "⅔": 2, "1/3": 1, "2/3": 2}


def to_num(value) -> float | None:
    """'1,234' / '0.350' / '-' / '' → float 또는 None."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    s = str(value).strip().replace(",", "")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_ip_outs(value) -> int | None:
    """이닝 표기 → 아웃카운트. '192 2/3', '123.1', '123⅓', '⅔' 모두 처리."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    s = str(value).strip().replace(",", "")
    m = re.fullmatch(r"(\d*)\s*(⅓|⅔|1/3|2/3)?", s)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 3 + _IP_FRAC.get(m.group(2) or "", 0)
    m = re.fullmatch(r"(\d+)\.([012])0*", s)
    if m:
        return int(m.group(1)) * 3 + int(m.group(2))
    return None


def format_ip(outs) -> str | None:
    """아웃카운트 → '192 2/3' 표기."""
    if outs is None or (isinstance(outs, float) and math.isnan(outs)):
        return None
    whole, frac = divmod(int(outs), 3)
    return f"{whole} {frac}/3" if frac else str(whole)
