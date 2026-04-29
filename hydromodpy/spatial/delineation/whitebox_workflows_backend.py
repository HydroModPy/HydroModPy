"""Whitebox backend split into thematic facades on a shared ``WbEnvironment``.

The public entry point is :class:`WhiteboxWorkflowsBackend`, a thin facade that
exposes three component sub-backends:

- ``raster``: raster/vector IO, in-memory cache and format conversions
  (:class:`WhiteboxRasterBackend`)
- ``flow``: DEM flow analysis (fill/breach, pointer, accumulation, mass flux,
  downslope) (:class:`WhiteboxFlowBackend`)
- ``delineation``: watersheds, pour points, stream networks
  (:class:`WhiteboxDelineationBackend`)
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from functools import lru_cache
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


class WhiteboxRasterBackend:
    """Raster/vector IO, cache and format conversions on a shared environment."""

    def __init__(self) -> None:
        self._env = wbw.WbEnvironment()
        self._verbose = self._is_truthy_env(os.environ.get("HYDROMODPY_WHITEBOX_VERBOSE"))
        try:
            self._env.verbose = bool(self._verbose)
        except Exception:
            pass
        self._compress_rasters = False
        self._raster_cache: dict[str, object] = {}
        self._cache_rasters = False

    @staticmethod
    def _ensure_parent(path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _is_truthy_env(value: str | None) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _is_vector_path(path: str) -> bool:
        return Path(path).suffix.lower() in _VECTOR_EXTENSIONS

    @contextmanager
    def _silence_stdio(self):
        """Suppress both Python-level and native stdio emitted by Whitebox."""
        if self._verbose:
            yield
            return

        with open(os.devnull, "w", encoding="utf-8", errors="ignore") as devnull:
            try:
                stdout_fd = os.dup(1)
                stderr_fd = os.dup(2)
            except OSError:
                with redirect_stdout(devnull), redirect_stderr(devnull):
                    yield
                return
            try:
                try:
                    sys.stdout.flush()
                except Exception:
                    pass
                try:
                    sys.stderr.flush()
                except Exception:
                    pass

                with redirect_stdout(devnull), redirect_stderr(devnull):
                    os.dup2(devnull.fileno(), 1)
                    os.dup2(devnull.fileno(), 2)
                    yield
            finally:
                try:
                    os.dup2(stdout_fd, 1)
                    os.dup2(stderr_fd, 2)
                finally:
                    os.close(stdout_fd)
                    os.close(stderr_fd)

    def _run_env_operation(self, operation, *args, **kwargs):
        with self._silence_stdio():
            return operation(*args, **kwargs)

    def _read_raster(self, path: str):
        cached = self._raster_cache.get(path)
        if cached is not None:
            return cached
        return self._run_env_operation(self._env.read_raster, path)

    def _write_raster(self, raster, path: str) -> None:
        self._ensure_parent(path)
        self._run_env_operation(
            self._env.write_raster,
            raster,
            path,
            compress=self._compress_rasters,
        )
        if self._cache_rasters:
            self._raster_cache[path] = raster

    def _read_vector(self, path: str):
        return self._run_env_operation(self._env.read_vector, path)

    @staticmethod
    def _vector_record_count(vector) -> int | None:
        records = getattr(vector, "records", None)
        if records is None:
            return None
        try:
            return int(len(records))
        except Exception:
            try:
                return int(len(list(records)))
            except Exception:
                return None

    def _write_vector(self, vector, path: str) -> None:
        self._ensure_parent(path)
        record_count = self._vector_record_count(vector)
        if record_count == 0:
            raise ValueError(
                "Whitebox produced an empty vector layer; refusing to write "
                f"{path}. Check the upstream clipping/delineation step."
            )
        self._run_env_operation(self._env.write_vector, vector, path)

    # ------------------------------------------------------------------
    # IO primitives
    # ------------------------------------------------------------------
    def read_raster(self, path: str):
        return self._read_raster(path)

    def write_raster(self, raster, path: str) -> None:
        self._write_raster(raster, path)

    def read_vector(self, path: str):
        return self._read_vector(path)

    def write_vector(self, vector, path: str) -> None:
        self._write_vector(vector, path)

    def vector_record_count(self, vector) -> int | None:
        return self._vector_record_count(vector)

    def clip_vector(self, vector, clip_layer):
        return self._run_env_operation(self._env.clip, vector, clip_layer)

    # ------------------------------------------------------------------
    # Cache and compression knobs
    # ------------------------------------------------------------------
    def set_compress_rasters(self, enabled: bool) -> None:
        self._compress_rasters = bool(enabled)

    def set_cache_rasters(self, enabled: bool) -> None:
        """Enable/disable in-memory raster caching.

        When enabled, ``_write_raster`` stores wbw.Raster objects in a dict
        (keyed by path string) instead of writing to disk.  ``_read_raster``
        checks the cache first, falling back to disk for paths not yet cached
        (e.g. the initial DEM input).
        """
        self._cache_rasters = bool(enabled)

    def get_cached_raster_numpy(self, path: str):
        """Return a cached raster as a numpy float64 array, or None."""
        import numpy as np

        raster = self._raster_cache.get(path)
        if raster is None:
            return None
        configs = raster.configs
        rows = configs.rows
        cols = configs.columns
        data = np.full((rows, cols), np.nan, dtype="float64")
        for row in range(rows):
            row_data = raster.get_row_data(row)
            data[row, : len(row_data)] = row_data
        nodata = configs.nodata
        if nodata is not None and nodata != np.nan:
            data[data == nodata] = np.nan
        return data

    def get_cached_raster_metadata(self, path: str) -> dict | None:
        """Return rasterio-compatible metadata for a cached raster."""
        raster = self._raster_cache.get(path)
        if raster is None:
            return None
        c = raster.configs
        return {
            "transform": (c.resolution_x, 0.0, c.west, 0.0, -c.resolution_y, c.north),
            "crs": getattr(c, "coordinate_ref_system_wkt", "") or getattr(c, "epsg", ""),
            "nodata": c.nodata,
            "shape": (c.rows, c.columns),
        }

    def clear_raster_cache(self) -> None:
        """Release all cached rasters."""
        self._raster_cache.clear()

    # ------------------------------------------------------------------
    # Generic clip / dissolve
    # ------------------------------------------------------------------
    def clip(self, input_path: str, clip_layer: str, output_path: str) -> None:
        clip_vector = self._read_vector(clip_layer)
        if self._is_vector_path(input_path):
            self._write_vector(
                self.clip_vector(self._read_vector(input_path), clip_vector),
                output_path,
            )
            return
        self._write_raster(
            self._run_env_operation(self._env.clip, self._read_raster(input_path), clip_vector),
            output_path,
        )

    def dissolve(
        self,
        input_path: str,
        output_path: str,
        *,
        dissolve_field: str | None = None,
        snap_tolerance: float | None = None,
    ) -> None:
        self._write_vector(
            self._run_env_operation(
                self._env.dissolve,
                self._read_vector(input_path),
                dissolve_field=dissolve_field,
                snap_tolerance=snap_tolerance,
            ),
            output_path,
        )

    # ------------------------------------------------------------------
    # Polygon clip and area
    # ------------------------------------------------------------------
    def clip_raster_to_polygon_raster(
        self,
        raster,
        polygon,
        *,
        maintain_dimensions: bool = False,
    ):
        return self._run_env_operation(
            self._env.clip_raster_to_polygon,
            raster,
            polygon,
            maintain_dimensions=maintain_dimensions,
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
            self.clip_raster_to_polygon_raster(
                self._read_raster(input_raster),
                self._read_vector(input_polygon),
                maintain_dimensions=maintain_dimensions,
            ),
            output_raster,
        )

    def polygon_area_vector(self, vector):
        return self._run_env_operation(self._env.polygon_area, vector)

    def polygon_area(self, input_shp: str) -> None:
        self._write_vector(self.polygon_area_vector(self._read_vector(input_shp)), input_shp)

    # ------------------------------------------------------------------
    # Nodata helpers
    # ------------------------------------------------------------------
    def modify_no_data_value_raster(self, raster, *, new_value: float):
        return self._run_env_operation(
            self._env.modify_nodata_value,
            raster,
            new_value=new_value,
        )

    def modify_no_data_value(self, raster_path: str, *, new_value: float) -> None:
        self._write_raster(
            self.modify_no_data_value_raster(self._read_raster(raster_path), new_value=new_value),
            raster_path,
        )

    def set_nodata_value_raster(self, raster, *, back_value: float):
        return self._run_env_operation(
            self._env.set_nodata_value,
            raster,
            back_value=back_value,
        )

    def set_nodata_value(
        self,
        input_raster: str,
        output_raster: str,
        *,
        back_value: float,
    ) -> None:
        self._write_raster(
            self.set_nodata_value_raster(self._read_raster(input_raster), back_value=back_value),
            output_raster,
        )

    # ------------------------------------------------------------------
    # Vector to raster rasterization
    # ------------------------------------------------------------------
    def vector_lines_to_raster_vector(
        self,
        vector,
        *,
        field: str | None = None,
        zero_background: bool | None = None,
        cell_size: float | None = None,
        base_raster=None,
    ):
        kwargs: dict[str, object] = {}
        if field is not None:
            kwargs["field_name"] = field
        if zero_background is not None:
            kwargs["zero_background"] = zero_background
        if cell_size is not None:
            kwargs["cell_size"] = cell_size
        if base_raster is not None:
            kwargs["base_raster"] = base_raster
        return self._run_env_operation(self._env.vector_lines_to_raster, vector, **kwargs)

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
            kwargs["field"] = field
        if zero_background is not None:
            kwargs["zero_background"] = zero_background
        if cell_size is not None:
            kwargs["cell_size"] = cell_size
        if base is not None:
            kwargs["base_raster"] = self._read_raster(base)
        self._write_raster(
            self.vector_lines_to_raster_vector(self._read_vector(input_path), **kwargs),
            output_raster,
        )

    def vector_polygons_to_raster_vector(
        self,
        vector,
        *,
        field: str | None = None,
        zero_background: bool | None = None,
        cell_size: float | None = None,
        base_raster=None,
    ):
        kwargs: dict[str, object] = {}
        if field is not None:
            kwargs["field_name"] = field
        if zero_background is not None:
            kwargs["zero_background"] = zero_background
        if cell_size is not None:
            kwargs["cell_size"] = cell_size
        if base_raster is not None:
            kwargs["base_raster"] = base_raster
        return self._run_env_operation(self._env.vector_polygons_to_raster, vector, **kwargs)

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
            kwargs["base_raster"] = self._read_raster(base)
        self._write_raster(
            self.vector_polygons_to_raster_vector(self._read_vector(input_path), **kwargs),
            output_raster,
        )

    def vector_points_to_raster_vector(
        self,
        vector,
        *,
        field: str | None = None,
        assign_op: str | None = None,
        zero_background: bool | None = None,
        cell_size: float | None = None,
        base_raster=None,
    ):
        kwargs: dict[str, object] = {}
        if field is not None:
            kwargs["field_name"] = field
        if assign_op is not None:
            kwargs["assign_op"] = assign_op
        if zero_background is not None:
            kwargs["zero_background"] = zero_background
        if cell_size is not None:
            kwargs["cell_size"] = cell_size
        if base_raster is not None:
            kwargs["base_raster"] = base_raster
        return self._run_env_operation(self._env.vector_points_to_raster, vector, **kwargs)

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
            kwargs["base_raster"] = self._read_raster(base)
        self._write_raster(
            self.vector_points_to_raster_vector(self._read_vector(input_path), **kwargs),
            output_raster,
        )

    # ------------------------------------------------------------------
    # Raster sampling at points
    # ------------------------------------------------------------------
    def extract_raster_values_at_points_vector(self, rasters: list, points):
        point_vector, _ = self._run_env_operation(
            self._env.extract_raster_values_at_points,
            rasters,
            points,
        )
        return point_vector

    def extract_raster_values_at_points(
        self,
        rasters: str | list[str],
        points: str,
    ) -> None:
        raster_paths = [rasters] if isinstance(rasters, str) else list(rasters)
        point_vector = self.extract_raster_values_at_points_vector(
            [self._read_raster(path) for path in raster_paths],
            self._read_vector(points),
        )
        self._write_vector(point_vector, points)


class _WhiteboxComponent:
    """Mixin sharing the WbEnvironment of a parent :class:`WhiteboxRasterBackend`."""

    def __init__(self, raster: WhiteboxRasterBackend) -> None:
        self._raster = raster

    @property
    def _env(self):
        return self._raster._env

    def _run(self, operation, *args, **kwargs):
        return self._raster._run_env_operation(operation, *args, **kwargs)

    def _read_raster(self, path: str):
        return self._raster._read_raster(path)

    def _write_raster(self, raster, path: str) -> None:
        self._raster._write_raster(raster, path)

    def _read_vector(self, path: str):
        return self._raster._read_vector(path)

    def _write_vector(self, vector, path: str) -> None:
        self._raster._write_vector(vector, path)


class WhiteboxFlowBackend(_WhiteboxComponent):
    """DEM flow analysis: pit-filling, pointer, accumulation, mass flux, downslope."""

    def fill_depressions_raster(self, dem):
        return self._run(self._env.fill_depressions, dem)

    def fill_depressions(self, input_dem: str, output_dem: str) -> None:
        self._write_raster(
            self.fill_depressions_raster(self._read_raster(input_dem)),
            output_dem,
        )

    def breach_depressions_raster(self, dem):
        return self._run(self._env.breach_depressions_least_cost, dem)

    def breach_depressions(self, input_dem: str, output_dem: str) -> None:
        self._write_raster(
            self.breach_depressions_raster(self._read_raster(input_dem)),
            output_dem,
        )

    def d8_pointer_raster(self, dem, *, esri_pntr: bool = False):
        return self._run(
            self._env.d8_pointer,
            dem,
            esri_pointer=esri_pntr,
        )

    def d8_pointer(
        self,
        input_dem: str,
        output_pointer: str,
        *,
        esri_pntr: bool = False,
    ) -> None:
        self._write_raster(
            self.d8_pointer_raster(self._read_raster(input_dem), esri_pntr=esri_pntr),
            output_pointer,
        )

    def d8_flow_accumulation_raster(self, dem, *, log: bool = True):
        return self._run(
            self._env.d8_flow_accum,
            dem,
            out_type="cells",
            log_transform=log,
            clip=False,
            input_is_pointer=False,
            esri_pntr=False,
        )

    def d8_flow_accumulation(
        self,
        input_dem: str,
        output_acc: str,
        *,
        log: bool = True,
    ) -> None:
        self._write_raster(
            self.d8_flow_accumulation_raster(self._read_raster(input_dem), log=log),
            output_acc,
        )

    def d8_mass_flux_raster(self, dem, loading, efficiency, absorption):
        return self._run(
            self._env.d8_mass_flux,
            dem,
            loading,
            efficiency,
            absorption,
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
            self.d8_mass_flux_raster(
                self._read_raster(dem),
                self._read_raster(loading),
                self._read_raster(efficiency),
                self._read_raster(absorption),
            ),
            output,
        )

    def downslope_distance_to_stream_raster(self, dem, streams, *, use_dinf: bool | None = None):
        kwargs: dict[str, object] = {}
        if use_dinf is not None:
            kwargs["use_dinf"] = use_dinf
        return self._run(
            self._env.downslope_distance_to_stream,
            dem,
            streams,
            **kwargs,
        )

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
            self.downslope_distance_to_stream_raster(
                self._read_raster(dem),
                self._read_raster(streams),
                **kwargs,
            ),
            output_raster,
        )

    def trace_downslope_flowpaths_raster(self, input_points, d8_pntr):
        return self._run(
            self._env.trace_downslope_flowpaths,
            input_points,
            d8_pntr,
        )

    def trace_downslope_flowpaths(
        self,
        input_points: str,
        d8_pntr: str,
        output_raster: str,
    ) -> None:
        self._write_raster(
            self.trace_downslope_flowpaths_raster(
                self._read_vector(input_points),
                self._read_raster(d8_pntr),
            ),
            output_raster,
        )


class WhiteboxDelineationBackend(_WhiteboxComponent):
    """Watershed delineation: pour points, watersheds, stream networks."""

    def snap_pour_points_vector(self, pour_points, flow_accumulation, snap_dist: int):
        return self._run(
            self._env.snap_pour_points,
            pour_points,
            flow_accumulation,
            snap_dist=snap_dist,
        )

    def snap_pour_points(
        self,
        pour_points: str,
        flow_accumulation: str,
        output: str,
        snap_dist: int,
    ) -> None:
        self._write_vector(
            self.snap_pour_points_vector(
                self._read_vector(pour_points),
                self._read_raster(flow_accumulation),
                snap_dist,
            ),
            output,
        )

    def watershed_raster(self, d8_pntr, pour_pts, *, esri_pntr: bool = False):
        return self._run(
            self._env.watershed,
            d8_pntr,
            pour_pts,
            esri_pntr=esri_pntr,
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
            self.watershed_raster(
                self._read_raster(d8_pntr),
                self._read_vector(pour_pts),
                esri_pntr=esri_pntr,
            ),
            output,
        )

    def raster_to_vector_polygons_raster(self, raster):
        return self._run(self._env.raster_to_vector_polygons, raster)

    def raster_to_vector_polygons(self, input_raster: str, output_shp: str) -> None:
        self._write_vector(
            self.raster_to_vector_polygons_raster(self._read_raster(input_raster)),
            output_shp,
        )

    def raster_to_vector_points_raster(self, raster):
        return self._run(self._env.raster_to_vector_points, raster)

    def raster_to_vector_points(self, input_raster: str, output_shp: str) -> None:
        self._write_vector(
            self.raster_to_vector_points_raster(self._read_raster(input_raster)),
            output_shp,
        )

    def extract_streams_raster(
        self,
        flow_accumulation,
        *,
        threshold: float | int | None = None,
        zero_background: bool | None = None,
    ):
        kwargs: dict[str, object] = {}
        if threshold is not None:
            kwargs["threshold"] = float(threshold)
        if zero_background is not None:
            kwargs["zero_background"] = zero_background
        return self._run(self._env.extract_streams, flow_accumulation, **kwargs)

    def extract_streams(
        self,
        flow_accumulation: str,
        output_raster: str,
        *,
        threshold: float | int | None = None,
        zero_background: bool | None = None,
    ) -> None:
        self._write_raster(
            self.extract_streams_raster(
                self._read_raster(flow_accumulation),
                threshold=threshold,
                zero_background=zero_background,
            ),
            output_raster,
        )

    def raster_streams_to_vector_raster(
        self,
        streams_raster,
        d8_pointer,
        *,
        esri_pointer: bool | None = None,
        all_vertices: bool | None = None,
    ):
        kwargs: dict[str, object] = {}
        if esri_pointer is not None:
            kwargs["esri_pointer"] = esri_pointer
        if all_vertices is not None:
            kwargs["all_vertices"] = all_vertices
        return self._run(
            self._env.raster_streams_to_vector,
            streams_raster,
            d8_pointer,
            **kwargs,
        )

    def raster_streams_to_vector(
        self,
        streams_raster: str,
        d8_pointer: str,
        output_vector: str,
        *,
        esri_pointer: bool | None = None,
        all_vertices: bool | None = None,
    ) -> None:
        self._write_vector(
            self.raster_streams_to_vector_raster(
                self._read_raster(streams_raster),
                self._read_raster(d8_pointer),
                esri_pointer=esri_pointer,
                all_vertices=all_vertices,
            ),
            output_vector,
        )

    def strahler_stream_order_raster(
        self,
        d8_pointer,
        streams_raster,
        *,
        esri_pntr: bool | None = None,
        zero_background: bool | None = None,
    ):
        kwargs: dict[str, object] = {}
        if esri_pntr is not None:
            kwargs["esri_pntr"] = esri_pntr
        if zero_background is not None:
            kwargs["zero_background"] = zero_background
        return self._run(
            self._env.strahler_stream_order,
            d8_pointer,
            streams_raster,
            **kwargs,
        )

    def strahler_stream_order(
        self,
        d8_pointer: str,
        streams_raster: str,
        output_raster: str,
        *,
        esri_pntr: bool | None = None,
        zero_background: bool | None = None,
    ) -> None:
        self._write_raster(
            self.strahler_stream_order_raster(
                self._read_raster(d8_pointer),
                self._read_raster(streams_raster),
                esri_pntr=esri_pntr,
                zero_background=zero_background,
            ),
            output_raster,
        )

    def stream_link_identifier_raster(
        self,
        d8_pointer,
        streams_raster,
        *,
        esri_pntr: bool | None = None,
        zero_background: bool | None = None,
    ):
        kwargs: dict[str, object] = {}
        if esri_pntr is not None:
            kwargs["esri_pntr"] = esri_pntr
        if zero_background is not None:
            kwargs["zero_background"] = zero_background
        return self._run(
            self._env.stream_link_identifier,
            d8_pointer,
            streams_raster,
            **kwargs,
        )

    def stream_link_identifier(
        self,
        d8_pointer: str,
        streams_raster: str,
        output_raster: str,
        *,
        esri_pntr: bool | None = None,
        zero_background: bool | None = None,
    ) -> None:
        self._write_raster(
            self.stream_link_identifier_raster(
                self._read_raster(d8_pointer),
                self._read_raster(streams_raster),
                esri_pntr=esri_pntr,
                zero_background=zero_background,
            ),
            output_raster,
        )

    def remove_short_streams_raster(
        self,
        d8_pointer,
        streams_raster,
        *,
        min_length: float | int | None = None,
        esri_pntr: bool | None = None,
    ):
        kwargs: dict[str, object] = {}
        if min_length is not None:
            kwargs["min_length"] = float(min_length)
        if esri_pntr is not None:
            kwargs["esri_pntr"] = esri_pntr
        return self._run(
            self._env.remove_short_streams,
            d8_pointer,
            streams_raster,
            **kwargs,
        )

    def remove_short_streams(
        self,
        d8_pointer: str,
        streams_raster: str,
        output_raster: str,
        *,
        min_length: float | int | None = None,
        esri_pntr: bool | None = None,
    ) -> None:
        self._write_raster(
            self.remove_short_streams_raster(
                self._read_raster(d8_pointer),
                self._read_raster(streams_raster),
                min_length=min_length,
                esri_pntr=esri_pntr,
            ),
            output_raster,
        )

    def polygons_to_lines_vector(self, vector):
        return self._run(self._env.polygons_to_lines, vector)

    def polygons_to_lines(self, input_shp: str, output_shp: str) -> None:
        self._write_vector(self.polygons_to_lines_vector(self._read_vector(input_shp)), output_shp)

    def add_point_coordinates_to_table_vector(self, vector):
        return self._run(self._env.add_point_coordinates_to_table, vector)

    def add_point_coordinates_to_table(self, input_shp: str) -> None:
        self._write_vector(
            self.add_point_coordinates_to_table_vector(self._read_vector(input_shp)),
            input_shp,
        )


class WhiteboxWorkflowsBackend:
    """Facade aggregating raster IO, flow analysis and delineation backends."""

    def __init__(self) -> None:
        self.raster = WhiteboxRasterBackend()
        self.flow = WhiteboxFlowBackend(self.raster)
        self.delineation = WhiteboxDelineationBackend(self.raster)


def _normalize_whitebox_backend_kind(kind: str | None = None) -> str:
    """Normalize backend selector while keeping HydroModPy workflows-only."""
    value = "whitebox_workflows" if kind is None else str(kind)
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "whitebox_workflows",
        "whiteboxworkflow",
        "workflows",
        "wbw",
    }
    if normalized not in aliases:
        raise ValueError(
            f"Unsupported whitebox backend {value!r}. "
            "HydroModPy now supports only 'whitebox_workflows'."
        )
    return "whitebox_workflows"


@lru_cache(maxsize=1)
def _get_cached_whitebox_backend(kind: str = "whitebox_workflows") -> WhiteboxWorkflowsBackend:
    _normalize_whitebox_backend_kind(kind)
    return WhiteboxWorkflowsBackend()


def clear_whitebox_backend_cache() -> None:
    """Clear the shared workflows backend singleton."""
    _get_cached_whitebox_backend.cache_clear()


def get_whitebox_backend(kind: str | None = None) -> WhiteboxWorkflowsBackend:
    """Return the shared workflows backend used by runtime code."""
    return _get_cached_whitebox_backend(_normalize_whitebox_backend_kind(kind))
