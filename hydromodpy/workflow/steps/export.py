"""Export step - write the data exports of the run, clean the scratch; the views follow the seal.

Every export lands under ``runs/<run>/exports/``: the run directory holds
everything the run produced. A copy out of the project is ``hmp publish``.
"""

from __future__ import annotations

import gc
import os
import shutil
import time
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core import progress
from hydromodpy.core.exceptions import ConfigError, ExportError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.progress import HINT, MILESTONE
from hydromodpy.core.state.paths import PREPROCESSING_DIRNAME, active_run_scratch, display_path
from hydromodpy.results.storage.contract import RUN_SOLVER_DIRNAME
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.run_store import run_is_persisted, run_store

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from hydromodpy.core.state.run_state import WorkflowContext

logger = get_logger(__name__)

_SCRATCH_CLEANUP_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6)


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
    announce_exports(written)
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
    from hydromodpy.results.export.run_identity import read_sealed_manifest

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


def announce_exports(written: Sequence[Path]) -> None:
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
    """Remove the solver scratch folders, or move them into the run under keep_solver_files.

    Every child of the scratch folder of the attempt goes (``<run>/.hmp/scratch/``,
    :func:`hydromodpy.results.storage.attempt.scratch_dir_for_attempt`) but the
    geographic ``_preprocessing/`` tree, which belongs to the session and which
    :func:`step_cleanup_preprocessing` is the one entitled to drop. Another run
    of the project works in another folder, so nothing of it is touched.

    Under ``keep_solver_files`` a persisted run moves those children into
    ``<run>/solver/`` instead: the seal drops ``<run>/.hmp/`` and the solver
    files must outlive it. A run without a directory keeps them in place.

    ``spare`` names folders someone else still owns: the solver folders of the
    calibration trials a session keeps for their own promotion. A child holding
    one of them stays.
    """
    workspace = ctx.setup.workspace
    if workspace is None:
        return
    scratch = workspace.solver_scratch_folder
    if not scratch.exists():
        return
    if keep_solver_files and not run_is_persisted(ctx):
        return
    spared = {Path(folder).resolve() for folder in spare}
    kept = Path(ctx.run_dir) / RUN_SOLVER_DIRNAME if keep_solver_files else None
    for target in sorted(scratch.iterdir()):
        if target.name == PREPROCESSING_DIRNAME:
            continue
        resolved = target.resolve()
        if any(folder == resolved or resolved in folder.parents for folder in spared):
            continue
        if kept is None:
            _remove_scratch_path(ctx, target)
        else:
            _keep_scratch_path(target, kept)


def _keep_scratch_path(target: Path, kept: Path) -> None:
    """Move one scratch entry into the solver folder of the run, replacing a former copy."""
    destination = kept / target.name
    if destination.is_dir():
        shutil.rmtree(destination)
    elif destination.exists():
        destination.unlink()
    kept.mkdir(parents=True, exist_ok=True)
    shutil.move(target, destination)


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
    folder = Path(workspace.solver_scratch_folder)
    for target in (folder, folder.parent) if active_run_scratch() else (folder,):
        try:
            target.rmdir()
        except OSError:
            # Still holding the preprocessing tree, a solver folder or another
            # run's folder: not ours to force.
            return


def _release_cleanup_handles(ctx: WorkflowContext) -> None:
    """Release best-effort runtime handles before deleting scratch files.

    No catalog handle survives the step that opened it, so the Zarr handles a
    catalog tracked are already closed by the time the scratch goes. A garbage
    collection drops what is left unreferenced.
    """
    gc.collect()


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
            from hydromodpy.simulation.extraction.post_run import cleanup_solver_outputs
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
            announce_exports(exported)
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
