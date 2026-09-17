"""A second terrain engine, on numpy, with no third-party flow routing.

It exists to make the port's substitutability a fact rather than a claim: the
conformance suite runs the same assertions against this engine and against the
Whitebox one, so a member that only makes sense for Whitebox cannot survive in
the port.

It is a reference implementation, not a production one. Depression filling is
the Wang & Liu priority flood and accumulation is a Kahn topological sweep,
both written as Python loops over cells: correct and deterministic at any size,
and the wrong thing to hand a 331 MB DEM. What it refuses, it refuses by name:
least-cost breaching is not implemented here, and saying so is the contract.

Where it can differ from Whitebox, by construction and not by accident:

- **flats**. The two engines resolve plateaus at different stages: this one
  during the fill, by raising each cell one float32 above its flood
  predecessor, so no plateau survives into the pointer; Whitebox keeps the
  plateau in the filled DEM and resolves it later. Both end with water leaving
  the domain, by different paths inside a plateau.
- **ties**. The steepest-descent search walks the pointer codes in ascending
  order and keeps a neighbour only on a strict improvement, so an exact tie
  goes to the lowest code. Whitebox breaks ties its own way.
"""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Sequence
from heapq import heappop, heappush
from math import hypot
from pathlib import Path
from typing import ClassVar

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes as raster_shapes
from shapely.geometry import shape as shapely_shape

from hydromodpy.core.exceptions import (
    TerrainCapabilityError,
    TerrainProductError,
    TerrainRequestError,
)
from hydromodpy.spatial.geographic.core.d8 import WBT_D8_OFFSETS
from hydromodpy.spatial.terrain._artifacts import (
    MASK_INSIDE,
    MASK_NODATA,
    boundary_area_m2,
    mask_cell_count,
)
from hydromodpy.spatial.terrain.port import (
    AccumulationTransform,
    AccumulationUnits,
    Catchment,
    ConditionedDem,
    ConditioningExtent,
    ConditioningMethod,
    DrainageDirections,
    FlowAccumulation,
    Outlet,
    StreamNetwork,
    require_batch,
    require_cell_counts,
    require_untransformed,
    snap_window_cells,
)

_POINTER_NODATA = MASK_NODATA
_NO_DOWNSTREAM = 0
"""What a data cell with no strictly lower neighbour is coded, as Whitebox does."""

ACCUMULATION_NODATA = -32768.0
"""Absent accumulation, the value Whitebox writes too.

Not 0: an accumulation in cells never goes below 1, but ``ln(1)`` is 0, so a
nodata of 0 would turn every headwater cell into a hole under a masked read.
"""

_CODES: tuple[tuple[int, int, int], ...] = tuple(
    (code, offset[0], offset[1]) for code, offset in sorted(WBT_D8_OFFSETS.items())
)


class _Grid:
    """A raster band with the geometry needed to route flow over it."""

    def __init__(self, path: str | Path) -> None:
        with rasterio.open(str(path)) as src:
            self.values = src.read(1).astype("float64")
            self.profile = src.profile.copy()
            self.transform = src.transform
            self.nodata = src.nodata
            self.crs = str(src.crs) if src.crs else ""
        self.rows, self.cols = self.values.shape
        self.dx = abs(float(self.transform.a))
        self.dy = abs(float(self.transform.e))
        if self.nodata is None:
            self.valid = np.isfinite(self.values)
        else:
            self.valid = np.isfinite(self.values) & (self.values != self.nodata)

    @property
    def cell_area_m2(self) -> float:
        return self.dx * self.dy

    def distance(self, drow: int, dcol: int) -> float:
        return hypot(dcol * self.dx, drow * self.dy)

    def centre(self, row: int, col: int) -> tuple[float, float]:
        x, y = rasterio.transform.xy(self.transform, row, col)
        return float(x), float(y)

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        row, col = rasterio.transform.rowcol(self.transform, x, y)
        return int(row), int(col)

    def write(self, path: str | Path, data: np.ndarray, *, dtype: str, nodata: float) -> None:
        profile = self.profile.copy()
        profile.update(driver="GTiff", count=1, dtype=dtype, nodata=nodata)
        if self.crs:
            profile.update(crs=self.crs)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(str(path), "w", **profile) as dst:
            dst.write(data.astype(dtype), 1)


