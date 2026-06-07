"""Watershed delineation: pour points, watersheds, stream networks."""

from __future__ import annotations

from hydromodpy.spatial.delineation.whitebox_workflows_backend.raster import (
    _WhiteboxComponent,
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


__all__ = ["WhiteboxDelineationBackend"]
