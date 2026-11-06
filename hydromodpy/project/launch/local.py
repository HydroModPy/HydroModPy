"""The local launcher of a ``[sites]`` project: plan, prepare, launch, count, index.

Why
---
The launcher decides nothing a worker can decide from the disk. It holds the
lease of the project, reads the current plan, picks the cases to start,
runs the prepare phase, then starts one ``hmp run plan/<hash>/<case>.toml
--frozen`` per case in a process of its own, as many side by side as the
budget of solves allows. It writes every event to
``jobs/<stamp>-local/journal.jsonl``, writes ``failed`` for a child that
died without writing its outcome, merges the private data cache of each
child into the shared one, and refreshes the index after every end. The
worker claims its directory, skips an identical sealed run, resumes an
interrupted attempt in place or starts a new version: none of that is
decided here.

Budget
------
``[sites.run] parallel`` is the budget of solves side by side: a simulation
takes one, a calibration takes its ``[calibration] parallel`` (the widest
of its phases). A case wider than the budget is refused without ``force``,
so the budget is never passed by one case running alone. The ceilings
were measured on 22 cores (:mod:`hydromodpy.project.launch.sites.budget`): above
sixteen solves, or more than eight for a campaign that holds a calibration,
or more than eight cases prepared side by side, the launch is refused
without ``force``; and never more solves times threads than cores. A launch
``until = "data"`` solves nothing, so only the prepare ceiling holds.

Selection
---------
By default every case that is not completed, not running and not stale is
started; a completed case that holds no sealed run (no completed session,
for a calibration) of the hash of the plan is started again, the rule of
``--dry-run``. ``only`` names statuses (``failed``, ``stale``...) or case
ids (shell patterns allowed); ``site`` keeps the cases of one site;
``resume`` keeps the cases with an unfinished attempt (partial, failed,
aborted), which resume in place. ``until = "data"`` stops after the prepare
phase.

A calibration case started again reopens its session (``--resume``) when
that session ran the configuration of the plan, unless ``fresh``: a rerun
is not a new version. A calibration session a live worker may still hold
(running, or stale with its death not proven) is never started again
without ``force``.
"""

from __future__ import annotations

import os
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.config.sites import (
    SitesRunConfig,
)
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME, data_cache_path_for
from hydromodpy.project.launch.children import (
    Child,
    PlannedCase,
    close_dead_child,
    exit_of,
    log_tail,
    merge_child_cache,
    planned_cases,
    start_child,
    worker_command,
)
from hydromodpy.project.launch.journal import Journal, new_job_dir
from hydromodpy.project.launch.lease import launcher_lease
from hydromodpy.project.launch.prepare import (
    POLL_INTERVAL_S,
    prepare_cases,
    workspace_data_dir,
    write_lockfile_once,
)
from hydromodpy.project.launch.selection import (
    effective_parallel,
    effective_prepare_parallel,
    select_cases,
    sites_run_config,
    worker_flags,
)
from hydromodpy.project.launch.sites.expansion import PlanDraft, expand_plan
from hydromodpy.project.launch.sites.plan import write_plan_draft
from hydromodpy.project.launch.status import CaseState, case_state, plan_is_stale
from hydromodpy.results.plan_store import StoredPlan, current_plan_hash, read_plan
from hydromodpy.results.storage.json_io import readable

logger = get_logger(__name__)

UNTIL_DATA = "data"
"""``until`` value that stops the launch after the prepare phase."""


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    """How one case of the launch ended, as its directory says it."""

    case_id: str
    site: str | None
    recipe: str | None
    status: str
    exit_code: int | None
    signal: int | None = None
    rel_dir: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LaunchReport:
    """What one launch did."""

    project_root: Path
    plan_hash: str
    journal: Path
    cases: tuple[CaseOutcome, ...]
    lockfile: Path | None = None
    until: str | None = None
    prepared: tuple[str, ...] = ()
    """Cases whose prepare phase ended well."""

    @property
    def n_completed(self) -> int:
        """Cases whose directory says completed."""
        return sum(1 for case in self.cases if case.status == "completed")

    @property
    def n_failed(self) -> int:
        """Cases that ended failed, aborted, partial or stale, or failed to prepare."""
        return sum(1 for case in self.cases if case.status != "completed")


