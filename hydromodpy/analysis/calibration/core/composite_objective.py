"""Composite objective blocks for multi-observable calibration workflows."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import math
from typing import Any

import numpy as np

from hydromodpy.analysis.calibration.core.objective_function import ObjectiveFunction


def _as_1d_float_array(values: Any, *, name: str) -> np.ndarray:
    """Convert values to one non-empty 1D float array."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError(f"{name} cannot be empty")
    return arr


def _default_reference_scale(
    observed: np.ndarray,
    *,
    metric: str,
    min_scale: float,
) -> float:
    """Return the default block scale used to normalize one raw cost."""
    metric_name = ObjectiveFunction.resolve_metric_name(metric)
    if ObjectiveFunction.metric_is_maximized(metric_name):
        return 1.0

    q1, q3 = np.nanpercentile(observed, [25.0, 75.0])
    iqr = float(q3 - q1)
    if math.isfinite(iqr) and iqr > float(min_scale):
        return iqr

    std = float(np.nanstd(observed, ddof=1)) if observed.size > 1 else 0.0
    if math.isfinite(std) and std > float(min_scale):
        return std

    return float(min_scale)


@dataclass(frozen=True, slots=True)
class CompositeObjectiveBlock:
    """One observable block contributing to the composite calibration cost."""

    name: str
    observed: np.ndarray
    selector: Callable[[Any], Any]
    metric: str = "rmse"
    weight: float = 1.0
    normalize_cost: bool = True
    reference_scale: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        if not name:
            raise ValueError("CompositeObjectiveBlock.name cannot be empty")
        if not callable(self.selector):
            raise TypeError("CompositeObjectiveBlock.selector must be callable")

        observed = _as_1d_float_array(self.observed, name=f"observed[{name}]")
        metric = ObjectiveFunction.resolve_metric_name(self.metric)
        weight = float(self.weight)
        if not math.isfinite(weight) or weight <= 0.0:
            raise ValueError(
                f"CompositeObjectiveBlock.weight must be finite and > 0 for '{name}'"
            )

        reference_scale = self.reference_scale
        if reference_scale is not None:
            reference_scale = float(reference_scale)
            if not math.isfinite(reference_scale) or reference_scale <= 0.0:
                raise ValueError(
                    "CompositeObjectiveBlock.reference_scale must be finite and > 0 "
                    f"for '{name}'"
                )

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "observed", observed.copy())
        object.__setattr__(self, "metric", metric)
        object.__setattr__(self, "weight", weight)
        object.__setattr__(self, "reference_scale", reference_scale)
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class CompositeBlockEvaluation:
    """Evaluation payload for one composite objective block."""

    name: str
    metric: str
    weight_raw: float
    weight_normalized: float
    score: float
    raw_cost: float
    normalized_cost: float
    reference_scale: float
    n_values: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name).strip())
        object.__setattr__(self, "metric", ObjectiveFunction.resolve_metric_name(self.metric))
        object.__setattr__(self, "weight_raw", float(self.weight_raw))
        object.__setattr__(self, "weight_normalized", float(self.weight_normalized))
        object.__setattr__(self, "score", float(self.score))
        object.__setattr__(self, "raw_cost", float(self.raw_cost))
        object.__setattr__(self, "normalized_cost", float(self.normalized_cost))
        object.__setattr__(self, "reference_scale", float(self.reference_scale))
        object.__setattr__(self, "n_values", int(self.n_values))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_mapping(self) -> dict[str, Any]:
        """Return a JSON-serializable view of one block evaluation."""
        return {
            "name": self.name,
            "metric": self.metric,
            "weight_raw": self.weight_raw,
            "weight_normalized": self.weight_normalized,
            "score": self.score,
            "raw_cost": self.raw_cost,
            "normalized_cost": self.normalized_cost,
            "reference_scale": self.reference_scale,
            "n_values": self.n_values,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class CompositeObjectiveEvaluation:
    """Aggregated evaluation payload for one composite objective call."""

    total_cost: float
    total_score: float | None
    blocks: tuple[CompositeBlockEvaluation, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        total_cost = float(self.total_cost)
        total_score = self.total_score
        if total_score is None:
            total_score = -total_cost
        object.__setattr__(self, "total_cost", total_cost)
        object.__setattr__(self, "total_score", float(total_score))
        object.__setattr__(self, "blocks", tuple(self.blocks))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_mapping(self) -> dict[str, Any]:
        """Return a JSON-serializable summary of one composite evaluation."""
        return {
            "total_cost": self.total_cost,
            "total_score": self.total_score,
            "blocks": [block.to_mapping() for block in self.blocks],
            "metadata": dict(self.metadata),
        }


class CompositeObjective:
    """Evaluate a weighted composite objective over several observable blocks."""

    def __init__(
        self,
        *,
        simulator: Callable[[dict[str, float]], Any],
        blocks: Iterable[CompositeObjectiveBlock],
        normalize_weights: bool = True,
        min_scale: float = 1.0e-12,
    ) -> None:
        if not callable(simulator):
            raise TypeError("CompositeObjective.simulator must be callable")
        parsed_blocks = tuple(blocks)
        if not parsed_blocks:
            raise ValueError("CompositeObjective requires at least one block")
        if not all(isinstance(block, CompositeObjectiveBlock) for block in parsed_blocks):
            raise TypeError("CompositeObjective.blocks must contain CompositeObjectiveBlock instances")

        total_weight = sum(float(block.weight) for block in parsed_blocks)
        if total_weight <= 0.0:
            raise ValueError("CompositeObjective requires a strictly positive total weight")

        self.simulator = simulator
        self.blocks = parsed_blocks
        self.normalize_weights = bool(normalize_weights)
        self.min_scale = float(min_scale)

    def simulate(self, params: dict[str, float]) -> Any:
        """Run the wrapped simulator once and return its raw payload."""
        return self.simulator(params)

    def evaluate(self, params: dict[str, float]) -> CompositeObjectiveEvaluation:
        """Evaluate all blocks and return the aggregated composite objective."""
        payload = self.simulate(params)
        raw_weights = np.asarray([block.weight for block in self.blocks], dtype=float)
        if self.normalize_weights:
            normalized_weights = raw_weights / np.sum(raw_weights)
        else:
            normalized_weights = raw_weights.copy()

        block_evaluations: list[CompositeBlockEvaluation] = []
        total_cost = 0.0
        for block, weight_normalized in zip(self.blocks, normalized_weights, strict=True):
            simulated = _as_1d_float_array(
                block.selector(payload),
                name=f"simulated[{block.name}]",
            )
            if simulated.shape != block.observed.shape:
                raise ValueError(
                    "CompositeObjective block shape mismatch for "
                    f"'{block.name}': simulated{simulated.shape} "
                    f"!= observed{block.observed.shape}"
                )

            objective = ObjectiveFunction(metric=block.metric)
            score = float(
                objective.evaluate(
                    observed=block.observed,
                    simulated=simulated,
                    return_components=False,
                )["value"]
            )
            raw_cost = float(objective.value_to_cost(score))
            reference_scale = (
                float(block.reference_scale)
                if block.reference_scale is not None
                else _default_reference_scale(
                    block.observed,
                    metric=block.metric,
                    min_scale=self.min_scale,
                )
            )
            normalized_cost = (
                raw_cost / reference_scale if block.normalize_cost else raw_cost
            )
            total_cost += float(weight_normalized) * float(normalized_cost)
            block_evaluations.append(
                CompositeBlockEvaluation(
                    name=block.name,
                    metric=block.metric,
                    weight_raw=block.weight,
                    weight_normalized=float(weight_normalized),
                    score=score,
                    raw_cost=raw_cost,
                    normalized_cost=normalized_cost,
                    reference_scale=reference_scale,
                    n_values=int(simulated.size),
                    metadata=block.metadata,
                )
            )

        return CompositeObjectiveEvaluation(
            total_cost=float(total_cost),
            total_score=None,
            blocks=tuple(block_evaluations),
            metadata={
                "normalize_weights": self.normalize_weights,
                "min_scale": self.min_scale,
            },
        )


__all__ = (
    "CompositeBlockEvaluation",
    "CompositeObjective",
    "CompositeObjectiveBlock",
    "CompositeObjectiveEvaluation",
)
