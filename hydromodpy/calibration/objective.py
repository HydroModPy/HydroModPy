"""Objective Protocol - computes a cost from observed vs simulated data.

The calibration engine only requires an object with ``evaluate(sim) -> float``
or ``evaluate(sim) -> dict`` (multi-objective). ``ObservationSet`` and
``SimulationOutput`` are the standard payloads but any callable-like object
matching the Protocol is accepted.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

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

    def evaluate(self, sim: SimulationOutput) -> ObjectiveValue | float | dict: ...


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


def evaluate_objective(obj: Objective, sim: SimulationOutput) -> ObjectiveValue:
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


# ---------------------------------------------------------------------------
# CompositeObjective - weighted multi-block composite
# ---------------------------------------------------------------------------


def _transform_identity(cost: float) -> float:
    return float(cost)


def _transform_log(cost: float, *, epsilon: float = 1.0e-6) -> float:
    """Apply ``log10(cost + epsilon)``; flips small costs into large positive values."""
    value = float(cost) + float(epsilon)
    if value <= 0.0:
        raise ValueError(
            f"log transform requires cost + epsilon > 0 (got cost={cost}, epsilon={epsilon})"
        )
    # ``-log10`` so that small costs (near-zero) map to *large* penalty values
    # while large costs map to small penalty values. This matches the intent of
    # emphasising near-zero departures as "bad" when the user asks for log.
    return -float(np.log10(value))


def _transform_inverse(cost: float, *, epsilon: float = 1.0e-6) -> float:
    """Apply ``1 / (cost + epsilon)``; flips near-zero costs into large values."""
    value = float(cost) + float(epsilon)
    if value == 0.0:
        raise ValueError("inverse transform requires cost + epsilon != 0")
    return 1.0 / value


_TRANSFORMS: dict[str, Callable[[float], float]] = {
    "identity": _transform_identity,
    "log": _transform_log,
    "inverse": _transform_inverse,
}


def _resolve_transform(name: str) -> Callable[[float], float]:
    key = str(name).strip().lower() if name is not None else "identity"
    if key not in _TRANSFORMS:
        raise ValueError(f"Unknown transform: {name!r}. Choices: {sorted(_TRANSFORMS)}")
    return _TRANSFORMS[key]


class CompositeObjective:
    """Weighted composite of several :class:`ScalarObjective` blocks.

    Each block is a ``(ScalarObjective, weight)`` tuple. ``evaluate()`` runs
    every block on the same :class:`SimulationOutput`, optionally applies a
    per-block ``transform`` to the block total cost, then returns a single
    :class:`ObjectiveValue` whose ``.total`` is the weighted sum of the
    transformed block totals and ``.components`` merges every block's
    components. Weights are normalised so they sum to 1.0.

    Parameters
    ----------
    blocks
        Iterable of ``(ScalarObjective, weight)`` tuples. Weights must be
        strictly positive and finite.
    name
        Optional label for the composite (default: ``"composite"``).
    transform
        One of ``"identity"``, ``"log"``, ``"inverse"`` (case-insensitive).
        Applied to each block's cost before weighting. Default
        ``"identity"``.

    Notes
    -----
    This class implements the :class:`Objective` Protocol and can therefore
    be plugged directly into the calibration engine wherever a
    ``ScalarObjective`` would be accepted.
    """

    def __init__(
        self,
        blocks: Iterable[tuple[Objective, float]],
        *,
        name: str = "composite",
        transform: str = "identity",
    ) -> None:
        parsed: list[tuple[Objective, float]] = []
        for idx, item in enumerate(blocks):
            try:
                obj, weight = item
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    f"Each block must be a (ScalarObjective, weight) tuple; "
                    f"got {item!r} at index {idx}"
                ) from exc
            if not hasattr(obj, "evaluate"):
                raise TypeError(
                    f"Block {idx}: first element must implement .evaluate() (Objective Protocol)"
                )
            w = float(weight)
            if not np.isfinite(w) or w <= 0.0:
                raise ValueError(f"Block {idx}: weight must be finite and > 0 (got {weight!r})")
            parsed.append((obj, w))
        if not parsed:
            raise ValueError("CompositeObjective requires at least one block")

        raw = np.asarray([w for _, w in parsed], dtype=float)
        total_w = float(raw.sum())
        if total_w <= 0.0:
            raise ValueError("CompositeObjective requires a strictly positive total weight")
        normalized = raw / total_w

        self.name = str(name)
        self._blocks: tuple[tuple[Objective, float, float], ...] = tuple(
            (obj, float(raw_w), float(norm_w))
            for (obj, raw_w), norm_w in zip(parsed, normalized, strict=True)
        )
        self._transform_name = str(transform).strip().lower() if transform else "identity"
        self._transform_fn = _resolve_transform(self._transform_name)

    @property
    def blocks(self) -> tuple[tuple[Objective, float], ...]:
        """Return blocks with their *normalized* weights (sum to 1.0)."""
        return tuple((obj, norm_w) for obj, _raw, norm_w in self._blocks)

    @property
    def raw_weights(self) -> tuple[float, ...]:
        """Return weights as supplied (before normalisation)."""
        return tuple(raw_w for _obj, raw_w, _norm in self._blocks)

    @property
    def transform(self) -> str:
        return self._transform_name

    def evaluate(self, sim: SimulationOutput) -> ObjectiveValue:
        merged_components: dict[str, float] = {}
        total = 0.0
        for idx, (obj, _raw_w, norm_w) in enumerate(self._blocks):
            block_value = evaluate_objective(obj, sim)
            transformed = float(self._transform_fn(block_value.total))
            total += norm_w * transformed
            block_label = getattr(obj, "name", f"block{idx}")
            # Emit one "<block>.total" per block; if two blocks share the
            # same label (e.g. two NSE blocks) disambiguate with the index.
            total_key = f"{block_label}.total"
            if total_key in merged_components:
                total_key = f"{block_label}#{idx}.total"
            merged_components[total_key] = transformed
            # Merge per-block components. Collisions are disambiguated by
            # prefixing with the block label (and, if needed, the index).
            for key, value in block_value.components.items():
                target_key = key
                if target_key in merged_components:
                    target_key = f"{block_label}.{key}"
                if target_key in merged_components:
                    target_key = f"{block_label}#{idx}.{key}"
                merged_components[target_key] = float(value)
        return ObjectiveValue(total=float(total), components=merged_components)


__all__ = [
    "Objective",
    "ObjectiveValue",
    "ObservationSet",
    "SimulationOutput",
    "ScalarObjective",
    "CompositeObjective",
    "METRICS",
    "HIGHER_IS_BETTER",
    "evaluate_objective",
    "nse",
    "rmse",
    "mae",
    "kge",
]
