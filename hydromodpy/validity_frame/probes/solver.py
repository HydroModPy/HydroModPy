from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SolverMetrics:
    solver_name: str | None = None
    iterations: int | None = None
    converged: bool | None = None
    solver_status: str | None = None


class SolverProbe:
    @staticmethod
    def collect(source: Any = None) -> SolverMetrics:
        if source is None:
            return SolverMetrics()

        solver_name = getattr(source, "solver", None)
        if solver_name is None:
            solver_name = getattr(source, "solver_name", None)

        iterations = getattr(source, "iterations", None)
        if iterations is None:
            iterations = getattr(source, "n_iter", None)

        converged = getattr(source, "converged", None)
        solver_status = getattr(source, "status", None)

        return SolverMetrics(
            solver_name=solver_name,
            iterations=iterations,
            converged=converged,
            solver_status=solver_status,
        )
