"""원본 팀 표기 ↔ 프랜차이즈 id 매핑 (data/franchises.json)."""

from __future__ import annotations

import json
import math
from pathlib import Path

from . import config


def load_franchises(path: Path = config.FRANCHISES_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["franchises"]


def franchise_for(team, franchises: list[dict]) -> str | None:
    """'KIA', '15KIA', '넥센' 같은 원본 팀 표기 → franchise id. 못 찾으면 None.

    표기 안에 별칭이 포함돼 있으면 매칭하고, 여러 개 걸리면 가장 긴 별칭을 택함.
    한 행에 두 팀이 섞인 표기('삼성/LG')는 구분 못 하므로 수집 단계에서 팀별 행으로 둘 것.
    """
    if team is None or (isinstance(team, float) and math.isnan(team)):
        return None
    text = str(team).upper().replace(" ", "")
    best: tuple[int, str] | None = None
    for fr in franchises:
        for alias in fr["real_names"]:
            a = alias.upper()
            if a in text and (best is None or len(a) > best[0]):
                best = (len(a), fr["id"])
    return best[1] if best else None
