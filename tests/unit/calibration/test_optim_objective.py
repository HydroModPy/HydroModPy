"""Tests of `optim.objective`."""

from __future__ import annotations

import logging
import math
import re
import tomllib
import uuid
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

import hydromodpy.calibration as calibration
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_network import CalibOutputNetwork
from hydromodpy.calibration.config_objective import CalibObjectiveBlockDecl, CalibParameterDecl
from hydromodpy.calibration.config_outputs import validate_calib_output
from hydromodpy.calibration.config_terms import CalibWindow, window_bounds
from hydromodpy.calibration.criteria.hydrographic_network_distance import (
    distance_gap,
    distance_mean,
)
from hydromodpy.calibration.criteria.registry import NETWORK_ESTIMATORS
from hydromodpy.calibration.criteria.series import HIGHER_IS_BETTER, METRICS
from hydromodpy.calibration.metrics.composite import build_metric_extractor
from hydromodpy.calibration.metrics.composite import (
    build_metric_extractor as build_metric_extractor__log_nse,
)
from hydromodpy.calibration.metrics.observable_scoring import StationBlockScorer
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.calibration.metrics.solver_extract import ExtractedOutputs
from hydromodpy.calibration.optim import objective
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
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners.search import phase_cost_block_fractions
from hydromodpy.calibration.runners.staged_runner import _reused_phase_cost_block_fractions
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_param.sections import FieldHomogeneousSection
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.scoring.metric_table import METRIC_SPECS
from hydromodpy.core.scoring.metrics import clip_negatives, log_nse
from hydromodpy.workflow.steps.prepare_solver.freeze import portable_config_document
from tests.unit.calibration._factories import _score
from tests.unit.config.test_a_renamed_key_warns_and_a_sealed_one_reads import PROJECT, _project

# From test_a_criterion_has_no_observed_vector.py
# A criterion that balances two simulated quantities has nothing to fit.
#
# The stream-network criterion measures the descent from the simulated seepage
# network to the mapped one and, reciprocally, from the mapped one back. Both are
# simulated. Its cost is the imbalance between them, so there is no observed
# series anywhere in it.
#
# The objective could only score a block by pairing a simulated vector with an
# observed one, so the output declared ``observed_values = [0, 0]`` and every
# scoring path went through that fabrication: the length check compared against
# it, the reference scale was read off it, and a reader of the schema was told a
# network output has observations. Two zeros that mean "there is nothing here" are
# a worse answer than saying so.


def _network_output() -> CalibOutputNetwork:
    return validate_calib_output({"support": "network", "map": {"complete": "streams.gpkg"}})


class TestTheDeclaration:
    def test_a_network_output_declares_no_observed_values(self) -> None:
        assert "observed_values" not in CalibOutputNetwork.model_fields

    def test_writing_them_is_refused_rather_than_ignored(self) -> None:
        with pytest.raises(ValueError):
            validate_calib_output(
                {
                    "support": "network",
                    "map": {"complete": "streams.gpkg"},
                    "observed_values": [0.0, 0.0],
                }
            )


class TestTheMetrics:
    def test_the_distances_are_the_network_estimators(self) -> None:
        assert {"distance_gap", "distance_mean"} == NETWORK_ESTIMATORS

    def test_a_block_on_a_criterion_metric_needs_no_observed_vector(self) -> None:
        block = ConfigBlockObjective(
            name="gap", metric="distance_gap", uses_outputs=["net"], observed_by_output={}
        )

        value = block.evaluate({"net": [120.0, 100.0]})

        assert value.total == pytest.approx(20.0)

    def test_the_mean_reads_the_same_pair(self) -> None:
        block = ConfigBlockObjective(
            name="mean", metric="distance_mean", uses_outputs=["net"], observed_by_output={}
        )

        assert block.evaluate({"net": [120.0, 100.0]}).total == pytest.approx(110.0)

    def test_a_pair_that_is_not_a_pair_is_refused(self) -> None:
        block = ConfigBlockObjective(
            name="gap", metric="distance_gap", uses_outputs=["net"], observed_by_output={}
        )

        with pytest.raises(ValueError, match="pair"):
            block.evaluate({"net": [1.0, 2.0, 3.0]})

    def test_an_ordinary_metric_still_needs_its_observations(self) -> None:
        with pytest.raises(ValueError, match="observed"):
            ConfigBlockObjective(
                name="q", metric="rmse", uses_outputs=["out"], observed_by_output={}
            )


class TestTheAssembly:
    def test_a_configuration_declaring_only_a_criterion_block_builds(self) -> None:
        objective = build_objective_from_config(
            SimpleNamespace(
                outputs={"net": _network_output()},
                objective_blocks=[
                    CalibObjectiveBlockDecl(name="gap", metric="distance_gap", uses_outputs=["net"])
                ],
            )
        )

        assert objective.evaluate({"net": np.array([120.0, 100.0])}).total == pytest.approx(20.0)


# From test_a_normalised_cost_is_scaled_by_the_scored_sample.py
# ``normalize_cost`` divides by the spread of what the block scores.

_OBSERVED = np.array([10.0, 0.5, 9.0, 1.0, 8.0, 2.0, 5.0, 5.2, 4.9, 5.1, 5.0, 5.3])


def _block(observed: np.ndarray) -> ConfigBlockObjective:
    return ConfigBlockObjective(
        name="q",
        metric="rmse",
        uses_outputs=["q"],
        observed_by_output={"q": observed},
        normalize_cost=True,
    )


def test_the_scale_is_the_spread_of_the_observed_values() -> None:
    block = _block(_OBSERVED)

    value = block.evaluate({"q": _OBSERVED + 0.3})

    assert value.components["q.reference_scale"] == pytest.approx(float(np.std(_OBSERVED)))


def test_the_fallback_of_a_flat_sample_is_logged_once(caplog) -> None:
    flat = np.full(8, 4.0)
    block = _block(flat)

    with caplog.at_level(logging.WARNING, logger=objective_module.__name__):
        first = block.evaluate({"q": flat + 1.0})
        block.evaluate({"q": flat + 2.0})

    assert first.components["q.reference_scale"] == pytest.approx(4.0)
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 1
    assert "mean absolute" in messages[0]


# From test_build_objective_from_config.py
# Tests for :func:`hydromodpy.calibration.optim.objective.build_objective_from_config`.
#
# Covers Phase 3 of the calibration integration:
#
# - One-block config returns a single :class:`ConfigBlockObjective`.
# - Multi-block config returns a :class:`CompositeObjective` whose total is
#   the weighted sum of each block's transformed cost.
# - ``normalize_cost`` divides the block cost by a reference scale.
# - Per-block ``cost_transform`` (identity / log / inverse) is applied before
#   weighting.
# - Missing simulated values fail loudly.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _q_cfg(observed=(1.0, 2.0, 3.0, 4.0), metric="nse_log", name="b", **top) -> CalibrationConfig:
    """A boundary discharge output ``q`` scored by one block; ``top`` sets top-level keys."""
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            **top,
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


def _head_cfg(observed=(1.0, 2.0, 3.0), **block) -> CalibrationConfig:
    """One cell output ``head_A`` scored by one block; ``block`` sets the block's keys."""
    return CalibrationConfig.model_validate(
        {
            "outputs": {
                "head_A": {
                    "variable": "head",
                    "support": "cell",
                    "row": 0,
                    "col": 0,
                    "observed_values": list(observed),
                }
            },
            "objective_blocks": [{"name": "head_block", "uses_outputs": ["head_A"], **block}],
        }
    )


def _cfg_one_block() -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "objective": "rmse",
            "variable": "head",
            "outputs": {
                "head_A": {
                    "variable": "head",
                    "support": "cell",
                    "row": 0,
                    "col": 0,
                    "observed_values": [1.0, 2.0, 3.0],
                }
            },
            "objective_blocks": [
                {"name": "rmse_head", "metric": "rmse", "weight": 1.0, "uses_outputs": ["head_A"]}
            ],
        }
    )


