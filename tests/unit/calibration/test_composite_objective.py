"""Unit tests for :class:`hydromodpy.calibration.objective.CompositeObjective`.

The new architecture ships a weighted multi-block composite objective as a
building block users compose when writing their own ``metric_fn``. Each
block pairs a :class:`ScalarObjective` with a positive weight; weights are
normalised to sum to 1.0. An optional ``transform`` (``"identity"``,
``"log"`` or ``"inverse"``) is applied to each block total before the
weighted sum is computed.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from hydromodpy.calibration.objective import (
    CompositeObjective,
    ObjectiveValue,
    ObservationSet,
    ScalarObjective,
    SimulationOutput,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_obs(station: str, values: np.ndarray, *, variable: str = "head") -> ObservationSet:
    times = np.arange(values.size, dtype=float)
    return ObservationSet(
        stations=(station,),
        times=times,
        values={station: values},
        variable=variable,
    )


def _make_sim(values_by_station: dict[str, np.ndarray]) -> SimulationOutput:
    first = next(iter(values_by_station.values()))
    times = np.arange(first.size, dtype=float)
    stations = tuple(values_by_station.keys())
    return SimulationOutput(
        sim_id="sim-test",
        stations=stations,
        times=times,
        values=values_by_station,
    )


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------


def test_equal_weight_composite_two_nse_blocks_returns_mean_cost() -> None:
    """Two equal-weight NSE blocks => total = mean of block NSE costs."""
    obs_a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    obs_b = np.array([10.0, 11.0, 12.0, 13.0, 14.0])

    # Introduce different simulation errors so the two block costs differ.
    sim_a = obs_a + 0.5
    sim_b = obs_b + 2.0

    block_a = ScalarObjective(_make_obs("A", obs_a), metric="nse")
    block_b = ScalarObjective(_make_obs("B", obs_b), metric="nse")

    sim = _make_sim({"A": sim_a, "B": sim_b})

    # Reference: evaluate each block independently.
    cost_a = block_a.evaluate(sim).total
    cost_b = block_b.evaluate(sim).total

    composite = CompositeObjective([(block_a, 1.0), (block_b, 1.0)])
    out = composite.evaluate(sim)

    assert isinstance(out, ObjectiveValue)
    assert out.total == pytest.approx(0.5 * cost_a + 0.5 * cost_b)
    # Sanity check: different simulation errors => different block costs.
    assert cost_a != cost_b


def test_weighted_composite_reflects_weights() -> None:
    """Weights (0.8, 0.2) shift the total toward the first block."""
    obs_a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    obs_b = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

    sim_a = obs_a + 0.1
    sim_b = obs_b + 5.0  # much worse fit on B

    block_a = ScalarObjective(_make_obs("A", obs_a), metric="nse")
    block_b = ScalarObjective(_make_obs("B", obs_b), metric="nse")

    sim = _make_sim({"A": sim_a, "B": sim_b})

    cost_a = block_a.evaluate(sim).total
    cost_b = block_b.evaluate(sim).total
    assert cost_a < cost_b  # sanity: A fits better

    composite = CompositeObjective([(block_a, 0.8), (block_b, 0.2)])
    out = composite.evaluate(sim)

    # Weights already sum to 1.0, so no re-normalisation effect.
    expected = 0.8 * cost_a + 0.2 * cost_b
    assert out.total == pytest.approx(expected)

    # Compare to equal-weight composite: weighted-towards-A must be smaller.
    composite_equal = CompositeObjective([(block_a, 1.0), (block_b, 1.0)])
    out_equal = composite_equal.evaluate(sim)
    assert out.total < out_equal.total


def test_unequal_weights_are_normalized_to_sum_one() -> None:
    """Weights (3, 1) normalise to (0.75, 0.25). Result identical to (0.75, 0.25)."""
    obs_a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    obs_b = np.array([10.0, 11.0, 12.0, 13.0, 14.0])

    sim_a = obs_a + 0.3
    sim_b = obs_b + 1.5

    block_a = ScalarObjective(_make_obs("A", obs_a), metric="rmse")
    block_b = ScalarObjective(_make_obs("B", obs_b), metric="rmse")
    sim = _make_sim({"A": sim_a, "B": sim_b})

    raw_composite = CompositeObjective([(block_a, 3.0), (block_b, 1.0)])
    eq_composite = CompositeObjective([(block_a, 0.75), (block_b, 0.25)])

    assert raw_composite.evaluate(sim).total == pytest.approx(eq_composite.evaluate(sim).total)

    # Normalised weights exposed as tuple summing to 1.0.
    norm_weights = [w for _, w in raw_composite.blocks]
    assert sum(norm_weights) == pytest.approx(1.0)
    assert norm_weights[0] == pytest.approx(0.75)
    assert norm_weights[1] == pytest.approx(0.25)
    # Raw weights preserved.
    assert raw_composite.raw_weights == (3.0, 1.0)


def test_components_dict_is_merged_from_all_blocks() -> None:
    """Composite components should carry every block's station components."""
    obs_a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    obs_b = np.array([10.0, 11.0, 12.0, 13.0, 14.0])

    sim_a = obs_a + 0.5
    sim_b = obs_b + 2.0

    block_a = ScalarObjective(_make_obs("A", obs_a), metric="nse")
    block_b = ScalarObjective(_make_obs("B", obs_b), metric="nse")
    sim = _make_sim({"A": sim_a, "B": sim_b})

    composite = CompositeObjective([(block_a, 1.0), (block_b, 1.0)])
    out = composite.evaluate(sim)

    # Both per-station components from the two ScalarObjective blocks
    # survive in the merged components dict.
    assert "nse@A" in out.components
    assert "nse@B" in out.components
    # Per-block totals are also surfaced; both blocks carry the same
    # ``.name`` ("nse") so one of them is disambiguated by index.
    total_keys = [k for k in out.components if k.endswith(".total")]
    assert len(total_keys) == 2


