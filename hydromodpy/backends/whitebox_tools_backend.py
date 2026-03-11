"""Whitebox backend implementations and runtime selection helpers."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING

import whitebox

if TYPE_CHECKING:
    from hydromodpy.backends.whitebox_workflows_backend import WhiteboxWorkflowsBackend


class WhiteboxToolsBackend:
    """Thin adapter around ``whitebox.WhiteboxTools``."""

    def __init__(self) -> None:
        self._tool = whitebox.WhiteboxTools()
        self._tool.verbose = False

    def fill_depressions(self, input_dem: str, output_dem: str) -> None:
        self._tool.fill_depressions(input_dem, output_dem)

    def breach_depressions(self, input_dem: str, output_dem: str) -> None:
        self._tool.breach_depressions(input_dem, output_dem)

    def d8_pointer(
        self,
        input_dem: str,
        output_pointer: str,
        *,
        esri_pntr: bool = False,
    ) -> None:
        self._tool.d8_pointer(input_dem, output_pointer, esri_pntr=esri_pntr)

    def d8_flow_accumulation(
        self,
        input_dem: str,
        output_acc: str,
        *,
        log: bool = True,
    ) -> None:
        self._tool.d8_flow_accumulation(input_dem, output_acc, log=log)

    def clip_raster_to_polygon(
        self,
        input_raster: str,
        input_polygon: str,
        output_raster: str,
        *,
        maintain_dimensions: bool = False,
    ) -> None:
        self._tool.clip_raster_to_polygon(
            input_raster,
            input_polygon,
            output_raster,
            maintain_dimensions=maintain_dimensions,
        )

    def modify_no_data_value(self, raster_path: str, *, new_value: float) -> None:
        self._tool.modify_no_data_value(raster_path, new_value=new_value)

    def snap_pour_points(
        self,
        pour_points: str,
        flow_accumulation: str,
        output: str,
        snap_dist: int,
    ) -> None:
        self._tool.snap_pour_points(pour_points, flow_accumulation, output, snap_dist)

    def watershed(
        self,
        d8_pntr: str,
        pour_pts: str,
        output: str,
        *,
        esri_pntr: bool = False,
    ) -> None:
        self._tool.watershed(d8_pntr, pour_pts, output, esri_pntr=esri_pntr)

    def raster_to_vector_polygons(self, input_raster: str, output_shp: str) -> None:
        self._tool.raster_to_vector_polygons(input_raster, output_shp)

    def raster_to_vector_points(self, input_raster: str, output_shp: str) -> None:
        self._tool.raster_to_vector_points(input_raster, output_shp)

    def trace_downslope_flowpaths(
        self,
        input_points: str,
        d8_pntr: str,
        output_raster: str,
    ) -> None:
        self._tool.trace_downslope_flowpaths(input_points, d8_pntr, output_raster)

    def d8_mass_flux(
        self,
        dem: str,
        loading: str,
        efficiency: str,
        absorption: str,
        output: str,
    ) -> None:
        self._tool.d8_mass_flux(dem, loading, efficiency, absorption, output)

    def polygons_to_lines(self, input_shp: str, output_shp: str) -> None:
        self._tool.polygons_to_lines(input_shp, output_shp)

    def vector_lines_to_raster(
        self,
        input_shp: str,
        output_raster: str,
        *,
        field: str | None = None,
        zero_background: bool | None = None,
        cell_size: float | None = None,
        base: str | None = None,
    ) -> None:
        kwargs: dict[str, object] = {}
        if field is not None:
            kwargs["field"] = field
        if zero_background is not None:
            kwargs["zero_background"] = zero_background
        if cell_size is not None:
            kwargs["cell_size"] = cell_size
        if base is not None:
            kwargs["base"] = base
        self._tool.vector_lines_to_raster(input_shp, output_raster, **kwargs)

    def clip(self, input_path: str, clip_layer: str, output_path: str) -> None:
        self._tool.clip(input_path, clip_layer, output_path)

    def dissolve(
        self,
        input_path: str,
        output_path: str,
        *,
        dissolve_field: str | None = None,
        snap_tolerance: float | None = None,
    ) -> None:
        kwargs: dict[str, object] = {}
        if dissolve_field is not None:
            kwargs["dissolve_field"] = dissolve_field
        if snap_tolerance is not None:
            kwargs["snap_tolerance"] = snap_tolerance
        self._tool.dissolve(input_path, output_path, **kwargs)

    def vector_polygons_to_raster(
        self,
        input_path: str,
        output_raster: str,
        *,
        field: str | None = None,
        zero_background: bool | None = None,
        cell_size: float | None = None,
        base: str | None = None,
    ) -> None:
        kwargs: dict[str, object] = {}
        if field is not None:
            kwargs["field"] = field
        if zero_background is not None:
            kwargs["zero_background"] = zero_background
        if cell_size is not None:
            kwargs["cell_size"] = cell_size
        if base is not None:
            kwargs["base"] = base
        self._tool.vector_polygons_to_raster(input_path, output_raster, **kwargs)

    def vector_points_to_raster(
        self,
        input_path: str,
        output_raster: str,
        *,
        field: str | None = None,
        assign_op: str | None = None,
        zero_background: bool | None = None,
        cell_size: float | None = None,
        base: str | None = None,
    ) -> None:
        kwargs: dict[str, object] = {}
        if field is not None:
            kwargs["field"] = field
        if assign_op is not None:
            kwargs["assign_op"] = assign_op
        if zero_background is not None:
            kwargs["zero_background"] = zero_background
        if cell_size is not None:
            kwargs["cell_size"] = cell_size
        if base is not None:
            kwargs["base"] = base
        self._tool.vector_points_to_raster(input_path, output_raster, **kwargs)

    def set_nodata_value(
        self,
        input_raster: str,
        output_raster: str,
        *,
        back_value: float,
    ) -> None:
        self._tool.set_nodata_value(input_raster, output_raster, back_value=back_value)

    def polygon_area(self, input_shp: str) -> None:
        self._tool.polygon_area(input_shp)

    def downslope_distance_to_stream(
        self,
        dem: str,
        streams: str,
        output_raster: str,
        *,
        use_dinf: bool | None = None,
    ) -> None:
        kwargs: dict[str, object] = {}
        if use_dinf is not None:
            kwargs["use_dinf"] = use_dinf
        self._tool.downslope_distance_to_stream(dem, streams, output_raster, **kwargs)

    def add_point_coordinates_to_table(self, input_shp: str) -> None:
        self._tool.add_point_coordinates_to_table(input_shp)

    def extract_raster_values_at_points(
        self,
        rasters: str | list[str],
        points: str,
    ) -> None:
        if isinstance(rasters, str):
            self._tool.extract_raster_values_at_points(rasters, points)
            return
        self._tool.extract_raster_values_at_points(";".join(rasters), points)

    def set_compress_rasters(self, enabled: bool) -> None:
        setter = getattr(self._tool, "set_compress_rasters", None)
        if callable(setter):
            setter(enabled)


def _resolve_whitebox_backend_kind(kind: str | None = None) -> str:
    value = kind if kind is not None else os.environ.get(
        "HYDROMODPY_WHITEBOX_BACKEND",
        "whitebox_workflows",
    )
    normalized = str(value).strip().lower().replace("-", "_")
    aliases = {
        "whitebox": "whitebox",
        "whitebox_tools": "whitebox",
        "whiteboxtools": "whitebox",
        "wbt": "whitebox",
        "whitebox_workflows": "whitebox_workflows",
        "whiteboxworkflow": "whitebox_workflows",
        "workflows": "whitebox_workflows",
        "wbw": "whitebox_workflows",
    }
    if normalized not in aliases:
        raise ValueError(
            f"Unknown whitebox backend {value!r}. "
            "Expected one of: 'whitebox', 'whitebox_tools', 'whitebox_workflows'."
        )
    return aliases[normalized]


@lru_cache(maxsize=4)
def _get_cached_whitebox_backend(kind: str):
    if kind == "whitebox":
        return WhiteboxToolsBackend()
    if kind == "whitebox_workflows":
        from hydromodpy.backends.whitebox_workflows_backend import WhiteboxWorkflowsBackend

        return WhiteboxWorkflowsBackend()
    raise ValueError(f"Unsupported cached whitebox backend kind: {kind!r}")


def get_whitebox_backend(kind: str | None = None):
    """Return the shared configured backend used by runtime code."""
    return _get_cached_whitebox_backend(_resolve_whitebox_backend_kind(kind))
