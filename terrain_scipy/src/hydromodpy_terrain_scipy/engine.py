"""A D8 flow-routing engine for the HydroModPy terrain port, on numpy and scipy.

Why this distribution exists
----------------------------
To make "replace WhiteboxTools without touching the callers" a measured fact
instead of a design claim. It is packaged, installed and discovered exactly as a
third party would do it: a ``pyproject.toml`` of its own, one
``hydromodpy.terrain.engine`` entry point, and no line of HydroModPy naming it.
The conformance suite of the host runs every assertion it owns against whatever
that group resolves, so this engine is judged by a file that has never heard of
it.

Why not ``pysheds``
-------------------
The campaign named ``hydromodpy-terrain-pysheds``. Measured on 2026-09-19:
``pysheds`` 0.5 declares ``numpy`` with no upper bound and calls ``np.in1d`` in
nine members of its grid, including ``accumulation`` and ``catchment``.
``np.in1d`` was removed in numpy 2.0 and HydroModPy requires ``numpy>=2.4.4``,
so four of the eight port members cannot run at all. The port needs an engine,
not a library, and this one depends on nothing the host does not already
require.

What it computes, and how it differs from the engines in the host tree
----------------------------------------------------------------------
Three independent algorithms, none shared with ``NumpyTerrainEngine``:

- **conditioning** is Planchon & Darboux, run as a vectorised descending
  fixed point rather than as a priority queue: every non-seed cell starts at
  ``+inf`` and is lowered to ``max(z, nextafter(min over its neighbours))``
  until nothing moves. The epsilon is one float32 ULP and is what makes the
  result plateau-free by construction -- at the fixed point a non-seed cell is
  either one ULP above its lowest neighbour or above it by more, so it always
  has a strictly lower one.
- **accumulation** is a sparse linear solve. With ``M`` the donor matrix of the
  pointer, the upstream count is the solution of ``(I - M) a = 1``. ``M`` is
  nilpotent on a conditioned surface, the system is a permuted unit-triangular
  one, and every value in it is an integer, so the solve is exact. A pointer
  holding a cycle makes it singular; that is refused before the solve, by a
  strongly-connected-components pass, rather than read back out of a NaN.
- **delineation** is one ``breadth_first_order`` on that same matrix from the
  snapped outlet.

It is a reference implementation, like the numpy one it sits beside. The sparse
factorisation is what bounds it: a few hundred thousand cells is comfortable, a
331 MB national DEM is not.

Where it may legitimately disagree with Whitebox
------------------------------------------------
Inside plateaus, and on exact ties. The epsilon gradient this engine lays down
during the fill is its own, and the steepest-descent search keeps a neighbour
only on a strict improvement, so a tie goes to the lowest pointer code. Both are
declared rather than asserted anywhere: the port is what an engine owes, and
cell-for-cell agreement with Whitebox is not part of it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from math import hypot
from pathlib import Path
from typing import ClassVar

import geopandas as gpd
import numpy as np
import rasterio
import scipy
from rasterio.features import shapes as raster_shapes
from scipy.sparse import coo_matrix, eye_array
from scipy.sparse.csgraph import breadth_first_order, connected_components
from scipy.sparse.linalg import spsolve
from shapely.geometry import Point as shapely_point
from shapely.geometry import shape as shapely_shape

from hydromodpy.core.exceptions import (
    TerrainCapabilityError,
    TerrainProductError,
    TerrainRequestError,
)
from hydromodpy.spatial.terrain.port import (
    D8_WBT_OFFSETS,
    DEFAULT_CATCHMENT_LAYOUT,
    MASK_INSIDE,
    MASK_NODATA,
    OUTLET_LAYER_NAME,
    SNAPPED_OUTLET_LAYER_NAME,
    AccumulationTransform,
    AccumulationUnits,
    Catchment,
    CatchmentLayout,
    ConditionedDem,
    ConditioningExtent,
    ConditioningMethod,
    DrainageDirections,
    FlowAccumulation,
    Outlet,
    StreamNetwork,
    require_batch,
    require_rank_preserving,
    require_resolvable_counts,
    require_untransformed,
    snap_window_cells,
)
from hydromodpy_terrain_scipy import __version__

ACCUMULATION_NODATA = -9999.0
"""Absent accumulation.

