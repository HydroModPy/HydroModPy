"""The Whitebox Workflows engine, behind the terrain port.

Every member delegates to the sub-backends HydroModPy already ships. The one
number the engine computes itself is the report of a capped breach, measured
from the DEM before and after so a user sees what was dug. The import of
``whitebox_workflows`` stays where it always was, one file deep in
``catchment/delineation/whitebox_workflows_backend/raster.py``.

``WhiteboxTerrainEngine.__init__`` imports ``catchment.delineation`` only when it is
given no backend, so a third-party engine and the numpy engine never load Whitebox.
"""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any, ClassVar

import geopandas as gpd
import numpy as np
import rasterio

from hydromodpy.catchment.terrain.artifacts import (
    is_stream_cell,
    raster_crs,
    raster_nodata,
    write_outlet_point,
)
from hydromodpy.catchment.terrain.port import (
    DEFAULT_CATCHMENT_LAYOUT,
    OUTLET_LAYER_NAME,
    SNAPPED_OUTLET_LAYER_NAME,
    AccumulationTransform,
    AccumulationUnits,
    CappedBreach,
    CappedBreachReport,
    Catchment,
    CatchmentLayout,
    ConditionedDem,
    ConditioningExtent,
    ConditioningMethod,
    DrainageDirections,
    FlowAccumulation,
    JensonSnap,
    Outlet,
    SnapMethod,
    StreamNetwork,
    require_accumulation,
    require_conditioning,
    require_delineable,
    require_stream,
    stamp,
    stream_window_refusal,
)
from hydromodpy.core.exceptions import EmptyCatchmentError, TerrainProductError
from hydromodpy.core.io.crs import ensure_crs
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

_OUT_TYPE = {"cells": "cells", "m2": "catchment area"}  # the tool's name of each unit

MOVE_THRESHOLD_M = 0.01
"""A cell moved by less than this does not count as lowered or raised.

The breach tool writes a tiny increment on every cell of a path so that it
descends, and counting those would make a one-cell cut look like a trench.
"""


