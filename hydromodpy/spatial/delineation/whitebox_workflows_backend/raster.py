"""Raster/vector IO and format conversions on a shared environment."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path

import whitebox_workflows as wbw

from hydromodpy.core import progress

_VECTOR_EXTENSIONS = {
    ".shp",
    ".geojson",
    ".json",
    ".gpkg",
    ".dbf",
    ".shx",
}


def given_options(**options: object) -> dict[str, object]:
    """Return the options that were given, the ``None`` ones left out."""
    return {name: value for name, value in options.items() if value is not None}


class WhiteboxRasterBackend:
    """Raster/vector IO and format conversions on a shared environment."""

    def __init__(self) -> None:
        self.env = wbw.WbEnvironment()
        self.verbose = self._is_truthy_env(os.environ.get("HMP_WHITEBOX_VERBOSE"))
        redirect_env = os.environ.get("HMP_WHITEBOX_REDIRECT_NATIVE_STDIO")
        if redirect_env is not None:
            self._redirect_native_stdio = self._is_truthy_env(redirect_env)
        else:
            # Native Whitebox warnings write to fd 1/2 directly and bypass
            # Python-level redirection, corrupting the live progress display.
            # fd redirection is the default; pytest workers keep the Python
            # path (repeated dup2 cycles crash the binding under xdist).
            self._redirect_native_stdio = "PYTEST_CURRENT_TEST" not in os.environ
        try:
            self.env.verbose = bool(self.verbose)
        except Exception:
            pass
        self._compress_rasters = False

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
    def silence_stdio(self):
        """Suppress Python stdio while Whitebox native logging is disabled."""
        if self.verbose:
            yield
            return

        with open(os.devnull, "w", encoding="utf-8", errors="ignore") as devnull:
            if not self._redirect_native_stdio:
                # Whitebox Workflows honours ``env.verbose = False`` for its
                # native progress logging. Avoid fd-level redirection by
                # default: repeated dup2 cycles can make the native binding
                # terminate abruptly after several DEM workflows in one
                # pytest/xdist worker.
                with redirect_stdout(devnull), redirect_stderr(devnull):
                    yield
                return

            try:
                stdout_fd = os.dup(1)
            except OSError:
                with redirect_stdout(devnull), redirect_stderr(devnull):
                    yield
                return
            try:
                try:
                    sys.stdout.flush()
                except Exception:
                    pass

                # Only fd 1: native Whitebox warnings print to stdout, and
                # fd 2 carries the live progress display.
                with redirect_stdout(devnull), redirect_stderr(devnull):
                    os.dup2(devnull.fileno(), 1)
                    yield
            finally:
                try:
                    os.dup2(stdout_fd, 1)
                finally:
                    os.close(stdout_fd)

    @contextmanager
    def single_threaded(self):
        """Pin the Whitebox environment to one worker for the enclosed call.

        Whitebox resolves flats and equal-cost ties in worker-completion order,
        so its parallel depression removal returns a different corrected DEM on
        every identical call. Every flow product derives from that DEM, down to
        the catchment area, so those tools must run on a single worker to be
        reproducible.
        """
        previous = self.env.max_procs
        self.env.max_procs = 1
        try:
            yield
        finally:
            self.env.max_procs = previous

    def run_env_operation(self, operation, *args, **kwargs):
        """Run one Whitebox operation under a progress status, stdio silenced."""
        op_name = getattr(operation, "__name__", "operation").replace("_", " ")
        with progress.status(f"Whitebox: {op_name}"), self.silence_stdio():
            return operation(*args, **kwargs)

    def read_raster(self, path: str):
        return self.run_env_operation(self.env.read_raster, path)

    def write_raster(self, raster, path: str) -> None:
        self._ensure_parent(path)
        self.run_env_operation(
            self.env.write_raster,
            raster,
            path,
            compress=self._compress_rasters,
        )

    def read_vector(self, path: str):
        return self.run_env_operation(self.env.read_vector, path)

    @staticmethod
    def vector_record_count(vector) -> int | None:
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

    def write_vector(self, vector, path: str) -> None:
        self._ensure_parent(path)
        record_count = self.vector_record_count(vector)
        if record_count == 0:
            raise ValueError(
                "Whitebox produced an empty vector layer; refusing to write "
                f"{path}. Check the upstream clipping/delineation step."
            )
        self.run_env_operation(self.env.write_vector, vector, path)

    def clip_vector(self, vector, clip_layer):
        return self.run_env_operation(self.env.clip, vector, clip_layer)

    def set_compress_rasters(self, enabled: bool) -> None:
        self._compress_rasters = bool(enabled)

    def clip(self, input_path: str, clip_layer: str, output_path: str) -> None:
        clip_vector = self.read_vector(clip_layer)
        if self._is_vector_path(input_path):
            self.write_vector(
                self.clip_vector(self.read_vector(input_path), clip_vector),
                output_path,
            )
            return
        self.write_raster(
            self.run_env_operation(self.env.clip, self.read_raster(input_path), clip_vector),
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
        self.write_vector(
            self.run_env_operation(
                self.env.dissolve,
                self.read_vector(input_path),
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
        return self.run_env_operation(
            self.env.clip_raster_to_polygon,
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
        self.write_raster(
            self.clip_raster_to_polygon_raster(
                self.read_raster(input_raster),
                self.read_vector(input_polygon),
                maintain_dimensions=maintain_dimensions,
            ),
            output_raster,
        )

    def polygon_area_vector(self, vector):
        return self.run_env_operation(self.env.polygon_area, vector)

    def polygon_area(self, input_shp: str) -> None:
        self.write_vector(self.polygon_area_vector(self.read_vector(input_shp)), input_shp)

    def modify_no_data_value_raster(self, raster, *, new_value: float):
        return self.run_env_operation(
            self.env.modify_nodata_value,
            raster,
            new_value=new_value,
        )

    def modify_no_data_value(self, raster_path: str, *, new_value: float) -> None:
        self.write_raster(
            self.modify_no_data_value_raster(self.read_raster(raster_path), new_value=new_value),
            raster_path,
        )

    def set_nodata_value_raster(self, raster, *, back_value: float):
        return self.run_env_operation(
            self.env.set_nodata_value,
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
        self.write_raster(
            self.set_nodata_value_raster(self.read_raster(input_raster), back_value=back_value),
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
        return self.run_env_operation(
            self.env.vector_lines_to_raster,
            vector,
            **given_options(
                field_name=field,
                zero_background=zero_background,
                cell_size=cell_size,
                base_raster=base_raster,
            ),
        )

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
        base_raster = None if base is None else self.read_raster(base)
        self.write_raster(
            self.vector_lines_to_raster_vector(
                self.read_vector(input_path),
                field=field,
                zero_background=zero_background,
                cell_size=cell_size,
                base_raster=base_raster,
            ),
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
        return self.run_env_operation(
            self.env.vector_polygons_to_raster,
            vector,
            **given_options(
                field_name=field,
                zero_background=zero_background,
                cell_size=cell_size,
                base_raster=base_raster,
            ),
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
        base_raster = None if base is None else self.read_raster(base)
        self.write_raster(
            self.vector_polygons_to_raster_vector(
                self.read_vector(input_path),
                field=field,
                zero_background=zero_background,
                cell_size=cell_size,
                base_raster=base_raster,
            ),
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
        return self.run_env_operation(
            self.env.vector_points_to_raster,
            vector,
            **given_options(
                field_name=field,
                assign_op=assign_op,
                zero_background=zero_background,
                cell_size=cell_size,
                base_raster=base_raster,
            ),
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
        base_raster = None if base is None else self.read_raster(base)
        self.write_raster(
            self.vector_points_to_raster_vector(
                self.read_vector(input_path),
                field=field,
                assign_op=assign_op,
                zero_background=zero_background,
                cell_size=cell_size,
                base_raster=base_raster,
            ),
            output_raster,
        )

    def extract_raster_values_at_points_vector(self, rasters: list, points):
        point_vector, _ = self.run_env_operation(
            self.env.extract_raster_values_at_points,
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
            [self.read_raster(path) for path in raster_paths],
            self.read_vector(points),
        )
        self.write_vector(point_vector, points)


__all__ = [
    "WhiteboxRasterBackend",
    "given_options",
]
