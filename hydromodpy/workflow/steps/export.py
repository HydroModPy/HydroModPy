"""Export step - save run artifacts, finalize the store, clean scratch.

Exports published on demand land under ``share/``; the run directory itself
holds what the run produced.
"""

from __future__ import annotations

import gc
import shutil
import time
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

from hydromodpy.core.exceptions import ConfigError, ExportError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.workspace.path_registry import PREPROCESSING_DIRNAME
from hydromodpy.workflow.internals.state import DerivedState, ExportedState, PipelineState
from hydromodpy.workflow.run_catalog import run_catalog, run_is_catalogued

if TYPE_CHECKING:
    from collections.abc import Callable

    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.catalog.protocol import SimulationStore
    from hydromodpy.results.run import Run

logger = get_logger(__name__)

_SCRATCH_CLEANUP_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6)


# ---------------------------------------------------------------------------
# Run artifact persistence
# ---------------------------------------------------------------------------


def step_save_run_artifacts(
    ctx: WorkflowContext,
    wall_seconds: float,
    *,
    store: Catalog,
) -> None:
    """Save optional run artifacts."""
    analysis_cfg = getattr(ctx.cfg, "analysis", None)
    gallery_cfg = (
        getattr(analysis_cfg, "capability_gallery", None) if analysis_cfg is not None else None
    )
    if gallery_cfg is not None and getattr(gallery_cfg, "enabled", False):
        if ctx.setup.workspace is None:
            raise ExportError("Workspace is required to save run artifacts.")
        if ctx.sim_id is None:
            raise ExportError("A registered run is required to publish the capability gallery.")
        from hydromodpy.analysis.capability_gallery import (
            publish_run_to_capability_gallery,
        )
        from hydromodpy.display.runs import render_figure
        from hydromodpy.results.run import Run as _Run

        plan = ctx.execution.simulation_plan
        solvers_used = {r.solver for r in plan.runs} if plan is not None else set()

        def _render(figure_name: str, run: object, target_path: Path) -> None:
            render_figure(figure_name, cast("Run", run), save=target_path)

        publish_run_to_capability_gallery(
            run_id=str(ctx.setup.run_id),
            run_dir=store.run_dir_for(ctx.sim_id),
            config=gallery_cfg,
            solvers=tuple(str(s) for s in solvers_used),
            run=_Run(ctx.sim_id, store),
            render_figure=_render,
        )


# ---------------------------------------------------------------------------
# Intermediate cleanup
# ---------------------------------------------------------------------------


def step_drop_intermediate_budget(ctx: WorkflowContext, *, store: SimulationStore) -> None:
    """Drop the per-cell budget group when reconciliation forced it on.

    Computing is not persisting. A user who writes
    ``[simulation.results.budget] spatial_fields = true`` keeps the group.
    A user who only asked for a figure gets what the figure needs, not the
    raw per-cell budget consumed on the way: that one is written, read by
    the derive phase and by the figures, then removed. It runs last in the
    export step, after every consumer of the run and just before the store
    is sealed.
    """
    from hydromodpy.workflow.steps.planning import BUDGET_SPATIAL_FLAG

    if BUDGET_SPATIAL_FLAG not in tuple(getattr(ctx, "forced_results_flags", ())):
        return
    sim_id = ctx.sim_id
    if sim_id is None:
        return
    sz = store.open_zarr(sim_id)
    try:
        freed = sz.drop_group("budget")
    finally:
        sz.close()
    if freed:
        logger.info(
            "Dropped the intermediate per-cell budget from the store (%.2f MB freed). "
            "Set [simulation.results.budget] spatial_fields = true to keep it.",
            freed / 1e6,
        )


# ---------------------------------------------------------------------------
# Store finalization
# ---------------------------------------------------------------------------


def step_seal_store(
    ctx: WorkflowContext,
    *,
    store: SimulationStore,
    wall_seconds: float = 0.0,
    status: str = "completed",
) -> None:
    """Finalize the simulation in the store, leaving the handle open.

    Sealing is what writes ``manifest.json`` and ``provenance.json`` into the
    run directory. Whatever reads the *complete* run - the portable package
    first of all - must therefore run after this call and before the scope
    that owns ``store`` closes it.
    """
    store.finalize(ctx.sim_id, status=status)
    _log_run_epilogue(ctx, store=store, wall_seconds=wall_seconds, status=status)


