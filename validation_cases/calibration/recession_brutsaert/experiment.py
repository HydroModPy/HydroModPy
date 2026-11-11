"""Brutsaert-Nieber recession calibration - standalone experiment.

Forward model
-------------
Analytical recession following the Brutsaert-Nieber ODE

    d Q / d t = - a * Q ** b

with ``b > 0``. Integrated form (``b != 1``):

    Q(t) = [ Q0 ** (1 - b) - a * (1 - b) * t ] ** (1 / (1 - b))

``b = 1`` collapses to an exponential recession ``Q(t) = Q0 * exp(-a*t)``.

Synthetic observations: ``Q(t)`` at daily resolution for ``n_days`` days,
starting from ``Q0``, plus multiplicative log-normal noise (common in flow
series). Calibration recovers ``(a, b)``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.objective import CompositeObjective, SimulationOutput
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from validation_cases.calibration.shared.standalone import build_standalone_calibration

# ---------------------------------------------------------------------------
# Forward model
# ---------------------------------------------------------------------------


def recession_discharge(
    *,
    a: float,
    b: float,
    Q0: float,
    times: np.ndarray,
) -> np.ndarray:
    """Return Q(t) along the Brutsaert-Nieber recession law.

    Robust to ``b == 1`` (exponential) and to integrands that reach zero
    before ``times[-1]`` (clipped at ``0``).
    """
    if abs(b - 1.0) < 1e-6:
        return Q0 * np.exp(-a * times)
    exponent = 1.0 - b
    inside = Q0**exponent - a * exponent * times
    inside = np.clip(inside, 1.0e-30, None)
    return inside ** (1.0 / exponent)


# ---------------------------------------------------------------------------
# Case definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BrutsaertRecessionCase:
    """Synthetic recession + bounds for calibration."""

    truth: Mapping[str, float]
    bounds: Mapping[str, tuple[float, float]]
    Q0: float = 5.0
    n_days: int = 60
    log_noise_sigma: float = 0.05
    noise_seed: int = 11

    def parameter_space(self) -> ParameterSpace:
        return ParameterSpace(
            [
                CalibParameter(
                    name="a",
                    lower=self.bounds["a"][0],
                    upper=self.bounds["a"][1],
                    search_space="log",
                ),
                CalibParameter(
                    name="b",
                    lower=self.bounds["b"][0],
                    upper=self.bounds["b"][1],
                    search_space="identity",
                ),
            ]
        )

    def times(self) -> np.ndarray:
        return np.arange(self.n_days, dtype=float)

    def synthetic_observations(self) -> dict[str, np.ndarray]:
        t = self.times()
        clean = recession_discharge(
            a=float(self.truth["a"]),
            b=float(self.truth["b"]),
            Q0=self.Q0,
            times=t,
        )
        rng = np.random.default_rng(self.noise_seed)
        noise = rng.normal(0.0, self.log_noise_sigma, size=t.size)
        noisy = clean * np.exp(noise)
        return {"outlet": noisy}

    def simulate(self, values: Mapping[str, float]) -> SimulationOutput:
        t = self.times()
        q = recession_discharge(
            a=float(values["a"]),
            b=float(values["b"]),
            Q0=self.Q0,
            times=t,
        )
        return SimulationOutput(
            sim_id=f"brutsaert_a{values['a']:.3e}_b{values['b']:.3f}",
            stations=("outlet",),
            times=t,
            values={"outlet": q},
        )


BRUTSAERT_RECESSION_CASE = BrutsaertRecessionCase(
    truth={"a": 0.08, "b": 1.2},
    bounds={"a": (1.0e-3, 1.0e0), "b": (0.5, 2.5)},
)


def build_calibration(
    case: BrutsaertRecessionCase = BRUTSAERT_RECESSION_CASE,
    *,
    optimizer_name: str = "scipy_nelder_mead",
    max_trials: int = 80,
    seed: int = 11,
    metric: str = "rmse",
) -> tuple[CalibrationEngine, CompositeObjective]:
    """Assemble a ready-to-run CalibrationEngine for this case."""
    return build_standalone_calibration(
        case,
        optimizer_name=optimizer_name,
        max_trials=max_trials,
        seed=seed,
        metric=metric,
        popsize=10,
        grid_points=9,
    )


__all__ = [
    "BRUTSAERT_RECESSION_CASE",
    "BrutsaertRecessionCase",
    "build_calibration",
    "recession_discharge",
]
