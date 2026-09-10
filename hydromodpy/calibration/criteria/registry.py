"""Where a criterion is resolved by the name a TOML writes.

One place holds the mapping, so a file names a criterion and never imports one,
and an unknown name is refused with the list of what exists. The registry is
built from the scoring kernels rather than beside them: a kernel added to
``METRICS`` becomes a criterion with no second list to remember.
"""

from __future__ import annotations

from hydromodpy.calibration.criteria.base import Criterion
from hydromodpy.calibration.criteria.network import NetworkCriterion
from hydromodpy.calibration.criteria.series import SeriesCriterion

NETWORK_ESTIMATORS: frozenset[str] = frozenset({"distance_gap", "distance_mean"})
"""Names the network criterion answers to, rather than a series kernel."""


def _kernels() -> dict[str, object]:
    from hydromodpy.calibration.optim.objective import METRICS

    return dict(METRICS)


def available_criteria() -> tuple[str, ...]:
    """Return every criterion name a TOML may write, sorted."""
    return tuple(sorted(_kernels()))


def criterion_for(name: str) -> Criterion:
    """Return the criterion registered under ``name``.

    Refuses an unknown name with the list, the same way the optimizer and the
    protocol registries do: a reader of the message never has to grep for what
    was accepted.
    """
    key = str(name).strip().lower()
    if key in NETWORK_ESTIMATORS:
        return NetworkCriterion(key)  # type: ignore[arg-type]
    kernels = _kernels()
    kernel = kernels.get(key)
    if kernel is None:
        joined = ", ".join(sorted(kernels))
        raise ValueError(f"Unknown criterion {name!r}. Registered: {joined}.")
    return SeriesCriterion(key, kernel)


__all__ = ["NETWORK_ESTIMATORS", "available_criteria", "criterion_for"]