def test_transform_log_keeps_minimization_order() -> None:
    """``transform="log"`` preserves lower-is-better ordering."""
    # Build two identity-fit blocks (costs near zero after metric).
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    sim_values = obs.copy()

    block = ScalarObjective(_make_obs("A", obs), metric="rmse")
    sim = _make_sim({"A": sim_values})

    # Raw (identity) cost with a perfect fit => ~0.
    identity_composite = CompositeObjective([(block, 1.0)], transform="identity")
    identity_total = identity_composite.evaluate(sim).total
    assert identity_total == pytest.approx(0.0, abs=1.0e-12)

    log_composite = CompositeObjective([(block, 1.0)], transform="log")
    log_total = log_composite.evaluate(sim).total
    assert math.isfinite(log_total)

    bad_block = ScalarObjective(_make_obs("A", obs), metric="rmse")
    bad_sim = _make_sim({"A": obs + 10.0})
    bad_log_total = CompositeObjective([(bad_block, 1.0)], transform="log").evaluate(bad_sim).total
    assert log_total < bad_log_total


def test_transform_inverse_keeps_minimization_order() -> None:
    """``transform="inverse"`` preserves lower-is-better ordering."""
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    block = ScalarObjective(_make_obs("A", obs), metric="rmse")
    sim = _make_sim({"A": obs.copy()})  # perfect fit -> cost ~0

    inverse_composite = CompositeObjective([(block, 1.0)], transform="inverse")
    bad_sim = _make_sim({"A": obs + 10.0})
    assert inverse_composite.evaluate(sim).total < inverse_composite.evaluate(bad_sim).total


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_empty_blocks_raises() -> None:
    with pytest.raises(ValueError, match="at least one block"):
        CompositeObjective([])


def test_non_positive_weight_raises() -> None:
    obs = np.array([1.0, 2.0, 3.0])
    block = ScalarObjective(_make_obs("A", obs), metric="nse")
    with pytest.raises(ValueError, match="weight must be finite and > 0"):
        CompositeObjective([(block, 0.0)])
    with pytest.raises(ValueError, match="weight must be finite and > 0"):
        CompositeObjective([(block, -1.0)])


def test_non_finite_weight_raises() -> None:
    obs = np.array([1.0, 2.0, 3.0])
    block = ScalarObjective(_make_obs("A", obs), metric="nse")
    with pytest.raises(ValueError, match="weight must be finite and > 0"):
        CompositeObjective([(block, float("nan"))])


def test_unknown_transform_raises() -> None:
    obs = np.array([1.0, 2.0, 3.0])
    block = ScalarObjective(_make_obs("A", obs), metric="nse")
    with pytest.raises(ValueError, match="Unknown transform"):
        CompositeObjective([(block, 1.0)], transform="zigzag")


def test_malformed_block_tuple_raises() -> None:
    obs = np.array([1.0, 2.0, 3.0])
    block = ScalarObjective(_make_obs("A", obs), metric="nse")
    with pytest.raises(TypeError, match="must be a .*tuple"):
        CompositeObjective([block])  # forgot the weight


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


def test_composite_has_name_and_evaluate() -> None:
    """CompositeObjective satisfies the Objective Protocol surface."""
    obs = np.array([1.0, 2.0, 3.0])
    block = ScalarObjective(_make_obs("A", obs), metric="nse")
    composite = CompositeObjective([(block, 1.0)], name="my_composite")
    assert composite.name == "my_composite"
    assert hasattr(composite, "evaluate")
    assert composite.transform == "identity"
