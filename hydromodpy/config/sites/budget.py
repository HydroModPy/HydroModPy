"""What a plan costs before it runs: cases, solves, threads, scratch.

``hmp run project.toml --dry-run`` writes nothing and prints these numbers.
``[sites.run] parallel`` is the budget of solves side by side: a simulation
takes one, a calibration takes its ``[calibration] parallel``. The ceilings
the launcher refuses above without ``--force`` are
:data:`~hydromodpy.config.sites.models.PARALLEL_CEILING`,
:data:`~hydromodpy.config.sites.models.PREPARE_PARALLEL_CEILING` and
:data:`CALIBRATION_PARALLEL_CEILING`, measured on 22 cores
(:func:`hydromodpy.project.launch.selection.effective_parallel`). A solve of a
campaign of calibrations held 0.8 GiB on 21 000 cells. The scratch of
a kept solve was measured between 0.6 and 4.8 GiB (audit of 2026-10-14,
reader R04); the plan announces the range for the solves it keeps.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from hydromodpy.config.sites.expansion import PlanDraft
from hydromodpy.core.exceptions import ConfigError

SCRATCH_PER_KEPT_SOLVE_GIB: tuple[float, float] = (0.6, 4.8)
"""Scratch one kept solve takes, low and high, as measured on the example 04."""

CALIBRATION_PARALLEL_CEILING = 8
"""Budget of a campaign that holds a calibration: 8 solves held 6.5 GiB, no loss, equal costs."""


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
    "dry_run_lines",
    "plan_budget",
]
