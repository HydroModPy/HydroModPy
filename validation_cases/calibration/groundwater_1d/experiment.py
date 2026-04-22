"""Transient 1D groundwater calibration — standalone experiment.

Forward model
-------------
1D confined aquifer, length ``L``. Implicit finite-difference solution of

    S * d h / d t = d/dx (T * d h / d x) + R(t)

with Dirichlet boundary ``h(0) = h(L) = 0`` (reference fixed head), uniform
recharge ``R(t)``. The aquifer starts at steady-state with a constant
recharge and relaxes when recharge drops to zero — the classical recession.

Synthetic observations are drawn at one mid-column well with additive
Gaussian noise. Calibration recovers ``(T, S)`` from the noisy heads.

The experiment uses only numpy, the forward model is ~30 lines; the
point of the file is to exercise the new ``hydromodpy.calibration`` API
(ParameterSpace, ScalarObjective, CalibrationEngine, build_optimizer).
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
# Forward model
# ---------------------------------------------------------------------------


def solve_heads(
    *,
    T: float,
    S: float,
    L: float = 1000.0,
    nx: int = 41,
    t_end: float = 50.0 * 86400.0,
    nt: int = 51,
    recharge_initial: float = 5.0e-9,
    recharge_final: float = 0.0,
    recharge_switch_fraction: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Solve 1D confined aquifer head on a recession.

    Returns ``(times, x, heads)`` where ``heads`` has shape ``(nt, nx)``.
    ``recharge_switch_fraction`` is the fraction of ``t_end`` at which the
    recharge flips from ``recharge_initial`` to ``recharge_final``.
    """
    dx = L / (nx - 1)
    x = np.linspace(0.0, L, nx)
    times = np.linspace(0.0, t_end, nt)
    dt = times[1] - times[0]

    h_steady = np.zeros(nx)
    inner = slice(1, nx - 1)
    rhs = recharge_initial * dx * dx / T * np.ones(nx - 2)

    A = np.zeros((nx - 2, nx - 2))
    for i in range(nx - 2):
        A[i, i] = -2.0
        if i > 0:
            A[i, i - 1] = 1.0
        if i < nx - 3:
            A[i, i + 1] = 1.0
    h_steady[inner] = np.linalg.solve(A, -rhs)

    heads = np.empty((nt, nx))
    heads[0] = h_steady
    alpha = T * dt / (S * dx * dx)
    main = (1.0 + 2.0 * alpha) * np.ones(nx - 2)
    off = -alpha * np.ones(nx - 3)
    implicit = np.diag(main) + np.diag(off, 1) + np.diag(off, -1)

    switch_t = recharge_switch_fraction * t_end
    h = heads[0].copy()
    for k in range(1, nt):
        t_now = times[k]
        R = recharge_initial if t_now <= switch_t else recharge_final
        rhs_k = h[inner] + (R * dt / S)
        rhs_k[0] += alpha * h[0]
        rhs_k[-1] += alpha * h[-1]
        h_new = h.copy()
        h_new[inner] = np.linalg.solve(implicit, rhs_k)
        heads[k] = h_new
        h = h_new

    return times, x, heads


# ---------------------------------------------------------------------------
# Case definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Groundwater1DCase:
    """Everything the calibration engine needs to evaluate one trial."""

    truth: Mapping[str, float]
    bounds: Mapping[str, tuple[float, float]]
    well_position: float = 500.0
    noise_sigma: float = 5.0e-4
    noise_seed: int = 7
    model_kwargs: Mapping[str, object] = field(default_factory=dict)

    def parameter_space(self) -> ParameterSpace:
        return ParameterSpace(
            [
                CalibParameter(
                    name="T",
                    lower=self.bounds["T"][0],
                    upper=self.bounds["T"][1],
                    transform="log",
                ),
                CalibParameter(
                    name="S",
                    lower=self.bounds["S"][0],
                    upper=self.bounds["S"][1],
                    transform="log",
                ),
            ]
        )

    def synthetic_observations(self) -> ObservationSet:
        times, x, heads = solve_heads(**self.truth, **self.model_kwargs)
        j = int(np.argmin(np.abs(x - self.well_position)))
        rng = np.random.default_rng(self.noise_seed)
        noisy = heads[:, j] + rng.normal(0.0, self.noise_sigma, size=times.size)
        return ObservationSet(
            stations=("well_mid",),
            times=times,
            values={"well_mid": noisy},
            variable="head",
        )

    def simulate(self, values: Mapping[str, float]) -> SimulationOutput:
        times, x, heads = solve_heads(
            T=float(values["T"]),
            S=float(values["S"]),
            **self.model_kwargs,
        )
        j = int(np.argmin(np.abs(x - self.well_position)))
        return SimulationOutput(
            sim_id=f"gw1d_T{values['T']:.2e}_S{values['S']:.2e}",
            stations=("well_mid",),
            times=times,
            values={"well_mid": heads[:, j]},
        )


GROUNDWATER_1D_CASE = Groundwater1DCase(
    truth={"T": 5.0e-3, "S": 1.0e-3},
    bounds={"T": (1.0e-4, 1.0e-1), "S": (1.0e-5, 1.0e-1)},
)


# ---------------------------------------------------------------------------
# Calibration driver
# ---------------------------------------------------------------------------


def build_calibration(
    case: Groundwater1DCase = GROUNDWATER_1D_CASE,
    *,
    optimizer_name: str = "scipy_nelder_mead",
    max_iter: int = 60,
    seed: int = 7,
    metric: str = "rmse",
) -> tuple[CalibrationEngine, ScalarObjective]:
    """Assemble a ready-to-run CalibrationEngine for this case."""
    space = case.parameter_space()
    observations = case.synthetic_observations()
    objective = ScalarObjective(observations, metric=metric)

    optimizer_kwargs: dict[str, object] = {"seed": seed}
    if optimizer_name == "scipy_nelder_mead":
        optimizer_kwargs["maxiter"] = max_iter
    elif optimizer_name == "scipy_de":
        optimizer_kwargs.update({"maxiter": 15, "popsize": 8, "tol": 1e-4})
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
    "GROUNDWATER_1D_CASE",
    "Groundwater1DCase",
    "build_calibration",
    "solve_heads",
]
