"""The Whitebox Workflows engine, behind the terrain port.

Every member delegates to the sub-backends HydroModPy already ships. The one
number the engine computes itself is the report of a capped breach, measured
from the DEM before and after so a user sees what was dug. The import of
``whitebox_workflows`` stays where it always was, one file deep in
``spatial/delineation/whitebox_workflows_backend/raster.py``.
"""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Sequence
from importlib.metadata import version as distribution_version
from math import hypot
from pathlib import Path
from typing import Any, ClassVar

import geopandas as gpd
import numpy as np
import rasterio

from hydromodpy.core.exceptions import (
    EmptyCatchmentError,
    TerrainCapabilityError,
    TerrainProductError,
    TerrainRequestError,
)
from hydromodpy.core.io.crs import ensure_crs
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.terrain.artifacts import (
    boundary_area_m2,
    is_stream_cell,
    mask_cell_count,
    raster_crs,
    raster_max_near,
    raster_nodata,
    write_outlet_point,
)
from hydromodpy.spatial.terrain.port import (
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
    require_batch,
    require_rank_preserving,
    require_resolvable_counts,
    require_snap_method,
    require_untransformed,
    stream_window_refusal,
)

logger = get_logger(__name__)

_OUT_TYPE_BY_UNITS: dict[str, str] = {"cells": "cells", "m2": "catchment area"}

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
            from hydromodpy.spatial.delineation import get_whitebox_backend

            backend = get_whitebox_backend()
        self._backend: Any = backend
        # The rasters this engine wrote, by path, with the state of the file
        # after the write. A later member takes its input from here instead of
        # reading back the file it just wrote.
        self._written: dict[Path, tuple[Any, tuple[int, int, int]]] = {}

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
        if not (isinstance(method, CappedBreach) or method in ("fill", "breach")):
            raise TerrainCapabilityError(
                f"{self.engine_id} conditions with 'fill', 'breach' or a capped breach; "
                f"{method!r} is not implemented."
            )
        crs = raster_crs(dem)
        source = self._backend.raster.read_raster(str(dem))
        report: CappedBreachReport | None = None
        if isinstance(method, CappedBreach):
            max_dist = _breach_length_cells(method.max_distance_m, _cell_size_m(dem))
            conditioned = self._backend.flow.breach_depressions_raster(
                source,
                max_dist=max_dist,
                max_cost=method.max_depth_m,
                fill_deps=True,
            )
        elif method == "fill":
            conditioned = self._backend.flow.fill_depressions_raster(source)
        else:
            conditioned = self._backend.flow.breach_depressions_raster(source)
        self._write_product(conditioned, out, crs)
        if isinstance(method, CappedBreach):
            report = _measure_capped_breach(
                Path(dem), Path(out), max_dist=max_dist, max_cost_m=method.max_depth_m
            )
            logger.info(
                "Capped breach: %d cells lowered, %d cells raised (pit raise before the "
                "breach and the residual fill); realised max lowering %.3f m, max raise "
                "%.3f m "
                "(max_dist=%d cells, max_cost=%.3f m).",
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
        return ConditionedDem(
            path=Path(out), method=method, extent=extent, crs=crs, breach_report=report
        )

    def drainage_directions(
        self,
        conditioned: ConditionedDem,
        *,
        out: Path,
    ) -> DrainageDirections:
        source = self._read_raster(conditioned.path)
        pointer = self._backend.flow.d8_pointer_raster(source, esri_pntr=False)
        self._write_product(pointer, out, conditioned.crs)
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
        out_type = _OUT_TYPE_BY_UNITS.get(units)
        if out_type is None:
            raise TerrainCapabilityError(
                f"{self.engine_id} accumulates in {sorted(_OUT_TYPE_BY_UNITS)}; "
                f"{units!r} is not implemented."
            )
        if transform not in ("none", "ln"):
            raise TerrainCapabilityError(
                f"{self.engine_id} transforms with 'none' or 'ln'; "
                f"{transform!r} is not implemented."
            )
        pointer = self._read_raster(directions.path)
        accumulated = self._backend.flow.d8_flow_accumulation_raster(
            pointer,
            log=transform == "ln",
            out_type=out_type,
            input_is_pointer=True,
        )
        self._write_product(accumulated, out, directions.conditioned_dem.crs)
        return FlowAccumulation(
            path=Path(out),
            units=units,
            transform=transform,
            directions=directions,
            nodata=raster_nodata(out),
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
        source = self._read_raster(accumulation.path)
        streams = self._backend.delineation.extract_streams_raster(
            source,
            threshold=float(threshold),
            zero_background=False,
        )
        self._write_product(streams, out, accumulation.directions.conditioned_dem.crs)
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
        snap: SnapMethod = "window",
        layout: CatchmentLayout = DEFAULT_CATCHMENT_LAYOUT,
    ) -> tuple[Catchment, ...]:
        _refuse_an_unusable_batch(
            accumulation, outlets, snap=snap, snap_distance_m=snap_distance_m, layout=layout
        )
        crs = accumulation.directions.conditioned_dem.crs
        # Read the shared products once: that is what makes this a batch. The
        # raster the snap ranks is the accumulation for the window snap and the
        # stream network for a Jenson one.
        snap_raster = self._read_raster(
            snap.streams.path if isinstance(snap, JensonSnap) else accumulation.path
        )
        pointer = self._read_raster(accumulation.directions.path)
        return tuple(
            self._delineate_outlet(
                outlet,
                site_dir=layout.site_dir(Path(out_dir), outlet),
                layout=layout,
                crs=crs,
                snap=snap,
                snap_raster=snap_raster,
                snap_distance_m=snap_distance_m,
                pointer=pointer,
            )
            for outlet in outlets
        )

    def _delineate_outlet(
        self,
        outlet: Outlet,
        *,
        site_dir: Path,
        layout: CatchmentLayout,
        crs: str,
        snap: SnapMethod,
        snap_raster: Any,
        snap_distance_m: float,
        pointer: Any,
    ) -> Catchment:
        """Snap one outlet, then write its catchment mask and boundary."""
        site_dir.mkdir(parents=True, exist_ok=True)
        mask_path = site_dir / layout.mask_name
        boundary_path = site_dir / layout.boundary_name
        snapped, snapped_x, snapped_y = self._snap_outlet(
            outlet,
            site_dir=site_dir,
            crs=crs,
            snap=snap,
            snap_raster=snap_raster,
            snap_distance_m=snap_distance_m,
        )
        self._write_watershed(
            outlet,
            snapped,
            pointer=pointer,
            mask_path=mask_path,
            boundary_path=boundary_path,
            crs=crs,
        )
        return Catchment(
            outlet=outlet,
            mask_path=mask_path,
            boundary_path=boundary_path,
            cell_count=mask_cell_count(mask_path),
            area_m2=boundary_area_m2(boundary_path),
            snapped_x=snapped_x,
            snapped_y=snapped_y,
            snap_distance_m=hypot(snapped_x - outlet.x, snapped_y - outlet.y),
        )

    def _snap_outlet(
        self,
        outlet: Outlet,
        *,
        site_dir: Path,
        crs: str,
        snap: SnapMethod,
        snap_raster: Any,
        snap_distance_m: float,
    ) -> tuple[Any, float, float]:
        """Write the outlet, snap it and return the snapped vector and point."""
        outlet_shp = site_dir / OUTLET_LAYER_NAME
        snapped_shp = site_dir / SNAPPED_OUTLET_LAYER_NAME
        write_outlet_point(outlet_shp, outlet.outlet_id, outlet.x, outlet.y, crs)
        ensure_crs(outlet_shp, crs or None)
        outlet_vector = self._backend.raster.read_vector(str(outlet_shp))
        if isinstance(snap, JensonSnap):
            snapped = self._backend.delineation.jenson_snap_pour_points_vector(
                outlet_vector, snap_raster, snap_distance_m
            )
        else:
            snapped = self._backend.delineation.snap_pour_points_vector(
                outlet_vector, snap_raster, int(snap_distance_m)
            )
        if self._backend.raster.vector_record_count(snapped) == 0:
            raise TerrainProductError(
                f"Snapping outlet {outlet.outlet_id!r} produced no feature within "
                f"{snap_distance_m} m. The outlet may sit outside the accumulation raster."
            )
        self._backend.raster.write_vector(snapped, str(snapped_shp))
        snapped_x, snapped_y = read_point(snapped_shp)
        # The tool moves the point but writes the columns of the declared
        # outlet back empty (x and y read NaN), so the layer is written again
        # with the columns of the port, on the snapped point.
        write_outlet_point(snapped_shp, outlet.outlet_id, snapped_x, snapped_y, crs)
        ensure_crs(snapped_shp, crs or None)
        # The tool leaves an outlet where it was when its window holds no
        # stream cell, so a point that is not on the network is a refusal.
        if isinstance(snap, JensonSnap) and not is_stream_cell(
            snap.streams.path, snapped_x, snapped_y
        ):
            raise TerrainProductError(stream_window_refusal(outlet, snap_distance_m, snap))
        return snapped, snapped_x, snapped_y

    def _write_watershed(
        self,
        outlet: Outlet,
        snapped: Any,
        *,
        pointer: Any,
        mask_path: Path,
        boundary_path: Path,
        crs: str,
    ) -> None:
        """Write the catchment mask of a snapped outlet and its boundary polygon."""
        watershed = self._backend.delineation.watershed_raster(
            pointer,
            snapped,
            esri_pntr=False,
        )
        self._write_raster(watershed, mask_path, crs)
        boundary = self._backend.delineation.raster_to_vector_polygons_raster(watershed)
        if self._backend.raster.vector_record_count(boundary) == 0:
            raise EmptyCatchmentError(f"Outlet {outlet.outlet_id!r} delineated an empty catchment.")
        self._backend.raster.write_vector(boundary, str(boundary_path))
        ensure_crs(boundary_path, crs or None)

    def _read_raster(self, path: str | Path) -> Any:
        """Return a raster this engine wrote and nobody changed since, or read it."""
        held = self._written.get(Path(path))
        if held is not None and Path(path).is_file() and held[1] == _file_state(path):
            return held[0]
        return self._backend.raster.read_raster(str(path))

    def _write_raster(self, raster: Any, out: str | Path, crs: str) -> None:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        self._backend.raster.write_raster(raster, str(out))
        # An empty string is what a DEM with no declared CRS reads back as, and
        # stamping that on an output declares a CRS nobody chose.
        ensure_crs(out, crs or None)

    def _write_product(self, raster: Any, out: Path, crs: str) -> None:
        """Write a product a later member reads, and keep it for that member."""
        self._write_raster(raster, out, crs)
        self._written[Path(out)] = (raster, _file_state(out))


def _refuse_an_unusable_batch(
    accumulation: FlowAccumulation,
    outlets: Sequence[Outlet],
    *,
    snap: SnapMethod,
    snap_distance_m: float,
    layout: CatchmentLayout,
) -> None:
    """Refuse a batch the snap cannot rank or the layout cannot hold."""
    require_snap_method(snap, accumulation, member="delineate")
    # Only the window snap ranks the accumulation; a Jenson snap never reads it.
    ranks_counts = snap == "window"
    if ranks_counts:
        require_rank_preserving(accumulation, member="delineate")
    require_batch(outlets, snap_distance_m=snap_distance_m, layout=layout)
    if ranks_counts and accumulation.transform != "none":
        # Only when the values are transformed, and only where the snap reads:
        # the search window of each outlet is all the snap compares.
        require_resolvable_counts(
            accumulation,
            max_stored_value=raster_max_near(
                accumulation.path,
                [(outlet.x, outlet.y) for outlet in outlets],
                snap_distance_m,
            ),
            member="delineate",
        )


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
