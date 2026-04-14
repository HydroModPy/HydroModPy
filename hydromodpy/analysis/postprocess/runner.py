"""Launcher-managed postprocessing runner.

This module centralizes postprocess tasks run after flow/transport families.
When a :class:`~hydromodpy.simulation.results.catalog.SimulationCatalog` is provided,
catchment-aggregated timeseries are also written into the store so that
display suites can consume them without reading the legacy CSV files.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

import pandas as pd

from hydromodpy.analysis.display import (
    plot_boussinesq_flow_suite,
    plot_flow_suite,
    plot_particles_suite,
    plot_transport_suite,
)
from hydromodpy.analysis.display.suites import _CATCHMENT_STATION
from hydromodpy.analysis.postprocess.flow.matching_streams import run_matching_streams
from hydromodpy.analysis.postprocess.postprocess_config import PostprocessConfig

if TYPE_CHECKING:
    from hydromodpy.data.contracts.load_result import LoadResult
    from hydromodpy.core.state.run_state import WorkflowContext

logger = logging.getLogger(__name__)


def _extract_runoff_series_m_per_day(
    runoff_result: "LoadResult | None",
) -> pd.Series | None:
    """Extract a runoff time series in m/day from a LoadResult.

    Data managers output mm/day; this converts to m/day to match the
    unit expected by the postprocess layer.
    """
    if runoff_result is None:
        return None
    from hydromodpy.process.forcing.forcing_bridge import build_forcing_series

    return build_forcing_series(
        runoff_result, unit_conversion_factor=0.001, label="runoff"
    )


class PostprocessRunner:
    """Execute optional postprocess workflows after process-family runs.

    Parameters
    ----------
    config : PostprocessConfig, optional
        Controls which postprocess tasks are enabled.
    store : SimulationCatalog, optional
        When provided, catchment-aggregated timeseries produced by
        legacy postprocessors are replicated into the store.
    sim_id : str, optional
        Simulation UUID in the store. Required when *store* is set.
    """

    def __init__(
        self,
        config: PostprocessConfig | None = None,
        *,
        store: Any = None,
        sim_id: str | None = None,
    ) -> None:
        self.config = config or PostprocessConfig()
        self.store = store
        self.sim_id = sim_id

    def after_process(self, process_type: str, state: "WorkflowContext") -> None:
        """Run postprocess tasks registered for one process family."""
        if not self.config.enabled:
            return

        normalized = str(process_type).strip().lower()
        if normalized == "flow":
            self._after_flow(state)
            return
        if normalized == "transport":
            self._after_transport(state)

    def _write_timeseries_to_store(self, df: pd.DataFrame) -> None:
        """Write catchment-aggregated timeseries into the SimulationCatalog.

        Each numeric column of *df* (except ``date``) is stored as a
        separate timeseries entry under station ``_CATCHMENT_STATION``.
        """
        if self.store is None or self.sim_id is None:
            return
        for col in df.columns:
            if col == "date":
                continue
            ts = df[col].dropna()
            if ts.empty:
                continue
            try:
                self.store.write_timeseries(
                    self.sim_id, _CATCHMENT_STATION, col, ts,
                )
            except Exception:
                logger.debug("Failed to write %s to store", col, exc_info=True)

    @staticmethod
    def _resolve_flow_model(state: "WorkflowContext"):
        """Resolve flow model from canonical run registry."""
        flow_model = state.get_model_for_solver("modflownwt")
        if flow_model is None:
            flow_model = state.get_model_for_solver("modflow6")
        return flow_model

    @staticmethod
    def _resolve_boussinesq_model(state: "WorkflowContext"):
        """Resolve the Boussinesq flow model from canonical run registry."""
        return state.get_model_for_solver("boussinesq")

    def _after_flow(self, state: "WorkflowContext") -> None:
        cfg = self.config.flow
        if not cfg.enabled:
            return

        flow_model = self._resolve_flow_model(state)
        if flow_model is None:
            boussinesq_model = self._resolve_boussinesq_model(state)
            if boussinesq_model is None:
                return
            if cfg.display:
                display_options = state.cfg.display.to_runtime_options()
                plot_boussinesq_flow_suite(state, display_options)
            return

        if cfg.timeseries.enabled:
            from hydromodpy.analysis.postprocess.timeseries import FlowTimeseriesPostprocess

            runoff = _extract_runoff_series_m_per_day(state.loaded_data.runoff)
            ts_pp = FlowTimeseriesPostprocess(
                state.setup.geographic,
                model_modflow=flow_model,
                runoff=runoff,
                datetime_format=cfg.timeseries.datetime_format,
                subbasin_results=cfg.timeseries.subbasin_results,
                intermittency_weekly=cfg.intermittency.weekly,
                intermittency_monthly=cfg.intermittency.monthly,
                intermittency_yearly=cfg.intermittency.yearly,
                intermittency_daily=cfg.intermittency.daily,
                store=self.store,
                sim_id=self.sim_id,
            )
            if hasattr(ts_pp, "mfdata") and ts_pp.mfdata is not None:
                self._write_timeseries_to_store(ts_pp.mfdata)

        if cfg.netcdf.enabled:
            from hydromodpy.analysis.postprocess.netcdf import FlowNetcdfPostprocess

            FlowNetcdfPostprocess(
                state.setup.geographic,
                model_modflow=flow_model,
                datetime_format=cfg.netcdf.datetime_format,
                store=self.store,
                sim_id=self.sim_id,
            )

        if cfg.matching_streams and state.loaded_data.hydrography is not None:
            run_matching_streams(
                geographic=state.setup.geographic,
                hydrography=state.loaded_data.hydrography,
                workspace=state.setup.workspace,
                model_modflow=flow_model,
                iteration_label=flow_model.model_name,
            )

        if cfg.display:
            display_options = state.cfg.display.to_runtime_options()
            plot_flow_suite(
                state, display_options,
                store=self.store, sim_id=self.sim_id,
            )

    def _after_transport(self, state: "WorkflowContext") -> None:
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
            from hydromodpy.analysis.postprocess.timeseries import (
                TransportTimeseriesPostprocess,
            )

            runoff = _extract_runoff_series_m_per_day(state.loaded_data.runoff)
            ts_pp = TransportTimeseriesPostprocess(
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
                store=self.store,
                sim_id=self.sim_id,
            )
            if hasattr(ts_pp, "mfdata") and ts_pp.mfdata is not None:
                self._write_timeseries_to_store(ts_pp.mfdata)

        if cfg.netcdf.enabled and (transport_model is not None or particle_model is not None):
            from hydromodpy.analysis.postprocess.netcdf import TransportNetcdfPostprocess

            TransportNetcdfPostprocess(
                state.setup.geographic,
                model_modflow=flow_model,
                model_modpath=particle_model,
                model_mt3dms=transport_model,
                datetime_format=cfg.netcdf.datetime_format,
                residence_times=cfg.netcdf.residence_times,
                concentration_seepage=cfg.netcdf.concentration_seepage,
                mass_accumulated=cfg.netcdf.mass_accumulated,
                store=self.store,
                sim_id=self.sim_id,
            )

        display_options = state.cfg.display.to_runtime_options()
        if cfg.display_particles and particle_model is not None:
            plot_particles_suite(state, display_options)
        if cfg.display_transport and transport_model is not None:
            plot_transport_suite(state, display_options)
