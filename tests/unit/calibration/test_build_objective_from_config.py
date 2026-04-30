"""Tests for :func:`hydromodpy.calibration.objective.build_objective_from_config`.

Covers Phase 3 of the calibration integration:

- One-block config returns a single :class:`ConfigBlockObjective`.
- Multi-block config returns a :class:`CompositeObjective` whose total is
  the weighted sum of each block's transformed cost.
- ``normalize_cost`` divides the block cost by a reference scale.
- Per-block ``transform`` (identity / log / inverse) is applied before
  weighting.
- Missing simulated values fail loudly.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibOutputDecl,
    CalibrationConfig,
)
from hydromodpy.calibration.objective import (
    CompositeObjective,
    ConfigBlockObjective,
    ObjectiveValue,
    build_objective_from_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
                    "observed_values": [1.0, 2.0, 3.0],
                }
            },
            "objective_blocks": [
                {
                    "name": "rmse_head",
                    "metric": "rmse",
                    "weight": 1.0,
                    "uses_outputs": ["head_A"],
                }
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
                {
                    "name": "head_block",
                    "metric": "rmse",
                    "weight": 2.0,
                    "uses_outputs": ["head_A"],
                },
                {
                    "name": "discharge_block",
                    "metric": "rmse",
                    "weight": 1.0,
                    "uses_outputs": ["outlet"],
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
        cfg = CalibrationConfig.model_validate(
            {
                "outputs": {
                    "head_A": {
                        "variable": "head",
                        "support": "cell",
                        "observed_values": [1.0, 2.0, 3.0],
                    }
                },
                "objective_blocks": [
                    {
                        "name": "nse_head",
                        "metric": "nse",
                        "uses_outputs": ["head_A"],
                    }
                ],
            }
        )
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
        result = obj.evaluate(
            _SimStub(
                {
                    "head_A": [1.0, 2.0, 3.0],
                    "outlet": [15.0, 25.0, 35.0],
                }
            )
        )
        # weights [2.0, 1.0] normalised to [2/3, 1/3]
        expected = (2.0 / 3.0) * 0.0 + (1.0 / 3.0) * 5.0
        assert result.total == pytest.approx(expected)


class TestNormalizeCost:
    def test_normalize_divides_by_observed_std(self):
        cfg = CalibrationConfig.model_validate(
            {
                "outputs": {
                    "head_A": {
                        "variable": "head",
                        "support": "cell",
                        "observed_values": [1.0, 2.0, 3.0],
                    }
                },
                "objective_blocks": [
                    {
                        "name": "head_block",
                        "metric": "rmse",
                        "uses_outputs": ["head_A"],
                        "normalize_cost": True,
                    }
                ],
            }
        )
        obj = build_objective_from_config(cfg)
        # observed std = std([1,2,3]) = sqrt(2/3) ≈ 0.8165
        # simulated +0.5 everywhere → raw RMSE = 0.5
        simulated = [1.5, 2.5, 3.5]
        result = obj.evaluate({"head_A": simulated})
        scale = float(np.nanstd(np.array([1.0, 2.0, 3.0])))
        assert result.total == pytest.approx(0.5 / scale)


class TestTransform:
    def test_inverse_transform_flips_zero_cost_into_infinity(self):
        cfg = CalibrationConfig.model_validate(
            {
                "outputs": {
                    "head_A": {
                        "variable": "head",
                        "support": "cell",
                        "observed_values": [1.0, 2.0, 3.0],
                    }
                },
                "objective_blocks": [
                    {
                        "name": "head_block",
                        "metric": "rmse",
                        "uses_outputs": ["head_A"],
                        "transform": "inverse",
                    }
                ],
            }
        )
        obj = build_objective_from_config(cfg)
        # Perfect match → cost 0 → 1/(0 + eps) = 1/eps = large positive
        result = obj.evaluate({"head_A": [1.0, 2.0, 3.0]})
        assert result.total > 1e5

    def test_identity_transform_is_passthrough(self):
        cfg = CalibrationConfig.model_validate(
            {
                "outputs": {
                    "head_A": {
                        "variable": "head",
                        "support": "cell",
                        "observed_values": [1.0, 2.0, 3.0],
                    }
                },
                "objective_blocks": [
                    {
                        "name": "head_block",
                        "metric": "rmse",
                        "uses_outputs": ["head_A"],
                        "transform": "identity",
                    }
                ],
            }
        )
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
                "outputs": {
                    "head_A": {"variable": "head", "support": "cell"},
                },
                "objective_blocks": [
                    {"name": "b", "uses_outputs": ["head_A"]},
                ],
            }
        )
        with pytest.raises(ValueError, match="no observed_values"):
            build_objective_from_config(cfg)

    def test_missing_simulated_output_returns_inf(self):
        obj = build_objective_from_config(_cfg_one_block())
        result = obj.evaluate({"other_output": [1.0, 2.0, 3.0]})
        assert math.isinf(result.total)