def _cfg_two_blocks_weighted() -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "cma_es",
            "outputs": {
                "head_A": {
                    "variable": "head",
                    "support": "cell",
                    "row": 0,
                    "col": 0,
                    "observed_values": [1.0, 2.0, 3.0],
                },
                "outlet": {
                    "variable": "discharge",
                    "support": "boundary",
                    "boundary_id": "outlet",
                    "observed_values": [10.0, 20.0, 30.0],
                },
            },
            "objective_blocks": [
                # Meters and m3/s: both normalized, because a sum of two units
                # would let their magnitudes set the weighting.
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


class _SimStub:
    def __init__(self, values: dict[str, list[float]]):
        self.values = values


# ---------------------------------------------------------------------------
# Single-block path
# ---------------------------------------------------------------------------
class TestSingleBlock:
    def test_returns_config_block_objective_when_only_one(self):
        obj = build_objective_from_config(_cfg_one_block())
        assert isinstance(obj, ConfigBlockObjective)
        assert obj.name == "rmse_head"

    def test_perfect_match_yields_zero_cost(self):
        obj = build_objective_from_config(_cfg_one_block())
        result = obj.evaluate({"head_A": [1.0, 2.0, 3.0]})
        assert isinstance(result, ObjectiveValue)
        assert result.total == pytest.approx(0.0)

    def test_rmse_matches_numpy(self):
        obj = build_objective_from_config(_cfg_one_block())
        simulated = [1.5, 2.5, 3.5]
        result = obj.evaluate({"head_A": simulated})
        expected_rmse = math.sqrt(np.mean((np.array(simulated) - np.array([1.0, 2.0, 3.0])) ** 2))
        assert result.total == pytest.approx(expected_rmse)

    def test_nse_is_flipped_into_cost(self):
        cfg = _head_cfg(name="nse_head", metric="nse")
        obj = build_objective_from_config(cfg)
        perfect = obj.evaluate({"head_A": [1.0, 2.0, 3.0]})
        # Perfect NSE = 1.0 → cost should be 0 (1 - 1)
        assert perfect.total == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------
class TestCompositeBlocks:
    def test_returns_composite_when_multiple_blocks(self):
        obj = build_objective_from_config(_cfg_two_blocks_weighted())
        assert isinstance(obj, CompositeObjective)

    def test_weighted_sum_matches_manual_calc(self):
        cfg = _cfg_two_blocks_weighted()
        obj = build_objective_from_config(cfg)
        # Block 1 (head_A) perfectly matched → cost 0.
        # Block 2 (outlet) off by +5 each step → RMSE = 5.
        result = obj.evaluate(_SimStub({"head_A": [1.0, 2.0, 3.0], "outlet": [15.0, 25.0, 35.0]}))
        # Both blocks are normalized, so each cost is divided by the standard
        # deviation of its own observations before the weights apply. That is the
        # whole point of normalizing: the meters and the m3/s become pure numbers
        # first, and only then do the weights decide the shares.
        head_scale = float(np.std([1.0, 2.0, 3.0]))
        flow_scale = float(np.std([10.0, 20.0, 30.0]))
        # weights [2.0, 1.0] normalized to [2/3, 1/3]
        expected = (2.0 / 3.0) * (0.0 / head_scale) + (1.0 / 3.0) * (5.0 / flow_scale)
        assert result.total == pytest.approx(expected)


class TestNormalizeCost:
    def test_normalize_divides_by_observed_std(self):
        cfg = _head_cfg(metric="rmse", normalize_cost=True)
        obj = build_objective_from_config(cfg)
        # observed std = std([1,2,3]) = sqrt(2/3) ≈ 0.8165
        # simulated +0.5 everywhere → raw RMSE = 0.5
        simulated = [1.5, 2.5, 3.5]
        result = obj.evaluate({"head_A": simulated})
        scale = float(np.nanstd(np.array([1.0, 2.0, 3.0])))
        assert result.total == pytest.approx(0.5 / scale)


class TestTransform:
    def test_inverse_transform_keeps_minimization_order(self):
        cfg = _head_cfg(metric="rmse", cost_transform="inverse")
        obj = build_objective_from_config(cfg)
        perfect = obj.evaluate({"head_A": [1.0, 2.0, 3.0]})
        worse = obj.evaluate({"head_A": [2.0, 3.0, 4.0]})
        assert perfect.total < worse.total

    def test_identity_transform_is_passthrough(self):
        cfg = _head_cfg(metric="rmse", cost_transform="identity")
        obj = build_objective_from_config(cfg)
        result = obj.evaluate({"head_A": [1.5, 2.5, 3.5]})
        assert result.total == pytest.approx(0.5)


class TestErrors:
    def test_empty_blocks_raises(self):
        cfg = CalibrationConfig.model_validate({})
        with pytest.raises(ValueError, match="objective_blocks is empty"):
            build_objective_from_config(cfg)

    def test_missing_observed_values_raises(self):
        cfg = CalibrationConfig.model_validate(
            {
                "outputs": {"head_A": {"variable": "head", "support": "cell", "row": 0, "col": 0}},
                "objective_blocks": [{"name": "b", "metric": "rmse", "uses_outputs": ["head_A"]}],
            }
        )
        with pytest.raises(ValueError, match="no observed values"):
            build_objective_from_config(cfg)

    def test_missing_simulated_output_returns_inf(self):
        obj = build_objective_from_config(_cfg_one_block())
        result = obj.evaluate({"other_output": [1.0, 2.0, 3.0]})
        assert math.isinf(result.total)

    def test_mismatched_simulated_length_raises(self):
        obj = build_objective_from_config(_cfg_one_block())
        with pytest.raises(ValueError, match="simulated length 2 does not match observed length 3"):
            obj.evaluate({"head_A": [1.0, 2.0]})


# From test_cli_composite_routing.py
# Composite routing tests targeted at the CLI wiring boundary.
#
# The CLI builds the metric extractor by passing
# ``cfg.outputs or None`` and ``cfg.objective_blocks or None`` so the
# composite path is engaged whenever the user declares them. These tests
# verify that:
#
# - Calling :func:`build_metric_extractor` with the same arguments the CLI
#   would pass yields a callable that returns the composite components when
#   fed simulated values directly via the underlying objective.
# - Calling :func:`build_metric_extractor` with ``cfg.outputs is None``
#   (typical for the bare-minimum TOML) returns the single-metric extractor.


def _empty_ctx():
    return SimpleNamespace(
        setup=SimpleNamespace(cell_mesh=None, domain=None, time_grid=None),
        loaded_data=SimpleNamespace(piezometry=None, hydrometry=None),
        execution=None,
    )


class TestCliWiring:
    def test_cli_args_engage_composite_when_blocks_declared(self):
        cfg = CalibrationConfig.model_validate(
            {
                "method": "grid",
                "variable": "head",
                "outputs": {
                    "head_A": {
                        "variable": "head",
                        "support": "cell",
                        "row": 0,
                        "col": 0,
                        "observed_values": [1.0, 2.0, 3.0],
                    }
                },
                "objective_blocks": [
                    {"name": "head_block", "metric": "rmse", "uses_outputs": ["head_A"]}
                ],
            }
        )
        ctx = _empty_ctx()
        metric_fn = build_metric_extractor(
            cfg.variable,
            cfg.objective,
            ctx,
            outputs=cfg.outputs or None,
            objective_blocks=cfg.objective_blocks or None,
        )
        # The composite path is engaged: it fails on the missing flow run, not
        # on the single-metric branch, which would complain about observations.
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            metric_fn(ctx)

    def test_composite_evaluates_when_simulated_provided(self):
        """End-to-end check: feed simulated values directly into the
        composite (bypassing extraction) and verify the cost matches the
        block metric. This guards against regressions in
        ``build_objective_from_config`` wiring."""
        cfg = _head_cfg(observed=(10.0, 20.0, 30.0), name="b", metric="rmse")
        obj = build_objective_from_config(cfg)
        result = obj.evaluate({"head_A": [12.0, 22.0, 32.0]})
        assert result.total == pytest.approx(2.0)

    def test_cli_args_keep_single_metric_when_no_blocks(self):
        cfg = CalibrationConfig.model_validate(
            {"method": "grid", "variable": "head", "objective": "rmse"}
        )
        ctx = _empty_ctx()
        metric_fn = build_metric_extractor(
            cfg.variable,
            cfg.objective,
            ctx,
            outputs=cfg.outputs or None,
            objective_blocks=cfg.objective_blocks or None,
        )
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            metric_fn(ctx, objective="rmse", variable="head")


# From test_composite_objective.py
# Unit tests for :class:`hydromodpy.calibration.optim.objective.CompositeObjective`.
#
# The new architecture ships a weighted multi-block composite objective as a
# building block users compose when writing their own ``metric_fn``. Each
# block pairs a :class:`ConfigBlockObjective` with a positive weight; weights are
# normalized to sum to 1.0. An optional ``cost_transform`` (``"identity"``,
# ``"log"`` or ``"inverse"``) is applied to each block total before the
# weighted sum is computed.


def test_config_block_refuses_mismatched_output_lengths_even_when_totals_match() -> None:
    """Two outputs individually wrong on length can still sum to a matching total.

    Output "a" has 20 observations against a 30-length simulated series, and
    output "b" has 40 against 30. Concatenated, both sides total 60: a check
    made after concatenation would let this trial through and score a cost.
    """
    observed = {"a": [1.0] * 20, "b": [2.0] * 40}
    sim = {"a": [1.0] * 30, "b": [2.0] * 30}

    block = ConfigBlockObjective(
        name="x", metric="rmse", uses_outputs=["a", "b"], observed_by_output=observed
    )

    with pytest.raises(ValueError) as excinfo:
        block.evaluate(sim)

    message = str(excinfo.value)
    assert "output 'a'" in message
    assert "simulated length 30" in message
    assert "observed length 20" in message


def test_config_block_names_the_offending_output_when_it_is_not_the_first() -> None:
    """The mismatch is on "b", so checking only the first output is not enough.

    With the defect on output index 0, an implementation that checks the first
    output and stops answers exactly like one that checks every output. Three
    outputs, 10/20/40 observed against 10/30/30 simulated, put the mismatch
    where only the second kind of implementation can see it.
    """
    observed = {"a": [1.0] * 10, "b": [2.0] * 20, "c": [3.0] * 40}
    sim = {"a": [1.0] * 10, "b": [2.0] * 30, "c": [3.0] * 30}

    block = ConfigBlockObjective(
        name="x", metric="rmse", uses_outputs=["a", "b", "c"], observed_by_output=observed
    )

    with pytest.raises(ValueError) as excinfo:
        block.evaluate(sim)

    assert "output 'b'" in str(excinfo.value)


def test_config_block_scores_unequal_but_paired_output_lengths() -> None:
    """Outputs need not be the same length as each other, only as their own record."""
    observed = {"a": [1.0, 2.0, 3.0, 4.0], "b": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]}

    block = ConfigBlockObjective(
        name="x", metric="rmse", uses_outputs=["a", "b"], observed_by_output=observed
    )

    assert block.evaluate(dict(observed)).total == 0.0


