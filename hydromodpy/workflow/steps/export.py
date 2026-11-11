"""Export step - clean the solver files and the scratch; the exports follow the seal.

The data exports and the metadata views of the ``[[export]]`` blocks are
written right after the seal (:func:`step_after_seal`), from the sealed run,
as ``hmp export <run>`` writes them. Each file carries the identity block of
the run with its label of the day, the rules it follows and the date. An
export that fails after the seal leaves the run sealed and ``completed``, and
raises :class:`~hydromodpy.core.exceptions.ExportError` naming
``hmp export <run>``.

Every export lands under ``runs/<run>/exports/``: the run directory holds
everything the run produced. A copy out of the project is ``hmp publish``.

The seal step writes ``simulation.parquet``, ``parameters.parquet``,
``provenance.json``, ``inputs.json``, ``manifest.json`` last and then ``README.md``. The
outcome and ``<run>/.hmp/`` belong to the attempt protocol, after the pipeline. A
research run has no export and no view after the seal.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from hydromodpy.core.console import progress
from hydromodpy.core.console.progress import HINT, MILESTONE
from hydromodpy.core.exceptions import ConfigError, ExportError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.stopwatch import measured
from hydromodpy.core.state.portable import display_path
from hydromodpy.results.storage.contract import RUN_SOLVER_DIRNAME
from hydromodpy.results.storage.kept import renders
from hydromodpy.results.storage.scratch import clear_scratch, drop_empty_scratch
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.workflow.record.run_store import run_is_persisted, run_store
from hydromodpy.workflow.state import PipelineState

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.results.storage.run_store import RunStore

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Store finalization
# ---------------------------------------------------------------------------


@contextmanager
def sealed_run_store(ctx: WorkflowContext) -> Iterator[RunStore]:
    """Open the store of the sealed run of ``ctx``, as ``hmp export <run>`` opens it.

    The store is opened on the run directory alone, without the persistence
    of the pipeline: what is read after the seal is what the seal certifies.
    """
    from hydromodpy.results.storage.run_store import RunStore

    workspace = getattr(getattr(ctx, "setup", None), "workspace", None)
    store = RunStore.open(Path(ctx.run_dir), workspace=getattr(workspace, "project_root", None))
    try:
        yield store
    finally:
        store.close()


def sealed_run_name(run_dir: Path) -> str | None:
    """Return the name the seal gives the run; None when the directory has no seal."""
    from hydromodpy.results.record.label import read_sealed_manifest
    from hydromodpy.results.record.manifest import is_sealed

    try:
        manifest = read_sealed_manifest(run_dir)
    except (OSError, ValueError):
        return run_dir.name if is_sealed(run_dir) else None
    return manifest.run.name if manifest is not None else None


def step_after_seal(ctx: WorkflowContext) -> list[Path]:
    """Write the data exports, then the metadata views, then schedule the recap.

    Called right after the seal of the run. The data requests of the
    ``[[export]]`` blocks read the sealed run, as ``hmp export <run>`` does,
    and each file carries the identity block of the run labelled today. A run
    at the ``research`` level writes no data export. A view (STAC, RO-Crate,
    PROV) renders ``manifest.json`` and reads the directory alone. The recap
    is read from the seal and printed once the enclosing phase has printed
    its checkmark, as the last lines of the run. Returns the files written.
    The data exports and the views are one ``export`` line each of
    ``profile.json``.

    Raises
    ------
    ExportError
        When a request fails. The run stays sealed and ``completed``; the
        message names ``hmp export <run>``, which writes the exports again.
        Every request had its turn first, the views included.
    """
    from hydromodpy.results.exporters.registry import run_formats
    from hydromodpy.results.exporters.request import export_data_requests, export_views
    from hydromodpy.workflow.runner import record_measure

    run_dir = Path(ctx.run_dir)
    requests = list(ctx.cfg.export)
    views = run_formats()
    data_requests = [request for request in requests if request.output_format not in views]
    written: list[Path] = []
    failures: list[Exception] = []
    if (
        data_requests
        and ctx.sim_id is not None
        and renders(getattr(ctx, "level", None) or "result")
    ):
        with measured("export", "data") as measure:
            try:
                with sealed_run_store(ctx) as store:
                    written.extend(export_data_requests(store, ctx.sim_id, data_requests))
            except Exception as exc:  # noqa: BLE001 - the views still have their turn
                failures.append(exc)
        record_measure(run_dir, measure, attempt=ctx.attempt)
    with measured("export", "views") as measure:
        try:
            written.extend(export_views(run_dir, requests))
        except Exception as exc:  # noqa: BLE001 - raised below with the data failure
            failures.append(exc)
    record_measure(run_dir, measure, attempt=ctx.attempt)
    _announce_exports(written)
    if failures:
        name = sealed_run_name(run_dir) or run_dir.name
        reasons = "; ".join(str(exc) for exc in failures)
        raise ExportError(
            f"run {name} is sealed; write the exports again with hmp export {name}: {reasons}"
        ) from failures[0]
    lines = _run_epilogue_lines(ctx, run_dir=run_dir)
    progress.after_phase(partial(_log_run_epilogue, lines))
    return written


def _run_epilogue_lines(ctx: WorkflowContext, *, run_dir: Path) -> tuple[str, ...]:
    """Best-effort self-teaching epilogue: identity card + next commands.

    Read from ``manifest.json``, never from the index. The seal carries
    ``duration_s`` from ``ended_at - started_at``, the figure ``hmp
    show`` reads, and the epilogue says nothing of the duration when it has none.
    """
    from hydromodpy.results.record.label import read_sealed_manifest

    sid = str(ctx.sim_id)
    try:
        manifest = read_sealed_manifest(run_dir)
    except (OSError, ValueError):
        manifest = None
    name = manifest.run.name if manifest is not None else run_dir.name
    run_duration_s = manifest.run.duration_s if manifest is not None else None
    score = manifest.score if manifest is not None else None
    metric = f" nse={score.value:.2f}" if score is not None and score.value is not None else ""
    duration = f" {run_duration_s:.0f}s" if run_duration_s else ""
    return (
        f"Run completed: {name} [{sid[:8]}]{duration}{metric}",
        f"next: hmp show {name} | hmp publish {name} --to <folder> | hmp export {name} --list",
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
    from hydromodpy.catchment.preprocess.preprocessing_cleanup import cleanup_stable_folder

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
    """Drop the solver files and clean the scratch, before the seal.

    The solver outputs the retention does not keep are dropped, then the
    scratch (:func:`step_cleanup_scratch`, :func:`step_cleanup_preprocessing`).
    Each remains addressable from notebooks via its function-based helper.
    The seal comes next (``SealStep``), then the data exports and the
    metadata views (:func:`step_after_seal`), then the figures
    (``DisplayStep``): what renders the run is written from the seal and
    carries its label. The fields stay in ``fields.zarr`` after the cleanup,
    so an export after the seal reads the same values.

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
        return ("derive",)

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("ExportStep requires 'ctx' in state.data")

        results_cfg = ctx.cfg.simulation.results
        plan = ctx.execution.simulation_plan if run_is_persisted(ctx) else None
        if plan is not None and ctx.sim_id is not None:
            from hydromodpy.solver.base.plan import RunContext
            from hydromodpy.workflow.steps.extract import retention_of
            from hydromodpy.workflow.steps.run_outputs import cleanup_solver_outputs

            retention = retention_of(ctx, plan)
            with run_store(ctx) as store:
                for run in plan.runs:
                    if not run.is_solver_backed:
                        continue
                    cleanup_solver_outputs(
                        ctx=RunContext.of(ctx, plan=plan, run=run, store=store),
                        retention=retention,
                    )
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
    """Step 12 - write the seal of the run from its store; the exports follow it.

    The seal is ``simulation.parquet``, ``parameters.parquet``, ``provenance.json``,
    ``inputs.json`` and ``manifest.json`` last, then ``README.md``. The data
    exports and the metadata views the ``[[export]]`` blocks ask for render the
    sealed run, so they are written right after it (:func:`step_after_seal`),
    and the figures after them (``DisplayStep``). The outcome is not touched
    here: the attempt protocol around the pipeline flips ``outcome.json`` to
    ``completed`` and removes ``<run>/.hmp/`` when it finds the seal, also
    when an export or a figure raised after it.
    """

    name = "seal"
    reads: ClassVar[tuple[str, ...]] = ("cfg", "ctx", "replay_of", "strict")
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
            replay_of = state.get("replay_of")
            with run_store(ctx) as store:
                if replay_of is None:
                    record = seal_completed(store)
                else:
                    record = _seal_replay(
                        store,
                        state.get("cfg"),
                        replay_of,
                        strict=bool(state.get("strict")),
                    )
            logger.info("Run %s sealed: %s", record.run.name, ctx.run_dir)
            step_after_seal(ctx)
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )


