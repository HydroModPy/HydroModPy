"""Adapter for the ``flow/modflownwt`` solver pair.

This module contains only the MODFLOW-NWT-specific construction step. The
shared execution lifecycle itself lives in ``flow.common``.
"""

from __future__ import annotations

from hydromodpy.simulation.adapters.flow.modflow_common import (
    build_preprocess_options,
    resolve_run_model_name,
    run_flow_model,
)
from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.modflow_nwt import Modflow


class ModflowNwtFlowAdapter:
    """Bridge one planned ``flow/modflownwt`` run to the ``Modflow`` API."""

    process_type = "flow"
    solver_name = "modflownwt"

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW-NWT flow run.

        The method is intentionally thin:

        - resolve the shared preprocessing options,
        - derive the stable model folder name for this run,
        - build the concrete ``Modflow`` object,
        - delegate the rest of the lifecycle to ``run_flow_model``.
        """

        state = ctx.state
        preprocess_options = build_preprocess_options(state)
        model_name = resolve_run_model_name(ctx)
        # This is the only MODFLOW-NWT-specific part of the adapter: wiring
        # the correct config section into the concrete solver class.
        model_modflow = Modflow(
            state.setup.geographic,
            model_folder=state.setup.workspace.simulations_folder,
            model_name=model_name,
            bin_path=state.setup.workspace.bin_path,
            modflow_config=state.cfg.modflownwt,
            preprocess_options=preprocess_options,
        )
        return run_flow_model(ctx, model_modflow, preprocess_options)