No product of any transform this engine serves can reach it: a count is at least
1, ``ln`` of a count is at least 0, and an area is positive. It is deliberately
not the value the host engines use -- the port makes every product declare its
own nodata, and an engine that could only work because every engine picked the
same number would not be substitutable.
"""

_CODES: tuple[int, ...] = tuple(sorted(D8_WBT_OFFSETS))
_OFFSETS: tuple[tuple[int, int], ...] = tuple(D8_WBT_OFFSETS[code] for code in _CODES)
_NO_DOWNSTREAM = 0
"""What a data cell with no strictly lower neighbour is coded, as the port says."""

_HUGE = float(np.finfo("float32").max)
"""Stands in for an absent elevation, so no valid cell ever drains into one."""


class ScipyTerrainEngine:
    """The terrain port, served by numpy arrays and scipy sparse graphs."""

    engine_id: ClassVar[str] = "scipy_d8"
    engine_version: ClassVar[str] = __version__

    def engine_digest(self) -> str:
        payload = "\n".join(
            (self.engine_id, self.engine_version, "d8_wbt", f"scipy {scipy.__version__}")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def condition_dem(
        self,
        dem: Path,
        *,
        method: ConditioningMethod,
        extent: ConditioningExtent,
        out: Path,
    ) -> ConditionedDem:
        if extent.kind != "regional":
            raise TerrainCapabilityError(
                f"{self.engine_id} conditions the whole DEM in one pass; extent "
                f"{extent.kind!r} is not implemented."
            )
        if method != "fill":
            raise TerrainCapabilityError(
                f"{self.engine_id} conditions with 'fill' only; {method!r} is not implemented. "
                "Breaching carves a least-cost path, which is a search this engine does not "
                "have, and answering a breach request with a fill would publish a DEM whose "
                "declared method is not the one that produced it."
            )
        grid = _Raster(dem)
        filled = _epsilon_fill(grid)
        nodata = -9999.0 if grid.nodata is None else float(grid.nodata)
        grid.write(out, np.where(grid.valid, filled, nodata), dtype="float32", nodata=nodata)
        return ConditionedDem(path=Path(out), method=method, extent=extent, crs=grid.crs)

    def drainage_directions(
        self,
        conditioned: ConditionedDem,
        *,
        out: Path,
    ) -> DrainageDirections:
        grid = _Raster(conditioned.path)
        grid.write(out, _steepest_descent(grid), dtype="int16", nodata=MASK_NODATA)
        return DrainageDirections(
            path=Path(out),
            pointer_convention="d8_wbt",
            conditioned_dem=conditioned,
        )

    def flow_accumulation(
        self,
        directions: DrainageDirections,
        *,
        units: AccumulationUnits,
        transform: AccumulationTransform,
        out: Path,
    ) -> FlowAccumulation:
        if units not in ("cells", "m2"):
            raise TerrainCapabilityError(
                f"{self.engine_id} accumulates in 'cells' or 'm2'; {units!r} is not implemented."
            )
        if transform not in ("none", "ln"):
            raise TerrainCapabilityError(
                f"{self.engine_id} transforms with 'none' or 'ln'; {transform!r} is "
                "not implemented."
            )
        grid = _pointer_raster(directions)
        graph = _FlowGraph(grid)
        values = np.zeros(grid.shape, dtype="float64")
        values[graph.rows, graph.cols] = graph.upstream_counts()
        if units == "m2":
            values *= grid.cell_area_m2
        if transform == "ln":
            values = np.where(values > 0.0, np.log(np.where(values > 0.0, values, 1.0)), 0.0)
        grid.write(
            out,
            np.where(grid.valid, values, ACCUMULATION_NODATA),
            dtype="float32",
            nodata=ACCUMULATION_NODATA,
        )
        return FlowAccumulation(
            path=Path(out),
            units=units,
            transform=transform,
            directions=directions,
            nodata=ACCUMULATION_NODATA,
        )

    def stream_network(
        self,
        accumulation: FlowAccumulation,
        *,
        threshold: float,
        out: Path,
    ) -> StreamNetwork:
        require_untransformed(accumulation, member="stream_network")
        if threshold <= 0.0:
            raise TerrainRequestError("A stream threshold must be > 0.")
        grid = _Raster(accumulation.path)
        channel = grid.valid & (grid.values > float(threshold))
        grid.write(
            out,
            np.where(channel, MASK_INSIDE, MASK_NODATA),
            dtype="int16",
            nodata=MASK_NODATA,
        )
        return StreamNetwork(
            path=Path(out),
            threshold=float(threshold),
            threshold_units=accumulation.units,
            directions=accumulation.directions,
        )

    def delineate(
        self,
        accumulation: FlowAccumulation,
        outlets: Sequence[Outlet],
        *,
        out_dir: Path,
        snap_distance_m: float,
        layout: CatchmentLayout = DEFAULT_CATCHMENT_LAYOUT,
    ) -> tuple[Catchment, ...]:
        require_rank_preserving(accumulation, member="delineate")
        require_batch(outlets, snap_distance_m=snap_distance_m, layout=layout)
        if accumulation.transform != "none":
            require_resolvable_counts(
                accumulation,
                max_stored_value=_raster_max(accumulation.path),
                member="delineate",
            )

        acc = _Raster(accumulation.path)
        pointer = _pointer_raster(accumulation.directions)
        graph = _FlowGraph(pointer)

        delineated: list[Catchment] = []
        for outlet in outlets:
            row, col = _snap(acc, outlet, snap_distance_m)
            snapped_x, snapped_y = acc.centre(row, col)
            inside = graph.upstream_of(row, col)

            site_dir = layout.site_dir(Path(out_dir), outlet)
            site_dir.mkdir(parents=True, exist_ok=True)
            mask_path = site_dir / layout.mask_name
            boundary_path = site_dir / layout.boundary_name
            pointer.write(
                mask_path,
                np.where(inside, MASK_INSIDE, MASK_NODATA),
                dtype="int16",
                nodata=MASK_NODATA,
            )
            _write_boundary(boundary_path, inside, pointer)
            _write_point(site_dir / OUTLET_LAYER_NAME, outlet.x, outlet.y, pointer.crs)
            _write_point(site_dir / SNAPPED_OUTLET_LAYER_NAME, snapped_x, snapped_y, pointer.crs)

            delineated.append(
                Catchment(
                    outlet=outlet,
                    mask_path=mask_path,
                    boundary_path=boundary_path,
                    cell_count=_mask_cell_count(mask_path),
                    area_m2=_boundary_area_m2(boundary_path),
                    snapped_x=snapped_x,
                    snapped_y=snapped_y,
                    snap_distance_m=hypot(snapped_x - outlet.x, snapped_y - outlet.y),
                )
            )
        return tuple(delineated)


class _Raster:
    """One band, with the geometry and the validity mask routing needs."""

    def __init__(self, path: str | Path) -> None:
        with rasterio.open(str(path)) as src:
            self.values = src.read(1).astype("float64")
            self.profile = src.profile.copy()
            self.transform = src.transform
            self.nodata = src.nodata
            self.crs = str(src.crs) if src.crs else ""
        self.shape = self.values.shape
        self.dx = abs(float(self.transform.a))
        self.dy = abs(float(self.transform.e))
        self.valid = np.isfinite(self.values)
        if self.nodata is not None:
            self.valid &= self.values != self.nodata

    @property
    def cell_area_m2(self) -> float:
        return self.dx * self.dy

    def step_length(self, drow: int, dcol: int) -> float:
        return hypot(dcol * self.dx, drow * self.dy)

    def centre(self, row: int, col: int) -> tuple[float, float]:
        x, y = rasterio.transform.xy(self.transform, row, col)
        return float(x), float(y)

    def write(self, path: str | Path, data: np.ndarray, *, dtype: str, nodata: float) -> None:
        profile = self.profile.copy()
        profile.update(driver="GTiff", count=1, dtype=dtype, nodata=nodata)
        if self.crs:
            profile.update(crs=self.crs)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(str(path), "w", **profile) as dst:
            dst.write(data.astype(dtype), 1)


class _FlowGraph:
    """The D8 pointer of a raster, as a sparse receiver-to-donor graph.

    One row and one column per valid cell. ``matrix[i, j]`` is set when cell
    ``j`` drains directly into cell ``i``, which is the orientation both users
    want: the upstream count is the solution of ``(I - matrix) a = 1``, and the
    catchment of a cell is what a breadth-first walk from it reaches.
    """

    def __init__(self, pointer: _Raster) -> None:
        self.shape = pointer.shape
        self.rows, self.cols = np.nonzero(pointer.valid)
        self.size = self.rows.size
        if self.size == 0:
            raise TerrainProductError(f"The flow pointer holds no valid cell: {pointer.shape}.")
        index = np.full(pointer.shape, -1, dtype="int64")
        index[self.rows, self.cols] = np.arange(self.size)

        codes = pointer.values[self.rows, self.cols]
        drow = np.zeros(self.size, dtype="int64")
        dcol = np.zeros(self.size, dtype="int64")
        coded = np.zeros(self.size, dtype=bool)
        for code, (offset_row, offset_col) in D8_WBT_OFFSETS.items():
            selected = codes == code
            drow[selected] = offset_row
            dcol[selected] = offset_col
            coded |= selected

        target_row = self.rows + drow
        target_col = self.cols + dcol
        inside = (
            coded
            & (target_row >= 0)
            & (target_row < pointer.shape[0])
            & (target_col >= 0)
            & (target_col < pointer.shape[1])
        )
        receiver = np.full(self.size, -1, dtype="int64")
        receiver[inside] = index[target_row[inside], target_col[inside]]
        drains = receiver >= 0
        donor = np.arange(self.size)[drains]
        self.matrix = coo_matrix(
            (np.ones(donor.size, dtype="int8"), (receiver[drains], donor)),
            shape=(self.size, self.size),
        ).tocsr()
        self._index = index

    def upstream_counts(self) -> np.ndarray:
        """Return, per valid cell, itself plus every cell draining through it."""
        self._refuse_a_cycle()
        counts = spsolve(
            (eye_array(self.size, format="csc", dtype="float64") - self.matrix).tocsc(),
            np.ones(self.size, dtype="float64"),
        )
        if not np.all(np.isfinite(counts)):
            raise TerrainProductError(
                "The upstream count of this pointer has no finite solution, so the pointer "
                "is not the drainage of a conditioned surface."
            )
        return np.rint(counts)

    def upstream_of(self, row: int, col: int) -> np.ndarray:
        """Return the mask of every cell draining through ``(row, col)``."""
        start = int(self._index[row, col])
        if start < 0:
            raise TerrainProductError(
                f"Cell ({row}, {col}) carries no flow direction, so nothing drains through it."
            )
        reached = breadth_first_order(self.matrix, start, directed=True, return_predecessors=False)
        inside = np.zeros(self.shape, dtype=bool)
        inside[self.rows[reached], self.cols[reached]] = True
        return inside

    def _refuse_a_cycle(self) -> None:
        """Refuse a pointer that drains in a circle, before it becomes a NaN.

        Every cell has at most one receiver, so any strongly connected component
        of more than one cell is a cycle, and a cycle makes ``I - matrix``
        singular. Caught here rather than read back off the solve: a singular
        sparse solve answers with NaN and a warning, which is a worse way to
        learn that the DEM behind the pointer was never conditioned.
        """
        count, labels = connected_components(self.matrix, directed=True, connection="strong")
        if count == self.size:
            return
        sizes = np.bincount(labels, minlength=count)
        looping = int(np.sum(sizes[sizes > 1]))
        raise TerrainProductError(
            f"The flow pointer holds a cycle, so accumulation has no order: {looping} cells "
            "drain in a circle. The DEM this pointer came from was not conditioned."
        )


def _epsilon_fill(grid: _Raster) -> np.ndarray:
    """Raise every cell until it has a strictly lower neighbour.

    Planchon & Darboux, as a descending fixed point. The seeds -- the frame of
    the grid and every cell touching an absent one -- keep their elevation and
    are the only ways out of the domain. Everything else starts at ``+inf`` and
    is lowered, once per pass, to ``max(z, nextafter(min over its neighbours))``
    until a pass changes nothing.

    The ``nextafter`` is what removes plateaus, and it has to be one float32 ULP
    rather than a constant: the smallest increment that survives float32 storage
    depends on the elevation, so an epsilon chosen for a 100 m surface vanishes
    on a 1 000 m one. On a surface that already drains the increment never
    binds -- every cell is at or above one ULP over its lowest neighbour
    already -- so a plane comes back bit for bit.

    A cell touching an absent one is a seed and not a drainage target: a
    depression whose only low way out crosses a nodata hole stays a depression.
    The port states that behaviour for every engine, so it is implemented and
    not inherited.
    """
    elevation = np.where(grid.valid, grid.values, _HUGE).astype("float32")
    seed = (_frame_of(grid.shape) | _touching_an_absent_cell(grid.valid)) & grid.valid
    pinned = seed | ~grid.valid

    # An absent cell holds +inf and not its stand-in elevation, so it never wins
    # the minimum below and never reaches nextafter, which overflows on it.
    water = np.where(seed, elevation, np.float32(np.inf))
    for _pass in range(grid.values.size + 2):
        lowest = np.full(grid.shape, np.float32(np.inf), dtype="float32")
        for drow, dcol in _OFFSETS:
            lowest = np.minimum(lowest, _shift(water, drow, dcol, fill=np.float32(np.inf)))
        lowered = np.minimum(water, np.maximum(elevation, np.nextafter(lowest, np.float32(np.inf))))
        lowered = np.where(pinned, water, lowered)
        if np.array_equal(lowered, water):
            return water
        water = lowered
    raise TerrainProductError(
        "Conditioning did not settle: the fill is still lowering cells after one pass per "
        "cell of the DEM, which cannot happen on a finite surface."
    )


def _steepest_descent(grid: _Raster) -> np.ndarray:
    """Code every data cell with the direction of its steepest descent.

    The eight slopes are stacked and ``argmax`` picks one, which resolves an
    exact tie to the first code of the stack -- the codes are stacked in
    ascending order, so a tie goes to the lowest one. A cell whose best slope is
    not strictly positive drains nowhere and is coded ``0``.
    """
    elevation = np.where(grid.valid, grid.values, _HUGE)
    slopes = np.stack(
        [
            (elevation - _shift(elevation, drow, dcol, fill=_HUGE)) / grid.step_length(drow, dcol)
            for drow, dcol in _OFFSETS
        ]
    )
    steepest = np.argmax(slopes, axis=0)
    codes = np.where(slopes.max(axis=0) > 0.0, np.asarray(_CODES)[steepest], _NO_DOWNSTREAM)
    return np.where(grid.valid, codes, MASK_NODATA)


def _shift(data: np.ndarray, drow: int, dcol: int, *, fill) -> np.ndarray:
    """Return ``data`` seen from each cell's ``(drow, dcol)`` neighbour."""
    shifted = np.full(data.shape, fill, dtype=data.dtype)
    rows, cols = data.shape
    shifted[
        max(-drow, 0) : rows + min(-drow, 0),
        max(-dcol, 0) : cols + min(-dcol, 0),
    ] = data[
        max(drow, 0) : rows + min(drow, 0),
        max(dcol, 0) : cols + min(dcol, 0),
    ]
    return shifted