@pytest.mark.parametrize(
    ("observed", "sim"),
    [({"a": []}, {"a": [1.0, 2.0, 3.0]}), ({"a": [1.0, 2.0, 3.0]}, {"a": []})],
    ids=["no observation", "no simulated value"],
)
def test_a_trial_the_optimizer_used_to_step_over_is_not_turned_into_an_exception(
    observed, sim
) -> None:
    """The length check must not swallow the three soft rejections around it.

    Each of these returned an infinite cost, which a search steps over. Their
    only production caller re-raises anything ``evaluate`` throws as a
    ``RuntimeError``, so a length check placed ahead of them turns a rejected
    trial into an aborted run.
    """
    block = ConfigBlockObjective(
        name="x", metric="rmse", uses_outputs=["a"], observed_by_output=observed
    )

    assert block.evaluate(sim).total == float("inf")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _block__composite_objective(
    station: str, values: np.ndarray, metric: str
) -> ConfigBlockObjective:
    """One block scoring ``metric`` on the output named after ``station``."""
    return ConfigBlockObjective(
        name=station, metric=metric, uses_outputs=[station], observed_by_output={station: values}
    )


def _make_sim(values_by_station: dict[str, np.ndarray]) -> SimulationOutput:
    first = next(iter(values_by_station.values()))
    times = np.arange(first.size, dtype=float)
    stations = tuple(values_by_station.keys())
    return SimulationOutput(
        sim_id="sim-test", stations=stations, times=times, values=values_by_station
    )


# ---------------------------------------------------------------------------
# Core behavior
# ---------------------------------------------------------------------------
def _pair(offset_a: float, offset_b: float, metric: str = "nse", start_b: float = 10.0):
    """Two blocks on stations A and B, each simulated at its observations plus an offset."""
    obs_a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    obs_b = np.arange(5.0) + start_b
    block_a = _block__composite_objective("A", obs_a, metric)
    block_b = _block__composite_objective("B", obs_b, metric)
    return block_a, block_b, _make_sim({"A": obs_a + offset_a, "B": obs_b + offset_b})


def test_equal_weight_composite_two_nse_blocks_returns_mean_cost() -> None:
    """Two equal-weight NSE blocks => total = mean of block NSE costs."""
    block_a, block_b, sim = _pair(0.5, 2.0)
    cost_a = block_a.evaluate(sim).total
    cost_b = block_b.evaluate(sim).total

    out = CompositeObjective([(block_a, 1.0), (block_b, 1.0)]).evaluate(sim)

    assert isinstance(out, ObjectiveValue)
    assert out.total == pytest.approx(0.5 * cost_a + 0.5 * cost_b)
    # Sanity check: different simulation errors => different block costs.
    assert cost_a != cost_b


def test_weighted_composite_reflects_weights() -> None:
    """Weights (0.8, 0.2) shift the total toward the first block."""
    block_a, block_b, sim = _pair(0.1, 5.0, start_b=1.0)
    cost_a = block_a.evaluate(sim).total
    cost_b = block_b.evaluate(sim).total
    assert cost_a < cost_b  # sanity: A fits better

    out = CompositeObjective([(block_a, 0.8), (block_b, 0.2)]).evaluate(sim)

    # Weights already sum to 1.0, so no re-normalization effect.
    assert out.total == pytest.approx(0.8 * cost_a + 0.2 * cost_b)
    # Compare to equal-weight composite: weighted-towards-A must be smaller.
    out_equal = CompositeObjective([(block_a, 1.0), (block_b, 1.0)]).evaluate(sim)
    assert out.total < out_equal.total


def test_unequal_weights_are_normalized_to_sum_one() -> None:
    """Weights (3, 1) normalize to (0.75, 0.25). Result identical to (0.75, 0.25)."""
    block_a, block_b, sim = _pair(0.3, 1.5, "rmse")

    raw_composite = CompositeObjective([(block_a, 3.0), (block_b, 1.0)])
    eq_composite = CompositeObjective([(block_a, 0.75), (block_b, 0.25)])

    assert raw_composite.evaluate(sim).total == pytest.approx(eq_composite.evaluate(sim).total)

    # Normalized weights exposed as tuple summing to 1.0.
    norm_weights = [w for _, w in raw_composite.blocks]
    assert sum(norm_weights) == pytest.approx(1.0)
    assert norm_weights[0] == pytest.approx(0.75)
    assert norm_weights[1] == pytest.approx(0.25)


def test_components_dict_is_merged_from_all_blocks() -> None:
    """Composite components should carry every block's station components."""
    block_a, block_b, sim = _pair(0.5, 2.0)

    out = CompositeObjective([(block_a, 1.0), (block_b, 1.0)]).evaluate(sim)

    # The components of both blocks survive in the merged components dict.
    assert "A.raw_cost" in out.components
    assert "B.raw_cost" in out.components
    # Per-block totals are also surfaced, one per block.
    total_keys = [k for k in out.components if k.endswith(".total")]
    assert len(total_keys) == 2