class NumpyTerrainEngine:
    """Terrain engine implemented on numpy, with no flow-routing dependency."""

    engine_id: ClassVar[str] = "numpy_d8"
    engine_version: ClassVar[str] = np.__version__

    def engine_digest(self) -> str:
        payload = "\n".join((self.engine_id, self.engine_version, "d8_wbt"))
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
                f"{self.engine_id} conditions the whole DEM; extent "
                f"{extent.kind!r} is not implemented."
            )
        if method != "fill":
            raise TerrainCapabilityError(
                f"{self.engine_id} conditions with 'fill' only; {method!r} is not "
                "implemented. Least-cost breaching needs a carving search this "
                "engine does not have."
            )
        grid = _Grid(dem)
        filled = _priority_flood_fill(grid)
        nodata = -9999.0 if grid.nodata is None else float(grid.nodata)
        filled = np.where(grid.valid, filled, nodata)
        grid.write(out, filled, dtype="float32", nodata=nodata)
        return ConditionedDem(path=Path(out), method=method, extent=extent, crs=grid.crs)

    def drainage_directions(
        self,
        conditioned: ConditionedDem,
        *,
        out: Path,
    ) -> DrainageDirections:
        grid = _Grid(conditioned.path)
        codes = _steepest_descent_codes(grid)
        grid.write(out, codes, dtype="int16", nodata=_POINTER_NODATA)
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
        grid = _pointer_grid(directions)
        counts = _accumulate(grid)
        values = counts.astype("float64")
        if units == "m2":
            values = values * grid.cell_area_m2
        if transform == "ln":
            values = np.where(values > 0.0, np.log(np.where(values > 0.0, values, 1.0)), 0.0)
        values = np.where(grid.valid, values, ACCUMULATION_NODATA)
        grid.write(out, values, dtype="float32", nodata=ACCUMULATION_NODATA)
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
        grid = _Grid(accumulation.path)
        channel = grid.valid & (grid.values > float(threshold))
        mask = np.where(channel, MASK_INSIDE, MASK_NODATA)
        grid.write(out, mask, dtype="int16", nodata=MASK_NODATA)
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
    ) -> tuple[Catchment, ...]:
        require_cell_counts(accumulation, member="delineate")
        require_batch(outlets, snap_distance_m=snap_distance_m)

        acc = _Grid(accumulation.path)
        pointer = _pointer_grid(accumulation.directions)
        donors = _donors(pointer)

        delineated: list[Catchment] = []
        for outlet in outlets:
            row, col = _snap(acc, outlet, snap_distance_m)
            snapped_x, snapped_y = acc.centre(row, col)
            inside = _upstream_mask(donors, pointer, row, col)

            site_dir = Path(out_dir) / outlet.outlet_id
            mask_path = site_dir / "mask.tif"
            boundary_path = site_dir / "boundary.shp"
            pointer.write(
                mask_path,
                np.where(inside, MASK_INSIDE, MASK_NODATA),
                dtype="int16",
                nodata=MASK_NODATA,
            )
            _write_boundary(boundary_path, inside, pointer)

            delineated.append(
                Catchment(
                    outlet=outlet,
                    mask_path=mask_path,
                    boundary_path=boundary_path,
                    cell_count=mask_cell_count(mask_path),
                    area_m2=boundary_area_m2(boundary_path),
                    snapped_x=snapped_x,
                    snapped_y=snapped_y,
                    snap_distance_m=hypot(snapped_x - outlet.x, snapped_y - outlet.y),
                )
            )
        return tuple(delineated)


