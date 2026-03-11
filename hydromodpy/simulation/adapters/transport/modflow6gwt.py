"""Adapter for the ``transport/modflow6gwt`` solver pair."""

from __future__ import annotations

from hydromodpy.simulation.adapters.transport.common import (
    required_flow_model,
    transport_output_suffix,
)
from hydromodpy.simulation.runtime.runtime_contracts import RunContext, RunExecutionResult
from hydromodpy.solver.modflow6 import Modflow6Transport


class Modflow6GwtTransportAdapter:
    """Adapter for ``transport/modflow6gwt`` runs."""

    process_type = "transport"
    solver_name = "modflow6gwt"

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW 6 GWT concentration run."""

        state = ctx.state
        flow_model = required_flow_model(ctx)
        model_transport = Modflow6Transport(
            state.setup.domain,
            state.setup.transport,
            flow_model,
            model_folder=state.setup.workspace.simulations_folder,
            model_name=flow_model.model_name,
            suffix_name=transport_output_suffix(ctx.plan, ctx.run),
        )
        model_transport.pre_processing()
        model_transport.processing(write_model=True, run_model=True, verbose=True)
        model_transport.post_processing(model_transport)
        return RunExecutionResult(primary_model=model_transport)
