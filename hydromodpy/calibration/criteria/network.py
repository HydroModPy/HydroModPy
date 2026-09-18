"""The stream-network criterion, as one object.

It compares a simulated seepage network to a mapped one, in both directions, and
its cost is the imbalance between the two. Nothing in it is fitted to a record,
which is why it had to disguise itself to enter a signature built for a series.

The estimator carries the difference the objective could not express. Under
``distance_gap`` the cost IS the absolute signed residual of Eq. 1, so a bracket
that closes on the zero of that residual and a report that names the smallest
cost as best agree by construction. Under ``distance_mean`` they do not: the mean
of the two distances has its own interior minimum, which sits nowhere near the
crossing, so a root search pointed at it reports a trial it never converged to.
That is the difference ``signed`` declares.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

import numpy as np

from hydromodpy.calibration.criteria.base import CriterionRequirements, CriterionResult

Estimator = Literal["distance_gap", "distance_mean"]


def distance_pair(simulated: Sequence[float] | Any) -> tuple[float, float]:
    """Read the ``(D_so, D_os)`` pair a network output produces."""
    values = np.asarray(simulated, dtype=float).ravel()
    if values.size != 2:
        raise ValueError(
            "a distance metric scores the pair (D_so, D_os) a network output "
            f"produces; got {values.size} value(s)."
        )
    return float(values[0]), float(values[1])


class NetworkCriterion:
    """The two published estimators of the stream-network method."""

    def __init__(self, estimator: Estimator) -> None:
        if estimator not in ("distance_gap", "distance_mean"):
            raise ValueError(
                f"unknown network estimator {estimator!r}; "
                "choose 'distance_gap' (Eq. 1) or 'distance_mean' (Eq. 2)."
            )
        self.name = str(estimator)
        self._estimator: Estimator = estimator

    def requirements(self) -> CriterionRequirements:
        """No observations, no time axis, and a signed residual only for Eq. 1.

        It reads a network output and nothing else: the pair it scores exists on
        no other support, and pointed at a series it would read two of its
        values as two distances.
        """
        return CriterionRequirements(
            needs_observations=False,
            has_time_axis=False,
            signed=self._estimator == "distance_gap",
            cost_is_dimensionless=False,
            reads_supports=("network",),
            cost_unit="m",
        )

    def score(
        self,
        simulated: Sequence[float] | Any,
        observed: Sequence[float] | Any | None = None,
    ) -> CriterionResult:
        """Return the cost in metres, with the pair it was read from."""
        del observed  # structurally absent, see the module docstring
        d_so, d_os = distance_pair(simulated)
        signed = d_so - d_os
        cost = abs(signed) if self._estimator == "distance_gap" else 0.5 * (d_so + d_os)
        return CriterionResult(
            cost=float(cost),
            signed_residual=float(signed) if self._estimator == "distance_gap" else None,
            diagnostics={"D_so": d_so, "D_os": d_os, "J_signed": signed},
        )


__all__ = ["Estimator", "NetworkCriterion", "distance_pair"]