def _priority_flood_fill(grid: _Grid) -> np.ndarray:
    """Raise every cell to the lowest elevation it can drain from, plus one bit.

    Wang & Liu: flood inward from the edges of the data, always from the lowest
    open cell, so a cell is fixed at the highest elevation on the lowest path
    out. Ordering the heap by ``(elevation, row, col)`` makes it deterministic.

    The "plus one bit" is Barnes' epsilon variant, and it is not cosmetic: a
    plain fill leaves plateaus, a plateau cell has no strictly lower neighbour,
    and a steepest-descent pointer therefore codes it as draining nowhere.
    Measured before this variant, on the 5 400 cells of
    ``examples/data/dem/DEM_gouville_25m.tif``: 637 cells with no outlet against
    34 for Whitebox, and an accumulation maximum of 181 against 1 459 -- the
    upstream area of a coastal aquifer under-reported eightfold, in silence.

    Each cell is raised to at least the next float32 above its flood
    predecessor, so every cell has a strictly lower neighbour by construction.
    ``nextafter`` rather than a fixed epsilon: the smallest increment that
    survives float32 storage depends on the elevation, and a constant chosen for
    100 m vanishes at 1 000 m. On a surface with no plateau the increment never
    binds, which is why the plane, the V valley and ``dem_valley.tif`` stay
    identical to what Whitebox writes.
    """
    filled = grid.values.astype("float32")
    visited = ~grid.valid
    heap: list[tuple[float, int, int]] = []

    for row in range(grid.rows):
        for col in range(grid.cols):
            if visited[row, col]:
                continue
            if row in (0, grid.rows - 1) or col in (0, grid.cols - 1):
                heappush(heap, (float(filled[row, col]), row, col))
                visited[row, col] = True
                continue
            for _code, drow, dcol in _CODES:
                if not grid.valid[row + drow, col + dcol]:
                    heappush(heap, (float(filled[row, col]), row, col))
                    visited[row, col] = True
                    break

    while heap:
        elevation, row, col = heappop(heap)
        floor = float(np.nextafter(np.float32(elevation), np.float32(np.inf)))
        for _code, drow, dcol in _CODES:
            nrow, ncol = row + drow, col + dcol
            if not (0 <= nrow < grid.rows and 0 <= ncol < grid.cols):
                continue
            if visited[nrow, ncol]:
                continue
            visited[nrow, ncol] = True
            raised = max(float(filled[nrow, ncol]), floor)
            filled[nrow, ncol] = raised
            heappush(heap, (raised, nrow, ncol))
    return filled


def _steepest_descent_codes(grid: _Grid) -> np.ndarray:
    """Code every data cell with the direction of its steepest descent."""
    codes = np.full((grid.rows, grid.cols), _POINTER_NODATA, dtype="int64")
    codes[grid.valid] = _NO_DOWNSTREAM
    best = np.zeros((grid.rows, grid.cols), dtype="float64")

    for code, drow, dcol in _CODES:
        shifted = _shift(grid.values, drow, dcol, fill=np.inf)
        neighbour_valid = _shift(grid.valid.astype("uint8"), drow, dcol, fill=0).astype(bool)
        slope = (grid.values - shifted) / grid.distance(drow, dcol)
        improves = grid.valid & neighbour_valid & (slope > best)
        best = np.where(improves, slope, best)
        codes = np.where(improves, code, codes)
    return codes


def _shift(data: np.ndarray, drow: int, dcol: int, *, fill: float) -> np.ndarray:
    """Return ``data`` seen from each cell's ``(drow, dcol)`` neighbour."""
    out = np.full(data.shape, fill, dtype=data.dtype if data.dtype != bool else "uint8")
    rows, cols = data.shape
    src_rows = slice(max(drow, 0), rows + min(drow, 0))
    src_cols = slice(max(dcol, 0), cols + min(dcol, 0))
    dst_rows = slice(max(-drow, 0), rows + min(-drow, 0))
    dst_cols = slice(max(-dcol, 0), cols + min(-dcol, 0))
    out[dst_rows, dst_cols] = data[src_rows, src_cols]
    return out


def _pointer_grid(directions: DrainageDirections) -> _Grid:
    if directions.pointer_convention != "d8_wbt":
        raise TerrainProductError(
            f"numpy_d8 reads the 'd8_wbt' pointer table; this raster declares "
            f"{directions.pointer_convention!r}."
        )
    grid = _Grid(directions.path)
    grid.valid = grid.values != float(_POINTER_NODATA)
    if grid.nodata is not None:
        grid.valid &= grid.values != float(grid.nodata)
    return grid


def _receiver(grid: _Grid, row: int, col: int) -> tuple[int, int] | None:
    """Return the cell ``(row, col)`` drains into, inside the grid, or None."""
    offset = WBT_D8_OFFSETS.get(int(grid.values[row, col]))
    if offset is None:
        return None
    nrow, ncol = row + offset[0], col + offset[1]
    if not (0 <= nrow < grid.rows and 0 <= ncol < grid.cols):
        return None
    if not grid.valid[nrow, ncol]:
        return None
    return nrow, ncol


