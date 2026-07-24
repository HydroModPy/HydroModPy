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

from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError, ExtractError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.derived import DerivedResult
from hydromodpy.workflow.internals.derived import registry as _default_registry
from hydromodpy.workflow.internals.state import DerivedState, ExtractedState, PipelineState

if TYPE_CHECKING:
    from hydromodpy.simulation.planning.results_config import ResultsConfig

logger = get_logger(__name__)


class DeriveStep:
    """Compute derived fields registered on the :class:`DerivedRegistry`."""

    name = "derive"
    tin: ClassVar[type] = ExtractedState
    tout: ClassVar[type] = DerivedState
    config_sections: ClassVar[tuple[str, ...]] = ("postprocess",)

    def __init__(self, registry=None) -> None:
        self._registry = registry if registry is not None else _default_registry

    def depends_on(self) -> tuple[str, ...]:
        return ("extract",)

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace,
        run_id: str,
    ) -> PipelineState:
        """Restore derived names by listing the Zarr ``/derived`` group."""
        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("DeriveStep.rebuild_state requires 'ctx' in state.data")
        derived_names: list[str] = []
        store = getattr(ctx, "store", None)
        sim_id = getattr(ctx, "sim_id", None)
        if store is not None and sim_id is not None:
            try:
                sim_zarr = store.open_zarr(sim_id)
            except Exception:
                sim_zarr = None
            if sim_zarr is not None:
                try:
                    derived_group = sim_zarr.root.get("derived")
                    if derived_group is not None:
                        derived_names = sorted(str(k) for k in derived_group.array_keys())
                except Exception:
                    derived_names = []
                finally:
                    _close_owned_zarr_handle(sim_zarr)
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            derived_names=derived_names,
        )

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

        # Solver models are consumed up to extraction only (provenance backfill,
        # calibration trial metrics; trials cap the pipeline at extract). Past
        # this point they are dead weight: a transient flopy model carries the
        # full stress-period data, which reaches GBs on multi-thousand-period
        # runs. Release them before the derive stacks allocate.
        ctx.execution.models_by_run_id.clear()

        plan = ctx.execution.simulation_plan
        results_cfg = getattr(ctx, "effective_results_config", None) or ctx.cfg.simulation.results

        # Registry first (needs head): it can persist watertable_elevation/depth,
        # seepage_mask and budget fluxes slab-wise. These are OFF by default:
        # figures recompute them on the fly from head, so only the config-enabled
        # fields are materialised. Running it before compute_derived lets an enabled
        # pass reuse the slab-written water table.
        enabled = self._enabled_registry_names(results_cfg)
        forced = tuple(getattr(ctx, "forced_results_flags", ()) or ())
        derived_names: list[str] = []
        try:
            sim_zarr = store.open_zarr(sim_id)
        except Exception as exc:
            raise ExtractError(f"DeriveStep cannot open Zarr for sim {sim_id}") from exc
        try:
            if enabled and "head" in sim_zarr.root:
                results = self._registry.apply(sim_zarr, names=enabled)
                for result in results:
                    if result.status == "computed":
                        derived_names.append(result.name)
                        logger.debug("DeriveStep: computed '%s'", result.name)
                    else:
                        self._log_skipped_derived(result, forced=forced)
            elif not enabled:
                logger.debug("DeriveStep: no derived field enabled, registry skipped")
            else:
                logger.debug(
                    "DeriveStep: no 'head' field in Zarr for sim %s, registry skipped",
                    sim_id,
                )
        finally:
            _close_owned_zarr_handle(sim_zarr)

        # compute_derived (opt-in transport/flux variables) plus catchment aggregation.
        # Runs regardless of head, as before; its seepage step is now a guarded no-op and
        # water-table readers find the registry's slab-written field.
        if plan is not None and not ctx.execution.lightweight:
            from hydromodpy.simulation.extraction.post_run import derive_run_outputs
            from hydromodpy.simulation.planning.plan import RunContext

            for run in plan.runs:
                if not run.is_solver_backed:
                    continue
                derive_run_outputs(
                    ctx=RunContext(plan=plan, run=run, state=ctx),
                    sim_id=sim_id,
                    results_config=results_cfg,
                    store=store,
                )

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            derived_names=derived_names,
        )

    @staticmethod
    def _log_skipped_derived(result: DerivedResult, *, forced: tuple[str, ...]) -> None:
        """Report a registry field that was enabled and did not get computed.

        Loud by default: the config asked for the field, so an empty ``/derived``
        entry cannot pass in silence. ``fluxes_from_budget`` is the exception
        when the per-cell budget was switched on by reconciliation rather than
        by the user: nobody asked for that field, it only rode along.
        """
        from hydromodpy.workflow.steps.planning import BUDGET_SPATIAL_FLAG

        if result.name == "fluxes_from_budget" and BUDGET_SPATIAL_FLAG in forced:
            logger.debug("DeriveStep: skipped '%s' (%s)", result.name, result.reason)
            return
        logger.warning(
            "Derived field '%s' is enabled in [simulation.results] but was not computed: %s.",
            result.name,
            result.reason,
        )

    @staticmethod
    def _enabled_registry_names(results_cfg: ResultsConfig) -> list[str]:
        """Registry derived fields to persist, per the results config.

        Watertable/seepage fields are off by default: figures recompute them on
        the fly from head. ``fluxes_from_budget`` rides on the budget spatial
        opt-in. A dependent field pulls in its upstream (watertable_elevation).
        """
        derived = results_cfg.derived
        names: set[str] = set()
        if derived.watertable_elevation:
            names.add("watertable_elevation")
        if derived.watertable_depth:
            names.update(("watertable_elevation", "watertable_depth"))
        if derived.seepage_areas:
            names.update(("watertable_elevation", "seepage_mask"))
        if results_cfg.budget.spatial_fields:
            names.add("fluxes_from_budget")
        return sorted(names)


def _close_owned_zarr_handle(sim_zarr) -> None:
    """Close catalog-owned Zarr handles, but leave borrowed handles open."""

    if getattr(sim_zarr, "_on_close", None) is not None:
        sim_zarr.close()
