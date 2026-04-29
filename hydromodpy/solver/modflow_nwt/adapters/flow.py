"""Adapter for the ``flow/modflownwt`` solver pair.

This module contains only the MODFLOW-NWT-specific construction step. The
shared execution lifecycle lives in
``hydromodpy.solver.modflow_common.flow_adapter_helpers``.
"""

from __future__ import annotations

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.modflow_common.flow_adapter_helpers import (
    build_preprocess_options,
    resolve_run_model_name,
    run_flow_model,
)
from hydromodpy.solver.modflow_nwt.nwt import ModflowNwt


class ModflowNwtFlowAdapter:
    """Bridge one planned ``flow/modflownwt`` run to the ``ModflowNwt`` API."""

    process_type = "flow"
    solver_name = "modflownwt"
    requires: tuple[tuple[str, str], ...] = ()

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks for MODFLOW-NWT flow runs."""

    def cleanup(self, ctx: RunContext) -> None:
        """Remove the scratch directory written by this run, if any."""
        solver_output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)
        if solver_output_dir is not None:
            cleanup_solver_files(solver_output_dir)

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW-NWT flow run.

        The method is intentionally thin:

        - resolve the shared preprocessing options,
        - derive the stable model folder name for this run,
        - build the concrete ``ModflowNwt`` object,
        - delegate the rest of the lifecycle to ``run_flow_model``.
        """

        state = ctx.state
        preprocess_options = build_preprocess_options(state)
        model_name = resolve_run_model_name(ctx)
        # This is the only MODFLOW-NWT-specific part of the adapter: wiring
        # the correct config section into the concrete solver class.
        model_modflow = ModflowNwt(
            state.setup.geographic,
            model_folder=state.setup.workspace.solver_scratch_folder,
            model_name=model_name,
            bin_path=state.setup.workspace.bin_path,
            modflow_config=state.cfg.modflownwt,
            preprocess_options=preprocess_options,
        )
        return run_flow_model(ctx, model_modflow, preprocess_options)