def _accumulate(grid: _Grid) -> np.ndarray:
    """Count, for every cell, itself plus every cell draining through it."""
    counts = np.where(grid.valid, 1, 0).astype("int64")
    indegree = np.zeros((grid.rows, grid.cols), dtype="int64")
    receivers: dict[tuple[int, int], tuple[int, int]] = {}

    for row in range(grid.rows):
        for col in range(grid.cols):
            if not grid.valid[row, col]:
                continue
            target = _receiver(grid, row, col)
            if target is None:
                continue
            receivers[(row, col)] = target
            indegree[target] += 1

    queue = deque(
        (row, col)
        for row in range(grid.rows)
        for col in range(grid.cols)
        if grid.valid[row, col] and indegree[row, col] == 0
    )
    settled = 0
    while queue:
        cell = queue.popleft()
        settled += 1
        target = receivers.get(cell)
        if target is None:
            continue
        counts[target] += counts[cell]
        indegree[target] -= 1
        if indegree[target] == 0:
            queue.append(target)

    if settled != int(np.count_nonzero(grid.valid)):
        raise TerrainProductError(
            "The flow pointer holds a cycle, so accumulation has no order: "
            f"{int(np.count_nonzero(grid.valid)) - settled} cells never drain. "
            "The DEM this pointer came from was not conditioned."
        )
    return counts


def _donors(grid: _Grid) -> dict[tuple[int, int], list[tuple[int, int]]]:
    """Map each cell to the cells that drain directly into it."""
    donors: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for row in range(grid.rows):
        for col in range(grid.cols):
            if not grid.valid[row, col]:
                continue
            target = _receiver(grid, row, col)
            if target is None:
                continue
            donors.setdefault(target, []).append((row, col))
    return donors


def _upstream_mask(
    donors: dict[tuple[int, int], list[tuple[int, int]]],
    grid: _Grid,
    row: int,
    col: int,
) -> np.ndarray:
    """Return the mask of every cell draining through ``(row, col)``."""
    inside = np.zeros((grid.rows, grid.cols), dtype=bool)
    queue = deque([(row, col)])
    inside[row, col] = True
    while queue:
        cell = queue.popleft()
        for donor in donors.get(cell, ()):
            if inside[donor]:
                continue
            inside[donor] = True
            queue.append(donor)
    return inside


def _snap(acc: _Grid, outlet: Outlet, snap_distance_m: float) -> tuple[int, int]:
    """Move an outlet to the highest accumulation in its snap window.

    The window is the one ``snap_pour_points`` is measured to search, so the
    two engines snap on the same rule: a square of half-width
    ``floor(snap_distance_m / (2 * cell size))`` cells, per axis. Ties go to the
    nearest cell, then to the lowest ``(row, col)``, so two identical requests
    snap identically.
    """
    row0, col0 = acc.cell_of(outlet.x, outlet.y)
    reach_rows, reach_cols = snap_window_cells(snap_distance_m, dx=acc.dx, dy=acc.dy)

    best: tuple[float, float, int, int] | None = None
    for row in range(row0 - reach_rows, row0 + reach_rows + 1):
        for col in range(col0 - reach_cols, col0 + reach_cols + 1):
            if not (0 <= row < acc.rows and 0 <= col < acc.cols):
                continue
            if not acc.valid[row, col]:
                continue
            x, y = acc.centre(row, col)
            candidate = (
                -float(acc.values[row, col]),
                hypot(x - outlet.x, y - outlet.y),
                row,
                col,
            )
            if best is None or candidate < best:
                best = candidate
    if best is None:
        raise TerrainProductError(
            f"Snapping outlet {outlet.outlet_id!r} found no data cell in a snap "
            f"window of {snap_distance_m} m around ({outlet.x}, {outlet.y})."
        )
    return best[2], best[3]


def _write_boundary(path: Path, inside: np.ndarray, grid: _Grid) -> None:
    """Polygonize a catchment mask into a vector boundary."""
    footprint = inside.astype("uint8")
    geometries = [
        shapely_shape(geometry)
        for geometry, value in raster_shapes(
            footprint,
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


__all__ = ["NumpyTerrainEngine"]
