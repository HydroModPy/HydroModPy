"""Whitebox backend implemented with ``whitebox_workflows.WbEnvironment``."""

from __future__ import annotations

from pathlib import Path

import whitebox_workflows as wbw


_VECTOR_EXTENSIONS = {
    ".shp",
    ".geojson",
    ".json",
    ".gpkg",
    ".dbf",
    ".shx",
}


class WhiteboxWorkflowsBackend:
    """File-based adapter around ``whitebox_workflows.WbEnvironment``."""

    def __init__(self) -> None:
        self._env = wbw.WbEnvironment()
        self._compress_rasters = False

    @staticmethod
    def _ensure_parent(path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _is_vector_path(path: str) -> bool:
        return Path(path).suffix.lower() in _VECTOR_EXTENSIONS

    def _read_raster(self, path: str):
        return self._env.read_raster(path)

    def _write_raster(self, raster, path: str) -> None:
        self._ensure_parent(path)
        self._env.write_raster(raster, path, compress=self._compress_rasters)

    def _read_vector(self, path: str):
        return self._env.read_vector(path)

    def _write_vector(self, vector, path: str) -> None:
        self._ensure_parent(path)
        self._env.write_vector(vector, path)

    def fill_depressions(self, input_dem: str, output_dem: str) -> None:
        self._write_raster(self._env.fill_depressions(self._read_raster(input_dem)), output_dem)

    def breach_depressions(self, input_dem: str, output_dem: str) -> None:
        self._write_raster(
            self._env.breach_depressions_least_cost(self._read_raster(input_dem)),
            output_dem,
        )

    def d8_pointer(
        self,
        input_dem: str,
        output_pointer: str,
        *,
        esri_pntr: bool = False,
    ) -> None:
        self._write_raster(
            self._env.d8_pointer(self._read_raster(input_dem), esri_pointer=esri_pntr),
            output_pointer,
        )

    def d8_flow_accumulation(
        self,
        input_dem: str,
        output_acc: str,
        *,
        log: bool = True,
    ) -> None:
        self._write_raster(
            self._env.d8_flow_accum(
                self._read_raster(input_dem),
                out_type="cells",
                log_transform=log,
                clip=False,
                input_is_pointer=False,
                esri_pntr=False,
            ),
            output_acc,
        )

    def clip_raster_to_polygon(
        self,
        input_raster: str,
        input_polygon: str,
        output_raster: str,
        *,
        maintain_dimensions: bool = False,
    ) -> None:
        self._write_raster(
            self._env.clip_raster_to_polygon(
                self._read_raster(input_raster),
                self._read_vector(input_polygon),
                maintain_dimensions=maintain_dimensions,
            ),
            output_raster,
        )

    def modify_no_data_value(self, raster_path: str, *, new_value: float) -> None:
        self._write_raster(
            self._env.modify_nodata_value(self._read_raster(raster_path), new_value=new_value),
            raster_path,
        )

    def snap_pour_points(
        self,
        pour_points: str,
        flow_accumulation: str,
        output: str,
        snap_dist: int,
    ) -> None:
        self._write_vector(
            self._env.snap_pour_points(
                self._read_vector(pour_points),
                self._read_raster(flow_accumulation),
                snap_dist=snap_dist,
            ),
            output,
        )

    def watershed(
        self,
        d8_pntr: str,
        pour_pts: str,
        output: str,
        *,
        esri_pntr: bool = False,
    ) -> None:
        self._write_raster(
            self._env.watershed(
                self._read_raster(d8_pntr),
                self._read_vector(pour_pts),
                esri_pntr=esri_pntr,
            ),
            output,
        )

    def raster_to_vector_polygons(self, input_raster: str, output_shp: str) -> None:
        self._write_vector(
            self._env.raster_to_vector_polygons(self._read_raster(input_raster)),
            output_shp,
        )

    def raster_to_vector_points(self, input_raster: str, output_shp: str) -> None:
        self._write_vector(
            self._env.raster_to_vector_points(self._read_raster(input_raster)),
            output_shp,
        )

    def trace_downslope_flowpaths(
        self,
        input_points: str,
        d8_pntr: str,
        output_raster: str,
    ) -> None:
        self._write_raster(
            self._env.trace_downslope_flowpaths(
                self._read_vector(input_points),
                self._read_raster(d8_pntr),
            ),
            output_raster,
        )

    def d8_mass_flux(
        self,
        dem: str,
        loading: str,
        efficiency: str,
        absorption: str,
        output: str,
    ) -> None:
        self._write_raster(
            self._env.d8_mass_flux(
                self._read_raster(dem),
                self._read_raster(loading),
                self._read_raster(efficiency),
                self._read_raster(absorption),
            ),
            output,
        )

    def polygons_to_lines(self, input_shp: str, output_shp: str) -> None:
        self._write_vector(self._env.polygons_to_lines(self._read_vector(input_shp)), output_shp)

    def vector_lines_to_raster(
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
            kwargs["field_name"] = field
        if zero_background is not None:
            kwargs["zero_background"] = zero_background
        if cell_size is not None:
            kwargs["cell_size"] = cell_size
        if base is not None:
            kwargs["base_raster"] = self._read_raster(base)
        self._write_raster(
            self._env.vector_lines_to_raster(self._read_vector(input_path), **kwargs),
            output_raster,
        )

    def clip(self, input_path: str, clip_layer: str, output_path: str) -> None:
        clip_vector = self._read_vector(clip_layer)
        if self._is_vector_path(input_path):
            self._write_vector(self._env.clip(self._read_vector(input_path), clip_vector), output_path)
            return
        self._write_raster(self._env.clip(self._read_raster(input_path), clip_vector), output_path)

    def dissolve(
        self,
        input_path: str,
        output_path: str,
        *,
        dissolve_field: str | None = None,
        snap_tolerance: float | None = None,
    ) -> None:
        self._write_vector(
            self._env.dissolve(
                self._read_vector(input_path),
                dissolve_field=dissolve_field,
                snap_tolerance=snap_tolerance,
            ),
            output_path,
        )

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
            kwargs["field_name"] = field
        if zero_background is not None:
            kwargs["zero_background"] = zero_background
        if cell_size is not None:
            kwargs["cell_size"] = cell_size
        if base is not None:
            kwargs["base_raster"] = self._read_raster(base)
        self._write_raster(
            self._env.vector_polygons_to_raster(self._read_vector(input_path), **kwargs),
            output_raster,
        )

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
            kwargs["field_name"] = field
        if assign_op is not None:
            kwargs["assign_op"] = assign_op
        if zero_background is not None:
            kwargs["zero_background"] = zero_background
        if cell_size is not None:
            kwargs["cell_size"] = cell_size
        if base is not None:
            kwargs["base_raster"] = self._read_raster(base)
        self._write_raster(
            self._env.vector_points_to_raster(self._read_vector(input_path), **kwargs),
            output_raster,
        )

    def set_nodata_value(
        self,
        input_raster: str,
        output_raster: str,
        *,
        back_value: float,
    ) -> None:
        self._write_raster(
            self._env.set_nodata_value(self._read_raster(input_raster), back_value=back_value),
            output_raster,
        )

    def polygon_area(self, input_shp: str) -> None:
        self._write_vector(self._env.polygon_area(self._read_vector(input_shp)), input_shp)

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
        self._write_raster(
            self._env.downslope_distance_to_stream(
                self._read_raster(dem),
                self._read_raster(streams),
                **kwargs,
            ),
            output_raster,
        )

    def add_point_coordinates_to_table(self, input_shp: str) -> None:
        self._write_vector(
            self._env.add_point_coordinates_to_table(self._read_vector(input_shp)),
            input_shp,
        )

    def extract_raster_values_at_points(
        self,
        rasters: str | list[str],
        points: str,
    ) -> None:
        raster_paths = [rasters] if isinstance(rasters, str) else list(rasters)
        point_vector, _ = self._env.extract_raster_values_at_points(
            [self._read_raster(path) for path in raster_paths],
            self._read_vector(points),
        )
        self._write_vector(point_vector, points)

    def set_compress_rasters(self, enabled: bool) -> None:
        self._compress_rasters = bool(enabled)