def plan_project(
    project_root: Path,
    *,
    set_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    force: bool = False,
    config_path: Path | None = None,
) -> PlanDraft:
    """Expand the project and write ``plan/<hash>/``; return the draft.

    *config_path* is ``project.toml`` by default, or one recipe file (that
    recipe alone on every site). A case still running refuses a new plan
    unless *force*
    (:class:`~hydromodpy.project.launch.sites.plan.RunningCaseError`); a case that
    does not validate refuses the plan
    (:class:`~hydromodpy.project.launch.sites.issues.PlanError`).
    """
    root = Path(project_root).resolve()
    path = (
        Path(config_path).resolve() if config_path is not None else root / PROJECT_MARKER_FILENAME
    )
    draft = expand_plan(
        root, path, set_overrides=set_overrides, env=os.environ if env is None else env
    )
    write_plan_draft(root, draft, force=force)
    return draft


def _current_plan(project_root: Path) -> StoredPlan:
    """Return the current plan, writing it from ``project.toml`` when missing or stale."""
    if current_plan_hash(project_root) is not None:
        stored = readable(read_plan, project_root)
        if stored is not None and not plan_is_stale(project_root, stored):
            return stored
    plan_project(project_root)
    return read_plan(project_root)


def run_plan(
    project_root: Path,
    *,
    parallel: int | None = None,
    prepare_parallel: int | None = None,
    only: Sequence[str] = (),
    site: str | None = None,
    until: str | None = None,
    fresh: bool = False,
    force: bool = False,
    resume: bool = False,
) -> LaunchReport:
    """Launch the current plan of *project_root* and return what happened.

    The plan is written from ``project.toml`` first when the project has none
    or when its files changed. Raises
    :class:`~hydromodpy.project.launch.lease.LeaseHeldError` when another
    launcher holds the project, and
    :class:`~hydromodpy.project.launch.sites.budget.BudgetError` for a budget above
    the ceilings without *force*.

    *force* lifts four guards at once: the budget ceilings (``parallel``,
    ``prepare_parallel``, the calibration ceiling, solves times threads over
    the cores); the lease of a launcher still alive, which this one takes
    over; and, passed to the worker of each simulation, the skip of an
    identical sealed run and the refusal of a stale case whose death is not
    proven; a stale calibration session is reopened under the same rule.
    :func:`plan_project` takes it too, to plan over a running case.
    """
    if until not in (None, UNTIL_DATA):
        raise ConfigError(
            f"until = {until!r}: a [sites] project stops after its prepare phase "
            f"(until = {UNTIL_DATA!r}) or runs to the end"
        )
    root = Path(project_root).resolve()
    run_config = sites_run_config(root)
    with launcher_lease(root, force=force):
        stored = _current_plan(root)
        cases = planned_cases(stored)
        chosen, left = select_cases(root, cases, only=only, site=site, resume=resume, force=force)
        budget = _solve_budget(run_config, parallel, [case for case, _ in chosen], until, force)
        preparing = effective_prepare_parallel(
            run_config.prepare_parallel if prepare_parallel is None else prepare_parallel,
            force=force,
        )
        job_dir = new_job_dir(root, "local")
        journal = Journal(job_dir)
        journal.append(
            "launch_start",
            plan_hash=stored.plan.plan_hash,
            n_cases=len(chosen),
            parallel=budget,
            only=list(only),
            site=site,
            until=until,
            fresh=fresh,
            force=force,
            resume=resume,
        )
        for case, why in left:
            journal.append("case_skipped", case_id=case.case_id, reason=why)
        outcomes, lockfile, prepared = _launch(
            root,
            job_dir,
            journal,
            chosen,
            run_config=run_config,
            parallel=budget,
            prepare_parallel=preparing,
            until=until,
            fresh=fresh,
            force=force,
        )
        report = LaunchReport(
            project_root=root,
            plan_hash=stored.plan.plan_hash,
            journal=journal.path,
            cases=tuple(outcomes),
            lockfile=lockfile,
            until=until,
            prepared=prepared,
        )
        journal.append("launch_end", n_completed=report.n_completed, n_failed=report.n_failed)
    return report


