"""Step 9 - derived fields via the :mod:`~hydromodpy.workflow.internals.derived` registry.

Runs the registered :class:`DerivedComputation` objects over the
simulation Zarr store. Each computation is responsible for its own
input check; the step itself is a thin driver that resolves
``ctx.store`` / ``ctx.sim_id``, opens the Zarr, and delegates to
``registry.apply``. Skipped derivations are logged but do not raise.

Inputs
------
``ctx`` : WorkflowContext with ``store`` and ``sim_id`` populated.

Outputs
-------
``ctx`` : unchanged; the Zarr ``/derived`` group gains any computed
fields as a side effect.
"""

from __future__ import annotations

from typing import ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.derived import registry as _default_registry
from hydromodpy.workflow.internals.state import DerivedState, ExtractedState, PipelineState

logger = get_logger(__name__)


class DeriveStep:
    """Compute derived fields registered on the :class:`DerivedRegistry`."""

    name = "derive"
    tin: ClassVar[type] = ExtractedState
    tout: ClassVar[type] = DerivedState
    config_sections: ClassVar[tuple[str, ...]] = ("postprocess",)

    def __init__(self, registry=None) -> None:
        self._registry = registry if registry is not None else _default_registry

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("DeriveStep requires 'ctx' in state.data")

        store = getattr(ctx, "store", None)
        sim_id = getattr(ctx, "sim_id", None)
        if store is None or sim_id is None:
            logger.debug("DeriveStep: no store/sim_id on ctx, skipping registry application")
            return state.advance(
                step_index=state.step_index + 1,
                step_name=self.name,
                ctx=ctx,
            )

        plan = ctx.execution.simulation_plan
        if plan is not None and not ctx.execution.lightweight:
            from hydromodpy.simulation.extraction.post_run import derive_run_outputs
            from hydromodpy.simulation.planning.plan import RunContext
            from hydromodpy.workflow.steps.planning import step_configure_results

            results_cfg = getattr(ctx, "effective_results_config", None) or step_configure_results(
                ctx.cfg.simulation.results,
                plan,
            )
            ctx.effective_results_config = results_cfg
            for run in plan.runs:
                derive_run_outputs(
                    ctx=RunContext(plan=plan, run=run, state=ctx),
                    sim_id=sim_id,
                    results_config=results_cfg,
                    store=store,
                )

        try:
            sim_zarr = store.open_zarr(sim_id)
        except Exception as exc:
            raise RuntimeError(f"DeriveStep cannot open Zarr for sim {sim_id}") from exc

        derived_names: list[str] = []
        try:
            if "head" not in sim_zarr.root:
                logger.debug(
                    "DeriveStep: no 'head' field in Zarr for sim %s, nothing to derive",
                    sim_id,
                )
                return state.advance(
                    step_index=state.step_index + 1,
                    step_name=self.name,
                    ctx=ctx,
                )

            results = self._registry.apply(sim_zarr)
            for result in results:
                if result.status == "computed":
                    derived_names.append(result.name)
                    logger.debug("DeriveStep: computed '%s'", result.name)
                else:
                    logger.debug("DeriveStep: skipped '%s' (%s)", result.name, result.reason)
        finally:
            sim_zarr.close()

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            derived_names=derived_names,
        )
