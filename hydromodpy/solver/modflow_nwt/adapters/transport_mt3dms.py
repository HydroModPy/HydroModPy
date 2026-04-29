"""Adapter for the ``transport/mt3dms`` solver pair."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.simulation.adapters.transport_helpers import (
    required_flow_model,
    transport_output_suffix,
)
from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.modflow_nwt.mt3dms import Mt3dms


class Mt3dmsTransportAdapter:
    """Adapter for ``transport/mt3dms`` runs."""

    process_type = "transport"
    solver_name = "mt3dms"
    requires: tuple[tuple[str, str], ...] = (("flow", "modflownwt"),)
    produces_concentration: bool = True

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks for MT3DMS transport runs."""

    def cleanup(self, ctx: RunContext) -> None:
        """Remove the scratch directory written by this run, if any."""
        solver_output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)
        if solver_output_dir is not None:
            cleanup_solver_files(solver_output_dir)

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MT3DMS concentration transport run."""

        state = ctx.state
        flow_model = required_flow_model(ctx)
        model_transport = Mt3dms(
            state.setup.domain,
            state.setup.transport,
            flow_model,
            model_folder=state.setup.workspace.solver_scratch_folder,
            model_name=flow_model.model_name,
            suffix_name=transport_output_suffix(ctx.plan, ctx.run),
            bin_path=state.setup.workspace.bin_path,
        )
        model_transport.pre_processing()
        success = model_transport.processing(write_model=True, run_model=True, verbose=True)
        if not success:
            raise RuntimeError(
                f"Transport solver '{ctx.run.solver}' failed for run '{ctx.run.id}'. "
                f"See {getattr(model_transport, 'full_path', '<unknown>')} for diagnostics."
            )
        return RunExecutionResult(
            primary_model=model_transport,
            solver_output_dir=Path(model_transport.full_path)
            if hasattr(model_transport, "full_path")
            else None,
        )
