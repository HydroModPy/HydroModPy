"""The methods a ``[recharge_estimates]`` section can name: what each reads and gives.

The table holds no formula, so the data configuration validates a name against
it without loading pandas. The formulas are in ``recharge_estimates.py``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Estimator:
    """One estimator: the data families it reads, what it gives, and its reference."""

    reads: tuple[str, ...]
    gives: str  # "recharge", "effective_rainfall" or "factor"
    reference: str


ESTIMATORS: dict[str, Estimator] = {
    "turc": Estimator(("precipitation", "temperature"), "effective_rainfall", "Turc (1954)"),
    "guttman_zuckerman": Estimator(("precipitation",), "recharge", "Guttman and Zuckerman (1995)"),
    "kessler": Estimator(("precipitation",), "recharge", "Kessler (1967)"),
    "wallingford": Estimator(("hydrometry",), "recharge", "Gustard et al. (1992)"),
    "chapman_maxwell": Estimator(("hydrometry",), "recharge", "Chapman and Maxwell (1996)"),
    "eckhardt": Estimator(("hydrometry",), "recharge", "Eckhardt (2005)"),
    "wtf": Estimator(("piezometry",), "recharge", "Healy and Cook (2002)"),
    "closing_factor": Estimator(("hydrometry",), "factor", "Abherve (2022), eq. 12"),
}
"""The estimators, by the name a ``methods`` list writes."""

WEATHER = frozenset({"precipitation", "temperature"})
WEATHER_ESTIMATORS: tuple[str, ...] = tuple(
    name for name, estimator in ESTIMATORS.items() if set(estimator.reads) <= WEATHER
)
"""The estimators that read the weather only: a steady run may take one as its recharge."""

__all__ = ["ESTIMATORS", "WEATHER", "WEATHER_ESTIMATORS", "Estimator"]
