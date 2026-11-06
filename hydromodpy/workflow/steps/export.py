"""Export step - write the data exports of the run, clean the scratch; the views follow the seal.

Every export lands under ``runs/<run>/exports/``: the run directory holds
everything the run produced. A copy out of the project is ``hmp publish``.
"""

from __future__ import annotations

import os
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.console import progress
from hydromodpy.core.console.progress import HINT, MILESTONE
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.portable import display_path
from hydromodpy.results.storage.contract import RUN_SOLVER_DIRNAME
from hydromodpy.results.storage.scratch import clear_scratch, drop_empty_scratch
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.workflow.record.run_store import run_is_persisted, run_store
from hydromodpy.workflow.state import PipelineState

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from hydromodpy.core.state.run_state import WorkflowContext

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Store finalization
# ---------------------------------------------------------------------------


def step_after_seal(ctx: WorkflowContext, *, wall_seconds: float = 0.0) -> list[Path]:
    """Write the metadata views the ``[[export]]`` blocks ask for, then schedule the recap.

    Called right after the seal of the run: a view (STAC, RO-Crate, PROV)
    renders ``manifest.json`` and reads the directory alone. The recap is
    read from the seal and printed once the enclosing phase has printed its
    checkmark, as the last lines of the run. Returns the views written.
    """
    from hydromodpy.results.exporters.request import export_views

    run_dir = Path(ctx.run_dir)
    written = export_views(run_dir, list(ctx.cfg.export))
    _announce_exports(written)
    lines = _run_epilogue_lines(ctx, run_dir=run_dir, wall_seconds=wall_seconds)
    progress.after_phase(partial(_log_run_epilogue, lines))
    return written


def _run_epilogue_lines(
    ctx: WorkflowContext, *, run_dir: Path, wall_seconds: float
) -> tuple[str, ...]:
    """Best-effort self-teaching epilogue: identity card + next commands.

    Read from ``manifest.json``, never from the index. ``wall_seconds`` only
    covers the ``run_solver`` step, so it understates the run; the seal
    carries ``duration_s`` from ``ended_at - started_at``, the figure
    ``hmp catalog show`` reads. ``wall_seconds`` is the fallback of a seal
    that has none.
    """
    from hydromodpy.results.run_identity import read_sealed_manifest

    sid = str(ctx.sim_id)
    try:
        manifest = read_sealed_manifest(run_dir)
    except (OSError, ValueError):
        manifest = None
    name = manifest.run.name if manifest is not None else run_dir.name
    run_duration_s = manifest.run.duration_s if manifest is not None else None
    score = manifest.score if manifest is not None else None
    metric = f" nse={score.value:.2f}" if score is not None and score.value is not None else ""
    duration_s = run_duration_s if run_duration_s is not None else wall_seconds
    duration = f" {duration_s:.0f}s" if duration_s else ""
    return (
        f"Run completed: {name} [{sid[:8]}]{duration}{metric}",
        f"next: hmp catalog show {name} | hmp publish {name} --to <folder> "
        f"| hmp export {name} --list",
    )


def _announce_exports(written: Sequence[Path]) -> None:
    """Say on the console how many files the exports of a run wrote, and where.

    The exporters name every file they write, one INFO line each. This is the
    one line the default verbosity keeps, naming the folder that holds them all.
    """
    if written:
        folder = Path(os.path.commonpath([Path(path).parent for path in written]))
        logger.info(
            "Exported %d file(s) -> %s", len(written), display_path(folder), extra=MILESTONE
        )


def _log_run_epilogue(lines: tuple[str, ...]) -> None:
    recap, next_commands = lines
    logger.info("%s", recap, extra=MILESTONE)
    logger.info("%s", next_commands, extra=HINT)


# ---------------------------------------------------------------------------
# Scratch cleanup
# ---------------------------------------------------------------------------


def step_cleanup_scratch(
    ctx: WorkflowContext,
    *,
    keep_solver_files: bool = False,
    spare: Iterable[str | Path] = (),
) -> None:
    """Empty the scratch of the attempt; under keep_solver_files a persisted run keeps its solver files.

    The rule is :func:`hydromodpy.results.storage.scratch.clear_scratch`. Under
    ``keep_solver_files`` a persisted run moves the children into
    ``<run>/solver/`` instead of dropping them: the seal drops ``<run>/.hmp/``
    and the solver files must outlive it. A run without a directory keeps them
    in place. ``spare`` names folders someone else still owns.
    """
    workspace = ctx.setup.workspace
    if workspace is None:
        return
    if keep_solver_files and not run_is_persisted(ctx):
        return
    kept = Path(ctx.run_dir) / RUN_SOLVER_DIRNAME if keep_solver_files else None
    clear_scratch(workspace.solver_scratch_folder, kept=kept, spare=spare)