def test_transform_log_keeps_minimization_order() -> None:
    """``cost_transform="log"`` preserves lower-is-better ordering."""
    # Build two identity-fit blocks (costs near zero after metric).
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    sim_values = obs.copy()

    block = _block__composite_objective("A", obs, "rmse")
    sim = _make_sim({"A": sim_values})

    # Raw (identity) cost with a perfect fit => ~0.
    identity_composite = CompositeObjective([(block, 1.0)], cost_transform="identity")
    identity_total = identity_composite.evaluate(sim).total
    assert identity_total == pytest.approx(0.0, abs=1.0e-12)

    log_composite = CompositeObjective([(block, 1.0)], cost_transform="log")
    log_total = log_composite.evaluate(sim).total
    assert math.isfinite(log_total)

    bad_block = _block__composite_objective("A", obs, "rmse")
    bad_sim = _make_sim({"A": obs + 10.0})
    bad_log_total = (
        CompositeObjective([(bad_block, 1.0)], cost_transform="log").evaluate(bad_sim).total
    )
    assert log_total < bad_log_total


def test_transform_inverse_keeps_minimization_order() -> None:
    """``cost_transform="inverse"`` preserves lower-is-better ordering."""
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    block = _block__composite_objective("A", obs, "rmse")
    sim = _make_sim({"A": obs.copy()})  # perfect fit -> cost ~0

    inverse_composite = CompositeObjective([(block, 1.0)], cost_transform="inverse")
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
    block = _block__composite_objective("A", obs, "nse")
    with pytest.raises(ValueError, match="weight must be finite and > 0"):
        CompositeObjective([(block, 0.0)])
    with pytest.raises(ValueError, match="weight must be finite and > 0"):
        CompositeObjective([(block, -1.0)])


def test_non_finite_weight_raises() -> None:
    obs = np.array([1.0, 2.0, 3.0])
    block = _block__composite_objective("A", obs, "nse")
    with pytest.raises(ValueError, match="weight must be finite and > 0"):
        CompositeObjective([(block, float("nan"))])


def test_unknown_transform_raises() -> None:
    obs = np.array([1.0, 2.0, 3.0])
    block = _block__composite_objective("A", obs, "nse")
    with pytest.raises(ValueError, match="Unknown cost_transform"):
        CompositeObjective([(block, 1.0)], cost_transform="zigzag")


def test_malformed_block_tuple_raises() -> None:
    obs = np.array([1.0, 2.0, 3.0])
    block = _block__composite_objective("A", obs, "nse")
    with pytest.raises(TypeError, match="must be an .*tuple"):
        CompositeObjective([block])  # forgot the weight


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------
def test_composite_has_name_and_evaluate() -> None:
    """CompositeObjective satisfies the Objective Protocol surface."""
    obs = np.array([1.0, 2.0, 3.0])
    block = _block__composite_objective("A", obs, "nse")
    composite = CompositeObjective([(block, 1.0)], name="my_composite")
    assert composite.name == "my_composite"
    assert hasattr(composite, "evaluate")
    assert composite.cost_transform == "identity"


# From test_every_objective_is_a_block.py
# Every trial is scored by blocks, so no objective is left beside them.
#
# ``ScalarObjective`` scored one metric over an ``ObservationSet`` with its own
# station average, its own sign flip and no window, burn-in or sampling step.
# Since decision m10 the one-line form is read as implicit blocks, and nothing
# in the package built one any more: it is gone with the payload it read.


def test_the_package_exports_no_objective_beside_the_blocks() -> None:
    for name in ("ScalarObjective", "ObservationSet"):
        assert name not in vars(calibration).get("__all__", ())
        assert not hasattr(calibration, name)
        assert not hasattr(objective, name)


def test_the_blocks_and_their_sum_remain() -> None:
    assert hasattr(objective, "ConfigBlockObjective")
    assert hasattr(objective, "CompositeObjective")


# From test_log_nse_and_scoring_window.py
# The three things phase 2 of the method needs before it can be declared.
#
# ``nse_log`` as a registered metric, a scoring window written in dates rather
# than in samples.


class TestNseLogRegistration:
    def test_nse_log_is_registered_and_higher_is_better(self) -> None:
        assert METRICS["nse_log"] is log_nse
        assert "nse_log" in HIGHER_IS_BETTER

    def test_a_block_can_declare_it(self) -> None:
        cfg = _q_cfg()
        assert cfg.objective_blocks[0].metric == "nse_log"

    def test_a_perfect_simulation_costs_zero(self) -> None:
        # nse_log is higher-is-better, so the cost is 1 - value and a perfect
        # match must land on zero, not on one.
        cfg = _q_cfg()
        objective = build_objective_from_config(cfg)
        assert objective.evaluate({"q": [1.0, 2.0, 3.0, 4.0]}).total == pytest.approx(0.0)


class TestNegativeDischargeClipping:
    def test_clipping_counts_both_sides(self) -> None:
        sim, obs, n_clipped = clip_negatives(np.array([-1.0, 2.0]), np.array([1.0, -3.0]))
        assert n_clipped == 2
        assert sim.tolist() == [0.0, 2.0]
        assert obs.tolist() == [1.0, 0.0]

    def test_a_clean_series_is_returned_untouched(self) -> None:
        sim, obs, n_clipped = clip_negatives(np.array([1.0, 2.0]), np.array([1.0, 3.0]))
        assert n_clipped == 0
        assert sim.tolist() == [1.0, 2.0]

    def test_the_block_reports_how_many_were_clipped(self) -> None:
        # A reconstructed discharge below a dam with releases can be negative;
        # log_nse would otherwise raise, and clipping in silence would hide a
        # sign error that looks exactly the same.
        cfg = _q_cfg()
        value = build_objective_from_config(cfg).evaluate({"q": [-1.0, 2.0, 3.0, 4.0]})
        assert value.components["b.n_clipped"] == 1.0
        assert np.isfinite(value.total)

    def test_variable_and_objective_clip_before_the_log_and_count(self) -> None:
        # Each simulated stamp closes the day observed one day before it.
        observed = pd.Series([1.0, 2.0, 3.0, 4.0], index=pd.date_range("2020-01-01", periods=4))
        simulated = pd.Series([-1.0, 2.0, 3.0, 4.0], index=pd.date_range("2020-01-02", periods=4))
        cost, components = _score(observed, simulated, "nse_log")
        assert np.isfinite(cost)
        assert components["nse_log@S.n_clipped"] == 1.0


class TestWindowBounds:
    def test_bounds_parse_to_timestamps(self) -> None:
        window = CalibWindow(start="2012-01-01", end="2015-12-31")
        start, end = window_bounds(window)
        assert (start, end) == (pd.Timestamp("2012-01-01"), pd.Timestamp("2015-12-31"))
        assert window_bounds(None) is None

    def test_an_open_bound_stays_open(self) -> None:
        start, end = window_bounds(CalibWindow(start="2012-01-01"))
        assert start == pd.Timestamp("2012-01-01")
        assert end is None

    def test_a_reversed_window_is_refused(self) -> None:
        with pytest.raises(ValueError, match="is after end"):
            CalibWindow(start="2015-01-01", end="2012-01-01")

    def test_a_date_that_is_not_a_date_is_refused(self) -> None:
        with pytest.raises(ValueError, match="is not a date"):
            CalibWindow(start="not-a-date")

    def test_score_drops_the_samples_outside_the_window(self) -> None:
        index = pd.date_range("2020-01-01", periods=4, freq="D")
        observed = pd.Series([1.0, 1.0, 1.0, 1.0], index=index)
        # The first two days are badly simulated, the last two are perfect.
        simulated = pd.Series([9.0, 9.0, 1.0, 1.0], index=index)
        window = (pd.Timestamp("2020-01-03"), None)

        full, _ = _score(observed, simulated, "rmse", variable="head")
        scored, _ = _score(observed, simulated, "rmse", variable="head", window=window)

        assert scored == pytest.approx(0.0)
        assert full > scored

    def test_an_empty_window_is_an_error_not_an_empty_score(self) -> None:
        index = pd.date_range("2020-01-01", periods=3, freq="D")
        series = pd.Series([1.0, 2.0, 3.0], index=index)
        with pytest.raises(ValueError, match="share no timestamp inside"):
            _score(
                series,
                series,
                "rmse",
                variable="head",
                window=(pd.Timestamp("2030-01-01"), None),
            )


