"""Raster/vector IO, cache and format conversions on a shared environment."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
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

    def set_compress_rasters(self, enabled: bool) -> None:
        self._compress_rasters = bool(enabled)

    def set_cache_rasters(self, enabled: bool) -> None:
        """Enable/disable in-memory raster caching."""
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


__all__ = ["WhiteboxRasterBackend", "_WhiteboxComponent"]
