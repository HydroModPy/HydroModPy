"""Bridge from data-manager LoadResult to flow recharge configuration.

Converts recharge/runoff LoadResult objects into FlowRechargeConfig-compatible
payloads, handling unit conversion (mm/day -> m/s) and stress-period alignment.

Heterogeneous (per-cell) grid data is NOT handled here; it requires the
MODFLOW grid definition and is deferred to the solver adapter layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from hydromodpy.data_managers.contracts.load_result import LoadResult
from hydromodpy.forcing.recharge_chronicle import (
    align_forcing_series_to_simulation_window,
)

if TYPE_CHECKING:
    from hydromodpy.simulation.time import ResolvedSimulationTimeWindow


# mm/day -> m/s
_MM_PER_DAY_TO_M_PER_S = 1.0 / (1000.0 * 86400.0)


def extract_homogeneous_series(result: LoadResult) -> pd.Series | None:
    """Extract a single homogeneous time series from a LoadResult.

    For point data, if multiple stations are present, their mean is used.
    The returned series is in the data-manager internal unit (mm/day).

    Returns None if no suitable point data is available.
    """
    if not result.has_points:
        return None

    series_list: list[pd.Series] = []
    for rec in result.points:
        if rec.data is None or rec.data.empty:
            continue
        s = rec.data.set_index("datetime")["value"].sort_index()
        series_list.append(s)

    if not series_list:
        return None

    if len(series_list) == 1:
        return series_list[0]

    # Multiple stations: combine and average
    combined = pd.concat(series_list, axis=1)
    return combined.mean(axis=1)


def build_recharge_series(
    recharge_result: LoadResult,
    *,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
) -> pd.Series | None:
    """Build flow-ready recharge values from a LoadResult.

    Extracts homogeneous point data, converts mm/day -> m/s, and aligns
    to simulation stress periods if a window is provided.

    Returns None if no homogeneous point data is available (e.g. only
    grid data, which requires heterogeneous processing by the adapter).
    """
    series = extract_homogeneous_series(recharge_result)
    if series is None:
        return None

    series_ms = series * _MM_PER_DAY_TO_M_PER_S

    if simulation_window is not None:
        series_ms = align_forcing_series_to_simulation_window(
            series_ms,
            simulation_window=simulation_window,
            label="recharge (data-manager)",
        )

    return series_ms


def build_runoff_series(
    runoff_result: LoadResult,
    *,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
) -> pd.Series | None:
    """Build flow-ready runoff values from a LoadResult.

    Same logic as recharge but for runoff.
    """
    series = extract_homogeneous_series(runoff_result)
    if series is None:
        return None

    series_ms = series * _MM_PER_DAY_TO_M_PER_S

    if simulation_window is not None:
        series_ms = align_forcing_series_to_simulation_window(
            series_ms,
            simulation_window=simulation_window,
            label="runoff (data-manager)",
        )

    return series_ms