class TestBlockRouteWindowBounds:
    """A window in dates has nothing to cut on the block route, and says so."""

    @staticmethod
    def _kwargs() -> dict:
        cfg = _q_cfg(metric="rmse")
        return {"outputs": cfg.outputs, "objective_blocks": cfg.objective_blocks}

    def test_a_declared_window_is_refused_and_names_the_block(self) -> None:
        with pytest.raises(ValueError, match="no time axis") as excinfo:
            build_metric_extractor__log_nse(
                None,
                None,
                None,
                window=(pd.Timestamp("2012-01-01"), None),
                **self._kwargs(),
            )
        assert "'b'" in str(excinfo.value)

    def test_an_end_bound_alone_is_refused_too(self) -> None:
        with pytest.raises(ValueError, match="no time axis"):
            build_metric_extractor__log_nse(
                None,
                None,
                None,
                window=(None, pd.Timestamp("2015-12-31")),
                **self._kwargs(),
            )

    def test_an_absent_window_builds(self) -> None:
        assert build_metric_extractor__log_nse(None, None, None, window=None, **self._kwargs())

    def test_a_window_with_two_open_bounds_cuts_nothing_and_builds(self) -> None:
        assert build_metric_extractor__log_nse(
            None, None, None, window=(None, None), **self._kwargs()
        )


class TestDistanceBlock:
    """The pair (D_so, D_os) scored by a block, end to end."""

    @staticmethod
    def _config(metric: str = "distance_gap", **calibration: object) -> CalibrationConfig:
        return CalibrationConfig.model_validate(
            {
                "method": "grid",
                "outputs": {"net": {"support": "network", "map": {"complete": "streams.gpkg"}}},
                "objective_blocks": [{"name": "gap", "metric": metric, "uses_outputs": ["net"]}],
                **calibration,
            }
        )

    def test_the_gap_is_the_absolute_signed_difference(self) -> None:
        assert distance_gap(np.array([300.0, 100.0])) == pytest.approx(200.0)
        assert distance_gap(np.array([100.0, 300.0])) == pytest.approx(200.0)

    def test_the_mean_averages_the_pair(self) -> None:
        assert distance_mean(np.array([300.0, 100.0])) == pytest.approx(200.0)

    def test_a_time_series_is_not_a_pair(self) -> None:
        with pytest.raises(ValueError, match="got 3 value"):
            distance_gap(np.array([1.0, 2.0, 3.0]))

    def test_a_block_scores_the_pair(self) -> None:
        value = build_objective_from_config(self._config()).evaluate({"net": [300.0, 100.0]})
        assert value.total == pytest.approx(200.0)
        assert value.components["gap.n_values"] == 2.0

    def test_the_zero_of_the_cost_is_the_balance(self) -> None:
        value = build_objective_from_config(self._config()).evaluate({"net": [150.0, 150.0]})
        assert value.total == pytest.approx(0.0)

    def test_the_mean_block_scores_the_pair(self) -> None:
        value = build_objective_from_config(self._config("distance_mean")).evaluate(
            {"net": [300.0, 100.0]}
        )
        assert value.total == pytest.approx(200.0)


# From test_normalising_a_dimensionless_cost.py
# Normalizing a cost that has no unit distorts the weighting it was meant to fix.
#
# ``normalize_cost`` divides a block's cost by a reference scale read off the
# observed vector. It exists so that a composite sum does not let the unit decide
# the weighting: an RMSE on heads is in meters, one on discharge in m3/s, and
# adding them raw gives the meters a say the weights never granted.
#
# An efficiency score has no unit to remove. NSE, KGE, nse_log, nse_delta,
# nse_seasonal and the reservoir score are already dimensionless numbers, so
# dividing them by the standard deviation of the observations does not put two
# costs on a common footing: it multiplies one block's weight by a number that
# belongs to its data, silently. Two blocks written with equal weights come out
# unequal, and nothing in the report says by how much.
#
# The network distances have a unit, meters, and no observed vector to take a
# scale from. Their scale is the validity length of the output, which
# ``test_metrics_observable_scoring.py`` covers.


_OBSERVED__normalising_dimensionless = {"q": (1.0, 2.0, 3.0)}


def _block__normalising_dimensionless(metric: str, *, normalize: bool) -> ConfigBlockObjective:
    return ConfigBlockObjective(
        name="b",
        metric=metric,
        uses_outputs=["q"],
        observed_by_output=_OBSERVED__normalising_dimensionless,
        normalize_cost=normalize,
    )


class TestWhichMetricsHaveNoUnit:
    """The list lives with the kernels it describes, not beside them."""

    def test_the_efficiency_scores_are_listed(self) -> None:
        flagged = {name for name, spec in METRIC_SPECS.items() if spec.dimensionless}
        assert {"nse", "kge", "nse_log", "nse_delta", "nse_seasonal", "reservoir"} <= flagged

    def test_a_residual_metric_is_not(self) -> None:
        assert not METRIC_SPECS["rmse"].dimensionless
        assert not METRIC_SPECS["mae"].dimensionless


class TestWhatIsRefused:
    @pytest.mark.parametrize("metric", ["nse", "kge", "nse_log", "reservoir"])
    def test_normalising_an_efficiency_score_is_refused(self, metric: str) -> None:
        with pytest.raises(ValueError, match="normalize_cost"):
            _block__normalising_dimensionless(metric, normalize=True)

    def test_the_refusal_names_the_metric_and_what_to_do(self) -> None:
        with pytest.raises(ValueError) as caught:
            _block__normalising_dimensionless("nse", normalize=True)

        message = str(caught.value)
        assert "nse" in message
        assert "weight" in message

    def test_normalising_a_network_distance_never_reads_an_observed_scale(self) -> None:
        """Its scale is the validity length a trial publishes, not a pair of zeros.

        Without one the trial is refused by name rather than divided by one.
        """
        block = ConfigBlockObjective(
            name="net",
            metric="distance_gap",
            uses_outputs=["net"],
            observed_by_output={"net": (0.0, 0.0)},
            normalize_cost=True,
        )
        with pytest.raises(ValueError, match="validity length"):
            block.evaluate({"net": [120.0, 80.0]})


class TestWhatIsUntouched:
    @pytest.mark.parametrize("metric", ["rmse", "mae"])
    def test_normalising_a_residual_metric_still_works(self, metric: str) -> None:
        assert _block__normalising_dimensionless(metric, normalize=True) is not None

    @pytest.mark.parametrize("metric", ["nse", "kge", "rmse", "distance_gap"])
    def test_leaving_it_off_is_always_fine(self, metric: str) -> None:
        assert (
            ConfigBlockObjective(
                name="b",
                metric=metric,
                uses_outputs=["q"],
                observed_by_output=_OBSERVED__normalising_dimensionless,
                normalize_cost=False,
            )
            is not None
        )


class TestWhereTheRefusalHappens:
    """The reader writes TOML, so the file is where the refusal belongs."""

    def test_the_file_is_refused_when_it_is_read(self) -> None:
        with pytest.raises(ValueError, match="normalize_cost"):
            CalibObjectiveBlockDecl(name="b", metric="nse", uses_outputs=["q"], normalize_cost=True)

    def test_a_residual_block_still_loads(self) -> None:
        block = CalibObjectiveBlockDecl(
            name="b", metric="rmse", uses_outputs=["q"], normalize_cost=True
        )

        assert block.normalize_cost is True


# From test_objective_block_cost_fractions.py
# Each phase reports the fraction of the cost each block actually took.
#
# ``cost_block_fractions`` reads it off the ``<block>.total`` components
# :class:`CompositeObjective` already writes, weighted by the same normalized
# weights the objective used: ``w_i * c_i / sum_j(w_j * c_j)``.
# ``mean_cost_block_fractions`` averages it over several trials, the way
# :func:`hydromodpy.calibration.runners.search.phase_cost_block_fractions`
# averages it over a phase's finished trials.


BLOCKS = [("network", 1.0), ("hydrograph", 3.0)]  # normalized: 0.25 / 0.75


