"""Objective Protocol - computes a cost from observed vs simulated data.

The calibration engine only requires an object with ``evaluate(sim) -> float``
or ``evaluate(sim) -> dict`` (multi-objective). ``ObservationSet`` and
``SimulationOutput`` are the standard payloads but any callable-like object
matching the Protocol is accepted.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np

from hydromodpy.core.metrics import kge, mae, nse, rmse


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


def _kge_score(sim: np.ndarray, obs: np.ndarray) -> float:
    """Scalar KGE score; calibration needs a single number, not the decomposition."""
    return float(kge(sim, obs)["kge"])


METRICS: dict[str, Callable[[np.ndarray, np.ndarray], float]] = {
    "nse": nse,
    "rmse": rmse,
    "mae": mae,
    "kge": _kge_score,
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
            value = float(self._metric_fn(s, o))
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


class ConfigBlockObjective:
    """Objective for one ``[[calibration.objective_blocks]]`` declaration.

    Concatenates the observed vectors of the referenced outputs, receives
    the simulated vectors at evaluation time via ``sim.values``
    (``Mapping[output_name, Sequence[float]]``), computes the block metric
    and applies the configured normalisation and transform.
    """

    def __init__(
        self,
        *,
        name: str,
        metric: str,
        uses_outputs: Iterable[str],
        observed_by_output: Mapping[str, Iterable[float]],
        normalize_cost: bool = False,
        transform: str = "identity",
    ) -> None:
        metric_key = str(metric).strip().lower()
        if metric_key not in METRICS:
            raise ValueError(
                f"Block {name!r}: unknown metric {metric!r}. Choices: {sorted(METRICS)}"
            )
        outputs = tuple(str(output) for output in uses_outputs)
        if not outputs:
            raise ValueError(f"Block {name!r}: uses_outputs must not be empty")
        observed_parts: list[np.ndarray] = []
        for output_name in outputs:
            values = observed_by_output.get(output_name)
            if values is None:
                raise ValueError(f"Block {name!r}: output {output_name!r} has no observed_values")
            observed_parts.append(np.asarray(list(values), dtype=float).ravel())
        observed = np.concatenate(observed_parts) if observed_parts else np.empty(0)
        self.name = str(name)
        self._metric = metric_key
        self._metric_fn = METRICS[metric_key]
        self._higher_is_better = metric_key in HIGHER_IS_BETTER
        self._outputs = outputs
        self._observed = observed
        self._normalize_cost = bool(normalize_cost)
        self._transform_name = str(transform).strip().lower() if transform else "identity"
        self._transform_fn = _resolve_transform(self._transform_name)
        self._reference_scale = self._compute_reference_scale(observed)

    @staticmethod
    def _compute_reference_scale(observed: np.ndarray) -> float:
        if observed.size == 0:
            return 1.0
        std = float(np.nanstd(observed))
        if std > 0.0 and np.isfinite(std):
            return std
        mean_abs = float(np.mean(np.abs(observed)))
        return mean_abs if mean_abs > 0.0 else 1.0

    @property
    def metric(self) -> str:
        return self._metric

    @property
    def uses_outputs(self) -> tuple[str, ...]:
        return self._outputs

    def evaluate(self, sim: SimulationOutput | Mapping[str, Iterable[float]]) -> ObjectiveValue:
        if hasattr(sim, "values") and not isinstance(sim, Mapping):
            sim_values = sim.values
        else:
            sim_values = sim
        simulated_parts: list[np.ndarray] = []
        for output_name in self._outputs:
            part = sim_values.get(output_name) if isinstance(sim_values, Mapping) else None
            if part is None:
                return ObjectiveValue(
                    total=float("inf"),
                    components={f"{self.name}.missing": 1.0},
                )
            simulated_parts.append(np.asarray(list(part), dtype=float).ravel())
        simulated = np.concatenate(simulated_parts) if simulated_parts else np.empty(0)
        n = int(min(self._observed.size, simulated.size))
        if n == 0:
            return ObjectiveValue(total=float("inf"), components={})
        observed = self._observed[:n]
        simulated = simulated[:n]
        raw = float(self._metric_fn(simulated, observed))
        if not np.isfinite(raw):
            return ObjectiveValue(
                total=float("inf"),
                components={f"{self.name}.raw_cost": float("inf")},
            )
        cost = (1.0 - raw) if self._higher_is_better else raw
        normalized = cost / self._reference_scale if self._normalize_cost else cost
        transformed = float(self._transform_fn(normalized))
        components = {
            f"{self.name}.raw_cost": float(cost),
            f"{self.name}.normalized_cost": float(normalized),
            f"{self.name}.reference_scale": float(self._reference_scale),
            f"{self.name}.n_values": float(n),
        }
        return ObjectiveValue(total=float(transformed), components=components)


def build_objective_from_config(cfg: Any) -> Objective:
    """Assemble an :class:`Objective` from a :class:`CalibrationConfig`.

    Each ``objective_block`` becomes one :class:`ConfigBlockObjective`
    (metric + normalise + transform applied per block). When a single block
    is declared, the block is returned directly; otherwise the blocks are
    wrapped in a :class:`CompositeObjective` with normalised weights.
    """
    blocks = getattr(cfg, "objective_blocks", None) or []
    outputs = getattr(cfg, "outputs", None) or {}
    if not blocks:
        raise ValueError(
            "cfg.objective_blocks is empty; declare [[calibration.objective_blocks]] "
            "or populate cfg.outputs so the implicit block can be synthesised."
        )
    observed_by_output: dict[str, tuple[float, ...]] = {}
    for output_name, decl in outputs.items():
        values = getattr(decl, "observed_values", None)
        if values is not None:
            observed_by_output[str(output_name)] = tuple(float(v) for v in values)
    block_objectives: list[Objective] = []
    for block in blocks:
        name = str(block.name)
        uses_outputs = tuple(block.uses_outputs)
        metric = str(getattr(block, "metric", "rmse"))
        normalize_cost = bool(getattr(block, "normalize_cost", False))
        transform = str(getattr(block, "transform", "identity"))
        block_objectives.append(
            ConfigBlockObjective(
                name=name,
                metric=metric,
                uses_outputs=uses_outputs,
                observed_by_output=observed_by_output,
                normalize_cost=normalize_cost,
                transform=transform,
            )
        )
    if len(block_objectives) == 1:
        return block_objectives[0]
    weights = [float(getattr(block, "weight", 1.0)) for block in blocks]
    return CompositeObjective(
        list(zip(block_objectives, weights, strict=True)),
        name="config_composite",
        transform="identity",
    )


__all__ = [
    "Objective",
    "ObjectiveValue",
    "ObservationSet",
    "SimulationOutput",
    "ScalarObjective",
    "CompositeObjective",
    "ConfigBlockObjective",
    "build_objective_from_config",
    "METRICS",
    "HIGHER_IS_BETTER",
    "evaluate_objective",
]
