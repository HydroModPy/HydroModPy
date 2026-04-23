"""Adapter for the ``transport/modflow6gwt`` solver pair."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.simulation.adapters.transport_helpers import (
    required_flow_model,
    transport_output_suffix,
)
from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.modflow6.modflow6 import Modflow6Transport


class Modflow6GwtTransportAdapter:
    """Adapter for ``transport/modflow6gwt`` runs."""

    process_type = "transport"
    solver_name = "modflow6gwt"
    requires: tuple[tuple[str, str], ...] = (("flow", "modflow6"),)
    produces_concentration: bool = True

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW 6 GWT concentration run."""

        state = ctx.state
        flow_model = required_flow_model(ctx)
        model_transport = Modflow6Transport(
            state.setup.domain,
            state.setup.transport,
            flow_model,
            model_folder=state.setup.workspace.solver_scratch_folder,
            model_name=flow_model.model_name,
            suffix_name=transport_output_suffix(ctx.plan, ctx.run),
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
