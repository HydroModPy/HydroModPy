"""Launcher-managed postprocessing runner.

This module centralizes postprocess tasks run after flow/transport families.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display import plot_flow_suite, plot_particles_suite, plot_transport_suite
from hydromodpy.postprocess.flow.matching_streams import run_matching_streams
from hydromodpy.postprocess.postprocess_config import PostprocessConfig

if TYPE_CHECKING:
    from hydromodpy.simulation.state.run_state import LauncherRunState


class PostprocessRunner:
    """Execute optional postprocess workflows after process-family runs."""

    def __init__(self, config: PostprocessConfig | None = None) -> None:
        self.config = config or PostprocessConfig()

    def after_process(self, process_type: str, state: "LauncherRunState") -> None:
        """Run postprocess tasks registered for one process family."""
        if not self.config.enabled:
            return

        normalized = str(process_type).strip().lower()
        if normalized == "flow":
            self._after_flow(state)
            return
        if normalized == "transport":
            self._after_transport(state)

    @staticmethod
    def _resolve_flow_model(state: "LauncherRunState"):
        """Resolve flow model from canonical run registry."""
        flow_model = state.get_model_for_solver("modflownwt")
        if flow_model is None:
            flow_model = state.get_model_for_solver("modflow6")
        return flow_model

    def _after_flow(self, state: "LauncherRunState") -> None:
        cfg = self.config.flow
        if not cfg.enabled:
            return

        flow_model = self._resolve_flow_model(state)
        if flow_model is None:
            return

        if cfg.timeseries.enabled:
            from hydromodpy.postprocess.timeseries import FlowTimeseriesPostprocess

            runoff = state.loaded_data.climatic.runoff if state.loaded_data.climatic is not None else None
            FlowTimeseriesPostprocess(
                state.setup.geographic,
                model_modflow=flow_model,
                runoff=runoff,
                datetime_format=cfg.timeseries.datetime_format,
                subbasin_results=cfg.timeseries.subbasin_results,
                intermittency_weekly=cfg.intermittency.weekly,
                intermittency_monthly=cfg.intermittency.monthly,
                intermittency_yearly=cfg.intermittency.yearly,
                intermittency_daily=cfg.intermittency.daily,
            )

        if cfg.netcdf.enabled:
            from hydromodpy.postprocess.netcdf import FlowNetcdfPostprocess

            FlowNetcdfPostprocess(
                state.setup.geographic,
                model_modflow=flow_model,
                datetime_format=cfg.netcdf.datetime_format,
            )

        if cfg.matching_streams and state.loaded_data.hydrography is not None:
            run_matching_streams(
                geographic=state.setup.geographic,
                hydrography=state.loaded_data.hydrography,
                workspace=state.setup.workspace,
                iteration_label=flow_model.model_name,
                from_calib=False,
            )

        if cfg.display:
            display_options = state.cfg.display.to_runtime_options()
            plot_flow_suite(state, display_options)

    def _after_transport(self, state: "LauncherRunState") -> None:
        cfg = self.config.transport
        if not cfg.enabled:
            return

        flow_model = self._resolve_flow_model(state)
        if flow_model is None:
            return

        particle_model = state.get_model_for_solver("modpath")
        transport_model = state.get_model_for_solver("mt3dms")
        if transport_model is None:
            transport_model = state.get_model_for_solver("modflow6gwt")

        if cfg.timeseries.enabled and transport_model is not None:
            from hydromodpy.postprocess.timeseries import (
                TransportTimeseriesPostprocess,
            )

            runoff = state.loaded_data.climatic.runoff if state.loaded_data.climatic is not None else None
            TransportTimeseriesPostprocess(
                state.setup.geographic,
                model_modflow=flow_model,
                runoff=runoff,
                model_modpath=particle_model,
                model_mt3dms=transport_model,
                suffix_name=cfg.timeseries.suffix_name,
                datetime_format=cfg.timeseries.datetime_format,
                subbasin_results=cfg.timeseries.subbasin_results,
                intermittency_weekly=cfg.intermittency.weekly,
                intermittency_monthly=cfg.intermittency.monthly,
                intermittency_yearly=cfg.intermittency.yearly,
                intermittency_daily=cfg.intermittency.daily,
                residence_times=cfg.timeseries.residence_times,
                concentration_seepage=cfg.timeseries.concentration_seepage,
                mass_accumulated=cfg.timeseries.mass_accumulated,
            )

        if cfg.netcdf.enabled and (transport_model is not None or particle_model is not None):
            from hydromodpy.postprocess.netcdf import TransportNetcdfPostprocess

            TransportNetcdfPostprocess(
                state.setup.geographic,
                model_modflow=flow_model,
                model_modpath=particle_model,
                model_mt3dms=transport_model,
                datetime_format=cfg.netcdf.datetime_format,
                residence_times=cfg.netcdf.residence_times,
                concentration_seepage=cfg.netcdf.concentration_seepage,
                mass_accumulated=cfg.netcdf.mass_accumulated,
            )

        display_options = state.cfg.display.to_runtime_options()
        if cfg.display_particles and particle_model is not None:
            plot_particles_suite(state, display_options)
        if cfg.display_transport and transport_model is not None:
            plot_transport_suite(state, display_options)
