"""Intermittency metrics for flow/timeseries postprocess outputs.

This module computes perennial/intermittent area indicators from
``accumulation_flux`` grids over configurable temporal windows.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.tools import get_logger

logger = get_logger(__name__)

_WINDOWS_BY_MODE: dict[str, int] = {
    "yearly": 1,
    "monthly": 12,
    "weekly": 52,
    "daily": 365,
}


def _ordered_flux_items(accumulation_flux: Any) -> list[tuple[Any, Any]]:
    """Return accumulation-flux entries in a deterministic order."""

    if isinstance(accumulation_flux, Mapping):
        items = list(accumulation_flux.items())
        try:
            return sorted(items, key=lambda item: item[0])
        except Exception:
            return items

    try:
        return list(enumerate(accumulation_flux))
    except Exception:
        return []


def _compute_mode_rows(
    accumulation_flux: Any,
    dem_clip: np.ndarray,
    cell_count: int,
    mode_name: str,
    window_size: int,
) -> list[tuple[float, float, float]]:
    """Compute intermittency rows for one temporal aggregation mode."""

    items = _ordered_flux_items(accumulation_flux)
    if not items or window_size <= 0 or len(items) < window_size or cell_count <= 0:
        return []

    rows: list[tuple[float, float, float]] = []
    inf = 0
    sup = window_size
    step = int(round(len(items) / window_size))

    for i in range(step):
        logger.debug("Computing %s intermittency: %d / %d", mode_name, i, step)
        interval = items[inf:sup]
        if not interval:
            break

        mask = dem_clip.copy()
        masked_interval = [
            np.ma.masked_array(interval_item[1], mask=(mask < 0))
            for interval_item in interval
        ]

        zero = masked_interval[0] * 0
        for grid in masked_interval:
            tempo = grid.copy()
            tempo[tempo > 0] = 1
            zero = zero + tempo

        days_flux = np.ma.masked_array(zero.copy(), mask=(mask < 0))
        days_flux = np.ma.masked_array(days_flux, mask=(days_flux <= 0))

        for grid in masked_interval:
            tempo = np.ma.masked_where(grid <= 0, grid)
            tempo[days_flux < window_size] = 0
            tempo[days_flux == window_size] = 1
            tempo = np.ma.masked_where(grid <= 0, tempo)

            surflow = (((tempo >= 0).sum()) / cell_count) * 100
            perenn = (((tempo == 1).sum()) / cell_count) * 100
            intermit = (((tempo == 0).sum()) / cell_count) * 100

            rows.append((float(surflow), float(perenn), float(intermit)))

        inf += window_size
        sup += window_size

    return rows


def apply_intermittency_columns(
    frame: pd.DataFrame,
    *,
    accumulation_flux: Any,
    dem_clip: np.ndarray,
    cell_count: int,
    yearly: bool = False,
    monthly: bool = False,
    weekly: bool = False,
    daily: bool = False,
) -> pd.DataFrame:
    """Populate intermittency columns in ``frame`` for enabled modes.

    The function keeps the legacy write pattern: each mode writes from row ``0``
    onward, so enabling several modes in one call means the last enabled mode
    wins for overlapping rows.
    """

    enabled_modes = (
        ("yearly", yearly),
        ("monthly", monthly),
        ("weekly", weekly),
        ("daily", daily),
    )

    for mode_name, enabled in enabled_modes:
        if not enabled:
            continue

        rows = _compute_mode_rows(
            accumulation_flux=accumulation_flux,
            dem_clip=dem_clip,
            cell_count=cell_count,
            mode_name=mode_name,
            window_size=_WINDOWS_BY_MODE[mode_name],
        )
        for index, (total, perenn, intermit) in enumerate(rows):
            frame.loc[index, "total_areas"] = total
            frame.loc[index, "perenn_areas"] = perenn
            frame.loc[index, "intermit_areas"] = intermit

    return frame


__all__ = [
    "apply_intermittency_columns",
]
