"""Whitebox-style backend contract used across HydroModPy.

Why this file exists
--------------------
HydroModPy uses a small subset of Whitebox-style operations in several runtime
pipelines (catchment delineation, DEM clipping, routing products, mass-flux
accumulation, ...).  The rest of the code should not depend directly on the
third-party backend object, because that would:

- couple domain logic to one concrete dependency;
- make tests harder to isolate;
- prevent replacing the implementation with a mock or another adapter.

This module therefore defines the minimal file-based protocol expected by the
runtime. Implementations are free to delegate to whitebox_workflows, a fake
test double, or another backend exposing the same side effects on disk.
"""

from __future__ import annotations

from typing import Protocol


class WhiteboxBackend(Protocol):
    """Minimal file-based operations required from a Whitebox-like backend.

    The contract is intentionally narrow:

    - inputs and outputs are expressed as filesystem paths;
    - methods perform side effects on disk and return ``None``;
    - the protocol follows HydroModPy naming instead of mirroring the full
      WhiteboxTools public API.
    """

    def fill_depressions(self, input_dem: str, output_dem: str) -> None:
        """Fill closed depressions in one DEM and write the corrected raster."""
        ...

    def breach_depressions(self, input_dem: str, output_dem: str) -> None:
        """Breach depressions in one DEM when carving is preferred to filling."""
        ...

    def d8_pointer(
        self,
        input_dem: str,
        output_pointer: str,
        *,
        esri_pntr: bool = False,
    ) -> None:
        """Compute a D8 flow-direction raster from one elevation raster."""
        ...

    def d8_flow_accumulation(
        self,
        input_dem: str,
        output_acc: str,
        *,
        log: bool = True,
    ) -> None:
        """Compute a D8 flow-accumulation raster from one DEM or pointer raster."""
        ...

    def clip_raster_to_polygon(
        self,
        input_raster: str,
        input_polygon: str,
        output_raster: str,
        *,
        maintain_dimensions: bool = False,
    ) -> None:
        """Clip one raster to one polygon extent and write the resulting raster."""
        ...

    def modify_no_data_value(self, raster_path: str, *, new_value: float) -> None:
        """Rewrite the nodata marker stored in one raster file."""
        ...

    def snap_pour_points(
        self,
        pour_points: str,
        flow_accumulation: str,
        output: str,
        snap_dist: int,
    ) -> None:
        """Snap pour points to the nearest high-flow cell within ``snap_dist``."""
        ...

    def watershed(
        self,
        d8_pntr: str,
        pour_pts: str,
        output: str,
        *,
        esri_pntr: bool = False,
    ) -> None:
        """Delineate one watershed raster from D8 directions and pour points."""
        ...

    def raster_to_vector_polygons(self, input_raster: str, output_shp: str) -> None:
        """Polygonize one raster and write the result as a vector layer."""
        ...

    def raster_to_vector_points(self, input_raster: str, output_shp: str) -> None:
        """Convert raster cells to point features."""
        ...

    def trace_downslope_flowpaths(
        self,
        input_points: str,
        d8_pntr: str,
        output_raster: str,
    ) -> None:
        """Trace downslope flowpaths from point seeds over a D8 pointer raster."""
        ...

    def extract_streams(
        self,
        flow_accumulation: str,
        output_raster: str,
        *,
        threshold: float | int | None = None,
        zero_background: bool | None = None,
    ) -> None:
        """Extract one stream raster from accumulation values and one threshold."""
        ...

    def raster_streams_to_vector(
        self,
        streams_raster: str,
        d8_pointer: str,
        output_vector: str,
        *,
        esri_pointer: bool | None = None,
        all_vertices: bool | None = None,
    ) -> None:
        """Convert one stream raster + D8 pointer support into one vector network."""
        ...

    def strahler_stream_order(
        self,
        d8_pointer: str,
        streams_raster: str,
        output_raster: str,
        *,
        esri_pntr: bool | None = None,
        zero_background: bool | None = None,
    ) -> None:
        """Compute one Strahler stream-order raster."""
        ...

    def stream_link_identifier(
        self,
        d8_pointer: str,
        streams_raster: str,
        output_raster: str,
        *,
        esri_pntr: bool | None = None,
        zero_background: bool | None = None,
    ) -> None:
        """Compute one stream-link identifier raster."""
        ...

    def remove_short_streams(
        self,
        d8_pointer: str,
        streams_raster: str,
        output_raster: str,
        *,
        min_length: float | int | None = None,
        esri_pntr: bool | None = None,
    ) -> None:
        """Remove short stream segments from one stream raster."""
        ...

    def d8_mass_flux(
        self,
        dem: str,
        loading: str,
        efficiency: str,
        absorption: str,
        output: str,
    ) -> None:
        """Accumulate one mass-loading raster through a D8 routing network."""
        ...

    def polygons_to_lines(self, input_shp: str, output_shp: str) -> None:
        """Convert polygon boundaries to line features."""
        ...

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
        """Rasterize line features on the requested grid support."""
        ...

    def clip(self, input_path: str, clip_layer: str, output_path: str) -> None:
        """Clip one raster or vector dataset with another vector mask."""
        ...

    def dissolve(
        self,
        input_path: str,
        output_path: str,
        *,
        dissolve_field: str | None = None,
        snap_tolerance: float | None = None,
    ) -> None:
        """Dissolve vector features and write the resulting dataset."""
        ...

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
        """Rasterize polygons on the requested grid support."""
        ...

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
        """Rasterize points on the requested grid support."""
        ...

    def set_nodata_value(
        self,
        input_raster: str,
        output_raster: str,
        *,
        back_value: float,
    ) -> None:
        """Reassign the background / nodata marker into a new raster file."""
        ...

    def polygon_area(self, input_shp: str) -> None:
        """Add polygon area attributes to the input vector dataset."""
        ...

    def downslope_distance_to_stream(
        self,
        dem: str,
        streams: str,
        output_raster: str,
        *,
        use_dinf: bool | None = None,
    ) -> None:
        """Compute downslope distance-to-stream diagnostics on raster support."""
        ...

    def add_point_coordinates_to_table(self, input_shp: str) -> None:
        """Add point XY coordinates to the vector attribute table."""
        ...

    def extract_raster_values_at_points(
        self,
        rasters: str | list[str],
        points: str,
    ) -> None:
        """Sample one or more rasters at point locations and persist attributes."""
        ...

    def set_compress_rasters(self, enabled: bool) -> None:
        """Enable or disable raster compression when the backend supports it."""
        ...
