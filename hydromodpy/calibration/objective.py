"""Objective Protocol — computes a cost from observed vs simulated data.

The calibration engine only requires an object with ``evaluate(sim) -> float``
or ``evaluate(sim) -> dict`` (multi-objective). ``ObservationSet`` and
``SimulationOutput`` are the standard payloads but any callable-like object
matching the Protocol is accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True, slots=True)
class ObservationSet:
    """Observed values, indexed by station."""

    stations: tuple[str, ...]
    times: np.ndarray
    values: Mapping[str, np.ndarray]
    variable: str
    weights: Mapping[str, float] | None = None


@dataclass(frozen=True, slots=True)
class SimulationOutput:
    """Simulated values aligned with an ObservationSet."""

    sim_id: str
    stations: tuple[str, ...]
    times: np.ndarray
    values: Mapping[str, np.ndarray]
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ObjectiveValue:
    """Cost (minimizable) plus per-component breakdown."""

    total: float
    components: Mapping[str, float] = field(default_factory=dict)
    vector: tuple[float, ...] | None = None


@runtime_checkable
class Objective(Protocol):
    """Contract: measure distance between observed and simulated."""

    name: str

    def evaluate(self, sim: SimulationOutput) -> ObjectiveValue | float | dict:
        ...


# ---------------------------------------------------------------------------
# Builtin metrics and a lightweight ScalarObjective
# ---------------------------------------------------------------------------


def nse(obs: np.ndarray, sim: np.ndarray) -> float:
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    mask = np.isfinite(obs) & np.isfinite(sim)
    if mask.sum() < 2:
        return float("nan")
    o, s = obs[mask], sim[mask]
    denom = float(np.sum((o - o.mean()) ** 2))
    if denom == 0.0:
        return float("nan")
    return 1.0 - float(np.sum((s - o) ** 2)) / denom


def rmse(obs: np.ndarray, sim: np.ndarray) -> float:
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    mask = np.isfinite(obs) & np.isfinite(sim)
    if mask.sum() == 0:
        return float("nan")
    return float(np.sqrt(np.mean((sim[mask] - obs[mask]) ** 2)))


def mae(obs: np.ndarray, sim: np.ndarray) -> float:
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    mask = np.isfinite(obs) & np.isfinite(sim)
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(np.abs(sim[mask] - obs[mask])))


def kge(obs: np.ndarray, sim: np.ndarray) -> float:
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    mask = np.isfinite(obs) & np.isfinite(sim)
    if mask.sum() < 2:
        return float("nan")
    o, s = obs[mask], sim[mask]
    if o.std() == 0.0 or o.mean() == 0.0:
        return float("nan")
    r = float(np.corrcoef(o, s)[0, 1])
    alpha = float(s.std() / o.std())
    beta = float(s.mean() / o.mean())
    return 1.0 - float(np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))


METRICS: dict[str, callable] = {
    "nse": nse,
    "rmse": rmse,
    "mae": mae,
    "kge": kge,
}

HIGHER_IS_BETTER: frozenset[str] = frozenset({"nse", "kge"})


class ScalarObjective:
    """One metric over one ObservationSet, optionally multi-station."""

    def __init__(
        self,
        observations: ObservationSet,
        *,
        metric: str = "nse",
        station_weights: Mapping[str, float] | None = None,
    ):
        if metric not in METRICS:
            raise ValueError(f"Unknown metric: {metric!r}. Choices: {sorted(METRICS)}")
        self.name = metric
        self._observations = observations
        self._metric_fn = METRICS[metric]
        self._higher_is_better = metric in HIGHER_IS_BETTER
        self._weights = dict(station_weights) if station_weights else {}

    def evaluate(self, sim: SimulationOutput) -> ObjectiveValue:
        obs = self._observations
        components: dict[str, float] = {}
        weights: list[float] = []
        costs: list[float] = []
        for station in obs.stations:
            o = obs.values[station]
            s = sim.values.get(station)
            if s is None:
                continue
            value = float(self._metric_fn(o, s))
            cost = (1.0 - value) if self._higher_is_better else value
            components[f"{self.name}@{station}"] = cost
            costs.append(cost)
            weights.append(float(self._weights.get(station, 1.0)))
        if not costs:
            return ObjectiveValue(total=float("inf"), components={})
        w = np.array(weights, dtype=float)
        c = np.array(costs, dtype=float)
        total = float(np.average(c, weights=w))
        return ObjectiveValue(total=total, components=components)


def evaluate_objective(
    obj: Objective, sim: SimulationOutput
) -> ObjectiveValue:
    """Normalize return types from user-defined Objective implementations."""
    out = obj.evaluate(sim)
    if isinstance(out, ObjectiveValue):
        return out
    if isinstance(out, (int, float)):
        return ObjectiveValue(total=float(out))
    if isinstance(out, Mapping):
        total = float(out.get("total", out.get("value", float("inf"))))
        comps = {k: float(v) for k, v in out.items() if k not in {"total", "value"}}
        return ObjectiveValue(total=total, components=comps)
    raise TypeError(f"Unsupported Objective return type: {type(out)}")


__all__ = [
    "Objective",
    "ObjectiveValue",
    "ObservationSet",
    "SimulationOutput",
    "ScalarObjective",
    "METRICS",
    "HIGHER_IS_BETTER",
    "evaluate_objective",
    "nse",
    "rmse",
    "mae",
    "kge",
]