def test_the_fraction_is_the_normalised_weighted_contribution() -> None:
    components = {"network.total": 10.0, "hydrograph.total": 2.0}

    fractions = cost_block_fractions(components, BLOCKS)

    # contributions: 0.25 * 10 = 2.5, 0.75 * 2 = 1.5, sum = 4.0
    assert fractions == pytest.approx({"network": 0.625, "hydrograph": 0.375})
    assert sum(fractions.values()) == pytest.approx(1.0)


def test_the_mean_fraction_averages_exactly_over_the_trials() -> None:
    trials = [
        {"network.total": 10.0, "hydrograph.total": 2.0},  # network 0.625, hydrograph 0.375
        {"network.total": 2.0, "hydrograph.total": 2.0},  # network 0.25, hydrograph 0.75
    ]

    mean, n_trials = mean_cost_block_fractions(BLOCKS, trials)

    assert mean == pytest.approx({"network": 0.4375, "hydrograph": 0.5625})
    assert n_trials == 2


def test_a_trial_missing_a_block_total_is_skipped_from_the_mean() -> None:
    trials = [
        {"network.total": 2.0, "hydrograph.total": 2.0},  # network 0.25, hydrograph 0.75
        {"network.total": 5.0},  # no hydrograph.total: cannot be told apart, skipped
    ]

    mean, n_trials = mean_cost_block_fractions(BLOCKS, trials)

    assert mean == pytest.approx({"network": 0.25, "hydrograph": 0.75})
    assert n_trials == 1


def test_no_computable_trial_returns_none() -> None:
    trials = [{"network.total": 5.0}, None]

    assert mean_cost_block_fractions(BLOCKS, trials) is None


def test_a_single_declared_block_always_takes_the_whole_cost() -> None:
    # No ".total" key needed: a lone block is never wrapped in a CompositeObjective.
    assert cost_block_fractions({"hydrograph.raw_cost": 3.0}, [("hydrograph", 1.0)]) == {
        "hydrograph": 1.0
    }


def test_no_declared_block_gives_no_fraction() -> None:
    assert cost_block_fractions({}, []) is None
    assert mean_cost_block_fractions([], [{}]) is None


def test_weighted_costs_summing_to_zero_give_no_fraction() -> None:
    blocks = [("a", 1.0), ("b", 1.0)]
    components = {"a.total": 5.0, "b.total": -5.0}

    assert cost_block_fractions(components, blocks) is None


def test_a_signed_criterion_reads_a_non_negative_total_and_a_fraction_in_0_1() -> None:
    """``distance_gap`` publishes a signed residual, but ``.total`` already holds
    ``abs(D_so - D_os)``: the cost the composite actually weighted and summed.
    """
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
    fractions = cost_block_fractions(value.components, [("network", 1.0), ("hydrograph", 3.0)])

    assert value.components["network.total"] == pytest.approx(3.0)
    weighted_network = 0.25 * value.components["network.total"]
    weighted_hydrograph = 0.75 * value.components["hydrograph.total"]
    denom = weighted_network + weighted_hydrograph
    assert denom == pytest.approx(value.total)
    assert fractions == pytest.approx(
        {"network": weighted_network / denom, "hydrograph": weighted_hydrograph / denom}
    )
    assert all(0.0 <= fraction <= 1.0 for fraction in fractions.values())


def _result(trial_id: int, cost: float, components: dict | None, **kwargs) -> EvaluationResult:
    return EvaluationResult(
        trial_id=trial_id,
        sim_id=None,
        cost=cost,
        components=components,
        status=kwargs.get("status", "completed"),
    )


def _cfg(blocks: list[tuple[str, float]]) -> SimpleNamespace:
    return SimpleNamespace(
        objective_blocks=[SimpleNamespace(name=name, weight=weight) for name, weight in blocks]
    )


def test_the_phase_report_helper_reads_mean_and_best_off_the_history() -> None:
    cfg = _cfg(BLOCKS)
    history = [
        _result(1, 4.0, {"network.total": 10.0, "hydrograph.total": 2.0}),
        _result(2, 2.0, {"network.total": 2.0, "hydrograph.total": 2.0}),
    ]
    best = history[1]

    fractions = phase_cost_block_fractions(cfg, history, best)

    assert fractions["mean_n_trials"] == 2
    assert fractions["mean"] == pytest.approx({"network": 0.4375, "hydrograph": 0.5625})
    assert fractions["best"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})


def test_a_failed_trial_does_not_enter_the_mean() -> None:
    cfg = _cfg(BLOCKS)
    history = [
        _result(1, 2.0, {"network.total": 2.0, "hydrograph.total": 2.0}),
        _result(
            2, float("inf"), {"network.total": 999.0, "hydrograph.total": 999.0}, status="failed"
        ),
    ]
    best = history[0]

    fractions = phase_cost_block_fractions(cfg, history, best)

    assert fractions["mean_n_trials"] == 1
    assert fractions["mean"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})


def test_no_declared_blocks_gives_no_report_entry() -> None:
    cfg = _cfg([])
    history = [_result(1, 0.5, {"whatever.total": 1.0})]

    assert phase_cost_block_fractions(cfg, history, history[0]) is None


def _seed_trials(tmp_path, trials: list[tuple[str, float, dict | None]]) -> CalibrationPersistence:
    """Journal one session with the given (status, cost, metrics) trials."""
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


class TestReusedPhase:
    """``_reused_phase_cost_block_fractions`` reads a reused phase's own persisted trials."""

    def test_recomputes_the_fractions_from_the_persisted_metrics(self, tmp_path) -> None:
        persistence = _seed_trials(
            tmp_path,
            [
                ("completed", 4.0, {"network.total": 10.0, "hydrograph.total": 2.0}),
                ("completed", 2.0, {"network.total": 2.0, "hydrograph.total": 2.0}),
            ],
        )
        fractions, note = _reused_phase_cost_block_fractions(_cfg(BLOCKS), persistence, "main")

        assert note is None
        assert fractions["mean_n_trials"] == 2
        assert fractions["mean"] == pytest.approx({"network": 0.4375, "hydrograph": 0.5625})
        # trial 2 (cost 2.0) is the best: network 0.25, hydrograph 0.75
        assert fractions["best"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})

    def test_a_crashed_persisted_trial_does_not_enter_the_mean(self, tmp_path) -> None:
        persistence = _seed_trials(
            tmp_path,
            [
                ("completed", 2.0, {"network.total": 2.0, "hydrograph.total": 2.0}),
                # The journal accepts only finite lifecycle states; a live run never
                # journals "failed" either (cli_runner.py remaps it to "crashed" first).
                ("crashed", float("inf"), {"network.total": 999.0, "hydrograph.total": 999.0}),
            ],
        )
        fractions, note = _reused_phase_cost_block_fractions(_cfg(BLOCKS), persistence, "main")

        assert note is None
        assert fractions["mean_n_trials"] == 1
        assert fractions["mean"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})

    def test_no_persisted_components_gives_an_absent_note_not_a_fraction(self, tmp_path) -> None:
        persistence = _seed_trials(tmp_path, [("completed", 1.0, None)])
        fractions, note = _reused_phase_cost_block_fractions(_cfg(BLOCKS), persistence, "main")

        assert fractions is None
        assert note is not None
        assert "not recomputed" in note

    def test_fewer_than_two_blocks_reports_nothing_without_touching_the_journal(self) -> None:
        fractions, note = _reused_phase_cost_block_fractions(
            _cfg([("hydrograph", 1.0)]), None, "unused"
        )

        assert fractions is None
        assert note is None


# From test_score_diagnosis.py
# A metric left undefined has to say what about its series made it so.
#
# An infinite cost sends the reader looking at the metric, which is almost never
# where the problem is. Three different causes produce it, and they call for
# three different answers: a constant record, a non-finite sample that survived
# the alignment, and a genuine numerical blow-up. The trial fails on the
# infinite cost; the block says why in the log, once.


INDEX = pd.date_range("2001-01-01", periods=12, freq="MS")