def _frame_of(shape: tuple[int, int]) -> np.ndarray:
    frame = np.zeros(shape, dtype=bool)
    frame[0, :] = frame[-1, :] = True
    frame[:, 0] = frame[:, -1] = True
    return frame


def _touching_an_absent_cell(valid: np.ndarray) -> np.ndarray:
    touching = np.zeros(valid.shape, dtype=bool)
    for drow, dcol in _OFFSETS:
        touching |= _shift(~valid, drow, dcol, fill=False)
    return touching & valid


def _pointer_raster(directions: DrainageDirections) -> _Raster:
    if directions.pointer_convention != "d8_wbt":
        raise TerrainProductError(
            f"{ScipyTerrainEngine.engine_id} reads the 'd8_wbt' pointer table; this raster "
            f"declares {directions.pointer_convention!r}."
        )
    grid = _Raster(directions.path)
    grid.valid = grid.values != float(MASK_NODATA)
    if grid.nodata is not None:
        grid.valid &= grid.values != float(grid.nodata)
    return grid


def _snap(acc: _Raster, outlet: Outlet, snap_distance_m: float) -> tuple[int, int]:
    """Move an outlet to the largest accumulation of its snap window.

    The window is the one the port describes and the host measured on Whitebox:
    a square of half-width ``floor(snap_distance_m / (2 * cell size))`` cells per
    axis. Ties go to the nearest cell, then to the lowest ``(row, col)``, so two
    identical requests snap to the same cell.
    """
    row0, col0 = rasterio.transform.rowcol(acc.transform, outlet.x, outlet.y)
    reach_rows, reach_cols = snap_window_cells(snap_distance_m, dx=acc.dx, dy=acc.dy)
    rows, cols = np.mgrid[
        max(int(row0) - reach_rows, 0) : min(int(row0) + reach_rows + 1, acc.shape[0]),
        max(int(col0) - reach_cols, 0) : min(int(col0) + reach_cols + 1, acc.shape[1]),
    ]
    rows, cols = rows.ravel(), cols.ravel()
    inside = acc.valid[rows, cols]
    rows, cols = rows[inside], cols[inside]
    if rows.size == 0:
        raise TerrainProductError(
            f"Snapping outlet {outlet.outlet_id!r} found no data cell in a snap window of "
            f"{snap_distance_m} m around ({outlet.x}, {outlet.y})."
        )
    x, y = rasterio.transform.xy(acc.transform, rows, cols)
    distance = np.hypot(np.asarray(x) - outlet.x, np.asarray(y) - outlet.y)
    best = np.lexsort((cols, rows, distance, -acc.values[rows, cols]))[0]
    return int(rows[best]), int(cols[best])


