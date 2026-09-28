"""The hydrographic-network distance, as one criterion object.

It compares a simulated seepage network to a mapped one, in both directions, and
its cost is built from the two distances.

The name says what the criterion measures, and the citation says who published
it. It was called ``NetworkCriterion`` in a module called ``network``, in a
repository where a network is also a set of SFR reaches and a list of hosts a
capability contacts. The protocol above it is already named after its method,
``matching_hydrographic_network``, and the figure that draws it after what it
draws; this is the third and last name of the trio. Nothing in it is fitted to a record,
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
    """Read the ``(D_so, D_os)`` pair a one-bound network output produces."""
    values = np.asarray(simulated, dtype=float).ravel()
    if values.size != 2:
        raise ValueError(
            "a distance metric scores the pair (D_so, D_os) a network output "
            f"produces; got {values.size} value(s)."
        )
    return float(values[0]), float(values[1])


def distance_pairs(simulated: Sequence[float] | Any) -> list[tuple[float, float]]:
    """Read the ``(D_so, D_os)`` pairs a vector of network values holds, in order.

    One pair per bound in the cost. A two-bound output produces two, each
    already multiplied by its bound's weight, so summing over the pairs is the
    weighted cost; a one-bound output produces one, unweighted.
    """
    values = np.asarray(simulated, dtype=float).ravel()
    if values.size == 0 or values.size % 2:
        raise ValueError(
            "a distance metric scores (D_so, D_os) pairs, one per bound a network output "
            f"scores; got {values.size} value(s)."
        )
    return [(float(values[i]), float(values[i + 1])) for i in range(0, values.size, 2)]


def distance_gap(simulated: Sequence[float] | Any) -> float:
    """``abs(D_so - D_os)``, Eq. 1: the cost the root search drives to zero.

    It takes no observed vector, structurally: the criterion balances an excess
    of simulated stream against a missing one, both simulated. That is why the
    zero of this cost is an intersection and not a minimum of distance.

    With two bounds the cost is ``w_min |J_min| + w_max |J_max|``, the sum over
    the weighted pairs. A minimiser needs one number, and this is it; it is
    not the log-space interpolation between two roots a root search returns,
    and a weighted sum of two V-shaped costs tends to settle on one root or
    the other rather than between them.
    """
    return float(sum(abs(d_so - d_os) for d_so, d_os in distance_pairs(simulated)))


def distance_mean(simulated: Sequence[float] | Any) -> float:
    """``(D_so + D_os) / 2``, Eq. 2. A diagnostic, and a cost only outside.

    It is legitimate as a cost in the outer loop that picks between structures
    already balanced at ``J = 0``; using it inside, in place of Eq. 1, is a
    different estimator, and nothing puts its interior minimum at the crossing.
    With two bounds, the weighted sum of each bound's ``Doptim``.
    """
    return float(sum(0.5 * (d_so + d_os) for d_so, d_os in distance_pairs(simulated)))


class HydrographicNetworkDistance:
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
        """Return the cost in metres, with the pairs it was read from.

        One pair has a signed residual. Two bounds have two, which no single
        number carries: the residual is then None and a root search reads the
        two signed components the output publishes.
        """
        del observed  # structurally absent, see the module docstring
        pairs = distance_pairs(simulated)
        gap = self._estimator == "distance_gap"
        cost = distance_gap(simulated) if gap else distance_mean(simulated)
        if len(pairs) == 1:
            d_so, d_os = pairs[0]
            return CriterionResult(
                cost=float(cost),
                signed_residual=float(d_so - d_os) if gap else None,
                diagnostics={"D_so": d_so, "D_os": d_os, "J_signed": d_so - d_os},
            )
        diagnostics: dict[str, float] = {}
        for index, (d_so, d_os) in enumerate(pairs):
            diagnostics[f"weighted_D_so_{index}"] = d_so
            diagnostics[f"weighted_D_os_{index}"] = d_os
            diagnostics[f"weighted_J_signed_{index}"] = d_so - d_os
        return CriterionResult(cost=float(cost), signed_residual=None, diagnostics=diagnostics)


__all__ = [
    "Estimator",
    "HydrographicNetworkDistance",
    "distance_gap",
    "distance_mean",
    "distance_pair",
    "distance_pairs",
]
