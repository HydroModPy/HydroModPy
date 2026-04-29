"""Adapter for the ``transport/modpath`` solver pair."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from hydromodpy.core.exceptions import SolverDivergedError
from hydromodpy.simulation.adapters.transport_helpers import required_flow_model
from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.modflow_nwt.modpath import Modpath


class ModpathTransportAdapter:
    """Adapter for ``transport/modpath`` runs."""

    process_type = "transport"
    solver_name = "modpath"
    requires: tuple[tuple[str, str], ...] = (("flow", "modflownwt"),)

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks for Modpath transport runs."""

    def cleanup(self, ctx: RunContext) -> None:
        """Remove the scratch directory written by this run, if any."""
        solver_output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)
        if solver_output_dir is not None:
            cleanup_solver_files(solver_output_dir)

    def extract_calibration_series(
        self,
        ctx: RunContext,
        store: Any,
        *,
        variable: str,
        station_cells: Mapping[str, tuple[int, int, int]] | None = None,
        time_index: pd.DatetimeIndex | None = None,
    ) -> pd.Series:
        """Transport runs are not calibration targets; return empty series."""
        del ctx, store, station_cells, time_index
        return pd.Series(dtype=float, name=variable)

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one Modpath particle-tracking run."""

        state = ctx.state
        flow_model = required_flow_model(ctx)
        model_modpath = Modpath(
            state.setup.domain,
            state.setup.transport,
            flow_model,
            model_folder=state.setup.workspace.solver_scratch_folder,
            model_name=flow_model.model_name,
            bin_path=state.setup.workspace.bin_path,
        )
        model_modpath.pre_processing()
        success = model_modpath.processing(write_model=True, run_model=True)
        if not success:
            raise SolverDivergedError(
                f"[HMPY.E401] Transport solver '{ctx.run.solver}' failed for run '{ctx.run.id}'. "
                f"See {getattr(model_modpath, 'full_path', '<unknown>')} for diagnostics.",
                run_id=ctx.run.id,
            )
        # Legacy post_processing / filt_processing skipped:
        # ModpathOutputAdapter.extract() reads pathlines/endpoints into
        # the SimulationCatalog (Zarr).  Shapefile generation is no longer needed.
        return RunExecutionResult(
            primary_model=model_modpath,
            solver_output_dir=Path(model_modpath.full_path)
            if hasattr(model_modpath, "full_path")
            else None,
        )
