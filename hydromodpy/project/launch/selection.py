"""Which cases a launch starts, with which flags, within which budget.

Why
---
The local launcher and the SLURM array write the same plan and start the same
workers, so the rules that choose the cases, the flags of a worker and the
budget of solves live here, and neither launcher imports the other.

Selection
---------
By default every case that is not completed, not running and not stale is
started; a completed case that holds no sealed run (no completed session,
for a calibration) of the hash of the plan is started again, the rule of
``--dry-run``. ``only`` names statuses (``failed``, ``stale``...) or case
ids (shell patterns allowed); ``site`` keeps the cases of one site;
``resume`` keeps the cases with an unfinished attempt (partial, failed,
aborted), which resume in place.

A calibration case started again reopens its session (``--resume``) when
that session ran the configuration of the plan, unless ``fresh``: a rerun
is not a new version. A calibration session a live worker may still hold
(running, or stale with its death not proven) is never started again
without ``force``.

Budget
------
:func:`effective_parallel` and :func:`effective_prepare_parallel` refuse a
launch above the ceilings of :mod:`hydromodpy.project.launch.sites.budget` without
``force``.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from hydromodpy.config.sites import (
    PARALLEL_CEILING,
    PREPARE_PARALLEL_CEILING,
    SitesConfig,
    SitesRunConfig,
)
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.project.launch.children import PlannedCase
from hydromodpy.project.launch.sites.budget import CALIBRATION_PARALLEL_CEILING, BudgetError
from hydromodpy.project.launch.sites.expansion import case_is_done
from hydromodpy.project.launch.status import CaseState, case_state
from hydromodpy.results.outcome import death_is_proven

UNFINISHED_STATES = frozenset({"partial", "failed", "aborted"})
"""States of an attempt ``resume`` picks up."""

LAUNCHABLE_BY_DEFAULT = frozenset({"planned", "partial", "failed", "aborted"})
"""States started when ``only`` names nothing."""


def sites_run_config(project_root: Path) -> SitesRunConfig:
    """Return ``[sites.run]`` of the project, read from ``project.toml`` and its chain."""
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    marker = Path(project_root) / PROJECT_MARKER_FILENAME
    if not marker.is_file():
        # Every other verb of a [sites] project (plan, status, run) refuses a folder
        # without the marker, so this one does not read around it.
        raise ConfigError(f"{project_root} holds no {PROJECT_MARKER_FILENAME}: not a project")
    document = load_toml_with_base_config(marker)
    section = document.get("sites")
    if not isinstance(section, Mapping):
        raise ConfigError(f"{project_root}/{PROJECT_MARKER_FILENAME} declares no [sites]")
    return SitesConfig.model_validate(section).run


def _matches(case: PlannedCase, state: CaseState, tokens: Sequence[str]) -> bool:
    return any(
        token == state.status or fnmatch.fnmatchcase(case.case_id, token) for token in tokens
    )


def _differs_from_plan(project_root: Path, case: PlannedCase, state: CaseState) -> bool:
    """Whether a completed case holds no sealed run, or completed session, of the plan's hash.

    A calibration case is done when one of its sessions holds the hash: the
    run it promoted carries the parameters of the best trial, so its own hash
    never matches the plan.
    """
    if state.status != "completed":
        return False
    kind = "calibration" if case.workflow == "calibration" else "simulation"
    return not case_is_done(Path(project_root), case.case_id, case.config_hash, kind)


def _death_is_proven(state: CaseState) -> bool:
    """Whether the outcome of *state* names a process of this host that is gone."""
    outcome = state.outcome or {}
    return death_is_proven(outcome.get("host"), outcome.get("pid"))


def _session_held(case: PlannedCase, state: CaseState, *, force: bool) -> str | None:
    """Why a calibration whose session a live worker may hold is not started, or None.

    A simulation worker refuses a live case at its claim; a calibration
    worker opens its session without that check, so the launcher holds it.
    """
    if case.workflow != "calibration" or state.session_hash is None:
        return None
    if state.status == "running":
        return "running"
    if state.status == "stale" and not force and not _death_is_proven(state):
        return "stale; its death is not proven, pass --force once it is known dead"
    return None


def select_cases(
    project_root: Path,
    cases: Sequence[PlannedCase],
    *,
    only: Sequence[str] = (),
    site: str | None = None,
    resume: bool = False,
    force: bool = False,
) -> tuple[list[tuple[PlannedCase, CaseState]], list[tuple[PlannedCase, str]]]:
    """Return the cases to start with their state, and the cases left out with why."""
    tokens = [token for item in only for token in str(item).split(",") if token.strip()]
    chosen: list[tuple[PlannedCase, CaseState]] = []
    left: list[tuple[PlannedCase, str]] = []
    for case in cases:
        if site is not None and case.site != site:
            continue
        state = case_state(project_root, case.case_id)
        if tokens:
            if _matches(case, state, tokens):
                held = _session_held(case, state, force=force)
                if held is None:
                    chosen.append((case, state))
                else:
                    left.append((case, held))
            continue
        if resume:
            if state.status in UNFINISHED_STATES:
                chosen.append((case, state))
            continue
        if state.status in LAUNCHABLE_BY_DEFAULT or _differs_from_plan(project_root, case, state):
            chosen.append((case, state))
        elif state.status in ("running", "stale"):
            left.append((case, state.status))
    return chosen, left


def effective_parallel(
    requested: int,
    cases: Sequence[PlannedCase],
    *,
    threads_per_case: int,
    force: bool,
    cores: int | None = None,
) -> int:
    """Return the budget of solves the launch uses, or refuse it.

    Raises :class:`~hydromodpy.project.launch.sites.budget.BudgetError` above the
    ceilings, or for a case that solves more side by side than the budget,
    unless *force*.
    """
    if requested < 1:
        raise BudgetError(f"parallel = {requested}: the budget of solves is at least 1")
    if force:
        return requested
    widest = max(cases, key=lambda case: case.solves, default=None)
    if widest is not None and widest.solves > requested:
        # A case wider than the budget would start alone and pass it: refuse it here,
        # so the ceilings below hold for the widest case too.
        raise BudgetError(
            f"[calibration] parallel = {widest.solves} of case {widest.case_id} exceeds "
            f"[sites.run] parallel = {requested}; lower the one or raise the other, or pass "
            "--force."
        )
    if requested > PARALLEL_CEILING:
        raise BudgetError(
            f"parallel = {requested} is above {PARALLEL_CEILING}, the measured ceiling "
            "(16 runs side by side held 14 GiB); lower it or pass --force."
        )
    calibrations = sum(1 for case in cases if case.workflow == "calibration")
    if calibrations and requested > CALIBRATION_PARALLEL_CEILING:
        raise BudgetError(
            f"parallel = {requested} for a campaign of {calibrations} calibration(s); the "
            f"measured ceiling is {CALIBRATION_PARALLEL_CEILING} (8 solves side by side held "
            f"6.5 GiB on 21 000 cells). Set [sites.run] parallel = "
            f"{CALIBRATION_PARALLEL_CEILING}, or pass --force."
        )
    available = cores if cores is not None else (os.cpu_count() or 1)
    if requested * threads_per_case > available:
        raise BudgetError(
            f"{requested} solves x {threads_per_case} threads = {requested * threads_per_case} "
            f"on {available} cores; lower parallel or threads_per_case, or pass --force."
        )
    return requested


def effective_prepare_parallel(requested: int, *, force: bool) -> int:
    """Return the cases prepared side by side, or refuse above the ceiling without *force*."""
    if requested < 1:
        raise BudgetError(f"prepare_parallel = {requested}: at least one case is prepared")
    if requested > PREPARE_PARALLEL_CEILING and not force:
        raise BudgetError(
            f"prepare_parallel = {requested} is above {PREPARE_PARALLEL_CEILING}, the measured "
            "ceiling; lower it or pass --force."
        )
    return requested


def _resumes_its_session(case: PlannedCase, state: CaseState, *, force: bool) -> bool:
    """Whether a calibration case reopens its latest session instead of a new version.

    Only a session that ran the configuration of the plan is reopened: a
    changed configuration is a new version, as for a simulation.
    """
    if state.session_hash is None or state.session_hash != case.config_hash:
        return False
    if state.status in UNFINISHED_STATES:
        return True
    return state.status == "stale" and (force or _death_is_proven(state))


def worker_flags(
    case: PlannedCase, state: CaseState, *, frozen: bool, fresh: bool, force: bool
) -> list[str]:
    """Return the flags of the worker of one case.

    A simulation takes the attempt flags. A calibration takes a bare
    ``--resume`` when its unfinished session is reopened; ``fresh`` opens a
    new version of the session instead.
    """
    flags = ["--frozen"] if frozen else []
    if case.workflow == "calibration":
        if not fresh and _resumes_its_session(case, state, force=force):
            flags.append("--resume")
        return flags
    if case.workflow != "simulation":
        return flags
    if fresh:
        flags.append("--fresh")
    if force:
        flags.append("--force")
    if state.status in UNFINISHED_STATES or state.status == "stale":
        flags += ["--resume", case.case_id]
    return flags


__all__ = [
    "LAUNCHABLE_BY_DEFAULT",
    "UNFINISHED_STATES",
    "effective_parallel",
    "effective_prepare_parallel",
    "select_cases",
    "sites_run_config",
    "worker_flags",
]
