"""What qualifies a trial, beside its cost.

The solver reports a percent water-balance discrepancy on every run. Until now
that number was recorded and nothing read it: a run at twelve per cent was an
ordinary trial, scored, ranked, and eligible for promotion. Its cost is not
comparable to a run that closed, because part of the water it routed came from
nowhere, so ranking the two together compares a model with a bookkeeping error
against one without.

The threshold is a declaration and not a constant. A steady solve on a coarse
mesh closes to a fraction of a per cent; a transient one with a lake and a routed
stream network legitimately sits higher. Whoever runs the model states what they
accept, and nothing is rejected until they do.

The verdict is a :class:`~hydromodpy.calibration.criteria.base.Validity`: a name,
a pass or fail, the value, and a sentence saying what the failure does to the
number. That last part is the point on a platform, where the reader of a result
is not the person who produced it.
"""

from __future__ import annotations

from collections.abc import Mapping

from hydromodpy.calibration.criteria.base import Validity
from hydromodpy.solver.modflow_common.flow_adapter_helpers import WATER_BUDGET_METRIC


def water_budget_verdict(
    metrics: Mapping[str, float],
    *,
    threshold: float | None,
) -> Validity | None:
    """Return the water-balance verdict for one trial, or ``None``.

    ``None`` means there is nothing to say: either no threshold was declared, or
    the backend reported no discrepancy. Absent is not zero, and treating it as
    zero would pass a run nobody measured.
    """
    if threshold is None:
        return None
    reported = metrics.get(WATER_BUDGET_METRIC)
    if reported is None:
        return None
    discrepancy = abs(float(reported))
    limit = float(threshold)
    if discrepancy <= limit:
        return Validity(
            name="water_budget",
            passed=True,
            value=discrepancy,
            message=(
                f"the water balance closes to {discrepancy:.3g} per cent, within the "
                f"{limit:.3g} per cent this calibration accepts."
            ),
        )
    return Validity(
        name="water_budget",
        passed=False,
        value=discrepancy,
        message=(
            f"the water balance does not close: {discrepancy:.3g} per cent against the "
            f"{limit:.3g} per cent this calibration accepts. Part of the water the run "
            "routed came from nowhere, so its cost is not comparable to a run that "
            "closed and the trial is rejected rather than scored."
        ),
        fatal=True,
    )


__all__ = ["WATER_BUDGET_METRIC", "water_budget_verdict"]
