"""Extract step - solver result extraction, observation ingestion, modpath helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import numpy as np
import rasterio

from hydromodpy.core.exceptions import ConfigError, ExtractError
from hydromodpy.core.io.raster_io import export_tif
from hydromodpy.core.logging import get_logger
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.workflow.record.run_store import run_is_persisted, run_store
from hydromodpy.workflow.state import PipelineState

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.results.storage.kept import Retention
    from hydromodpy.solver.base.plan import SimulationPlan

logger = get_logger(__name__)


def retention_of(ctx: WorkflowContext, plan: SimulationPlan) -> Retention:
    """Return what the run keeps of its solver outputs, from its ``[simulation.results]``.

    The per-cell budget the plan keeps is ``ctx.budget_terms``, set by the
    prepare-solver step or read back from the store on a resume. A run that
    reaches here without it has it computed from the plan, as the planning does.
    """
    from hydromodpy.results.storage.kept import Retention
    from hydromodpy.workflow.steps.planning import step_configure_results

    results_cfg = ctx.cfg.simulation.results
    if ctx.budget_terms is None:
        ctx.budget_terms = step_configure_results(
            results_cfg,
            plan,
            ctx.cfg.display,
            display_active=True,
            export_requests=ctx.cfg.export,
            calibration=ctx.cfg.calibration,
            observation=ctx.cfg.observation,
            lightweight=ctx.execution.lightweight,
        )
    return Retention.of(results_cfg, ctx.budget_terms)


# ---------------------------------------------------------------------------
# Observation ingestion
# ---------------------------------------------------------------------------


def step_ingest_observations(ctx: WorkflowContext, sim_id: str, *, store: RunStore) -> None:
    """Ingest observation timeseries associated with this simulation.

    Observation ingestion is part of the scientific record. Failures abort
    the run instead of leaving its store half populated.
    """
    from hydromodpy.data.ingest.observations import ingest_observations

    try:
        ingest_observations(sim_id, store, ctx.loaded_data)
    except Exception as exc:
        # Whatever the ingestion raised, the run stops and names the simulation.
        logger.exception("Failed to ingest observations for sim %s", sim_id)
        raise ExtractError(f"Failed to ingest observations for sim {sim_id}") from exc


# ---------------------------------------------------------------------------
# Modpath ingestion helper
# ---------------------------------------------------------------------------


def restore_seepage_raster_from_store(
    run_dir: str | Path,
    base_raster_path: str | Path,
    seepage_tif_path: str | Path,
) -> bool:
    """Rebuild the seepage GeoTIFF from the store of the run in *run_dir*.

    Returns ``True`` when the raster has been written, ``False`` otherwise.
    """
    base_raster = Path(base_raster_path)
    if not base_raster.is_file():
        return False

    seepage_tif = Path(seepage_tif_path)
    try:
        with RunStore.open(run_dir) as store:
            arr = store.query_field(store.sim_id, "seepage_mask", 0)

        seepage_flat = np.asarray(arr, dtype=float).ravel()
        with rasterio.open(base_raster) as src:
            seepage_array = seepage_flat.reshape(src.height, src.width)

        os.makedirs(seepage_tif.parent, exist_ok=True)
        export_tif(str(base_raster), seepage_array, str(seepage_tif), -9999.0)
    except Exception as exc:
        # The raster is an optional product: any failure means it is not rebuilt.
        logger.debug("Failed to rebuild seepage from the run store: %s", exc)
        return False

    return seepage_tif.is_file()


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------


class ExtractStep:
    """Extract solver outputs and ingest observations into the result store."""

    name = "extract"
    reads: ClassVar[tuple[str, ...]] = ("ctx",)
    writes: ClassVar[tuple[str, ...]] = (
        "ctx",
        "extraction_summary",
    )
    config_sections: ClassVar[tuple[str, ...]] = ()

    def depends_on(self) -> tuple[str, ...]:
        return ("run_solver",)

    def run(self, state: PipelineState) -> PipelineState:
        ctx: WorkflowContext | None = state.get("ctx")
        if ctx is None:
            raise ConfigError("ExtractStep requires 'ctx' in state.data")
        if ctx.sim_id is None or not run_is_persisted(ctx):
            return state.advance(
                step_index=state.step_index + 1,
                step_name=self.name,
                ctx=ctx,
                extraction_summary={"runs": 0},
            )

        from hydromodpy.solver.base.plan import RunContext
        from hydromodpy.workflow.steps.run_outputs import extract_run_outputs

        plan = ctx.execution.simulation_plan
        if plan is None:
            raise ConfigError("ExtractStep requires execution.simulation_plan to be set")

        retention = retention_of(ctx, plan)
        extracted = 0
        with run_store(ctx) as store:
            for run in plan.runs:
                if not run.is_solver_backed:
                    continue
                extract_run_outputs(
                    ctx=RunContext.of(ctx, plan=plan, run=run, store=store),
                    store=store,
                    retention=retention,
                )
                extracted += 1
            # Observation series (hydrometry, piezometry, ...) are part of the
            # scientific record but are independent of solver extraction, so they
            # are ingested here once the store is populated for this sim. Runs
            # without observation data write nothing and do not raise.
            step_ingest_observations(ctx, ctx.sim_id, store=store)
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            extraction_summary={"runs": extracted},
        )

    def artifacts(self, state: PipelineState) -> tuple[str, ...]:
        """Return workspace-relative paths populated by extraction."""
        from hydromodpy.workflow.steps.prepare_solver.facts import store_sim_artifacts

        ctx = state.get("ctx")
        if ctx is None or not run_is_persisted(ctx):
            return ()
        sim_id = getattr(ctx, "sim_id", None)
        if not sim_id or getattr(ctx, "run_dir", None) is None:
            return ()
        with run_store(ctx) as store:
            return store_sim_artifacts(ctx, sim_id, store=store)

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Restore the post-extraction state without re-running extraction.

        The extraction artifacts already live in the Zarr / Parquet store
        opened by :class:`PrepareSolverStep`. The summary is rebuilt as a
        marker so downstream steps know the rows are durable.
        """
        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("ExtractStep.rebuild_state requires 'ctx' in state.data")
        summary = {"rebuilt_from_artifacts": True, "step": self.name}
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            extraction_summary=summary,
        )
