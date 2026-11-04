"""Objective Protocol - computes a cost from observed vs simulated data.

The calibration engine only requires an object with ``evaluate(sim) -> float``
or ``evaluate(sim) -> dict`` (multi-objective). ``SimulationOutput`` is the
standard payload but any callable-like object matching the Protocol is
accepted. Every trial of a document is scored by :class:`ConfigBlockObjective`,
one per declared or implicit block.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np

from hydromodpy.calibration.criteria.series import (
    LOG_METRICS,
    METRICS,
    SAMPLED_BY_DATE,
)
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SimulationOutput:
    """Simulated values a trial produced, keyed by output name.

    The payload is intentionally small: a simulation id, station ids, a time
    axis, and one vector per station. Metadata can carry backend-specific
    details without changing the objective Protocol.
    """

    sim_id: str
    stations: tuple[str, ...]
    times: np.ndarray
    values: Mapping[str, np.ndarray]
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ObjectiveValue:
    """Minimization cost returned by an objective.

    ``total`` is the scalar value minimized by the optimizer. ``components``
    stores named diagnostics such as station costs or block totals. ``vector``
    is available for optimizers that need a multi-objective representation.
    """

    total: float
    components: Mapping[str, float] = field(default_factory=dict)
    vector: tuple[float, ...] | None = None


@runtime_checkable
class Objective(Protocol):
    """Protocol for calibration objectives.

    Implementations expose a ``name`` and an ``evaluate`` method accepting a
    ``SimulationOutput``. The return value may be an ``ObjectiveValue``, a
    scalar cost, or a mapping with a ``total`` key.
    """

    name: str

    def evaluate(self, sim: SimulationOutput) -> ObjectiveValue | float | dict: ...


# ---------------------------------------------------------------------------
# Supports and return-type normalization
# ---------------------------------------------------------------------------


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
    """Apply a monotone log cost transform to a minimization cost."""
    value = float(cost) + float(epsilon)
    if value <= 0.0:
        raise ValueError(
            f"log cost_transform requires cost + epsilon > 0 (got cost={cost}, epsilon={epsilon})"
        )
    return float(np.log10(value))


def _transform_inverse(cost: float, *, epsilon: float = 1.0e-6) -> float:
    """Apply a monotone inverse cost transform to a minimization cost."""
    value = float(cost) + float(epsilon)
    if value == 0.0:
        raise ValueError("inverse cost_transform requires cost + epsilon != 0")
    return -1.0 / value


_TRANSFORMS: dict[str, Callable[[float], float]] = {
    "identity": _transform_identity,
    "log": _transform_log,
    "inverse": _transform_inverse,
}


def _resolve_transform(name: str) -> Callable[[float], float]:
    key = str(name).strip().lower() if name is not None else "identity"
    if key not in _TRANSFORMS:
        raise ValueError(f"Unknown cost_transform: {name!r}. Choices: {sorted(_TRANSFORMS)}")
    return _TRANSFORMS[key]


class CompositeObjective:
    """Weighted composite of several objective blocks.

    Each block is an ``(Objective, weight)`` tuple. ``evaluate()`` runs
    every block on the same :class:`SimulationOutput`, optionally applies a
    per-block ``cost_transform`` to the block total cost, then returns a single
    :class:`ObjectiveValue` whose ``.total`` is the weighted sum of the
    transformed block totals and ``.components`` merges every block's
    components. Weights are normalized so they sum to 1.0.

    Parameters
    ----------
    blocks
        Iterable of ``(Objective, weight)`` tuples. Weights must be
        strictly positive and finite.
    name
        Optional label for the composite (default: ``"composite"``).
    cost_transform
        One of ``"identity"``, ``"log"``, ``"inverse"`` (case-insensitive).
        Applied to each block's cost before weighting. Default
        ``"identity"``.

    Notes
    -----
    This class implements the :class:`Objective` Protocol and can therefore
    be plugged directly into the calibration engine wherever an objective is
    accepted.
    """

    def __init__(
        self,
        blocks: Iterable[tuple[Objective, float]],
        *,
        name: str = "composite",
        cost_transform: str = "identity",
    ) -> None:
        parsed: list[tuple[Objective, float]] = []
        for idx, item in enumerate(blocks):
            try:
                obj, weight = item
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    f"Each block must be an (Objective, weight) tuple; got {item!r} at index {idx}"
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
        self._transform_name = str(cost_transform).strip().lower() if cost_transform else "identity"
        self._transform_fn = _resolve_transform(self._transform_name)

    @property
    def blocks(self) -> tuple[tuple[Objective, float], ...]:
        """Return blocks with their *normalized* weights (sum to 1.0)."""
        return tuple((obj, norm_w) for obj, _raw, norm_w in self._blocks)

    @property
    def cost_transform(self) -> str:
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


def cost_block_fractions(
    components: Mapping[str, float] | None,
    blocks: Sequence[tuple[str, float]],
) -> dict[str, float] | None:
    """Return each block's fraction of the cost one trial's components actually summed.

    ``blocks`` lists ``(name, weight)`` as declared; the weights are normalized
    the same way :class:`CompositeObjective` normalizes them. The fraction of
    block ``i`` is ``w_i * c_i / sum_j(w_j * c_j)``, where ``c_i`` is read from
    ``components["<name>.total"]``: the per-block cost :class:`CompositeObjective`
    itself weighted and summed, after the block's own cost transform and before its
    weight. Reading it there rather than re-deriving a sign is why a signed
    criterion such as ``distance_gap`` never turns the fraction negative: its
    ``.total`` is already the absolute residual the criterion publishes as a
    cost, not the raw signed value. A single declared block always takes the
    whole cost, without needing a ``.total`` key at all (no composite wraps
    it). Returns ``None`` when the fraction cannot be told apart: ``components``
    is missing a block total, or the weighted costs sum to (numerically) zero.
    """
    if not blocks:
        return None
    if len(blocks) == 1:
        return {blocks[0][0]: 1.0}
    if not components:
        return None
    raw = np.asarray([weight for _, weight in blocks], dtype=float)
    total_weight = float(raw.sum())
    if total_weight <= 0.0:
        return None
    normalized = raw / total_weight
    contributions: list[float] = []
    for (name, _weight), norm_weight in zip(blocks, normalized, strict=True):
        key = f"{name}.total"
        if key not in components:
            return None
        contributions.append(float(norm_weight) * float(components[key]))
    denominator = float(sum(contributions))
    if not np.isfinite(denominator) or abs(denominator) < 1.0e-15:
        return None
    return {
        name: contribution / denominator
        for (name, _weight), contribution in zip(blocks, contributions, strict=True)
    }


def mean_cost_block_fractions(
    blocks: Sequence[tuple[str, float]],
    trial_components: Iterable[Mapping[str, float] | None],
) -> tuple[dict[str, float], int] | None:
    """Average each block's fraction of the cost over several trials.

    Skips a trial whose fraction :func:`cost_block_fractions` cannot compute.
    Returns ``None`` when ``blocks`` is empty or none of the trials could;
    otherwise the averaged fractions and the count of trials that entered the
    average, so a caller can say how many trials the mean actually covers.
    """
    if not blocks:
        return None
    sums: dict[str, float] = {name: 0.0 for name, _weight in blocks}
    n = 0
    for components in trial_components:
        fraction = cost_block_fractions(components, blocks)
        if fraction is None:
            continue
        for name in sums:
            sums[name] += fraction[name]
        n += 1
    if n == 0:
        return None
    return {name: total / n for name, total in sums.items()}, n


def scores_network_distances(needs: Any) -> bool:
    """Whether a criterion's cost is a distance between two networks.

    Its scale is not read off a record, which it has none of: it is the
    validity length of the output, the length Eq. 4 qualifies a match with.
    """
    return not needs.needs_observations and "network" in tuple(needs.reads_supports)


def non_finite_diagnosis(observed: np.ndarray, simulated: np.ndarray) -> str:
    """Say which property of two paired series makes a metric undefined.

    Every efficiency divides by the spread of the observations, so a constant
    record is undefined however good the simulation is. A single non-finite
    sample poisons the whole score the same way, and neither is visible from
    the value alone.
    """
    obs = np.asarray(observed, dtype="float64")
    sim = np.asarray(simulated, dtype="float64")
    reasons: list[str] = []
    if not np.all(np.isfinite(obs)):
        reasons.append(f"{int(np.count_nonzero(~np.isfinite(obs)))} of {obs.size} observed")
    if not np.all(np.isfinite(sim)):
        reasons.append(f"{int(np.count_nonzero(~np.isfinite(sim)))} of {sim.size} simulated")
    if reasons:
        return "Non-finite samples reached the metric: " + ", ".join(reasons) + "."
    finite_obs = obs[np.isfinite(obs)]
    if finite_obs.size and float(np.var(finite_obs)) == 0.0:
        return (
            f"The {obs.size} observed samples are all {finite_obs[0]:.6g}: an efficiency "
            "divides by their spread, so none is defined on a constant record."
        )
    if obs.size == 0:
        return "No sample was scored."
    return (
        f"{obs.size} sample(s) scored, observed in [{np.min(obs):.6g}, {np.max(obs):.6g}], "
        f"simulated in [{np.min(sim):.6g}, {np.max(sim):.6g}]."
    )


def refuse_a_normalisation_that_means_nothing(block: str, metric: str) -> None:
    """Refuse ``normalize_cost`` where dividing by a reference scale says nothing.

    The verdict comes from the criterion itself: it declares whether its cost is
    already a pure number, whether it fits observations at all, and which
    supports it reads. Reading those answers rather than lists held here is
    what stops the lists from drifting away from the kernels they describe.

    A network distance is normalized by its output's validity length, so a gap
    counted in validity lengths adds to an efficiency as a pure number. Any
    other criterion with no observations has no scale to divide by.
    """
    from hydromodpy.calibration.criteria import criterion_for

    needs = criterion_for(metric).requirements()
    if needs.cost_is_dimensionless:
        raise ValueError(
            f"Block {block!r}: normalize_cost = true divides the cost by the standard "
            f"deviation of the observations, and {metric!r} is already a pure number. "
            "Dividing it does not put two blocks on a common footing, it multiplies "
            "this one's weight by a figure that belongs to its data. Set the share you "
            "want in 'weight' and leave normalize_cost off."
        )
    if not needs.needs_observations and not scores_network_distances(needs):
        raise ValueError(
            f"Block {block!r}: normalize_cost = true has nothing to read a scale from "
            f"for {metric!r}. That criterion balances two simulated quantities, so no "
            "observed record exists to take a spread from. Set the share you want in "
            "'weight'."
        )


class ConfigBlockObjective:
    """Objective for one ``[[calibration.objective_blocks]]`` declaration.

    Concatenates the observed vectors of the referenced outputs, receives
    the simulated vectors at evaluation time via ``sim.values``
    (``Mapping[output_name, Sequence[float]]``), computes the block metric
    and applies the configured normalization and cost transform.

    ``distance_scales`` gives, per network output, the validity length of each
    distance it produces. A block that normalizes a network distance divides
    each distance by its own length before the criterion reads them, so the
    cost is counted in validity lengths.
    """

    def __init__(
        self,
        *,
        name: str,
        metric: str,
        uses_outputs: Iterable[str],
        observed_by_output: Mapping[str, Iterable[float]],
        normalize_cost: bool = False,
        cost_transform: str = "identity",
        distance_scales: Mapping[str, Sequence[float]] | None = None,
    ) -> None:
        from hydromodpy.calibration.criteria import criterion_for

        metric_key = str(metric).strip().lower()
        if metric_key not in METRICS:
            raise ValueError(
                f"Block {name!r}: unknown metric {metric!r}. Choices: {sorted(METRICS)}"
            )
        # The criterion owns the sign convention and the clipping, and declares
        # whether it fits observations at all. The block asks it rather than
        # re-deriving both from two frozensets held beside the registry.
        criterion = criterion_for(metric_key)
        needs = criterion.requirements()
        outputs = tuple(str(output) for output in uses_outputs)
        if not outputs:
            raise ValueError(f"Block {name!r}: uses_outputs must not be empty")
        scores_a_criterion = not needs.needs_observations
        observed_parts: list[np.ndarray] = []
        if not scores_a_criterion:
            for output_name in outputs:
                values = observed_by_output.get(output_name)
                if values is None:
                    raise ValueError(
                        f"Block {name!r}: output {output_name!r} has no observed values. "
                        "Name a station in 'observes', or write 'observed_values'."
                    )
                observed_parts.append(np.asarray(list(values), dtype=float).ravel())
        observed = np.concatenate(observed_parts) if observed_parts else np.empty(0)
        self.name = str(name)
        self._scores_a_criterion = scores_a_criterion
        self._metric = metric_key
        self._criterion = criterion
        self._outputs = outputs
        self._observed = observed
        self._observed_parts = observed_parts
        if normalize_cost:
            refuse_a_normalisation_that_means_nothing(self.name, metric_key)
        self._normalize_cost = bool(normalize_cost)
        self._scales_distances = self._normalize_cost and scores_network_distances(needs)
        self._distance_scales: dict[str, np.ndarray] = {
            str(output): np.asarray(list(scales), dtype=float).ravel()
            for output, scales in (distance_scales or {}).items()
        }
        self._transform_name = str(cost_transform).strip().lower() if cost_transform else "identity"
        self._transform_fn = _resolve_transform(self._transform_name)
        self._warned_scale_fallback = False
        self._said_undefined = False

    def _say_why_the_cost_is_undefined(self, observed: np.ndarray, simulated: np.ndarray) -> None:
        """Log once per block what about its series left the metric undefined.

        The optimizer sees an infinite cost and the trial fails on it, which
        says nothing about why. A constant record, a non-finite sample and a
        numerical blow-up call for three different answers.
        """
        if self._said_undefined:
            return
        self._said_undefined = True
        logger.warning(
            "Block %r: metric %r is undefined on this trial. %s",
            self.name,
            self._metric,
            non_finite_diagnosis(observed, simulated),
        )

    def _distances_in_validity_lengths(
        self, parts: Sequence[np.ndarray]
    ) -> tuple[np.ndarray, float]:
        """Divide each output's distances by its validity lengths.

        Returns the divided vector and the mean length it was divided by, the
        one number a report names as the scale. Refused by name when the trial
        published no length for an output, or one that is not a positive
        distance: a cost divided by an unknown is no share of anything.
        """
        divided: list[np.ndarray] = []
        used: list[np.ndarray] = []
        for output_name, part in zip(self._outputs, parts, strict=True):
            scales = self._distance_scales.get(output_name)
            if scales is None or scales.size != part.size:
                raise ValueError(
                    f"Block {self.name!r}: normalize_cost = true divides the distances of "
                    f"output {output_name!r} by its validity length, and the trial published "
                    f"{'none' if scales is None else f'{scales.size} for {part.size} values'}."
                )
            if not np.all(np.isfinite(scales)) or np.any(scales <= 0.0):
                raise ValueError(
                    f"Block {self.name!r}: output {output_name!r} published validity lengths "
                    f"{scales.tolist()} m; a distance is divided by a positive length."
                )
            divided.append(part / scales)
            used.append(scales)
        return np.concatenate(divided), float(np.mean(np.concatenate(used)))

    def _reference_scale_of(self, observed: np.ndarray, simulated: np.ndarray) -> float:
        """Return the spread the cost is divided by, read on the scored sample.

        The observed values the metric reads: past the burn-in, paired with a
        finite simulated value. The standard deviation answers; a sample with
        none falls back on its mean absolute value, then on 1.0, and the
        fallback is logged once per block.
        """
        if observed.size == 0 or self._scores_a_criterion:
            return 1.0
        paired = np.isfinite(observed) & np.isfinite(simulated)
        sample = observed[paired] if paired.any() else observed
        std = float(np.nanstd(sample))
        if std > 0.0 and np.isfinite(std):
            return std
        mean_abs = float(np.mean(np.abs(sample)))
        scale, used = (mean_abs, "mean absolute value") if mean_abs > 0.0 else (1.0, "1.0")
        if self._normalize_cost and not self._warned_scale_fallback:
            self._warned_scale_fallback = True
            logger.warning(
                "Block %r: the scored observations have no spread, so normalize_cost "
                "divides by their %s instead of their standard deviation.",
                self.name,
                used,
            )
        return scale

    @property
    def metric(self) -> str:
        return self._metric

    @property
    def uses_outputs(self) -> tuple[str, ...]:
        return self._outputs

    def _sample_days(self, sim: object) -> float | None:
        """Sampling step of this block's outputs, in days, when the trial dated them.

        Read from ``metadata["sample_days"]`` of a :class:`SimulationOutput`, one
        step per output. The median of the block's outputs answers; ``None``
        when no output of the block is dated.
        """
        metadata = getattr(sim, "metadata", None)
        if not isinstance(metadata, Mapping):
            return None
        steps = metadata.get("sample_days")
        if not isinstance(steps, Mapping):
            return None
        found = [float(steps[name]) for name in self._outputs if name in steps]
        found = [step for step in found if np.isfinite(step) and step > 0.0]
        return float(np.median(found)) if found else None

    def _times_days(self, sim: object) -> list[np.ndarray] | None:
        """Dates of each output of this block, in days, when the trial paired them.

        Read from ``metadata["sample_times"]`` of a :class:`SimulationOutput`,
        one array per output. ``None`` unless every output of the block has one.
        """
        metadata = getattr(sim, "metadata", None)
        if not isinstance(metadata, Mapping):
            return None
        times = metadata.get("sample_times")
        if not isinstance(times, Mapping) or any(name not in times for name in self._outputs):
            return None
        return [np.asarray(times[name], dtype=float).ravel() for name in self._outputs]

    def evaluate(self, sim: SimulationOutput | Mapping[str, Iterable[float]]) -> ObjectiveValue:
        sample_days = self._sample_days(sim)
        times_parts = self._times_days(sim)
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
        scored_parts = simulated_parts
        observed_parts = list(self._observed_parts)
        simulated = np.concatenate(simulated_parts) if simulated_parts else np.empty(0)
        observed = self._observed
        if simulated.size == 0:
            return ObjectiveValue(total=float("inf"), components={})
        if self._scores_a_criterion:
            scored = self._criterion.score(simulated)
            observed = simulated
        else:
            if observed.size == 0:
                return ObjectiveValue(total=float("inf"), components={})
            # Output by output, not on the concatenation. Two outputs each
            # wrong - 20 simulated against 30 observed, then 40 against 30 -
            # sum to 60 on both sides and pass a check made on the totals,
            # while the metric scores the second output's first ten values
            # against the first one's last ten.
            #
            # Placed here, after the two early returns above, which keep the
            # trials they used to reject softly. A trial the optimizer steps
            # over must not become an exception: its only production caller
            # turns one into an aborted run.
            for name, scored_part, observed_part in zip(
                self._outputs, scored_parts, observed_parts, strict=True
            ):
                if scored_part.size != observed_part.size:
                    raise ValueError(
                        f"Block {self.name!r}: output {name!r}: simulated length "
                        f"{scored_part.size} does not match observed length "
                        f"{observed_part.size}"
                    )
            if self._metric in SAMPLED_BY_DATE:
                times_days = None
                if times_parts is not None and all(
                    times.size == part.size
                    for times, part in zip(times_parts, scored_parts, strict=True)
                ):
                    times_days = np.concatenate(times_parts) if times_parts else None
                scored = self._criterion.score(
                    simulated, observed, sample_days=sample_days, times_days=times_days
                )
            else:
                scored = self._criterion.score(simulated, observed)
        cost = scored.cost
        n_clipped = int(scored.diagnostics.get("n_clipped", 0))
        if not np.isfinite(cost):
            self._say_why_the_cost_is_undefined(observed, simulated)
            return ObjectiveValue(
                total=float("inf"),
                components={f"{self.name}.raw_cost": float("inf")},
            )
        reference_scale = self._reference_scale_of(observed, simulated)
        if self._scales_distances:
            # Each distance by its own validity length, before the criterion
            # adds them: two bounds of one output may carry two lengths.
            divided, reference_scale = self._distances_in_validity_lengths(scored_parts)
            normalized = float(self._criterion.score(divided).cost)
        else:
            normalized = cost / reference_scale if self._normalize_cost else cost
        transformed = float(self._transform_fn(normalized))
        components = {
            f"{self.name}.raw_cost": float(cost),
            f"{self.name}.normalized_cost": float(normalized),
            f"{self.name}.reference_scale": float(reference_scale),
            f"{self.name}.n_values": float(observed.size),
        }
        if self._metric in LOG_METRICS:
            components[f"{self.name}.n_clipped"] = float(n_clipped)
        return ObjectiveValue(total=float(transformed), components=components)


def build_objective_from_config(
    cfg: Any,
    *,
    observed_by_output: Mapping[str, Iterable[float]] | None = None,
    distance_scales: Mapping[str, Sequence[float]] | None = None,
) -> Objective:
    """Assemble an :class:`Objective` from a :class:`CalibrationConfig`.

    Each ``objective_block`` becomes one :class:`ConfigBlockObjective`
    (metric + normalize + cost transform applied per block). When a single block
    is declared, the block is returned directly; otherwise the blocks are
    wrapped in a :class:`CompositeObjective` with normalized weights.

    A block that inherits a burn-in while consuming an output with no time
    axis is refused here, by name, rather than scored on a truncated vector.

    ``observed_by_output`` supplies the observed vector of an output that names
    a station rather than typing its values: the record is only known once it
    has been aligned on a trial's simulated timestamps, so it arrives here
    instead of being read off the declaration. What it names wins over
    ``observed_values``; every other output is read from its declaration as
    before.

    ``distance_scales`` gives the validity lengths a trial published for its
    network outputs, which a block with ``normalize_cost`` on a network
    distance divides by. Like the aligned records, they are known only once the
    trial has run, so the objective is then built per trial.
    """
    blocks = getattr(cfg, "objective_blocks", None) or []
    outputs = getattr(cfg, "outputs", None) or {}
    if not blocks:
        raise ValueError(
            "cfg.objective_blocks is empty; declare [[calibration.objective_blocks]] "
            "or populate cfg.outputs so the implicit block can be synthesised."
        )
    declared_observed: dict[str, tuple[float, ...]] = {}
    for output_name, decl in outputs.items():
        values = getattr(decl, "observed_values", None)
        if values is not None:
            declared_observed[str(output_name)] = tuple(float(v) for v in values)
    for output_name, values in (observed_by_output or {}).items():
        declared_observed[str(output_name)] = tuple(float(v) for v in values)
    block_objectives: list[Objective] = []
    for block in blocks:
        name = str(block.name)
        uses_outputs = tuple(block.uses_outputs)
        metric = str(getattr(block, "metric", "rmse"))
        normalize_cost = bool(getattr(block, "normalize_cost", False))
        cost_transform = str(getattr(block, "cost_transform", "identity"))
        block_objectives.append(
            ConfigBlockObjective(
                name=name,
                metric=metric,
                uses_outputs=uses_outputs,
                observed_by_output=declared_observed,
                normalize_cost=normalize_cost,
                cost_transform=cost_transform,
                distance_scales=distance_scales,
            )
        )
    if len(block_objectives) == 1:
        return block_objectives[0]
    weights = [float(getattr(block, "weight", 1.0)) for block in blocks]
    return CompositeObjective(
        list(zip(block_objectives, weights, strict=True)),
        name="config_composite",
        cost_transform="identity",
    )


__all__ = [
    "Objective",
    "ObjectiveValue",
    "SimulationOutput",
    "CompositeObjective",
    "ConfigBlockObjective",
    "build_objective_from_config",
    "refuse_a_normalisation_that_means_nothing",
    "non_finite_diagnosis",
    "evaluate_objective",
    "cost_block_fractions",
    "mean_cost_block_fractions",
]
