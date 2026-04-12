"""Generic bridge from data-manager LoadResult to solver-ready forcing.

Works with ANY climatic variable (recharge, precipitation, ETP, temperature,
wind, humidity, radiation, soil_moisture, runoff).  Handles:

- Homogeneous series extraction (station average, or spatial mean of fields)
- Unit conversion (parameterized factor)
- Simulation-window alignment (stress-period aggregation)
- Spatial-mode dispatch (auto / homogeneous / heterogeneous)

The output is a :class:`ResolvedForcing` that downstream binders and solver
adapters consume without knowing which variable it came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import pandas as pd

if TYPE_CHECKING:
    from hydromodpy.data.contracts.load_result import LoadResult
    from hydromodpy.core.time import ResolvedSimulationTimeWindow

SpatialMode = Literal["auto", "homogeneous", "heterogeneous"]
InterpolationMethod = Literal["nearest", "linear", "idw"]

# ── Result container ──────────────────────────────────────────


@dataclass
class ResolvedForcing:
    """Solver-ready forcing resolved from a data-manager LoadResult.

    Attributes
    ----------
    series : pd.Series or None
        Homogeneous time series in **solver units** (e.g. m/s for fluxes,
        °C for temperature).  None when only heterogeneous data is available.
    heterogeneous_source : LoadResult or None
        Original LoadResult to be discretized per-cell by the solver adapter.
        Set when spatial_mode requires 2-D arrays.
    spatial_mode : str
        The mode that was actually applied.
    interpolation_method : str
        Interpolation method to pass to the discretizer.
    """

    series: pd.Series | None
    heterogeneous_source: "LoadResult | None"
    spatial_mode: str
    interpolation_method: str


# ── Homogeneous extraction (variable-agnostic) ───────────────


def extract_homogeneous_series(result: "LoadResult") -> pd.Series | None:
    """Extract a single time series from point records.

    If multiple stations are present, returns the arithmetic mean.
    The returned series is in the **data-manager internal unit**.
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

    combined = pd.concat(series_list, axis=1)
    return combined.mean(axis=1)


def extract_homogeneous_series_from_fields(result: "LoadResult") -> pd.Series | None:
    """Compute the spatial mean of FieldRecords.

    Reduces gridded data (TIF, NC, xarray) to one scalar per time step
    by averaging all spatial cells.  Returns a Series in the data-manager
    internal unit, or None.
    """
    from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_field_discretization import (
        spatial_mean_from_fields,
    )

    return spatial_mean_from_fields(result)


# ── Series builder (generic) ─────────────────────────────────


def build_forcing_series(
    load_result: "LoadResult",
    *,
    unit_conversion_factor: float = 1.0,
    simulation_window: "ResolvedSimulationTimeWindow | None" = None,
    force_homogeneous: bool = False,
    label: str = "forcing",
) -> pd.Series | None:
    """Build a homogeneous solver-ready time series from a LoadResult.

    Parameters
    ----------
    load_result :
        Data from any variable manager.
    unit_conversion_factor :
        Multiplicative factor from data-manager internal unit to solver unit.
        E.g. ``1 / (1000 * 86400)`` for mm/day → m/s.  Default ``1.0`` (no conversion).
    simulation_window :
        If provided, the series is aggregated to stress periods.
    force_homogeneous :
        When True and no point data exists, fall back to spatial-mean of fields.
    label :
        Human-readable label for error messages.
    """
    series = extract_homogeneous_series(load_result)

    if series is None and force_homogeneous:
        series = extract_homogeneous_series_from_fields(load_result)

    if series is None:
        return None

    if unit_conversion_factor != 1.0:
        series = series * unit_conversion_factor

    if simulation_window is not None:
        from hydromodpy.process.forcing.time_alignment import (
            align_forcing_series_to_simulation_window,
        )

        series = align_forcing_series_to_simulation_window(
            series,
            simulation_window=simulation_window,
            label=label,
        )

    return series


# ── Spatial-mode dispatch (generic) ──────────────────────────


def has_located_points(load_result: "LoadResult") -> bool:
    """Return True if the LoadResult contains PointRecords with (x, y)."""
    for rec in load_result.points:
        loc = getattr(rec, "location", None)
        if loc is not None and hasattr(loc, "x") and hasattr(loc, "y"):
            return True
    return False


def resolve_forcing(
    load_result: "LoadResult | None",
    *,
    unit_conversion_factor: float = 1.0,
    simulation_window: "ResolvedSimulationTimeWindow | None" = None,
    spatial_mode: SpatialMode = "auto",
    interpolation_method: InterpolationMethod = "nearest",
    label: str = "forcing",
) -> ResolvedForcing | None:
    """Resolve a LoadResult into solver-ready forcing.

    This is the **single entry point** for converting any climatic variable
    from its data-manager representation to what the solver needs.

    Parameters
    ----------
    load_result :
        LoadResult from any variable manager.  None → returns None.
    unit_conversion_factor :
        From data-manager internal unit to solver unit.
    simulation_window :
        For stress-period alignment of the homogeneous series.
    spatial_mode :
        ``"auto"``  — points → homogeneous, fields → heterogeneous.
        ``"homogeneous"`` — force spatial averaging (even for fields).
        ``"heterogeneous"`` — force per-cell discretization.
    interpolation_method :
        ``"nearest"``, ``"linear"``, or ``"idw"`` — used when discretizing
        points or re-gridding fields onto the solver mesh.
    label :
        Human-readable name for error messages (e.g. ``"recharge"``).

    Returns
    -------
    ResolvedForcing or None
        None if load_result is None or contains no usable data.
    """
    if load_result is None:
        return None

    force_homogeneous = spatial_mode == "homogeneous"
    force_heterogeneous = spatial_mode == "heterogeneous"

    # ── Homogeneous series ──
    series = build_forcing_series(
        load_result,
        unit_conversion_factor=unit_conversion_factor,
        simulation_window=simulation_window,
        force_homogeneous=force_homogeneous,
        label=label,
    )

    # ── Heterogeneous source ──
    heterogeneous_source = None
    if force_heterogeneous:
        if load_result.has_fields or has_located_points(load_result):
            heterogeneous_source = load_result
    elif not force_homogeneous:
        # Auto: fields → heterogeneous; located points without series → heterogeneous
        if load_result.has_fields:
            heterogeneous_source = load_result
        elif series is None and has_located_points(load_result):
            heterogeneous_source = load_result

    if series is None and heterogeneous_source is None:
        return None

    return ResolvedForcing(
        series=series,
        heterogeneous_source=heterogeneous_source,
        spatial_mode=spatial_mode,
        interpolation_method=interpolation_method,
    )
