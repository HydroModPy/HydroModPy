"""The Whitebox Workflows engine, behind the terrain port.

Nothing here computes: every member delegates to the sub-backends HydroModPy
already ships, which is why this engine moves no number. The import of
``whitebox_workflows`` stays where it always was, one file deep in
``spatial/delineation/whitebox_workflows_backend/raster.py``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from importlib.metadata import version as distribution_version
from math import hypot
from pathlib import Path
from typing import Any, ClassVar

import geopandas as gpd
import pandas as pd

from hydromodpy.core.exceptions import (
    EmptyCatchmentError,
    TerrainCapabilityError,
    TerrainProductError,
    TerrainRequestError,
)
from hydromodpy.core.io.crs import ensure_crs
from hydromodpy.spatial.terrain.artifacts import (
    boundary_area_m2,
    mask_cell_count,
    raster_crs,
    raster_max,
    raster_nodata,
)
from hydromodpy.spatial.terrain.port import (
    DEFAULT_CATCHMENT_LAYOUT,
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
)

_OUT_TYPE_BY_UNITS: dict[str, str] = {"cells": "cells", "m2": "catchment area"}


class WhiteboxTerrainEngine:
    """Terrain engine backed by the Whitebox Workflows sub-backends."""

    engine_id: ClassVar[str] = "whitebox_workflows"
    engine_version: ClassVar[str] = distribution_version("whitebox-workflows")

    def __init__(self, backend: Any = None) -> None:
        if backend is None:
            from hydromodpy.spatial.delineation import get_whitebox_backend

            backend = get_whitebox_backend()
        self._backend: Any = backend

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
        if method not in ("fill", "breach"):
            raise TerrainCapabilityError(
                f"{self.engine_id} conditions with 'fill' or 'breach'; "
                f"{method!r} is not implemented."
            )
        crs = raster_crs(dem)
        source = self._backend.raster.read_raster(str(dem))
        if method == "fill":
            conditioned = self._backend.flow.fill_depressions_raster(source)
        else:
            conditioned = self._backend.flow.breach_depressions_raster(source)
        self._write_raster(conditioned, out, crs)
        return ConditionedDem(path=Path(out), method=method, extent=extent, crs=crs)

    def drainage_directions(
        self,
        conditioned: ConditionedDem,
        *,
        out: Path,
    ) -> DrainageDirections:
        source = self._backend.raster.read_raster(str(conditioned.path))
        pointer = self._backend.flow.d8_pointer_raster(source, esri_pntr=False)
        self._write_raster(pointer, out, conditioned.crs)
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
        pointer = self._backend.raster.read_raster(str(directions.path))
        accumulated = self._backend.flow.d8_flow_accumulation_raster(
            pointer,
            log=transform == "ln",
            out_type=out_type,
            input_is_pointer=True,
        )
        self._write_raster(accumulated, out, directions.conditioned_dem.crs)
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
        source = self._backend.raster.read_raster(str(accumulation.path))
        streams = self._backend.delineation.extract_streams_raster(
            source,
            threshold=float(threshold),
            zero_background=False,
        )
        self._write_raster(streams, out, accumulation.directions.conditioned_dem.crs)
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
            # One pass over the raster, and only when the values are transformed:
            # what is stored is what the snap compares.
            require_resolvable_counts(
                accumulation,
                max_stored_value=raster_max(accumulation.path),
                member="delineate",
            )

        crs = accumulation.directions.conditioned_dem.crs
        # Read the two shared products once: that is what makes this a batch.
        acc_raster = self._backend.raster.read_raster(str(accumulation.path))
        pointer = self._backend.raster.read_raster(str(accumulation.directions.path))

        delineated: list[Catchment] = []
        for outlet in outlets:
            site_dir = layout.site_dir(Path(out_dir), outlet)
            site_dir.mkdir(parents=True, exist_ok=True)
            outlet_shp = site_dir / OUTLET_LAYER_NAME
            snapped_shp = site_dir / SNAPPED_OUTLET_LAYER_NAME
            mask_path = site_dir / layout.mask_name
            boundary_path = site_dir / layout.boundary_name

            _write_point(outlet_shp, outlet.x, outlet.y, crs)
            ensure_crs(outlet_shp, crs or None)
            snapped = self._backend.delineation.snap_pour_points_vector(
                self._backend.raster.read_vector(str(outlet_shp)),
                acc_raster,
                int(snap_distance_m),
            )
            if self._backend.raster.vector_record_count(snapped) == 0:
                raise TerrainProductError(
                    f"Snapping outlet {outlet.outlet_id!r} produced no feature within "
                    f"{snap_distance_m} m. The outlet may sit outside the accumulation raster."
                )
            self._backend.raster.write_vector(snapped, str(snapped_shp))
            ensure_crs(snapped_shp, crs or None)
            snapped_x, snapped_y = _read_point(snapped_shp)

            watershed = self._backend.delineation.watershed_raster(
                pointer,
                snapped,
                esri_pntr=False,
            )
            self._write_raster(watershed, mask_path, crs)
            boundary = self._backend.delineation.raster_to_vector_polygons_raster(watershed)
            if self._backend.raster.vector_record_count(boundary) == 0:
                raise EmptyCatchmentError(
                    f"Outlet {outlet.outlet_id!r} delineated an empty catchment."
                )
            self._backend.raster.write_vector(boundary, str(boundary_path))
            ensure_crs(boundary_path, crs or None)

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

    def _write_raster(self, raster: Any, out: str | Path, crs: str) -> None:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        self._backend.raster.write_raster(raster, str(out))
        # An empty string is what a DEM with no declared CRS reads back as, and
        # stamping that on an output declares a CRS nobody chose.
        ensure_crs(out, crs or None)


def _write_point(path: Path, x: float, y: float, crs: str) -> None:
    frame = gpd.GeoDataFrame(
        pd.DataFrame({"x": [float(x)], "y": [float(y)]}),
        geometry=gpd.points_from_xy([float(x)], [float(y)]),
        crs=crs or None,
    )
    frame.to_file(str(path))


def _read_point(path: Path) -> tuple[float, float]:
    frame = gpd.read_file(str(path))
    if frame.empty:
        raise TerrainProductError(f"Point layer holds no feature: {path}")
    point = frame.geometry.iloc[0]
    return float(point.x), float(point.y)


__all__ = ["WhiteboxTerrainEngine"]