def step_cleanup_preprocessing(ctx: WorkflowContext, *, keep: bool = False) -> int:
    """Remove the geographic preprocessing tree and return the bytes freed.

    :func:`step_cleanup_scratch` leaves ``.hmp/scratch/<run>/_preprocessing``
    alone: the geographic tree belongs to the session. It is dropped here
    unless ``[geographic] write_intermediates`` asked to keep the rasters on
    disk, or ``keep`` says a multi-run session owns the tree and drops it at
    the end of the session rather than at the end of a run.
    """
    from hydromodpy.spatial.geographic.preprocessing_cleanup import cleanup_stable_folder

    geographic = getattr(getattr(ctx, "setup", None), "geographic", None)
    if geographic is None:
        return 0
    geographic_cfg = getattr(ctx.cfg, "geographic", None)
    keep = keep or bool(getattr(geographic_cfg, "write_intermediates", False))
    return cleanup_stable_folder(geographic, keep=keep)


def step_drop_empty_scratch(ctx: WorkflowContext) -> None:
    """Remove the run's scratch folder, then ``.hmp/scratch/``, once nothing is left under them."""
    workspace = getattr(getattr(ctx, "setup", None), "workspace", None)
    if workspace is None:
        return
    drop_empty_scratch(Path(workspace.solver_scratch_folder))


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------


class ExportStep:
    """Write the data exports, drop the solver files, clean the scratch.

    Composed of two concerns: the ``[[export]]`` data requests
    (:func:`hydromodpy.results.exporters.request.export_data_requests`) and
    scratch cleanup
    (:func:`step_cleanup_scratch`, :func:`step_cleanup_preprocessing`). Each
    remains addressable from notebooks via its function-based helper. The
    seal comes next (``SealStep``), and the metadata views after it
    (:func:`step_after_seal`): a view renders the seal.

    Everything the store does happens inside one scope this step opens and
    closes; the scratch is cleaned after it, when no handle is left to pin a
    file.
    """

    name = "export"
    reads: ClassVar[tuple[str, ...]] = (
        "ctx",
        "export_paths",
        "keep_preprocessing",
        "kept_scratch",
    )
    writes: ClassVar[tuple[str, ...]] = (
        "ctx",
        "export_paths",
    )
    config_sections: ClassVar[tuple[str, ...]] = ()

    def depends_on(self) -> tuple[str, ...]:
        return ("display",)

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("ExportStep requires 'ctx' in state.data")

        results_cfg = ctx.cfg.simulation.results
        plan = ctx.execution.simulation_plan if run_is_persisted(ctx) else None
        if plan is not None and ctx.sim_id is not None:
            from hydromodpy.results.exporters.request import export_data_requests
            from hydromodpy.simulation.post_run import cleanup_solver_outputs
            from hydromodpy.simulation.planning.plan import RunContext

            with run_store(ctx) as store:
                # The data requests read the fields of the run, not its seal.
                exported = export_data_requests(store, ctx.sim_id, list(ctx.cfg.export))
                for run in plan.runs:
                    if not run.is_solver_backed:
                        continue
                    cleanup_solver_outputs(
                        ctx=RunContext.of(ctx, plan=plan, run=run, store=store),
                        results_config=results_cfg,
                        keep_solver_files=bool(getattr(results_cfg, "keep_solver_files", False)),
                    )
            _announce_exports(exported)
        step_cleanup_scratch(
            ctx,
            keep_solver_files=bool(getattr(results_cfg, "keep_solver_files", False)),
            spare=tuple(state.get("kept_scratch", ()) or ()),
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

        Exposes the run directory on the new state so callers can inspect it.
        """
        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("ExportStep.rebuild_state requires 'ctx' in state.data")
        existing: list[Path] = []
        run_dir = getattr(ctx, "run_dir", None)
        if run_dir is not None and Path(run_dir).is_dir():
            existing.append(Path(run_dir))
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            export_paths=existing,
        )


class SealStep:
    """Step 13 - write the seal of the run from its store; the attempt protocol closes the outcome after it.

    The seal is ``simulation.parquet``, ``parameters.parquet``, ``provenance.json``,
    ``inputs.json`` and ``manifest.json`` last, then ``README.md``. The metadata
    views the ``[[export]]`` blocks ask for render the seal, so they are written
    right after it (:func:`step_after_seal`). The outcome is not touched here: the
    attempt protocol around the pipeline flips ``outcome.json`` to ``completed``
    and removes ``<run>/.hmp/`` when it finds the seal.
    """

    name = "seal"
    reads: ClassVar[tuple[str, ...]] = ("ctx", "wall_seconds")
    writes: ClassVar[tuple[str, ...]] = ("ctx",)
    config_sections: ClassVar[tuple[str, ...]] = ()

    def depends_on(self) -> tuple[str, ...]:
        return ("export",)

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace,
        run_id: str,
    ) -> PipelineState:
        """Advance past a seal that is already on disk."""
        ctx: WorkflowContext | None = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("SealStep.rebuild_state requires 'ctx' in state.data")
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def run(self, state: PipelineState) -> PipelineState:
        ctx: WorkflowContext | None = state.get("ctx")
        if ctx is None:
            raise ConfigError("SealStep requires 'ctx' in state.data")
        if ctx.sim_id is None or not run_is_persisted(ctx):
            logger.debug("SealStep: this run keeps no store to seal, skipping")
        else:
            with run_store(ctx) as store:
                record = seal_completed(store)
            logger.info("Run %s sealed: %s", record.run.name, ctx.run_dir)
            step_after_seal(ctx, wall_seconds=float(state.get("wall_seconds", 0.0) or 0.0))
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )


__all__ = ["ExportStep", "SealStep"]
