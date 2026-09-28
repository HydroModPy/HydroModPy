"""A monthly transient run on the V-valley grid, whose extents are known by hand.

The grid is the ``5 x 3`` valley of :mod:`tests.unit.display._network_comparison_run`:
the axis is the middle column, the outlet its southern cell, and a release on
one axis cell floods that cell and every axis cell below it. The run releases:

- in winter (January to March, November and December), 1 m3/s on the northern
  axis cell, so the whole axis flows;
- the rest of the year, ``summer_release`` on the outlet cell alone.

So in every complete year the outlet flows 12 timesteps of 12 and the two
upper axis cells 5 of 12, as long as ``summer_release`` stays above the
visible flow. The maximal map is the whole axis, the minimal map its two
southern cells. The run covers 2001 and 2002 whole and 2003 up to March,
which is not a complete year.
"""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString

from tests.unit.display._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    CELL_RECHARGE_M3_S,
    CRS,
    NX,
    NY,
    cell,
    comparison_run,
)

WINTER_MONTHS = (1, 2, 3, 11, 12)
"""Months the whole axis flows: five of twelve."""

WINTER_RELEASE_M3_S = 1.0
"""Release of the northern axis cell in winter."""

SUMMER_RELEASE_M3_S = 2.0e-3
"""Release of the outlet cell the rest of the year: two litres per second."""

OUTLET = cell(AXIS_COLUMN, 0)
MIDDLE = cell(AXIS_COLUMN, 1)
HEAD = cell(AXIS_COLUMN, 2)
HILLSLOPE = cell(0, 2)
"""A cell no release ever reaches."""

N_STEPS = 27
"""Monthly steps from January 2001 to March 2003."""


def _axis_line(rows_from: float, rows_to: float) -> gpd.GeoDataFrame:
    x = (AXIS_COLUMN + 0.5) * CELL_M
    return gpd.GeoDataFrame(
        geometry=[LineString([(x, rows_from * CELL_M), (x, rows_to * CELL_M)])], crs=CRS
    )


def transient_run(
    *,
    summer_release: float = SUMMER_RELEASE_M3_S,
    with_minimal: bool = True,
    n_steps: int = N_STEPS,
    exclusive_bounds: bool = False,
    with_period_start: bool = True,
    with_time: bool = True,
    roles: tuple[str, ...] | None = None,
) -> SimpleNamespace:
    """Return the transient run described in the module docstring.

    ``exclusive_bounds`` stamps each month on the first day of the next one,
    the other spelling a solver writes a period end with. ``roles`` replaces
    the stored networks the run declares.
    """
    run = comparison_run()
    freq = "MS" if exclusive_bounds else "ME"
    first = "2001-02-01" if exclusive_bounds else "2001-01-31"
    index = pd.date_range(first, periods=n_steps, freq=freq)
    # A stamp on the first of the next month closes the month before it.
    shift = np.timedelta64(1, "D") if exclusive_bounds else np.timedelta64(0, "D")
    months = pd.DatetimeIndex(index.to_numpy() - shift).month.tolist()

    stack = np.zeros((n_steps, NX * NY), dtype=float)
    for step, month in enumerate(months):
        if month in WINTER_MONTHS:
            stack[step, HEAD] = WINTER_RELEASE_M3_S
        else:
            stack[step, OUTLET] = float(summer_release)
    recharge = np.full(NX * NY, CELL_RECHARGE_M3_S)

    def field(variable: str, timestep: int = -1, **_) -> np.ndarray:
        if variable == "release_flux":
            return stack[int(timestep)]
        if variable == "recharge":
            return recharge
        if variable == "topography":
            return run.mesh.topography
        raise KeyError(variable)

    networks = {"reference": _axis_line(0.1, NY - 0.1)}
    if with_minimal:
        networks["reference_permanent"] = _axis_line(0.1, 1.9)
    declared = tuple(networks) if roles is None else roles

    fresh = _TransientRun(**vars(run))
    fresh.index = index if with_time else None
    fresh.n_timesteps = n_steps
    fresh.stack = stack
    fresh.field = field
    fresh.has_field = lambda variable, **_: variable in {"release_flux", "recharge", "topography"}
    fresh.has_hydrographic_network = lambda role="generated": role in declared
    fresh.hydrographic_network = lambda role="generated": networks.get(role, networks["reference"])
    fresh._load_row = lambda: {"period_start": "2001-01-01" if with_period_start else None}
    return fresh


class _TransientRun(SimpleNamespace):
    """A run namespace carrying a ``time_index`` that can fail like a real one."""

    @property
    def time_index(self) -> pd.DatetimeIndex:
        if self.index is None:
            raise RuntimeError("simulation has no n_timesteps recorded")
        return self.index


__all__ = [
    "HEAD",
    "HILLSLOPE",
    "MIDDLE",
    "N_STEPS",
    "OUTLET",
    "SUMMER_RELEASE_M3_S",
    "WINTER_MONTHS",
    "transient_run",
]