class WhiteboxTerrainEngine:
    """Terrain engine backed by the Whitebox Workflows sub-backends."""

    engine_id: ClassVar[str] = "whitebox_workflows"
    engine_version: ClassVar[str] = distribution_version("whitebox-workflows")

    def __init__(self, backend: Any = None) -> None:
        if backend is None:
            from hydromodpy.catchment.delineation import get_whitebox_backend

            backend = get_whitebox_backend()
        self._backend: Any = backend
        # Rasters this engine wrote, with the state of their file. A later member takes
        # its input from here instead of reading back what it just wrote.
        self._written: dict[Path, tuple[Any, tuple[int, int, int]]] = {}

    def engine_digest(self) -> str:
        return stamp(self.engine_id, self.engine_version)

    def condition_dem(
        self, dem: Path, *, method: ConditioningMethod, extent: ConditioningExtent, out: Path
    ) -> ConditionedDem:
        require_conditioning(self.engine_id, method, extent, serves=("fill", "breach", "capped"))
        crs, source, report = raster_crs(dem), self._backend.raster.read_raster(str(dem)), None
        if isinstance(method, CappedBreach):
            cells = _breach_length_cells(method.max_distance_m, _cell_size_m(dem))
            result = self._backend.flow.breach_depressions_raster(
                source, max_dist=cells, max_cost=method.max_depth_m, fill_deps=True
            )
        elif method == "fill":
            result = self._backend.flow.fill_depressions_raster(source)
        else:
            result = self._backend.flow.breach_depressions_raster(source)
        self._write_product(result, out, crs)
        if isinstance(method, CappedBreach):
            report = _measure_capped_breach(
                Path(dem), Path(out), max_dist=cells, max_cost_m=method.max_depth_m
            )
            logger.info(
                "Capped breach: %d cells lowered, %d cells raised (pit raise before the "
                "breach and the residual fill); realised max lowering %.3f m, max raise "
                "%.3f m (max_dist=%d cells, max_cost=%.3f m).",
                report.cells_lowered,
                report.cells_raised,
                report.max_lowering_m,
                report.max_raise_m,
                report.max_dist_cells,
                report.max_cost_m,
            )
            if report.max_lowering_m > method.max_depth_m + MOVE_THRESHOLD_M:
                logger.warning(
                    "Capped breach: the realised maximum lowering %.3f m exceeds "
                    "max_depth %.3f m. max_depth bounds the cumulative cost of one "
                    "breach path, not the depth of one cell, and later paths are costed "
                    "on the DEM earlier ones already lowered, so a cell can be cut "
                    "deeper than max_depth.",
                    report.max_lowering_m,
                    method.max_depth_m,
                )
        return ConditionedDem(Path(out), method, extent, crs, report)

    def drainage_directions(self, conditioned: ConditionedDem, *, out: Path) -> DrainageDirections:
        source = self._read_raster(conditioned.path)
        pointer = self._backend.flow.d8_pointer_raster(source, esri_pntr=False)
        self._write_product(pointer, out, conditioned.crs)
        return DrainageDirections(Path(out), "d8_wbt", conditioned)

    def flow_accumulation(
        self,
        directions: DrainageDirections,
        *,
        units: AccumulationUnits,
        transform: AccumulationTransform,
        out: Path,
    ) -> FlowAccumulation:
        require_accumulation(self.engine_id, units, transform)
        accumulated = self._backend.flow.d8_flow_accumulation_raster(
            self._read_raster(directions.path),
            log=transform == "ln",
            out_type=_OUT_TYPE[units],
            input_is_pointer=True,
        )
        self._write_product(accumulated, out, directions.conditioned_dem.crs)
        return FlowAccumulation(Path(out), units, transform, directions, raster_nodata(out))

    def stream_network(
        self, accumulation: FlowAccumulation, *, threshold: float, out: Path
    ) -> StreamNetwork:
        require_stream(accumulation, threshold)
        streams = self._backend.delineation.extract_streams_raster(
            self._read_raster(accumulation.path), threshold=float(threshold), zero_background=False
        )
        self._write_product(streams, out, accumulation.directions.conditioned_dem.crs)
        directions = accumulation.directions
        return StreamNetwork(Path(out), float(threshold), accumulation.units, directions)

    def delineate(
        self,
        accumulation: FlowAccumulation,
        outlets: Sequence[Outlet],
        *,
        out_dir: Path,
        snap_distance_m: float,
        snap: SnapMethod = "window",
        layout: CatchmentLayout = DEFAULT_CATCHMENT_LAYOUT,
    ) -> tuple[Catchment, ...]:
        require_delineable(
            accumulation, outlets, snap=snap, snap_distance_m=snap_distance_m, layout=layout
        )
        crs = accumulation.directions.conditioned_dem.crs
        # The products are read once for the whole batch. The snap ranks the accumulation
        # for a window and the stream network for a Jenson snap.
        ranked = self._read_raster(
            snap.streams.path if isinstance(snap, JensonSnap) else accumulation.path
        )
        pointer = self._read_raster(accumulation.directions.path)
        delineation = self._backend.delineation
        found = []
        for outlet in outlets:
            site, mask_path, boundary_path = layout.make_site(out_dir, outlet)
            snapped, x, y = self._snap(outlet, site, crs, snap, ranked, snap_distance_m)
            watershed = delineation.watershed_raster(pointer, snapped, esri_pntr=False)
            self._write_raster(watershed, mask_path, crs)
            boundary = delineation.raster_to_vector_polygons_raster(watershed)
            if self._backend.raster.vector_record_count(boundary) == 0:
                raise EmptyCatchmentError(
                    f"Outlet {outlet.outlet_id!r} delineated an empty catchment."
                )
            self._backend.raster.write_vector(boundary, str(boundary_path))
            ensure_crs(boundary_path, crs or None)
            found.append(Catchment.from_files(outlet, mask_path, boundary_path, x, y))
        return tuple(found)

    def _snap(
        self,
        outlet: Outlet,
        site: Path,
        crs: str,
        snap: SnapMethod,
        ranked: Any,
        distance: float,
    ) -> tuple[Any, float, float]:
        """Write the outlet, snap it, rewrite the snapped layer with the port columns."""
        outlet_shp, snapped_shp = site / OUTLET_LAYER_NAME, site / SNAPPED_OUTLET_LAYER_NAME
        write_outlet_point(outlet_shp, outlet.outlet_id, outlet.x, outlet.y, crs)
        ensure_crs(outlet_shp, crs or None)
        raster, delineation = self._backend.raster, self._backend.delineation
        vector = raster.read_vector(str(outlet_shp))
        if isinstance(snap, JensonSnap):
            snapped = delineation.jenson_snap_pour_points_vector(vector, ranked, distance)
        else:
            snapped = delineation.snap_pour_points_vector(vector, ranked, int(distance))
        if raster.vector_record_count(snapped) == 0:
            raise TerrainProductError(
                f"Snapping outlet {outlet.outlet_id!r} produced no feature within {distance} m. "
                "The outlet may sit outside the accumulation raster."
            )
        raster.write_vector(snapped, str(snapped_shp))
        x, y = read_point(snapped_shp)
        # The tool writes the declared columns back empty, so the layer is written again.
        write_outlet_point(snapped_shp, outlet.outlet_id, x, y, crs)
        ensure_crs(snapped_shp, crs or None)
        # The tool leaves an outlet where it was when its window holds no stream cell.
        if isinstance(snap, JensonSnap) and not is_stream_cell(snap.streams.path, x, y):
            raise TerrainProductError(stream_window_refusal(outlet, distance, snap))
        return snapped, x, y

    def _read_raster(self, path: str | Path) -> Any:
        """A raster this engine wrote and nobody changed since, or a fresh read."""
        held = self._written.get(Path(path))
        if held is not None and Path(path).is_file() and held[1] == _file_state(path):
            return held[0]
        return self._backend.raster.read_raster(str(path))

    def _write_raster(self, raster: Any, out: str | Path, crs: str) -> None:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        self._backend.raster.write_raster(raster, str(out))
        ensure_crs(out, crs or None)  # an empty CRS must not be stamped on an output

    def _write_product(self, raster: Any, out: Path, crs: str) -> None:
        """Write a product a later member reads, and keep it for that member."""
        self._write_raster(raster, out, crs)
        self._written[Path(out)] = (raster, _file_state(out))


