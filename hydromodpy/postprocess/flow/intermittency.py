"""Intermittency indicators from accumulation-flux grids.

This module transforms raw `accumulation_flux` sequences into three percent
indicators written in a timeseries frame:

- `total_areas`: cells showing any surface-flow signal,
- `perenn_areas`: cells active for all time slices in the window,
- `intermit_areas`: cells active only part of the window.

Supported modes map to a fixed temporal window size:
- yearly: 1 slice,
- monthly: 12 slices,
- weekly: 52 slices,
- daily: 365 slices.

Example
-------
Given monthly slices over one year:
- a cell active in all 12 slices contributes to `perenn_areas`,
- a cell active in 3/12 slices contributes to `intermit_areas`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.support.tools import get_logger

logger = get_logger(__name__)

_WINDOWS_BY_MODE: dict[str, int] = {
    "yearly": 1,
    "monthly": 12,
    "weekly": 52,
    "daily": 365,
}


def _ordered_flux_items(accumulation_flux: Any) -> list[tuple[Any, Any]]:
    """Return accumulation-flux entries in a deterministic order.

    Examples
    --------
    Mapping input:
    `{3: arr_c, 1: arr_a, 2: arr_b}` -> `[(1, arr_a), (2, arr_b), (3, arr_c)]`

    Sequence input:
    `[arr_0, arr_1]` -> `[(0, arr_0), (1, arr_1)]`
    """

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
    """Compute intermittency rows for one temporal aggregation mode.

    Parameters
    ----------
    accumulation_flux : Any
        Flux payload (mapping keyed by timestep or plain sequence).
    dem_clip : np.ndarray
        DEM support used as spatial validity mask (`dem_clip < 0` excluded).
    cell_count : int
        Number of valid cells used for percent normalization.
    mode_name : str
        Human-readable mode label used in debug logs.
    window_size : int
        Number of slices per aggregation window.

    Returns
    -------
    list[tuple[float, float, float]]
        One tuple per processed slice:
        `(total_areas, perenn_areas, intermit_areas)`, in percent.

    Illustration
    ------------
    For one window of 12 slices:
    - if `days_flux == 12` for a cell => perennial,
    - if `1 <= days_flux < 12` => intermittent,
    - if `days_flux == 0` => excluded from active-flow indicators.
    """

    items = _ordered_flux_items(accumulation_flux)
    if not items or window_size <= 0 or len(items) < window_size or cell_count <= 0:
        return []

    rows: list[tuple[float, float, float]] = []
    inf = 0
    sup = window_size
    # Number of full windows processed for the selected mode.
    step = int(round(len(items) / window_size))

    for i in range(step):
        logger.debug("Computing %s intermittency: %d / %d", mode_name, i, step)
        interval = items[inf:sup]
        if not interval:
            break

        # `dem_clip < 0` is treated as spatial nodata/masked support.
        mask = dem_clip.copy()
        masked_interval = [
            np.ma.masked_array(interval_item[1], mask=(mask < 0))
            for interval_item in interval
        ]

        # Count active days/slices per cell in the current window.
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

    Example
    -------
    ```python
    frame = apply_intermittency_columns(
        frame,
        accumulation_flux=acc_flux,
        dem_clip=dem,
        cell_count=1200,
        monthly=True,
    )
    ```
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