# A monthly run stamps each month at its end, the record at its start.
SIM_INDEX = pd.date_range("2001-02-01", periods=12, freq="MS")


def _score__score_diagnosis(observed_values, simulated_values, metric: str) -> float:
    scorer = StationBlockScorer(
        "discharge",
        metric,
        [ObservedSeries("G", "discharge", pd.Series(np.asarray(observed_values), index=INDEX))],
    )
    cost, _ = scorer.score(
        {"G": ObservableResult("G", np.asarray(simulated_values, dtype=float), "-", SIM_INDEX)}
    )
    return cost


def test_a_constant_record_names_itself(caplog) -> None:
    # Every efficiency divides by the spread of the observations, so a flat
    # record is undefined however good the simulation is.
    with caplog.at_level("WARNING"):
        cost = _score__score_diagnosis(np.full(12, 2.5), np.linspace(2.0, 3.0, 12), "nse")

    assert cost == float("inf")
    said = [record.getMessage() for record in caplog.records if "all 2.5" in record.getMessage()]
    assert len(said) == 1
    assert "divides by their spread" in said[0]
    assert "12 observed samples" in said[0]


def test_a_healthy_pair_scores_without_a_diagnosis(caplog) -> None:
    observed = [1.0, 1.4, 2.2, 3.1, 2.0, 1.5, 1.2, 1.0, 0.9, 1.1, 1.6, 2.4]

    with caplog.at_level("WARNING"):
        cost = _score__score_diagnosis(observed, np.asarray(observed) * 1.3, "nse_log")

    assert np.isfinite(cost)
    assert not [record for record in caplog.records if "undefined" in record.getMessage()]


def test_a_non_finite_sample_is_counted_on_the_side_it_came_from() -> None:
    message = non_finite_diagnosis(np.array([1.0, np.nan, 3.0]), np.array([1.0, 2.0, np.inf]))

    assert "1 of 3 observed" in message
    assert "1 of 3 simulated" in message


def test_the_fallback_reports_both_ranges() -> None:
    # A metric can go non-finite without either cause above; the message then
    # hands the reader the two ranges rather than nothing.
    message = non_finite_diagnosis(np.array([1.0, 2.0, 3.0]), np.array([4.0, 5.0, 6.0]))

    assert "3 sample(s) scored" in message
    assert "[1, 3]" in message
    assert "[4, 6]" in message


# From test_search_space_sampling_and_cost_transform_are_three_words.py
# ``search_space``, ``sampling`` and ``cost_transform`` each name one thing.
#
# ``transform`` named two unrelated maps: the space a search walks a parameter in
# (``log``, ``logit``) and the function applied to a block's cost before its
# weight. ``prior`` named a probability law that a search without a Bayesian
# reading only uses to draw starting points. Now the parameter says
# ``search_space`` and ``sampling``, the block says ``cost_transform``, and the
# engine's own vocabulary follows. A key renamed is refused with the new name and
# the way to the doctor of a 2.0.x release, which rewrites the file, and the
# ``Calibrable`` metadata a field carries uses the same words.


PROTOCOL = "matching_hydrographic_network"


def _parameter(**fields_: Any) -> CalibParameterDecl:
    return CalibParameterDecl.model_validate({"bounds": [1e-7, 1e-3], **fields_})


def _block__search_space(**fields_: Any) -> CalibObjectiveBlockDecl:
    return CalibObjectiveBlockDecl.model_validate(
        {"name": "q", "metric": "rmse", "uses_outputs": ["q"], **fields_}
    )


# -- the file ----------------------------------------------------------------
def test_a_parameter_names_its_search_space_and_its_sampling() -> None:
    declared = _parameter(search_space="log", sampling="log_uniform")

    assert (declared.search_space, declared.sampling) == ("log", "log_uniform")
    assert (_parameter().search_space, _parameter().sampling) == ("identity", "uniform")
    assert "transform" not in CalibParameterDecl.model_fields
    assert "prior" not in CalibParameterDecl.model_fields


def test_a_block_names_its_cost_transform() -> None:
    assert _block__search_space(cost_transform="log").cost_transform == "log"
    assert _block__search_space().cost_transform == "identity"
    assert "transform" not in CalibObjectiveBlockDecl.model_fields


@pytest.mark.parametrize(
    ("build", "new"),
    [
        (lambda: _parameter(transform="log"), "'search_space'"),
        (lambda: _parameter(prior="uniform"), "'sampling'"),
        (lambda: _block__search_space(transform="log"), "'cost_transform'"),
    ],
)
def test_the_old_word_is_refused_with_the_name_that_replaces_it(build: Any, new: str) -> None:
    with pytest.raises(ValidationError, match="is not accepted any more: renamed") as refused:
        build()

    assert new in str(refused.value)
    assert "hmp doctor --fix-config" in str(refused.value)


def test_a_parameter_declared_in_a_file_reads_the_new_words() -> None:
    section = CalibrationConfig.model_validate(
        {
            "parameters": {
                "K": {"bounds": [1e-7, 1e-3], "search_space": "log", "sampling": "normal"}
            },
            "objective_blocks": [
                {"name": "q", "metric": "rmse", "uses_outputs": ["q"], "cost_transform": "inverse"}
            ],
            "outputs": {
                "q": {
                    "support": "point",
                    "x": 1.0,
                    "y": 2.0,
                    "variable": "discharge",
                    "observed_values": [1.0, 2.0],
                }
            },
        }
    )

    assert section.parameters["K"].search_space == "log"
    assert section.parameters["K"].sampling == "normal"
    assert section.objective_blocks[0].cost_transform == "inverse"


# -- the engine --------------------------------------------------------------
def test_a_resolved_dimension_carries_the_new_words() -> None:
    names = {field.name for field in fields(CalibParameter)}

    assert {"search_space", "sampling"} <= names
    assert not {"transform", "prior"} & names
    parameter = CalibParameter("K", 1e-6, 1e-3, search_space="log", sampling="log_uniform")
    assert parameter.lower_transformed == pytest.approx(-6.0)
    assert parameter.to_physical(-5.0) == pytest.approx(1e-5)


def test_the_space_is_built_from_the_new_keys_of_a_declaration() -> None:
    space = ParameterSpace.from_toml_mapping(
        {
            "K": {
                "bounds": [1e-6, 1e-3],
                "search_space": "log",
                "sampling": "log_uniform",
                "target": "flow.param.K.field.value",
            }
        }
    )

    (parameter,) = list(space)
    assert (parameter.search_space, parameter.sampling) == ("log", "log_uniform")
    declared = space.describe_values({"K": 1e-4})["K"]
    assert (declared["search_space"], declared["sampling"]) == ("log", "log_uniform")
    assert "transform" not in declared and "prior" not in declared


def test_a_block_cost_is_transformed_by_its_cost_transform() -> None:
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


def test_the_engine_traits_name_the_search_space_a_stopping_rule_needs() -> None:
    names = {field.name for field in fields(EngineTraits)}

    assert "required_search_space" in names
    assert "required_transform" not in names


# -- what a field declares ---------------------------------------------------
def test_a_field_declares_its_search_space_and_its_sampling() -> None:
    declared = Calibrable(bounds=(1e-7, 1e-2), search_space="log", sampling="log_uniform")

    assert (declared.search_space, declared.sampling) == ("log", "log_uniform")
    record = declared.to_dict()
    assert (record["search_space"], record["sampling"]) == ("log", "log_uniform")
    assert "transform" not in record and "prior" not in record
    with pytest.raises(TypeError):
        Calibrable(transform="log")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        Calibrable(prior="uniform")  # type: ignore[call-arg]


def test_the_hydraulic_conductivity_declares_a_log_search() -> None:
    extra = FieldHomogeneousSection.model_fields["value"].json_schema_extra
    declared = extra["calibrable"]  # type: ignore[index]

    assert (declared.search_space, declared.sampling) == ("log", "log_uniform")


def test_the_documentation_catalogue_prints_the_new_words() -> None:
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