def _source_kind(replay_of: Path) -> str:
    """Return the lineage kind of a replayed source, a run and a copy alike.

    ``replay`` covers both, and ``replay.source`` says which one it was. The word
    ``published`` stays for the copy a publication writes.
    """
    return "replay"


def _seal_replay(store: RunStore, cfg: Any, replay_of: Path, *, strict: bool) -> Any:
    """Seal a replay with what it found against the run or copy it played again.

    The class is computed by the seal itself, after the field store is harmonised,
    so the values compared are the ones the seal certifies; under ``strict`` a
    deviation raises there and the attempt keeps its fields and tables with no
    seal. The producer entries that differ and the drift of the configuration and
    of the build enter the lineage, with the source id, its directory name and the
    kind of the source. The level of the source, read from its directory, lets
    a replay add keys a source below ``result`` never kept without classing
    them as deviations. The seal itself is the ordinary one.
    """
    from hydromodpy.results.record.manifest import read_seal
    from hydromodpy.results.retention import level_at
    from hydromodpy.results.storage.sealing import build_provenance
    from hydromodpy.workflow.replay_checks import (
        producer_differences,
        warn_config_drift,
        warn_producer_differences,
    )
    from hydromodpy.workflow.steps.prepare_solver.resolved import BUILD_TABLE, build_drift

    facts = store.facts
    when = datetime.now(UTC)
    producer = producer_differences(replay_of, build_provenance(facts, ended_at=when))
    warn_producer_differences(replay_of, producer)
    drift = warn_config_drift(cfg, replay_of) if cfg is not None else {}
    for item in build_drift(replay_of, store.run_dir):
        drift[f"{BUILD_TABLE}.{item.key}"] = item.record()
    facts.lineage = facts.lineage.model_copy(
        update={
            "kind": _source_kind(replay_of),
            "parent_sim_id": read_seal(replay_of).identity.sim_id,
            "parent_hint": Path(replay_of).name,
            "drift": drift,
        }
    )
    return seal_completed(
        store,
        replay_of=replay_of,
        strict=strict,
        producer=producer,
        source_level=level_at(replay_of),
    )


__all__ = ["ExportStep", "SealStep"]
