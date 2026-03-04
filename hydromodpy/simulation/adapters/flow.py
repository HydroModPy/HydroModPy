"""Adapters for flow-family simulation runs."""

from __future__ import annotations

import pickle
from pathlib import Path

from hydromodpy.simulation.adapters.base import flow_model_name
from hydromodpy.simulation.runtime import RunContext, RunExecutionResult
from hydromodpy.solver.modflow_nwt import (
    Modflow,
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)
from hydromodpy.solver.modflow6 import Modflow6


def _build_preprocess_options(state) -> ModflowPreprocessOptions:
    """Build the common flow pre-processing options from the shared settings."""

    settings = state.settings
    return ModflowPreprocessOptions(
        box=settings.box,
        sink_fill=settings.sink_fill,
        check_grid=settings.check_grid,
        plot_cross=settings.plot_cross,
        cross_ylim=tuple(settings.cross_ylim) if settings.cross_ylim else None,
    )


def _persist_pre_run_payload(workspace, model_name: str, model_modflow) -> None:
    """Write the legacy pre-run pickle expected by downstream utilities."""

    pickle_path = Path(workspace.simulations_folder) / model_name / f"results_{model_name}.pkl"
    pickle_path.parent.mkdir(parents=True, exist_ok=True)
    with pickle_path.open("wb") as fh:
        pickle.dump(
            {
                "list_model_name": [model_name],
                "list_model_modflow": [model_modflow],
            },
            fh,
        )


def _run_flow_model(ctx: RunContext, model_modflow, preprocess_options) -> RunExecutionResult:
    """Execute the shared flow-solver lifecycle for one instantiated model."""

    state = ctx.state
    model_modflow.pre_processing(
        flow=state.flow,
        domain=state.domain,
        options=preprocess_options,
    )

    _persist_pre_run_payload(state.workspace, model_modflow.model_name, model_modflow)

    success = model_modflow.processing(
        options=ModflowRunOptions(write_model=True, run_model=True, link_mt3dms=True)
    )
    if success:
        model_modflow.post_processing(
            options=ModflowPostprocessOptions(
                watertable_elevation=True,
                watertable_depth=True,
                seepage_areas=True,
                outflow_drain=True,
                accumulation_flux=True,
                intermittency_monthly=True,
            )
        )

    return RunExecutionResult(primary_model=model_modflow)


class ModflowNwtFlowAdapter:
    """Adapter for ``flow/modflownwt`` runs."""

    process_type = "flow"
    solver_name = "modflownwt"

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW-NWT flow run."""

        state = ctx.state
        preprocess_options = _build_preprocess_options(state)
        model_name = flow_model_name(ctx.plan, state.settings.model_name, ctx.run)
        model_modflow = Modflow(
            state.geographic,
            model_folder=state.workspace.simulations_folder,
            model_name=model_name,
            bin_path=state.workspace.bin_path,
            modflow_config=state.cfg.modflownwt,
            preprocess_options=preprocess_options,
        )
        return _run_flow_model(ctx, model_modflow, preprocess_options)


class Modflow6FlowAdapter:
    """Adapter for ``flow/modflow6`` runs."""

    process_type = "flow"
    solver_name = "modflow6"

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW 6 flow run."""

        state = ctx.state
        preprocess_options = _build_preprocess_options(state)
        model_name = flow_model_name(ctx.plan, state.settings.model_name, ctx.run)
        model_modflow = Modflow6(
            state.geographic,
            model_folder=state.workspace.simulations_folder,
            model_name=model_name,
            bin_path=state.workspace.bin_path,
            modflow_config=state.cfg.modflow6,
            preprocess_options=preprocess_options,
        )
        return _run_flow_model(ctx, model_modflow, preprocess_options)
