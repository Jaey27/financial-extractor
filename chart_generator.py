"""matplotlib 차트 생성 모듈.

기본 포맷 규칙 (유저 별도 요청 없으면 적용):
- 숫자($m 등) → 묶은 세로 막대 (bar)
- % 데이터 → 꺾은선 (line), 데이터 라벨에 % 표시
- 숫자 + % 혼합 또는 같은 단위라도 값 차이 2배 이상 → 보조축 사용
- 데이터 라벨 항상 표시
- 색상 순서: 빨강 → 파랑 → 노랑 → 초록 → 검정
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# --- 색상 팔레트 ---
BAR_COLORS = ["#C0504D", "#4472C4", "#E2C541", "#70AD47", "#2D2D2D"]
LINE_COLORS = ["#4472C4", "#C0504D", "#E2C541", "#70AD47", "#2D2D2D"]


def _get_color(idx: int, palette: list[str]) -> str:
    if idx < len(palette):
        return palette[idx]
    cmap = plt.cm.get_cmap("tab10")
    return matplotlib.colors.rgb2hex(cmap(idx % 10))


def _apply_style(ax: plt.Axes) -> None:
    """주축 스타일: 흰 배경, 최소 그리드."""
    ax.set_facecolor("white")
    ax.figure.set_facecolor("white")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#CCCCCC")
    ax.spines["bottom"].set_color("#CCCCCC")
    ax.tick_params(colors="#666666", labelsize=9)
    ax.grid(axis="y", color="#EEEEEE", linewidth=0.5)
    ax.set_axisbelow(True)


def _apply_style_secondary(ax2: plt.Axes) -> None:
    """보조축 스타일."""
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color("#CCCCCC")
    ax2.spines["bottom"].set_color("#CCCCCC")
    ax2.tick_params(colors="#666666", labelsize=9)


def _format_label(value: float | None, unit: str) -> str:
    """데이터 라벨 포맷. % → 소수점 첫째 + %, $m → 천단위 콤마."""
    if value is None:
        return ""
    if unit == "%":
        return f"{value:.1f}%"
    elif unit == "$m":
        if abs(value) >= 1000:
            return f"{value:,.0f}"
        return f"{value:,.1f}"
    elif unit == "x":
        return f"{value:.1f}x"
    else:
        if abs(value) >= 1000:
            return f"{value:,.0f}"
        elif value == int(value):
            return f"{int(value)}"
        return f"{value:.1f}"


def _sanitize_filename(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    text = text.replace(" ", "_")
    text = re.sub(r'_+', '_', text)
    return text.strip("_")


def _classify_series(series_list: list[dict], global_unit: str) -> tuple[list, list]:
    """시리즈를 bar vs line으로 분류.

    규칙 우선순위:
    1) render_type 명시 → 그대로
    2) unit이 "%" 또는 이름에 margin/ratio/% chg → line
    3) 나머지 → bar
    4) 안전장치: 한쪽에만 몰렸는데 값 스케일 10배+ 차이 → 큰 값=bar, 작은 값=line
    """
    bar_series = []
    line_series = []

    for i, s in enumerate(series_list):
        unit = s.get("unit", global_unit)
        render = s.get("render_type", s.get("render_as", ""))
        name_lower = s.get("name", "").lower()

        if render == "bar":
            bar_series.append((i, s, unit))
        elif render == "line":
            line_series.append((i, s, unit))
        elif unit == "%" or "margin" in name_lower or "ratio" in name_lower or "%" in s.get("name", ""):
            line_series.append((i, s, unit))
        else:
            bar_series.append((i, s, unit))

    # --- 안전장치: 한쪽에만 몰렸는데 값 스케일이 크게 다르면 재분류 ---
    only_bucket = None
    if line_series and not bar_series and len(line_series) >= 2:
        only_bucket = line_series
    elif bar_series and not line_series and len(bar_series) >= 2:
        only_bucket = bar_series

    if only_bucket:
        maxes = []
        for _, s, _ in only_bucket:
            vals = [abs(v) for v in s.get("values", []) if v is not None]
            maxes.append(max(vals) if vals else 0)

        positive_maxes = [v for v in maxes if v > 0]
        if len(positive_maxes) >= 2:
            biggest = max(positive_maxes)
            smallest = min(positive_maxes)
            if smallest > 0 and biggest / smallest >= 10:
                # 큰 값 → bar, 작은 값 → line
                threshold = (biggest * smallest) ** 0.5  # 기하평균
                new_bar, new_line = [], []
                for item, mx in zip(only_bucket, maxes):
                    if mx >= threshold:
                        new_bar.append(item)
                    else:
                        new_line.append(item)
                if new_bar and new_line:
                    return new_bar, new_line

    return bar_series, line_series


def _needs_secondary_axis(bar_series: list, line_series: list) -> bool:
    """보조축 필요 여부. 단위가 다르거나 값 차이 2배 이상."""
    if not bar_series or not line_series:
        return False

    bar_units = {u for _, _, u in bar_series}
    line_units = {u for _, _, u in line_series}

    # 단위가 다르면 보조축
    if bar_units != line_units:
        return True

    # 같은 단위라도 값 범위 차이 2배 이상
    bar_maxes = []
    for _, s, _ in bar_series:
        vals = [v for v in s.get("values", []) if v is not None]
        if vals:
            bar_maxes.append(max(abs(v) for v in vals))

    line_maxes = []
    for _, s, _ in line_series:
        vals = [v for v in s.get("values", []) if v is not None]
        if vals:
            line_maxes.append(max(abs(v) for v in vals))

    if bar_maxes and line_maxes:
        big = max(max(bar_maxes), max(line_maxes))
        small = min(min(bar_maxes), min(line_maxes))
        if small > 0 and big / small >= 2:
            return True

    return False


# === 메인 진입점 ===

def generate_chart(data: dict, output_dir: Path | None = None) -> tuple[bytes, str]:
    """데이터 JSON → 차트 PNG 생성."""
    chart_type = data.get("chart_type", "combo")
    series_list = data.get("series", [])
    global_unit = data.get("unit", "")

    # 자동 감지: 단위 혼합이면 combo, 모두 %면 line, 모두 $m이면 bar
    if chart_type not in ("stacked_bar",):
        bar_s, line_s = _classify_series(series_list, global_unit)
        if bar_s and line_s:
            chart_type = "combo"
        elif line_s and not bar_s:
            chart_type = "line"
        elif bar_s and not line_s:
            chart_type = "bar"

    if chart_type == "combo":
        png_bytes = _combo_chart(data)
    elif chart_type == "line":
        png_bytes = _line_chart(data)
    elif chart_type == "bar":
        png_bytes = _bar_chart(data)
    elif chart_type == "stacked_bar":
        png_bytes = _stacked_bar_chart(data)
    else:
        png_bytes = _combo_chart(data)

    # 파일명: 날짜_티커_내용.png
    company = _sanitize_filename(data.get("company", "Unknown"))
    title_clean = _sanitize_filename(data.get("title", "chart"))
    today = date.today().strftime("%Y-%m-%d")
    filename = f"{today}_{company}_{title_clean}.png"

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / filename).write_bytes(png_bytes)

    return png_bytes, filename


# === 콤보 차트 (핵심: 막대 + 꺾은선 + 보조축) ===

def _combo_chart(data: dict) -> bytes:
    periods = data.get("periods", [])
    series_list = data.get("series", [])
    global_unit = data.get("unit", "")
    title = data.get("title", "")
    company = data.get("company", "")

    bar_series, line_series = _classify_series(series_list, global_unit)

    # 예외: 한쪽만 있으면 해당 차트로
    if not bar_series and line_series:
        return _line_chart(data)
    if bar_series and not line_series:
        return _bar_chart(data)

    use_secondary = _needs_secondary_axis(bar_series, line_series)

    n = len(periods)
    fig_width = max(12, n * 0.8)
    fig, ax1 = plt.subplots(figsize=(fig_width, 5.5))
    _apply_style(ax1)
    x = np.arange(n)

    legend_handles = []
    legend_labels = []

    # --- 막대 (왼쪽 축) ---
    n_bars = len(bar_series)
    bar_width = 0.55 / max(n_bars, 1)

    for bi, (orig_idx, s, unit) in enumerate(bar_series):
        values = s.get("values", [])
        name = s.get("name", f"Bar {bi+1}")
        color = _get_color(bi, BAR_COLORS)
        offset = (bi - n_bars / 2 + 0.5) * bar_width

        y = [v if v is not None else 0 for v in values]
        bars = ax1.bar(x + offset, y, bar_width, color=color, zorder=2)
        legend_handles.append(bars)
        legend_labels.append(f"{name} ({unit})")

        # 라벨: 막대 위
        for bar_obj, val in zip(bars, values):
            if val is not None:
                ax1.text(
                    bar_obj.get_x() + bar_obj.get_width() / 2,
                    bar_obj.get_height(),
                    _format_label(val, unit),
                    ha="center", va="bottom", fontsize=7.5,
                    color="#333333", fontweight="medium",
                )

    # 왼쪽 Y축 여유
    bar_vals = []
    for _, s, _ in bar_series:
        bar_vals.extend([v for v in s.get("values", []) if v is not None])
    if bar_vals:
        ax1.set_ylim(0, max(bar_vals) * 1.2)

    # --- 꺾은선 (오른쪽 축 또는 같은 축) ---
    ax_line = ax1.twinx() if use_secondary else ax1
    if use_secondary:
        _apply_style_secondary(ax_line)

    for li, (orig_idx, s, unit) in enumerate(line_series):
        values = s.get("values", [])
        name = s.get("name", f"Line {li+1}")
        color = _get_color(li, LINE_COLORS)

        y = [v if v is not None else np.nan for v in values]
        line, = ax_line.plot(
            x[:len(y)], y, color=color, linewidth=2.5,
            marker="o", markersize=5, zorder=4,
        )
        legend_handles.append(line)
        legend_labels.append(f"{name} ({unit})")

        # 라벨: 포인트 위
        for j, val in enumerate(y):
            if val is not None and not np.isnan(val):
                ax_line.annotate(
                    _format_label(val, unit),
                    (j, val),
                    textcoords="offset points",
                    xytext=(0, 10),
                    ha="center", va="bottom",
                    fontsize=7.5, color=color, fontweight="bold",
                )

    # 보조축 포맷
    if use_secondary and line_series:
        line_unit = line_series[0][2]
        line_vals = []
        for _, s, _ in line_series:
            line_vals.extend([v for v in s.get("values", []) if v is not None])
        if line_vals:
            y_min = min(line_vals)
            y_max = max(line_vals)
            margin = (y_max - y_min) * 0.35
            ax_line.set_ylim(max(0, y_min - margin), y_max + margin)
        if line_unit == "%":
            ax_line.yaxis.set_major_formatter(
                mticker.FuncFormatter(lambda v, pos: f"{v:.1f}%")
            )

    # X축, 제목
    ax1.set_xticks(x)
    ax1.set_xticklabels(periods, fontsize=9)
    ax1.set_title(f"[{company}] {title}", fontsize=13, fontweight="bold",
                  pad=15, color="#333333")

    # 범례 하단 중앙
    fig.legend(
        legend_handles, legend_labels,
        loc="lower center", bbox_to_anchor=(0.5, -0.02),
        ncol=len(legend_handles), fontsize=8.5, frameon=False,
    )

    plt.tight_layout()
    fig.subplots_adjust(bottom=0.13)
    return _fig_to_bytes(fig)


# === 꺾은선 차트 (모든 시리즈가 % 등 동일 단위) ===

def _line_chart(data: dict) -> bytes:
    periods = data.get("periods", [])
    series_list = data.get("series", [])
    global_unit = data.get("unit", "")
    title = data.get("title", "")
    company = data.get("company", "")

    n = len(periods)
    fig_width = max(12, n * 0.65)
    fig, ax = plt.subplots(figsize=(fig_width, 5))
    _apply_style(ax)
    x = np.arange(n)

    for i, s in enumerate(series_list):
        values = s.get("values", [])
        name = s.get("name", f"Series {i+1}")
        unit = s.get("unit", global_unit)
        color = _get_color(i, LINE_COLORS)

        y = [v if v is not None else np.nan for v in values]
        ax.plot(x[:len(y)], y, color=color, linewidth=2.5,
                marker="o", markersize=5, label=name, zorder=3)

        for j, val in enumerate(y):
            if val is not None and not np.isnan(val):
                offset_y = 10 if i % 2 == 0 else -14
                va = "bottom" if i % 2 == 0 else "top"
                ax.annotate(
                    _format_label(val, unit),
                    (j, val),
                    textcoords="offset points",
                    xytext=(0, offset_y),
                    ha="center", va=va,
                    fontsize=7.5, color=color, fontweight="medium",
                )

    ax.set_xticks(x)
    ax.set_xticklabels(periods, fontsize=9)
    ax.set_title(f"[{company}] {title}", fontsize=13, fontweight="bold",
                 pad=15, color="#333333")

    if len(series_list) > 1:
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.12),
                  ncol=len(series_list), fontsize=8.5, frameon=False)

    plt.tight_layout()
    fig.subplots_adjust(bottom=0.10)
    return _fig_to_bytes(fig)


# === 묶은 막대 차트 (모든 시리즈가 $m 등 동일 단위) ===

def _bar_chart(data: dict) -> bytes:
    periods = data.get("periods", [])
    series_list = data.get("series", [])
    global_unit = data.get("unit", "")
    title = data.get("title", "")
    company = data.get("company", "")

    n = len(periods)
    n_series = len(series_list)
    fig_width = max(12, n * 0.8)
    fig, ax = plt.subplots(figsize=(fig_width, 5))
    _apply_style(ax)
    x = np.arange(n)
    width = 0.7 / max(n_series, 1)

    for i, s in enumerate(series_list):
        values = s.get("values", [])
        name = s.get("name", f"Series {i+1}")
        unit = s.get("unit", global_unit)
        color = _get_color(i, BAR_COLORS)
        offset = (i - n_series / 2 + 0.5) * width

        y = [v if v is not None else 0 for v in values]
        bars = ax.bar(x + offset, y, width, label=name, color=color, zorder=3)

        for bar_obj, val in zip(bars, values):
            if val is not None:
                ax.text(
                    bar_obj.get_x() + bar_obj.get_width() / 2,
                    bar_obj.get_height(),
                    _format_label(val, unit),
                    ha="center", va="bottom", fontsize=7.5,
                    color="#333333", fontweight="medium",
                )

    all_vals = []
    for s in series_list:
        all_vals.extend([v for v in s.get("values", []) if v is not None])
    if all_vals:
        ax.set_ylim(0, max(all_vals) * 1.15)

    ax.set_xticks(x)
    ax.set_xticklabels(periods, fontsize=9)
    ax.set_title(f"[{company}] {title}", fontsize=13, fontweight="bold",
                 pad=15, color="#333333")

    if n_series > 1:
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.12),
                  ncol=n_series, fontsize=8.5, frameon=False)

    plt.tight_layout()
    fig.subplots_adjust(bottom=0.10)
    return _fig_to_bytes(fig)


# === 누적 막대 차트 ===

def _stacked_bar_chart(data: dict) -> bytes:
    periods = data.get("periods", [])
    series_list = data.get("series", [])
    global_unit = data.get("unit", "")
    title = data.get("title", "")
    company = data.get("company", "")

    n = len(periods)
    fig_width = max(12, n * 0.7)
    fig, ax = plt.subplots(figsize=(fig_width, 5))
    _apply_style(ax)
    x = np.arange(n)
    bottom = np.zeros(n)

    for i, s in enumerate(series_list):
        values = np.array(s.get("values", []), dtype=float)
        name = s.get("name", f"Series {i+1}")
        unit = s.get("unit", global_unit)
        color = _get_color(i, BAR_COLORS)

        ax.bar(x, values, 0.6, bottom=bottom, label=name, color=color, zorder=3)

        for j, val in enumerate(values):
            if val > 0:
                ax.text(j, bottom[j] + val / 2,
                        _format_label(val, unit),
                        ha="center", va="center", fontsize=7,
                        color="white", fontweight="bold")
        bottom += values

    ax.set_xticks(x)
    ax.set_xticklabels(periods, fontsize=9)
    ax.set_title(f"[{company}] {title}", fontsize=13, fontweight="bold",
                 pad=15, color="#333333")

    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.12),
              ncol=min(len(series_list), 5), fontsize=8.5, frameon=False)

    plt.tight_layout()
    fig.subplots_adjust(bottom=0.10)
    return _fig_to_bytes(fig)


def _fig_to_bytes(fig: plt.Figure) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