def _log_run_epilogue(
    ctx: WorkflowContext, *, store: Catalog, wall_seconds: float, status: str
) -> None:
    """Best-effort self-teaching epilogue: identity card + next commands."""
    try:
        sid = str(ctx.sim_id)
        row = store.backend.fetch_one("SELECT name FROM simulations WHERE sim_id = ?", [sid])
        name = (row[0] if row else None) or sid[:8]
        nse = store.backend.fetch_one(
            "SELECT value FROM metrics WHERE sim_id = ? "
            "AND station_id = '__outlet__' AND metric_name = 'nse'",
            [sid],
        )
        metric = f" nse={nse[0]:.2f}" if nse and nse[0] is not None else ""
        duration = f" {wall_seconds:.0f}s" if wall_seconds else ""
        logger.info("Run %s: %s [%s]%s%s", status, name, sid[:8], duration, metric)
        logger.info(
            "next: hmp catalog show %s | hmp catalog diff %s <other> | hmp catalog export %s",
            name,
            name,
            name,
        )
    except Exception:  # noqa: BLE001 - the epilogue must never disrupt a run
        return


# ---------------------------------------------------------------------------
# Scratch cleanup
# ---------------------------------------------------------------------------


def step_cleanup_scratch(
    ctx: WorkflowContext,
    *,
    keep_solver_files: bool = False,
) -> None:
    """Remove the solver scratch folders unless keep_solver_files is True.

    Only the run's own children of ``.hmp/scratch/`` go: the geographic
    ``_preprocessing/`` tree living beside them belongs to the session, and
    :func:`step_cleanup_preprocessing` is the one entitled to drop it.
    """
    if keep_solver_files:
        return
    workspace = ctx.setup.workspace
    if workspace is None:
        return
    scratch = workspace.solver_scratch_folder
    if not scratch.exists():
        return
    for target in sorted(scratch.iterdir()):
        if target.name != PREPROCESSING_DIRNAME:
            _remove_scratch_path(ctx, target)


