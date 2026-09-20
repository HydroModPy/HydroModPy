"""A closed-form linear reservoir for HydroModPy calibration."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest

if TYPE_CHECKING:
    from hydromodpy.calibration.optim.parameters import ParameterSpace

K_REFERENCE_PER_DAY = 1e-4
POROSITY_REFERENCE = 0.155
INITIAL_STORAGE_M3 = 1_000_000.0
RESERVOIR_AREA_M2 = 10_000_000.0
OBSERVATION_TIME_DAYS = 30.0
OBSERVED_DISCHARGE_M3_PER_DAY = 99.7004495503373
OBSERVED_HEAD_M = 0.6432287067763697


class ReservoirRecessionEvaluator:
    """Score recession discharge and head from a linear reservoir."""

    evaluator_id: ClassVar[str] = "reservoir_recession"
    needs_prepared_model: ClassVar[bool] = False

    def __init__(self, *, space: ParameterSpace | None = None) -> None:
        if space is None:
            raise ValueError(f"{self.evaluator_id!r} requires the calibration space.")
        _validate_space(space)
        self._space = space

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        """Return the mean squared relative observation residual."""
        started = time.perf_counter()
        values = request.values
        unknown = set(values).difference(self._space.names)
        if unknown:
            return self._failed(started, f"Unknown calibration parameter: {sorted(unknown)!r}.")

        try:
            k = _finite_value(values.get("k", K_REFERENCE_PER_DAY), "k")
            porosity = _finite_value(values.get("porosity", POROSITY_REFERENCE), "porosity")
            _validate_physical_values(k, porosity)
            discharge, head = _forward(k, porosity)
            components = _components(values, discharge, head)
            cost = _mean_component_cost(components)
        except (TypeError, ValueError, OverflowError) as exc:
            return self._failed(started, str(exc))

        if not math.isfinite(cost):
            return self._failed(started, "The observation cost is not finite.")
        return TrialOutcome(
            cost=float(cost),
            status="completed",
            duration_s=time.perf_counter() - started,
            components=components,
        )

    @staticmethod
    def _failed(started: float, reason: str) -> TrialOutcome:
        return TrialOutcome(
            cost=math.nan,
            status="failed",
            duration_s=time.perf_counter() - started,
            error=reason,
        )


def _validate_space(space: ParameterSpace) -> None:
    expected = {"k", "porosity"}
    actual = set(space.names)
    if actual != expected:
        raise ValueError(
            f"{ReservoirRecessionEvaluator.evaluator_id!r} requires exactly k and porosity; "
            f"the space declares {sorted(actual)!r}."
        )
    k = space["k"]
    porosity = space["porosity"]
    if k.transform != "log":
        raise ValueError("k must use the log transform.")
    if porosity.transform != "identity":
        raise ValueError("porosity must use the identity transform.")
    if not (math.isfinite(k.lower) and math.isfinite(k.upper) and 0.0 < k.lower <= k.upper):
        raise ValueError("k bounds must be finite and positive.")
    if not (
        math.isfinite(porosity.lower)
        and math.isfinite(porosity.upper)
        and 0.0 < porosity.lower <= porosity.upper <= 1.0
    ):
        raise ValueError("porosity bounds must be finite and lie in (0, 1].")


def _finite_value(value: object, name: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name}={value!r} is not a number.") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{name}={value!r} is not finite.")
    return numeric


def _validate_physical_values(k: float, porosity: float) -> None:
    if k <= 0.0:
        raise ValueError("k must be positive in 1/day.")
    if not 0.0 < porosity <= 1.0:
        raise ValueError("porosity must lie in (0, 1].")


def _forward(k: float, porosity: float) -> tuple[float, float]:
    storage = INITIAL_STORAGE_M3 * math.exp(-k * OBSERVATION_TIME_DAYS)
    discharge = k * storage
    head = storage / (RESERVOIR_AREA_M2 * porosity)
    if not (math.isfinite(discharge) and math.isfinite(head)):
        raise ValueError("The forward model returned a non-finite observable.")
    return discharge, head


def _components(values: Mapping[str, float], discharge: float, head: float) -> dict[str, float]:
    components: dict[str, float] = {}
    if "k" in values:
        components["discharge"] = (
            (discharge - OBSERVED_DISCHARGE_M3_PER_DAY) / OBSERVED_DISCHARGE_M3_PER_DAY
        ) ** 2
    if "porosity" in values:
        components["head"] = ((head - OBSERVED_HEAD_M) / OBSERVED_HEAD_M) ** 2
    if not all(math.isfinite(component) for component in components.values()):
        raise ValueError("The observation residual is not finite.")
    return components


def _mean_component_cost(components: Mapping[str, float]) -> float:
    if not components:
        return 0.0
    count = len(components)
    try:
        cost = math.fsum(component / count for component in components.values())
    except OverflowError as exc:
        raise ValueError("The observation cost is not representable.") from exc
    if not math.isfinite(cost):
        raise ValueError("The observation cost is not finite.")
    return cost


__all__ = ["ReservoirRecessionEvaluator"]
