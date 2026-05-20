"""Adapter for the ``transport/modflow6_prt`` solver pair."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from hydromodpy.core.exceptions import SolverDivergedError
from hydromodpy.simulation.adapters.transport_helpers import required_flow_model
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, RunExecutionResult
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.modflow6.prt import Modflow6Prt


def _prt_output_suffix(runs: list[ProcessRun], run: ProcessRun) -> str:
    prt_runs = [
        planned
        for planned in runs
        if planned.process_type == "transport" and planned.solver == "modflow6_prt"
    ]
    for index, planned in enumerate(prt_runs, start=1):
        if planned.id == run.id:
            return "_prt" if index == 1 else f"_prt_s{index}"
    return "_prt"


class Modflow6PrtTransportAdapter:
    """Adapter for ``transport/modflow6_prt`` particle tracking runs."""

    process_type = "transport"
    solver_name = "modflow6_prt"
    requires: tuple[tuple[str, str], ...] = (("flow", "modflow6"),)
    produces_particles: bool = True

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks beyond the declared MODFLOW 6 flow dependency."""

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
        """Fail explicitly because particle calibration is not implemented."""
        del ctx, store, station_cells, time_index
        raise NotImplementedError(
            f"MODFLOW 6 PRT calibration extraction is not implemented for {variable!r}."
        )

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW 6 PRT particle tracking run."""

        state = ctx.state
        flow_model = required_flow_model(ctx)
        model_prt = Modflow6Prt(
            state.setup.domain,
            state.setup.transport,
            flow_model,
            model_folder=state.setup.workspace.solver_scratch_folder,
            model_name=flow_model.model_name,
            suffix_name=_prt_output_suffix(ctx.plan.runs, ctx.run),
        )
        model_prt.pre_processing()
        success = model_prt.processing(write_model=True, run_model=True, verbose=True)
        if not success:
            raise SolverDivergedError(
                f"[HMPY.E401] Particle transport solver '{ctx.run.solver}' failed for "
                f"run '{ctx.run.id}'. See {getattr(model_prt, 'full_path', '<unknown>')} "
                "for diagnostics.",
                run_id=ctx.run.id,
            )
        return RunExecutionResult(
            primary_model=model_prt,
            solver_output_dir=Path(model_prt.full_path)
            if hasattr(model_prt, "full_path")
            else None,
        )
