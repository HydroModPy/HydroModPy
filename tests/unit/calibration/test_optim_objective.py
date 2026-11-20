"""Objective of a calibration: blocks score simulated against observed series.

A block gives one cost (dimensionless, or in the unit of the variable for a
residual metric such as rmse in m). A composite sums its blocks with weights
normalized to 1. Each phase reports the fraction of the cost taken by each block.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import fields
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

import hydromodpy.calibration as calibration
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_network import CalibOutputNetwork
from hydromodpy.calibration.config_objective import CalibObjectiveBlockDecl
from hydromodpy.calibration.config_outputs import validate_calib_output
from hydromodpy.calibration.config_terms import CalibWindow
from hydromodpy.calibration.criteria.hydrographic_network_distance import (
    distance_gap,
    distance_mean,
)
from hydromodpy.calibration.criteria.registry import NETWORK_ESTIMATORS
from hydromodpy.calibration.criteria.series import HIGHER_IS_BETTER, METRICS
from hydromodpy.calibration.metrics.composite import build_metric_extractor
from hydromodpy.calibration.optim import objective as objective_module
from hydromodpy.calibration.optim.objective import (
    CompositeObjective,
    ConfigBlockObjective,
    ObjectiveValue,
    SimulationOutput,
    build_objective_from_config,
    cost_block_fractions,
    mean_cost_block_fractions,
    non_finite_diagnosis,
)
from hydromodpy.calibration.optim.optimizer import EngineTraits, EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners.search import phase_cost_block_fractions
from hydromodpy.calibration.runners.staged_runner import _reused_phase_cost_block_fractions
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_param.sections import FieldHomogeneousSection
from hydromodpy.core.scoring.metric_table import METRIC_SPECS
from hydromodpy.core.scoring.metrics import log_nse
from tests.unit.calibration._factories import _score


def network_output() -> CalibOutputNetwork:
    return validate_calib_output({"support": "network", "map": {"complete": "streams.gpkg"}})


def q_cfg(observed=(1.0, 2.0, 3.0, 4.0), metric="nse_log", name="b") -> CalibrationConfig:
    # A boundary discharge output q scored by one block.
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "outputs": {
                "q": {
                    "variable": "discharge",
                    "support": "boundary",
                    "boundary_id": "outlet",
                    "observed_values": list(observed),
                }
            },
            "objective_blocks": [{"name": name, "metric": metric, "uses_outputs": ["q"]}],
        }
    )


HEAD_A = {
    "variable": "head",
    "support": "cell",
    "row": 0,
    "col": 0,
    "observed_values": [1.0, 2.0, 3.0],
}


def head_cfg(observed=(1.0, 2.0, 3.0), **block) -> CalibrationConfig:
    # One cell output head_A scored by one block, whose keys are given.
    output = {**HEAD_A, "observed_values": list(observed)}
    return CalibrationConfig.model_validate(
        {
            "outputs": {"head_A": output},
            "objective_blocks": [{"name": "head_block", "uses_outputs": ["head_A"], **block}],
        }
    )


def one_block_cfg() -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "objective": "rmse",
            "variable": "head",
            "outputs": {"head_A": HEAD_A},
            "objective_blocks": [
                {"name": "rmse_head", "metric": "rmse", "weight": 1.0, "uses_outputs": ["head_A"]}
            ],
        }
    )


def two_blocks_cfg() -> CalibrationConfig:
    # Meters and m3/s are both normalized, because a sum of two units would let
    # their magnitudes set the weighting.
    outlet = {
        "variable": "discharge",
        "support": "boundary",
        "boundary_id": "outlet",
        "observed_values": [10.0, 20.0, 30.0],
    }
    return CalibrationConfig.model_validate(
        {
            "method": "cma_es",
            "outputs": {"head_A": HEAD_A, "outlet": outlet},
            "objective_blocks": [
                {
                    "name": "head_block",
                    "metric": "rmse",
                    "weight": 2.0,
                    "uses_outputs": ["head_A"],
                    "normalize_cost": True,
                },
                {
                    "name": "discharge_block",
                    "metric": "rmse",
                    "weight": 1.0,
                    "uses_outputs": ["outlet"],
                    "normalize_cost": True,
                },
            ],
        }
    )


def net_cfg(metric="distance_gap") -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "outputs": {"net": {"support": "network", "map": {"complete": "streams.gpkg"}}},
            "objective_blocks": [{"name": "gap", "metric": metric, "uses_outputs": ["net"]}],
        }
    )


def net_block(**fields_) -> ConfigBlockObjective:
    arguments = {"name": "gap", "metric": "distance_gap", "uses_outputs": ["net"]}
    return ConfigBlockObjective(observed_by_output={}, **{**arguments, **fields_})


def block_on(station: str, values: np.ndarray, metric: str) -> ConfigBlockObjective:
    return ConfigBlockObjective(
        name=station, metric=metric, uses_outputs=[station], observed_by_output={station: values}
    )


def simulation_of(values_by_station: dict[str, np.ndarray]) -> SimulationOutput:
    first = next(iter(values_by_station.values()))
    return SimulationOutput(
        sim_id="sim-test",
        stations=tuple(values_by_station),
        times=np.arange(first.size, dtype=float),
        values=values_by_station,
    )


class SimStub:
    def __init__(self, values: dict[str, list[float]]):
        self.values = values


class Returns:
    def __init__(self, out, name="block"):
        self.out, self.name = out, name

    def evaluate(self, sim):
        return self.out


def test_network_output_declares_no_observed_values():
    assert "observed_values" not in CalibOutputNetwork.model_fields


def test_distances_are_the_network_estimators():
    assert {"distance_gap", "distance_mean"} == NETWORK_ESTIMATORS


DISTANCES = [
    pytest.param(distance_gap, [300.0, 100.0], 200.0, id="gap"),
    pytest.param(distance_gap, [100.0, 300.0], 200.0, id="gap, reversed pair"),
    pytest.param(distance_mean, [300.0, 100.0], 200.0, id="mean"),
]


@pytest.mark.parametrize(("estimator", "pair", "expected"), DISTANCES)
def test_distance_estimators(estimator, pair, expected):
    assert estimator(np.array(pair)) == pytest.approx(expected)


# (D_so, D_os) is the pair of simulated distances from each network to the other, in m.
CRITERION_BLOCKS = [
    pytest.param("distance_gap", [120.0, 100.0], 20.0, id="gap"),
    pytest.param("distance_mean", [120.0, 100.0], 110.0, id="mean"),
]


@pytest.mark.parametrize(("metric", "pair", "total"), CRITERION_BLOCKS)
def test_criterion_block_needs_no_observed_vector(metric, pair, total):
    assert net_block(metric=metric).evaluate({"net": pair}).total == pytest.approx(total)


CRITERION_FROM_CONFIG = [
    pytest.param("distance_gap", [300.0, 100.0], 200.0, id="gap"),
    pytest.param("distance_gap", [150.0, 150.0], 0.0, id="balanced networks"),
    pytest.param("distance_mean", [300.0, 100.0], 200.0, id="mean"),
]


@pytest.mark.parametrize(("metric", "pair", "total"), CRITERION_FROM_CONFIG)
def test_criterion_block_from_config(metric, pair, total):
    value = build_objective_from_config(net_cfg(metric)).evaluate({"net": pair})

    assert value.total == pytest.approx(total)
    assert value.components["gap.n_values"] == 2.0


def test_objective_from_a_bare_namespace():
    objective = build_objective_from_config(
        SimpleNamespace(
            outputs={"net": network_output()},
            objective_blocks=[
                CalibObjectiveBlockDecl(name="gap", metric="distance_gap", uses_outputs=["net"])
            ],
        )
    )

    assert objective.evaluate({"net": np.array([120.0, 100.0])}).total == pytest.approx(20.0)


def test_pair_refusal():
    with pytest.raises(ValueError, match="pair"):
        net_block().evaluate({"net": [1.0, 2.0, 3.0]})


# A distance is divided by the validity length (m) the trial published, one per value.
DISTANCE_SCALES = [
    pytest.param({"net": [100.0, 100.0]}, 2.0, None, id="published"),
    pytest.param({}, None, "published none", id="none published"),
    pytest.param({"net": [100.0]}, None, "published 1 for 2 values", id="too few"),
    pytest.param({"net": [0.0, 100.0]}, None, "divided by a positive length", id="zero length"),
]


@pytest.mark.parametrize(("scales", "total", "match"), DISTANCE_SCALES)
def test_distances_divided_by_the_validity_length(scales, total, match):
    block = net_block(normalize_cost=True, distance_scales=scales)

    if match is None:
        assert block.evaluate({"net": [300.0, 100.0]}).total == pytest.approx(total)
    else:
        with pytest.raises(ValueError, match=match):
            block.evaluate({"net": [300.0, 100.0]})


OBSERVED_HEADS = np.array([1.0, 2.0, 3.0])
HEAD_STD = float(np.std(OBSERVED_HEADS))  # sqrt(2/3)

# Every simulated head is 0.5 m above its observation, so the rmse is 0.5 m.
COSTS = [
    pytest.param(one_block_cfg(), [1.0, 2.0, 3.0], 0.0, id="perfect match"),
    pytest.param(one_block_cfg(), [1.5, 2.5, 3.5], 0.5, id="rmse"),
    pytest.param(head_cfg(name="nse_head", metric="nse"), [1.0, 2.0, 3.0], 0.0, id="nse is a cost"),
    pytest.param(
        head_cfg(metric="rmse", cost_transform="identity"), [1.5, 2.5, 3.5], 0.5, id="identity"
    ),
    pytest.param(
        head_cfg(metric="rmse", normalize_cost=True),
        [1.5, 2.5, 3.5],
        0.5 / HEAD_STD,
        id="normalized by the observed std",
    ),
    pytest.param(
        head_cfg(observed=(10.0, 20.0, 30.0), name="b", metric="rmse"),
        [12.0, 22.0, 32.0],
        2.0,
        id="two units too high",
    ),
]


@pytest.mark.parametrize(("cfg", "simulated", "total"), COSTS)
def test_cost_of_one_block(cfg, simulated, total):
    result = build_objective_from_config(cfg).evaluate({"head_A": simulated})

    assert result.total == pytest.approx(total)


def test_nse_log_registered_higher_better():
    assert METRICS["nse_log"] is log_nse
    assert "nse_log" in HIGHER_IS_BETTER


def test_perfect_nse_log_costs_zero():
    # nse_log is higher-is-better, so the cost is 1 - value and a perfect match lands on zero.
    objective = build_objective_from_config(q_cfg())

    assert objective.evaluate({"q": [1.0, 2.0, 3.0, 4.0]}).total == pytest.approx(0.0)


def test_inverse_transform_keeps_minimization_order():
    objective = build_objective_from_config(head_cfg(metric="rmse", cost_transform="inverse"))

    perfect = objective.evaluate({"head_A": [1.0, 2.0, 3.0]})
    worse = objective.evaluate({"head_A": [2.0, 3.0, 4.0]})

    assert perfect.total < worse.total


def test_missing_simulated_output_costs_infinity():
    result = build_objective_from_config(one_block_cfg()).evaluate(
        {"other_output": [1.0, 2.0, 3.0]}
    )

    assert math.isinf(result.total)


def test_mismatched_simulated_length_refused():
    objective = build_objective_from_config(one_block_cfg())

    with pytest.raises(ValueError, match="simulated length 2 does not match observed length 3"):
        objective.evaluate({"head_A": [1.0, 2.0]})


def test_wrong_length_names_its_output():
    # With the defect on output "b" only, a check of the first output alone would pass.
    observed = {"a": [1.0] * 10, "b": [2.0] * 20, "c": [3.0] * 40}
    sim = {"a": [1.0] * 10, "b": [2.0] * 30, "c": [3.0] * 30}
    block = ConfigBlockObjective(
        name="x", metric="rmse", uses_outputs=["a", "b", "c"], observed_by_output=observed
    )

    with pytest.raises(ValueError, match="output 'b'"):
        block.evaluate(sim)


# A trial the optimizer steps over is an infinite cost, never an exception.
SOFT_REJECTIONS = [
    pytest.param({"a": []}, {"a": [1.0, 2.0, 3.0]}, id="no observation"),
    pytest.param({"a": [1.0, 2.0, 3.0]}, {"a": []}, id="no simulated value"),
]


@pytest.mark.parametrize(("observed", "sim"), SOFT_REJECTIONS)
def test_rejected_trial_costs_infinity(observed, sim):
    block = ConfigBlockObjective(
        name="x", metric="rmse", uses_outputs=["a"], observed_by_output=observed
    )

    assert block.evaluate(sim).total == float("inf")


def test_undefined_cost_warns_once(caplog):
    block = ConfigBlockObjective(
        name="q", metric="nse", uses_outputs=["q"], observed_by_output={"q": np.ones(4)}
    )

    with caplog.at_level(logging.WARNING):
        first = block.evaluate({"q": np.arange(4.0)})
        block.evaluate({"q": np.arange(4.0)})

    assert first.total == math.inf
    assert sum("is undefined on this trial" in m for m in caplog.messages) == 1


SPREAD_OBSERVED = np.array([10.0, 0.5, 9.0, 1.0, 8.0, 2.0, 5.0, 5.2, 4.9, 5.1, 5.0, 5.3])


def normalized_block(observed: np.ndarray) -> ConfigBlockObjective:
    return ConfigBlockObjective(
        name="q",
        metric="rmse",
        uses_outputs=["q"],
        observed_by_output={"q": observed},
        normalize_cost=True,
    )


def test_scale_is_observed_spread():
    value = normalized_block(SPREAD_OBSERVED).evaluate({"q": SPREAD_OBSERVED + 0.3})

    assert value.components["q.reference_scale"] == pytest.approx(float(np.std(SPREAD_OBSERVED)))


def test_flat_sample_fallback_is_logged_once(caplog):
    flat = np.full(8, 4.0)
    block = normalized_block(flat)

    with caplog.at_level(logging.WARNING, logger=objective_module.__name__):
        first = block.evaluate({"q": flat + 1.0})
        block.evaluate({"q": flat + 2.0})

    assert first.components["q.reference_scale"] == pytest.approx(4.0)
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 1
    assert "mean absolute" in messages[0]


def test_block_names_its_metric_and_outputs():
    block = normalized_block(np.array([1.0, 2.0]))

    assert (block.metric, block.uses_outputs) == ("rmse", ("q",))


# Efficiency scores have no unit to remove, so normalizing them only changes the weights.
def test_efficiency_scores_have_no_unit():
    flagged = {name for name, spec in METRIC_SPECS.items() if spec.dimensionless}
    assert {"nse", "kge", "nse_log", "nse_delta", "nse_seasonal", "reservoir"} <= flagged


def test_residual_metrics_have_a_unit():
    assert not METRIC_SPECS["rmse"].dimensionless
    assert not METRIC_SPECS["mae"].dimensionless


BLOCK_ARGUMENTS = {"name": "b", "metric": "rmse", "uses_outputs": ["q"], "observed_by_output": {}}
EFFICIENCY = {"observed_by_output": {"q": (1.0, 2.0, 3.0)}, "normalize_cost": True}
BLOCK_REFUSALS = [
    pytest.param({"uses_outputs": ["out"]}, "observed", id="ordinary metric without observations"),
    pytest.param(
        {"metric": "no_such_metric"}, "unknown metric 'no_such_metric'", id="unknown metric"
    ),
    pytest.param({"uses_outputs": []}, "uses_outputs must not be empty", id="no output"),
    pytest.param({"metric": "nse", **EFFICIENCY}, "normalize_cost", id="normalized nse"),
    pytest.param({"metric": "kge", **EFFICIENCY}, "normalize_cost", id="normalized kge"),
    pytest.param({"metric": "nse_log", **EFFICIENCY}, "normalize_cost", id="normalized nse_log"),
    pytest.param(
        {"metric": "reservoir", **EFFICIENCY}, "normalize_cost", id="normalized reservoir"
    ),
    pytest.param(
        {"metric": "nse", **EFFICIENCY},
        r"(?s)(?=.*nse)(?=.*weight)",
        id="refusal names the metric and the way out",
    ),
]


@pytest.mark.parametrize(("kwargs", "match"), BLOCK_REFUSALS)
def test_block_refusals(kwargs, match):
    with pytest.raises(ValueError, match=match):
        ConfigBlockObjective(**{**BLOCK_ARGUMENTS, **kwargs})


def test_declaration_refuses_normalized_efficiency():
    with pytest.raises(ValueError, match="normalize_cost"):
        CalibObjectiveBlockDecl(name="b", metric="nse", uses_outputs=["q"], normalize_cost=True)


def test_config_refusals():
    with pytest.raises(ValueError, match="objective_blocks is empty"):
        build_objective_from_config(CalibrationConfig.model_validate({}))

    no_observations = CalibrationConfig.model_validate(
        {
            "outputs": {"head_A": {"variable": "head", "support": "cell", "row": 0, "col": 0}},
            "objective_blocks": [{"name": "b", "metric": "rmse", "uses_outputs": ["head_A"]}],
        }
    )
    with pytest.raises(ValueError, match="no observed values"):
        build_objective_from_config(no_observations)


def test_block_route_is_taken():
    cfg = CalibrationConfig.model_validate(
        {
            "method": "grid",
            "variable": "head",
            "outputs": {"head_A": HEAD_A},
            "objective_blocks": [
                {"name": "head_block", "metric": "rmse", "uses_outputs": ["head_A"]}
            ],
        }
    )
    ctx = SimpleNamespace(
        setup=SimpleNamespace(cell_mesh=None, domain=None, time_grid=None),
        loaded_data=SimpleNamespace(piezometry=None, hydrometry=None),
        execution=None,
    )
    metric_fn = build_metric_extractor(
        cfg.variable,
        cfg.objective,
        ctx,
        outputs=cfg.outputs or None,
        objective_blocks=cfg.objective_blocks or None,
    )

    # It fails on the missing flow run, not on the single-metric branch.
    with pytest.raises(NotImplementedError, match="No flow solver adapter"):
        metric_fn(ctx)


def test_reversed_window_refused():
    with pytest.raises(ValueError, match="is after end"):
        CalibWindow(start="2015-01-01", end="2012-01-01")


def test_score_drops_samples_outside_window():
    index = pd.date_range("2020-01-01", periods=4, freq="D")
    observed = pd.Series([1.0, 1.0, 1.0, 1.0], index=index)
    # The first two days are badly simulated, the last two are perfect.
    simulated = pd.Series([9.0, 9.0, 1.0, 1.0], index=index)
    window = (pd.Timestamp("2020-01-03"), None)

    full, _ = _score(observed, simulated, "rmse", variable="head")
    scored, _ = _score(observed, simulated, "rmse", variable="head", window=window)

    assert scored == pytest.approx(0.0)
    assert full > scored


def test_empty_window_is_an_error():
    index = pd.date_range("2020-01-01", periods=3, freq="D")
    series = pd.Series([1.0, 2.0, 3.0], index=index)

    with pytest.raises(ValueError, match="share no timestamp inside"):
        _score(series, series, "rmse", variable="head", window=(pd.Timestamp("2030-01-01"), None))


# A window in dates has nothing to cut on the block route, and says so.
BLOCK_ROUTE_WINDOWS = [
    pytest.param((pd.Timestamp("2012-01-01"), None), id="start only"),
    pytest.param((None, pd.Timestamp("2015-12-31")), id="end only"),
]


@pytest.mark.parametrize("window", BLOCK_ROUTE_WINDOWS)
def test_window_refused_on_the_block_route(window):
    cfg = q_cfg(metric="rmse")

    with pytest.raises(ValueError, match=r"(?s)(?=.*no time axis)(?=.*'b')"):
        build_metric_extractor(
            None,
            None,
            None,
            window=window,
            outputs=cfg.outputs,
            objective_blocks=cfg.objective_blocks,
        )


def test_window_with_two_open_bounds_builds():
    cfg = q_cfg(metric="rmse")

    assert build_metric_extractor(
        None,
        None,
        None,
        window=(None, None),
        outputs=cfg.outputs,
        objective_blocks=cfg.objective_blocks,
    )


def test_weighted_sum_of_normalized_blocks():
    objective = build_objective_from_config(two_blocks_cfg())
    # Block 1 (head_A) is perfect. Block 2 (outlet) is off by +5 each step, so its rmse is 5.
    result = objective.evaluate(SimStub({"head_A": [1.0, 2.0, 3.0], "outlet": [15.0, 25.0, 35.0]}))
    # Each cost is divided by the std of its own observations before the weights apply, so
    # meters and m3/s become pure numbers first. Weights [2, 1] normalize to [2/3, 1/3].
    head_scale = float(np.std([1.0, 2.0, 3.0]))
    flow_scale = float(np.std([10.0, 20.0, 30.0]))
    expected = (2.0 / 3.0) * (0.0 / head_scale) + (1.0 / 3.0) * (5.0 / flow_scale)
    assert result.total == pytest.approx(expected)


def pair_of_blocks(offset_a: float, offset_b: float, metric: str = "nse", start_b: float = 10.0):
    # Two blocks on stations A and B, each simulated at its observations plus an offset.
    obs_a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    obs_b = np.arange(5.0) + start_b
    sim = simulation_of({"A": obs_a + offset_a, "B": obs_b + offset_b})
    return block_on("A", obs_a, metric), block_on("B", obs_b, metric), sim


def test_equal_weights_give_the_mean_cost():
    block_a, block_b, sim = pair_of_blocks(0.5, 2.0)
    cost_a = block_a.evaluate(sim).total
    cost_b = block_b.evaluate(sim).total

    out = CompositeObjective([(block_a, 1.0), (block_b, 1.0)]).evaluate(sim)

    assert out.total == pytest.approx(0.5 * cost_a + 0.5 * cost_b)
    assert cost_a != cost_b


def test_weights_shift_the_total():
    block_a, block_b, sim = pair_of_blocks(0.1, 5.0, start_b=1.0)
    cost_a = block_a.evaluate(sim).total
    cost_b = block_b.evaluate(sim).total
    assert cost_a < cost_b

    out = CompositeObjective([(block_a, 0.8), (block_b, 0.2)]).evaluate(sim)
    out_equal = CompositeObjective([(block_a, 1.0), (block_b, 1.0)]).evaluate(sim)

    assert out.total == pytest.approx(0.8 * cost_a + 0.2 * cost_b)
    assert out.total < out_equal.total


def test_weights_are_normalized_to_one():
    block_a, block_b, sim = pair_of_blocks(0.3, 1.5, "rmse")

    raw = CompositeObjective([(block_a, 3.0), (block_b, 1.0)])
    normalized = CompositeObjective([(block_a, 0.75), (block_b, 0.25)])

    assert raw.evaluate(sim).total == pytest.approx(normalized.evaluate(sim).total)
    weights = [w for _, w in raw.blocks]
    assert sum(weights) == pytest.approx(1.0)
    assert weights == pytest.approx([0.75, 0.25])


def test_log_transform_keeps_minimization_order():
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    block = block_on("A", obs, "rmse")
    perfect = simulation_of({"A": obs.copy()})
    bad = simulation_of({"A": obs + 10.0})

    identity_total = (
        CompositeObjective([(block, 1.0)], cost_transform="identity").evaluate(perfect).total
    )
    log_composite = CompositeObjective([(block, 1.0)], cost_transform="log")
    log_total = log_composite.evaluate(perfect).total
    bad_log_total = log_composite.evaluate(bad).total

    assert identity_total == pytest.approx(0.0, abs=1.0e-12)
    assert math.isfinite(log_total)
    assert log_total < bad_log_total


def test_composite_name_and_default_transform():
    block = block_on("A", np.array([1.0, 2.0, 3.0]), "nse")
    composite = CompositeObjective([(block, 1.0)], name="my_composite")

    assert composite.name == "my_composite"
    assert composite.cost_transform == "identity"


A_BLOCK = block_on("A", np.array([1.0, 2.0, 3.0]), "nse")
WEIGHT_MATCH = "weight must be finite and > 0"
COMPOSITE_REFUSALS = [
    pytest.param([], {}, ValueError, "at least one block", id="no block"),
    pytest.param([(A_BLOCK, 0.0)], {}, ValueError, WEIGHT_MATCH, id="zero weight"),
    pytest.param([(A_BLOCK, -1.0)], {}, ValueError, WEIGHT_MATCH, id="negative weight"),
    pytest.param([(A_BLOCK, float("nan"))], {}, ValueError, WEIGHT_MATCH, id="nan weight"),
    pytest.param(
        [(A_BLOCK, 1.0)],
        {"cost_transform": "zigzag"},
        ValueError,
        "Unknown cost_transform",
        id="transform",
    ),
    pytest.param([A_BLOCK], {}, TypeError, "must be an .*tuple", id="weight forgotten"),
    pytest.param(
        [(object(), 1.0)],
        {},
        TypeError,
        "Block 0: first element must implement .evaluate",
        id="block that cannot evaluate",
    ),
]


@pytest.mark.parametrize(("blocks", "kwargs", "error", "match"), COMPOSITE_REFUSALS)
def test_composite_refusals(blocks, kwargs, error, match):
    with pytest.raises(error, match=match):
        CompositeObjective(blocks, **kwargs)


def test_same_name_blocks_stay_apart():
    composite = CompositeObjective(
        [
            (Returns({"total": 1.0, "n": 5.0}, name="nse"), 1.0),
            (Returns({"total": 3.0, "n": 7.0}, name="nse"), 1.0),
            (Returns({"total": 5.0, "n": 9.0}, name="nse"), 2.0),
        ]
    )

    value = composite.evaluate({})

    assert value.total == pytest.approx(0.25 * 1.0 + 0.25 * 3.0 + 0.5 * 5.0)
    assert value.components == {
        "nse.total": 1.0,
        "n": 5.0,
        "nse#1.total": 3.0,
        "nse.n": 7.0,
        "nse#2.total": 5.0,
        "nse#2.n": 9.0,
    }


# One efficiency per station, then the weighted mean of the costs.
OBSERVED = {
    "a": np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
    "b": np.array([100.0, 200.0, 300.0, 400.0, 500.0]),
}
SIMULATED = {
    "a": np.array([5.0, 4.0, 3.0, 2.0, 1.0]),
    "b": np.array([110.0, 190.0, 310.0, 390.0, 505.0]),
}


def nse_by_hand(simulated: np.ndarray, observed: np.ndarray) -> float:
    return 1.0 - float(
        np.sum((simulated - observed) ** 2) / np.sum((observed - observed.mean()) ** 2)
    )


def mean_cost_by_hand(weights: dict[str, float]) -> float:
    costs = {name: 1.0 - nse_by_hand(SIMULATED[name], OBSERVED[name]) for name in OBSERVED}
    return sum(weights[n] * costs[n] for n in costs) / sum(weights.values())


def two_stations() -> SimulationOutput:
    return SimulationOutput(sim_id="s", stations=("a", "b"), times=np.arange(5.0), values=SIMULATED)


@pytest.mark.parametrize("weights", [{"a": 1.0, "b": 1.0}, {"a": 2.0, "b": 1.0}])
def test_weighted_mean_of_station_blocks(weights):
    blocks = [(block_on(name, OBSERVED[name], "nse"), weights[name]) for name in ("a", "b")]

    value = CompositeObjective(blocks).evaluate(two_stations())

    assert value.total == pytest.approx(mean_cost_by_hand(weights))


def test_pooled_outputs_differ_from_mean():
    pooled = ConfigBlockObjective(
        name="both", metric="nse", uses_outputs=["a", "b"], observed_by_output=OBSERVED
    ).evaluate(two_stations())

    assert pooled.total != pytest.approx(mean_cost_by_hand({"a": 1.0, "b": 1.0}), abs=0.1)


def test_cost_transforms():
    class Fixed:
        name = "fixed"

        def evaluate(self, sim: Any) -> ObjectiveValue:
            return ObjectiveValue(total=9.0, components={})

    composite = CompositeObjective([(Fixed(), 1.0)], cost_transform="log")

    assert composite.cost_transform == "log"
    assert composite.evaluate(None).total == pytest.approx(0.9542425, rel=1e-5)
    simulated = SimulationOutput(
        sim_id="s", stations=("q",), times=np.arange(2), values={"q": np.array([2.0, 4.0])}
    )
    costs = {
        word: ConfigBlockObjective(
            name="q",
            metric="rmse",
            uses_outputs=["q"],
            observed_by_output={"q": [1.0, 2.0]},
            cost_transform=word,
        )
        .evaluate(simulated)
        .total
        for word in ("identity", "log", "inverse")
    }
    assert costs["identity"] == pytest.approx(math.sqrt(2.5))
    assert costs["log"] == pytest.approx(math.log10(math.sqrt(2.5) + 1e-6))
    assert costs["inverse"] == pytest.approx(-1.0 / (math.sqrt(2.5) + 1e-6))


TRANSFORM_REFUSALS = [
    pytest.param("log", -2.0, "cost \\+ epsilon > 0", id="log of a negative"),
    pytest.param("inverse", -1e-6, "cost \\+ epsilon != 0", id="inverse of zero"),
]


@pytest.mark.parametrize(("transform", "cost", "match"), TRANSFORM_REFUSALS)
def test_cost_transform_refusals(transform, cost, match):
    with pytest.raises(ValueError, match=match):
        objective_module._TRANSFORMS[transform](cost)


USER_ANSWERS = [
    pytest.param(2, 2.0, {}, id="int"),
    pytest.param({"total": 3.0, "a": 1}, 3.0, {"a": 1.0}, id="total"),
    pytest.param({"value": 4.0}, 4.0, {}, id="value"),
    pytest.param({"a": 1.0}, math.inf, {"a": 1.0}, id="no total"),
]


@pytest.mark.parametrize(("out", "total", "components"), USER_ANSWERS)
def test_user_objective_answers(out, total, components):
    value = objective_module.evaluate_objective(Returns(out), {})

    assert (value.total, value.components) == (total, components)


def test_user_objective_refuses_a_string():
    with pytest.raises(TypeError, match="Unsupported Objective return type"):
        objective_module.evaluate_objective(Returns("fast"), {})


def test_no_objective_beside_the_blocks():
    for name in ("ScalarObjective", "ObservationSet"):
        assert name not in vars(calibration).get("__all__", ())
        assert not hasattr(calibration, name)
        assert not hasattr(objective_module, name)
    assert hasattr(objective_module, "ConfigBlockObjective")
    assert hasattr(objective_module, "CompositeObjective")


BLOCKS = [("network", 1.0), ("hydrograph", 3.0)]  # normalized: 0.25 / 0.75
TOTALS_A = {"network.total": 10.0, "hydrograph.total": 2.0}  # network 0.625, hydrograph 0.375
TOTALS_B = {"network.total": 2.0, "hydrograph.total": 2.0}  # network 0.25, hydrograph 0.75


def test_fraction_is_the_normalized_weighted_contribution():
    fractions = cost_block_fractions(TOTALS_A, BLOCKS)

    # contributions: 0.25 * 10 = 2.5, 0.75 * 2 = 1.5, sum = 4.0
    assert fractions == pytest.approx({"network": 0.625, "hydrograph": 0.375})
    assert sum(fractions.values()) == pytest.approx(1.0)


NO_FRACTION = [
    pytest.param({}, [], id="no declared block"),
    pytest.param({"a.total": 5.0, "b.total": -5.0}, [("a", 1.0), ("b", 1.0)], id="sum to zero"),
    pytest.param({"a.total": 1.0, "b.total": 1.0}, [("a", 0.0), ("b", 0.0)], id="zero weights"),
]


@pytest.mark.parametrize(("components", "blocks"), NO_FRACTION)
def test_no_fraction_when_undefined(components, blocks):
    assert cost_block_fractions(components, blocks) is None


MEAN_FRACTIONS = [
    pytest.param(
        [TOTALS_A, TOTALS_B], {"network": 0.4375, "hydrograph": 0.5625}, 2, id="exact average"
    ),
    # No hydrograph.total in the second trial: it cannot be told apart, so it is skipped.
    pytest.param(
        [TOTALS_B, {"network.total": 5.0}], {"network": 0.25, "hydrograph": 0.75}, 1, id="skip one"
    ),
]


@pytest.mark.parametrize(("trials", "expected", "n_trials"), MEAN_FRACTIONS)
def test_mean_fraction_over_the_trials(trials, expected, n_trials):
    mean, n = mean_cost_block_fractions(BLOCKS, trials)

    assert mean == pytest.approx(expected)
    assert n == n_trials


def test_mean_fraction_without_a_computable_trial():
    assert mean_cost_block_fractions(BLOCKS, [{"network.total": 5.0}, None]) is None
    assert mean_cost_block_fractions([], [{}]) is None


def test_signed_criterion_total_is_non_negative():
    # distance_gap publishes a signed residual, but .total already holds abs(D_so - D_os).
    network = ConfigBlockObjective(
        name="network", metric="distance_gap", uses_outputs=["net"], observed_by_output={}
    )
    hydrograph = ConfigBlockObjective(
        name="hydrograph",
        metric="rmse",
        uses_outputs=["q"],
        observed_by_output={"q": [1.0, 2.0, 3.0]},
    )
    composite = CompositeObjective([(network, 1.0), (hydrograph, 3.0)], name="composite")
    # D_so=5, D_os=8: the signed residual is -3, but the cost is abs(-3) = 3.
    sim = {"net": [5.0, 8.0], "q": [1.5, 2.5, 3.5]}

    value = composite.evaluate(sim)
    fractions = cost_block_fractions(value.components, BLOCKS)

    assert value.components["network.total"] == pytest.approx(3.0)
    weighted_network = 0.25 * value.components["network.total"]
    weighted_hydrograph = 0.75 * value.components["hydrograph.total"]
    denom = weighted_network + weighted_hydrograph
    assert denom == pytest.approx(value.total)
    assert fractions == pytest.approx(
        {"network": weighted_network / denom, "hydrograph": weighted_hydrograph / denom}
    )
    assert all(0.0 <= fraction <= 1.0 for fraction in fractions.values())


def trial_result(trial_id: int, cost: float, components: dict | None, status="completed"):
    return EvaluationResult(
        trial_id=trial_id, sim_id=None, cost=cost, components=components, status=status
    )


def blocks_cfg(blocks: list[tuple[str, float]]) -> SimpleNamespace:
    return SimpleNamespace(
        objective_blocks=[SimpleNamespace(name=name, weight=weight) for name, weight in blocks]
    )


def test_phase_report_mean_and_best():
    history = [trial_result(1, 4.0, TOTALS_A), trial_result(2, 2.0, TOTALS_B)]

    fractions = phase_cost_block_fractions(blocks_cfg(BLOCKS), history, history[1])

    assert fractions["mean_n_trials"] == 2
    assert fractions["mean"] == pytest.approx({"network": 0.4375, "hydrograph": 0.5625})
    assert fractions["best"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})


def test_failed_trial_leaves_the_mean():
    failed = {"network.total": 999.0, "hydrograph.total": 999.0}
    history = [
        trial_result(1, 2.0, TOTALS_B),
        trial_result(2, float("inf"), failed, status="failed"),
    ]

    fractions = phase_cost_block_fractions(blocks_cfg(BLOCKS), history, history[0])

    assert fractions["mean_n_trials"] == 1
    assert fractions["mean"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})


def seed_trials(tmp_path, trials: list[tuple[str, float, dict | None]]) -> CalibrationPersistence:
    # Journal one session with the given (status, cost, components) trials.
    session_dir = tmp_path / "sessions" / "calage"
    session_dir.mkdir(parents=True, exist_ok=True)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(
        session_id=uuid.uuid4().hex,
        case_id="calage",
        site=None,
        project="unit_test",
        config_hash="c" * 64,
        hydromodpy_version="2.0.0a5",
        method="grid",
        cost_name="composite",
        bounds={},
        windows={},
    )
    for index, (status, cost, components) in enumerate(trials):
        result = EvaluationResult(
            trial_id=index, sim_id=None, cost=cost, status=status, components=components
        )
        persistence.append_iteration(ParamSuggestion(trial_id=index, values={}), result)
    persistence.finalize_session(status="completed", best=None)
    return persistence


def test_reused_phase_fractions(tmp_path):
    persistence = seed_trials(
        tmp_path, [("completed", 4.0, TOTALS_A), ("completed", 2.0, TOTALS_B)]
    )

    fractions, note = _reused_phase_cost_block_fractions(blocks_cfg(BLOCKS), persistence, "main")

    assert note is None
    assert fractions["mean_n_trials"] == 2
    assert fractions["mean"] == pytest.approx({"network": 0.4375, "hydrograph": 0.5625})
    # Trial 2 (cost 2.0) is the best.
    assert fractions["best"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})


def test_reused_phase_skips_a_crashed_trial(tmp_path):
    # The journal accepts only finite lifecycle states, and a live run remaps "failed" to "crashed".
    crashed = {"network.total": 999.0, "hydrograph.total": 999.0}
    persistence = seed_trials(
        tmp_path, [("completed", 2.0, TOTALS_B), ("crashed", float("inf"), crashed)]
    )

    fractions, note = _reused_phase_cost_block_fractions(blocks_cfg(BLOCKS), persistence, "main")

    assert note is None
    assert fractions["mean_n_trials"] == 1
    assert fractions["mean"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})


def test_reused_phase_without_components(tmp_path):
    persistence = seed_trials(tmp_path, [("completed", 1.0, None)])

    fractions, note = _reused_phase_cost_block_fractions(blocks_cfg(BLOCKS), persistence, "main")

    assert fractions is None
    assert note is not None
    assert "not recomputed" in note


DIAGNOSES = [
    pytest.param(
        [1.0, np.nan, 3.0],
        [1.0, 2.0, np.inf],
        ("1 of 3 observed", "1 of 3 simulated"),
        id="non-finite samples on each side",
    ),
    # A metric can go non-finite without a non-finite sample, so the ranges are given.
    pytest.param(
        [1.0, 2.0, 3.0],
        [4.0, 5.0, 6.0],
        ("3 sample(s) scored", "[1, 3]", "[4, 6]"),
        id="both ranges",
    ),
]


@pytest.mark.parametrize(("observed", "simulated", "fragments"), DIAGNOSES)
def test_non_finite_diagnosis(observed, simulated, fragments):
    message = non_finite_diagnosis(np.array(observed), np.array(simulated))

    for fragment in fragments:
        assert fragment in message


def test_empty_record_scored_no_sample():
    assert non_finite_diagnosis([], []) == "No sample was scored."


def test_dimension_carries_search_space_and_sampling():
    names = {field.name for field in fields(CalibParameter)}

    assert {"search_space", "sampling"} <= names
    assert not {"transform", "prior"} & names
    parameter = CalibParameter("K", 1e-6, 1e-3, search_space="log", sampling="log_uniform")
    assert parameter.lower_transformed == pytest.approx(-6.0)
    assert parameter.to_physical(-5.0) == pytest.approx(1e-5)


def test_engine_traits_search_space():
    names = {field.name for field in fields(EngineTraits)}

    assert "required_search_space" in names
    assert "required_transform" not in names


def test_field_declares_search_space():
    declared = Calibrable(bounds=(1e-7, 1e-2), search_space="log", sampling="log_uniform")

    assert (declared.search_space, declared.sampling) == ("log", "log_uniform")
    record = declared.to_dict()
    assert (record["search_space"], record["sampling"]) == ("log", "log_uniform")
    assert "transform" not in record and "prior" not in record
    with pytest.raises(TypeError):
        Calibrable(transform="log")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        Calibrable(prior="uniform")  # type: ignore[call-arg]


def test_conductivity_declares_a_log_search():
    declared = FieldHomogeneousSection.model_fields["value"].json_schema_extra["calibrable"]

    assert (declared.search_space, declared.sampling) == ("log", "log_uniform")


def test_catalogue_prints_search_space():
    from tools.docs import field_registry

    leaf = field_registry._leaf_info(
        "value", FieldHomogeneousSection.model_fields["value"], "flow.param.K.field.value"
    )

    assert leaf["calibrable"] == {
        "bounds": None,
        "search_space": "log",
        "sampling": "log_uniform",
        "units": None,
    }