def _file_state(path: str | Path) -> tuple[int, int, int]:
    """Return what tells a file rewritten since: its inode, size and mtime."""
    stat = os.stat(path)
    return stat.st_ino, stat.st_size, stat.st_mtime_ns


def _cell_size_m(dem: Path) -> float:
    """Return the coarser cell side of a DEM, in the unit of its CRS."""
    with rasterio.open(str(dem)) as src:
        return float(max(abs(src.res[0]), abs(src.res[1])))


def _breach_length_cells(max_distance_m: float, cell_size_m: float) -> int:
    """Translate a breach length in meters to the whole cells the tool counts.

    Rounded up, never below one cell. The ratio is rounded first so that 200 m on
    a 25 m grid is 8 cells and not 9 through a float artifact.
    """
    return max(1, math.ceil(round(max_distance_m / cell_size_m, 9)))


def _measure_capped_breach(
    source: Path, conditioned: Path, *, max_dist: int, max_cost_m: float
) -> CappedBreachReport:
    """Measure what the capped breach did, from the two files and nothing else."""
    with rasterio.open(str(source)) as before, rasterio.open(str(conditioned)) as after:
        a = before.read(1, masked=True).astype("float64")
        b = after.read(1, masked=True).astype("float64")
    valid = ~(np.ma.getmaskarray(a) | np.ma.getmaskarray(b))
    diff = np.where(valid, np.ma.getdata(b) - np.ma.getdata(a), 0.0)
    lowered = diff < -MOVE_THRESHOLD_M
    raised = diff > MOVE_THRESHOLD_M
    return CappedBreachReport(
        cells_lowered=int(np.count_nonzero(lowered)),
        cells_raised=int(np.count_nonzero(raised)),
        max_lowering_m=float(max(0.0, -diff.min())) if diff.size else 0.0,
        max_raise_m=float(max(0.0, diff.max())) if diff.size else 0.0,
        max_dist_cells=int(max_dist),
        max_cost_m=float(max_cost_m),
        move_threshold_m=MOVE_THRESHOLD_M,
    )


def read_point(path: Path) -> tuple[float, float]:
    """Return the coordinates of the first point of a vector layer."""
    frame = gpd.read_file(str(path))
    if frame.empty:
        raise TerrainProductError(f"Point layer holds no feature: {path}")
    point = frame.geometry.iloc[0]
    return float(point.x), float(point.y)


__all__ = ["WhiteboxTerrainEngine", "read_point"]
