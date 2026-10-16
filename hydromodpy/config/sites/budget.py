"""What a plan costs before it runs: cases, solves, threads, scratch.

``hmp run project.toml --dry-run`` writes nothing and prints these numbers.
``[sites.run] parallel`` is the budget of solves side by side: a simulation
takes one, a calibration takes its ``[calibration] parallel``. The scratch of
a kept solve was measured between 0.6 and 4.8 GiB (audit of 2026-10-14,
reader R04); the plan announces the range for the solves it keeps.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from hydromodpy.config.sites.expansion import PlanDraft
from hydromodpy.config.sites.models import PARALLEL_CEILING
from hydromodpy.core.exceptions import ConfigError

SCRATCH_PER_KEPT_SOLVE_GIB: tuple[float, float] = (0.6, 4.8)
"""Scratch one kept solve takes, low and high, as measured on the example 04."""

CALIBRATION_PARALLEL_CEILING = 1
"""Budget of a campaign of calibrations until the launch is measured."""


class BudgetError(ConfigError):
    """The plan asks for more than the machine, or the measurements, allow."""


@dataclass(frozen=True, slots=True)
class PlanBudget:
    """The numbers of a plan, as ``--dry-run`` prints them."""

    n_cases: int
    n_sites: int
    n_recipes: int
    n_done: int
    n_calibrations: int
    parallel: int
    peak_solves: int
    threads_per_case: int
    cores: int
    kept_solves: int
    scratch_gib: tuple[float, float]

    @property
    def n_pending(self) -> int:
        """Cases without a sealed run of the same hash."""
        return self.n_cases - self.n_done


def plan_budget(draft: PlanDraft, *, cores: int | None = None) -> PlanBudget:
    """Return the budget of a draft on a machine with *cores* cores."""
    run = draft.sites_config.run
    pending = [case for case in draft.cases if not case.done]
    peak = _peak_solves([case.solves for case in pending], run.parallel)
    kept = sum(case.kept_solves for case in pending)
    low, high = SCRATCH_PER_KEPT_SOLVE_GIB
    return PlanBudget(
        n_cases=len(draft.cases),
        n_sites=len(draft.sites),
        n_recipes=len(draft.recipes),
        n_done=len(draft.cases) - len(pending),
        n_calibrations=sum(1 for case in draft.cases if case.kind == "calibration"),
        parallel=run.parallel,
        peak_solves=peak,
        threads_per_case=run.threads_per_case,
        cores=cores if cores is not None else (os.cpu_count() or 1),
        kept_solves=kept,
        scratch_gib=(kept * low, kept * high),
    )


def _peak_solves(solves: list[int], budget: int) -> int:
    """Return the most solves running together under a greedy fill of *budget*.

    Cases start in order while their solves fit in the budget; a case larger
    than the budget runs alone, so the peak may exceed it.
    """
    peak = 0
    running = 0
    for count in sorted(solves, reverse=True):
        if running and running + count > budget:
            peak = max(peak, running)
            running = 0
        running += count
    return max(peak, running)


def check_run_budget(budget: PlanBudget, *, force: bool = False) -> None:
    """Refuse a budget above the measured ceilings, unless *force*.

    The ceilings stand until the launch measurements set the real values:
    :data:`~hydromodpy.config.sites.models.PARALLEL_CEILING` solves side by
    side, :data:`CALIBRATION_PARALLEL_CEILING` for a campaign of
    calibrations, and never more solves times threads than cores.
    """
    if force:
        return
    if budget.parallel > PARALLEL_CEILING:
        raise BudgetError(
            f"[sites.run] parallel = {budget.parallel} is above {PARALLEL_CEILING}, the "
            "ceiling until the launch is measured; lower it or pass --force."
        )
    if budget.n_calibrations and budget.parallel > CALIBRATION_PARALLEL_CEILING:
        raise BudgetError(
            f"[sites.run] parallel = {budget.parallel} for a campaign of "
            f"{budget.n_calibrations} calibration(s); the ceiling is "
            f"{CALIBRATION_PARALLEL_CEILING} until the launch is measured. Lower it or pass --force."
        )
    product = budget.peak_solves * budget.threads_per_case
    if product > budget.cores:
        raise BudgetError(
            f"{budget.peak_solves} solves x {budget.threads_per_case} threads = {product} on "
            f"{budget.cores} cores; lower [sites.run] parallel or threads_per_case, or pass --force."
        )


def dry_run_lines(draft: PlanDraft, budget: PlanBudget) -> list[str]:
    """Return the lines ``hmp run --dry-run`` prints for a ``[sites]`` project."""
    low, high = budget.scratch_gib
    lines = [
        f"[dry-run] project : {draft.project_file}",
        f"[dry-run] plan    : {budget.n_cases} cases ({budget.n_sites} sites x "
        f"{budget.n_recipes} recipes), {budget.n_done} already sealed, "
        f"{budget.n_pending} to run",
        f"[dry-run] solves  : {budget.parallel} side by side, peak {budget.peak_solves} solves x "
        f"{budget.threads_per_case} threads on {budget.cores} cores",
        f"[dry-run] scratch : {budget.kept_solves} kept solve(s), {low:.1f} to {high:.1f} GiB",
    ]
    run = draft.sites_config.run
    lines.append(
        f"[dry-run] dev     : threads_per_case = {run.threads_per_case}, keep_attempts = "
        f"{run.keep_attempts}, prepare_parallel = {run.prepare_parallel}"
    )
    for case in draft.cases:
        state = "sealed" if case.done else case.kind
        lines.append(f"[dry-run]   {case.case_id}: {state}, {case.solves} solve(s)")
    return lines


__all__ = [
    "CALIBRATION_PARALLEL_CEILING",
    "SCRATCH_PER_KEPT_SOLVE_GIB",
    "BudgetError",
    "PlanBudget",
    "check_run_budget",
    "dry_run_lines",
    "plan_budget",
]