def _write_point(path: Path, x: float, y: float, crs: str) -> None:
    """Write one of the two point layers the port says every engine writes."""
    frame = gpd.GeoDataFrame({"value": [1]}, geometry=[shapely_point(x, y)])
    if crs:
        frame = frame.set_crs(crs)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(str(path))


def _write_boundary(path: Path, inside: np.ndarray, grid: _Raster) -> None:
    """Polygonise a catchment mask into a vector boundary."""
    geometries = [
        shapely_shape(geometry)
        for geometry, value in raster_shapes(
            inside.astype("uint8"),
            mask=inside,
            transform=grid.transform,
            connectivity=4,
        )
        if value == 1
    ]
    if not geometries:
        raise TerrainProductError(f"Delineation produced an empty catchment: {path}")
    frame = gpd.GeoDataFrame({"value": [1] * len(geometries)}, geometry=geometries)
    if grid.crs:
        frame = frame.set_crs(grid.crs)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(str(path))


def _mask_cell_count(path: Path) -> int:
    """Count the cells of the mask that was written, read back from the file."""
    with rasterio.open(str(path)) as src:
        return int(np.count_nonzero(src.read(1) == MASK_INSIDE))


def _boundary_area_m2(path: Path) -> float:
    """Sum the area of the boundary that was written, read back from the file."""
    frame = gpd.read_file(str(path))
    return 0.0 if frame.empty else float(frame.geometry.area.sum())


def _raster_max(path: Path) -> float:
    """Return the largest value a raster carries, ignoring its nodata."""
    with rasterio.open(str(path)) as src:
        data = src.read(1, masked=True)
    if data.count() == 0:
        raise TerrainProductError(f"Raster holds no valid cell: {path}")
    return float(data.max())


__all__ = ["ACCUMULATION_NODATA", "ScipyTerrainEngine"]
