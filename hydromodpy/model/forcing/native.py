"""The forcing at its native step, beside the stress-period view.

A global solver steps on its own clock, so it reads the forcing it integrates
at the step of the source, not at the stress periods of the store.
:class:`NativeSeries` carries that series: the edges of the native steps, one
more than values, and one value per step in m/s, cut to the window of the run. The recharge
binder builds it in the same call that builds the period view; the period view
stays what the meshed backends read, so no number of an existing run moves.

A point source, or a series written in the TOML, gives its own series at the
step of the source. A spatial source read on a lumped mesh gives, at each
native step, the mean over the cell weighted by the area each pixel shares
with it, through :mod:`hydromodpy.model.forcing.area_weights`; outside a
lumped mesh it gives no native series, and no meshed backend reads one. The
source is read in the coordinates of the model, as every forcing the solvers
discretize is: the data layer reprojects on load.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from shapely.geometry import Polygon

from hydromodpy.core.time.coverage import record_step
from hydromodpy.core.time.window import build_simulation_time_boundaries
from hydromodpy.model.forcing.area_weights import area_mean, area_weights
from hydromodpy.model.forcing.forcing_bridge import extract_homogeneous_series
from hydromodpy.model.forcing.rasters import (
    _mask_declared_nodata,
    find_xy_dims,
    pick_field_variable,
)

if TYPE_CHECKING:
    from scipy import sparse

    from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
    from hydromodpy.model.contracts import LoadResultProto

__all__ = ["NativeSeries", "native_series"]


@dataclass(frozen=True)
class NativeSeries:
    """One value per native step of a forcing, in m/s.

    ``starts`` are the edges of the native steps, an unnamed index with one
    more edge than values: a value holds from its edge to the next one, and
    the last edge is the end of the run. The unit factor of the source is
    already applied.
    """

    starts: pd.DatetimeIndex
    values: Any

    def __post_init__(self) -> None:
        starts = pd.DatetimeIndex(self.starts).rename(None)
        values = np.asarray(self.values, dtype=float).reshape(-1)
        if len(values) == 0:
            raise ValueError("a NativeSeries holds at least one step; got none.")
        if len(starts) != len(values) + 1:
            raise ValueError(
                f"a NativeSeries holds {len(values)} values for {len(starts)} edges: "
                "one value per step, so one more edge than values, the last one at "
                "the end of the run."
            )
        if starts.has_duplicates or not starts.is_monotonic_increasing:
            raise ValueError("the starts of a NativeSeries are unique and increasing.")
        object.__setattr__(self, "starts", starts)
        object.__setattr__(self, "values", values)

    def __len__(self) -> int:
        return len(self.values)


def native_series(
    load_result: LoadResultProto | None,
    window: ResolvedSimulationTimeWindow | None,
    *,
    factor: float = 1.0,
    cell_polygon: Polygon | None = None,
) -> NativeSeries | None:
    """The series of *load_result* at its native step, cut to *window*.

    A point source gives its own series; several stations give their mean at
    each of their steps. A spatial source gives the mean over ``cell_polygon``
    weighted by the shared area, read once for the whole series, and gives
    ``None`` without a polygon. ``factor`` carries the source unit to m/s.
    Returns ``None`` when the source holds no step inside the window.
    """
    if load_result is None:
        return None
    series = extract_homogeneous_series(load_result)
    if series is None:
        if cell_polygon is None or not load_result.has_fields:
            return None
        series = _series_of_fields(load_result, cell_polygon)
    if series is None or series.empty:
        return None
    values = series.to_numpy(dtype=float) * float(factor)
    return _cut_to_window(pd.DatetimeIndex(series.index), values, window)


def _series_of_fields(load_result: LoadResultProto, cell_polygon: Polygon) -> pd.Series | None:
    """The mean of the field records over *cell_polygon*, per step of each record."""
    series_list: list[pd.Series] = []
    for field_rec in load_result.fields:
        one = _series_of_one_field(field_rec, cell_polygon)
        if one is not None:
            series_list.append(one)
    if not series_list:
        return None
    if len(series_list) == 1:
        return series_list[0]
    return pd.concat(series_list, axis=1).mean(axis=1)


def _series_of_one_field(field_rec: Any, cell_polygon: Polygon) -> pd.Series | None:
    """The mean over the cell of one field record, at each of its steps."""
    import xarray as xr

    data = field_rec.data
    if isinstance(data, (str, Path)):
        data = xr.open_dataset(str(data))
    if not isinstance(data, xr.Dataset):
        return None
    name = pick_field_variable(data)
    if name is None:
        return None
    da = _mask_declared_nodata(data[name])
    x_dim, y_dim = find_xy_dims(da)
    weights, flat = _cell_weights_and_values(
        da.coords[x_dim].values, da.coords[y_dim].values, da.values, cell_polygon
    )
    if "time" in da.dims:
        index = pd.DatetimeIndex(da.coords["time"].values)
    else:
        index = pd.DatetimeIndex([_static_anchor(field_rec)])
        flat = flat.reshape(1, -1)
    means = area_mean(weights, flat)[:, 0]
    return pd.Series(means, index=index)


def _cell_weights_and_values(
    x_centers: Any, y_centers: Any, values: Any, cell_polygon: Polygon
) -> tuple[sparse.csr_array, Any]:
    """The pixel weights over the one cell, and the pixel values they read.

    Returned in the ``(y, x)`` layout of the grid: the weights are read once
    for the whole series, on a one-cell mesh built from the polygon, through
    the clip of :func:`area_weights`.
    """
    from hydromodpy.mesh.planar.cell_types import CellType
    from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh

    x_full = np.asarray(x_centers, dtype=float)
    y_full = np.asarray(y_centers, dtype=float)
    if x_full.ndim != 1 or y_full.ndim != 1:
        raise ValueError(
            "the native forcing of a global model reads a grid with 1-D x and y "
            f"axes; got x of shape {x_full.shape} and y of shape {y_full.shape}."
        )
    xmin, ymin, xmax, ymax = cell_polygon.bounds
    reach = float(
        max(np.abs(np.diff(x_full)).max(initial=0.0), np.abs(np.diff(y_full)).max(initial=0.0))
    )
    keep_x = (x_full >= xmin - reach) & (x_full <= xmax + reach)
    keep_y = (y_full >= ymin - reach) & (y_full <= ymax + reach)
    if keep_x.sum() < 2 or keep_y.sum() < 2:
        raise ValueError(
            "the native forcing of a global model needs at least two pixel "
            "centres of the source grid along x and y over the cell; the "
            "pixel size cannot be read from one centre."
        )
    x, y = x_full[keep_x], y_full[keep_y]
    ny, nx = len(y_full), len(x_full)
    flat = np.asarray(values, dtype=float).reshape(-1, ny, nx)
    picked = flat[
        np.ix_(
            np.arange(flat.shape[0]),
            np.flatnonzero(keep_y),
            np.flatnonzero(keep_x),
        )
    ]
    ring = _exterior_ring(cell_polygon)
    mesh = HydroMesh(
        vertices=ring,
        cell_blocks=(CellBlock(CellType.POLYGON, np.arange(len(ring))[None, :]),),
    )
    return area_weights(mesh, x, y), picked.reshape(picked.shape[0], -1)


def _exterior_ring(polygon: Polygon) -> Any:
    """The vertices of the exterior ring of *polygon*, counterclockwise."""
    from shapely.geometry.polygon import orient

    shell = orient(polygon, sign=1.0)
    return np.asarray(shell.exterior.coords, dtype=np.float64)[:-1, :2]


def _static_anchor(field_rec: Any) -> pd.Timestamp:
    """The step a static field reads at: its declared start, else the epoch anchor."""
    anchor = getattr(field_rec, "date_start", None)
    if anchor is not None:
        return pd.Timestamp(anchor)
    return pd.Timestamp("2000-01-01")


def _cut_to_window(
    starts: pd.DatetimeIndex, values: Any, window: ResolvedSimulationTimeWindow | None
) -> NativeSeries | None:
    """Keep the steps the run reads, and close the last one at the end of the run.

    A step that starts at or after the end of the window holds nothing of the
    run. A step that starts before the window holds over its first instant
    only when no step starts there, and then its edge moves to the start of
    the run, so the series never carries water from before the run. Without
    a window, the last step closes one step of the source after its edge,
    the step ``record_step`` of ``core/time`` reads, and a source of one
    sample gives no series.
    """
    if window is None:
        step = record_step(starts)
        if step is None:
            return None
        return NativeSeries(
            starts=starts.append(pd.DatetimeIndex([starts[-1] + step])), values=values
        )
    boundaries = build_simulation_time_boundaries(window)
    start, end = pd.Timestamp(boundaries[0]), pd.Timestamp(boundaries[-1])
    keep = (starts >= start) & (starts < end)
    before = np.flatnonzero(starts < start)
    if before.size and not (starts == start).any():
        keep[int(before[-1])] = True
    if not keep.any():
        return None
    edges = pd.DatetimeIndex(starts[keep])
    edges = pd.DatetimeIndex([max(edges[0], start), *edges[1:], end])
    return NativeSeries(starts=edges, values=np.asarray(values)[keep])
