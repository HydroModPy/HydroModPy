"""Lumped reservoir calibration — standalone experiment.

Forward model
-------------
A single lumped reservoir per unit area, non-linear outlet:

    d h / d t = Q_in(t) - Q_out(h)
    Q_out(h)  = k * max(h, 0) ** n

Quantities are all expressed in consistent units (``h`` in ``m``, rates in
``m / day``, time in days, ``k`` in ``1/day`` for ``n = 1``). Explicit
forward Euler. ``Q_in(t)`` is a piecewise-constant pulse sequence.

Synthetic observations are daily ``Q_out`` with additive Gaussian noise.
Calibration recovers ``(k, n)``.

A two-reservoir-in-series variant is exposed as ``TWO_RESERVOIR_CASE``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np

from hydromodpy.calibration import (
    CalibParameter,
    CalibrationEngine,
    EvaluationResult,
    ObservationSet,
    ParameterSpace,
    ParamSuggestion,
    ScalarObjective,
    SimulationOutput,
    build_optimizer,
)
from hydromodpy.calibration.objective import evaluate_objective


# ---------------------------------------------------------------------------
# Forward models
# ---------------------------------------------------------------------------


def make_inflow(n_days: int, *, seed: int = 3, amplitude: float = 0.03) -> np.ndarray:
    """Piecewise-constant daily inflow (``m / day``) with a few pulses."""
    rng = np.random.default_rng(seed)
    inflow = np.zeros(n_days)
    n_pulses = max(3, n_days // 20)
    starts = rng.integers(low=1, high=max(2, n_days - 6), size=n_pulses)
    durations = rng.integers(low=2, high=6, size=n_pulses)
    for s, d in zip(starts, durations):
        inflow[s : s + d] += amplitude * (0.5 + rng.random())
    return inflow


def solve_one_reservoir(
    *,
    k: float,
    n: float,
    inflow: np.ndarray,
    dt: float = 1.0,
    h0: float = 0.0,
) -> np.ndarray:
    """Explicit Euler on the one-reservoir ODE. Returns daily ``Q_out``."""
    h = float(h0)
    qout = np.empty_like(inflow, dtype=float)
    for i, qin in enumerate(inflow):
        out = k * max(h, 0.0) ** n
        h = h + dt * (float(qin) - out)
        h = max(h, 0.0)
        qout[i] = out
    return qout


def solve_two_reservoirs(
    *,
    k1: float,
    k2: float,
    n1: float,
    n2: float,
    inflow: np.ndarray,
    dt: float = 1.0,
) -> np.ndarray:
    """Two reservoirs in series — ``Q_out`` from the second reservoir."""
    h1 = 0.0
    h2 = 0.0
    qout2 = np.empty_like(inflow, dtype=float)
    for i, qin in enumerate(inflow):
        out1 = k1 * max(h1, 0.0) ** n1
        out2 = k2 * max(h2, 0.0) ** n2
        h1 = h1 + dt * (float(qin) - out1)
        h1 = max(h1, 0.0)
        h2 = h2 + dt * (out1 - out2)
        h2 = max(h2, 0.0)
        qout2[i] = out2
    return qout2


# ---------------------------------------------------------------------------
# Case definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OneReservoirCase:
    """Single-reservoir calibration setup."""

    truth: Mapping[str, float]
    bounds: Mapping[str, tuple[float, float]]
    n_days: int = 90
    inflow_seed: int = 3
    noise_sigma: float = 0.05
    noise_seed: int = 13

    def parameter_space(self) -> ParameterSpace:
        return ParameterSpace(
            [
                CalibParameter(
                    name="k",
                    lower=self.bounds["k"][0],
                    upper=self.bounds["k"][1],
                    transform="log",
                ),
                CalibParameter(
                    name="n",
                    lower=self.bounds["n"][0],
                    upper=self.bounds["n"][1],
                    transform="identity",
                ),
            ]
        )

    def _inflow(self) -> np.ndarray:
        return make_inflow(self.n_days, seed=self.inflow_seed)

    def synthetic_observations(self) -> ObservationSet:
        inflow = self._inflow()
        clean = solve_one_reservoir(
            k=float(self.truth["k"]),
            n=float(self.truth["n"]),
            inflow=inflow,
        )
        rng = np.random.default_rng(self.noise_seed)
        noisy = clean + rng.normal(
            0.0, self.noise_sigma * max(clean.max(), 1.0e-6), size=clean.size
        )
        return ObservationSet(
            stations=("outlet",),
            times=np.arange(self.n_days, dtype=float),
            values={"outlet": np.maximum(noisy, 0.0)},
            variable="discharge",
        )

    def simulate(self, values: Mapping[str, float]) -> SimulationOutput:
        inflow = self._inflow()
        q = solve_one_reservoir(
            k=float(values["k"]),
            n=float(values["n"]),
            inflow=inflow,
        )
        return SimulationOutput(
            sim_id=f"reservoir1_k{values['k']:.3e}_n{values['n']:.2f}",
            stations=("outlet",),
            times=np.arange(self.n_days, dtype=float),
            values={"outlet": q},
        )


@dataclass(frozen=True)
class TwoReservoirCase:
    """Two-reservoirs-in-series calibration setup."""

    truth: Mapping[str, float]
    bounds: Mapping[str, tuple[float, float]]
    n_days: int = 90
    inflow_seed: int = 3
    noise_sigma: float = 0.05
    noise_seed: int = 17
    fixed: Mapping[str, float] = field(default_factory=lambda: {"n1": 1.5, "n2": 1.5})

    def parameter_space(self) -> ParameterSpace:
        return ParameterSpace(
            [
                CalibParameter(
                    name="k1",
                    lower=self.bounds["k1"][0],
                    upper=self.bounds["k1"][1],
                    transform="log",
                ),
                CalibParameter(
                    name="k2",
                    lower=self.bounds["k2"][0],
                    upper=self.bounds["k2"][1],
                    transform="log",
                ),
            ]
        )

    def _inflow(self) -> np.ndarray:
        return make_inflow(self.n_days, seed=self.inflow_seed)

    def synthetic_observations(self) -> ObservationSet:
        inflow = self._inflow()
        clean = solve_two_reservoirs(
            k1=float(self.truth["k1"]),
            k2=float(self.truth["k2"]),
            n1=float(self.fixed["n1"]),
            n2=float(self.fixed["n2"]),
            inflow=inflow,
        )
        rng = np.random.default_rng(self.noise_seed)
        noisy = clean + rng.normal(
            0.0, self.noise_sigma * max(clean.max(), 1.0e-6), size=clean.size
        )
        return ObservationSet(
            stations=("outlet",),
            times=np.arange(self.n_days, dtype=float),
            values={"outlet": np.maximum(noisy, 0.0)},
            variable="discharge",
        )

    def simulate(self, values: Mapping[str, float]) -> SimulationOutput:
        inflow = self._inflow()
        q = solve_two_reservoirs(
            k1=float(values["k1"]),
            k2=float(values["k2"]),
            n1=float(self.fixed["n1"]),
            n2=float(self.fixed["n2"]),
            inflow=inflow,
        )
        return SimulationOutput(
            sim_id=f"reservoir2_k1{values['k1']:.3e}_k2{values['k2']:.3e}",
            stations=("outlet",),
            times=np.arange(self.n_days, dtype=float),
            values={"outlet": q},
        )


ONE_RESERVOIR_CASE = OneReservoirCase(
    truth={"k": 0.25, "n": 1.5},
    bounds={"k": (1.0e-2, 5.0), "n": (0.8, 2.5)},
)

TWO_RESERVOIR_CASE = TwoReservoirCase(
    truth={"k1": 0.4, "k2": 0.2},
    bounds={"k1": (1.0e-2, 5.0), "k2": (1.0e-2, 5.0)},
)


# ---------------------------------------------------------------------------
# Calibration driver
# ---------------------------------------------------------------------------


def build_calibration(
    case: OneReservoirCase | TwoReservoirCase = ONE_RESERVOIR_CASE,
    *,
    optimizer_name: str = "scipy_nelder_mead",
    max_iter: int = 100,
    seed: int = 13,
    metric: str = "rmse",
) -> tuple[CalibrationEngine, ScalarObjective]:
    space = case.parameter_space()
    observations = case.synthetic_observations()
    objective = ScalarObjective(observations, metric=metric)

    optimizer_kwargs: dict[str, object] = {"seed": seed}
    if optimizer_name == "scipy_nelder_mead":
        optimizer_kwargs["maxiter"] = max_iter
    elif optimizer_name == "scipy_de":
        optimizer_kwargs.update({"maxiter": 25, "popsize": 10, "tol": 1e-4})
    elif optimizer_name == "grid":
        optimizer_kwargs["points_per_dim"] = 9
    optimizer = build_optimizer(optimizer_name, space, **optimizer_kwargs)

    def evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        sim = case.simulate(sugg.values)
        obj = evaluate_objective(objective, sim)
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=sim.sim_id,
            objective_value=obj.total,
            components=dict(obj.components),
            status="completed",
            metadata={"values": dict(sugg.values)},
        )

    engine = CalibrationEngine(
        space=space,
        optimizer=optimizer,
        evaluator=evaluator,
        max_iter=max_iter,
    )
    return engine, objective


__all__ = [
    "ONE_RESERVOIR_CASE",
    "TWO_RESERVOIR_CASE",
    "OneReservoirCase",
    "TwoReservoirCase",
    "build_calibration",
    "make_inflow",
    "solve_one_reservoir",
    "solve_two_reservoirs",
]