def _solve_budget(
    run_config: SitesRunConfig,
    parallel: int | None,
    cases: Sequence[PlannedCase],
    until: str | None,
    force: bool,
) -> int:
    """Return how many solves run side by side, as asked or as the cores of this machine allow."""
    requested = run_config.parallel if parallel is None else parallel
    if parallel is None and "parallel" not in run_config.model_fields_set:
        # The default is a default, not a request: it bends to the cores of this
        # machine instead of being refused on a box with fewer than eight.
        cores = os.cpu_count() or 1
        requested = max(1, min(requested, cores // max(1, run_config.threads_per_case)))
    # A launch that stops after the prepare phase starts no solve.
    if until == UNTIL_DATA:
        return requested
    return effective_parallel(
        requested, cases, threads_per_case=run_config.threads_per_case, force=force
    )


def _launch(
    root: Path,
    job_dir: Path,
    journal: Journal,
    chosen: list[tuple[PlannedCase, CaseState]],
    *,
    run_config: SitesRunConfig,
    parallel: int,
    prepare_parallel: int,
    until: str | None,
    fresh: bool,
    force: bool,
) -> tuple[list[CaseOutcome], Path | None, tuple[str, ...]]:
    """Prepare then run *chosen*; return the outcomes, the lockfile and the prepared cases."""
    from hydromodpy.data.provenance.lockfile import project_lockfile_path

    if not chosen:
        return [], None, ()
    data_dir = workspace_data_dir(chosen[0][0].path)
    shared_cache = data_cache_path_for(data_dir)
    outcomes: list[CaseOutcome] = []
    to_prepare = [case for case, state in chosen if fresh or state.status == "planned"]
    lockfile: Path | None = None
    failed_prepare: set[str] = set()
    prepared_ok: tuple[str, ...] = ()
    if to_prepare:
        prepared = prepare_cases(
            root,
            job_dir,
            to_prepare,
            journal=journal,
            shared_cache=shared_cache,
            parallel=prepare_parallel,
            threads_per_case=run_config.threads_per_case,
        )
        failed_prepare = {item.case_id for item in prepared if not item.ok}
        prepared_ok = tuple(item.case_id for item in prepared if item.ok)
        lockfile = write_lockfile_once(root, data_dir, journal)
        for item in prepared:
            if item.ok:
                continue
            case = next(case for case, _ in chosen if case.case_id == item.case_id)
            outcomes.append(
                CaseOutcome(
                    case_id=case.case_id,
                    site=case.site,
                    recipe=case.recipe,
                    status="failed",
                    exit_code=item.exit_code,
                    signal=item.signal,
                    error="the prepare phase failed; see the journal",
                )
            )
    if until == UNTIL_DATA:
        return outcomes, lockfile, prepared_ok
    frozen = project_lockfile_path(root).is_file()
    runnable = [(case, state) for case, state in chosen if case.case_id not in failed_prepare]
    if failed_prepare and run_config.on_error == "raise":
        for case, _ in runnable:
            journal.append("case_skipped", case_id=case.case_id, reason="on_error = raise")
        return outcomes, lockfile, prepared_ok
    outcomes.extend(
        _run_cases(
            root,
            job_dir,
            journal,
            runnable,
            shared_cache=shared_cache,
            parallel=parallel,
            threads_per_case=run_config.threads_per_case,
            stop_on_error=run_config.on_error == "raise",
            frozen=frozen,
            fresh=fresh,
            force=force,
        )
    )
    return outcomes, lockfile, prepared_ok


def _run_cases(
    root: Path,
    job_dir: Path,
    journal: Journal,
    chosen: list[tuple[PlannedCase, CaseState]],
    *,
    shared_cache: Path,
    parallel: int,
    threads_per_case: int,
    stop_on_error: bool,
    frozen: bool,
    fresh: bool,
    force: bool,
) -> list[CaseOutcome]:
    """Run the workers of *chosen* under a budget of *parallel* solves side by side."""
    pending = deque(chosen)
    running: list[Child] = []
    used = 0
    stopped = False
    outcomes: list[CaseOutcome] = []
    try:
        while pending or running:
            while pending and not stopped:
                case, state = pending[0]
                if running and used + case.solves > parallel:
                    break
                pending.popleft()
                flags = worker_flags(case, state, frozen=frozen, fresh=fresh, force=force)
                child = start_child(
                    job_dir,
                    case,
                    worker_command(case, flags),
                    phase="run",
                    threads_per_case=threads_per_case,
                )
                journal.append(
                    "case_start",
                    case_id=case.case_id,
                    pid=child.process.pid,
                    solves=case.solves,
                    flags=flags,
                    log=str(child.log_path),
                )
                running.append(child)
                used += case.solves
            reaped = [child for child in running if child.process.poll() is not None]
            for child in reaped:
                running.remove(child)
                used -= child.case.solves
                outcome = _close_case(root, child, journal=journal, shared_cache=shared_cache)
                outcomes.append(outcome)
                if stop_on_error and outcome.status != "completed" and not stopped:
                    stopped = True
                    for case, _ in pending:
                        journal.append(
                            "case_skipped", case_id=case.case_id, reason="on_error = raise"
                        )
                    pending.clear()
            if not reaped:
                time.sleep(POLL_INTERVAL_S)
    except BaseException:
        # SIGINT or SIGTERM of the launcher: the children end their attempt in order.
        for child in running:
            child.process.terminate()
        for child in running:
            child.process.wait()
            outcomes.append(_close_case(root, child, journal=journal, shared_cache=shared_cache))
        raise
    return outcomes


def _close_case(root: Path, child: Child, *, journal: Journal, shared_cache: Path) -> CaseOutcome:
    """Close what a reaped worker left: its outcome, its private cache, the index."""
    from hydromodpy.results.catalog.indexer import index_new_runs

    returncode = child.process.returncode
    assert returncode is not None
    exit_code, signal = exit_of(returncode)
    if exit_code != 0:
        close_dead_child(root, child, exit_code, signal)
    merged = merge_child_cache(shared_cache, child, journal=journal)
    try:
        index_new_runs(root)
    except Exception as exc:  # noqa: BLE001 - the run is on disk; the index is derived
        logger.warning("Index not refreshed after %s: %s", child.case.case_id, exc)
        journal.append("index_failed", case_id=child.case.case_id, error=str(exc))
    state = case_state(root, child.case.case_id)
    status = state.status
    if status == "planned":
        # The worker wrote no directory: it refused the case or died before its claim.
        status = "failed"
    outcome = state.outcome or {}
    error = outcome.get("error") or None
    error_text = None if error is None else f"{error.get('type')}: {error.get('message')}"
    if status != "completed" and error_text is None and exit_code != 0:
        error_text = f"exit code {exit_code}"
    if merged is None:
        # The run is on disk, but the data it fetched never reached the shared cache.
        status = "failed"
        error_text = "its private data cache could not be merged; see the journal"
    journal.append(
        "case_end",
        case_id=child.case.case_id,
        status=status,
        exit_code=exit_code,
        signal=signal,
        rel_dir=state.rel_dir,
        error=error,
        log=str(child.log_path),
        log_tail=[]
        if status == "completed"
        else (outcome.get("log_tail") or log_tail(child.log_path)),
        merged_entries=merged or 0,
    )
    return CaseOutcome(
        case_id=child.case.case_id,
        site=child.case.site,
        recipe=child.case.recipe,
        status=status,
        exit_code=exit_code,
        signal=signal,
        rel_dir=state.rel_dir,
        error=error_text,
    )


__all__ = [
    "UNTIL_DATA",
    "CaseOutcome",
    "LaunchReport",
    "plan_project",
    "run_plan",
]