# -- a run sealed by a pre-release ---------------------------------------------
def test_a_frozen_run_with_the_old_words_is_refused_with_the_way_out(tmp_path: Path) -> None:
    project = _project(tmp_path)
    toml = project / "project.toml"
    toml.write_text(
        PROJECT.replace(
            "[calibration.parameters.K]\nbounds = [1e-7, 1e-3]",
            '[calibration.parameters.K]\nbounds = [1e-7, 1e-3]\nsearch_space = "log"'
            '\nsampling = "log_uniform"',
        ),
        encoding="utf-8",
    )
    cfg = HydroModPyConfig.from_toml(toml)
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    frozen = portable_config_document(cfg, run_dir, project)
    old = re.sub(r"^search_space = ", "transform = ", frozen, flags=re.MULTILINE)
    old = re.sub(r"^sampling = ", "prior = ", old, flags=re.MULTILINE)
    old = re.sub(r"^cost_transform = ", "transform = ", old, flags=re.MULTILINE)
    assert old != frozen
    assert "search_space" not in old and "sampling" not in old
    sealed = run_dir / "config.toml"
    sealed.write_text(old, encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="written by a pre-release of 2.0") as refused:
        HydroModPyConfig.from_toml(sealed)

    told = str(refused.value)
    assert "calibration.parameters.K.transform" in told
    assert "calibration.parameters.K.prior" in told
    assert 'pip install "hydromodpy~=2.0.0"' in told


# From test_the_station_costs_are_averaged_not_pooled.py
# One efficiency per station, then the weighted mean of the costs.
#
# A composite of one block per output (block weights) must agree with the
# arithmetic written out; ``variable`` + ``objective`` is read as exactly such a
# composite, at equal weights. A block over both outputs is the pooled
# computation the configuration no longer lets an efficiency use; it is kept here
# to show it is another number.


OBSERVED = {
    "a": np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
    "b": np.array([100.0, 200.0, 300.0, 400.0, 500.0]),
}
SIMULATED = {
    "a": np.array([5.0, 4.0, 3.0, 2.0, 1.0]),
    "b": np.array([110.0, 190.0, 310.0, 390.0, 505.0]),
}


def _nse(simulated: np.ndarray, observed: np.ndarray) -> float:
    return 1.0 - float(
        np.sum((simulated - observed) ** 2) / np.sum((observed - observed.mean()) ** 2)
    )


def _simulation() -> SimulationOutput:
    return SimulationOutput(sim_id="s", stations=("a", "b"), times=np.arange(5.0), values=SIMULATED)


def _by_hand(weights: dict[str, float]) -> float:
    costs = {name: 1.0 - _nse(SIMULATED[name], OBSERVED[name]) for name in OBSERVED}
    return sum(weights[n] * costs[n] for n in costs) / sum(weights.values())


@pytest.mark.parametrize("weights", [{"a": 1.0, "b": 1.0}, {"a": 2.0, "b": 1.0}])
def test_one_block_per_output_gives_the_same_weighted_mean(weights: dict[str, float]) -> None:
    blocks = [
        (
            ConfigBlockObjective(
                name=name,
                metric="nse",
                uses_outputs=[name],
                observed_by_output={name: OBSERVED[name]},
            ),
            weights[name],
        )
        for name in ("a", "b")
    ]

    value = CompositeObjective(blocks).evaluate(_simulation())

    assert value.total == pytest.approx(_by_hand(weights))


def test_the_pool_of_both_outputs_is_another_number() -> None:
    pooled = ConfigBlockObjective(
        name="both", metric="nse", uses_outputs=["a", "b"], observed_by_output=OBSERVED
    ).evaluate(_simulation())

    assert pooled.total != pytest.approx(_by_hand({"a": 1.0, "b": 1.0}), abs=0.1)


# --------------------------------------------------------------------------- #
# What the objective layer reads, refuses and names
# --------------------------------------------------------------------------- #
class _Returns:
    def __init__(self, out, name="block") -> None:
        self.out, self.name = out, name

    def evaluate(self, sim):
        return self.out


@pytest.mark.parametrize(
    ("out", "total", "components"),
    [
        (2, 2.0, {}),
        ({"total": 3.0, "a": 1}, 3.0, {"a": 1.0}),
        ({"value": 4.0}, 4.0, {}),
        ({"a": 1.0}, math.inf, {"a": 1.0}),
    ],
    ids=["int", "total", "value", "no-total"],
)
def test_a_user_objective_may_answer_with_a_number_or_a_mapping(out, total, components) -> None:
    value = objective.evaluate_objective(_Returns(out), {})

    assert (value.total, value.components) == (total, components)


def test_an_objective_answering_with_anything_else_is_refused() -> None:
    with pytest.raises(TypeError, match="Unsupported Objective return type"):
        objective.evaluate_objective(_Returns("fast"), {})


@pytest.mark.parametrize(
    ("transform", "cost", "match"),
    [("log", -2.0, "cost \\+ epsilon > 0"), ("inverse", -1e-6, "cost \\+ epsilon != 0")],
)
def test_a_cost_transform_refuses_a_cost_it_cannot_take(transform, cost, match) -> None:
    with pytest.raises(ValueError, match=match):
        objective._TRANSFORMS[transform](cost)


def test_a_composite_refuses_a_block_that_cannot_evaluate() -> None:
    with pytest.raises(TypeError, match="Block 0: first element must implement .evaluate"):
        CompositeObjective([(object(), 1.0)])


def test_two_blocks_of_one_name_keep_their_totals_and_components_apart() -> None:
    composite = CompositeObjective(
        [
            (_Returns({"total": 1.0, "n": 5.0}, name="nse"), 1.0),
            (_Returns({"total": 3.0, "n": 7.0}, name="nse"), 1.0),
            (_Returns({"total": 5.0, "n": 9.0}, name="nse"), 2.0),
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


def test_block_fractions_have_no_answer_when_the_weights_sum_to_zero() -> None:
    components = {"a.total": 1.0, "b.total": 1.0}

    assert cost_block_fractions(components, [("a", 0.0), ("b", 0.0)]) is None


def test_an_empty_record_is_said_to_have_scored_no_sample() -> None:
    assert non_finite_diagnosis([], []) == "No sample was scored."


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"metric": "no_such_metric"}, "unknown metric 'no_such_metric'"),
        ({"uses_outputs": []}, "uses_outputs must not be empty"),
    ],
)
def test_a_block_that_names_no_metric_or_no_output_is_refused(kwargs, match) -> None:
    arguments = {"name": "b", "metric": "rmse", "uses_outputs": ["q"], "observed_by_output": {}}

    with pytest.raises(ValueError, match=match):
        ConfigBlockObjective(**{**arguments, **kwargs})


def test_a_block_names_its_metric_and_its_outputs() -> None:
    block = _block(np.array([1.0, 2.0]))

    assert (block.metric, block.uses_outputs) == ("rmse", ("q",))


@pytest.mark.parametrize(
    ("scales", "total", "match"),
    [
        ({"net": [100.0, 100.0]}, 2.0, None),
        ({}, None, "published none"),
        ({"net": [100.0]}, None, "published 1 for 2 values"),
        ({"net": [0.0, 100.0]}, None, "divided by a positive length"),
    ],
)
def test_distances_are_divided_by_the_validity_length_the_trial_published(
    scales, total, match
) -> None:
    block = ConfigBlockObjective(
        name="gap",
        metric="distance_gap",
        uses_outputs=["net"],
        observed_by_output={},
        normalize_cost=True,
        distance_scales=scales,
    )

    if match is None:
        assert block.evaluate({"net": [300.0, 100.0]}).total == pytest.approx(total)
    else:
        with pytest.raises(ValueError, match=match):
            block.evaluate({"net": [300.0, 100.0]})


def test_a_block_with_an_undefined_cost_explains_it_once(caplog) -> None:
    block = ConfigBlockObjective(
        name="q",
        metric="nse",
        uses_outputs=["q"],
        observed_by_output={"q": np.ones(4)},
    )

    with caplog.at_level(logging.WARNING):
        first = block.evaluate({"q": np.arange(4.0)})
        block.evaluate({"q": np.arange(4.0)})

    assert first.total == math.inf
    assert sum("is undefined on this trial" in m for m in caplog.messages) == 1
