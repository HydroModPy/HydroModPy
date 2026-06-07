"""DEM flow analysis: pit-filling, pointer, accumulation, mass flux, downslope."""

from __future__ import annotations

from hydromodpy.spatial.delineation.whitebox_workflows_backend.raster import (
    _WhiteboxComponent,
)


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

    def downslope_distance_to_stream_raster(
        self,
        dem,
        streams,
        *,
        use_dinf: bool | None = None,
    ):
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


__all__ = ["WhiteboxFlowBackend"]