def _remove_scratch_path(ctx: WorkflowContext, target: Path) -> None:
    """Delete one scratch entry, retrying while a handle still pins it."""
    _release_cleanup_handles(ctx)
    last_error: OSError | None = None
    for delay in (0.0, *_SCRATCH_CLEANUP_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
            _release_cleanup_handles(ctx)
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
    raise ExportError(
        f"Could not remove solver scratch directory: {target}: {last_error}"
    ) from last_error


def step_cleanup_preprocessing(ctx: WorkflowContext, *, keep: bool = False) -> int:
    """Remove the geographic preprocessing tree and return the bytes freed.

    ``.hmp/scratch/_preprocessing`` hangs off the *project root*, while the
    solver scratch follows ``workspace.output_root`` when one is set: with a
    redirected output root, :func:`step_cleanup_scratch` never reaches it. It
    is dropped here unless ``[geographic] write_intermediates`` asked to keep
    the rasters on disk, or ``keep`` says a multi-run session owns the tree
    and drops it at the end of the session rather than at the end of a run.
    """
    from hydromodpy.spatial.geographic.store_ingestion import cleanup_stable_folder

    geographic = getattr(getattr(ctx, "setup", None), "geographic", None)
    if geographic is None:
        return 0
    geographic_cfg = getattr(ctx.cfg, "geographic", None)
    keep = keep or bool(getattr(geographic_cfg, "write_intermediates", False))
    return cleanup_stable_folder(geographic, keep=keep)


def step_drop_empty_scratch(ctx: WorkflowContext) -> None:
    """Remove ``.hmp/scratch/`` once nothing is left under it."""
    workspace = getattr(getattr(ctx, "setup", None), "workspace", None)
    if workspace is None:
        return
    try:
        workspace.solver_scratch_folder.rmdir()
    except OSError:
        # Still holding the preprocessing tree or a solver folder: not ours to force.
        return


def _release_cleanup_handles(ctx: WorkflowContext) -> None:
    """Release best-effort runtime handles before deleting scratch files.

    No catalog handle survives the step that opened it, so the Zarr handles a
    catalog tracked are already closed by the time the scratch goes. What is
    left to release is the delineation raster cache.
    """
    try:
        from hydromodpy.spatial.geographic.geographic_io import (
            backend_has_callables,
            resolve_delineation_backend,
        )

        backend = resolve_delineation_backend()
        if backend_has_callables(backend, "raster", "clear_raster_cache"):
            backend.raster.clear_raster_cache()
    except Exception:
        logger.debug(
            "Could not clear delineation raster cache before scratch cleanup", exc_info=True
        )

    gc.collect()


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------


class ExportStep:
    """Save artefacts, seal the run, clean the scratch.

    Composed of four concerns: gallery publication
    (:func:`step_save_run_artifacts`), automatic format export
    (``auto_export_results``), sealing (:func:`step_seal_store`) and scratch
    cleanup (:func:`step_cleanup_scratch`,
    :func:`step_cleanup_preprocessing`). Each remains addressable from
    notebooks via its function-based helper.

    Everything the catalog does happens inside one scope this step opens and
    closes; the scratch is cleaned after it, when no handle is left to pin a
    file. The portable ``.hmp`` package is written between the seal and that
    close, never before: an archive built on an unsealed run carries neither
    the manifest nor the provenance.
    """

    name = "export"
    tin: ClassVar[type] = DerivedState
    tout: ClassVar[type] = ExportedState
    config_sections: ClassVar[tuple[str, ...]] = ()

    def depends_on(self) -> tuple[str, ...]:
        return ("display",)

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("ExportStep requires 'ctx' in state.data")

        wall_seconds = float(state.get("wall_seconds", 0.0) or 0.0)

        results_cfg = getattr(ctx, "effective_results_config", None) or ctx.cfg.simulation.results
        if run_is_catalogued(ctx):
            with run_catalog(ctx) as store:
                step_save_run_artifacts(ctx, wall_seconds, store=store)
                plan = ctx.execution.simulation_plan
                packaged = plan is not None and ctx.sim_id is not None
                export_package: Callable[[], None] | None = None
                if packaged:
                    from hydromodpy.core.state.run_state import RunState
                    from hydromodpy.simulation.extraction.post_run import (
                        auto_export_package,
                        auto_export_results,
                        cleanup_solver_outputs,
                    )
                    from hydromodpy.simulation.planning.plan import RunContext

                    export_cfg = ctx.cfg.export
                    save_catalog = bool(results_cfg.persistence.save_catalog)
                    auto_export_results(
                        sim_id=ctx.sim_id,
                        store=store,
                        export_config=export_cfg,
                        save_catalog=save_catalog,
                        run_id=ctx.setup.run_id,
                    )
                    for run in plan.runs:
                        if not run.is_solver_backed:
                            continue
                        cleanup_solver_outputs(
                            ctx=RunContext(plan=plan, run=run, state=RunState.of(ctx), store=store),
                            results_config=results_cfg,
                            keep_solver_files=bool(
                                getattr(results_cfg, "keep_solver_files", False)
                            ),
                        )
                    export_package = partial(
                        auto_export_package,
                        sim_id=ctx.sim_id,
                        store=store,
                        export_config=export_cfg,
                        save_catalog=save_catalog,
                        run_id=ctx.setup.run_id,
                    )
                step_drop_intermediate_budget(ctx, store=store)
                # Seal first, package second: the archive must carry the
                # manifest and the provenance the seal writes, and the packer
                # reads the index and the live Zarr through the same handle.
                step_seal_store(ctx, store=store, wall_seconds=wall_seconds)
                if export_package is not None:
                    export_package()
        step_cleanup_scratch(
            ctx,
            keep_solver_files=bool(getattr(results_cfg, "keep_solver_files", False)),
        )
        step_cleanup_preprocessing(ctx, keep=bool(state.get("keep_preprocessing")))
        step_drop_empty_scratch(ctx)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def artifacts(self, state: PipelineState) -> tuple[str, ...]:
        """Return workspace-relative paths exported by this step."""
        ctx = state.get("ctx")
        if ctx is None:
            return ()
        workspace = getattr(getattr(ctx, "setup", None), "workspace", None)
        project_root: Path | None = getattr(workspace, "project_root", None)
        if project_root is None:
            return ()
        found: list[str] = []
        for path_obj in state.get("export_paths", ()) or ():
            try:
                candidate = Path(path_obj)
            except TypeError:
                continue
            if not candidate.exists():
                continue
            try:
                rel = candidate.relative_to(project_root).as_posix()
            except ValueError:
                continue
            found.append(rel)
        return tuple(sorted(set(found)))

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Restore the post-export state without re-finalising the store.

        Lists the run directory currently on disk and exposes it on the new
        state so callers can inspect it.
        """
        from hydromodpy.core.state.paths import runs_dir_for

        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("ExportStep.rebuild_state requires 'ctx' in state.data")
        existing: list[Path] = []
        ws = getattr(getattr(ctx, "setup", None), "workspace", None)
        project_root: Path | None = getattr(ws, "project_root", None)
        sim_id = getattr(ctx, "sim_id", None)
        if project_root is not None and sim_id and run_is_catalogued(ctx):
            with run_catalog(ctx) as store:
                run_dir = store.run_dir_for(sim_id)
            if run_dir.is_dir():
                existing.append(run_dir)
        elif project_root is not None:
            existing.extend(p for p in runs_dir_for(project_root).glob("*") if p.is_dir())
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            export_paths=existing,
        )
