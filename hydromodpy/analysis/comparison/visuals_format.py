"""Time tick formatting helpers for comparison visuals."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from hydromodpy.analysis.comparison.visuals_style import _TICK_FONT_SIZE


def _format_time_tick_label(label: str) -> str:
    text = str(label).strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        if re.fullmatch(r"\d+", text):
            return text
        return text[:7] if len(text) >= 7 and text[4:5] == "-" else text
    return parsed.strftime("%b")


def _apply_time_ticks(
    ax: Any,
    *,
    tick_positions: list[float],
    tick_labels: list[str] | None = None,
) -> None:
    if not tick_positions:
        return
    unique_positions = sorted({float(value) for value in tick_positions})
    if len(unique_positions) <= 8:
        step = 1
    elif len(unique_positions) <= 16:
        step = 2
    else:
        step = max(1, int(math.ceil(len(unique_positions) / 6.0)))
    shown_positions = unique_positions[::step]
    if unique_positions[-1] not in shown_positions:
        shown_positions.append(unique_positions[-1])
    shown_labels: list[str] = []
    if tick_labels is None:
        shown_labels = [
            str(int(value)) if float(value).is_integer() else f"{value:g}"
            for value in shown_positions
        ]
    else:
        label_lookup = {
            float(position): _format_time_tick_label(label)
            for position, label in zip(tick_positions, tick_labels, strict=False)
        }
        shown_labels = [
            label_lookup.get(float(value), str(int(value))) for value in shown_positions
        ]
    ax.set_xticks(shown_positions)
    ax.set_xticklabels(shown_labels, fontsize=_TICK_FONT_SIZE)
