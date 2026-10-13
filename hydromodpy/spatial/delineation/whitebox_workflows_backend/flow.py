"""DEM flow analysis: pit-filling, pointer, accumulation, mass flux, downslope."""

from __future__ import annotations

from hydromodpy.spatial.delineation.whitebox_workflows_backend.raster import (
    _WhiteboxComponent,
)


class WhiteboxFlowBackend(_WhiteboxComponent):
    """DEM flow analysis: pit-filling, pointer, accumulation, mass flux, downslope.

    Depression removal runs single-threaded: it is the only stage of the chain
    whose parallel form is not reproducible, and everything downstream (D8
    pointer, accumulation, watershed, catchment area) inherits its output. It
    also runs in a child interpreter, because Whitebox can end the process that
    calls it (see :mod:`.isolated`).
    """

    def fill_depressions_raster(self, dem):
        return self._run_depression_tool("fill_depressions", dem)

    def fill_depressions(self, input_dem: str, output_dem: str) -> None:
        self._write_raster(
            self.fill_depressions_raster(self._read_raster(input_dem)),
            output_dem,
        )

    def breach_depressions_raster(
        self,
        dem,
        *,
        max_dist: int | None = None,
        max_cost: float | None = None,
        fill_deps: bool = False,
    ):
        """Breach the depressions of a DEM, optionally capped and then filled.

        With no keyword the call is the one this backend always made, so the
        tool defaults stand. ``max_dist`` is a length in cells and ``max_cost``
        bounds the cumulative lowering of one breach path, in the DEM's
        elevation unit. ``fill_deps`` fills the depressions the cap left
        unbreached. ``flat_increment`` is never passed: the tool derives it, and
        a forced value degraded the breach.
        """
        options: dict[str, object] = {}
        if max_dist is not None:
            options["max_dist"] = int(max_dist)
        if max_cost is not None:
            options["max_cost"] = float(max_cost)
        if fill_deps:
            options["fill_deps"] = True
        return self._run_depression_tool("breach_depressions_least_cost", dem, **options)

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

    def d8_flow_accumulation_raster(
        self,
        dem,
        *,
        log: bool = True,
        out_type: str = "cells",
        input_is_pointer: bool = False,
    ):
        """Accumulate on a DEM, or on a pointer raster already derived from one.

        ``input_is_pointer=True`` is measured bit-identical to the default on a
        plane, a V valley and a pitted plane: accumulating the pointer this tool
        would have computed itself changes no cell. ``out_type="catchment area"``
        returns the same counts times the cell area, exactly.
        """
        return self._run(
            self._env.d8_flow_accum,
            dem,
            out_type=out_type,
            log_transform=log,
            clip=False,
            input_is_pointer=input_is_pointer,
            esri_pntr=False,
        )

    def d8_flow_accumulation(
        self,
        input_dem: str,
        output_acc: str,
        *,
        log: bool = True,
        out_type: str = "cells",
        input_is_pointer: bool = False,
    ) -> None:
        self._write_raster(
            self.d8_flow_accumulation_raster(
                self._read_raster(input_dem),
                log=log,
                out_type=out_type,
                input_is_pointer=input_is_pointer,
            ),
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
