"""Shared MMS convergence helpers.

The Method of Manufactured Solutions (MMS) verifies that a discretisation
converges to its expected theoretical order. A manufactured exact solution
``u_exact(x)`` (or ``u_exact(x, t)``) is substituted into the governing PDE
to derive a consistent forcing term; the numerical scheme is then run on a
sequence of refinements, and the L2 error is regressed against the grid
spacing in log-log space. The slope of that regression is the empirical
order of convergence.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ConvergenceResult:
    """Outcome of an MMS refinement study."""

    refinements: tuple[float, ...]
    errors: tuple[float, ...]
    order: float

    def __post_init__(self) -> None:
        if len(self.refinements) != len(self.errors):
            raise ValueError("refinements and errors must have the same length")
        if len(self.refinements) < 2:
            raise ValueError("at least two refinements are required to estimate order")


def l2_error(numerical: np.ndarray, exact: np.ndarray, *, h: float) -> float:
    """Return the grid-weighted discrete L2 error ``sqrt(h * sum((u_h - u)^2))``."""
    diff = np.asarray(numerical, dtype=float) - np.asarray(exact, dtype=float)
    return float(np.sqrt(float(h) * np.sum(diff * diff)))


def estimate_convergence_order(refinements: Iterable[float], errors: Iterable[float]) -> float:
    """Return the empirical order ``p`` from a log-log regression ``log e = p log h + c``."""
    hs = np.asarray(list(refinements), dtype=float)
    es = np.asarray(list(errors), dtype=float)
    if np.any(hs <= 0.0) or np.any(es <= 0.0):
        raise ValueError("refinements and errors must be strictly positive for log-log fit")
    slope, _intercept = np.polyfit(np.log(hs), np.log(es), 1)
    return float(slope)


def run_mms_convergence(
    case_fn: Callable[[int], tuple[float, float]],
    refinements: Iterable[int],
) -> ConvergenceResult:
    """Run ``case_fn(N)`` for each requested ``N`` and summarise the refinement study.

    ``case_fn`` must return ``(h, error)`` where ``h`` is the characteristic
    grid size used and ``error`` the L2 error with respect to the
    manufactured solution. The empirical convergence order is then returned
    alongside the individual refinements and errors so tests can assert a
    theoretical bracket such as ``|p - 2| < 0.2``.
    """
    refs: list[float] = []
    errs: list[float] = []
    for n in refinements:
        h, err = case_fn(int(n))
        refs.append(float(h))
        errs.append(float(err))
    order = estimate_convergence_order(refs, errs)
    return ConvergenceResult(
        refinements=tuple(refs),
        errors=tuple(errs),
        order=order,
    )


__all__ = [
    "ConvergenceResult",
    "estimate_convergence_order",
    "l2_error",
    "run_mms_convergence",
]
