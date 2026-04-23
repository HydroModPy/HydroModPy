"""Protocols for catchment delineation backends.

This module defines the abstract contracts used by `hydromodpy` to perform
delineation on top of a digital elevation model. Concrete implementations
live in `whitebox_cli_backend.py`, `whitebox_workflows_backend.py`,
`pysheds_backend.py`, and `synthetic_backend.py`.

Two protocols cohabit at different abstraction levels:

- `DelineationBackend` - high-level API expected by runtime code
  (flow accumulation, flow direction, stream network extraction and
  catchment delineation from an outlet point).
- `WhiteboxBackend` - low-level, file-oriented contract used by the
  existing Whitebox-based pipeline; inputs and outputs are expressed as
  paths with side effects on disk.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DelineationBackend(Protocol):
    """Minimal high-level contract for a catchment delineation backend.

    All methods accept filesystem paths or arrays depending on the backend.
    Return types are intentionally left as ``Any`` so that backends can
    pick the representation best suited for their pipeline (numpy arrays,
    rasterio datasets, geopandas frames, ...). Runtime code should rely
    on the documented semantics rather than the concrete type.
    """

    name: str

    def flow_accumulation(self, dem: Any, **kwargs: Any) -> Any:
        """Compute a flow-accumulation raster from a DEM."""
        ...

    def flow_direction(self, dem: Any, **kwargs: Any) -> Any:
        """Compute a flow-direction (pointer) raster from a DEM."""
        ...

    def stream_network(self, dem: Any, threshold: float, **kwargs: Any) -> Any:
        """Extract the stream network from a DEM given an accumulation threshold."""
        ...

    def catchment_from_outlet(
        self,
        dem: Any,
        x: float,
        y: float,
        **kwargs: Any,
    ) -> Any:
        """Delineate the catchment polygon upstream of the outlet at (x, y)."""
        ...


class WhiteboxBackend(Protocol):
    """Low-level file-based operations required from a Whitebox-like backend.

    The contract is narrow: inputs and outputs are expressed as paths, all
    methods perform side effects on disk and return ``None``.
    """

    def fill_depressions(self, input_dem: str, output_dem: str) -> None: ...

    def breach_depressions(self, input_dem: str, output_dem: str) -> None: ...

    def d8_pointer(
        self,
        input_dem: str,
        output_pointer: str,
        *,
        esri_pntr: bool = False,
    ) -> None: ...

    def d8_flow_accumulation(
        self,
        input_dem: str,
        output_acc: str,
        *,
        log: bool = True,
    ) -> None: ...

    def clip_raster_to_polygon(
        self,
        input_raster: str,
        input_polygon: str,
        output_raster: str,
        *,
        maintain_dimensions: bool = False,
    ) -> None: ...

    def modify_no_data_value(self, raster_path: str, *, new_value: float) -> None: ...

    def snap_pour_points(
        self,
        pour_points: str,
        flow_accumulation: str,
        output: str,
        snap_dist: int,
    ) -> None: ...

    def watershed(
        self,
        d8_pntr: str,
        pour_pts: str,
        output: str,
        *,
        esri_pntr: bool = False,
    ) -> None: ...

    def raster_to_vector_polygons(self, input_raster: str, output_shp: str) -> None: ...

    def raster_to_vector_points(self, input_raster: str, output_shp: str) -> None: ...

    def trace_downslope_flowpaths(
        self,
        input_points: str,
        d8_pntr: str,
        output_raster: str,
    ) -> None: ...

    def extract_streams(
        self,
        flow_accumulation: str,
        output_raster: str,
        *,
        threshold: float | int | None = None,
        zero_background: bool | None = None,
    ) -> None: ...

    def raster_streams_to_vector(
        self,
        streams_raster: str,
        d8_pointer: str,
        output_vector: str,
        *,
        esri_pointer: bool | None = None,
        all_vertices: bool | None = None,
    ) -> None: ...

    def strahler_stream_order(
        self,
        d8_pointer: str,
        streams_raster: str,
        output_raster: str,
        *,
        esri_pntr: bool | None = None,
        zero_background: bool | None = None,
    ) -> None: ...

    def stream_link_identifier(
        self,
        d8_pointer: str,
        streams_raster: str,
        output_raster: str,
        *,
        esri_pntr: bool | None = None,
        zero_background: bool | None = None,
    ) -> None: ...

    def remove_short_streams(
        self,
        d8_pointer: str,
        streams_raster: str,
        output_raster: str,
        *,
        min_length: float | int | None = None,
        esri_pntr: bool | None = None,
    ) -> None: ...

    def d8_mass_flux(
        self,
        dem: str,
        loading: str,
        efficiency: str,
        absorption: str,
        output: str,
    ) -> None: ...

    def polygons_to_lines(self, input_shp: str, output_shp: str) -> None: ...

    def vector_lines_to_raster(
        self,
        input_shp: str,
        output_raster: str,
        *,
        field: str | None = None,
        zero_background: bool | None = None,
        cell_size: float | None = None,
        base: str | None = None,
    ) -> None: ...

    def clip(self, input_path: str, clip_layer: str, output_path: str) -> None: ...

    def dissolve(
        self,
        input_path: str,
        output_path: str,
        *,
        dissolve_field: str | None = None,
        snap_tolerance: float | None = None,
    ) -> None: ...

    def vector_polygons_to_raster(
        self,
        input_path: str,
        output_raster: str,
        *,
        field: str | None = None,
        zero_background: bool | None = None,
        cell_size: float | None = None,
        base: str | None = None,
    ) -> None: ...

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
    ) -> None: ...

    def set_nodata_value(
        self,
        input_raster: str,
        output_raster: str,
        *,
        back_value: float,
    ) -> None: ...

    def polygon_area(self, input_shp: str) -> None: ...

    def downslope_distance_to_stream(
        self,
        dem: str,
        streams: str,
        output_raster: str,
        *,
        use_dinf: bool | None = None,
    ) -> None: ...

    def add_point_coordinates_to_table(self, input_shp: str) -> None: ...

    def extract_raster_values_at_points(
        self,
        rasters: str | list[str],
        points: str,
    ) -> None: ...

    def set_compress_rasters(self, enabled: bool) -> None: ...
