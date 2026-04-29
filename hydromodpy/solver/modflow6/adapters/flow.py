"""Adapter for the ``flow/modflow6`` solver pair.

This module contains only the MODFLOW 6-specific construction step. The
shared flow execution lifecycle lives in
``hydromodpy.solver.modflow_common.flow_adapter_helpers``.
"""

from __future__ import annotations

from collections.abc import Mapping

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.modflow6.modflow6 import Modflow6
from hydromodpy.solver.modflow_common.flow_adapter_helpers import (
    build_preprocess_options,
    resolve_run_model_name,
    run_flow_model,
)


class Modflow6FlowAdapter:
    """Bridge one planned ``flow/modflow6`` run to the ``Modflow6`` API."""

    process_type = "flow"
    solver_name = "modflow6"
    requires: tuple[tuple[str, str], ...] = ()

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks for MODFLOW 6 flow runs."""

    def cleanup(self, ctx: RunContext) -> None:
        """Remove the scratch directory written by this run, if any."""
        solver_output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)
        if solver_output_dir is not None:
            cleanup_solver_files(solver_output_dir)

    @staticmethod
    def _solver_runtime_cache(state) -> dict[tuple[str, str, str], Modflow6]:
        cache = getattr(state.setup, "_flow_solver_runtime_cache", None)
        if isinstance(cache, dict):
            return cache
        cache = {}
        state.setup._flow_solver_runtime_cache = cache
        return cache

    @staticmethod
    def _reuse_solver_model_enabled(state) -> bool:
        overrides = getattr(state.setup, "flow_runtime_overrides", None)
        return bool(isinstance(overrides, Mapping) and overrides.get("reuse_solver_model", False))

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW 6 flow run.

        The method is intentionally narrow in scope:

        - resolve the shared preprocessing options,
        - derive the stable model folder name for this run,
        - build the concrete ``Modflow6`` object,
        - delegate the common run lifecycle to ``run_flow_model``.
        """

        state = ctx.state
        preprocess_options = build_preprocess_options(state)
        model_name = resolve_run_model_name(ctx)
        model_modflow = None
        if self._reuse_solver_model_enabled(state):
            cache = self._solver_runtime_cache(state)
            cache_key = (self.solver_name, str(ctx.run.id), str(model_name))
            model_modflow = cache.get(cache_key)
            if model_modflow is None:
                model_modflow = Modflow6(
                    state.setup.geographic,
                    model_folder=state.setup.workspace.simulations_folder,
                    model_name=model_name,
                    bin_path=state.setup.workspace.bin_path,
                    modflow_config=state.cfg.modflow6,
                    preprocess_options=preprocess_options,
                )
                cache[cache_key] = model_modflow
        # This is the only MODFLOW 6-specific part of the adapter: wiring the
        # MF6 config block into the concrete solver implementation.
        if model_modflow is None:
            model_modflow = Modflow6(
                state.setup.geographic,
                model_folder=state.setup.workspace.solver_scratch_folder,
                model_name=model_name,
                bin_path=state.setup.workspace.bin_path,
                modflow_config=state.cfg.modflow6,
                preprocess_options=preprocess_options,
            )
        return run_flow_model(ctx, model_modflow, preprocess_options)
